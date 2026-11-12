import csv
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from trading_lab_orchestration import billing
from trading_lab_orchestration.audit_model import Budget
from trading_lab_orchestration.billing_snapshots import capture_baseline
from trading_lab_orchestration.cli import main
from trading_lab_orchestration.processes import safe_environment
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import file_hash


def test_admin_key_is_not_inherited_by_trial_children(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "simulated-admin")
    assert "OPENAI_ADMIN_KEY" not in safe_environment(tmp_path)


def csv_file(path, day, rows):
    fields = ["start_time", "end_time", *dict.fromkeys(k for row in rows for k in row)]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({"start_time": day, "end_time": day + 86400, **row})
    return path


def usage_row(model=billing.REDUCED, requests=1, input_tokens=1425, output_tokens=120):
    return {
        "model": model,
        "service_tier": "default",
        "project_id": "proj_fixture",
        "num_model_requests": requests,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cached_tokens": 0,
    }


def pending(budget, tag, usage, agent="research", *, baseline=None, maximum=4):
    call = budget.reserve("openai", f"openai-{agent}-v1:{tag}", maximum, once=True)
    receipt = {
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cached_input_tokens": usage["input_cached_tokens"],
    }
    budget.settle(call, None, json.dumps({"usage": receipt, "pricing": usage, **(baseline or {})}))
    return call


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    budget = Budget(Store(tmp_path / "ledger.sqlite3"))
    budget.open_month(0, "Isolated simulated billing")
    monkeypatch.setenv("TRADING_LAB_GLOBAL_API_DB", str(budget.store.path))
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    return budget


def utc_day(budget, call):
    row = next(row for row in budget.inspect()["calls"] if row["call_id"] == call)
    return (
        int(datetime.fromisoformat(row["created_at_utc"]).astimezone(UTC).timestamp())
        // 86400
        * 86400
    )


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        ("valid", None),
        ("delayed", "COST_NOT_AVAILABLE"),
        ("extra_usage", "ATTRIBUTION_UNCERTAIN"),
        ("adjustment", "ATTRIBUTION_UNCERTAIN"),
        ("repriced", "ATTRIBUTION_UNCERTAIN"),
        ("other_org", "ATTRIBUTION_UNCERTAIN"),
        ("other_project", "ATTRIBUTION_UNCERTAIN"),
        ("missing", "BASELINE_MISSING"),
        ("tampered", "ATTRIBUTION_UNCERTAIN"),
    ],
)
def test_snapshot_delta_archived_auditor_case(ledger, monkeypatch, scenario, reason):
    # The archived prior CSV is aggregate. Reconstruct comparable itemized fixture rows
    # with its token counts and check them against both real archived USD totals.
    project = "proj_fixture"
    organization = "org-fixture"
    model = "gpt-6.1-sol"
    old_model = usage_row(model, input_tokens=1019, output_tokens=387)
    old_mini = usage_row(requests=4, input_tokens=5453, output_tokens=583)
    first = pending(ledger, "earlier-sol", old_model)
    ledger.settle(first, 1, "Simulated confirmed prior cost")
    for idx, (inp, out) in enumerate(((1247, 183), (1421, 156), (1425, 120), (1360, 124))):
        mini = pending(ledger, str(idx), usage_row(input_tokens=inp, output_tokens=out))
        ledger.settle(mini, 1, "Simulated confirmed prior cost")
    before = True

    def cost_rows(usages):
        rows = []
        for usage in usages:
            rates = (
                ("0.000002", "0.00001") if usage["model"] == model else ("0.00000015", "0.00000060")
            )
            for direction, rate in zip(("input", "output"), rates, strict=True):
                quantity = usage[f"{direction}_tokens"]
                rows.append(
                    {
                        "organization_id": organization,
                        "project_id": project,
                        "line_item": f"{usage['model']}, {direction}",
                        "quantity_unit": "tokens",
                        "quantity": quantity,
                        "amount": {"value": str(quantity * Decimal(rate)), "currency": "usd"},
                    }
                )
        return rows

    earlier = cost_rows([old_model, old_mini])
    new_model = usage_row(model, requests=2, input_tokens=1904, output_tokens=624)
    updated = cost_rows([new_model, old_mini])
    assert sum(Decimal(r["amount"]["value"]) for r in earlier) == Decimal("0.00707575")
    assert sum(Decimal(r["amount"]["value"]) for r in updated) == Decimal("0.01121575")

    def get(endpoint, query, _key, org):
        assert org == organization and query["project_ids"] == [project]
        if endpoint == "usage/completions":
            rows = [old_model if before else new_model.copy(), old_mini]
            if not before and scenario == "extra_usage":
                rows[0]["num_model_requests"] += 1
        else:
            rows = earlier if before or scenario == "delayed" else updated
            if not before and scenario == "adjustment":
                rows = [*rows, updated[0] | {"line_item": "credit adjustment"}]
            if not before and scenario == "repriced":
                rows = [
                    updated[0] | {"amount": {"value": "0.004", "currency": "usd"}},
                    *updated[1:],
                ]
            if not before and scenario == "other_org":
                rows = [updated[0] | {"organization_id": "org-other"}, *updated[1:]]
        return json.dumps(
            {
                "has_more": False,
                "data": [
                    {
                        "start_time": query["start_time"],
                        "end_time": query["end_time"],
                        "results": rows,
                    }
                ],
            }
        ).encode()

    monkeypatch.setattr(billing, "_get", get)
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "simulated-admin")
    provider = SimpleNamespace(billing_scope=(organization, project))
    baseline = {} if scenario == "missing" else capture_baseline(ledger, provider, 1808)
    call = pending(
        ledger,
        "archived-audit",
        usage_row(model, input_tokens=885, output_tokens=237),
        "audit",
        baseline=baseline,
        maximum=1808,
    )
    if scenario == "tampered":
        Path(baseline["billing_baseline"]["path"]).write_text("{}", encoding="utf-8")
    before = False
    fresh = Budget(Store(ledger.store.path))
    result = billing.reconcile(
        fresh,
        call,
        project="proj_other" if scenario == "other_project" else project,
        admin=True,
        snapshots=True,
        apply=True,
    )
    if reason:
        assert (result["status"], result["reason_code"], result["ledger_status"]) == (
            "BLOCKED",
            reason,
            "UNKNOWN",
        )
        assert result["reserved_cents"] == 1808 and result["released_now_cents"] == 0
        with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
            fresh.reserve("openai", "another", 1)
        return
    assert result["status"] == "SETTLED" and result["released_now_cents"] == 1807
    assert Decimal(result["attribution"]["billed_usd"]) == Decimal("0.00414")
    assert result["actual_cents"] == 1 and fresh.available() == 1994
    monkeypatch.delenv("OPENAI_ADMIN_KEY")
    replay = billing.reconcile(fresh, call, project=project, admin=True, snapshots=True, apply=True)
    assert replay["status"] == "ALREADY_SETTLED" and replay["released_now_cents"] == 0


