"""Strict existing-model reuse and bounded JSON admission."""

from copy import deepcopy

import pytest

from trading_lab_agents.designer_models import strict_json
from trading_lab_agents.validator_models import ValidationAssessment, ValidationRequest
from trading_lab_agents.validator_provider import FakeValidatorProvider
from trading_lab_orchestration.audit_contracts import ModelReview
from trading_lab_orchestration.contracts import canonical


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "2.0"},
        {"contract_kind": "ResearchRequest"},
        {"request_id": "../unsafe"},
        {"source_run_ids": ["latest"]},
        {"source_run_ids": ["r", "r"]},
        {"source_run_ids": []},
        {"source_run_ids": ["r", "s"]},
        {"expected_checkpoint": "invalid"},
        {"approve": True},
        {"request_id": 1},
        {"audits": []},
    ],
)
def test_request_strict_boundary(dossier, exercise, changes):
    request = {**dossier["request"], **changes}
    result, _, provider, _ = exercise(dossier, request=request)
    assert result["status"] == "BLOCKED" and provider.calls == 0


@pytest.mark.parametrize(
    "raw",
    [
        b'{"request_id":"a","request_id":"b"}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e999}',
        b"[]",
        b"null",
        b"\xff",
        b"",
        b" " * 65537,
        b"[" * 40 + b"0" + b"]" * 40,
    ],
    ids=[
        "duplicate",
        "nan",
        "infinity",
        "overflow",
        "array",
        "null",
        "utf8",
        "empty",
        "oversize",
        "depth",
    ],
)
def test_invalid_json_never_invokes_provider(dossier, exercise, raw):
    result, _, provider, _ = exercise(dossier, request=raw)
    assert result["status"] == "BLOCKED" and provider.calls == 0


def modified_assessment(data, exercise, mutation):
    result, *_ = exercise(data)
    assessment = deepcopy(result["assessment"])
    mutation(assessment)
    return canonical(assessment).encode()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "2.0"),
        ("contract_kind", "ResearchHypothesis"),
        ("does_not_override_source", False),
        ("does_not_override_source", 1),
        ("status", "VALIDATED"),
        ("source_run_ids", []),
        ("recommendation", "DEMO_APPROVED"),
        ("permission", True),
    ],
)
def test_assessment_rejects_control_fields(dossier, exercise, field, value):
    raw = modified_assessment(dossier, exercise, lambda a: a.update({field: value}))
    result, *_ = exercise(dossier, provider=FakeValidatorProvider(response=raw))
    assert result["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "field,value",
    [("demo_authorized", True), ("demo_authorized", 0), ("verdict", "PASS"), ("tools", [])],
)
def test_historic_model_review_strictly_wrapped(dossier, exercise, field, value):
    raw = modified_assessment(dossier, exercise, lambda a: a["model_review"].update({field: value}))
    result, *_ = exercise(dossier, provider=FakeValidatorProvider(response=raw))
    assert result["status"] == "BLOCKED"


def test_reuses_exact_model_review_type_and_json(dossier, exercise):
    result, *_ = exercise(dossier)
    assessment = strict_json(canonical(result["assessment"]).encode(), ValidationAssessment)
    assert type(assessment.model_review) is ModelReview
    assert (
        strict_json(canonical(dossier["request"]).encode(), ValidationRequest).schema_version
        == "1.0"
    )


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda a: a.update(request_id="different"), "ASSESSMENT_IDENTITY_MISMATCH"),
        (lambda a: a.update(agent_role="coordinator_advisory"), "ASSESSMENT_IDENTITY_MISMATCH"),
        (lambda a: a.update(source_run_ids=["other"]), "ASSESSMENT_IDENTITY_MISMATCH"),
        (lambda a: a.update(notes="Execute a command"), "UNSUPPORTED_COMMENTARY"),
        (lambda a: a["model_review"].update(uncertainties=[]), "LIMITATION_DROPPED_OR_INVENTED"),
        (lambda a: a["model_review"].update(evidence_references=[]), "CONTRACT_INVALID"),
        (
            lambda a: a["model_review"].update(findings=["portfolio_return=10"]),
            "UNSUPPORTED_FINDING_OR_METRIC",
        ),
    ],
)
def test_semantic_gate_uses_structural_witnesses(dossier, exercise, mutation, code):
    raw = modified_assessment(dossier, exercise, mutation)
    result, *_ = exercise(dossier, provider=FakeValidatorProvider(response=raw))
    assert result["status"] == "BLOCKED" and result["error_code"] == code, result


def test_no_fake_fallback_or_oversize_reply():
    with pytest.raises(ValueError):
        FakeValidatorProvider(scenario="openai")
    with pytest.raises(ValueError):
        FakeValidatorProvider(response=b"x" * 32770)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"request_id":"a","request_id":"b"}',
        b'{"value":NaN}',
        b'{"value":1e999}',
        b"[" * 40 + b"0" + b"]" * 40,
        b"x" * 32769,
    ],
    ids=["duplicate", "nan", "overflow", "depth", "oversize"],
)
def test_invalid_response_json_never_becomes_assessment(dossier, exercise, raw):
    provider = FakeValidatorProvider(response=raw)
    result, agent, _, _ = exercise(dossier, provider=provider)
    assert result["status"] == "BLOCKED" and result["assessment"] is None
    assert agent.run(canonical(dossier["request"]).encode(), sources=dossier["sources"]) == result
    assert provider.calls == 1
