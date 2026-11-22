"""Bounded pre-query adapter. Only the existing researcher profile is exposed here."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from trading_lab_catalog.read_api import CatalogReader
from trading_lab_catalog.read_models import public_data
from trading_lab_catalog.verification import sha
from trading_lab_orchestration.contracts import canonical

from .models import (
    ID,
    INPUT_LIMIT,
    CatalogRef,
    Contract,
    ResearchRequest,
    Text,
    Texts,
    UTCText,
    decode,
    ordered,
)


class ResearchError(ValueError):
    """Fixed public diagnostic code; no private exception message is disclosed."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ContextLimits(Contract):
    max_bytes: int = Field(default=INPUT_LIMIT, ge=1024, le=INPUT_LIMIT)
    page_size: int = Field(default=20, ge=1, le=50)
    max_pages: int = Field(default=8, ge=1, le=20)
    max_queries: int = Field(default=80, ge=1, le=128)


class SourceDocument(Contract):
    """Host-captured synthetic bytes, not a locator or a sealed-source accreditation."""

    reference_id: ID
    kind: Text
    content: Annotated[bytes, Field(min_length=1, max_length=16 * 1024)]


class Statistics(Contract):
    calculation_version: Text
    period_start_utc: UTCText
    period_end_utc: UTCText
    sample_size: int = Field(ge=1)
    searches_count: Annotated[int, Field(ge=0)] | None
    exclusions: Texts
    limitations: Texts

    @model_validator(mode="after")
    def period(self):
        ordered(self.period_start_utc, self.period_end_utc)
        return self


def source_context(request: ResearchRequest, documents: tuple[SourceDocument, ...]) -> list[dict]:
    if type(documents) is not tuple or any(type(d) is not SourceDocument for d in documents):
        raise ResearchError("SOURCE_INVALID")
    supplied = {d.reference_id: d for d in documents}
    if len(supplied) != len(documents) or set(supplied) != {
        r.reference_id for r in request.source_refs
    }:
        raise ResearchError("SOURCE_MISSING")
    result = []
    for ref in request.source_refs:
        doc = SourceDocument.model_validate(supplied[ref.reference_id].model_dump())
        hashed = sha(doc.content)
        if doc.kind != ref.kind or (ref.sha256 is not None and ref.sha256 != hashed):
            raise ResearchError("SOURCE_HASH_MISMATCH")
        if ref.verification == "SOURCE_AUDITED":
            # This adapter validates bytes, not seals. Catalogue accreditation is separate.
            raise ResearchError("SOURCE_AUDIT_UNSUPPORTED")
        if ref.verification == "HASH_VERIFIED" and ref.sha256 is None:
            raise ResearchError("SOURCE_HASH_MISSING")
        excerpt = doc.content.decode("utf-8")
        item = {
            "reference_id": ref.reference_id,
            "kind": ref.kind,
            "sha256": hashed,
            "verification": "HASH_VERIFIED" if ref.sha256 is not None else "UNVERIFIED",
            "limitations": list(ref.limitations),
            "excerpt": excerpt,
            "content_role": "UNTRUSTED_DATA",
        }
        if (
            request.flow == "FLOW2"
            and ref.reference_id == request.discovery.statistics_reference_id
        ):
            if doc.kind != "SYNTHETIC_STATISTICS":
                raise ResearchError("STATISTICS_PROVENANCE_MISSING")
            statistics = decode(doc.content, Statistics, 16 * 1024)
            discovery = request.discovery
            if (
                statistics.period_start_utc,
                statistics.period_end_utc,
                statistics.searches_count,
            ) != (discovery.period_start_utc, discovery.period_end_utc, discovery.searches_count):
                raise ResearchError("STATISTICS_PROVENANCE_MISMATCH")
            item["statistics"] = statistics.model_dump(mode="json")
        if public_data(item) != item:
            raise ResearchError("PRIVATE_SOURCE_CONTEXT")
        result.append(item)
    return result


@dataclass(frozen=True)
class Capture:
    checkpoint: str
    responses: tuple[dict, ...]
    references: tuple[CatalogRef, ...]
    match_status: str
    limitations: tuple[str, ...]
    queries: int
    attempts: int
    warning_provenance: tuple[dict, ...] = ()
    experiment_scope: tuple[dict, ...] = ()

    def payload(self) -> dict:
        return {
            "checkpoint": self.checkpoint,
            "responses": list(self.responses),
            "references": [r.model_dump(mode="json") for r in self.references],
            "match_status": self.match_status,
            "limitations": list(self.limitations),
            "warning_provenance": list(self.warning_provenance),
            "experiment_scope": list(self.experiment_scope),
            "inventory_scope": "DISCOVERY_ONLY_NOT_ECONOMIC_EVIDENCE",
        }


