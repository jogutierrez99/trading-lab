"""Representative synthetic catalogue volume and compound audit integration."""

from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

import pytest

from trading_lab_agents.receipts import ReceiptBook
from trading_lab_agents.validator import QuantValidator
from trading_lab_agents.validator_context import ValidatorContext
from trading_lab_agents.validator_provider import FakeValidatorProvider
from trading_lab_catalog.models import Bundle, Decision, Experiment, Strategy, Version
from trading_lab_orchestration.contracts import canonical

from .conftest import create_fixture, inventory
from .test_policy import packet_for


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"engine": "other_engine"}, "engine"),
        ({"engine_version": "2"}, "engine_version"),
    ],
)
def test_v04_distinct_runners_cannot_be_ranked(fixture_factory, exercise, changes, reason):
    data = fixture_factory(paired=True, comparable=True, second_updates={"run_updates": changes})
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    comp = packet_for(data, book)["catalogue"]["comparison"]
    assert comp["comparison_status"] == "NOT_COMPARABLE" and reason in comp["condition_differences"]
    assert comp["winner"] is None
    assert len(result["receipt"]["source_verdict_sha256"]) == 2


def test_comparable_with_limitations_keeps_insufficiency(fixture_factory, exercise):
    data = fixture_factory(paired=True, comparable=True)
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    assert (
        packet_for(data, book)["catalogue"]["comparison"]["comparison_status"]
        == "COMPARABLE_WITH_LIMITATIONS"
    )
    assert any("Small trade samples" in s for s in result["assessment"]["limitations"])


def test_v05_alternative_scenarios_across_runs_keep_warning(fixture_factory, exercise):
    data = fixture_factory(
        paired=True, comparable=True, second_updates={"case_updates": {0: {"scenario": "adverse"}}}
    )
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    assert any("alternative cost scenarios" in s for s in result["assessment"]["limitations"])
    packet = packet_for(data, book)
    warning = next(o for o in packet["policy"]["obligations"] if o["code"] == "SCENARIOS")
    assert len(warning["references"]) == 2


def test_40_strategy_catalogue_is_bounded_and_read_only(tmp_path, record_property):
    data = create_fixture(tmp_path / "representative")
    strategies, versions, experiments, decisions = [], [], [], []
    for i in range(39):
        sid, vid, eid = f"unrelated{i}", f"version{i}", f"experiment{i}"
        strategies.append(
            Strategy(
                id=sid,
                name=f"Synthetic {i}",
                source="fixture",
                description="Synthetic unrelated research",
            )
        )
        versions.append(
            Version(
                id=vid,
                strategy_id=sid,
                semantic_version="1.0.0",
                implementation_reference="fixture",
                code_sha256="a" * 64,
            )
        )
        experiments.append(
            Experiment.model_validate(
                {
                    **data["bundle"].experiments[0].model_dump(),
                    "id": eid,
                    "version_id": vid,
                    "asset": "ETHUSDT",
                }
            )
        )
        decisions.append(
            Decision(
                id=f"decision{i}",
                strategy_id=sid,
                version_id=vid,
                category="RESEARCH",
                verdict="PENDING",
                reasoning="Synthetic pending work",
                limitations=["Synthetic only"],
                decided_by="fixture",
                decided_at_utc=None,
            )
        )
    data["store"].ingest(
        Bundle(
            strategies=strategies,
            versions=versions,
            experiments=experiments,
            research_decisions=decisions,
        ),
        source="synthetic volume fixture",
    )
    before = inventory(data["store"].path.parent)
    provider, book = FakeValidatorProvider(), ReceiptBook()
    agent = QuantValidator(
        ValidatorContext(data["store"].path, fixture_root=data["root"]), provider, book
    )
    start = perf_counter()
    result = agent.run(canonical(data["request"]).encode(), sources=data["sources"])
    elapsed = perf_counter() - start
    assert result["status"] == "COMPLETE", result
    assert inventory(data["store"].path.parent) == before
    assert result["receipt"]["catalogue_metrics"] == {"queries": 3, "captures": 1}
    assert result["receipt"]["context_bytes"] <= 65536 and provider.calls == 1
    assert "unrelated0" not in canonical(packet_for(data, book))
    record_property("representative_strategies", 40)
    record_property("representative_experiments", 40)
    record_property("representative_decisions", 40)
    record_property("capture_and_validation_seconds", elapsed)
    record_property("context_bytes", result["receipt"]["context_bytes"])
    record_property("response_bytes", result["receipt"]["response_bytes"])
    record_property("queries", 3)
    record_property("pagination", "compound API; exact runs; no enumerated pages")


def test_invalid_sources_never_reuse_receipt_under_new_bytes(dossier, exercise):
    from .test_evidence import anchored, remake

    result, agent, provider, _ = exercise(dossier)
    assert result["status"] == "COMPLETE"
    new = anchored(dossier, remake(dossier, raw=dossier["raw_verdict"] + b" "))
    second = agent.run(canonical(new["request"]).encode(), sources=new["sources"])
    assert second["status"] == "CONFLICT" and provider.calls == 1


def test_concurrent_fixture_ingestion_requires_complete_recapture(tmp_path, monkeypatch):
    data = create_fixture(tmp_path / "concurrent-writer")
    context = ValidatorContext(data["store"].path, fixture_root=data["root"])
    original = context._profile.query
    calls = []
    after_writer = None

    def query(operation, **args):
        nonlocal after_writer
        response = original(operation, **args)
        calls.append(response["checkpoint"])
        if len(calls) == 1:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(
                    data["store"].ingest,
                    Bundle(
                        strategies=[
                            Strategy(
                                id="new",
                                name="Concurrent fixture",
                                description="Controlled writer only",
                                source="fixture",
                            )
                        ]
                    ),
                    "synthetic concurrent writer",
                ).result(timeout=5)
            after_writer = inventory(data["store"].path.parent)
        return response

    monkeypatch.setattr(context._profile, "query", query)
    book, provider = ReceiptBook(), FakeValidatorProvider()
    agent = QuantValidator(context, provider, book)
    result = agent.run(canonical(data["request"]).encode(), sources=data["sources"])
    assert result["status"] == "COMPLETE", result
    assert result["receipt"]["catalogue_metrics"] == {"queries": 5, "captures": 2}
    assert calls[0] != calls[1] and len(set(calls[1:])) == 1
    assert packet_for(data, book)["catalogue"]["checkpoint"] == calls[-1]
    assert inventory(data["store"].path.parent) == after_writer and provider.calls == 1
