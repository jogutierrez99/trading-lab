"""Replace scaffold checks with rule and prefix-invariance tests when implemented."""

import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.bollinger_regime_reversal import BollingerRegimeReversalStrategy
from quant_lab.strategies.registry import StrategyRegistry


def test_bollinger_regime_reversal_scaffold():
    registry = StrategyRegistry().discover()
    assert "bollinger_regime_reversal" in registry.names()
    config = StrategyConfig(name="bollinger_regime_reversal", enabled=True)
    strategy = registry.create(config)
    assert isinstance(strategy, BollingerRegimeReversalStrategy)
    assert strategy.metadata()["version"] == "1.0.0"
    with pytest.raises(NotImplementedError):
        strategy.generate_signals([])
