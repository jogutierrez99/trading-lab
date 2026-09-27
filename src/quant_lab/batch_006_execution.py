"""Bridge frozen Bollinger decisions to an hourly perpetual execution clock."""

import pandas as pd

from quant_lab.backtest import BacktestResult
from quant_lab.config import MarketConfig, RiskConfig, StrategyConfig
from quant_lab.perpetual_execution import FuturesAssumptions, run_perpetual
from quant_lab.strategies.bollinger_regime_reversal import VARIANTS, BollingerRegimeReversalStrategy
from quant_lab.study_data import HOURS, hours_to_bars
from quant_lab.study_execution import continuous_blocks
from quant_lab.study_features import regimes

MODES = {"LONG_ONLY": "long", "SHORT_ONLY": "short", "LONG_SHORT": "combined"}


def configuration(asset, tf, variant, mode):
    return StrategyConfig(
        name="bollinger_regime_reversal",
        enabled=True,
        market=MarketConfig(
            provider="binance_usdm", symbol=asset.replace("USDT", "/USDT"), timeframe=tf
        ),
        parameters={"variant": variant, "trade_mode": mode},
        risk=RiskConfig(
            risk_per_trade_pct=0.5,
            max_position_pct=25.0,
            max_exposure_pct=25.0,
            atr_multiplier=VARIANTS[variant]["stop_atr"],
            take_profit_enabled=False,
            max_holding_bars=hours_to_bars(72, tf),
        ),
    )


def prepare_market(dataset, asset, tf, variant, mode):
    strategy = BollingerRegimeReversalStrategy(configuration(asset, tf, variant, mode))
    blocks = []
    for execution in continuous_blocks(dataset["frames"]["1h"], "1h"):
        start, end = execution.index[0], execution.index[-1] + pd.Timedelta(hours=1)
        source = dataset["frames"][tf].loc[start : end - pd.Timedelta(hours=HOURS[tf])]
        features = strategy.prepare_features(source)
        sig = strategy.generate_signals(source)
        decisions = pd.DataFrame(
            {
                "le": sig.long_entries,
                "lx": sig.long_exits,
                "se": sig.short_entries,
                "sx": sig.short_exits,
                "distance": features.atr * VARIANTS[variant]["stop_atr"],
            },
            index=source.index,
        )
        labels = regimes(source, tf)
        decisions.index += pd.Timedelta(hours=HOURS[tf])
        labels.index += pd.Timedelta(hours=HOURS[tf])
        blocks.append(
            (
                execution,
                dataset["mark"].loc[execution.index],
                dataset["funding"].loc[start : end - pd.Timedelta(nanoseconds=1)],
                decisions,
                labels,
            )
        )
    return blocks


def execute_window(
    blocks, tf, variant, mode, start, end, costs, include_funding=True, benchmark=None
):
    # Time stop is72 elapsed hours on the execution clock, equal to72/18/3 strategy bars.
    risk = RiskConfig(
        risk_per_trade_pct=0.5,
        max_position_pct=25.0,
        max_exposure_pct=25.0,
        atr_multiplier=VARIANTS[variant]["stop_atr"],
        take_profit_enabled=False,
        max_holding_bars=72,
    )
    if benchmark is not None:
        risk = RiskConfig(
            sizing_method="fixed_notional",
            position_pct=float(benchmark),
            max_position_pct=float(benchmark),
            max_exposure_pct=100.0,
            stop_enabled=False,
            take_profit_enabled=False,
        )
    trades, rejections, events, equities, exposures, sides, all_labels = [], [], [], [], [], [], []
    balance = 10000.0
    turnover = 0.0
    for source, mark, funding, decisions, labels in blocks:
        left, right = (
            max(start, source.index[0]),
            min(end, source.index[-1] + pd.Timedelta(hours=1)),
        )
        if right <= left:
            continue
        frame = source.loc[left : right - pd.Timedelta(hours=1)]
        dec = decisions.loc[(decisions.index > left) & (decisions.index < right)].copy()
        # Do not reuse a decision at a later hour: signals are one-time close events.
        if benchmark is not None:
            dec = pd.DataFrame(
                {"le": True, "lx": False, "se": False, "sx": False, "distance": 1.0},
                index=frame.index[1:2],
            )
        result, direction, fund_events = run_perpetual(
            frame,
            mark.loc[frame.index],
            funding.loc[left : right - pd.Timedelta(nanoseconds=1)],
            dec,
            left,
            right,
            costs,
            risk,
            FuturesAssumptions(),
            balance,
            include_funding,
            MODES[mode],
        )
        previous_equity = balance
        for t in result.trades:
            if t.entry_time != t.signal_close or not left < t.entry_time < right:
                raise AssertionError("Signal/fill chronology violated")
            if (
                t.quantity * t.entry_price + t.entry_fee
                > previous_equity * min(risk.max_position_pct, risk.max_exposure_pct) / 100 + 1e-6
            ):
                raise AssertionError("Exposure cap exceeded")
            if t.expected_stop_loss is not None and t.expected_stop_loss > t.risk_budget + 1e-6:
                raise AssertionError("Initial risk cap exceeded")
            previous_equity += t.net_pnl
        balance = float(result.equity.iloc[-1])
        turnover += result.turnover
        trades.extend(result.trades)
        rejections.extend(result.rejections)
        events.extend(fund_events)
        equities.append(result.equity)
        exposures.append(result.exposure)
        sides.append(direction)
        all_labels.append(labels)
    index = pd.date_range(start, end, freq="h")

    def combine(series, initial, fill):
        if not series:
            return pd.Series(initial, index=index)
        result = pd.concat(series)
        result = result[~result.index.duplicated(keep="last")]
        result.loc[start] = initial
        result = result.sort_index().reindex(index)
        return result.ffill() if fill else result.fillna(0)

    equity = combine(equities, 10000.0, True)
    exposure = combine(exposures, 0.0, False)
    direction = combine(sides, 0, False)
    result = BacktestResult(
        tuple(trades), equity, tuple(rejections), None, MODES[mode], "perpetual", exposure, turnover
    )
    labels = pd.concat(all_labels) if all_labels else pd.DataFrame()
    return result, direction, events, labels


def walk_forward_windows(start, end):
    cursor = start
    folds = []
    while cursor + pd.DateOffset(months=15) <= end:
        middle = cursor + pd.DateOffset(months=12)
        stop = middle + pd.DateOffset(months=3)
        folds.append((cursor, middle, stop))
        cursor += pd.DateOffset(months=3)
    return folds
