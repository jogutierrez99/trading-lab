import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from catalog_read_support import extra_experiment, make_catalogue

from trading_lab_catalog.local_evidence import LocalEvidenceReferences
from trading_lab_catalog.models import Bundle, fingerprint
from trading_lab_catalog.read_api import PROFILES, CatalogReader
from trading_lab_catalog.read_models import public_data
from trading_lab_catalog.store import Store
from trading_lab_catalog.verification import sha


def test_audit_asset_timeframe_pair_must_exist_in_same_experiment(catalog, reader):
    store, bundle = catalog
    version = bundle.versions[0].model_copy(
        update={"id": "paired-version", "strategy_id": "paired"}
    )
    experiments = []
    for key, asset, timeframe in (("paired-a", "BTCUSDT", "4h"), ("paired-b", "ETHUSDT", "1h")):
        experiments.append(
            bundle.experiments[0].model_copy(
                update={"id": key, "version_id": version.id, "asset": asset, "timeframe": timeframe}
            )
        )
    strategy = bundle.strategies[0].model_copy(update={"id": "paired", "name": "Paired"})
    store.ingest(
        Bundle(strategies=[strategy], versions=[version], experiments=experiments), "fixture"
    )
    result = reader.list_strategies(
        {"strategy_id": "paired", "asset": "BTCUSDT", "timeframe": "1h"}
    )
    assert result["status"] == "OK" and result["count"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("asset", "ETHUSDT"),
        ("timeframe", "4h"),
        ("engine", "other"),
        ("capital_initial", 20000),
        ("scenario", "adverse"),
        ("costs", {"fee_pct": 0.3}),
        ("period_end_utc", "2022-03-01T00:00:00Z"),
    ],
)
def test_audit_comparison_condition_matrix(catalog, reader, field, value):
    from trading_lab_catalog.models import Case, Experiment, Run

    store, bundle = catalog
    exp = bundle.experiments[0].model_dump(mode="json")
    exp.update(id="comparison-exp", parameters={"window": 123}, parameter_fingerprint=None)
    run = bundle.runs[0].model_dump(mode="json")
    run.update(id="comparison-run", experiment_id=exp["id"])
    case = bundle.case_results[0].model_dump(mode="json")
    case.update(id="comparison-case", run_id=run["id"])
    target = exp if field in ("asset", "timeframe") else run if field == "engine" else case
    target[field] = value
    store.ingest(
        Bundle(
            experiments=[Experiment.model_validate(exp)],
            runs=[Run.model_validate(run)],
            case_results=[Case.model_validate(case)],
        ),
        "synthetic comparison",
    )
    response = reader.compare_results(["c1", case["id"]])
    assert response["status"] == "OK"
    comparison = response["items"][0]
    assert comparison["comparison_status"] == "NOT_COMPARABLE"
    assert field in comparison["condition_differences"]
    assert "Different or unknown " + field in comparison["reasons"]
    assert comparison["winner"] is None


@pytest.mark.parametrize("sort", ["id", "-id"])
def test_audit_full_pagination_has_no_gaps_or_duplicates(catalog, reader, sort):
    store, bundle = catalog
    extra = [extra_experiment(bundle, "e" + str(i)) for i in range(2, 215) if i != 50]
    store.ingest(Bundle(experiments=extra), "synthetic pages")
    expected = sorted(["e", *(e.id for e in extra)], reverse=sort == "-id")
    cursor, found = None, []
    while True:
        result = reader.search_experiments(page_size=200, sort=sort, cursor=cursor)
        assert result["status"] == "OK" and result["count"] <= 200
        found.extend(item["id"] for item in result["items"])
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert found == expected and len(found) == len(set(found))


