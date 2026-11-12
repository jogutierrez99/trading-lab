import pytest

from scripts.run_flow1_acceptance import AUDIT_MAX, Stopped, finish, wait_billing


def test_unattended_handoff_and_replay():
    quote = {
        "status": "READY",
        "available_cents": 1990,
        "pricing": {
            "model": "gpt-6.1-sol",
            "input_token_ceiling": 1050000,
            "output_token_limit": 1200,
            "maximum_cents": AUDIT_MAX,
        },
    }
    pending = {"status": "READY_FOR_AUDITOR_PREFLIGHT", "audit_id": "audit"}
    finished = {"status": "NOTICE_PREPARED", "notification_id": "same-draft"}
    settled = {"ledger_status": "SETTLED"}
    replay = {"status": "ALREADY_SETTLED", "released_now_cents": 0}
    dispatched = []
    readings = iter(
        [
            pending,
            finished | {"billing": settled},
            finished | {"billing": settled | replay},
            finished,
            finished | {"billing": settled | replay},
            finished | {"billing": settled | replay},
        ]
    )

    def dispatch(audit_id):
        dispatched.append(audit_id)
        return {"call_id": "auditor"}

    args = (
        lambda _: next(readings),
        lambda _: quote,
        dispatch,
        lambda: {"call_id": "auditor"},
        lambda state: state["notification_id"],
        "research",
        5,
        10,
    )
    assert finish(*args)["verification"] == "same-draft"
    assert finish(*args)["verification"] == "same-draft"
    assert dispatched == ["audit"]


@pytest.mark.parametrize(
    "reason, sleeps",
    [
        ("COST_NOT_AVAILABLE", [5, 2]),
        ("BILLING_TIMEOUT", [5, 2]),
        ("ATTRIBUTION_UNCERTAIN", []),
    ],
)
def test_wait_is_bounded_and_stops_on_ambiguity(reason, sleeps):
    elapsed = []
    state = {"status": "WAITING_BILLING", "billing": {"reason_code": reason}}
    with pytest.raises(Stopped) as exc:
        wait_billing(
            lambda _: state, "research", 5, 7, clock=lambda: sum(elapsed), sleep=elapsed.append
        )
    assert elapsed == sleeps
    assert exc.value.result == {"stage": "billing", **state, "poll_seconds": sum(sleeps)}
