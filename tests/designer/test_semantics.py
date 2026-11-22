"""D01-D08/D11: semantic negatives, contradictory declarations and fingerprints."""

import copy

import pytest

from trading_lab_agents.designer_models import StrategySpecification, strict_json
from trading_lab_agents.designer_semantics import signal_template
from trading_lab_agents.receipts import ReceiptBook
from trading_lab_catalog.verification import parse
from trading_lab_orchestration.contracts import HypothesisManifest, canonical


def change_json(spec, location, **updates):
    owner = spec
    for key in location[:-1]:
        owner = owner[key]
    owner[location[-1]] = canonical({**parse(owner[location[-1]]), **updates})


@pytest.mark.parametrize(
    "field,value",
    [
        ("centered", True),
        ("fill", "BACKFILL"),
        ("shift", -1),
        ("closed", False),
        ("timeframe", "4h"),
        ("window", 0),
        ("window", True),
        ("operator", "FUTURE"),
        ("input", "tomorrow_close"),
    ],
)
def test_d02_causal_declarations_rejected(spec, exercise, field, value):
    change_json(spec, ("formulas", 0, "expression"), **{field: value})
    result, _, provider = exercise(spec)
    assert result["status"] in {"NEEDS_REVIEW", "BLOCKED"}, result
    assert not result["receipt"]["mapping"] and provider.calls == 1


@pytest.mark.parametrize(
    "location,updates",
    [
        (("manifest", "signal_spec", "long_entry"), {"right": "future_data"}),
        (("manifest", "execution_assumptions", "sizing"), {"risk_per_trade_pct": 50.0}),
        (("manifest", "execution_assumptions", "sizing"), {"capital_policy": "CONTINUOUS"}),
        (("manifest", "execution_assumptions", "sizing"), {"method": "fixed_notional"}),
        (("manifest", "execution_assumptions", "stop"), {"freeze": "FUTURE_CLOSE"}),
        (("manifest", "execution_assumptions", "stop"), {"formula": "prior_high"}),
        (("manifest", "execution_assumptions", "target"), {"trailing": True}),
        (("manifest", "evaluation_plan", "robustness_plan"), {"selection_segment": "TEST"}),
        (("manifest", "evaluation_plan", "robustness_plan"), {"cost_application": "ENTRY_ONLY"}),
    ],
)
def test_d01_d03_d05_structural_contradictions(spec, exercise, location, updates):
    change_json(spec, location, **updates)
    result, _, _ = exercise(spec)
    assert result["status"] in {"NEEDS_REVIEW", "BLOCKED"}, result
    assert result["receipt"]["mapping"] is None


@pytest.mark.parametrize("field", ["stop", "target", "sizing", "intrabar_policy"])
def test_d05_missing_execution_rule_requires_review(spec, exercise, field):
    spec["manifest"]["execution_assumptions"][field] = "UNKNOWN"
    result, _, _ = exercise(spec)
    assert result["status"] == "NEEDS_REVIEW" and result["receipt"]["mapping"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("warmup_bars", 0),
        ("gap_policy", "FILL_WITH_FUTURE"),
        ("availability", "PENDING"),
        ("dataset_refs", ["invented"]),
        ("funding_policy", "REQUIRED"),
    ],
)
def test_d04_d05_d07_data_constraints(spec, exercise, field, value):
    spec["manifest"]["data_requirements"][field] = value
    result, _, _ = exercise(spec)
    assert result["status"] in {"NEEDS_REVIEW", "BLOCKED"}


@pytest.mark.parametrize("field", ["stop", "target", "sizing"])
def test_d05_incomplete_json_rule_never_guessed(spec, exercise, field):
    spec["manifest"]["execution_assumptions"][field] = "{}"
    result, _, _ = exercise(spec)
    assert result["status"] == "NEEDS_REVIEW"


