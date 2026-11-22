"""Independent-review regressions. All data and databases are disposable fixtures."""

import time

import pytest

from trading_lab_agents import CatalogContext, FakeProvider, QuantResearcher, ReceiptBook
from trading_lab_agents.context import ContextLimits
from trading_lab_agents.models import ResearchRequest
from trading_lab_catalog.models import Bundle, Decision, Experiment, Strategy, Version
from trading_lab_catalog.store import Store
from trading_lab_catalog.verification import sha
from trading_lab_orchestration.contracts import canonical

WARNINGS = {
    "CONSUMED": "CONSUMED: previously observed holdout is not independent OOS",
    "RESET_PER_SEGMENT": "RESET_PER_SEGMENT: returns must not be compounded across segments",
    "NO_DECISION": "NO_DECISION: no favorable economic conclusion or trading authorization",
}


def snapshot(root):
    return {
        str(p.relative_to(root)): sha(p.read_bytes()) if p.is_file() else "DIR"
        for p in root.rglob("*")
    }


def reference(kind, key, state="UNKNOWN"):
    return {
        "entity_type": kind,
        "entity_id": key,
        "record_fingerprint": None,
        "checkpoint": None,
        "effective_status": state,
    }


@pytest.fixture
def review_catalogue(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "catalog_api"))
    from catalog_read_support import make_catalogue

    store, bundle = make_catalogue(tmp_path, audited=True)
    primary = bundle.experiments[0].model_copy(
        update={"id": "main", "holdout": "UNOBSERVED", "capital_policy": "CONTINUOUS"}
    )
    foreign = bundle.experiments[0].model_copy(update={"id": "foreign", "asset": "ETHUSDT"})
    foreign_run = bundle.runs[0].model_copy(
        update={"id": "foreign_run", "experiment_id": "foreign", "audit_status": "UNVERIFIED"}
    )
    foreign_decision = bundle.research_decisions[0].model_copy(
        update={"id": "foreign_decision", "run_id": "foreign_run"}
    )
    store.ingest(
        Bundle(
            experiments=[primary, foreign],
            runs=[foreign_run],
            research_decisions=[foreign_decision],
        ),
        "synthetic setup",
    )
    before = snapshot(store.path.parent)
    yield store
    assert snapshot(store.path.parent) == before


def secondary_request(request_data):
    return request_data(
        catalog_context=[reference("experiment", "main"), reference("run", "r", "SOURCE_AUDITED")]
    )


def proposal(request, capture, *, omit=None):
    market = request["market"]
    return {
        "schema_version": "1.0",
        "contract_kind": "ResearchHypothesis",
        "request_id": request["request_id"],
        "status": "HYPOTHESIS_PROPOSED",
        "candidates": [
            {
                "hypothesis_id": "review_hypothesis",
                "asset": market["asset"],
                "market_type": market["market_type"],
                "timeframe": market["timeframe"],
                "statement": "Synthetic exploratory hypothesis, not an observed edge",
                "justification": "Possible persistence mechanism; not validated",
                "source_ids": ["source_01"],
                "evidence_ids": [],
                "observable_conditions": ["A previous closed high is exceeded"],
                "falsification": ["Reject a preregistered nonpositive net expectancy"],
                "bias_risks": ["Exploratory selection"],
                "limitations": [x for x in capture.limitations if x != WARNINGS.get(omit)],
                "catalog_refs": [r.model_dump(mode="json") for r in capture.references][:20],
                "verification_status": "DECLARED",
            }
        ],
        "rejected_reasons": [],
        "missing_fields": [],
        "notes": None,
    }


def test_review_secondary_graph_propagates_all_warnings(review_catalogue, tmp_path, request_data):
    context = CatalogContext(review_catalogue.path, fixture_root=tmp_path)
    capture = context.capture(ResearchRequest.model_validate(secondary_request(request_data)))
    assert set(WARNINGS.values()) <= set(capture.limitations)


