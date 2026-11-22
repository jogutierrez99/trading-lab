"""Read budgets, checkpoints, controlled failures and representative synthetic volume."""

from pathlib import Path
from time import perf_counter

import pytest

from trading_lab_agents.context import ContextLimits, ResearchError
from trading_lab_agents.designer_context import DesignerContext
from trading_lab_agents.models import ResearchRequest
from trading_lab_catalog.models import Bundle, Decision, Experiment, Strategy, Version
from trading_lab_orchestration.contracts import canonical


def test_context_only_designer_profile(catalogue, handoff, tmp_path, monkeypatch):
    context = DesignerContext(catalogue[0].path, fixture_root=tmp_path)
    original, observed = context._profile.query, []

    def query(operation, **args):
        observed.append(operation)
        return original(operation, **args)

    monkeypatch.setattr(context._profile, "query", query)
    result = context.capture(ResearchRequest.model_validate_json(handoff["request"]))
    assert set(observed) <= {
        "list_strategies",
        "get_strategy",
        "list_versions",
        "search_experiments",
        "find_existing_research",
    }
    assert not any(
        k in canonical(result)
        for k in ("C:/Users/", "economic_verdicts", "evidence_reference", "catalog_events")
    )
    assert result["inventory_scope"] == "DISCOVERY_ONLY_NOT_EQUIVALENCE"
    assert result["experiments"]


@pytest.mark.parametrize(
    "limits,code",
    [
        ({"page_size": 1, "max_pages": 1}, "CONTEXT_PAGE_LIMIT"),
        ({"max_queries": 1}, "CONTEXT_QUERY_LIMIT"),
        ({"max_bytes": 1024}, "CONTEXT_LIMIT_EXCEEDED"),
    ],
)
def test_context_limits_no_provider_call(catalogue, tmp_path, exercise, spec, limits, code):
    context = DesignerContext(
        catalogue[0].path, fixture_root=tmp_path, limits=ContextLimits(**limits)
    )
    result, _, provider = exercise(spec, context=context)
    assert result["error_code"] == code and provider.calls == 0


@pytest.mark.parametrize(
    "code", ["CURSOR_INVALIDATED", "INVALID_CURSOR", "INTEGRITY_ERROR", "BLOCKED"]
)
def test_context_errors_and_bounded_recapture(catalogue, tmp_path, handoff, monkeypatch, code):
    context = DesignerContext(catalogue[0].path, fixture_root=tmp_path)
    count = []

    def query(*args, **kwargs):
        count.append(1)
        return {"status": code}

    monkeypatch.setattr(context._profile, "query", query)
    with pytest.raises(ResearchError, match=code):
        context.capture(ResearchRequest.model_validate_json(handoff["request"]))
    assert len(count) == (3 if code == "CURSOR_INVALIDATED" else 1)


