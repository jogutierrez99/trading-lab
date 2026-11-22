"""Disposable synthetic catalogues only; never resolve the real catalogue location."""

import hashlib
from pathlib import Path

import pytest

from trading_lab_agents import CatalogContext, QuantResearcher, ReceiptBook, SourceDocument
from trading_lab_agents.provider import FakeProvider
from trading_lab_catalog.verification import sha
from trading_lab_orchestration.contracts import canonical


@pytest.fixture(autouse=True)
def simulation_measurements(monkeypatch, record_property):
    """Measure actual fake invocations rather than summing cumulative counters."""
    original, observed = FakeProvider.respond, []

    def measured(self, packet):
        observed.append(len(packet))
        return original(self, packet)

    monkeypatch.setattr(FakeProvider, "respond", measured)
    yield
    record_property("measured_fake_invocations", len(observed))
    record_property("measured_context_sizes", canonical(observed))


def inventory(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        if p.is_file()
        else "DIR"
        for p in root.rglob("*")
    }


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    # Reuse existing synthetic accepted-source fixture; this does not import Issue #3.
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "catalog_api"))
    from catalog_read_support import make_catalogue

    store, bundle = make_catalogue(tmp_path, audited=True)
    before = inventory(store.path.parent)
    yield store, bundle
    assert inventory(store.path.parent) == before
    assert not any(
        p.name.endswith(("-wal", "-shm", "-journal")) for p in store.path.parent.iterdir()
    )


@pytest.fixture
def documents():
    return (
        SourceDocument(
            reference_id="source_01",
            kind="SYNTHETIC_PAPER",
            content=b"Synthetic source: prior-high persistence is only a hypothesis.",
        ),
    )


@pytest.fixture
def request_data(documents):
    def make(**updates):
        payload = {
            "schema_version": "1.0",
            "contract_kind": "ResearchRequest",
            "request_id": "req_01",
            "flow": "FLOW1",
            "objective": "Propose a falsifiable hypothesis for review only",
            "market": {
                "asset": "BTCUSDT",
                "market_type": "spot",
                "timeframe": "1h",
                "requested_years": None,
                "coverage_start_utc": None,
                "coverage_end_utc": None,
            },
            "source_refs": [
                {
                    "reference_id": documents[0].reference_id,
                    "kind": documents[0].kind,
                    "sha256": sha(documents[0].content),
                    "verification": "UNVERIFIED",
                    "limitations": ["Synthetic data, not a verified economic result"],
                }
            ],
            "catalog_context": [],
            "discovery": {
                "statistics_reference_id": None,
                "searches_count": None,
                "period_start_utc": None,
                "period_end_utc": None,
            },
            "max_hypotheses": 1,
            "status": "PREPARED",
            "limitations": [],
            "notes": None,
        }
        payload.update(updates)
        return payload

    return make


@pytest.fixture
def exercise(catalogue, tmp_path, record_property):
    def run(provider, payload, documents, *, book=None, context=None, gate=None):
        context = context or CatalogContext(catalogue[0].path, fixture_root=tmp_path)
        book = book or ReceiptBook()
        agent = QuantResearcher(context, provider, book, gate=gate)
        raw = payload if isinstance(payload, bytes) else canonical(payload).encode()
        result = agent.run(raw, documents=documents)
        record_property("context_bytes", result["receipt"]["context_bytes"])
        record_property("simulated_calls", provider.calls)
        record_property("error_code", result["error_code"] or "NONE")
        record_property("context_queries", result["receipt"]["queries"])
        return result, agent, context, book

    return run
