from pathlib import Path

import pytest

from quant_lab.config import StrictModel
from quant_lab.strategies.base import BaseStrategy


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[1]


class Parameters(StrictModel):
    threshold: float = 10.0


class ExampleStrategy(BaseStrategy[Parameters]):
    """Test-only causal strategy; deliberately not shipped in the registry."""

    name = "example"
    parameter_model = Parameters

    def prepare_features(self, candles):
        return candles

    def generate_long_entries(self, features):
        return [value > self.parameters.threshold for value in features]

    def generate_long_exits(self, features):
        return [value <= self.parameters.threshold for value in features]

    def generate_short_entries(self, features):
        return [value < self.parameters.threshold for value in features]

    def generate_short_exits(self, features):
        return [value >= self.parameters.threshold for value in features]


@pytest.fixture
def example_class():
    return ExampleStrategy