def test_cli_attributed_grouped_delta_then_replay(ledger, tmp_path, capsys):
    old = usage_row(input_tokens=1247, output_tokens=183)
    earlier = pending(ledger, "prior", old)
    day = utc_day(ledger, earlier)
    prior_usage = csv_file(tmp_path / "prior_usage.csv", day, [old])
    prior_costs = csv_file(
        tmp_path / "prior_costs.csv",
        day,
        [
            {"amount_value": "0.00029685", "amount_currency": "usd"},
        ],
    )
    ledger.settle(earlier, 1, f"Verified export SHA256 {file_hash(prior_costs)}")
    call = pending(ledger, "target", usage_row())
    use = csv_file(
        tmp_path / "usage.csv", day, [usage_row(requests=2, input_tokens=2672, output_tokens=303)]
    )
    cost = csv_file(
        tmp_path / "costs.csv",
        day,
        [
            {"amount_value": "0.00058260", "amount_currency": "usd"},
        ],
    )
    options = [
        call,
        "--usage-csv",
        str(use),
        "--costs-csv",
        str(cost),
        "--prior-usage-csv",
        str(prior_usage),
        "--prior-costs-csv",
        str(prior_costs),
        "--exclusive-billing-scope",
    ]
    before = ledger.inspect()
    for command, status, release in (
        ("api-budget-billing-doctor", "READY", 0),
        ("api-budget-billing-reconcile", "SETTLED", 3),
        ("api-budget-billing-reconcile", "ALREADY_SETTLED", 0),
    ):
        assert main(["--db", str(ledger.store.path), command, *options]) == 0
        result = json.loads(capsys.readouterr().out)
        assert (result["status"], result["released_now_cents"]) == (status, release)
        if status == "READY":
            assert ledger.inspect() == before
        if status == "SETTLED":
            assert result["attribution"]["billed_usd"] == "0.00028575"
            assert result["attribution"]["evidence"]["costs"]["sha256"] == file_hash(cost)
    assert len(ledger.inspect()["calls"]) == 2 and ledger.available() == 1998


