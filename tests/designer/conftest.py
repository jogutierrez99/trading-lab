"""All catalogue writes are fixture preparation; the agents subsequently read only."""

import hashlib
from pathlib import Path

import pytest

from trading_lab_agents import CatalogContext, QuantResearcher, ReceiptBook, SourceDocument
from trading_lab_agents.designer import QuantStrategyDesigner
from trading_lab_agents.designer_capabilities import DesignCapabilities
from trading_lab_agents.designer_context import DesignerContext
from trading_lab_agents.designer_host import DesignReviewHost
from trading_lab_agents.designer_provider import FakeDesignerProvider
from trading_lab_agents.provider import FakeProvider
from trading_lab_catalog.verification import sha
from trading_lab_orchestration.contracts import canonical

REPOSITORY = Path(__file__).parents[2]


@pytest.fixture(autouse=True)
def simulation_measurements(monkeypatch, record_property):
    original, sizes = FakeDesignerProvider.respond, []

    def measured(self, packet):
        sizes.append(len(packet))
        return original(self, packet)

    monkeypatch.setattr(FakeDesignerProvider, "respond", measured)
    yield
    record_property("measured_designer_invocations", len(sizes))
    record_property("measured_designer_context_bytes", canonical(sizes))


def inventory(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        if p.is_file()
        else "DIR"
        for p in root.rglob("*")
    }


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "catalog_api"))
    from catalog_read_support import make_catalogue

    store, bundle = make_catalogue(tmp_path, audited=True)
    from trading_lab_catalog.models import Bundle

    store.ingest(
        Bundle(
            versions=[
                bundle.versions[0].model_copy(
                    update={
                        "id": "reuse_version",
                        "configuration_sha256": "b" * 64,
                        "parameter_schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["window"],
                            "properties": {
                                "window": {"type": "integer", "minimum": 2, "maximum": 240}
                            },
                        },
                    }
                )
            ]
        ),
        "Synthetic host-reviewed reuse fixture",
    )
    before = inventory(store.path.parent)
    yield store, bundle
    assert inventory(store.path.parent) == before
    assert not any(
        p.name.endswith(("-journal", "-wal", "-shm")) for p in store.path.parent.iterdir()
    )


@pytest.fixture
def capabilities():
    return DesignCapabilities(
        REPOSITORY,
        dataset_id="synthetic_data",
        dataset_bytes=b"synthetic OHLCV fixture; never market data",
        asset="BTCUSDT",
        market_type="spot",
        timeframe="1h",
        coverage_start_utc="2023-12-01T00:00:00Z",
        coverage_end_utc="2024-07-01T00:00:00Z",
    )


def make_handoff(catalogue, tmp_path, capabilities):
    doc = SourceDocument(
        reference_id="source_01",
        kind="SYNTHETIC_PAPER",
        content=b"Synthetic hypothesis source. Not verified economic evidence.",
    )
    req = {
        "schema_version": "1.0",
        "contract_kind": "ResearchRequest",
        "request_id": "request_01",
        "flow": "FLOW1",
        "objective": "Prepare a synthetic falsifiable breakout hypothesis",
        "market": {
            **capabilities.payload()["dataset"]["market"],
            "coverage_start_utc": None,
            "coverage_end_utc": None,
        },
        "source_refs": [
            {
                "reference_id": "source_01",
                "kind": doc.kind,
                "sha256": sha(doc.content),
                "verification": "UNVERIFIED",
                "limitations": ["Synthetic source only"],
            }
        ],
        "catalog_context": [],
        "discovery": {
            "statistics_reference_id": None,
            "searches_count": None,
            "period_start_utc": None,
            "period_end_utc": None,
        },
        "max_hypotheses": 1,
        "status": "PREPARED",
        "limitations": [],
        "notes": None,
    }
    request = canonical(req).encode()
    book = ReceiptBook()
    researcher = QuantResearcher(
        CatalogContext(catalogue[0].path, fixture_root=tmp_path), FakeProvider(), book
    )
    result = researcher.run(request, documents=(doc,))
    assert result["status"] == "COMPLETE", result
    hypothesis = bytes.fromhex(book.export(req["request_id"])["response_hex"])
    candidate = result["hypothesis"]["candidates"][0]
    host = DesignReviewHost()
    review = host.review(
        request,
        hypothesis,
        candidate["hypothesis_id"],
        researcher_receipts=book,
        capabilities=capabilities,
    )
    return {
        "request": request,
        "hypothesis": hypothesis,
        "candidate": candidate,
        "host": host,
        "review": review,
        "book": book,
        "researcher_result": result,
    }


