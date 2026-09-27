"""Common sizing, segment resets and signal diagnostics across MTF architectures."""

from pathlib import Path

import numpy as np
import pandas as pd

from quant_lab.backtest import BacktestResult
from quant_lab.config import (
    CostsConfig,
    MarketConfig,
    RiskConfig,
    StrategyConfig,
    StrictModel,
    load_yaml,
)
from quant_lab.mtf_clock import execute
from quant_lab.mtf_features import STEPS
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.study_execution import continuous_blocks

FAMILIES = ("trend_pullback", "bollinger", "donchian", "ema_adx")


class Settings(StrictModel):
    source_run: str
    capital: float
    risk: RiskConfig
    costs: dict[str, CostsConfig]


def settings() -> Settings:
    return load_yaml(Path("configs/profiles/mtf_series.yaml"), Settings)


def configuration(asset: str, family: str, architecture: str, mode="LONG_ONLY") -> StrategyConfig:
    inherited = settings()
    return StrategyConfig(
        name="mtf_" + family,
        enabled=True,
        risk=inherited.risk,
        market=MarketConfig(
            provider="binance_usdm",
            symbol=asset.replace("USDT", "/USDT"),
            timeframe="15m" if architecture in {"V3", "V4"} else "1h",
        ),
        parameters={"architecture": architecture, "trade_mode": mode},
    )


def prepare(dataset: dict, config: StrategyConfig) -> list:
    strategy = StrategyRegistry().discover().create(config)
    tf = config.market.timeframe
    step = STEPS[tf]
    blocks = []
    for hourly in continuous_blocks(dataset["frames"]["1h"], "1h"):
        left, right = hourly.index[0], hourly.index[-1] + STEPS["1h"]
        source = hourly if tf == "1h" else dataset["quarter"].loc[left : right - step]
        mark = dataset["mark"] if tf == "1h" else dataset["quarter_mark"]
        f = strategy.prepare_features(source)
        decisions = pd.DataFrame(
            {
                "le": strategy.generate_long_entries(f),
                "se": strategy.generate_short_entries(f),
                "lx": strategy.generate_long_exits(f),
                "sx": strategy.generate_short_exits(f),
                "distance": f.risk_atr * config.risk.atr_multiplier,
            },
            index=source.index + step,
        )
        # Series alignment must be by position when changing the index to close availability.
        decisions["distance"] = (f.risk_atr * config.risk.atr_multiplier).to_numpy()
        blocks.append(
            (
                source,
                mark.loc[source.index],
                dataset["funding"].loc[left : right - pd.Timedelta(nanoseconds=1)],
                decisions,
                f,
            )
        )
    return blocks


def execute_window(
    blocks: list,
    config: StrategyConfig,
    start,
    end,
    costs,
    capital: float,
    include_funding=True,
    execution_policy_factory=None,
):
    tf = config.market.timeframe
    step = STEPS[tf]
    direction = {"LONG_ONLY": "long", "SHORT_ONLY": "short", "LONG_SHORT": "combined"}[
        config.parameters["trade_mode"]
    ]
    trades = []
    rejections = []
    events = []
    equities = []
    exposures = []
    sides = []
    balance = capital
    turnover = 0.0
    for source, mark, funding, decisions, _features in blocks:
        left, right = max(start, source.index[0]), min(end, source.index[-1] + step)
        if right <= left:
            continue
        source = source.loc[left : right - step]
        dec = decisions.loc[(decisions.index > left) & (decisions.index < right)]
        policy = (
            execution_policy_factory(_features, left, right) if execution_policy_factory else None
        )
        result, side, fund_events = execute(
            source,
            mark.loc[source.index],
            funding.loc[left : right - pd.Timedelta(nanoseconds=1)],
            dec,
            left,
            right,
            costs,
            config.risk,
            balance,
            include_funding,
            direction,
            tf,
            execution_policy=policy,
        )
        if policy is not None:
            policy.finalize(right, "gap_or_segment_end" if right < end else "window_end")
        previous = balance
        for t in result.trades:
            if t.entry_time != t.signal_close or not left < t.entry_time < right:
                raise AssertionError("Non-causal entry chronology")
            if t.quantity * t.entry_price + t.entry_fee > previous * 0.25 + 1e-6:
                raise AssertionError("Inherited entry exposure cap exceeded")
            if t.expected_stop_loss > t.risk_budget + 1e-6:
                raise AssertionError("Inherited planned risk cap exceeded")
            previous += t.net_pnl
        trades.extend(result.trades)
        rejections.extend(result.rejections)
        events.extend(fund_events)
        equities.append(result.equity)
        exposures.append(result.exposure)
        sides.append(side)
        balance = float(result.equity.iloc[-1])
        turnover += result.turnover
    index = pd.date_range(start, end, freq=step)

    def merge(parts, initial, cash=False):
        if not parts:
            return pd.Series(initial, index=index)
        values = pd.concat(parts)
        values = values[~values.index.duplicated(keep="last")].sort_index().reindex(index)
        values.loc[start] = initial
        return values.ffill() if cash else values.fillna(0)

    result = BacktestResult(
        tuple(trades),
        merge(equities, capital, True),
        tuple(rejections),
        None,
        direction,
        "perpetual",
        merge(exposures, 0.0),
        turnover,
    )
    if not np.isclose(result.equity.iloc[-1] - capital, sum(t.net_pnl for t in trades), atol=1e-6):
        raise AssertionError("Window equity reconciliation")
    return result, merge(sides, 0), events