@pytest.mark.parametrize("scenario", ["delayed", "ambiguous", "partial", "denied", "timeout"])
def test_unsafe_evidence_keeps_global_gate(ledger, tmp_path, monkeypatch, scenario):
    call = pending(ledger, "target", usage_row())
    day = utc_day(ledger, call)
    before = ledger.inspect()
    if scenario in {"denied", "timeout"}:

        class DeniedConnection:
            def __init__(self, host, timeout):
                assert host == "api.openai.com" and timeout == 15

            def request(self, method, path, headers):
                assert method == "GET" and path.startswith("/v1/organization/")

            def getresponse(self):
                if scenario == "timeout":
                    raise TimeoutError
                return SimpleNamespace(status=403)

            def close(self):
                pass

        monkeypatch.setenv("OPENAI_ADMIN_KEY", "simulated-key")
        monkeypatch.setattr(billing.http.client, "HTTPSConnection", DeniedConnection)
        opts = {"admin": True, "project": "proj_fixture"}
        message = "HTTP 403" if scenario == "denied" else "TimeoutError"
    else:
        row = usage_row(requests=2) if scenario == "ambiguous" else usage_row()
        use = csv_file(tmp_path / "use.csv", day, [row])
        cost = csv_file(
            tmp_path / "cost.csv",
            day,
            [
                {
                    "amount_value": {"delayed": "", "partial": "0.0001"}.get(
                        scenario, "0.00028575"
                    ),
                    "amount_currency": "usd",
                },
            ],
        )
        opts = {"usage_csv": use, "costs_csv": cost, "exclusive": True}
        message = {
            "delayed": "No billed cost",
            "ambiguous": "does not uniquely match",
            "partial": "does not match the sole",
        }[scenario]
    result = billing.reconcile(ledger, call, apply=True, **opts)
    assert result["status"] == "BLOCKED" and message in result["reason"]
    assert (
        result["reason_code"]
        == {
            "delayed": "COST_NOT_AVAILABLE",
            "ambiguous": "ATTRIBUTION_UNCERTAIN",
            "partial": "ATTRIBUTION_UNCERTAIN",
            "denied": "ADMIN_ACCESS_DENIED",
            "timeout": "BILLING_TIMEOUT",
        }[scenario]
    )
    assert result["released_now_cents"] == 0 and ledger.inspect() == before
    with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
        ledger.available()


def test_admin_itemized_auditor_cost_has_one_atomic_settlement(ledger, monkeypatch):
    model = "gpt-6.1-sol"
    usage = usage_row(model=model, input_tokens=1000, output_tokens=500)
    call = pending(ledger, "target", usage, agent="audit")
    day = utc_day(ledger, call)
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "simulated-key")
    barrier = Barrier(2)
    requests = []
    costs = [
        {
            "line_item": f"{model}, {field}",
            "quantity": quantity,
            "quantity_unit": "1000_tokens",
            "project_id": "proj_fixture",
            "amount": {"value": value, "currency": "usd"},
        }
        for field, quantity, value in (("input_tokens", 1, 0.002), ("output_tokens", 0.5, 0.005))
    ]

    class FakeConnection:
        def __init__(self, host, timeout):
            assert host == "api.openai.com"

        def request(self, method, path, headers):
            assert method == "GET"
            self.path = urlsplit(path).path
            requests.append(self.path)

        def getresponse(self):
            is_costs = self.path == "/v1/organization/costs"
            if is_costs:
                barrier.wait(timeout=5)
            payload = {
                "has_more": False,
                "next_page": None,
                "data": [
                    {
                        "start_time": day,
                        "end_time": day + 86400,
                        "results": costs if is_costs else [usage],
                    },
                ],
            }
            return SimpleNamespace(status=200, read=lambda _: json.dumps(payload).encode())

        def close(self):
            pass

    monkeypatch.setattr(billing.http.client, "HTTPSConnection", FakeConnection)

    def settle():
        return billing.reconcile(ledger, call, admin=True, project="proj_fixture", apply=True)

    with ThreadPoolExecutor(2) as pool:
        jobs = [pool.submit(settle) for _ in range(2)]
        results = [job.result() for job in jobs]
    assert {result["status"] for result in results} == {"SETTLED", "ALREADY_SETTLED"}
    assert sum(result["released_now_cents"] for result in results) == 2
    assert (
        sorted(requests)
        == ["/v1/organization/costs"] * 2 + ["/v1/organization/usage/completions"] * 2
    )
    assert ledger.available() == 1998
