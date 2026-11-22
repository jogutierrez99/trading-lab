"""M01/M02/L01 regressions over disposable evidence, never production data."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy

import pytest

from trading_lab_agents.context import ContextLimits
from trading_lab_agents.receipts import ReceiptBook
from trading_lab_agents.validator import QuantValidator
from trading_lab_agents.validator_context import ValidatorContext
from trading_lab_agents.validator_provider import FakeValidatorProvider
from trading_lab_catalog.verification import parse, sha
from trading_lab_orchestration.contracts import canonical

from . import conftest as fixtures
from .test_evidence import anchored, remake
from .test_policy import packet_for


def scientific_source(data, *, searches=12, variants=12, risk="Discovery used observed periods"):
    verdict = deepcopy(data["verdict"])
    verdict["observations"]["search_history"] = {
        "known_searches": searches,
        "known_variants": variants,
        "prior_work": "Synthetic discovery history",
    }
    verdict["observations"]["selection_history"]["holdout_risk"] = risk
    return anchored(data, remake(data, verdict=verdict))


def config_source(
    fixture_factory,
    monkeypatch,
    *,
    matches=False,
    include_pin=True,
    protocol="StudyBackend v1 / lab_experiment_v1",
):
    resolved = {"parameters": {"window": 20}, "scope": "SYNTHETIC"}
    raw = canonical(resolved).encode()
    original = fixtures.Experiment

    def experiment(**kwargs):
        return original(
            **{
                **kwargs,
                "configuration_sha256": sha(raw) if matches else "e" * 64,
                "experimental_protocol": protocol,
            }
        )

    monkeypatch.setattr(fixtures, "Experiment", experiment)
    data = fixture_factory()
    verdict, documents = deepcopy(data["verdict"]), dict(data["documents"])
    if include_pin:
        documents["native:resolved.json"] = raw
        verdict["references"]["native:resolved.json"] = {
            "path": "private synthetic reference",
            "sha256": sha(raw),
        }
        verdict["observations"]["resolved_configuration"] = resolved
    return anchored(data, remake(data, verdict=verdict, documents=documents))


class InterruptHistory(list):
    def __init__(self, values, state):
        super().__init__(values)
        self.target = state

    def append(self, item):
        if item.get("state") == self.target:
            raise KeyboardInterrupt("Synthetic host interruption")
        return super().append(item)


def interrupt_history(book, state):
    original = book.claim

    @contextmanager
    def claim(*a, **kw):
        with original(*a, **kw) as pair:
            entry, new = pair
            if new:
                entry.history = InterruptHistory(entry.history, state)
            yield pair

    book.claim = claim


def test_m01_reproduces_known_12_12_history_loss(dossier, exercise):
    data = scientific_source(dossier)
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    primary = packet_for(data, book)["catalogue"]["primary_audits"][0]
    history = primary["scientific_history"]
    assert history["search_history"]["known_searches"] == 12
    assert history["search_history"]["known_variants"] == 12
    assert history["selection_history"]["holdout_risk"] == "Discovery used observed periods"
    assert any(
        '"known_searches":12' in s and "observed periods" in s
        for s in result["assessment"]["limitations"]
    )


def test_m02_reproduces_configuration_mismatch(fixture_factory, monkeypatch, exercise):
    data = config_source(fixture_factory, monkeypatch)
    result, _, provider, _ = exercise(data)
    assert (
        result["status"] == "BLOCKED" and result["error_code"] == "AUDIT_CONFIGURATION_PIN_MISMATCH"
    ), result
    assert provider.calls == 0
    detail = result["receipt"]["evidence_diagnostic"]
    assert detail["catalogue_sha256"] == "e" * 64
    assert (
        detail["source_sha256"]
        == data["sources"][0].verdict().references["native:resolved.json"].sha256
    )


def test_l01_reproduces_interrupt_after_context_before_call(dossier):
    book, provider = ReceiptBook(), FakeValidatorProvider()
    interrupt_history(book, "RESERVED_SIMULATED")
    agent = QuantValidator(
        ValidatorContext(dossier["store"].path, fixture_root=dossier["root"]), provider, book
    )
    raw = canonical(dossier["request"]).encode()
    with pytest.raises(KeyboardInterrupt):
        agent.run(raw, sources=dossier["sources"])
    result = agent.run(raw, sources=dossier["sources"])
    assert result["status"] == "UNKNOWN"
    assert provider.calls == result["receipt"]["simulated_invocations"] == 0
    assert agent.run(raw, sources=dossier["sources"]) == result


@pytest.mark.parametrize(
    "value,availability",
    [
        ("absent", "ABSENT"),
        (None, "NULL"),
        ({}, "PRESENT"),
        ({"known_searches": None, "known_variants": None}, "PRESENT"),
        ({"known_searches": 0, "known_variants": 0}, "PRESENT"),
    ],
)
def test_m01_absence_null_and_zero_are_distinct(dossier, exercise, value, availability):
    verdict = deepcopy(dossier["verdict"])
    if value != "absent":
        verdict["observations"]["search_history"] = value
    data = anchored(dossier, remake(dossier, verdict=verdict))
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    primary = packet_for(data, book)["catalogue"]["primary_audits"][0]
    h = primary["scientific_history"]["search_history"]
    assert h["availability"] == availability
    assert h["known_searches"] == (
        0 if isinstance(value, dict) and value.get("known_searches") == 0 else None
    )
    assert h["fields_present"] == (sorted(value) if isinstance(value, dict) else [])


@pytest.mark.parametrize("counter", [-1, True, "12", 12.0])
def test_m01_strict_multiplicity_types(dossier, exercise, counter):
    data = scientific_source(dossier, searches=counter)
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == "AUDIT_HISTORY_INVALID" and provider.calls == 0


def test_m01_selection_provenance_and_original_policies(dossier, exercise):
    data = scientific_source(dossier)
    result, _, _, book = exercise(data)
    primary = packet_for(data, book)["catalogue"]["primary_audits"][0]
    h = primary["scientific_history"]
    assert h["reference_id"] == primary["reference_id"]
    assert h["verdict_sha256"] == data["sources"][0].snapshot()["expected_sha256"]
    assert result["receipt"]["source_verdict_sha256"] == [h["verdict_sha256"]]
    assert any("CONSUMED" in s for s in result["assessment"]["limitations"])
    assert any("RESET_PER_SEGMENT" in s for s in result["assessment"]["limitations"])
    assert result["assessment"]["model_review"]["verdict"] == "NO_DECISION"


@pytest.mark.parametrize("mode", ["omit", "contradict"])
def test_m01_provider_cannot_drop_or_reduce_known_history(dossier, exercise, mode):
    data = scientific_source(dossier)
    first, *_ = exercise(data)
    a = first["assessment"]
    if mode == "omit":
        a["limitations"] = [
            s for s in a["limitations"] if not s.startswith("Scientific selection history:")
        ]
        a["model_review"]["uncertainties"] = list(a["limitations"])
    else:
        finding = parse(a["model_review"]["findings"][0])
        finding["data"]["scientific_history"]["search_history"]["known_searches"] = 5
        a["model_review"]["findings"][0] = canonical(finding)
    result, *_ = exercise(data, provider=FakeValidatorProvider(response=canonical(a).encode()))
    assert result["status"] == "BLOCKED" and result["assessment"] is None


def test_m01_period_disagreement_requires_review(dossier, exercise):
    data = scientific_source(dossier)
    verdict = data["sources"][0].verdict().model_dump(mode="json")
    verdict["observations"]["selection_history"]["train"] = {
        "start": "2023-01-01T00:00:00Z",
        "end": "2023-02-01T00:00:00Z",
    }
    data = anchored(data, remake(dossier, verdict=verdict))
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE" and result["assessment"]["status"] == "NEEDS_REVIEW", (
        result
    )
    history = packet_for(data, book)["catalogue"]["primary_audits"][0]["scientific_history"]
    assert {p["case_id"] for p in history["period_conflicts"]} == {"c1", "c2"}
    a = result["assessment"]
    a["status"] = "CONSULTATIVE"
    rejected, *_ = exercise(data, provider=FakeValidatorProvider(response=canonical(a).encode()))
    assert rejected["error_code"] == "SOURCE_CONFIDENCE_ELEVATED"


def test_m01_contradictory_holdout_is_not_relabelled(dossier, exercise):
    v = deepcopy(dossier["verdict"])
    v["observations"]["selection_history"]["holdout_status"] = "UNOBSERVED_DECLARED"
    data = anchored(dossier, remake(dossier, verdict=v))
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == "AUDIT_HOLDOUT_MISMATCH" and provider.calls == 0


def test_m01_overlapping_selection_periods_block(dossier, exercise):
    v = deepcopy(dossier["verdict"])
    v["observations"]["selection_history"].update(
        train={"start": "2024-01-01T00:00:00Z", "end": "2024-03-01T00:00:00Z"},
        validation={"start": "2024-02-01T00:00:00Z", "end": "2024-04-01T00:00:00Z"},
    )
    data = anchored(dossier, remake(dossier, verdict=v))
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == "AUDIT_SELECTION_PERIOD_CONFLICT" and provider.calls == 0


def test_m01_essential_history_is_not_truncated(dossier, exercise):
    data = scientific_source(dossier, risk="x" * 3900)
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == "AUDIT_HISTORY_WARNING_LIMIT" and provider.calls == 0


def test_m01_dense_context_uses_existing_bound(dossier, exercise):
    data = scientific_source(dossier)
    context = ValidatorContext(
        data["store"].path, fixture_root=data["root"], limits=ContextLimits(max_bytes=1024)
    )
    result, _, provider, _ = exercise(data, context=context)
    assert result["error_code"] == "CONTEXT_LIMIT_EXCEEDED" and provider.calls == 0


def test_m01_private_source_text_stays_private(dossier, exercise):
    data = scientific_source(dossier, risk="C:/Users/private/source.txt")
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == "PRIVATE_PROVIDER_CONTEXT" and provider.calls == 0


@pytest.mark.parametrize("include_pin", [False, True])
def test_m02_matching_or_absent_configuration_pin(
    fixture_factory, monkeypatch, exercise, include_pin
):
    data = config_source(fixture_factory, monkeypatch, matches=True, include_pin=include_pin)
    result, _, provider, book = exercise(data)
    assert result["status"] == "COMPLETE" and provider.calls == 1, result
    pin = packet_for(data, book)["catalogue"]["primary_audits"][0]["identity_pins"]["configuration"]
    assert pin["status"] == (
        "MATCHED_CAPTURED_BYTES" if include_pin else "UNVERIFIED_MISSING_SOURCE_PIN"
    )
    assert (pin["source_sha256"] is not None) == include_pin
    if not include_pin:
        assert any(
            "no captured comparable source pin" in s for s in result["assessment"]["limitations"]
        )


def test_m02_domain_distinction_even_with_equal_digests(dossier, exercise):
    v = deepcopy(dossier["verdict"])
    v["observations"]["dataset_identity"] = [
        {
            "dataset_id": "fixture",
            "kind": "SYNTHETIC",
            "manifest_sha256": "c" * 64,
            "parquet_sha256": "f" * 64,
            "path": "C:/Users/private/data.parquet",
        }
    ]
    data = anchored(dossier, remake(dossier, verdict=v))
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    pins = packet_for(data, book)["catalogue"]["primary_audits"][0]["identity_pins"]
    assert (
        pins["datasets"]["catalogue"]["sha256"]
        == pins["datasets"]["source_pins"][0]["manifest_sha256"]
    )
    assert pins["datasets"]["mapping_status"] == "UNVERIFIED_NO_DOMAIN_BINDING"
    assert pins["datasets"]["manifest_domain"] != pins["datasets"]["catalogue"]["domain"]
    assert pins["datasets"]["data_file_domain"] != pins["configuration"]["source_domain"]
    assert pins["experiment_record_fingerprint"] is None
    assert "C:/Users/private" not in canonical(packet_for(data, book))


def test_m02_different_dataset_domains_are_not_false_conflicts(dossier, exercise):
    v = deepcopy(dossier["verdict"])
    v["observations"]["dataset_identity"] = [
        {
            "dataset_id": "fixture",
            "kind": "SYNTHETIC",
            "manifest_sha256": "d" * 64,
            "parquet_sha256": "f" * 64,
        }
    ]
    data = anchored(dossier, remake(dossier, verdict=v))
    result, *_ = exercise(data)
    assert result["status"] == "COMPLETE", result
    assert any("dataset binding is UNVERIFIED" in s for s in result["assessment"]["limitations"])


def test_m02_resolved_observation_must_match_captured_bytes(fixture_factory, monkeypatch, exercise):
    data = config_source(fixture_factory, monkeypatch, matches=True)
    v = data["sources"][0].verdict().model_dump(mode="json")
    v["observations"]["resolved_configuration"] = {"parameters": {"window": 99}}
    documents = {
        k: bytes.fromhex(raw) for k, raw in data["sources"][0].snapshot()["documents"].items()
    }
    data = anchored(data, remake(data, verdict=v, documents=documents))
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == "AUDIT_RESOLVED_CONTENT_MISMATCH" and provider.calls == 0


def test_m02_pin_conflict_replay_preserves_details(fixture_factory, monkeypatch, exercise):
    data = config_source(fixture_factory, monkeypatch)
    result, agent, provider, _ = exercise(data)
    assert result["status"] == "BLOCKED"
    detail = result["receipt"]["evidence_diagnostic"]
    assert (
        detail["verdict_sha256"] == data["sources"][0].snapshot()["expected_sha256"]
        and len(detail["checkpoint"]) == 64
    )
    assert agent.run(canonical(data["request"]).encode(), sources=data["sources"]) == result
    assert provider.calls == 0


@pytest.mark.parametrize("matches", [False, True])
def test_m02_unsupported_configuration_domain_never_infers_match(
    fixture_factory, monkeypatch, exercise, matches
):
    data = config_source(
        fixture_factory, monkeypatch, matches=matches, protocol="synthetic_other_identity_domain"
    )
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    pin = packet_for(data, book)["catalogue"]["primary_audits"][0]["identity_pins"]["configuration"]
    assert pin["status"] == "UNVERIFIED_DOMAIN_BINDING"
    assert pin["catalogue_domain"] != pin["source_domain"]
    assert any("no verified mapping" in s for s in result["assessment"]["limitations"])


def test_m02_real_auditor_bridge_rejects_changed_catalogue_pin(tmp_path, monkeypatch):
    from tests.validator.test_audit_bridge import (
        test_existing_deterministic_audit_to_consultative_validator,
    )
    from trading_lab_catalog.models import Bundle
    from trading_lab_catalog.store import Store

    original_ingest, original_run = Store.ingest, QuantValidator.run
    results = []

    def ingest(self, bundle, *a, **kw):
        payload = bundle.model_dump(mode="json")
        payload["experiments"][0]["configuration_sha256"] = "e" * 64
        return original_ingest(self, Bundle.model_validate(payload), *a, **kw)

    def run(self, *a, **kw):
        result = original_run(self, *a, **kw)
        results.append(result)
        return result

    monkeypatch.setattr(Store, "ingest", ingest)
    monkeypatch.setattr(QuantValidator, "run", run)
    # The unmodified positive bridge deliberately asserts COMPLETE. Its failure
    # here proves the injected contradiction cannot pass the former acceptance.
    with pytest.raises(AssertionError):
        test_existing_deterministic_audit_to_consultative_validator(tmp_path, monkeypatch)
    assert len(results) == 1
    assert results[0]["status"] == "BLOCKED"
    assert results[0]["error_code"] == "AUDIT_CONFIGURATION_PIN_MISMATCH"
    assert results[0]["receipt"]["simulated_invocations"] == 0


@pytest.mark.parametrize(
    "item",
    [
        {"dataset_id": "fixture", "kind": "SYNTHETIC", "manifest_sha256": "not-a-hash"},
        {
            "dataset_id": "fixture",
            "kind": "SYNTHETIC",
            "manifest_sha256": "a" * 64,
            "authorize": True,
        },
    ],
)
def test_m02_invalid_dataset_pins_are_rejected(dossier, exercise, item):
    v = deepcopy(dossier["verdict"])
    v["observations"]["dataset_identity"] = [item]
    result, _, provider, _ = exercise(anchored(dossier, remake(dossier, verdict=v)))
    assert result["error_code"] == "AUDIT_DATASET_IDENTITY_INVALID" and provider.calls == 0


@pytest.mark.parametrize(
    "stage,expected_calls,actual_calls,context_prepared,response_received",
    [
        ("before_context", 0, 0, False, False),
        ("RESERVED_SIMULATED", 0, 0, True, False),
        ("INVOCATION_INTENT", None, 0, True, False),
        ("provider_boundary", None, 0, True, False),
        ("provider_interrupted", 1, 1, True, False),
        ("RESPONSE_RECEIVED", 1, 1, True, True),
        ("after_return_before_record", 1, 1, True, False),
    ],
)
def test_l01_interruption_boundaries(
    dossier, monkeypatch, stage, expected_calls, actual_calls, context_prepared, response_received
):
    book, provider = (
        ReceiptBook(),
        FakeValidatorProvider(
            scenario="interrupted" if stage == "provider_interrupted" else "valid"
        ),
    )
    context = ValidatorContext(dossier["store"].path, fixture_root=dossier["root"])
    if stage == "before_context":

        def stop(*a, **kw):
            raise KeyboardInterrupt("before capture")

        monkeypatch.setattr(context, "capture", stop)
    elif stage in {"RESERVED_SIMULATED", "INVOCATION_INTENT", "RESPONSE_RECEIVED"}:
        interrupt_history(book, stage)
    elif stage in {"provider_boundary", "after_return_before_record"}:
        original = provider.respond

        def stop(raw):
            if stage == "after_return_before_record":
                original(raw)
            raise KeyboardInterrupt("uncertain host/provider boundary")

        monkeypatch.setattr(provider, "respond", stop)
    agent = QuantValidator(context, provider, book)
    raw = canonical(dossier["request"]).encode()
    with pytest.raises(KeyboardInterrupt):
        agent.run(raw, sources=dossier["sources"])
    result = agent.run(raw, sources=dossier["sources"])
    assert result["status"] == "UNKNOWN"
    observation = result["receipt"]["invocation_observation"]
    assert provider.calls == actual_calls
    assert observation["context_prepared"] is context_prepared
    assert observation["response_received"] is response_received
    assert (
        result["receipt"]["simulated_invocations"]
        == observation["observed_calls"]
        == expected_calls
    )
    assert agent.run(raw, sources=dossier["sources"]) == result
    assert provider.calls == actual_calls


def test_l01_recovery_of_legacy_untraced_context_is_unknown(dossier):
    book, provider = ReceiptBook(), FakeValidatorProvider()
    interrupt_history(book, "RESERVED_SIMULATED")
    agent = QuantValidator(
        ValidatorContext(dossier["store"].path, fixture_root=dossier["root"]), provider, book
    )
    raw = canonical(dossier["request"]).encode()
    with pytest.raises(KeyboardInterrupt):
        agent.run(raw, sources=dossier["sources"])
    # Emulate an interrupted in-memory entry from the pre-correction host.
    for entry in book._entries.values():
        entry.history[:] = [e for e in entry.history if e.get("state") != "VALIDATOR_INVOCATION"]
    result = agent.run(raw, sources=dossier["sources"])
    assert result["receipt"]["simulated_invocations"] is None and provider.calls == 0


def test_l01_parallel_books_do_not_share_observations(dossier):
    provider = FakeValidatorProvider()
    agents = [
        QuantValidator(
            ValidatorContext(dossier["store"].path, fixture_root=dossier["root"]),
            provider,
            ReceiptBook(),
        )
        for _ in range(4)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda a: a.run(canonical(dossier["request"]).encode(), sources=dossier["sources"]),
                agents,
            )
        )
    assert provider.calls == 4
    assert all(
        r["status"] == "COMPLETE" and r["receipt"]["simulated_invocations"] == 1 for r in results
    )
