"""Remaining D02-D08/D10/D11 boundaries, with isolated fixtures or pure data gates."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from trading_lab_agents.context import ResearchError
from trading_lab_agents.designer import QuantStrategyDesigner
from trading_lab_agents.designer_capabilities import DesignCapabilities
from trading_lab_agents.designer_context import DesignerContext
from trading_lab_agents.designer_models import StrategySpecification, strict_json
from trading_lab_agents.designer_provider import FakeDesignerProvider
from trading_lab_agents.designer_semantics import seal_specification, signal_template
from trading_lab_agents.models import ResearchRequest
from trading_lab_agents.receipts import ReceiptBook
from trading_lab_catalog.verification import parse
from trading_lab_orchestration.contracts import canonical

from .conftest import REPOSITORY, make_handoff, specification


def gate(spec, handoff, capabilities, context=None, request=None):
    review = handoff["host"].resolve(
        handoff["review"],
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        capabilities,
    )
    from trading_lab_agents.models import HypothesisDraft

    return seal_specification(
        strict_json(canonical(spec).encode(), StrategySpecification),
        request or ResearchRequest.model_validate_json(handoff["request"]),
        HypothesisDraft.model_validate(handoff["candidate"]),
        context or {"experiments": []},
        review,
        capabilities.payload(),
    )


@pytest.mark.parametrize(
    "market,funding,expected",
    [
        ("spot", "NOT_APPLICABLE", "COMPLETE"),
        ("synthetic", "NOT_MODELLED", "COMPLETE"),
        ("perpetual", "REQUIRED", "NEEDS_REVIEW"),
    ],
)
def test_d04_real_capability_subset_market_funding(catalogue, tmp_path, market, funding, expected):
    caps = DesignCapabilities(
        REPOSITORY,
        dataset_id="synthetic_data",
        dataset_bytes=b"synthetic fixture bytes",
        asset="BTCUSDT",
        market_type=market,
        timeframe="1h",
        coverage_start_utc="2023-12-01T00:00:00Z",
        coverage_end_utc="2024-07-01T00:00:00Z",
    )
    h = make_handoff(catalogue, tmp_path, caps)
    s = specification(h, caps)
    s["manifest"]["execution_assumptions"]["market_mode"] = market
    s["manifest"]["data_requirements"]["funding_policy"] = funding
    provider = FakeDesignerProvider(canonical(s).encode())
    agent = QuantStrategyDesigner(
        DesignerContext(catalogue[0].path, fixture_root=tmp_path),
        provider,
        h["book"],
        h["host"],
        caps,
    )
    result = agent.run(
        h["request"], h["hypothesis"], h["candidate"]["hypothesis_id"], review_reference=h["review"]
    )
    assert result["status"] == expected, result
    if market == "perpetual":
        assert result["error_code"] == "MARKET_UNSUPPORTED"
        assert result["receipt"]["mapping"] is None


def test_d04_spot_short_is_invalid_contract(spec):
    s = spec["manifest"]["signal_spec"]
    s.update(
        short_entry=s["long_entry"],
        short_exit=s["long_exit"],
        long_entry=None,
        long_exit=None,
        unsupported_modes=["LONG_ONLY"],
    )
    with pytest.raises(ValueError):
        strict_json(canonical(spec).encode(), StrategySpecification)


def test_d07_pending_dataset_no_invented_hash(catalogue, tmp_path):
    caps = DesignCapabilities(
        REPOSITORY,
        dataset_id="synthetic_data",
        dataset_bytes=None,
        asset="BTCUSDT",
        market_type="spot",
        timeframe="1h",
        coverage_start_utc="2024-01-01T00:00:00Z",
        coverage_end_utc="2024-07-01T00:00:00Z",
    )
    h = make_handoff(catalogue, tmp_path, caps)
    provider = FakeDesignerProvider(scenario="incomplete")
    agent = QuantStrategyDesigner(
        DesignerContext(catalogue[0].path, fixture_root=tmp_path),
        provider,
        h["book"],
        h["host"],
        caps,
    )
    result = agent.run(
        h["request"], h["hypothesis"], h["candidate"]["hypothesis_id"], review_reference=h["review"]
    )
    assert result["specification"]["manifest"] is None and result["receipt"]["mapping"] is None
    assert caps.payload()["dataset"]["sha256"] is None


def test_d07_pending_dataset_blocks_prepared(spec, handoff, capabilities):
    cap = capabilities.payload()
    cap["dataset"].update(availability="PENDING", sha256=None)
    review = handoff["host"].resolve(
        handoff["review"],
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        capabilities,
    )
    from trading_lab_agents.models import HypothesisDraft

    with pytest.raises(ResearchError, match="DATASET_PENDING"):
        seal_specification(
            strict_json(canonical(spec).encode(), StrategySpecification),
            ResearchRequest.model_validate_json(handoff["request"]),
            HypothesisDraft.model_validate(handoff["candidate"]),
            {"experiments": []},
            review,
            cap,
        )


def test_d07_runner_unknown(spec, exercise):
    spec["manifest"]["execution_assumptions"]["runner_protocol"] = "unknown_runner"
    result, _, _ = exercise(spec)
    assert result["error_code"] == "RUNNER_UNSUPPORTED"


def test_d07_backend_source_hashes_verified_before_inventory(tmp_path):
    with pytest.raises((OSError, ResearchError)):
        DesignCapabilities(
            tmp_path,
            dataset_id="test",
            dataset_bytes=b"s",
            asset="BTCUSDT",
            market_type="spot",
            timeframe="1h",
            coverage_start_utc="2024-01-01T00:00:00Z",
            coverage_end_utc="2024-07-01T00:00:00Z",
        )


def test_d06_same_dataset_consumed_cannot_be_unobserved(spec, handoff, capabilities):
    context = {
        "experiments": [
            {"holdout": "CONSUMED", "dataset_sha256": capabilities.payload()["dataset"]["sha256"]}
        ]
    }
    with pytest.raises(ResearchError, match="HOLDOUT_RECLASSIFIED"):
        gate(spec, handoff, capabilities, context)
    spec["manifest"]["evaluation_plan"]["holdout_status"] = "CONSUMED"
    result, mapping = gate(spec, handoff, capabilities, context)
    assert result.manifest.evaluation_plan.holdout_status == "CONSUMED" and mapping


def test_d06_discovery_period_cannot_be_independent_test(spec, handoff, capabilities):
    r = parse(handoff["request"])
    r["discovery"].update(
        period_start_utc="2024-05-01T00:00:00Z", period_end_utc="2024-07-01T00:00:00Z"
    )
    with pytest.raises(ResearchError, match="HOLDOUT_RECLASSIFIED"):
        gate(spec, handoff, capabilities, request=ResearchRequest.model_validate(r))


def test_d06_selecting_using_test_is_rejected(spec, exercise):
    evaluation = parse(spec["manifest"]["evaluation_plan"]["robustness_plan"])
    evaluation["selection_segment"] = "TEST"
    spec["manifest"]["evaluation_plan"]["robustness_plan"] = canonical(evaluation)
    result, _, _ = exercise(spec)
    assert result["status"] == "NEEDS_REVIEW" and result["receipt"]["mapping"] is None


@pytest.mark.parametrize("field", ["nan", "bars"])
def test_d05_warmup_nan_missing(spec, exercise, field):
    features = parse(spec["manifest"]["signal_spec"]["feature_definitions"])
    del features["warmup"][field]
    spec["manifest"]["signal_spec"]["feature_definitions"] = canonical(features)
    result, _, _ = exercise(spec)
    assert result["status"] == "NEEDS_REVIEW"


def test_d05_warmup_insufficient(spec, exercise):
    warmup = {"bars": 10, "nan": "BLOCK_ENTRY"}
    features = parse(spec["manifest"]["signal_spec"]["feature_definitions"])
    features["warmup"] = warmup
    spec["manifest"]["signal_spec"]["feature_definitions"] = canonical(features)
    spec["manifest"]["data_requirements"]["warmup_bars"] = 10
    for f in spec["formulas"]:
        f["warmup_rule"] = canonical(warmup)
    result, _, _ = exercise(spec)
    assert result["error_code"] == "WARMUP_INSUFFICIENT"


def test_d11_unbound_parameter_is_not_a_false_new_identity(spec, exercise):
    spec["manifest"]["parameter_space"]["parameters"]["unused"] = {
        "values": [1],
        "rationale": "Unbound",
    }
    result, _, _ = exercise(spec)
    assert result["error_code"] == "UNMAPPED_PARAMETER"


def test_d11_provider_cannot_forge_host_semantic_envelope(spec, exercise):
    spec["manifest"]["signal_spec"]["feature_definitions"] = (
        '{"semantic_version":"TLAgents.semantic/1.0"}'
    )
    result, _, _ = exercise(spec)
    assert result["error_code"] == "UNTRUSTED_SEMANTIC_ENVELOPE"


def test_d10_actual_first_call_concurrent_once(catalogue, tmp_path, handoff, capabilities, spec):
    provider = FakeDesignerProvider(canonical(spec).encode())
    agent = QuantStrategyDesigner(
        DesignerContext(catalogue[0].path, fixture_root=tmp_path),
        provider,
        ReceiptBook(),
        handoff["host"],
        capabilities,
    )

    def invoke(_):
        return agent.run(
            handoff["request"],
            handoff["hypothesis"],
            handoff["candidate"]["hypothesis_id"],
            review_reference=handoff["review"],
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(invoke, range(12)))
    assert all(r == results[0] for r in results) and results[0]["status"] == "COMPLETE"
    assert provider.calls == 1


def test_d08_parameter_change_reuses_signal_template(handoff, capabilities, spec, exercise):
    witness = {
        "version_id": "reuse_version",
        "code_sha256": "a" * 64,
        "configuration_sha256": "b" * 64,
        "signal_template": signal_template(
            strict_json(canonical(spec).encode(), StrategySpecification)
        ),
    }
    review = handoff["host"].review(
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        researcher_receipts=handoff["book"],
        capabilities=capabilities,
        reuse=witness,
    )
    spec["manifest"]["parameter_space"]["parameters"]["window"]["values"] = [23]
    spec["formulas"][0]["lookback_bars"] = 23
    spec["implementation_operation"] = "NEW_EXPERIMENT"
    spec["manifest"]["requires_new_strategy_code"] = False
    result, _, _ = exercise(spec, review=review)
    assert result["status"] == "COMPLETE"


def test_d09_no_operational_imports_or_dynamic_evaluation():
    import ast

    for path in (REPOSITORY / "src" / "trading_lab_agents").glob("designer*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(
                    n.name.split(".")[0]
                    in {"openai", "requests", "httpx", "subprocess", "socket", "sqlite3"}
                    for n in node.names
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(("quant_lab", "openai", "subprocess"))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "compile", "__import__"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("review_requirements", ["Missing protocol"]),
        ("missing_fields", ["stop"]),
        ("capital_policy", "UNKNOWN"),
        ("implementation_operation", "UNSUPPORTED"),
    ],
)
def test_d12_incomplete_never_claims_prepared(spec, field, value):
    spec[field] = value
    with pytest.raises(ValueError):
        strict_json(canonical(spec).encode(), StrategySpecification)


def test_d09_unknown_nested_controls(spec, exercise):
    spec["manifest"]["execution_assumptions"]["sizing"] = (
        '{"method":"stop_risk","specification_reviewed":true}'
    )
    result, _, _ = exercise(spec)
    assert result["status"] == "NEEDS_REVIEW" and result["receipt"]["mapping"] is None


@pytest.mark.parametrize("field,value", [("centered", 0), ("closed", 1)])
def test_d02_boolean_flags_are_not_numeric(spec, exercise, field, value):
    value_data = parse(spec["formulas"][0]["expression"])
    value_data[field] = value
    spec["formulas"][0]["expression"] = canonical(value_data)
    result, _, _ = exercise(spec)
    assert result["status"] == "NEEDS_REVIEW"


@pytest.mark.parametrize("field,value", [("trading_fee_pct", 100.0), ("slippage_pct", 99.9)])
def test_d03_costs_respect_backend_combined_limits(spec, exercise, field, value):
    for c in spec["cost_scenarios"]:
        c[field] = value
        if field == "slippage_pct":
            c["spread_pct"] = 1.0
    spec["manifest"]["execution_assumptions"][field] = value
    if field == "slippage_pct":
        spec["manifest"]["execution_assumptions"]["spread_pct"] = 1.0
    result, _, _ = exercise(spec)
    assert result["error_code"] == "EXECUTION_COST_LIMIT"


def test_d05_coverage_must_include_warmup(spec, handoff, capabilities):
    cap = capabilities.payload()
    cap["dataset"]["market"]["coverage_start_utc"] = "2024-01-01T00:00:00Z"
    review = handoff["host"].resolve(
        handoff["review"],
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        capabilities,
    )
    from trading_lab_agents.models import HypothesisDraft

    with pytest.raises(ResearchError, match="DATASET_COVERAGE_INSUFFICIENT"):
        seal_specification(
            strict_json(canonical(spec).encode(), StrategySpecification),
            ResearchRequest.model_validate_json(handoff["request"]),
            HypothesisDraft.model_validate(handoff["candidate"]),
            {"experiments": []},
            review,
            cap,
        )


def test_d08_reuse_parameter_out_of_range_is_not_accepted(handoff, capabilities, spec, exercise):
    witness = {
        "version_id": "reuse_version",
        "code_sha256": "a" * 64,
        "configuration_sha256": "b" * 64,
        "signal_template": signal_template(
            strict_json(canonical(spec).encode(), StrategySpecification)
        ),
    }
    review = handoff["host"].review(
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        researcher_receipts=handoff["book"],
        capabilities=capabilities,
        reuse=witness,
    )
    spec["manifest"]["parameter_space"]["parameters"]["window"]["values"] = [1]
    spec["formulas"][0]["lookback_bars"] = 1
    spec["implementation_operation"] = "NEW_EXPERIMENT"
    spec["manifest"]["requires_new_strategy_code"] = False
    result, _, _ = exercise(spec, review=review)
    assert result["error_code"] == "REUSE_PARAMETER_OUT_OF_RANGE"