def diagnostics(blocks: list, config: StrategyConfig, start, end, result, sides) -> dict:
    tf = config.market.timeframe
    step = STEPS[tf]
    mode = config.parameters["trade_mode"]
    directions = [
        s
        for s in ("long", "short")
        if mode == "LONG_SHORT" or (mode == "LONG_ONLY") == (s == "long")
    ]
    counts = {"raw_signals_15m": 0, "signals_after_1h_filter": 0, "signals_after_4h_filter": 0}
    samples = {
        s: {group: {h: [] for h in (6, 24, 72)} for group in ("accepted", "rejected")}
        for s in directions
    }
    delays = []
    entered = {t.entry_time: t.side for t in result.trades}
    for frame, _mark, _funding, _decisions, f in blocks:
        available = f.index + step
        eligible = (available > start) & (available < end)
        for side in directions:
            raw = f[f"{side}_raw"] & eligible
            setup = f[f"{side}_confirmed"] & eligible
            final = f[f"{side}_final"] & eligible
            counts["raw_signals_15m"] += int(raw.sum())
            counts["signals_after_1h_filter"] += int(setup.sum())
            counts["signals_after_4h_filter"] += int(final.sum())
            for group, mask in (("accepted", final), ("rejected", setup & ~final)):
                sign = 1 if side == "long" else -1
                for h in (6, 24, 72):
                    n = int(pd.Timedelta(hours=h) / step)
                    forward = sign * (frame.close.shift(-n) / frame.open.shift(-1) - 1) * 100
                    values = forward.loc[mask & (available + pd.Timedelta(hours=h) <= end)].dropna()
                    samples[side][group][h].extend(values.tolist())
            for t in available[final]:
                if entered.get(t) == side:
                    age = f.loc[t - step, f"{side}_delay_hours"]
                    if pd.notna(age):
                        delays.append(float(age))
    base = counts["signals_after_1h_filter"]
    accepted = counts["signals_after_4h_filter"]
    counts.update(
        SIGNALS_BASELINE=base,
        SIGNALS_ACCEPTED_BY_4H=accepted,
        SIGNALS_REJECTED_BY_4H=base - accepted,
        final_entries=len(result.trades),
        filter_rejection_rate=(base - accepted) / base if base else None,
        average_delay_to_entry=float(np.mean(delays)) if delays else None,
        delay_observations=len(delays),
        time_in_market_pct=float((sides.iloc[1:] != 0).mean() * 100),
        trades_per_month=len(result.trades) / ((end - start).total_seconds() / 86400 / 30.4375),
        execution_bar_minutes=int(step.total_seconds() / 60),
    )
    summary = {
        side: {
            group: {
                str(h): {"n": len(v), "mean_return_pct": float(np.mean(v)) if v else None}
                for h, v in horizons.items()
            }
            for group, horizons in groups.items()
        }
        for side, groups in samples.items()
    }
    return {
        "counts": counts,
        "signal_follow_through": summary,
        "note": "Forward returns are post-run raw-price diagnostics, not "
        "executable rejected-signal PnL. "
        "Delay measures age of observed pullback touch for filled entries "
        "only, not matched V1 delay. "
        "raw_signals_15m uses the actual execution timeframe, recorded in execution_bar_minutes.",
    }