@pytest.mark.parametrize("omitted", ["CONSUMED", "RESET_PER_SEGMENT", "NO_DECISION"])
def test_review_dropping_secondary_warning_is_rejected(
    review_catalogue, tmp_path, request_data, documents, omitted
):
    context = CatalogContext(review_catalogue.path, fixture_root=tmp_path)
    request = secondary_request(request_data)
    capture = context.capture(ResearchRequest.model_validate(request))
    provider = FakeProvider(response=canonical(proposal(request, capture, omit=omitted)).encode())
    result = QuantResearcher(context, provider, ReceiptBook()).run(
        canonical(request).encode(), documents=documents
    )
    assert result["error_code"] == "LIMITATION_DROPPED", result["error_code"]


@pytest.mark.parametrize(
    "kind,key,state", [("experiment", "foreign", "UNKNOWN"), ("run", "foreign_run", "UNVERIFIED")]
)
def test_review_foreign_explicit_evidence_rejected(
    review_catalogue, tmp_path, request_data, documents, kind, key, state
):
    provider = FakeProvider()
    request = request_data(catalog_context=[reference(kind, key, state)])
    result = QuantResearcher(
        CatalogContext(review_catalogue.path, fixture_root=tmp_path), provider, ReceiptBook()
    ).run(canonical(request).encode(), documents=documents)
    assert result["error_code"] == "REFERENCE_MARKET_MISMATCH", result["error_code"]
    assert provider.calls == 0


@pytest.fixture
def scale_catalogue(tmp_path, request):
    strategies, versions, experiments, decisions = [], [], [], []
    for index in range(40):
        sid, vid = f"strategy_{index:02}", f"version_{index:02}"
        asset = "BTCUSDT" if index < 4 or getattr(request, "param", None) == "dense" else "ETHUSDT"
        strategies.append(
            Strategy(
                id=sid,
                name=f"Synthetic strategy {index}",
                family="synthetic",
                description="Synthetic description; no economic validation. " * 3,
                source="synthetic",
            )
        )
        versions.append(
            Version(
                id=vid,
                strategy_id=sid,
                semantic_version="1.0.0",
                implementation_reference="synthetic.Module",
                code_sha256="a" * 64,
            )
        )
        for variant in range(3):
            experiments.append(
                Experiment(
                    id=f"experiment_{index:02}_{variant}",
                    version_id=vid,
                    hypothesis="Synthetic hypothesis",
                    market_type="spot",
                    asset=asset,
                    timeframe="1h",
                    direction="LONG_ONLY",
                    parameters={"window": 10 + variant},
                    configuration_sha256="b" * 64,
                    dataset_sha256="c" * 64,
                    experimental_protocol="synthetic only",
                    risk={"risk_pct": 0.5},
                    execution_assumptions={"timing": "NEXT_OPEN"},
                    holdout="CONSUMED",
                    capital_policy="RESET_PER_SEGMENT",
                )
            )
        for revision in range(2):
            decisions.append(
                Decision(
                    id=f"decision_{index:02}_{revision}",
                    strategy_id=sid,
                    version_id=vid,
                    run_id=None,
                    category="ECONOMIC",
                    verdict="NO_DECISION",
                    reasoning="Synthetic economic uncertainty, no promotion or trading. " * 5,
                    limitations=["Only synthetic evidence; no independent validation"],
                    decided_by="synthetic_fixture",
                    decided_at_utc=None,
                )
            )
    store = Store(tmp_path / "scale" / "strategy-catalog.sqlite3")
    store.init()
    store.ingest(
        Bundle(
            strategies=strategies,
            versions=versions,
            experiments=experiments,
            research_decisions=decisions,
        ),
        "synthetic scale setup",
    )
    before = snapshot(store.path.parent)
    yield store
    assert snapshot(store.path.parent) == before


