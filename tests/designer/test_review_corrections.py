"""Reproduce multiplicity loss and empty-reference checkpoint drift before fixing them."""

import pytest

from trading_lab_agents import CatalogContext, QuantResearcher, ReceiptBook, SourceDocument
from trading_lab_agents.designer import QuantStrategyDesigner, designer_operation_id
from trading_lab_agents.designer_context import DesignerContext
from trading_lab_agents.designer_host import DesignReviewHost
from trading_lab_agents.designer_provider import FakeDesignerProvider
from trading_lab_agents.models import ResearchRequest
from trading_lab_agents.provider import FakeProvider
from trading_lab_catalog.models import Bundle, Strategy
from trading_lab_catalog.store import Store
from trading_lab_catalog.verification import parse, sha
from trading_lab_orchestration.contracts import HypothesisManifest, canonical

from .conftest import inventory, specification


def research_handoff(
    path,
    root,
    capabilities,
    *,
    searches=12,
    flow="FLOW2",
    request_id="request_01",
    start="2023-09-01T00:00:00Z",
    end="2023-10-01T00:00:00Z",
):
    statistics = {
        "calculation_version": "synthetic_statistics/1.0",
        "period_start_utc": start,
        "period_end_utc": end,
        "sample_size": 720,
        "searches_count": searches,
        "exclusions": [],
        "limitations": ["Exploratory synthetic observations, not OOS"],
    }
    doc = SourceDocument(
        reference_id="source_01",
        kind="SYNTHETIC_STATISTICS" if flow == "FLOW2" else "SYNTHETIC_PAPER",
        content=canonical(statistics).encode() if flow == "FLOW2" else b"Synthetic proposal only",
    )
    request = {
        "schema_version": "1.0",
        "contract_kind": "ResearchRequest",
        "request_id": request_id,
        "flow": flow,
        "objective": "Preserve discovery multiplicity and catalogue snapshot in simulated design",
        "market": {
            **capabilities.payload()["dataset"]["market"],
            "coverage_start_utc": None,
            "coverage_end_utc": None,
        },
        "source_refs": [
            {
                "reference_id": doc.reference_id,
                "kind": doc.kind,
                "sha256": sha(doc.content),
                "verification": "HASH_VERIFIED",
                "limitations": ["Synthetic evidence, not economic validation"],
            }
        ],
        "catalog_context": [],
        "discovery": {
            "statistics_reference_id": doc.reference_id if flow == "FLOW2" else None,
            "searches_count": searches,
            "period_start_utc": start if flow == "FLOW2" else None,
            "period_end_utc": end if flow == "FLOW2" else None,
        },
        "max_hypotheses": 1,
        "status": "PREPARED",
        "limitations": [],
        "notes": None,
    }
    raw = canonical(request).encode()
    book, provider = ReceiptBook(), FakeProvider()
    before = inventory(path.parent)
    result = QuantResearcher(CatalogContext(path, fixture_root=root), provider, book).run(
        raw, documents=(doc,)
    )
    assert result["status"] == "COMPLETE", result
    assert provider.calls == 1 and inventory(path.parent) == before
    hypothesis = bytes.fromhex(book.export(request_id)["response_hex"])
    host = DesignReviewHost()
    candidate = result["hypothesis"]["candidates"][0]
    review = host.review(
        raw,
        hypothesis,
        candidate["hypothesis_id"],
        researcher_receipts=book,
        capabilities=capabilities,
    )
    return {
        "request": raw,
        "hypothesis": hypothesis,
        "candidate": candidate,
        "host": host,
        "review": review,
        "book": book,
        "researcher_result": result,
        "research_provider": provider,
    }


def proposed(handoff, capabilities, count):
    spec = specification(handoff, capabilities)
    spec["request_id"] = parse(handoff["request"])["request_id"]
    spec["manifest"]["novelty"]["known_searches"] = count
    return spec


