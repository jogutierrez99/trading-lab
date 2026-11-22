"""Simulation-only research components; no operational dispatch or provider clients."""

from .context import CatalogContext, ContextLimits, SourceDocument
from .models import ResearchHypothesis, ResearchRequest
from .provider import FakeProvider
from .receipts import ReceiptBook
from .researcher import QuantResearcher, SimulationGate

__all__ = [
    "CatalogContext",
    "ContextLimits",
    "FakeProvider",
    "QuantResearcher",
    "ReceiptBook",
    "ResearchHypothesis",
    "ResearchRequest",
    "SimulationGate",
    "SourceDocument",
]
