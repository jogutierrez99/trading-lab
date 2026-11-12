"""The model and billing ledger are simulated. No network or trading workloads."""

import json
from pathlib import Path

import pytest

from trading_lab_orchestration import audit_openai
from trading_lab_orchestration.audit_model import Budget
from trading_lab_orchestration.cli import main
from trading_lab_orchestration.research_intake import QUEUE_FACTS, REDUCED_MODEL, ingest, load_batch
from trading_lab_orchestration.store import Store

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/orchestration/research_batch_smoke.json"
DIRECT = EXAMPLE.with_name("research_batch_direct_queue_v2.json")


class FakeProvider:
    name = "openai"
    model = "gpt-6.1-sol"

    def __init__(
        self, idea="breakout_synthetic", *, timeout=False, model="gpt-6.1-sol", missing=()
    ):
        self.idea = idea
        self.timeout = timeout
        self.model = model
        self.missing = list(missing)
        self.calls = 0

    def post(self, body):
        self.calls += 1
        request = json.loads(body)
        assert request["store"] is False and request["tools"] == []
        assert request["model"] == self.model
        assert request["max_output_tokens"] == (1200 if self.model == REDUCED_MODEL else 2400)
        assert request["truncation"] == "disabled"
        assert ("reasoning" in request) == (self.model != REDUCED_MODEL)
        assert request["text"]["format"]["strict"] is True
        missing_items = request["text"]["format"]["schema"]["properties"]["missing"]["items"]
        assert "liquidity_assumption" in missing_items["enum"]
        if self.timeout:
            raise TimeoutError
        selection = {
            "idea_id": self.idea,
            "title": "Ruptura sintética",
            "rationale": "Comprueba el registro manual con un caso didáctico.",
            "limitations": ["Economic evidence and robustness results are pending execution."],
            "missing": self.missing,
        }
        return {
            "model": self.model,
            "service_tier": "default",
            "status": "completed",
            "usage": {"input_tokens": 400, "output_tokens": 100},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(selection)}],
                }
            ],
        }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from datetime import date

    monkeypatch.setattr(audit_openai, "PRICE_REVIEWED", date.min)
    monkeypatch.setattr(audit_openai, "PRICE_EXPIRES", date.max)
    budget = Budget(Store(tmp_path / "global/budget.sqlite"))
    budget.open_month(0, "Simulated ledger only")
    return budget, tmp_path / "queue/queue.sqlite", tmp_path / "artifacts"


def test_cli_diagnostic_and_repeat_one_call_one_queued_task(setup, monkeypatch, capsys):
    budget, queue, artifacts = setup
    provider = FakeProvider("sawtooth_cross_1h")
    monkeypatch.setenv("TRADING_LAB_GLOBAL_API_DB", str(budget.store.path))
    monkeypatch.setattr(audit_openai, "load_openai_key", lambda _: "fake")
    monkeypatch.setattr(audit_openai, "OpenAIResponses", lambda _: provider)
    options = [str(DIRECT), "--budget-db", str(budget.store.path)]
    assert main(["research-doctor", *options]) == 0
    diagnostic = json.loads(capsys.readouterr().out)
    assert diagnostic["pricing"]["maximum_cents"] == 1811
    assert not queue.exists() and provider.calls == 0
    command = [
        "--db",
        str(queue),
        "research-intake",
        *options,
        "--artifacts",
        str(artifacts),
        "--confirm-maximum-cents",
        "1811",
    ]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert first["status"] == "REGISTERED" and first["queue_status"] == "QUEUED"
    assert provider.calls == 1 and len(budget.inspect()["calls"]) == 1
    with Store(queue).connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM tasks").fetchone()[0] == "QUEUED"
    assert (Path(first["dossier"]) / "source.json").is_file()
    budget.settle(first["call_id"], 1, "Simulated billing receipt")
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert provider.calls == 1


