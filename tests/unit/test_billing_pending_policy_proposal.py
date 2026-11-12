"""Executable proposal only. Every reservation is made in a pytest SQLite fixture."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import ROUND_CEILING
from pathlib import Path
from threading import Barrier

import pytest

from trading_lab_orchestration import billing
from trading_lab_orchestration.audit_model import MONTHLY_CAP_CENTS, Budget
from trading_lab_orchestration.billing import reconcile
from trading_lab_orchestration.contracts import canonical
from trading_lab_orchestration.research_intake import (
    REDUCED_INPUT_CAP,
    REDUCED_MODEL,
    REDUCED_OUTPUT_CAP,
    _reduced_cost,
)
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import file_hash, write_json


def verified_research_hold(row):
    if row["provider"] != "openai" or not row["purpose"].startswith("openai-research-v1:"):
        return False
    try:
        proof = json.loads(row["provenance"])
        root = Path(proof["dossier"])
        receipt_path = root / "provider-receipt.json"
        intent_path = root / "intent.json"
        if (
            file_hash(receipt_path) != proof["provider_receipt_sha256"]
            or file_hash(intent_path) != proof["intent_sha256"]
        ):
            return False
        receipt = json.loads(receipt_path.read_bytes())
        intent = json.loads(intent_path.read_bytes())
        quote = intent["pricing"]
        usage = receipt["usage"]
        inp, out = usage["input_tokens"], usage["output_tokens"]
        upper = _reduced_cost(REDUCED_INPUT_CAP, REDUCED_OUTPUT_CAP)["maximum_cents"]
        return (
            receipt["call_id"] == intent["call_id"] == row["call_id"]
            and receipt["status"] == proof["status"] == "SELECTION_RECORDED"
            and usage == proof["usage"]
            and quote == proof["pricing"]
            and quote["model"] == REDUCED_MODEL
            and quote["service_tier"] == "default"
            and quote["input_token_ceiling"] == REDUCED_INPUT_CAP
            and quote["output_token_limit"] == REDUCED_OUTPUT_CAP
            and type(inp) is int
            and type(out) is int
            and 0 <= inp <= REDUCED_INPUT_CAP
            and 0 <= out <= REDUCED_OUTPUT_CAP
            and quote["price_reviewed_utc"]
            <= row["created_at_utc"][:10]
            <= quote["price_expires_utc"]
            and quote["maximum_cents"] == row["reserved_cents"] == upper
        )
    except (OSError, ValueError, TypeError, KeyError):
        return False


class ProposedAuditBudget(Budget):
    """Exercise Budget.reserve's real transaction with the proposed admission rule."""

    def reserve(self, provider, purpose, maximum_cents, *, once=False):
        if provider != "openai" or not purpose.startswith("openai-audit-v1:"):
            raise ValueError("Proposal only permits the dependent OpenAI auditor")
        return super().reserve(provider, purpose, maximum_cents, once=True)

    @staticmethod
    def _available(conn, month):
        opening = conn.execute("SELECT * FROM api_months WHERE month=?", (month,)).fetchone()
        if not opening:
            raise ValueError("GLOBAL_API_ACCOUNTING_UNKNOWN")
        unsettled = conn.execute("SELECT * FROM api_calls WHERE status != 'SETTLED'").fetchall()
        if len(unsettled) > 1 or any(
            row["status"] != "UNKNOWN" or row["month"] != month or not verified_research_hold(row)
            for row in unsettled
        ):
            raise ValueError("UNKNOWN_API_SPEND")
        settled = conn.execute(
            "SELECT COALESCE(SUM(actual_cents),0) FROM api_calls "
            "WHERE month=? AND status='SETTLED'",
            (month,),
        ).fetchone()[0]
        held = sum(row["reserved_cents"] for row in unsettled)
        return MONTHLY_CAP_CENTS - opening["opening_spend_cents"] - settled - held


def seed_research(tmp_path, *, opening=0, scenario="verified"):
    budget = Budget(Store(tmp_path / "prototype.sqlite3"))
    budget.open_month(opening, "Simulated complete opening spend")
    hold = 3 if scenario == "unbounded" else 4
    call_id = budget.reserve("openai", "openai-research-v1:fixture", hold)
    if scenario == "in_flight":
        return budget, call_id, None
    root = tmp_path / "mock-receipt"
    root.mkdir()
    usage = (
        None
        if scenario == "no_response"
        else {
            "input_tokens": 1425,
            "output_tokens": 120,
            "cached_input_tokens": 0,
        }
    )
    status = "UNKNOWN_PROVIDER_OUTCOME" if usage is None else "SELECTION_RECORDED"
    pricing = {
        "model": REDUCED_MODEL,
        "service_tier": "default",
        "maximum_cents": hold,
        "input_token_ceiling": REDUCED_INPUT_CAP,
        "output_token_limit": REDUCED_OUTPUT_CAP,
        "price_reviewed_utc": "2000-01-01",
        "price_expires_utc": "9999-12-31",
    }
    intent = root / "intent.json"
    receipt = root / "provider-receipt.json"
    write_json(intent, {"call_id": call_id, "pricing": pricing})
    write_json(receipt, {"call_id": call_id, "status": status, "usage": usage})
    provenance = canonical(
        {
            "dossier": str(root),
            "intent_sha256": file_hash(intent),
            "provider_receipt_sha256": file_hash(receipt),
            "usage": usage,
            "pricing": pricing,
            "status": status,
        }
    )
    budget.settle(call_id, None, provenance)
    if scenario == "tampered":
        receipt.write_text("{}", encoding="utf-8")
    return budget, call_id, provenance