def test_public_methods_and_strategy_stages(reader):
    rows = reader.list_strategies()
    assert rows["status"] == "OK" and rows["count"] == 2
    row = reader.get_strategy("s")["items"][0]
    assert row["stages"]["discovered"]
    assert row["stages"]["has_experiments"] and row["stages"]["has_results"]
    assert not row["stages"]["has_source_audited_run"]
    assert row["stages"]["economic_validation"] == "NOT_ASSESSED"
    assert row["economic_verdicts"] == ["NO_DECISION"]
    assert row["research_state"] == "UNKNOWN"
    empty = reader.get_strategy("empty")["items"][0]
    assert empty["experiment_count"] == 0 and not empty["stages"]["has_runs"]
    assert empty["family"] is None


def test_queries_and_json_contract(reader):
    assert reader.list_versions("s")["count"] == 2
    assert reader.search_experiments({"asset": "BTCUSDT", "timeframe": "1h"})["count"] == 1
    assert reader.search_experiments({"strategy_id": "s", "version_id": "v"})["count"] == 1
    assert reader.list_runs("e")["count"] == 1
    details = reader.get_run_details("r")
    assert details["status"] == "OK"
    assert details["items"][0]["experiment"]["holdout"] == "CONSUMED"
    assert details["items"][0]["experiment"]["capital_policy"] == "RESET_PER_SEGMENT"
    assert details["items"][0]["decisions"][0]["verdict"] == "NO_DECISION"
    json.dumps(details, allow_nan=False)
    assert reader.get_research_decisions("s", category="ECONOMIC")["count"] == 1
    assert reader.get_research_decisions("s", category="RESEARCH")["count"] == 0
    assert reader.list_versions("empty")["items"] == []
    assert reader.list_runs("e", status="FAILED")["items"] == []


@pytest.mark.parametrize(
    "method,args",
    [
        ("get_strategy", ("missing",)),
        ("list_versions", ("missing",)),
        ("list_runs", ("missing",)),
        ("get_run_details", ("missing",)),
        ("list_case_results", ("missing",)),
        ("get_evidence_summary", ("missing",)),
        ("get_research_decisions", ("missing",)),
        ("compare_results", (["missing"],)),
    ],
)
def test_missing_ids(reader, method, args):
    assert getattr(reader, method)(*args)["status"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page_size": 0},
        {"page_size": 201},
        {"page_size": True},
        {"sort": "name"},
        {"filters": {"asset": "BTCUSDT", "sql": "DROP TABLE runs"}},
        {"filters": {"parameters": {"window": 50}, "parameter_fingerprint": "a" * 64}},
        {"filters": {"asset": 50}},
        {"filters": {"parameters": {"x": float("inf")}}},
    ],
)
def test_invalid_contracts(reader, kwargs):
    assert reader.search_experiments(**kwargs)["status"] == "INVALID_QUERY"


def test_filter_values_are_parameters(reader, catalog):
    assert reader.search_experiments({"asset": "' OR 1=1 --"})["items"] == []
    assert catalog[0].verify()["status"] == "OK"
    assert reader.list_strategies({"asset": "BTCUSDT", "timeframe": "1h"})["count"] == 1
    assert reader.list_strategies({"family": "unknown"})["count"] == 0
    assert (
        reader.search_experiments({"holdout": "CONSUMED", "capital_policy": "RESET_PER_SEGMENT"})[
            "count"
        ]
        == 1
    )
    assert reader.search_experiments({"parameters": {"window": 50}})["count"] == 1


def test_stable_signed_pagination(reader, catalog):
    store, bundle = catalog
    store.ingest(
        Bundle(experiments=[extra_experiment(bundle, "e2"), extra_experiment(bundle, "e3")]),
        "fixture",
    )
    first = reader.search_experiments(page_size=1)
    again = reader.search_experiments(page_size=1)
    assert first == again
    second = reader.search_experiments(page_size=1, cursor=first["next_cursor"])
    third = reader.search_experiments(page_size=1, cursor=second["next_cursor"])
    assert [r["items"][0]["id"] for r in (first, second, third)] == ["e", "e2", "e3"]
    assert third["next_cursor"] is None
    descending = reader.search_experiments(page_size=2, sort="-id")
    assert [r["id"] for r in descending["items"]] == ["e3", "e2"]
    assert (
        reader.search_experiments(page_size=1, cursor=first["next_cursor"] + "x")["status"]
        == "INVALID_CURSOR"
    )
    assert (
        reader.search_experiments(page_size=2, cursor=first["next_cursor"])["status"]
        == "INVALID_CURSOR"
    )
    assert (
        reader.search_experiments({"asset": "BTCUSDT"}, page_size=1, cursor=first["next_cursor"])[
            "status"
        ]
        == "INVALID_CURSOR"
    )
    other = CatalogReader(store.path, cursor_key=b"b" * 32)
    assert (
        other.search_experiments(page_size=1, cursor=first["next_cursor"])["status"]
        == "INVALID_CURSOR"
    )