def test_direct_queue_reduced_profile_checks_budget_and_replays(setup, monkeypatch, capsys):
    budget, queue, artifacts = setup
    provider = FakeProvider("sawtooth_cross_1h", model=REDUCED_MODEL, missing=QUEUE_FACTS)
    monkeypatch.setenv("TRADING_LAB_GLOBAL_API_DB", str(budget.store.path))
    monkeypatch.setattr(audit_openai, "load_openai_key", lambda _: "fake")
    monkeypatch.setattr(audit_openai, "OpenAIResponses", lambda _, model: provider)
    options = [str(DIRECT), "--budget-db", str(budget.store.path), "--profile", "reduced"]
    command = [
        "--db",
        str(queue),
        "research-intake",
        *options,
        "--artifacts",
        str(artifacts),
        "--confirm-maximum-cents",
        "4",
    ]
    pending = budget.reserve("openai", "previous-unreconciled", 1811)
    budget.settle(pending, None, "simulated missing billing evidence")
    assert main(command) == 2
    assert "UNKNOWN_API_SPEND" in capsys.readouterr().out
    assert provider.calls == 0 and not queue.exists()
    budget.settle(pending, 1, "simulated billing evidence")
    assert main(["research-doctor", *options]) == 0
    pricing = json.loads(capsys.readouterr().out)["pricing"]
    assert (pricing["input_token_ceiling"], pricing["maximum_cents"]) == (128_000, 4)
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(command) == 0
    second = json.loads(capsys.readouterr().out)
    assert first == second and first["status"] == "REGISTERED"
    assert first["missing"] == [] and first["model_reported_missing"] == list(QUEUE_FACTS)
    assert provider.calls == 1
    manifest = json.loads((Path(first["dossier"]) / "manifest.json").read_text(encoding="utf-8"))
    assumption = load_batch(DIRECT).ideas[0].facts["liquidity_assumption"]
    assert assumption in manifest["execution_assumptions"]["intrabar_policy"]
    assert (
        "Economic evidence and robustness results are pending execution." in manifest["limitations"]
    )
    with Store(queue).connection() as conn:
        assert [tuple(row) for row in conn.execute("SELECT task_id,status FROM tasks")] == [
            (first["task_id"], "QUEUED"),
        ]
        assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM executions").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("field_path", "value", "diagnostic"),
    [
        (("liquidity_assumption",), None, "liquidity_assumption"),
        (("liquidity_assumption",), 42, "liquidity_assumption"),
        (
            ("execution_assumptions", "slippage_pct"),
            None,
            "execution_assumptions.slippage_pct: missing",
        ),
        (
            ("execution_assumptions", "slippage_pct"),
            "0.03",
            "execution_assumptions.slippage_pct: float_type",
        ),
        (
            ("data_requirements", "funding_policy"),
            "REQUIRED",
            "Synthetic funding must be NOT_MODELLED",
        ),
    ],
)
def test_invalid_source_blocks_despite_complete_model_response(
    setup, field_path, value, diagnostic
):
    budget, queue, artifacts = setup
    source = json.loads(DIRECT.read_text(encoding="utf-8"))
    facts = source["ideas"][0]["facts"]
    for field in field_path[:-1]:
        facts = facts[field]
    if value is None:
        facts.pop(field_path[-1])
    else:
        facts[field_path[-1]] = value
    incomplete = artifacts.parent / "incomplete.json"
    incomplete.write_text(json.dumps(source), encoding="utf-8")
    provider = FakeProvider("sawtooth_cross_1h", model=REDUCED_MODEL)
    result = ingest(
        load_batch(incomplete), budget, queue, artifacts, provider, 4, profile="reduced"
    )
    assert result["status"] == "NEEDS_REVIEW" and result["task_id"] is None
    assert any(diagnostic in issue for issue in result["missing"])
    assert provider.calls == 1 and not queue.exists()


@pytest.mark.parametrize(
    ("idea", "timeout", "status"),
    [
        ("mean_reversion_notes", False, "NEEDS_REVIEW"),
        ("invented", False, "NEEDS_REVIEW"),
        (None, False, "NEEDS_REVIEW"),
        ("breakout_synthetic", True, "UNKNOWN_PROVIDER_OUTCOME"),
    ],
)
def test_review_and_uncertain_results_are_cached(setup, idea, timeout, status):
    budget, queue, artifacts = setup
    batch = load_batch(EXAMPLE)
    provider = FakeProvider(idea, timeout=timeout)
    result = ingest(batch, budget, queue, artifacts, provider, 1811)
    assert result["status"] == status and result["task_id"] is None
    assert ingest(batch, budget, queue, artifacts, None, 1811) == result
    assert provider.calls == 1 and not queue.exists()
    assert budget.inspect()["calls"][0]["status"] == "UNKNOWN"
    with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
        budget.available()


def test_missing_key_wrong_confirmation_and_budget_exhaustion(setup):
    budget, queue, artifacts = setup
    batch = load_batch(EXAMPLE)
    provider = FakeProvider()
    with pytest.raises(ValueError, match="OPENAI_API_KEY_ABSENT"):
        ingest(batch, budget, queue, artifacts, None, 1811)
    with pytest.raises(ValueError, match="Confirm the exact"):
        ingest(batch, budget, queue, artifacts, provider, 1)
    initial = budget.reserve("simulated", "prior", 500)
    budget.settle(initial, 500, "simulated")
    with pytest.raises(ValueError, match="GLOBAL_API_BUDGET_EXHAUSTED"):
        ingest(batch, budget, queue, artifacts, provider, 1811)
    assert provider.calls == 0 and not queue.exists()
