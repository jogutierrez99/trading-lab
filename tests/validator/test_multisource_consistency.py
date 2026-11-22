"""Permanent frozen-manifest consistency regressions; disposable sources only."""

from copy import deepcopy
from pathlib import Path

import pytest

from trading_lab_agents.context import ContextLimits
from trading_lab_agents.validator_context import ValidatorContext
from trading_lab_agents.validator_evidence import AuditDocument, PreparedAudit
from trading_lab_agents.validator_provider import FakeValidatorProvider
from trading_lab_catalog.models import Bundle
from trading_lab_catalog.store import Store
from trading_lab_catalog.verification import sha
from trading_lab_orchestration.contracts import canonical, load_manifest

from .conftest import create_fixture, inventory
from .test_policy import packet_for


def with_histories(data, rows):
    manifest = load_manifest(Path("examples/orchestration/manual_valid.json")).model_dump(
        mode="json"
    )
    manifest["novelty"].update(known_searches=12, known_variants=12)
    common = sha(canonical(manifest).encode())
    sources = []
    for old, row in zip(data["sources"], rows, strict=True):
        v = old.verdict().model_dump(mode="json")
        v["candidate_id"] = row.get("candidate_id", "candidate_shared")
        if not row.get("omit_identity", False):
            v["observations"]["hypothesis_manifest_sha256"] = row.get("manifest_sha256", common)
        else:
            v["observations"].pop("hypothesis_manifest_sha256", None)
        v["observations"]["search_history"] = {
            "prior_work": "Synthetic frozen manifest provenance",
            "known_searches": row.get("searches", 12),
            "known_variants": row.get("variants", 12),
        }
        for field in row.get("omit_fields", []):
            v["observations"]["search_history"].pop(field)
        if "declared_scope" in row:
            v["observations"]["search_history_scope"] = row["declared_scope"]
        host = {}
        if "verified" in row:
            host["manifest_identity_verified"] = row["verified"]
        if "scope" in row:
            host["history_scope"] = row["scope"]
        saved = old.snapshot()
        raw = canonical(v).encode()
        sources.append(
            PreparedAudit(
                raw,
                expected_sha256=sha(raw),
                documents=tuple(
                    AuditDocument(k, bytes.fromhex(b)) for k, b in saved["documents"].items()
                ),
                case_bindings=saved["case_bindings"],
                **host,
            )
        )
    result = {**data, "sources": tuple(sources), "request": deepcopy(data["request"])}
    result["request"]["audits"] = [
        {
            "run_id": s.verdict().run_id,
            "audit_id": s.verdict().audit_id,
            "verdict_sha256": s.snapshot()["expected_sha256"],
        }
        for s in sources
    ]
    return result


def test_same_frozen_manifest_12_12_vs_zero_blocks_before_provider(fixture_factory, exercise):
    data = with_histories(
        fixture_factory(paired=True, comparable=True, holdout="UNOBSERVED", trades=40),
        [{}, {"searches": 0, "variants": 0}],
    )
    result, agent, provider, book = exercise(data)
    assert (
        result["status"] == "BLOCKED" and result["error_code"] == "SCIENTIFIC_HISTORY_CONFLICT"
    ), result
    assert provider.calls == result["receipt"]["simulated_invocations"] == 0
    detail = result["receipt"]["evidence_diagnostic"]
    assert detail["conflicts"][0]["fields"] == ["known_searches", "known_variants"]
    assert len(detail["conflicts"][0]["references"]) == 2
    assert agent.run(canonical(data["request"]).encode(), sources=data["sources"]) == result
    assert provider.calls == 0


def pair(fixture_factory, rows):
    return with_histories(
        fixture_factory(paired=True, comparable=True, holdout="UNOBSERVED", trades=40), rows
    )