def test_catalogue_change_invalidates_cursor(reader, catalog):
    store, bundle = catalog
    first = reader.list_versions("s", page_size=1)
    store.ingest(Bundle(experiments=[extra_experiment(bundle, "e2")]), "fixture")
    result = reader.list_versions("s", page_size=1, cursor=first["next_cursor"])
    assert result["status"] == "CURSOR_INVALIDATED"


def test_case_filters_and_nulls(reader):
    data = reader.list_case_results("r", {"scenario": "base"})
    assert data["count"] == 1
    assert data["items"][0]["net_return_pct"] is None
    assert data["items"][0]["profit_factor"] is None
    assert data["items"][0]["run_audit_status"] == "UNVERIFIED"
    assert reader.list_case_results("r", {"audit_status": "SOURCE_AUDITED"})["count"] == 0
    assert reader.list_case_results("r", {"audit_status": "UNVERIFIED"})["count"] == 2
    assert (
        reader.list_case_results(
            "r",
            {
                "status": "COMPLETE",
                "asset": "BTCUSDT",
                "version_id": "v",
                "period_start_utc": "2022-01-01T00:00:00+00:00",
            },
        )["count"]
        == 2
    )
    assert (
        reader.list_case_results("r", {"period_start_utc": "2022-01-01T00:00:00"})["status"]
        == "INVALID_QUERY"
    )


def test_comparison_reuses_policy(reader):
    result = reader.compare_results(["c1", "c2"])["items"][0]
    assert result["comparison_status"] == "NOT_COMPARABLE"
    assert result["condition_differences"] == ["scenario", "costs"]
    assert "Holdout consumed or unknown; retrospective evidence" in result["limitations"]
    assert result["winner"] is None
    assert reader.compare_results(["c1"])["items"][0]["comparison_status"] == "NOT_COMPARABLE"
    assert reader.compare_results([])["items"][0]["comparison_status"] == "NOT_COMPARABLE"
    assert reader.compare_results(["c1", "c1"])["status"] == "INVALID_QUERY"


def test_exact_related_and_unknown(reader, catalog):
    exp = catalog[1].experiments[0].model_dump(mode="json")
    digest = fingerprint({k: v for k, v in exp.items() if k != "id"})
    assert reader.find_existing_research({"experiment_id": "e"})["match_status"] == "EXACT_MATCH"
    assert (
        reader.find_existing_research({"definition_fingerprint": digest})["match_status"]
        == "EXACT_MATCH"
    )
    assert (
        reader.find_existing_research({"asset": "BTCUSDT"})["match_status"] == "RELATED_CANDIDATE"
    )
    assert reader.find_existing_research({"asset": "HYPE"})["match_status"] == "NO_MATCH"
    assert reader.find_existing_research()["match_status"] == "UNKNOWN"


def test_trust_comes_from_events(tmp_path):
    store, bundle = make_catalogue(tmp_path, audited=True)
    reader = CatalogReader(store.path)
    details = reader.get_run_details("r")
    assert details["items"][0]["run"]["audit_status"] == "SOURCE_AUDITED"
    assert reader.list_case_results("r", {"audit_status": "SOURCE_AUDITED"})["count"] == 2
    artifact = reader.get_evidence_summary("r")["items"][0]["artifacts"][0]
    assert artifact["verification_status"] == "HASH_VERIFIED"
    assert "reference" not in artifact
    assert "not a new audit" in reader.get_evidence_summary("r")["items"][0]["limitations"][0]
    assert bundle.runs[0].audit_status == "SOURCE_AUDITED"