def test_d03_percentage_values_preserved_exactly(spec, exercise):
    result, _, _ = exercise(spec)
    s = result["specification"]
    assert s["manifest"]["execution_assumptions"]["trading_fee_pct"] == 0.05
    assert s["risk_constraints"]["risk_per_trade_pct"] == 0.5
    assert s["cost_scenarios"][1]["trading_fee_pct"] == 0.1
    assert result["status"] == "COMPLETE"


@pytest.mark.parametrize(
    "field,value",
    [("max_open_positions", 2), ("max_exposure_pct", 101.0), ("max_position_pct", 101.0)],
)
def test_d03_risk_and_single_position_limits(spec, exercise, field, value):
    spec["risk_constraints"][field] = value
    result, _, _ = exercise(spec)
    assert result["status"] in {"NEEDS_REVIEW", "BLOCKED"}


@pytest.mark.parametrize("scenario", ["base_mismatch", "adverse_reduced", "scenario_absent"])
def test_d03_cost_scenario_conflicts(spec, exercise, scenario):
    if scenario == "base_mismatch":
        spec["cost_scenarios"][0]["trading_fee_pct"] = 0.1
    elif scenario == "adverse_reduced":
        spec["cost_scenarios"][1]["slippage_pct"] = 0.0
    else:
        spec["cost_scenarios"].pop()
    result, _, _ = exercise(spec)
    assert result["status"] == "NEEDS_REVIEW" and result["receipt"]["mapping"] is None


def test_d06_consumed_never_independent(spec, exercise):
    spec["manifest"]["evaluation_plan"]["holdout_status"] = "CONSUMED"
    change_json(spec, ("manifest", "evaluation_plan", "robustness_plan"), holdout_independent=True)
    result, _, _ = exercise(spec)
    assert result["error_code"] == "FALSE_INDEPENDENT_HOLDOUT"
    assert result["specification"]["manifest"]["evaluation_plan"]["holdout_status"] == "CONSUMED"


def test_d06_warnings_and_provenance_survive_without_new_independence(spec, exercise, handoff):
    result, _, _ = exercise(spec)
    limits = result["specification"]["manifest"]["limitations"]
    assert limits == handoff["candidate"]["limitations"]
    assert any("CONSUMED" in s for s in limits)
    assert any("NO_DECISION" in s for s in limits)
    assert any("RESET_PER_SEGMENT" in s for s in limits)
    from trading_lab_agents.designer import designer_operation_id

    exported = handoff["book"].export(
        designer_operation_id("request_01", handoff["candidate"]["hypothesis_id"])
    )
    packet = parse(bytes.fromhex(exported["context_hex"]))
    assert (
        packet["host_review"]["warning_provenance"]
        == handoff["researcher_result"]["antecedents"]["warning_provenance"]
    )
    # A different synthetic dataset does not inherit an unrelated holdout identity.
    assert (
        result["specification"]["manifest"]["evaluation_plan"]["holdout_status"]
        == "UNOBSERVED_DECLARED"
    )


def test_d06_dropped_warning_is_blocked(spec, exercise):
    spec["manifest"]["limitations"] = ["Everything is safe"]
    result, _, _ = exercise(spec)
    assert result["error_code"] == "LIMITATION_DROPPED"


@pytest.mark.parametrize("field", ["train", "validation", "test"])
def test_d06_utc_and_period_order(spec, field):
    spec["manifest"]["evaluation_plan"][field]["start"] = "2024-01-01T00:00:00"
    with pytest.raises(ValueError):
        strict_json(canonical(spec).encode(), StrategySpecification)


def test_d07_invented_capability_and_unknown_runner(spec, exercise):
    spec["capability_reference_ids"] = ["invented"]
    result, _, _ = exercise(spec)
    assert result["error_code"] == "INVENTED_CAPABILITY"