def test_equal_counts_accept_and_bind_exact_manifest(fixture_factory, exercise):
    data = pair(fixture_factory, [{}, {}])
    result, _, provider, book = exercise(data)
    assert result["status"] == "COMPLETE" and result["assessment"]["status"] == "CONSULTATIVE", (
        result
    )
    packet = packet_for(data, book)
    consistency = packet["catalogue"]["history_consistency"]
    assert consistency["issues"] == [] and len(consistency["groups"]) == 1
    group = consistency["groups"][0]
    for field in ("known_searches", "known_variants"):
        assert group["field_checks"][field]["status"] == "AGREEMENT"
    for primary, source in zip(packet["catalogue"]["primary_audits"], data["sources"], strict=True):
        identity = primary["manifest_identity"]
        assert (
            identity["hypothesis_manifest_sha256"]
            == source.verdict().observations["hypothesis_manifest_sha256"]
        )
        assert identity["candidate_id"] == source.verdict().candidate_id
        assert identity["provenance"]["audit_sha256"] == source.snapshot()["expected_sha256"]
        assert identity["domain"] == "HYPOTHESIS_MANIFEST_JSON_SHA256"
    assert provider.calls == 1


def test_different_manifests_different_candidates_do_not_conflict(fixture_factory, exercise):
    data = pair(
        fixture_factory,
        [
            {"candidate_id": "candidate_a", "manifest_sha256": "a" * 64},
            {
                "candidate_id": "candidate_b",
                "manifest_sha256": "b" * 64,
                "searches": 0,
                "variants": 0,
            },
        ],
    )
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE" and result["assessment"]["status"] == "CONSULTATIVE", (
        result
    )
    consistency = packet_for(data, book)["catalogue"]["history_consistency"]
    assert len(consistency["groups"]) == 2 and not consistency["needs_review"]
    assert all(
        g["field_checks"]["known_searches"]["status"] == "SINGLE_SOURCE"
        for g in consistency["groups"]
    )


@pytest.mark.parametrize("field", ["known_searches", "known_variants"])
@pytest.mark.parametrize("missing", [False, True])
def test_null_and_absent_are_not_zero_or_agreement(fixture_factory, exercise, field, missing):
    row = {"searches": None} if field == "known_searches" else {"variants": None}
    if missing:
        row = {"omit_fields": [field]}
    data = pair(fixture_factory, [{}, row])
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    assert result["assessment"]["status"] == "NEEDS_REVIEW"
    packet = packet_for(data, book)
    projected = packet["catalogue"]["primary_audits"][1]["scientific_history"]["search_history"]
    assert projected[field] is None
    check = packet["catalogue"]["history_consistency"]["groups"][0]["field_checks"][field]
    assert check["status"] == "PARTIAL_KNOWLEDGE"
    assert len(check["absent_references"] if missing else check["null_references"]) == 1


@pytest.mark.parametrize("omit", [False, True])
def test_missing_manifest_identity_does_not_group(fixture_factory, exercise, omit):
    row = {"omit_identity": True} if omit else {"manifest_sha256": None}
    data = pair(fixture_factory, [{}, {**row, "searches": 0, "variants": 0}])
    result, _, provider, book = exercise(data)
    assert result["status"] == "COMPLETE" and result["assessment"]["status"] == "NEEDS_REVIEW", (
        result
    )
    consistency = packet_for(data, book)["catalogue"]["history_consistency"]
    assert len(consistency["groups"]) == 1 and len(consistency["groups"][0]["references"]) == 1
    identity = packet_for(data, book)["catalogue"]["primary_audits"][1]["manifest_identity"]
    assert (
        identity["hypothesis_manifest_sha256"] is None
        and identity["binding_status"] == "UNVERIFIED"
    )
    assert provider.calls == 1


def test_host_unaccredited_identity_cannot_create_equivalence(fixture_factory, exercise):
    data = pair(fixture_factory, [{}, {"verified": False, "searches": 0, "variants": 0}])
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE" and result["assessment"]["status"] == "NEEDS_REVIEW", (
        result
    )
    packet = packet_for(data, book)
    assert (
        packet["catalogue"]["primary_audits"][1]["manifest_identity"]["binding_status"]
        == "UNVERIFIED"
    )
    assert len(packet["catalogue"]["history_consistency"]["groups"][0]["references"]) == 1
    assert (
        packet["catalogue"]["runs"][1]["audit_status"] == "SOURCE_AUDITED"
    )  # unchanged catalogue fact, not an identity grant