@pytest.mark.parametrize("page_size", [20, 5])
def test_review_scale_40_strategies(
    scale_catalogue, tmp_path, request_data, documents, monkeypatch, record_property, page_size
):
    context = CatalogContext(
        scale_catalogue.path, fixture_root=tmp_path, limits=ContextLimits(page_size=page_size)
    )
    original, queries = context._profile.query, []
    original_capture, captures = context.capture, []

    def measured_capture(request):
        started = time.perf_counter()
        capture = original_capture(request)
        captures.append(
            {
                "seconds": time.perf_counter() - started,
                "payload_bytes": len(canonical(capture.payload()).encode()),
            }
        )
        return capture

    monkeypatch.setattr(context, "capture", measured_capture)

    def measured(operation, **arguments):
        result = original(operation, **arguments)
        queries.append(
            {
                "operation": operation,
                "items": result["count"],
                "has_next": result.get("next_cursor") is not None,
                "bytes": len(canonical(result).encode()),
            }
        )
        return result

    monkeypatch.setattr(context._profile, "query", measured)
    provider = FakeProvider()
    start = time.perf_counter()
    result = QuantResearcher(context, provider, ReceiptBook()).run(
        canonical(request_data()).encode(), documents=documents
    )
    elapsed = time.perf_counter() - start
    record_property(
        "scale_metrics",
        canonical(
            {
                "strategies": 40,
                "experiments": 120,
                "decisions": 80,
                "queries": queries,
                "elapsed_seconds": elapsed,
                "context_bytes": result["receipt"]["context_bytes"],
                "status": result["status"],
                "error_code": result["error_code"],
                "fake_calls": provider.calls,
                "page_size": page_size,
                "captures": captures,
            }
        ),
    )
    assert result["status"] == "COMPLETE", result["error_code"]
    assert provider.calls == 1
    decision_queries = [q for q in queries if q["operation"] == "get_research_decisions"]
    assert len(decision_queries) == 4
    assert sum(q["items"] for q in decision_queries) == 8
    assert len(result["antecedents"]["experiment_scope"]) == 12
    assert {r["strategy_id"] for r in result["antecedents"]["experiment_scope"]} == {
        f"strategy_{i:02}" for i in range(4)
    }
    assert result["receipt"]["context_bytes"] <= 64 * 1024


def test_review_warning_provenance_keeps_identity_and_scope(
    review_catalogue, tmp_path, request_data
):
    capture = CatalogContext(review_catalogue.path, fixture_root=tmp_path).capture(
        ResearchRequest.model_validate(secondary_request(request_data))
    )
    evidence = {item["code"]: item for item in capture.warning_provenance}
    consumed = evidence["CONSUMED"]["origins"]
    assert any(
        r["entity_id"] == "e"
        and r["scope"] == "EXPERIMENT"
        and r["field"] == "holdout"
        and r["value"] == "CONSUMED"
        and "get_run_details" in r["via"]
        for r in consumed
    )
    assert all(r["entity_id"] != "main" for r in consumed)
    assert any(
        r["entity_id"] == "d" and r["scope"] == "RUN" and r["field"] == "verdict"
        for r in evidence["NO_DECISION"]["origins"]
    )
    assert {r["experiment_id"] for r in capture.experiment_scope} == {"main", "e"}
    assert next(r for r in capture.experiment_scope if r["experiment_id"] == "e")["relation"] == (
        "RELATED_CONTEXT"
    )


def test_review_scoped_search_also_contributes_warnings(review_catalogue, tmp_path, request_data):
    data = request_data(catalog_context=[reference("experiment", "main")])
    capture = CatalogContext(review_catalogue.path, fixture_root=tmp_path).capture(
        ResearchRequest.model_validate(data)
    )
    assert set(WARNINGS.values()) <= set(capture.limitations)
    consumed = next(p for p in capture.warning_provenance if p["code"] == "CONSUMED")
    assert any(
        p["entity_id"] == "e" and "search_experiments" in p["via"] for p in consumed["origins"]
    )


def test_review_copying_warning_text_without_witness_is_rejected(
    review_catalogue, tmp_path, request_data, documents
):
    context = CatalogContext(review_catalogue.path, fixture_root=tmp_path)
    data = secondary_request(request_data)
    capture = context.capture(ResearchRequest.model_validate(data))
    payload = proposal(data, capture)
    payload["candidates"][0]["catalog_refs"] = [
        r.model_dump(mode="json") for r in capture.references if r.entity_id == "main"
    ]
    result = QuantResearcher(
        context, FakeProvider(response=canonical(payload).encode()), ReceiptBook()
    ).run(canonical(data).encode(), documents=documents)
    assert result["error_code"] == "LIMITATION_REFERENCE_DROPPED"