@pytest.mark.parametrize(
    "audited,expected",
    [
        (False, "COMPARABLE_WITH_LIMITATIONS"),
        (True, "COMPARABLE"),
    ],
)
def test_audit_comparison_preserves_all_states_without_promotion(tmp_path, audited, expected):
    store, _ = make_catalogue(tmp_path, audited=audited, comparable=True)
    reader = CatalogReader(store.path)
    comparison = reader.compare_results(["c1", "c2"])["items"][0]
    assert comparison["comparison_status"] == expected
    assert comparison["winner"] is None
    assert comparison["cases"][0]["verdict"] == "NO_DECISION"
    assert reader.get_strategy("s")["items"][0]["stages"]["economic_validation"] == "NOT_ASSESSED"


def test_privacy_and_explicit_local_boundary(reader, catalog):
    rendered = json.dumps(reader.get_run_details("r"))
    assert "private" not in rendered and "receipt.json" not in rendered
    assert "never-return" not in rendered
    assert public_data(
        {"description": "C:/Users/operator/private", "password": "secret-value"}
    ) == {"description": "[REDACTED]", "password": "[REDACTED]"}
    assert public_data({"note": "S-1-5-21-1234"})["note"] == "[REDACTED]"
    local = LocalEvidenceReferences(catalog[0].path).for_run("r")
    assert local["trusted_local_only"] and "C:/Users/private" in local["evidence_reference"]


def test_no_write_capability_and_connection_cleanup(reader, catalog):
    before = sha(catalog[0].path.read_bytes())
    for name in ("init", "migrate", "ingest", "register", "execute", "discover", "connection"):
        assert not hasattr(reader, name)
    with reader._snapshot() as snap:
        connection = snap.c
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("DELETE FROM runs")
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("ATTACH DATABASE ':memory:' AS extra")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    assert sha(catalog[0].path.read_bytes()) == before
    assert sorted(p.name for p in catalog[0].path.parent.iterdir()) == ["strategy-catalog.sqlite3"]


def test_error_closes_connection(reader, monkeypatch):
    captured = []
    original = reader._page

    def fail(snap, *args, **kwargs):
        captured.append(snap.c)
        raise ValueError("query error")

    monkeypatch.setattr(reader, "_page", fail)
    assert reader.search_experiments()["status"] == "INVALID_QUERY"
    with pytest.raises(sqlite3.ProgrammingError):
        captured[0].execute("SELECT 1")
    monkeypatch.setattr(reader, "_page", original)
    assert reader.search_experiments()["status"] == "OK"


def test_storage_refusals(tmp_path):
    missing = CatalogReader(tmp_path / "catalog" / "strategy-catalog.sqlite3")
    assert missing.get_catalog_status()["status"] == "BLOCKED"
    assert not (tmp_path / "catalog").exists()
    path = tmp_path / "unknown" / "strategy-catalog.sqlite3"
    path.parent.mkdir()
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE foreign_table(x)")
    before = path.read_bytes()
    assert CatalogReader(path).get_catalog_status()["status"] == "BLOCKED"
    assert path.read_bytes() == before


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_sidecars_rejected(reader, catalog, suffix):
    p = catalog[0].path
    p.with_name(p.name + suffix).write_bytes(b"fixture")
    assert reader.get_catalog_status()["status"] in ("INVALID_QUERY", "BLOCKED")
    assert p.with_name(p.name + suffix).read_bytes() == b"fixture"


def test_wal_mode_rejected(catalog):
    store, _ = catalog
    with sqlite3.connect(store.path) as c:
        c.execute("PRAGMA journal_mode=WAL")
    before = store.path.read_bytes()
    assert CatalogReader(store.path).get_catalog_status()["status"] in ("BLOCKED", "INVALID_QUERY")
    assert store.path.read_bytes() == before


