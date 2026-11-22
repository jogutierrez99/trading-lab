"""D01/D03/D09/D12: strict contracts and faithful JSON date semantics."""

import copy

import pytest

from trading_lab_agents.designer_models import StrategySpecification, strict_json
from trading_lab_orchestration.contracts import canonical


def test_d01_full_manifest_json_dates(spec, exercise):
    proposal = strict_json(canonical(spec).encode(), StrategySpecification)
    assert proposal.manifest.created_at_utc.utcoffset().total_seconds() == 0
    result, _, provider = exercise(spec)
    assert result["status"] == "COMPLETE", result
    assert result["specification"]["status"] == "SPECIFICATION_PREPARED"
    assert result["receipt"]["mapping"]["manifest_fingerprint"]
    assert provider.calls == 1


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"1.0","schema_version":"1.0"}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":1e999}',
        b'{"a":' + b"[" * 26 + b"0" + b"]" * 26 + b"}",
        b"[]",
        b"\xff",
        b"",
    ],
)
def test_d09_reject_unsafe_json(raw):
    with pytest.raises(ValueError):
        strict_json(raw, StrategySpecification)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "2.0"),
        ("contract_kind", "ImplementationRequest"),
        ("request_id", "latest"),
        ("request_id", "../a"),
        ("status", "APPROVED"),
        ("specification_reviewed", True),
        ("tools", ["execute"]),
        ("budget", 20.0),
    ],
)
def test_d09_unknown_control_and_identity_fields(spec, field, value):
    spec[field] = value
    with pytest.raises(ValueError):
        strict_json(canonical(spec).encode(), StrategySpecification)


@pytest.mark.parametrize(
    "field,value",
    [
        ("risk_per_trade_pct", "0.5"),
        ("risk_per_trade_pct", True),
        ("risk_per_trade_pct", -1.0),
        ("risk_per_trade_pct", 101.0),
        ("max_open_positions", 1.0),
        ("max_open_positions", 0),
    ],
)
def test_d03_strict_risk_units_types_bounds(spec, field, value):
    spec["risk_constraints"][field] = value
    with pytest.raises(ValueError):
        strict_json(canonical(spec).encode(), StrategySpecification)


@pytest.mark.parametrize("field", ["formulas", "cost_scenarios", "capability_reference_ids"])
def test_d01_duplicate_scientific_ids(spec, field):
    spec[field].append(copy.deepcopy(spec[field][0]))
    with pytest.raises(ValueError):
        strict_json(canonical(spec).encode(), StrategySpecification)


@pytest.mark.parametrize("field", ["manifest", "risk_constraints"])
def test_d12_no_fabricated_complete_manifest(spec, field):
    spec[field] = None
    with pytest.raises(ValueError):
        strict_json(canonical(spec).encode(), StrategySpecification)


def test_d12_incomplete_has_real_nulls(exercise):
    result, _, provider = exercise(scenario="incomplete")
    assert result["status"] == "COMPLETE" and provider.calls == 1
    s = result["specification"]
    assert s["status"] == "NEEDS_REVIEW" and s["missing_fields"]
    assert s["manifest"] is s["risk_constraints"] is None
    assert result["receipt"]["mapping"] is None


def test_normative_document_examples_remain_compatible():
    import json
    import re

    from .conftest import REPOSITORY

    text = (REPOSITORY / "docs/agents/agent-contracts-v1.md").read_text("utf-8")
    found = []
    for block in re.findall(r"```json\s*(.*?)\s*```", text, re.S):
        payload = json.loads(block)
        if payload.get("contract_kind") == "StrategySpecification":
            found.append(strict_json(block.encode(), StrategySpecification))
    assert len(found) == 2
    assert all(s.status == "NEEDS_REVIEW" for s in found)
