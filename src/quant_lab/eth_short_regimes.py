"""Descriptive close-time labels only; never imported by strategy/execution code."""

import numpy as np
import pandas as pd

from quant_lab.features import atr, ema
from quant_lab.literature_features import segmented

TREND_BUCKETS = ("bearish", "bullish", "mixed", "unavailable")
VOLATILITY_BUCKETS = ("high", "ordinary", "unavailable")
MINIMUM_TRADES = 20  # Descriptive sample annotation, not a profitability gate.


def regime_features(candles: pd.DataFrame) -> pd.DataFrame:
    """EMA200 slope over five bars; ATR14 / previous 50 ATR mean; high >=1.1."""

    def calculate(frame):
        result = pd.DataFrame(index=frame.index)
        result["ema200"] = ema(frame.close, 200)
        result["ema200_slope"] = result.ema200 - result.ema200.shift(5)
        current = atr(frame, 14)
        result["atr_ratio"] = current / current.shift(1).rolling(50, min_periods=50).mean()
        result["trend"] = "mixed"
        result.loc[(frame.close < result.ema200) & (result.ema200_slope < 0), "trend"] = "bearish"
        result.loc[(frame.close > result.ema200) & (result.ema200_slope > 0), "trend"] = "bullish"
        result.loc[result.ema200_slope.isna(), "trend"] = "unavailable"
        result["volatility"] = np.where(result.atr_ratio >= 1.1, "high", "ordinary")
        result.loc[~np.isfinite(result.atr_ratio), "volatility"] = "unavailable"
        return result

    return segmented(candles, "1h", calculate)


def tag_trades(trades: list[dict], features: pd.DataFrame) -> list[dict]:
    tagged = []
    for trade in trades:
        if trade["side"] != "short":
            raise ValueError("ETH SHORT regime study contains non-short trade")
        # OHLCV index is candle OPEN; signal_close is the instant its close becomes available.
        signal = pd.Timestamp(trade["signal_close"])
        if signal.tz is None or signal.utcoffset().total_seconds() != 0:
            raise ValueError("Require UTC signal_close")
        opening = signal - pd.Timedelta(hours=1)
        if opening not in features.index:
            raise ValueError("Signal candle missing from audited period warmup")
        row = features.loc[opening]
        tagged.append(trade | {"trend": row.trend, "volatility": row.volatility})
    return tagged


def pnl_statistics(values: list[float]) -> dict:
    pnl = pd.Series(values, dtype=float)
    winners, losers = pnl[pnl > 0], pnl[pnl < 0]
    gains, losses = float(winners.sum()), float(-losers.sum())
    count = len(pnl)
    return dict(
        closed_trades=count,
        winners=len(winners),
        losers=len(losers),
        breakeven_trades=int((pnl == 0).sum()),
        net_pnl=float(pnl.sum()),
        expectancy=float(pnl.mean()) if count else None,
        profit_factor=gains / losses if losses else None,
        win_rate_pct=100 * len(winners) / count if count else None,
        median_net_pnl=float(pnl.median()) if count else None,
        sample_status="DESCRIPTIVE_SAMPLE" if count >= MINIMUM_TRADES else "INSUFFICIENT_SAMPLE",
    )


def regime_rows(identity: dict, trades: list[dict]) -> list[dict]:
    rows = []
    dimensions = {
        "trend": [(b, [t for t in trades if t["trend"] == b]) for b in TREND_BUCKETS],
        "volatility": [
            (b, [t for t in trades if t["volatility"] == b]) for b in VOLATILITY_BUCKETS
        ],
        "combined": [
            (
                f"{trend}/{volatility}",
                [t for t in trades if t["trend"] == trend and t["volatility"] == volatility],
            )
            for trend in TREND_BUCKETS
            for volatility in VOLATILITY_BUCKETS
        ],
    }
    total = sum(t["net_pnl"] for t in trades)
    for dimension, buckets in dimensions.items():
        for bucket, selected in buckets:
            stats = pnl_statistics([t["net_pnl"] for t in selected])
            rows.append(
                identity
                | stats
                | dict(
                    dimension=dimension,
                    bucket=bucket,
                    trade_share_pct=100 * len(selected) / len(trades) if trades else None,
                    net_pnl_share_pct=100 * stats["net_pnl"] / total if total > 0 else None,
                )
            )
    return rows


def outlier_rows(identity: dict, trades: list[dict]) -> list[dict]:
    ordered = sorted((t["net_pnl"] for t in trades), reverse=True)
    rows = []
    for label, count in (
        ("complete", 0),
        ("without_best", min(1, len(ordered))),
        ("without_top_5pct", int(np.ceil(len(ordered) * 0.05))),
        ("without_top_10pct", int(np.ceil(len(ordered) * 0.1))),
    ):
        rows.append(
            identity
            | pnl_statistics(ordered[count:])
            | dict(
                diagnostic=label,
                removed_trades=count,
                removed_net_pnl=sum(ordered[:count]),
                interpretation=(
                    "descriptive deletion of net PnL; no resimulation, return or drawdown"
                ),
            )
        )
    return rows