@pytest.fixture
def handoff(catalogue, tmp_path, capabilities):
    return make_handoff(catalogue, tmp_path, capabilities)


def specification(handoff, capabilities):
    candidate = handoff["candidate"]
    warmup = {"bars": 240, "nan": "BLOCK_ENTRY"}
    formulas = []
    for name, operator, source, window, lookback, shift in (
        ("prior_high", "ROLLING_MAX", "high", "window", 20, 1),
        ("atr", "ATR_SMA", "OHLC", 14, 14, 0),
    ):
        formulas.append(
            {
                "name": name,
                "expression": canonical(
                    {
                        "operator": operator,
                        "input": source,
                        "window": window,
                        "shift": shift,
                        "centered": False,
                        "fill": "NONE",
                        "timeframe": "1h",
                        "closed": True,
                    }
                ),
                "units": "PRICE",
                "availability": "CANDLE_CLOSE",
                "lookback_bars": lookback,
                "shift_bars": shift,
                "warmup_rule": canonical(warmup),
                "gap_rule": "REJECT_DISCONTINUITIES",
            }
        )
    risk = {
        "risk_per_trade_pct": 0.5,
        "max_position_pct": 25.0,
        "max_exposure_pct": 100.0,
        "max_open_positions": 1,
    }
    caps = capabilities.payload()
    manifest = {
        "schema_version": "1.0",
        "hypothesis_id": candidate["hypothesis_id"],
        "created_at_utc": "2026-11-22T00:00:00Z",
        "researcher_version": "TLAgents.designer/1.0",
        "title": "Synthetic prior-high specification",
        "market_hypothesis": candidate["statement"],
        "rationale": candidate["justification"],
        "source_refs": [
            {"reference": s, "accessed_on": "2026-11-22", "verification": "UNVERIFIED"}
            for s in candidate["source_ids"]
        ],
        "data_requirements": {
            "assets": ["BTCUSDT"],
            "timeframe": "1h",
            "horizon": "Synthetic six months",
            "warmup_bars": 240,
            "gap_policy": "REJECT_DISCONTINUITIES",
            "funding_policy": "NOT_APPLICABLE",
            "dataset_refs": ["synthetic_data:sha256:" + caps["dataset"]["sha256"]],
            "availability": "MANUALLY_VERIFIED",
        },
        "signal_spec": {
            "long_entry": canonical({"operator": "GT", "left": "close", "right": "prior_high"}),
            "long_exit": canonical({"operator": "LT", "left": "close", "right": "prior_high"}),
            "short_entry": None,
            "short_exit": None,
            "unsupported_modes": ["SHORT_ONLY"],
            "availability": "CANDLE_CLOSE",
            "feature_definitions": canonical(
                {
                    "formulas": ["prior_high", "atr"],
                    "warmup": warmup,
                    "gaps": "REJECT_DISCONTINUITIES",
                }
            ),
        },
        "parameter_space": {
            "parameters": {
                "window": {"values": [20], "rationale": "Frozen synthetic training-only candidate"}
            },
            "combination_limit": 1,
            "limit_rationale": "One frozen design, no sweep",
        },
        "execution_assumptions": {
            "market_mode": "spot",
            "runner_protocol": caps["protocol"]["reference_id"],
            "entry_timing": "NEXT_OPEN",
            "trading_fee_pct": 0.05,
            "slippage_pct": 0.03,
            "spread_pct": 0.01,
            "stop": canonical(
                {"type": "ATR", "formula": "atr", "multiple": 2.0, "freeze": "SIGNAL_CLOSE"}
            ),
            "target": canonical(
                {"type": "RISK_REWARD", "multiple": 2.0, "trailing": False, "time_stop_bars": None}
            ),
            "sizing": canonical(
                {
                    "method": "stop_risk",
                    "capital_initial": 10000.0,
                    "capital_policy": "RESET_PER_SEGMENT",
                    **risk,
                    "position_pct": None,
                }
            ),
            "intrabar_policy": caps["protocol"]["intrabar"],
        },
        "evaluation_plan": {
            "train": {"start": "2024-01-01T00:00:00Z", "end": "2024-03-01T00:00:00Z"},
            "validation": {"start": "2024-03-01T00:00:00Z", "end": "2024-05-01T00:00:00Z"},
            "test": {"start": "2024-05-01T00:00:00Z", "end": "2024-07-01T00:00:00Z"},
            "holdout_status": "UNOBSERVED_DECLARED",
            "holdout_risk": "A declaration, not a certification of independence",
            "walk_forward": "DISABLED_TRAIN_ONLY_SELECTION",
            "primary_metric": "net_expectancy_after_costs",
            "falsification": candidate["falsification"][0],
            "robustness_plan": canonical(
                {
                    "selection_segment": "TRAIN",
                    "holdout_independent": False,
                    "cost_application": caps["protocol"]["cost_application"],
                    "tests": ["BASE versus ADVERSE; no returns calculated"],
                }
            ),
        },
        "novelty": {
            "prior_work": "Related antecedents only",
            "known_searches": None,
            "known_variants": None,
        },
        "limitations": candidate["limitations"],
        "expected_compute_class": "SMALL",
        "requires_new_strategy_code": True,
        "status": "PROPOSED",
    }
    return {
        "schema_version": "1.0",
        "contract_kind": "StrategySpecification",
        "request_id": "request_01",
        "research_hypothesis_id": candidate["hypothesis_id"],
        "status": "SPECIFICATION_PREPARED",
        "manifest": manifest,
        "capital_policy": "RESET_PER_SEGMENT",
        "formulas": formulas,
        "risk_constraints": risk,
        "cost_scenarios": [
            {"name": "BASE", "trading_fee_pct": 0.05, "slippage_pct": 0.03, "spread_pct": 0.01},
            {"name": "ADVERSE", "trading_fee_pct": 0.1, "slippage_pct": 0.06, "spread_pct": 0.02},
        ],
        "capability_reference_ids": [caps["protocol"]["reference_id"]],
        "implementation_operation": "NEW_STRATEGY",
        "missing_fields": [],
        "review_requirements": [],
        "notes": "Synthetic design, no implementation or execution authorization",
    }


@pytest.fixture
def spec(handoff, capabilities):
    return specification(handoff, capabilities)


@pytest.fixture
def exercise(catalogue, tmp_path, handoff, capabilities, record_property):
    def run(
        payload=None,
        *,
        scenario="response",
        book=None,
        host=None,
        review=None,
        context=None,
        caps=None,
    ):
        raw = (
            payload
            if isinstance(payload, bytes)
            else canonical(payload).encode()
            if payload is not None
            else None
        )
        provider = FakeDesignerProvider(raw, scenario=scenario)
        agent = QuantStrategyDesigner(
            context or DesignerContext(catalogue[0].path, fixture_root=tmp_path),
            provider,
            book or handoff["book"],
            host or handoff["host"],
            caps or capabilities,
        )
        result = agent.run(
            handoff["request"],
            handoff["hypothesis"],
            handoff["candidate"]["hypothesis_id"],
            review_reference=review or handoff["review"],
        )
        record_property("designer_invocations", provider.calls)
        record_property("context_bytes", result["receipt"]["context_bytes"])
        record_property("context_metrics", canonical(result["receipt"]["catalogue_metrics"]))
        record_property("error_code", result["error_code"] or "NONE")
        return result, agent, provider

    return run