@pytest.mark.parametrize(
    "change", ["capital", "risk", "formula", "adverse", "parameters", "sizing", "stop", "target"]
)
def test_d11_scientific_changes_enter_existing_fingerprint(spec, exercise, change):
    original, _, _ = exercise(copy.deepcopy(spec), book=ReceiptBook())
    assert original["status"] == "COMPLETE", original
    if change == "capital":
        change_json(spec, ("manifest", "execution_assumptions", "sizing"), capital_initial=20000.0)
    elif change == "risk":
        spec["risk_constraints"]["risk_per_trade_pct"] = 0.8
        change_json(spec, ("manifest", "execution_assumptions", "sizing"), risk_per_trade_pct=0.8)
    elif change == "formula":
        change_json(spec, ("formulas", 0, "expression"), operator="SMA")
    elif change == "adverse":
        spec["cost_scenarios"][1]["spread_pct"] = 0.09
    elif change == "parameters":
        spec["manifest"]["parameter_space"]["parameters"]["window"]["values"] = [21]
        spec["formulas"][0]["lookback_bars"] = 21
    elif change == "sizing":
        change_json(
            spec,
            ("manifest", "execution_assumptions", "sizing"),
            method="fixed_notional",
            position_pct=20.0,
        )
    else:
        change_json(spec, ("manifest", "execution_assumptions", change), multiple=3.0)
    changed, _, _ = exercise(spec, book=ReceiptBook())
    if change == "sizing":
        # The backend has fixed_notional, but it does not enforce the stop-risk budget.
        # Refuse admission rather than misrepresent RiskConstraints as a guarantee.
        assert changed["error_code"] == "SIZING_UNSUPPORTED"
        assert changed["receipt"]["mapping"] is None
        return
    assert changed["status"] == "COMPLETE", changed
    a, b = original["receipt"], changed["receipt"]
    assert a["mapping"]["manifest_fingerprint"] != b["mapping"]["manifest_fingerprint"]
    assert a["specification_fingerprint"] != b["specification_fingerprint"]
    m = HypothesisManifest.model_validate_json(canonical(changed["specification"]["manifest"]))
    assert m.fingerprint() == b["mapping"]["manifest_fingerprint"]


def test_d11_mapping_does_not_modify_raw_proposal(spec, exercise, handoff):
    raw = canonical(spec).encode()
    result, _, _ = exercise(raw)
    from trading_lab_agents.designer import designer_operation_id

    exported = handoff["book"].export(
        designer_operation_id("request_01", handoff["candidate"]["hypothesis_id"])
    )
    assert bytes.fromhex(exported["response_hex"]) == raw
    assert "TLAgents.semantic/1.0" not in canonical(spec)
    assert "TLAgents.semantic/1.0" in canonical(result["specification"]["manifest"])


def test_d08_new_experiment_requires_host_reuse_witness(spec, exercise):
    spec["implementation_operation"] = "NEW_EXPERIMENT"
    spec["manifest"]["requires_new_strategy_code"] = False
    result, _, _ = exercise(spec)
    assert result["error_code"] == "REUSE_NOT_VERIFIED"


def test_d08_verified_reuse_and_parameter_change(handoff, capabilities, spec, exercise):
    version = {"version_id": "v", "code_sha256": "a" * 64, "configuration_sha256": None}
    # A missing configuration hash is unknown, so it cannot serve as a complete witness.
    with pytest.raises(ValueError):
        handoff["host"].review(
            handoff["request"],
            handoff["hypothesis"],
            handoff["candidate"]["hypothesis_id"],
            researcher_receipts=handoff["book"],
            capabilities=capabilities,
            reuse={
                **version,
                "signal_template": signal_template(
                    strict_json(canonical(spec).encode(), StrategySpecification)
                ),
            },
        )


def test_d11_conflicting_supplements_block_instead_of_hashing_metadata(spec, exercise):
    spec["risk_constraints"]["risk_per_trade_pct"] = 0.9
    result, _, _ = exercise(spec)
    assert result["error_code"] == "RISK_CONTRADICTION"
    assert result["receipt"]["mapping"] is None
