"""Deterministic close-time setup state, rebuilt for each input prefix."""

import numpy as np
import pandas as pd


def channel_retest(features: pd.DataFrame) -> pd.DataFrame:
    entries, anchors, phases = [], [], []
    breakout_at = retest_at = None
    level = tolerance = retest_high = anchor = float("nan")
    for i, row in enumerate(features.itertuples()):
        entry, stop, phase = False, float("nan"), "idle"
        if breakout_at is not None:
            if row.close < row.ema200:
                breakout_at = retest_at = None
                phase = "cancelled_trend"
            elif retest_at is None:
                if i - breakout_at > 24:
                    breakout_at = None
                    phase = "expired_retest"
                elif row.low <= level + tolerance and row.close >= level - tolerance:
                    retest_at, retest_high = i, row.high
                    anchor = row.low - 0.01 * row.atr
                    phase = "retested"
                else:
                    phase = "waiting_retest"
            elif row.close > retest_high:
                entry, stop, phase = True, anchor, "confirmed"
                breakout_at = retest_at = None
            else:
                phase = "waiting_confirmation"
        elif row.close > row.prior_high and row.ema50 > row.ema200 and np.isfinite(row.atr):
            breakout_at, level, tolerance = i, row.prior_high, 0.25 * row.atr
            phase = "breakout"
        entries.append(entry)
        anchors.append(stop)
        phases.append(phase)
    return pd.DataFrame(
        {"entry": entries, "stop_anchor": anchors, "setup_phase": phases}, index=features.index
    )


def rsi_reset(features: pd.DataFrame, threshold: int, expiry: int) -> pd.DataFrame:
    reset_at = None
    previous = float("nan")
    entries, ages = [], []
    for i, row in enumerate(features.itertuples()):
        if reset_at is not None and i - reset_at > expiry:
            reset_at = None
        regime = row.ema50 > row.ema200 and row.roc30 > 0
        if reset_at is None and previous >= threshold > row.rsi and regime:
            reset_at = i
        age = float("nan") if reset_at is None else float(i - reset_at)
        entry = (
            reset_at is not None
            and i > reset_at
            and previous <= 50 < row.rsi
            and row.close > row.ema50
            and regime
        )
        if entry:
            reset_at = None
        previous = row.rsi
        entries.append(bool(entry))
        ages.append(age)
    return pd.DataFrame({"entry": entries, "reset_age": ages}, index=features.index)