def test_proposed_auditor_can_reserve_without_liquidating_research(tmp_path):
    budget, research, _ = seed_research(tmp_path, opening=188)
    with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
        budget.available()
    proposal = ProposedAuditBudget(budget.store)
    assert proposal.available() == 1808
    audit = proposal.reserve("openai", "openai-audit-v1:fixture", 1808)
    assert [
        (row["call_id"], row["status"], row["reserved_cents"], row["actual_cents"])
        for row in budget.inspect()["calls"]
    ] == [
        (research, "UNKNOWN", 4, None),
        (audit, "RESERVED", 1808, None),
    ]
    with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
        proposal.reserve("openai", "openai-audit-v1:second", 1)


@pytest.mark.parametrize("scenario", ["no_response", "in_flight", "tampered", "unbounded"])
def test_proposal_blocks_unverifiable_or_unbounded_outcomes(tmp_path, scenario):
    budget, _, _ = seed_research(tmp_path, scenario=scenario)
    before = budget.inspect()
    with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
        ProposedAuditBudget(budget.store).reserve("openai", "openai-audit-v1:fixture", 1)
    assert budget.inspect() == before


def test_proposal_refuses_auditor_when_first_hold_leaves_one_cent_too_little(tmp_path):
    budget, _, _ = seed_research(tmp_path, opening=189)
    with pytest.raises(ValueError, match="GLOBAL_API_BUDGET_EXHAUSTED"):
        ProposedAuditBudget(budget.store).reserve("openai", "openai-audit-v1:fixture", 1808)
    assert len(budget.inspect()["calls"]) == 1


def test_concurrent_auditor_reservations_cannot_overbook(tmp_path):
    budget, _, _ = seed_research(tmp_path, opening=188)
    proposal = ProposedAuditBudget(budget.store)
    start = Barrier(2)

    def reserve(name):
        start.wait(timeout=5)
        try:
            return proposal.reserve("openai", f"openai-audit-v1:{name}", 1808)
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(2) as workers:
        outcomes = list(workers.map(reserve, ["first", "second"]))
    assert sum(value.startswith("call_") for value in outcomes) == 1
    assert outcomes.count("UNKNOWN_API_SPEND") == 1
    assert sum(row["reserved_cents"] for row in budget.inspect()["calls"]) + 188 == 2000


def test_repeat_individually_attributed_settlement_releases_only_once(tmp_path):
    budget, research, provenance = seed_research(tmp_path, opening=188)
    proposal = ProposedAuditBudget(budget.store)
    audit = proposal.reserve("openai", "openai-audit-v1:fixture", 1808)
    budget.settle(audit, None, "Simulated auditor receipt awaiting independent attribution")
    diagnostic = reconcile(budget, research)
    assert diagnostic["status"] == "BLOCKED"
    assert "More than one unsettled" in diagnostic["reason"]
    assert budget.settle(
        research, 1, "Simulated itemized charge for research", expected_unknown=provenance
    )
    first = budget.inspect()
    assert not budget.settle(
        research, 1, "Simulated itemized charge for research", expected_unknown=provenance
    )
    assert budget.inspect() == first
    with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
        budget.available()
    assert budget.settle(
        audit,
        2,
        "Simulated itemized charge for audit",
        expected_unknown="Simulated auditor receipt awaiting independent attribution",
    )
    assert budget.available() == 1809