def test_same_candidate_distinct_manifests_require_review_without_counter_merge(
    fixture_factory, exercise
):
    data = pair(fixture_factory, [{}, {"manifest_sha256": "d" * 64, "searches": 0, "variants": 0}])
    result, _, provider, book = exercise(data)
    assert result["status"] == "COMPLETE" and result["assessment"]["status"] == "NEEDS_REVIEW", (
        result
    )
    consistency = packet_for(data, book)["catalogue"]["history_consistency"]
    assert len(consistency["groups"]) == 2
    assert any(i["code"] == "CANDIDATE_HAS_DISTINCT_MANIFESTS" for i in consistency["issues"])
    assert provider.calls == 1


def test_same_manifest_conflicting_candidate_provenance_requires_review(fixture_factory, exercise):
    data = pair(fixture_factory, [{}, {"candidate_id": "candidate_other"}])
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE" and result["assessment"]["status"] == "NEEDS_REVIEW", (
        result
    )
    consistency = packet_for(data, book)["catalogue"]["history_consistency"]
    assert any(i["code"] == "MANIFEST_HAS_DISTINCT_CANDIDATES" for i in consistency["issues"])


def three_sources(root):
    inputs = [
        create_fixture(
            root / f"input-{i}",
            run_id="r" if i == 0 else f"r{i + 1}",
            source_audited=False,
            hash_verified=False,
            comparable=True,
            holdout="UNOBSERVED",
            trades=40,
        )
        for i in range(3)
    ]
    store = Store(root / "joined" / "strategy-catalog.sqlite3")
    store.init()
    first = inputs[0]["bundle"]
    bundle = Bundle(
        strategies=first.strategies,
        versions=first.versions,
        experiments=first.experiments,
        runs=[r for d in inputs for r in d["bundle"].runs],
        case_results=[r for d in inputs for r in d["bundle"].case_results],
        artifacts=[r for d in inputs for r in d["bundle"].artifacts],
        research_decisions=[r for d in inputs for r in d["bundle"].research_decisions],
    )
    store.ingest(bundle, source="synthetic three-source fixture")
    data = {
        **inputs[0],
        "root": root,
        "store": store,
        "sources": tuple(d["source"] for d in inputs),
        "request": deepcopy(inputs[0]["request"]),
    }
    data["request"]["source_run_ids"] = [d["request"]["source_run_ids"][0] for d in inputs]
    return data


def test_three_sources_detect_one_contradiction_without_mutation(tmp_path, exercise):
    data = with_histories(three_sources(tmp_path / "triple"), [{}, {}, {"searches": 0}])
    before = inventory(data["root"])
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == "SCIENTIFIC_HISTORY_CONFLICT" and provider.calls == 0, result
    detail = result["receipt"]["evidence_diagnostic"]["conflicts"][0]
    assert detail["fields"] == ["known_searches"] and len(detail["references"]) == 3
    assert detail["field_checks"]["known_variants"]["status"] == "AGREEMENT"
    assert inventory(data["root"]) == before


def test_source_reordering_gives_same_diagnostic_and_replay_is_exact(fixture_factory, exercise):
    data = pair(fixture_factory, [{}, {"searches": 0, "variants": 0}])
    first, agent, provider, book = exercise(data)
    reverse = {
        **data,
        "sources": tuple(reversed(data["sources"])),
        "request": deepcopy(data["request"]),
    }
    reverse["request"]["request_id"] = "reordered_independent"
    reverse["request"]["source_run_ids"].reverse()
    reverse["request"]["audits"].reverse()
    second, _, other, _ = exercise(reverse)
    assert first["receipt"]["evidence_diagnostic"] == second["receipt"]["evidence_diagnostic"]
    assert provider.calls == other.calls == 0
    assert agent.run(canonical(data["request"]).encode(), sources=data["sources"]) == first
    # Input order changes bytes, so the same request ID keeps the existing conflict rule.
    changed = agent.run(
        canonical(data["request"]).encode(), sources=tuple(reversed(data["sources"]))
    )
    assert changed["status"] == "CONFLICT" and provider.calls == 0