@pytest.mark.parametrize("changed", ["dataset", "lineage"])
def test_review_contradictory_evidence_fails_closed(
    review_catalogue, tmp_path, request_data, documents, monkeypatch, changed
):
    context = CatalogContext(review_catalogue.path, fixture_root=tmp_path)
    original = context._profile.query

    def contradictory(operation, **arguments):
        response = original(operation, **arguments)
        if operation == "get_run_details" and arguments["run_id"] == "r":
            graph = response["items"][0]
            if changed == "dataset":
                graph["experiment"]["dataset_sha256"] = "f" * 64
            else:
                graph["version"]["strategy_id"] = "wrong_strategy"
        return response

    monkeypatch.setattr(context._profile, "query", contradictory)
    provider = FakeProvider()
    result = QuantResearcher(context, provider, ReceiptBook()).run(
        canonical(secondary_request(request_data)).encode(), documents=documents
    )
    assert result["error_code"] == (
        "EVIDENCE_CONFLICT" if changed == "dataset" else "REFERENCE_LINEAGE_MISMATCH"
    )
    assert provider.calls == 0


def test_review_decision_run_market_is_resolved_before_inclusion(
    review_catalogue, tmp_path, request_data
):
    capture = CatalogContext(review_catalogue.path, fixture_root=tmp_path).capture(
        ResearchRequest.model_validate(request_data())
    )
    keys = {(r.entity_type, r.entity_id) for r in capture.references}
    assert ("decision", "d") in keys and ("run", "r") in keys
    assert (
        not {("decision", "foreign_decision"), ("run", "foreign_run"), ("experiment", "foreign")}
        & keys
    )
    for response in capture.responses:
        if response["operation"] == "get_research_decisions":
            assert all(row["id"] != "foreign_decision" for row in response["items"])


def test_review_summary_provenance_survives_resolving_a_run(
    review_catalogue, tmp_path, request_data
):
    capture = CatalogContext(review_catalogue.path, fixture_root=tmp_path).capture(
        ResearchRequest.model_validate(request_data())
    )
    warning = next(w for w in capture.warning_provenance if w["code"] == "NO_DECISION")
    assert any(
        o["entity_type"] == "strategy"
        and o["entity_id"] == "s"
        and o["scope"] == "STRATEGY_SUMMARY"
        and o["via"] == ["get_strategy"]
        for o in warning["origins"]
    )


@pytest.mark.parametrize(
    "field,value", [("max_bytes", 32 * 1024), ("max_queries", 10), ("max_pages", 1)]
)
def test_review_scale_limits_block_without_provider(
    scale_catalogue, tmp_path, request_data, documents, field, value, record_property
):
    context = CatalogContext(
        scale_catalogue.path, fixture_root=tmp_path, limits=ContextLimits(**{field: value})
    )
    provider = FakeProvider()
    result = QuantResearcher(context, provider, ReceiptBook()).run(
        canonical(request_data()).encode(), documents=documents
    )
    assert result["status"] == "BLOCKED" and provider.calls == 0
    expected = {
        "max_bytes": "CONTEXT_LIMIT_EXCEEDED",
        "max_queries": "CONTEXT_QUERY_LIMIT",
        "max_pages": "CONTEXT_PAGE_LIMIT",
    }[field]
    assert result["error_code"] == expected
    record_property(
        "limit_metrics",
        canonical(
            {
                "field": field,
                "value": value,
                "queries": result["receipt"]["queries"],
                "error_code": expected,
                "fake_calls": 0,
            }
        ),
    )


@pytest.mark.parametrize("scale_catalogue", ["dense"], indirect=True)
def test_review_dense_relevant_evidence_is_not_silently_truncated(
    scale_catalogue, tmp_path, request_data, documents
):
    provider = FakeProvider()
    result = QuantResearcher(
        CatalogContext(scale_catalogue.path, fixture_root=tmp_path), provider, ReceiptBook()
    ).run(canonical(request_data()).encode(), documents=documents)
    assert result["error_code"] == "CONTEXT_LIMIT_EXCEEDED"
    assert result["hypothesis"] is None and provider.calls == 0
