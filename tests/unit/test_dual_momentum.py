import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_dual_momentum_gates_exits_and_disabled_shorts():
    strategy = (
        StrategyRegistry().discover().create(StrategyConfig(name="dual_momentum", enabled=True))
    )
    base = {"close": 110.0, "ema200": 100.0, "roc_short": 0.2, "roc_long": 0.1}
    gates = [{"close": 100.0}, {"roc_long": 0.0}, {"roc_short": 0.0}, {"roc_short": 0.1}]
    frame = pd.DataFrame([base] + [base | g for g in gates])
    assert strategy.generate_long_entries(frame) == [True] + [False] * len(gates)
    assert strategy.generate_long_exits(pd.DataFrame([base])) == [False]
    exits = [{"close": 99.0}, {"roc_short": -0.1}, {"roc_short": 0.05}]
    assert all(strategy.generate_long_exits(pd.DataFrame([base | e for e in exits])))
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
    with pytest.raises(ValueError):
        StrategyRegistry().discover().create(
            StrategyConfig(name="dual_momentum", enabled=True, parameters={"typo": 1})
        )