def settle_itemized_pair_prototype(budget, ids, day, usage_csv, costs_csv, project):
    """Test-only cohort settlement. Both bills must be uniquely attributable before any update."""
    usage, costs, refs = billing.csv_evidence(usage_csv, costs_csv, day)
    with budget.store.transaction() as conn:
        rows = [
            conn.execute("SELECT * FROM api_calls WHERE call_id=?", (cid,)).fetchone()
            for cid in ids
        ]
        if all(row["status"] == "SETTLED" for row in rows):
            for row in rows:
                recorded = json.loads(json.loads(row["provenance"])["invoice_reference"])
                if recorded["evidence"] != refs:
                    raise ValueError("Replay requires the original evidence")
            return "ALREADY_SETTLED", (0, 0)
        if any(row["status"] != "UNKNOWN" for row in rows):
            return "BLOCKED", (0, 0)
        try:
            receipts = billing._ledger_usage(rows)
            if len({receipt["model"] for receipt in receipts}) != 2 or any(
                receipt["service_tier"] != "default" or receipt["input_cached_tokens"] != 0
                for receipt in receipts
            ):
                raise billing.EvidenceUnavailable(
                    "Receipts do not match distinct text billing groups"
                )
            if billing._usage(usage, project) != billing._usage(receipts, None):
                raise billing.EvidenceUnavailable("Usage does not match the two receipts")
            scoped_costs = billing._costs(costs, project)
            if len(scoped_costs) != 4:
                raise billing.EvidenceUnavailable("Missing distinct billed input and output lines")
            amounts = [billing._token_lines(scoped_costs, receipt) for receipt in receipts]
            multiplier = (
                billing.EUR_PER_USD_CEILING * billing.REGIONAL_CEILING * billing.TAX_CEILING
            )
            cents = [
                int((amount * multiplier * 100).to_integral_value(rounding=ROUND_CEILING))
                for amount in amounts
            ]
            if any(charge > row["reserved_cents"] for row, charge in zip(rows, cents, strict=True)):
                raise billing.EvidenceUnavailable("Charge exceeds reservation")
        except billing.EvidenceUnavailable:
            return "BLOCKED", (0, 0)
        released = []
        for row, charge, amount in zip(rows, cents, amounts, strict=True):
            proof = canonical({"evidence": refs, "billed_usd": str(amount), "project_id": project})
            provenance = canonical(
                {"prior_calculation": row["provenance"], "invoice_reference": proof}
            )
            conn.execute(
                "UPDATE api_calls SET status='SETTLED', actual_cents=?, provenance=? "
                "WHERE call_id=?",
                (charge, provenance, row["call_id"]),
            )
            released.append(row["reserved_cents"] - charge)
        return "SETTLED", tuple(released)


@pytest.mark.parametrize("itemized", [True, False], ids=["itemized", "aggregate"])
def test_two_same_day_calls_need_individually_attributable_costs(tmp_path, itemized):
    budget, research, _ = seed_research(tmp_path)
    auditor_model = "gpt-6.1-sol"
    audit = ProposedAuditBudget(budget.store).reserve("openai", "openai-audit-v1:fixture", 1808)
    budget.settle(
        audit,
        None,
        canonical(
            {
                "usage": {"input_tokens": 1000, "output_tokens": 500, "cached_input_tokens": 0},
                "pricing": {"model": auditor_model, "service_tier": "default"},
            }
        ),
    )
    before = budget.inspect()
    days = {
        int(datetime.fromisoformat(row["created_at_utc"]).timestamp()) // 86400 * 86400
        for row in before["calls"]
    }
    (day,) = days
    project = "proj_fixture"
    prefix = f"{day},{day + 86400},{project}"
    usage = tmp_path / "usage.csv"
    usage.write_text(
        "start_time,end_time,project_id,model,service_tier,num_model_requests,"
        "input_tokens,output_tokens,input_cached_tokens\n"
        f"{prefix},{REDUCED_MODEL},default,1,1425,120,0\n"
        f"{prefix},{auditor_model},default,1,1000,500,0\n",
        encoding="utf-8",
    )
    costs = tmp_path / "costs.csv"
    cost_rows = (
        f'{prefix},"{REDUCED_MODEL}, input_tokens",1425,tokens,0.00021375,usd\n'
        f'{prefix},"{REDUCED_MODEL}, output_tokens",120,tokens,0.000072,usd\n'
        f'{prefix},"{auditor_model}, input_tokens",1000,tokens,0.002,usd\n'
        f'{prefix},"{auditor_model}, output_tokens",500,tokens,0.005,usd\n'
        if itemized
        else f"{prefix},,,,0.00728575,usd\n"
    )
    costs.write_text(
        "start_time,end_time,project_id,line_item,quantity,quantity_unit,amount_value,amount_currency\n"
        + cost_rows,
        encoding="utf-8",
    )
    assert reconcile(budget, research, usage_csv=usage, costs_csv=costs)["status"] == "BLOCKED"
    args = (budget, (research, audit), day, usage, costs, project)
    first = settle_itemized_pair_prototype(*args)
    after_first = budget.inspect()
    second = settle_itemized_pair_prototype(*args)
    assert budget.inspect() == after_first
    if itemized:
        assert first == ("SETTLED", (3, 1806))
        assert second == ("ALREADY_SETTLED", (0, 0))
        assert {row["call_id"]: row["actual_cents"] for row in after_first["calls"]} == {
            research: 1,
            audit: 2,
        }
        assert budget.available() == 1997
    else:
        assert first == second == ("BLOCKED", (0, 0))
        assert after_first == before
        assert sum(row["reserved_cents"] for row in after_first["calls"]) == 1812
        with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
            budget.available()
