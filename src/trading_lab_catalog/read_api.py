"""Deterministic local read API. No ingestion, execution, network, or write endpoints."""

import functools
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .comparison import REQUIRED, compare
from .models import canonical, fingerprint
from .pagination import decode_cursor, encode_cursor
from .read_models import (
    CaseFilters,
    ExperimentFilters,
    Page,
    ReadFailure,
    ResearchCriteria,
    StrategyFilters,
    json_size,
    public_data,
)
from .read_paths import pinned_catalogue
from .read_queries import Snapshot, read_authorizer
from .schema import VERSION
from .service import joined_cases
from .store import IntegrityError, Store


def endpoint(method):
    @functools.wraps(method)
    def call(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except ReadFailure as exc:
            return self._error(exc.code, exc.reason)
        except IntegrityError:
            return self._error("BLOCKED", "Catalogue identity or journal state requires review")
        except (ValidationError, ValueError, TypeError):
            return self._error("INVALID_QUERY", "Invalid query contract")
        except (OSError, sqlite3.Error) as exc:
            code = getattr(exc, "sqlite_errorcode", None)
            if code == sqlite3.SQLITE_INTERRUPT:
                return self._error("QUERY_LIMIT_EXCEEDED", "Read time budget exceeded")
            if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or isinstance(exc, OSError):
                return self._error("BLOCKED", "Catalogue unavailable for safe reading")
            return self._error("INTEGRITY_ERROR", "Catalogue could not be verified")

    return call


def identity(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 160:
        raise ValueError("Invalid identity")
    return value


def filters_of(model, value):
    if value is None:
        return model()
    if not isinstance(value, (model, dict)):
        raise ValueError("Filters must be a typed contract or a mapping")
    # Frozen Pydantic models can still contain mutated dictionaries, and
    # model_construct bypasses validators. Capture and revalidate every request.
    data = value.model_dump(mode="python", warnings=False) if isinstance(value, model) else value
    return model.model_validate(data)


def clauses(values, mapping):
    result, parameters = [], []
    for name, value in values.items():
        if value is not None:
            result.append(mapping[name] + "=?")
            parameters.append(value)
    return result, parameters


def expression(alias, field):
    return f"json_extract({alias}.payload,'$.{field}')"


class CatalogReader:
    """A new guarded read transaction per request; no raw SQL or mutators exposed."""

    def __init__(
        self,
        path: str | Path,
        *,
        cursor_key: bytes | None = None,
        max_response_bytes: int = 512 * 1024,
        timeout_seconds: float = 5.0,
    ):
        if cursor_key is not None and (not isinstance(cursor_key, bytes) or len(cursor_key) < 32):
            raise ValueError("Cursor key must contain at least 32 bytes")
        if not 1024 <= max_response_bytes <= 2 * 1024 * 1024:
            raise ValueError("Invalid response size limit")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Invalid read time limit")
        self._path = Path(path).absolute()
        self._key = cursor_key if cursor_key is not None else secrets.token_bytes(32)
        self._bytes = max_response_bytes
        self._timeout = timeout_seconds

    @staticmethod
    def _error(code, reason):
        return {
            "api_version": "1.0",
            "status": code,
            "reason": reason,
            "items": [],
            "count": 0,
            "next_cursor": None,
        }

    @contextmanager
    def _snapshot(self):
        with pinned_catalogue(self._path) as object_id:
            with self._read_transaction(object_id) as snapshot:
                yield snapshot

    @contextmanager
    def _read_transaction(self, object_id):
        # Construct on every call so later link/journal substitutions are not ignored.
        try:
            store = Store(self._path)
            store._location()
        except ValueError:
            raise ReadFailure("BLOCKED", "Catalogue location requires review") from None
        with store.connection() as c:
            deadline = time.monotonic() + self._timeout
            c.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            c.set_authorizer(read_authorizer)
            snap = Snapshot(c)
            snap.checkpoint = fingerprint([snap.checkpoint, *object_id])
            snap.deadline = deadline
            yield snap

    def _execute(self, operation, query, work):
        query_id = fingerprint({"operation": operation, "query": query, "api_version": "1.0"})
        with self._snapshot() as snap:
            result = work(snap, query_id)
            response = {
                "api_version": "1.0",
                "status": "OK",
                "schema": VERSION,
                "checkpoint": snap.checkpoint,
                "query_id": query_id,
                "integrity": "SCHEMA_AND_SELECTED_RECORDS_VERIFIED",
                "next_cursor": None,
                **result,
            }
            response["count"] = len(response.get("items", []))
            projected = public_data(response)
            redacted = projected != response
            projected["redaction_policy"] = "AGENT_PUBLIC_V1"
            projected["data_redacted"] = redacted
            response = projected
            if json_size(response) > self._bytes:
                raise ReadFailure("RESPONSE_LIMIT_EXCEEDED", "Response exceeds configured limit")
            return response

    def _page(
        self, snap, query_id, table, page, conditions, parameters, transform=None, post_filter=None
    ):
        conditions, parameters = list(conditions), list(parameters)
        last = None
        if page.cursor:
            cursor = decode_cursor(self._key, page.cursor)
            if set(cursor) != {"checkpoint", "query_id", "last"} or cursor["query_id"] != query_id:
                raise ReadFailure("INVALID_CURSOR", "Cursor query does not match")
            if cursor["checkpoint"] != snap.checkpoint:
                raise ReadFailure("CURSOR_INVALIDATED", "Catalogue changed; restart pagination")
            last = identity(cursor["last"])
        desc = page.sort == "-id"
        found = []
        chunk = min(200, page.page_size + 1)
        while len(found) <= page.page_size:
            if time.monotonic() > snap.deadline:
                raise ReadFailure("QUERY_LIMIT_EXCEEDED", "Read time budget exceeded")
            where = list(conditions)
            args = list(parameters)
            if last is not None:
                where.append("t.id" + ("<?" if desc else ">?"))
                args.append(last)
            sql_where = " WHERE " + " AND ".join(where) if where else ""
            ids = [
                r[0]
                for r in snap.c.execute(
                    f"SELECT t.id FROM {table} t{sql_where} ORDER BY t.id "
                    + ("DESC" if desc else "ASC")
                    + " LIMIT ?",
                    (*args, chunk),
                )
            ]
            if not ids:
                break
            rows = transform(snap, ids) if transform else snap.load(table, ids)
            mapping = {r["id"]: r for r in rows}
            for key in ids:
                row = mapping[key]
                if post_filter is None or post_filter(row):
                    found.append(row)
                    if len(found) > page.page_size:
                        break
            last = ids[-1]
            if len(ids) < chunk:
                break
        items = found[: page.page_size]
        next_cursor = None
        if len(found) > page.page_size:
            if public_data(items[-1]["id"]) != items[-1]["id"]:
                # A MAC is not encryption. Never hide a sensitive identifier in
                # an encoded token while redacting it from the visible record.
                raise ReadFailure("BLOCKED", "Cursor identity requires trusted local review")
            next_cursor = encode_cursor(
                self._key,
                {"query_id": query_id, "checkpoint": snap.checkpoint, "last": items[-1]["id"]},
            )
        return {"items": items, "next_cursor": next_cursor}

    @staticmethod
    def _page_query(filters, page):
        return {"filters": filters, "page_size": page.page_size, "sort": page.sort}

    @staticmethod
    def _case_rows(snap, ids):
        snap.graph(ids)
        return joined_cases(snap)

    @staticmethod
    def _summary(snap, record):
        sid = record["id"]
        versions = snap.load("versions", snap.scoped_ids("versions", "strategy_id", sid))
        n_exp = snap.c.execute(
            "SELECT count(*) FROM experiments e JOIN versions v ON v.id=e.version_id "
            "WHERE v.strategy_id=?",
            (sid,),
        ).fetchone()[0]
        run_ids = [
            r[0]
            for r in snap.c.execute(
                "SELECT r.id FROM runs r JOIN experiments e ON e.id=r.experiment_id "
                "JOIN versions v ON v.id=e.version_id "
                "WHERE v.strategy_id=? ORDER BY r.id LIMIT 201",
                (sid,),
            )
        ]
        runs = snap.load("runs", run_ids)
        decisions = snap.load(
            "research_decisions", snap.scoped_ids("research_decisions", "strategy_id", sid)
        )
        markets = snap.c.execute(
            "SELECT DISTINCT json_extract(e.payload,'$.asset'),"
            "json_extract(e.payload,'$.timeframe') FROM experiments e JOIN versions v "
            "ON v.id=e.version_id WHERE v.strategy_id=? ORDER BY 1,2 LIMIT 201",
            (sid,),
        ).fetchall()
        if len(markets) > 200:
            raise ReadFailure("RESPONSE_LIMIT_EXCEEDED", "Market summary exceeds limit")
        n_cases = snap.c.execute(
            "SELECT count(*) FROM case_results c JOIN runs r ON r.id=c.run_id "
            "JOIN experiments e ON e.id=r.experiment_id JOIN versions v ON v.id=e.version_id "
            "WHERE v.strategy_id=?",
            (sid,),
        ).fetchone()[0]
        research = sorted({d["verdict"] for d in decisions if d["category"] == "RESEARCH"})
        return {
            **record,
            # Schema 1 has no family accreditation contract. Preserve the
            # declaration separately rather than manufacture an audited family.
            "family": None,
            "declared_family": record["family"],
            "family_status": "UNKNOWN" if record["family"] is None else "DECLARED_UNVERIFIED",
            "version_count": len(versions),
            "experiment_count": n_exp,
            "run_count": len(runs),
            "result_count": n_cases,
            "assets_investigated": sorted({m[0] for m in markets}),
            "timeframes_investigated": sorted({m[1] for m in markets}),
            "research_state": research[0]
            if len(research) == 1
            else "UNKNOWN"
            if not research
            else "MULTIPLE_DECISIONS",
            "economic_verdicts": sorted(
                {d["verdict"] for d in decisions if d["category"] == "ECONOMIC"}
            ),
            "stages": {
                "discovered": any(v["metadata"].get("discovered") for v in versions),
                "has_experiments": n_exp > 0,
                "has_runs": bool(runs),
                "has_results": n_cases > 0,
                "has_source_audited_run": any(r["audit_status"] == "SOURCE_AUDITED" for r in runs),
                "economic_validation": "NOT_ASSESSED",
            },
            "effective_trading_authorization": "NOT_ASSESSED",
        }

    @endpoint
    def get_catalog_status(self, *, verify: bool = False) -> dict[str, Any]:
        if not isinstance(verify, bool):
            raise ValueError

        def work(snap, _):
            if verify:
                snap.verify()
            return {
                "items": [
                    {
                        "counts": snap.counts,
                        "verification": "FULL_SQLITE_AND_PAYLOAD" if verify else "SCHEMA_CHECKED",
                    }
                ]
            }

        return self._execute("get_catalog_status", {"verify": verify}, work)

    @endpoint
    def list_strategies(
        self,
        filters: StrategyFilters | dict | None = None,
        *,
        page_size: int = 50,
        cursor: str | None = None,
        sort: str = "id",
    ) -> dict[str, Any]:
        f, page = (
            filters_of(StrategyFilters, filters),
            Page(page_size=page_size, cursor=cursor, sort=sort),
        )
        values = f.model_dump()
        conditions, args = clauses(
            {k: v for k, v in values.items() if k in ("strategy_id", "family")},
            {"strategy_id": "t.id", "family": expression("t", "family")},
        )
        # The pair must have been researched together, not in unrelated experiments.
        market_fields = [key for key in ("asset", "timeframe") if values[key] is not None]
        if market_fields:
            conditions.append(
                "EXISTS(SELECT 1 FROM versions v JOIN experiments e "
                "ON e.version_id=v.id WHERE v.strategy_id=t.id AND "
                + " AND ".join(expression("e", key) + "=?" for key in market_fields)
                + ")"
            )
            args.extend(values[key] for key in market_fields)

        def transform(snap, ids):
            return [self._summary(snap, r) for r in snap.load("strategies", ids)]

        return self._execute(
            "list_strategies",
            self._page_query(values, page),
            lambda s, q: self._page(s, q, "strategies", page, conditions, args, transform),
        )

    @endpoint
    def get_strategy(self, strategy_id: str) -> dict[str, Any]:
        sid = identity(strategy_id)
        return self._execute(
            "get_strategy",
            {"strategy_id": sid},
            lambda s, q: {"items": [self._summary(s, s.require("strategies", sid))]},
        )

    @endpoint
    def list_versions(
        self, strategy_id: str, *, page_size: int = 50, cursor: str | None = None, sort: str = "id"
    ) -> dict[str, Any]:
        sid, page = identity(strategy_id), Page(page_size=page_size, cursor=cursor, sort=sort)

        def work(snap, q):
            snap.require("strategies", sid)
            return self._page(snap, q, "versions", page, ["t.strategy_id=?"], [sid])

        return self._execute("list_versions", self._page_query({"strategy_id": sid}, page), work)

    @staticmethod
    def _experiment_where(f):
        values = f.model_dump()
        conditions, args = [], []
        for key, value in values.items():
            if value is None or key in ("parameters", "definition_fingerprint"):
                continue
            if key == "strategy_id":
                conditions.append(
                    "EXISTS(SELECT 1 FROM versions v WHERE v.id=t.version_id AND v.strategy_id=?)"
                )
            else:
                column = (
                    "t.id"
                    if key == "experiment_id"
                    else ("t.version_id" if key == "version_id" else expression("t", key))
                )
                conditions.append(column + "=?")
            args.append(value)
        return conditions, args

    @endpoint
    def search_experiments(
        self,
        filters: ExperimentFilters | dict | None = None,
        *,
        page_size: int = 50,
        cursor: str | None = None,
        sort: str = "id",
    ) -> dict[str, Any]:
        f, page = (
            filters_of(ExperimentFilters, filters),
            Page(page_size=page_size, cursor=cursor, sort=sort),
        )
        conditions, args = self._experiment_where(f)
        return self._execute(
            "search_experiments",
            self._page_query(f.model_dump(), page),
            lambda s, q: self._page(s, q, "experiments", page, conditions, args),
        )

    @endpoint
    def list_runs(
        self,
        experiment_id: str,
        *,
        status: str | None = None,
        page_size: int = 50,
        cursor: str | None = None,
        sort: str = "id",
    ) -> dict[str, Any]:
        eid, page = identity(experiment_id), Page(page_size=page_size, cursor=cursor, sort=sort)
        state = CaseFilters(status=status).status
        conditions, args = ["t.experiment_id=?"], [eid]
        if state is not None:
            conditions.append(expression("t", "status") + "=?")
            args.append(state)

        def work(s, q):
            s.require("experiments", eid)
            return self._page(s, q, "runs", page, conditions, args)

        return self._execute(
            "list_runs", self._page_query({"experiment_id": eid, "status": state}, page), work
        )

    @endpoint
    def list_case_results(
        self,
        run_id: str,
        filters: CaseFilters | dict | None = None,
        *,
        page_size: int = 50,
        cursor: str | None = None,
        sort: str = "id",
    ) -> dict[str, Any]:
        rid = identity(run_id)
        f, page = (
            filters_of(CaseFilters, filters),
            Page(page_size=page_size, cursor=cursor, sort=sort),
        )
        conditions, args = ["t.run_id=?"], [rid]
        mapping = {
            key: expression("t", key)
            for key in ("segment", "scenario", "period_start_utc", "period_end_utc")
        }
        for key in ("asset", "timeframe", "version_id", "status"):
            mapping[key] = (
                "(SELECT "
                + (
                    "e.version_id"
                    if key == "version_id"
                    else expression("r", "status")
                    if key == "status"
                    else expression("e", key)
                )
                + " FROM runs r JOIN experiments e ON e.id=r.experiment_id WHERE r.id=t.run_id)"
            )
        extra, values = clauses(
            {k: v for k, v in f.model_dump().items() if k != "audit_status"}, mapping
        )
        conditions += extra
        args += values

        def work(s, q):
            s.require("runs", rid)
            return self._page(
                s,
                q,
                "case_results",
                page,
                conditions,
                args,
                self._case_rows,
                None if f.audit_status is None else lambda r: r["audit_status"] == f.audit_status,
            )

        return self._execute(
            "list_case_results", self._page_query({"run_id": rid, **f.model_dump()}, page), work
        )

    @endpoint
    def get_research_decisions(
        self,
        strategy_id: str,
        *,
        category: str | None = None,
        page_size: int = 50,
        cursor: str | None = None,
        sort: str = "id",
    ) -> dict[str, Any]:
        sid, page = identity(strategy_id), Page(page_size=page_size, cursor=cursor, sort=sort)
        if category not in (None, "RESEARCH", "ECONOMIC", "DEMO_ELIGIBILITY", "AUTHORIZATION"):
            raise ValueError
        conditions, args = ["t.strategy_id=?"], [sid]
        if category:
            conditions.append(expression("t", "category") + "=?")
            args.append(category)

        def work(s, q):
            s.require("strategies", sid)
            return self._page(s, q, "research_decisions", page, conditions, args)

        return self._execute(
            "get_research_decisions",
            self._page_query({"strategy_id": sid, "category": category}, page),
            work,
        )

    @endpoint
    def get_run_details(self, run_id: str) -> dict[str, Any]:
        rid = identity(run_id)

        def work(s, _):
            run = s.require("runs", rid)
            experiment = s.require("experiments", run["experiment_id"])
            version = s.require("versions", experiment["version_id"])
            strategy = s.require("strategies", version["strategy_id"])
            cases = s.scoped_ids("case_results", "run_id", rid)
            decisions = s.applicable_decision_ids([strategy["id"]], [version["id"]], [rid])
            return {
                "items": [
                    {
                        "run": run,
                        "experiment": experiment,
                        "version": version,
                        "strategy": strategy,
                        "case_results": self._case_rows(s, cases),
                        "artifacts": s.load("artifacts", s.scoped_ids("artifacts", "run_id", rid)),
                        "decisions": [
                            d
                            for d in s.load("research_decisions", decisions)
                            if d["version_id"] in (None, version["id"])
                            and d["run_id"] in (None, rid)
                        ],
                        "effective_trading_authorization": "NOT_ASSESSED",
                    }
                ]
            }

        return self._execute("get_run_details", {"run_id": rid}, work)

    @endpoint
    def get_evidence_summary(self, run_id: str) -> dict[str, Any]:
        rid = identity(run_id)

        def work(s, _):
            run = s.require("runs", rid)
            artifacts = s.load("artifacts", s.scoped_ids("artifacts", "run_id", rid))
            declared = s.load("runs", [rid], declarations=True)
            raw_artifacts = s.load("artifacts", [a["id"] for a in artifacts], declarations=True)
            raw_cases = s.load(
                "case_results", s.scoped_ids("case_results", "run_id", rid), declarations=True
            )
            accredited = s.accreditations()
            provenance = []
            for table, rows in (
                ("runs", declared),
                ("case_results", raw_cases),
                ("artifacts", raw_artifacts),
            ):
                kind = (
                    "HASH_VERIFIED_artifacts" if table == "artifacts" else "SOURCE_AUDITED_" + table
                )
                for record in rows:
                    digest = fingerprint(record)
                    provenance.append(
                        {
                            "entity_id": record["id"],
                            "record_fingerprint": digest,
                            "accreditation_kind": kind if (kind, digest) in accredited else None,
                        }
                    )
            return {
                "items": [
                    {
                        "run_id": rid,
                        "audit_status": run["audit_status"],
                        "evidence_sha256": run["evidence_sha256"],
                        "artifacts": artifacts,
                        "provenance": provenance,
                        "verification_scope": "PERSISTED_ACCREDITATIONS_NOT_A_NEW_FILE_CHECK",
                        "limitations": [
                            "SOURCE_AUDITED preserves the sealed source audit, not a new audit",
                            "Hashes are integrity references, not trading authorizations",
                        ],
                    }
                ]
            }

        return self._execute("get_evidence_summary", {"run_id": rid}, work)

    @endpoint
    def compare_results(self, case_ids: list[str]) -> dict[str, Any]:
        if not isinstance(case_ids, list) or len(case_ids) > 200:
            raise ValueError
        ids = sorted(identity(key) for key in case_ids)
        if len(ids) != len(set(ids)):
            raise ValueError

        def work(s, _):
            rows = self._case_rows(s, ids)
            if len(rows) != len(ids):
                raise ReadFailure("NOT_FOUND", "Compared case was not found")
            result = compare(rows)
            limitations = []
            if any(r["holdout"] != "UNOBSERVED" for r in rows):
                limitations.append("Holdout consumed or unknown; retrospective evidence")
            if any(r["trades"] < 30 for r in rows):
                limitations.append("Small trade samples")
            if any(r["audit_status"] != "SOURCE_AUDITED" for r in rows):
                limitations.append("Evidence is not source-audited")
            differences = [
                key for key in REQUIRED if len({canonical(r.get(key)) for r in rows}) > 1
            ]
            return {
                "items": [
                    {
                        "case_ids": ids,
                        "comparison_status": result["status"],
                        "reasons": result["reasons"],
                        "condition_differences": differences,
                        "limitations": limitations,
                        "cases": rows,
                        "winner": None,
                    }
                ]
            }

        return self._execute("compare_results", {"case_ids": ids}, work)

    @endpoint
    def find_existing_research(
        self,
        criteria: ResearchCriteria | dict | None = None,
        *,
        page_size: int = 50,
        cursor: str | None = None,
        sort: str = "id",
    ) -> dict[str, Any]:
        f, page = (
            filters_of(ResearchCriteria, criteria),
            Page(page_size=page_size, cursor=cursor, sort=sort),
        )
        conditions, args = self._experiment_where(f)

        def work(s, q):
            if f.definition_fingerprint is not None:

                def definition(raw):
                    from .verification import parse

                    return fingerprint(parse(raw))

                s.c.create_function("catalogue_definition", 1, definition, deterministic=True)
                conditions.append("catalogue_definition(json_remove(t.payload,'$.id'))=?")
                args.append(f.definition_fingerprint)
            result = self._page(s, q, "experiments", page, conditions, args)
            specified = any(v is not None for v in f.model_dump().values())
            kind = (
                "UNKNOWN"
                if not specified
                else "NO_MATCH"
                if not result["items"]
                else "EXACT_MATCH"
                if f.experiment_id or f.definition_fingerprint
                else "RELATED_CANDIDATE"
            )
            result["match_status"] = kind
            result["limitations"] = [
                "RELATED_CANDIDATE is an explicit partial match, not scientific equivalence"
            ]
            return result

        return self._execute("find_existing_research", self._page_query(f.model_dump(), page), work)

    def for_profile(self, profile: str):
        return QueryProfile(self, profile)


PROFILES = {
    "researcher": (
        "list_strategies",
        "get_strategy",
        "search_experiments",
        "find_existing_research",
        "get_run_details",
        "list_case_results",
        "get_research_decisions",
    ),
    "designer": (
        "list_strategies",
        "get_strategy",
        "list_versions",
        "search_experiments",
        "find_existing_research",
    ),
    "auditor": (
        "get_catalog_status",
        "list_runs",
        "get_run_details",
        "list_case_results",
        "get_evidence_summary",
        "get_research_decisions",
        "compare_results",
    ),
    "coordinator": (
        "get_catalog_status",
        "list_strategies",
        "get_strategy",
        "list_versions",
        "search_experiments",
        "list_runs",
        "get_run_details",
        "list_case_results",
        "get_evidence_summary",
        "get_research_decisions",
        "compare_results",
        "find_existing_research",
    ),
}


class QueryProfile:
    """A deterministic method allowlist; no agent, prompt, scheduler, or model."""

    def __init__(self, reader: CatalogReader, profile: str):
        if profile not in PROFILES:
            raise ValueError("Unknown query profile")
        self._reader, self._profile = reader, profile

    def query(self, operation: str, **arguments) -> dict[str, Any]:
        if operation not in PROFILES[self._profile]:
            return CatalogReader._error("INVALID_QUERY", "Operation is not in this read profile")
        return getattr(self._reader, operation)(**arguments)
