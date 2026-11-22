import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_lab_agents.models import (
    INPUT_LIMIT,
    OUTPUT_LIMIT,
    ResearchHypothesis,
    ResearchRequest,
    decode,
    identity,
)
from trading_lab_orchestration.contracts import canonical


@pytest.mark.parametrize(
    "kind,model",
    [
        ("ResearchRequest", ResearchRequest),
        ("ResearchHypothesis", ResearchHypothesis),
    ],
)
def test_normative_documented_examples(kind, model):
    text = (Path(__file__).parents[2] / "docs/agents/agent-contracts-v1.md").read_text("utf-8")
    examples = [json.loads(x) for x in re.findall(r"```json\n(.*?)\n```", text, re.S)]
    example = next(x for x in examples if x.get("contract_kind") == kind and "message_id" not in x)
    assert model.model_validate(example).schema_version == "1.0"


@pytest.mark.parametrize(
    "field,value",
    [
        ("grant", True),
        ("schema_version", "2.0"),
        ("request_id", "../../bad"),
        ("request_id", "latest"),
        ("request_id", "a" * 129),
        ("request_id", 7),
        ("max_hypotheses", True),
        ("max_hypotheses", "1"),
        ("max_hypotheses", 4),
        ("status", "APPROVED"),
        ("objective", ""),
        ("objective", "  \n"),
        ("objective", "x" * 4001),
        ("source_refs", []),
    ],
)
def test_r15_strict_request_contract(request_data, field, value):
    with pytest.raises(ValidationError):
        ResearchRequest.model_validate(request_data(**{field: value}))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e400}',
        b"[]",
        b"{",
        b"\xff",
    ],
)
def test_r15_duplicate_nonfinite_and_invalid_json(raw):
    with pytest.raises(ValueError):
        decode(raw, ResearchRequest, INPUT_LIMIT)


@pytest.mark.parametrize(
    "change",
    [
        "non_utc",
        "backwards",
        "one_endpoint",
        "bool_searches",
        "flow2_no_statistics",
        "duplicate_sources",
    ],
)
def test_request_nested_constraints(request_data, change):
    data = request_data()
    if change == "non_utc":
        data["market"]["coverage_start_utc"] = "2022-01-01T00:00:00"
        data["market"]["coverage_end_utc"] = "2022-02-01T00:00:00Z"
    elif change == "backwards":
        data["discovery"].update(
            period_start_utc="2022-02-01T00:00:00Z", period_end_utc="2022-01-01T00:00:00Z"
        )
    elif change == "one_endpoint":
        data["market"]["coverage_start_utc"] = "2022-01-01T00:00:00Z"
    elif change == "bool_searches":
        data["discovery"]["searches_count"] = False
    elif change == "flow2_no_statistics":
        data["flow"] = "FLOW2"
    else:
        data["source_refs"] *= 2
    with pytest.raises(ValidationError):
        ResearchRequest.model_validate(data)


def test_exact_namespace_fingerprints_and_unknowns(request_data):
    data = request_data()
    parsed = ResearchRequest.model_validate(data)
    assert parsed.market.coverage_start_utc is None
    assert parsed.discovery.searches_count is None
    assert identity("ResearchRequest", data) == identity(
        "ResearchRequest", json.loads(canonical(data))
    )
    assert identity("ResearchRequest", data) != identity("ResearchHypothesis", data)


def test_catalogue_identifiers_have_their_own_domain(request_data):
    data = request_data(
        catalog_context=[
            {
                "entity_type": "strategy",
                "entity_id": "é" + "x" * 159,
                "record_fingerprint": None,
                "checkpoint": None,
                "effective_status": "UNKNOWN",
            }
        ]
    )
    assert len(ResearchRequest.model_validate(data).catalog_context[0].entity_id) == 160


@pytest.mark.parametrize(
    "size,model,limit",
    [
        (INPUT_LIMIT + 1, ResearchRequest, INPUT_LIMIT),
        (OUTPUT_LIMIT + 1, ResearchHypothesis, OUTPUT_LIMIT),
    ],
)
def test_bounded_raw_contracts(size, model, limit):
    with pytest.raises(ValueError):
        decode(b" " * size, model, limit)


@pytest.mark.parametrize(
    "model,limit",
    [(ResearchRequest, INPUT_LIMIT), (ResearchHypothesis, OUTPUT_LIMIT)],
    ids=["request", "response"],
)
def test_r15_excessive_json_nesting_is_a_controlled_error(model, limit):
    raw = b'{"unknown":' + b"[" * 11000 + b"0" + b"]" * 11000 + b"}"
    with pytest.raises(ValueError):
        decode(raw, model, limit)