def test_response_limits(catalog):
    reader = CatalogReader(catalog[0].path, max_response_bytes=1024)
    assert reader.get_run_details("r")["status"] == "RESPONSE_LIMIT_EXCEEDED"


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_query_profiles(reader, profile):
    selected = reader.for_profile(profile)
    for method in PROFILES[profile]:
        assert callable(getattr(reader, method))
    assert selected.query("ingest")["status"] == "INVALID_QUERY"
    operation = "get_catalog_status" if profile in ("coordinator", "auditor") else "get_strategy"
    args = {} if operation == "get_catalog_status" else {"strategy_id": "s"}
    assert selected.query(operation, **args)["status"] == "OK"


def test_multiple_readers_do_not_mutate(reader, catalog):
    before = catalog[0].path.read_bytes()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: reader.get_run_details("r"), range(12)))
    assert all(r == results[0] and r["status"] == "OK" for r in results)
    assert catalog[0].path.read_bytes() == before


def test_selected_record_api_reuses_original_trust(catalog):
    store, _ = catalog
    assert store.records("runs", ids=["r"]) == store.records("runs")
    assert store.records("runs", ids=[]) == []
    assert store.records("runs", ids=["missing"]) == []
    with pytest.raises(ValueError):
        store.records("runs", ids=["r"] * 201)


def test_trust_provenance_contains_no_local_locator(tmp_path):
    store, _ = make_catalogue(tmp_path, audited=True)
    result = CatalogReader(store.path).get_evidence_summary("r")
    provenance = result["items"][0]["provenance"]
    assert len(provenance) == 4
    assert {p["accreditation_kind"] for p in provenance} == {
        "SOURCE_AUDITED_runs",
        "SOURCE_AUDITED_case_results",
        "HASH_VERIFIED_artifacts",
    }
    assert all(len(p["record_fingerprint"]) == 64 for p in provenance)
    assert "C:/Users" not in json.dumps(result)


def test_empty_experiment_and_unknown_run(reader, catalog):
    store, bundle = catalog
    store.ingest(Bundle(experiments=[extra_experiment(bundle, "e2")]), "synthetic")
    assert reader.list_runs("e2")["items"] == []
    unknown = bundle.runs[0].model_copy(
        update={"id": "unknown", "status": "UNKNOWN", "job_sha256": "f" * 64}
    )
    store.ingest(Bundle(runs=[unknown]), "synthetic")
    rows = reader.list_runs("e", status="UNKNOWN")
    assert rows["count"] == 1 and rows["items"][0]["status"] == "UNKNOWN"


def test_pagination_effective_audit_filter_and_full_integrity(reader):
    first = reader.list_case_results("r", {"audit_status": "UNVERIFIED"}, page_size=1)
    next_page = reader.list_case_results(
        "r", {"audit_status": "UNVERIFIED"}, page_size=1, cursor=first["next_cursor"]
    )
    assert first["count"] == next_page["count"] == 1
    assert next_page["next_cursor"] is None
    assert (
        reader.get_catalog_status(verify=True)["items"][0]["verification"]
        == "FULL_SQLITE_AND_PAYLOAD"
    )


def test_bounded_sql_selection(catalog, monkeypatch):
    store, _ = catalog
    seen = []
    original = Store.records

    def recorded(self, table, **kwargs):
        seen.append((table, kwargs.get("ids")))
        return original(self, table, **kwargs)

    monkeypatch.setattr(Store, "records", recorded)
    result = CatalogReader(store.path).search_experiments(page_size=1)
    assert result["status"] == "OK"
    assert seen and all(ids is not None and len(ids) <= 200 for _, ids in seen)