def design(handoff, path, root, capabilities, proposal, record_property):
    provider = FakeDesignerProvider(canonical(proposal).encode())
    agent = QuantStrategyDesigner(
        DesignerContext(path, fixture_root=root),
        provider,
        handoff["book"],
        handoff["host"],
        capabilities,
    )
    before = inventory(path.parent)
    result = agent.run(
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        review_reference=handoff["review"],
    )
    repeated = agent.run(
        handoff["request"],
        handoff["hypothesis"],
        handoff["candidate"]["hypothesis_id"],
        review_reference=handoff["review"],
    )
    assert repeated == result and inventory(path.parent) == before
    assert not any(p.name.endswith(("-wal", "-shm", "-journal")) for p in path.parent.iterdir())
    assert provider.calls == result["receipt"]["simulated_invocations"]
    if "research_provider" in handoff:
        assert handoff["research_provider"].calls == 1
    else:
        assert handoff["researcher_result"]["receipt"]["simulated_invocations"] == 1
    assert result["receipt"]["operational_effects"] == []
    request = parse(handoff["request"])
    receipt = handoff["book"].export(
        designer_operation_id(request["request_id"], handoff["candidate"]["hypothesis_id"])
    )
    assert bytes.fromhex(receipt["request_hex"]) == handoff["request"]
    if provider.calls:
        assert bytes.fromhex(receipt["response_hex"]) == canonical(proposal).encode()
        assert sha(bytes.fromhex(receipt["response_hex"])) == result["receipt"]["response_sha256"]
        packet = parse(bytes.fromhex(receipt["context_hex"]))
        assert (
            packet["request"]["discovery"]["searches_count"]
            == request["discovery"]["searches_count"]
        )
        assert (
            packet["host_review"]["warning_provenance"]
            == handoff["researcher_result"]["antecedents"]["warning_provenance"]
        )
        if result["receipt"]["mapping"]:
            manifest = HypothesisManifest.model_validate_json(
                canonical(result["specification"]["manifest"])
            )
            assert manifest.fingerprint() == result["receipt"]["mapping"]["manifest_fingerprint"]
    record_property("observed_status", result["status"])
    record_property("observed_error", result["error_code"] or "NONE")
    record_property(
        "observed_known_searches",
        canonical(result["specification"]["manifest"]["novelty"]["known_searches"])
        if result["specification"]
        else "NO_SPECIFICATION",
    )
    record_property("review_checkpoint", handoff["researcher_result"]["antecedents"]["checkpoint"])
    record_property("measured_provider_calls_after_repeat", provider.calls)
    record_property("fixture_inventory_unchanged", "true")
    return result, receipt


@pytest.mark.parametrize("count", [0, 5, None])
def test_a_known_searches_cannot_be_reduced_or_erased(
    catalogue, tmp_path, capabilities, record_property, count
):
    handoff = research_handoff(catalogue[0].path, tmp_path, capabilities)
    result, _ = design(
        handoff,
        catalogue[0].path,
        tmp_path,
        capabilities,
        proposed(handoff, capabilities, count),
        record_property,
    )
    assert result["status"] == "NEEDS_REVIEW", result
    assert result["error_code"] == "DISCOVERY_MULTIPLICITY_LOST"
    assert result["receipt"]["mapping"] is None


@pytest.mark.parametrize("count", [12, 15])
def test_a_known_minimum_preserved_with_warning_provenance(
    catalogue, tmp_path, capabilities, record_property, count
):
    handoff = research_handoff(catalogue[0].path, tmp_path, capabilities)
    result, _ = design(
        handoff,
        catalogue[0].path,
        tmp_path,
        capabilities,
        proposed(handoff, capabilities, count),
        record_property,
    )
    assert result["status"] == "COMPLETE", result
    manifest = result["specification"]["manifest"]
    assert manifest["novelty"]["known_searches"] == count
    assert all(limit in manifest["limitations"] for limit in handoff["candidate"]["limitations"])
    for label in ("CONSUMED", "NO_DECISION", "RESET_PER_SEGMENT"):
        assert any(label in limit for limit in manifest["limitations"])
    assert (
        "Discovery period is exploratory, not independent OOS validation" in manifest["limitations"]
    )


@pytest.mark.parametrize("count", [None, 0, 12])
def test_a_unknown_count_stays_unknown(catalogue, tmp_path, capabilities, record_property, count):
    handoff = research_handoff(catalogue[0].path, tmp_path, capabilities, searches=None)
    result, _ = design(
        handoff,
        catalogue[0].path,
        tmp_path,
        capabilities,
        proposed(handoff, capabilities, count),
        record_property,
    )
    if count is None:
        assert result["status"] == "COMPLETE", result
        assert result["specification"]["manifest"]["novelty"]["known_searches"] is None
        assert (
            "Multiple-testing search count is UNKNOWN"
            in result["specification"]["manifest"]["limitations"]
        )
    else:
        assert result["status"] == "NEEDS_REVIEW", result
        assert result["error_code"] == "DISCOVERY_MULTIPLICITY_UNVERIFIED"
        assert result["receipt"]["mapping"] is None