def test_context_does_not_mix_checkpoints(catalogue, tmp_path, handoff, monkeypatch):
    context = DesignerContext(catalogue[0].path, fixture_root=tmp_path)
    original, calls = context._profile.query, []

    def query(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        result["checkpoint"] = ("a" if len(calls) % 2 else "b") * 64
        return result

    monkeypatch.setattr(context._profile, "query", query)
    with pytest.raises(ResearchError, match="CURSOR_INVALIDATED"):
        context.capture(ResearchRequest.model_validate_json(handoff["request"]))
    assert len(calls) == 6


def test_context_explicit_foreign_market_is_not_equivalent(
    catalogue, tmp_path, handoff, monkeypatch
):
    context = DesignerContext(catalogue[0].path, fixture_root=tmp_path)
    original = context._profile.query

    def query(operation, **kwargs):
        result = original(operation, **kwargs)
        if operation == "search_experiments":
            result["items"][0]["market_type"] = "perpetual"
        return result

    monkeypatch.setattr(context._profile, "query", query)
    with pytest.raises(ResearchError, match="REFERENCE_MARKET_MISMATCH"):
        context.capture(ResearchRequest.model_validate_json(handoff["request"]))


def test_context_fixture_root_required(tmp_path):
    with pytest.raises(ValueError):
        DesignerContext(tmp_path.parent / "elsewhere.sqlite3", fixture_root=tmp_path)
    with pytest.raises(ValueError):
        DesignerContext(tmp_path / ".." / "elsewhere.sqlite3", fixture_root=tmp_path)


def test_context_stale_handoff_checkpoint_blocks(exercise, catalogue, tmp_path, spec, monkeypatch):
    context = DesignerContext(catalogue[0].path, fixture_root=tmp_path)
    original = context.capture

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        result["checkpoint"] = "a" * 64
        return result

    monkeypatch.setattr(context, "capture", capture)
    result, _, provider = exercise(spec, context=context)
    assert result["error_code"] == "HANDOFF_CHECKPOINT_CHANGED" and provider.calls == 0


def test_context_40_strategies_multiple_experiments_and_decisions(
    tmp_path, monkeypatch, record_property
):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "catalog_api"))
    from catalog_read_support import make_catalogue

    from .conftest import inventory

    store, bundle = make_catalogue(tmp_path, audited=False)
    strategies, versions, experiments, decisions = [], [], [], []
    # Two existing strategies + 38 additional = 40. 120 experiments, 80 decisions.
    for i in range(38):
        strategies.append(
            Strategy(
                id=f"s{i:02d}",
                name=f"Synthetic {i}",
                description="Discovery only",
                source="fixture",
            )
        )
        versions.append(
            Version(
                id=f"v{i:02d}",
                strategy_id=f"s{i:02d}",
                semantic_version="1.0.0",
                implementation_reference="fixture",
                code_sha256="a" * 64,
            )
        )
    for i in range(119):
        experiments.append(
            Experiment.model_validate(
                {
                    **bundle.experiments[0].model_dump(mode="json"),
                    "id": f"e{i:03d}",
                    "version_id": "v" if i < 3 else f"v{i % 38:02d}",
                    "asset": "BTCUSDT" if i < 3 else "ETHUSDT",
                    "parameters": {"window": i + 1},
                    "parameter_fingerprint": None,
                }
            )
        )
    for i in range(79):
        decisions.append(
            Decision(
                id=f"d{i:03d}",
                strategy_id=f"s{i % 38:02d}",
                category="ECONOMIC",
                verdict="NO_DECISION",
                reasoning="Synthetic only",
                limitations=["Not evidence for another market"],
                decided_by="fixture",
                decided_at_utc=None,
            )
        )
    store.ingest(
        Bundle(
            strategies=strategies,
            versions=versions,
            experiments=experiments,
            research_decisions=decisions,
        ),
        "Synthetic volume fixture",
    )
    before = inventory(store.path.parent)
    request = ResearchRequest.model_validate(
        {
            "schema_version": "1.0",
            "contract_kind": "ResearchRequest",
            "request_id": "volume",
            "flow": "FLOW1",
            "objective": "Synthetic bounded capture",
            "market": {
                "asset": "BTCUSDT",
                "market_type": "spot",
                "timeframe": "1h",
                "requested_years": None,
                "coverage_start_utc": None,
                "coverage_end_utc": None,
            },
            "source_refs": [],
            "catalog_context": [],
            "discovery": {
                "statistics_reference_id": None,
                "searches_count": None,
                "period_start_utc": None,
                "period_end_utc": None,
            },
            "max_hypotheses": 1,
            "status": "BLOCKED",
            "limitations": [],
        }
    )
    context = DesignerContext(store.path, fixture_root=tmp_path)
    start = perf_counter()
    capture = context.capture(request)
    elapsed = perf_counter() - start
    assert len(capture["inventory"]) == 40 and len(capture["experiments"]) == 4
    assert len(capture["versions"]) == 1
    assert not any(
        key in canonical(capture) for key in ("economic_verdicts", "NO_DECISION", "ETHUSDT")
    )
    assert inventory(store.path.parent) == before
    measure = {
        "strategies": 40,
        "experiments": 120,
        "decisions": 80,
        "selected_experiments": 4,
        "selected_versions": 1,
        "capture_seconds": elapsed,
        "context_bytes": len(canonical(capture).encode()),
        **capture["metrics"],
    }
    record_property("synthetic_volume_measurement", canonical(measure))
    print("DESIGNER_VOLUME=" + canonical(measure))
    with pytest.raises(ResearchError, match="CONTEXT_PAGE_LIMIT"):
        DesignerContext(
            store.path, fixture_root=tmp_path, limits=ContextLimits(page_size=1, max_pages=1)
        ).capture(request)
    assert inventory(store.path.parent) == before