def test_family_declaration_does_not_become_accredited(reader, catalog):
    store, bundle = catalog
    other = bundle.strategies[0].model_copy(update={"id": "declared", "family": "momentum"})
    store.ingest(Bundle(strategies=[other]), "synthetic operator declaration")
    result = reader.list_strategies({"family": "momentum"})
    assert result["count"] == 1
    assert result["items"][0]["family"] is None
    assert result["items"][0]["declared_family"] == "momentum"
    assert result["items"][0]["family_status"] == "DECLARED_UNVERIFIED"


@pytest.mark.parametrize(
    "text",
    [
        "/etc/passwd",
        "C:/Users/operator/private",
        "note /home/operator/file",
        "Bearer synthetic-access-token",
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_recognized_sensitive_text_is_redacted(text):
    assert public_data({"note": text})["note"] == "[REDACTED]"


@pytest.mark.parametrize("filters", [[], False, 0, ""])
def test_falsey_non_mapping_filters_are_rejected(reader, filters):
    assert reader.search_experiments(filters)["status"] == "INVALID_QUERY"


def test_read_budget_exhaustion_is_structured(catalog, monkeypatch):
    from itertools import count

    from trading_lab_catalog import read_api

    clock = count()
    monkeypatch.setattr(read_api.time, "monotonic", lambda: float(next(clock)))
    reader = CatalogReader(catalog[0].path, timeout_seconds=0.1)
    assert reader.search_experiments()["status"] == "QUERY_LIMIT_EXCEEDED"


@pytest.mark.parametrize("arguments", [{"filters": {"asset": ""}}, {"cursor": ""}])
def test_empty_filter_values_and_cursor_are_rejected(reader, arguments):
    assert reader.search_experiments(**arguments)["status"] == "INVALID_QUERY"


def test_audit_mutated_typed_filter_is_revalidated(reader):
    from trading_lab_catalog.read_models import ExperimentFilters

    query = ExperimentFilters(parameters={"window": 50})
    query.parameters["window"] = 200
    assert reader.search_experiments(query)["status"] == "INVALID_QUERY"


def test_audit_constructed_typed_filter_is_revalidated(reader):
    from trading_lab_catalog.read_models import ExperimentFilters

    query = ExperimentFilters.model_construct(asset=123)
    assert reader.search_experiments(query)["status"] == "INVALID_QUERY"


def test_audit_private_dictionary_keys_are_not_returned(reader, catalog):
    store, bundle = catalog
    from trading_lab_catalog.models import Experiment

    path_key = "C:/Users/synthetic-private/results"
    exp = Experiment.model_validate(
        {
            **bundle.experiments[0].model_dump(mode="json"),
            "id": "private-keys",
            "parameters": {path_key: 1},
            "parameter_fingerprint": None,
        }
    )
    store.ingest(Bundle(experiments=[exp]), "synthetic audit")
    response = reader.search_experiments({"experiment_id": "private-keys"})
    assert response["status"] == "OK"
    assert path_key not in json.dumps(response)
    assert response["data_redacted"] is True


def test_audit_noncanonical_cursor_is_rejected(reader):
    first = reader.list_versions("s", page_size=1)
    cursor = first["next_cursor"]
    padded = cursor + "=" * ((-len(cursor)) % 4 or 4)
    assert reader.list_versions("s", page_size=1, cursor=padded)["status"] == "INVALID_CURSOR"


def test_audit_cursor_must_not_encode_a_private_identity(reader, catalog):
    import base64

    from trading_lab_catalog.models import Strategy

    private_id = "C:/Users/synthetic-private/research"
    catalog[0].ingest(
        Bundle(
            strategies=[
                Strategy(
                    id=private_id,
                    name="Synthetic private identity",
                    description="fixture",
                    source="fixture",
                )
            ]
        ),
        "fixture",
    )
    response = reader.list_strategies(page_size=1)
    if response["status"] == "OK":
        token = response["next_cursor"]
        decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        assert json.loads(decoded[32:])["last"] == private_id
    # HMAC authenticates but does not conceal cursor contents. Reject rather than
    # encode a locator that the public projection would otherwise redact.
    assert response["status"] == "BLOCKED"
    assert response["next_cursor"] is None
