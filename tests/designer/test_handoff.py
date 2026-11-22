"""Synthetic Researcher -> host review -> Designer; no operational coordinator."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from trading_lab_agents.designer import QuantStrategyDesigner, designer_operation_id
from trading_lab_agents.designer_host import DesignReviewHost
from trading_lab_agents.designer_models import StrategySpecification, strict_json
from trading_lab_agents.designer_provider import FakeDesignerProvider
from trading_lab_agents.designer_semantics import signal_template
from trading_lab_agents.receipts import ReceiptBook
from trading_lab_catalog.verification import parse, sha
from trading_lab_orchestration.contracts import canonical


def test_d01_local_handoff_preserves_independent_operations(handoff, spec, exercise):
    result, _, provider = exercise(spec)
    assert result["status"] == "COMPLETE"
    assert handoff["book"].export("request_01")["result"] == handoff["researcher_result"]
    exported = handoff["book"].export(
        designer_operation_id("request_01", handoff["candidate"]["hypothesis_id"])
    )
    packet = parse(bytes.fromhex(exported["context_hex"]))
    assert packet["tools"] == [] and packet["agent_id"] == "quant_strategy_designer_v1"
    assert (
        packet["host_review"]["authorizes"]
        == "SYNTHETIC_DESIGN_ONLY_NO_IMPLEMENTATION_OR_EXECUTION"
    )
    assert exported["result"] == result and provider.calls == 1


@pytest.mark.parametrize("status", ["NO_HYPOTHESIS", "NEEDS_REVIEW"])
def test_d09_non_proposed_handoff_rejected(handoff, status, capabilities):
    h = parse(handoff["hypothesis"])
    h.update(
        status=status,
        candidates=[],
        missing_fields=["Evidence missing"] if status == "NEEDS_REVIEW" else [],
    )
    with pytest.raises(ValueError):
        handoff["host"].review(
            handoff["request"],
            canonical(h).encode(),
            handoff["candidate"]["hypothesis_id"],
            researcher_receipts=handoff["book"],
            capabilities=capabilities,
        )


@pytest.mark.parametrize("alter", ["request_id", "market", "hypothesis", "candidate", "raw_bytes"])
def test_d09_altered_identity_before_provider(handoff, spec, exercise, alter):
    _, agent, provider = exercise(spec, review="unknown-review")
    req, hypothesis, candidate = (
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
    )
    if alter in {"request_id", "market"}:
        q = parse(req)
        if alter == "request_id":
            q["request_id"] = "changed"
        else:
            q["market"]["asset"] = "ETHUSDT"
        req = canonical(q).encode()
    elif alter == "hypothesis":
        h = parse(hypothesis)
        h["candidates"][0]["statement"] += " changed"
        hypothesis = canonical(h).encode()
    elif alter == "candidate":
        candidate = "invented"
    else:
        req += b" "
    result = agent.run(req, hypothesis, candidate, review_reference=handoff["review"])
    assert result["status"] == "BLOCKED" and provider.calls == 0


def test_d09_host_review_cannot_be_self_granted(spec, exercise):
    result, _, provider = exercise(spec, host=DesignReviewHost())
    assert result["error_code"] == "HOST_REVIEW_REQUIRED" and provider.calls == 0


def test_d09_missing_or_boolean_review(spec, exercise):
    result, _, provider = exercise(spec, review=True)
    assert result["error_code"] == "HOST_REVIEW_REQUIRED" and provider.calls == 0


def test_d09_unknown_fields_in_response_are_not_permissions(exercise):
    result, _, provider = exercise(scenario="malicious")
    assert result["status"] == "BLOCKED" and result["specification"] is None
    assert provider.calls == 1 and result["receipt"]["operational_effects"] == []


@pytest.mark.parametrize(
    "scenario,state", [("timeout", "UNKNOWN"), ("error", "UNKNOWN"), ("truncated", "BLOCKED")]
)
def test_d10_failures_no_automatic_repair(handoff, exercise, scenario, state):
    result, agent, provider = exercise(scenario=scenario)
    assert result["status"] == state
    repeated = agent.run(
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        review_reference=handoff["review"],
    )
    assert repeated == result and provider.calls == 1


def test_d10_interruption_retains_uncertain_memory_entry(
    handoff, catalogue, tmp_path, capabilities
):
    from trading_lab_agents.designer_context import DesignerContext

    provider = FakeDesignerProvider(scenario="interrupted")
    agent = QuantStrategyDesigner(
        DesignerContext(catalogue[0].path, fixture_root=tmp_path),
        provider,
        handoff["book"],
        handoff["host"],
        capabilities,
    )
    with pytest.raises(KeyboardInterrupt):
        agent.run(
            handoff["request"],
            handoff["hypothesis"],
            handoff["candidate"]["hypothesis_id"],
            review_reference=handoff["review"],
        )
    result = agent.run(
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        review_reference=handoff["review"],
    )
    assert result["status"] == "UNKNOWN" and provider.calls == 1
    assert result["error_code"] == "SIMULATION_RECONCILIATION_REQUIRED"


def test_d10_concurrent_identical_request_invoked_once(handoff, exercise, spec):
    result, agent, provider = exercise(spec)

    def read(_):
        return agent.run(
            handoff["request"],
            handoff["hypothesis"],
            handoff["candidate"]["hypothesis_id"],
            review_reference=handoff["review"],
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(read, range(12)))
    assert outcomes == [result] * 12 and provider.calls == 1


def test_d10_results_and_exports_are_detached(handoff, exercise, spec):
    result, agent, provider = exercise(spec)
    original = deepcopy(result)
    result["specification"]["capital_policy"] = "FORGED"
    exported = handoff["book"].export(
        designer_operation_id("request_01", handoff["candidate"]["hypothesis_id"])
    )
    exported["history"].append({"state": "FORGED"})
    assert (
        agent.run(
            handoff["request"],
            handoff["hypothesis"],
            handoff["candidate"]["hypothesis_id"],
            review_reference=handoff["review"],
        )
        == original
    )
    assert provider.calls == 1


def test_d10_same_id_changed_bytes_conflicts_after_review(handoff, exercise, spec, capabilities):
    first, agent, provider = exercise(spec)
    request = parse(handoff["request"])
    request["objective"] += " changed"
    raw = canonical(request).encode()
    # The host cannot mint a fresh review from the previous byte receipt.
    with pytest.raises(ValueError):
        handoff["host"].review(
            raw,
            handoff["hypothesis"],
            handoff["candidate"]["hypothesis_id"],
            researcher_receipts=handoff["book"],
            capabilities=capabilities,
        )
    result = agent.run(
        raw,
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        review_reference=handoff["review"],
    )
    assert result["status"] == "BLOCKED" and provider.calls == 1
    assert (
        handoff["book"].export(
            designer_operation_id("request_01", handoff["candidate"]["hypothesis_id"])
        )["result"]
        == first
    )


def test_d08_verified_new_experiment_not_name_equivalence(handoff, capabilities, spec, exercise):
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
    spec["implementation_operation"] = "NEW_EXPERIMENT"
    spec["manifest"]["requires_new_strategy_code"] = False
    result, _, _ = exercise(spec, review=review)
    assert result["status"] == "COMPLETE", result
    assert result["specification"]["implementation_operation"] == "NEW_EXPERIMENT"


def test_d08_reuse_cannot_hide_new_logic(handoff, capabilities, spec, exercise):
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
    spec["implementation_operation"] = "NEW_EXPERIMENT"
    spec["manifest"]["requires_new_strategy_code"] = False
    expression = parse(spec["formulas"][0]["expression"])
    expression["operator"] = "SMA"
    spec["formulas"][0]["expression"] = canonical(expression)
    result, _, _ = exercise(spec, review=review)
    assert result["error_code"] == "REUSE_SIGNAL_MISMATCH"


def test_d09_arbitrary_provider_or_subclass_not_accepted(
    catalogue, tmp_path, handoff, capabilities
):
    from trading_lab_agents.designer_context import DesignerContext

    class Other(FakeDesignerProvider):
        pass

    with pytest.raises(TypeError):
        QuantStrategyDesigner(
            DesignerContext(catalogue[0].path, fixture_root=tmp_path),
            Other(),
            ReceiptBook(),
            handoff["host"],
            capabilities,
        )


def test_d10_new_book_is_new_simulation_not_durable_recovery(exercise, spec):
    a, _, p1 = exercise(spec, book=ReceiptBook())
    b, _, p2 = exercise(spec, book=ReceiptBook())
    assert a == b and p1.calls == p2.calls == 1


def test_d09_privacy_rejects_paths_and_credentials(spec, exercise):
    spec["notes"] = "C:/Users/private/hidden.sqlite3"
    result, _, _ = exercise(spec)
    assert result["error_code"] == "PRIVATE_RESPONSE_CONTEXT"


def test_d10_raw_bytes_and_hash_preserved(spec, exercise, handoff):
    raw = canonical(spec).encode() + b" "
    result, _, _ = exercise(raw)
    assert result["receipt"]["response_sha256"] == sha(raw)
    assert result["receipt"]["response_bytes"] == len(raw)


def test_d10_oversize_is_rejected_with_bounded_raw_evidence(exercise, handoff):
    raw = b" " * (64 * 1024 + 1)
    result, agent, provider = exercise(raw)
    assert result["error_code"] == "RESPONSE_LIMIT_EXCEEDED"
    assert result["receipt"]["response_sha256"] == sha(raw)
    assert result["receipt"]["response_bytes"] == len(raw)
    repeated = agent.run(
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        review_reference=handoff["review"],
    )
    assert repeated == result and provider.calls == 1