def test_a_search_count_does_not_turn_discovery_into_oos(
    catalogue, tmp_path, capabilities, record_property
):
    handoff = research_handoff(
        catalogue[0].path,
        tmp_path,
        capabilities,
        start="2024-05-01T00:00:00Z",
        end="2024-07-01T00:00:00Z",
    )
    spec = proposed(handoff, capabilities, 12)
    evaluation = parse(spec["manifest"]["evaluation_plan"]["robustness_plan"])
    evaluation["holdout_independent"] = True
    spec["manifest"]["evaluation_plan"]["robustness_plan"] = canonical(evaluation)
    result, _ = design(handoff, catalogue[0].path, tmp_path, capabilities, spec, record_property)
    assert result["status"] == "NEEDS_REVIEW" and result["error_code"] == "HOLDOUT_RECLASSIFIED"


def empty_catalogue(tmp_path):
    store = Store(tmp_path / "checkpoint-catalogue" / "strategy-catalog.sqlite3")
    store.init()
    return store


def change_catalogue(store):
    before = inventory(store.path.parent)
    store.ingest(
        Bundle(
            strategies=[
                Strategy(
                    id="new_fixture_strategy",
                    name="Synthetic later strategy",
                    description="A new discovery entry",
                    source="synthetic fixture",
                )
            ]
        ),
        "Explicit synthetic test mutation",
    )
    assert inventory(store.path.parent) != before


def test_b_changed_checkpoint_without_references_is_blocked(
    tmp_path, capabilities, record_property
):
    store = empty_catalogue(tmp_path)
    handoff = research_handoff(store.path, tmp_path, capabilities, flow="FLOW1", searches=None)
    assert not handoff["candidate"]["catalog_refs"]
    change_catalogue(store)
    current = DesignerContext(store.path, fixture_root=tmp_path).capture(
        ResearchRequest.model_validate_json(handoff["request"])
    )
    assert current["checkpoint"] != handoff["researcher_result"]["antecedents"]["checkpoint"]
    record_property("new_checkpoint", current["checkpoint"])
    result, receipt = design(
        handoff,
        store.path,
        tmp_path,
        capabilities,
        proposed(handoff, capabilities, None),
        record_property,
    )
    assert result["error_code"] == "HANDOFF_CHECKPOINT_CHANGED", result
    assert result["status"] == "BLOCKED"
    assert result["receipt"]["simulated_invocations"] == 0
    assert receipt["context_hex"] is receipt["response_hex"] is None


def test_b_unchanged_empty_checkpoint_is_accepted(tmp_path, capabilities, record_property):
    store = empty_catalogue(tmp_path)
    handoff = research_handoff(store.path, tmp_path, capabilities, flow="FLOW1", searches=None)
    assert not handoff["candidate"]["catalog_refs"]
    result, _ = design(
        handoff,
        store.path,
        tmp_path,
        capabilities,
        proposed(handoff, capabilities, None),
        record_property,
    )
    assert result["status"] == "COMPLETE"


def test_b_unchanged_checkpoint_with_references_is_accepted(
    handoff, catalogue, tmp_path, capabilities, record_property
):
    assert handoff["candidate"]["catalog_refs"]
    result, _ = design(
        handoff,
        catalogue[0].path,
        tmp_path,
        capabilities,
        proposed(handoff, capabilities, None),
        record_property,
    )
    assert result["status"] == "COMPLETE"


def test_b_new_explicit_handoff_has_identified_review(tmp_path, capabilities, record_property):
    store = empty_catalogue(tmp_path)
    old = research_handoff(store.path, tmp_path, capabilities, flow="FLOW1", searches=None)
    change_catalogue(store)
    # This is an explicit, separate synthetic test action, never a retry in Designer.run.
    fresh = research_handoff(
        store.path,
        tmp_path,
        capabilities,
        flow="FLOW1",
        searches=None,
        request_id="request_after_catalogue_change",
    )
    assert old["review"] != fresh["review"]
    assert (
        old["researcher_result"]["antecedents"]["checkpoint"]
        != fresh["researcher_result"]["antecedents"]["checkpoint"]
    )
    result, _ = design(
        fresh,
        store.path,
        tmp_path,
        capabilities,
        proposed(fresh, capabilities, None),
        record_property,
    )
    assert result["status"] == "COMPLETE"
    assert old["research_provider"].calls == fresh["research_provider"].calls == 1