def test_duplicate_source_is_not_an_independent_observation(fixture_factory, exercise):
    data = pair(fixture_factory, [{}, {}])
    duplicated = {**data, "sources": (*data["sources"], data["sources"][0])}
    result, _, provider, _ = exercise(duplicated)
    assert result["error_code"] == "AUDIT_SOURCE_SET_MISMATCH" and provider.calls == 0


def test_size_limit_blocks_without_truncation(fixture_factory, exercise):
    data = pair(fixture_factory, [{}, {}])
    context = ValidatorContext(
        data["store"].path, fixture_root=data["root"], limits=ContextLimits(max_bytes=1024)
    )
    result, _, provider, _ = exercise(data, context=context)
    assert result["error_code"] == "CONTEXT_LIMIT_EXCEEDED" and provider.calls == 0


def test_provider_cannot_omit_identity_consistency_warning(fixture_factory, exercise):
    data = pair(fixture_factory, [{}, {}])
    first, *_ = exercise(data)
    a = first["assessment"]
    a["limitations"] = [
        s for s in a["limitations"] if not s.startswith("Frozen manifest identity consistency:")
    ]
    a["model_review"]["uncertainties"] = list(a["limitations"])
    result, _, provider, _ = exercise(
        data, provider=FakeValidatorProvider(response=canonical(a).encode())
    )
    assert result["error_code"] == "LIMITATION_DROPPED_OR_INVENTED" and provider.calls == 1


def test_provider_cannot_hide_material_provenance_ambiguity(fixture_factory, exercise):
    data = pair(fixture_factory, [{}, {"candidate_id": "candidate_other"}])
    first, *_ = exercise(data)
    a = first["assessment"]
    a["status"] = "CONSULTATIVE"
    result, *_ = exercise(data, provider=FakeValidatorProvider(response=canonical(a).encode()))
    assert result["error_code"] == "SOURCE_CONFIDENCE_ELEVATED"


def test_conflict_diagnostic_keeps_safe_references_without_private_candidate(
    fixture_factory, exercise
):
    private = "S-1-5-21-123-456-789-1000"
    data = pair(
        fixture_factory,
        [{"candidate_id": private}, {"candidate_id": private, "searches": 0, "variants": 0}],
    )
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == "SCIENTIFIC_HISTORY_CONFLICT" and provider.calls == 0
    diagnostic = result["receipt"]["evidence_diagnostic"]
    assert len(diagnostic["conflicts"][0]["references"]) == 2
    assert diagnostic["conflicts"][0]["candidate_reference_id"].startswith("candidate.")
    assert private not in canonical(result)


@pytest.mark.parametrize(
    "row",
    [
        {"scope": None},
        {"scope": "RUN_LOCAL_SEARCHES/1.0"},
        {"declared_scope": "PER_ASSET_SEARCHES/1.0"},
    ],
)
def test_different_or_unknown_counter_scopes_are_not_compared(fixture_factory, exercise, row):
    data = pair(fixture_factory, [{}, {**row, "searches": 0, "variants": 0}])
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE" and result["assessment"]["status"] == "NEEDS_REVIEW", (
        result
    )
    consistency = packet_for(data, book)["catalogue"]["history_consistency"]
    assert len(consistency["groups"]) == 1 and len(consistency["groups"][0]["references"]) == 1
    assert any(i["code"] == "UNVERIFIED_COUNTER_SCOPE" for i in consistency["issues"])


@pytest.mark.parametrize("digest", ["bad", 12, False])
def test_malformed_manifest_hash_blocks(fixture_factory, exercise, digest):
    data = pair(fixture_factory, [{}, {"manifest_sha256": digest}])
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == "AUDIT_MANIFEST_IDENTITY_INVALID" and provider.calls == 0


def test_provider_cannot_grant_its_own_host_binding(fixture_factory, exercise):
    data = pair(fixture_factory, [{}, {"verified": False}])
    first, *_ = exercise(data)
    a = first["assessment"]
    a["manifest_identity_verified"] = True
    result, *_ = exercise(data, provider=FakeValidatorProvider(response=canonical(a).encode()))
    assert result["status"] == "BLOCKED" and result["assessment"] is None
