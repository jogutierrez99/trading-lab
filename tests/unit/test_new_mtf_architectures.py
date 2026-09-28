"""Every new family: closed availability, prefix invariance, gaps and warmup."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from quant_lab.mtf_execution import configuration, prepare
from quant_lab.mtf_features import STEPS, closed_features
from quant_lab.new_mtf_features import FAMILIES, v4_triggers
from quant_lab.strategies.registry import StrategyRegistry


def candles(n=1000, tf="1h"):
    t = np.arange(n)
    price = 100 + t * 0.005 + np.sin(t / 12) * 3
    return pd.DataFrame(
        dict(open=price - 0.1, high=price + 0.5, low=price - 0.5, close=price, volume=1.0),
        index=pd.date_range("2020", periods=n, freq=STEPS[tf], tz="UTC"),
    )


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("version", ["V1", "V2", "V4"])
def test_prefix_availability_timeframe_and_direction(family, version):
    config = configuration("BTCUSDT", family, version)
    strategy = StrategyRegistry().discover().create(config)
    f = candles(900, config.market.timeframe)
    full = strategy.prepare_features(f)
    for n in (1, 17, 127, 839):
        pd.testing.assert_frame_equal(strategy.prepare_features(f.iloc[:n]), full.iloc[:n])
    for tf in ("1h", "4h"):
        if "available_at_" + tf in full:
            known = full["available_at_" + tf].dropna()
            assert (known <= known.index + STEPS[config.market.timeframe]).all()
    assert not any(strategy.generate_short_entries(full))
    assert not any(strategy.generate_long_exits(full))
    assert not full.long_final.iloc[:14].any()
    bad = config.model_copy(update={"market": config.market.model_copy(update={"timeframe": "4h"})})
    with pytest.raises(ValueError, match="timeframe"):
        StrategyRegistry().discover().create(bad).prepare_features(f)


@pytest.mark.parametrize("family", FAMILIES)
def test_frozen_parameters_and_excluded_architecture(family):
    for parameters in ({"architecture": "V3"}, {"trade_mode": "SHORT_ONLY"}, {"atr_period": 5}):
        config = configuration("BTCUSDT", family, "V1").model_copy(
            update={"parameters": parameters}
        )
        with pytest.raises(ValidationError):
            StrategyRegistry().discover().create(config)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("version", ["V1", "V2", "V4"])
def test_gap_resets_warmup_and_execution_clock(family, version):
    config = configuration("BTCUSDT", family, version)
    f = candles(600, config.market.timeframe).drop(candles(600, config.market.timeframe).index[300])
    strategy = StrategyRegistry().discover().create(config)
    values = strategy.prepare_features(f)
    pd.testing.assert_frame_equal(values.iloc[300:], strategy.prepare_features(f.iloc[300:]))
    if version != "V4":
        data = {
            "frames": {"1h": f},
            "mark": f,
            "funding": pd.DataFrame({"rate": []}, index=pd.DatetimeIndex([], tz="UTC")),
        }
        blocks = prepare(data, config)
        assert len(blocks) == 2
        for source, _, _, decisions, feat in blocks:
            assert decisions.index.equals(source.index + STEPS["1h"])
            np.testing.assert_allclose(decisions.distance, feat.risk_atr * 2, equal_nan=True)


def test_shared_alignment_callback_uses_closed_complete_bars():
    f = candles(32, "15m")

    def callback(frame):
        return frame.copy()

    hourly = closed_features(f, "15m", "1h", callback)
    assert hourly.close.iloc[:3].isna().all()
    assert hourly.close.iloc[3:7].eq(f.close.iloc[3]).all()
    higher = closed_features(f.drop(f.index[2]), "15m", "4h", callback)
    assert higher.close.iloc[:-1].isna().all()
    assert higher.close.iloc[-1] == f.close.iloc[-1]


@pytest.mark.parametrize("family", FAMILIES)
def test_v4_needs_prior_hourly_opportunity_and_consumes_once(family):
    f = candles(12, "15m")
    f["previous_high"] = 1.0
    f["small_high"] = 1.0
    f["ema20"] = f.close
    f["consolidation"] = True
    f["range_expanding"] = True
    hourly = pd.DataFrame(index=f.index)
    for c in ("st_setup", "compression", "kc_event", "roc_event"):
        hourly[c] = True
    hourly["available_at"] = f.index[0]
    hourly["st_line"] = hourly["kc_middle"] = 1.0
    allowed = pd.Series(True, index=f.index)
    _, _, final, _ = v4_triggers(f, hourly, allowed, family)
    assert final.sum() == 1
    assert not final.iloc[0]
    if family in ("roc_momentum", "volatility_expansion"):
        assert not final.iloc[:3].any()
    assert not v4_triggers(f, hourly, ~allowed, family)[2].any()
    hourly["available_at"] = f.index[0] - STEPS["4h"]
    assert not v4_triggers(f, hourly, allowed, family)[2].any()
    hourly["available_at"] = f.index[0]
    for c in ("st_setup", "compression", "kc_event", "roc_event"):
        hourly[c] = False
    assert not v4_triggers(f, hourly, allowed, family)[2].any()