class CatalogContext:
    """Explicit fixture path only; no default path, discovery, or connection to real data.

    fixture_root is trusted caller configuration, not a security boundary against a
    Python process with the operator's filesystem privileges. Native guards remain
    the responsibility of CatalogReader and are never weakened here.
    """

    def __init__(self, path: Path, *, fixture_root: Path, limits: ContextLimits | None = None):
        root, path = Path(fixture_root).absolute(), Path(path).absolute()
        if (
            ".." in path.parts
            or ".." in root.parts
            or not path.is_relative_to(root)
            or path == root
        ):
            raise ValueError("Catalogue must be inside the explicit disposable fixture root")
        self._profile = CatalogReader(path).for_profile("researcher")
        self.limits = ContextLimits.model_validate((limits or ContextLimits()).model_dump())

    def capture(self, request: ResearchRequest) -> Capture:
        metrics = {"queries": 0}
        for attempt in range(1, 4):
            try:
                return self._capture(request, attempt, metrics)
            except ResearchError as exc:
                exc.queries = metrics["queries"]
                exc.attempts = attempt
                if exc.code != "CURSOR_INVALIDATED" or attempt == 3:
                    raise
        raise AssertionError("Unreachable")

    def _capture(self, request: ResearchRequest, attempt: int, metrics: dict) -> Capture:
        responses, references, seen = [], {}, set()
        entities, entity_sources, owners, foreign_runs, summaries = {}, {}, {}, set(), {}
        checkpoint = None
        match_status = "UNKNOWN"
        operation_name = None

        def query(operation, *, _project=None, **arguments):
            nonlocal checkpoint, operation_name
            if metrics["queries"] >= self.limits.max_queries:
                raise ResearchError("CONTEXT_QUERY_LIMIT")
            metrics["queries"] += 1
            response = self._profile.query(operation, **arguments)
            code = response.get("status")
            if code != "OK":
                error = ResearchError(
                    code
                    if code
                    in {
                        "INVALID_CURSOR",
                        "CURSOR_INVALIDATED",
                        "NOT_FOUND",
                        "INVALID_QUERY",
                        "RESPONSE_LIMIT_EXCEEDED",
                        "QUERY_LIMIT_EXCEEDED",
                        "BLOCKED",
                        "INTEGRITY_ERROR",
                    }
                    else "CATALOGUE_INVALID"
                )
                raise error
            current = response.get("checkpoint")
            if not isinstance(current, str) or len(current) != 64:
                raise ResearchError("CATALOGUE_INVALID")
            if checkpoint is not None and current != checkpoint:
                error = ResearchError("CURSOR_INVALIDATED")
                raise error
            checkpoint = current
            operation_name = operation
            items = _project(response["items"]) if _project else response["items"]
            operation_name = operation  # A projection may have resolved a run via another read.
            # Cursors remain inside this adapter, never in provider context.
            responses.append(
                {
                    "operation": operation,
                    "items": items,
                    "query_id": response["query_id"],
                }
            )
            if len(canonical(responses).encode()) > self.limits.max_bytes:
                raise ResearchError("CONTEXT_LIMIT_EXCEEDED")
            return response

        def paged(operation, *, _project=None, **arguments):
            rows, cursor, cursors, kind = [], None, set(), None
            for _ in range(self.limits.max_pages):
                response = query(
                    operation,
                    _project=_project,
                    **arguments,
                    page_size=self.limits.page_size,
                    cursor=cursor,
                    sort="id",
                )
                if kind is not None and response.get("match_status") != kind:
                    raise ResearchError("CATALOGUE_INVALID")
                kind = response.get("match_status")
                rows.extend(response["items"])
                cursor = response.get("next_cursor")
                if cursor is None:
                    return rows, kind
                if cursor in cursors:
                    raise ResearchError("INVALID_CURSOR")
                cursors.add(cursor)
            raise ResearchError("CONTEXT_PAGE_LIMIT")

        def record(kind, row):
            key = (kind, row["id"])
            if "[REDACTED]" in row["id"]:
                raise ResearchError("PRIVATE_REFERENCE")
            state = row.get("audit_status", row.get("verification_status", "UNKNOWN"))
            ref = CatalogRef(
                entity_type=kind,
                entity_id=row["id"],
                record_fingerprint=None,
                checkpoint=checkpoint,
                effective_status=state,
            )
            if key in references and references[key] != ref:
                raise ResearchError("CATALOGUE_INVALID")
            if kind == "experiment" and (row["asset"], row["market_type"], row["timeframe"]) != (
                request.market.asset,
                request.market.market_type,
                request.market.timeframe,
            ):
                raise ResearchError("REFERENCE_MARKET_MISMATCH")
            # Strategy summaries and graph strategy records are different public views.
            # Scientific entities themselves must remain identical across every query.
            if kind != "strategy" and key in entities and entities[key] != row:
                raise ResearchError("EVIDENCE_CONFLICT")
            if kind == "strategy" and operation_name == "get_strategy":
                if row["id"] in summaries and summaries[row["id"]] != row:
                    raise ResearchError("EVIDENCE_CONFLICT")
                summaries[row["id"]] = row
            entities[key] = row
            entity_sources.setdefault(key, set()).add(operation_name)
            references[key] = ref

        def inventory(rows):
            fields = {
                "id",
                "name",
                "family",
                "declared_family",
                "family_status",
                "version_count",
                "experiment_count",
                "run_count",
                "result_count",
                "assets_investigated",
                "timeframes_investigated",
                "stages",
                "effective_trading_authorization",
            }
            return [{k: v for k, v in row.items() if k in fields} for row in rows]

        def owner(version_id, strategy_id):
            if version_id in owners and owners[version_id] != strategy_id:
                raise ResearchError("REFERENCE_LINEAGE_MISMATCH")
            owners[version_id] = strategy_id

        def matching_market(row):
            return (row["asset"], row["market_type"], row["timeframe"]) == (
                request.market.asset,
                request.market.market_type,
                request.market.timeframe,
            )

        def load_run(run_id, *, explicit=False):
            if ("run", run_id) in entities:
                return True
            if run_id in foreign_runs:
                if explicit:
                    raise ResearchError("REFERENCE_MARKET_MISMATCH")
                return False
            graphs = query(
                "get_run_details",
                run_id=run_id,
                _project=lambda rows: [g for g in rows if matching_market(g["experiment"])],
            )["items"]
            for graph in graphs:
                if (
                    graph["run"]["experiment_id"] != graph["experiment"]["id"]
                    or graph["experiment"]["version_id"] != graph["version"]["id"]
                    or graph["version"]["strategy_id"] != graph["strategy"]["id"]
                ):
                    raise ResearchError("REFERENCE_LINEAGE_MISMATCH")
                if not matching_market(graph["experiment"]):
                    if explicit:
                        raise ResearchError("REFERENCE_MARKET_MISMATCH")
                    foreign_runs.add(run_id)
                    return False
                owner(graph["version"]["id"], graph["strategy"]["id"])
                for kind in ("strategy", "version", "experiment", "run"):
                    record(kind, graph[kind])
                for kind, field in (
                    ("case", "case_results"),
                    ("artifact", "artifacts"),
                    ("decision", "decisions"),
                ):
                    for row in graph[field]:
                        record(kind, row)
            return True

        strategies, _ = paged("list_strategies", _project=inventory)
        for row in strategies:
            record("strategy", row)
        criteria = {
            "asset": request.market.asset,
            "timeframe": request.market.timeframe,
            "market_type": request.market.market_type,
        }
        exp_ids = [r.entity_id for r in request.catalog_context if r.entity_type == "experiment"]
        if len(exp_ids) == 1:
            criteria["experiment_id"] = exp_ids[0]
        experiments, match_status = paged("find_existing_research", criteria=criteria)
        main_ids = {row["id"] for row in experiments}
        for row in experiments:
            record("experiment", row)
        for ref in request.catalog_context:
            key = (ref.entity_type, ref.entity_id)
            if key in references:
                continue
            if ref.entity_type == "strategy":
                for row in query("get_strategy", strategy_id=ref.entity_id)["items"]:
                    record("strategy", row)
            elif ref.entity_type == "experiment":
                rows, _ = paged("search_experiments", filters={"experiment_id": ref.entity_id})
                for row in rows:
                    record("experiment", row)
            elif ref.entity_type == "run":
                load_run(ref.entity_id, explicit=True)
        # Inventory is not economic evidence. Only inspect decisions of a confirmed
        # pertinent strategy or one explicitly requested. Asset/timeframe membership
        # alone is a candidate filter; the scoped query confirms the actual triple.
        explicit_strategies = {
            r.entity_id for r in request.catalog_context if r.entity_type == "strategy"
        }
        candidates = (
            explicit_strategies
            | set(owners.values())
            | {
                row["id"]
                for row in strategies
                if request.market.asset in row["assets_investigated"]
                and request.market.timeframe in row["timeframes_investigated"]
            }
        )
        relevant = set(explicit_strategies)
        for sid in sorted(candidates):
            rows, _ = paged(
                "search_experiments",
                filters={**criteria, "strategy_id": sid, "experiment_id": None},
                _project=lambda rows: [r for r in rows if ("experiment", r["id"]) not in entities],
            )
            if rows:
                relevant.add(sid)
            for row in rows:
                owner(row["version_id"], sid)
                record("experiment", row)

        def decision_relevant(row):
            if row["run_id"] is not None:
                # Resolve an actual catalogue ID, never invent/enumerate run IDs.
                # Its market must be verified even if this version spans markets.
                if not load_run(row["run_id"]):
                    return False
                graph_run = entities[("run", row["run_id"])]
                graph_exp = entities[("experiment", graph_run["experiment_id"])]
                if owners[graph_exp["version_id"]] != row["strategy_id"]:
                    raise ResearchError("REFERENCE_LINEAGE_MISMATCH")
                return True
            if row["version_id"] is not None:
                return any(
                    kind == "experiment" and e["version_id"] == row["version_id"]
                    for (kind, _), e in entities.items()
                )
            return True  # An unscoped decision applies to this confirmed strategy.

        for sid in sorted(relevant):
            # Full descriptions and economic summaries are confined to pertinent IDs.
            for row in query("get_strategy", strategy_id=sid)["items"]:
                record("strategy", row)
            decisions, _ = paged(
                "get_research_decisions",
                strategy_id=sid,
                _project=lambda rows: [r for r in rows if decision_relevant(r)],
            )
            for decision in decisions:
                if decision_relevant(decision):
                    record("decision", decision)
        for ref in request.catalog_context:
            actual = references.get((ref.entity_type, ref.entity_id))
            if actual is None:
                raise ResearchError("INVENTED_REFERENCE")
            if (
                ref.record_fingerprint is not None
                or (ref.checkpoint is not None and ref.checkpoint != actual.checkpoint)
                or ref.effective_status != actual.effective_status
            ):
                raise ResearchError("REFERENCE_MISMATCH")
        for response in responses:
            for item in response["items"]:
                key = (response["query_id"], item.get("id"))
                if item.get("id") is not None and key in seen:
                    raise ResearchError("CATALOGUE_DUPLICATE_PAGE")
                seen.add(key)
        limitations = [
            "Read-only catalogue context; not a new audit or trading authorization",
            "Related matches do not prove scientific equivalence",
        ]
        warning_definitions = {
            "CONSUMED": (
                "holdout",
                "CONSUMED",
                "CONSUMED: previously observed holdout is not independent OOS",
            ),
            "RESET_PER_SEGMENT": (
                "capital_policy",
                "RESET_PER_SEGMENT",
                "RESET_PER_SEGMENT: returns must not be compounded across segments",
            ),
            "NO_DECISION": (
                "verdict",
                "NO_DECISION",
                "NO_DECISION: no favorable economic conclusion or trading authorization",
            ),
        }
        provenance = []
        for code, (field, value, warning) in warning_definitions.items():
            origins = []
            for (kind, key), row in sorted(entities.items()):
                if kind == "strategy":
                    row = summaries.get(key, row)
                applies = (kind == "experiment" and field != "verdict" and row[field] == value) or (
                    kind == "decision"
                    and field == "verdict"
                    and row["category"] == "ECONOMIC"
                    and row["verdict"] == value
                )
                summary = (
                    kind == "strategy"
                    and key in relevant
                    and code == "NO_DECISION"
                    and "NO_DECISION" in row.get("economic_verdicts", [])
                )
                if applies or summary:
                    origins.append(
                        {
                            "entity_type": kind,
                            "entity_id": key,
                            "field": "economic_verdicts" if summary else field,
                            "value": value,
                            "via": ["get_strategy"]
                            if summary
                            else sorted(entity_sources[(kind, key)]),
                            "scope": "STRATEGY_SUMMARY"
                            if summary
                            else "EXPERIMENT"
                            if kind == "experiment"
                            else "RUN"
                            if row["run_id"] is not None
                            else "VERSION"
                            if row["version_id"] is not None
                            else "STRATEGY",
                        }
                    )
            if origins:
                limitations.append(warning)
                provenance.append({"code": code, "warning": warning, "origins": origins})
        if request.discovery.period_start_utc is not None:
            limitations.append("Discovery period is exploratory, not independent OOS validation")
        if request.discovery.searches_count is None:
            limitations.append("Multiple-testing search count is UNKNOWN")
        return Capture(
            checkpoint,
            tuple(responses),
            tuple(references[k] for k in sorted(references)),
            match_status,
            tuple(limitations),
            metrics["queries"],
            attempt,
            tuple(provenance),
            tuple(
                {
                    "experiment_id": key,
                    "strategy_id": owners.get(row["version_id"]),
                    "version_id": row["version_id"],
                    "relation": "MAIN_QUERY_MATCH" if key in main_ids else "RELATED_CONTEXT",
                }
                for (kind, key), row in sorted(entities.items())
                if kind == "experiment"
            ),
        )
