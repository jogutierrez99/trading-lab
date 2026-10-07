"""Tiny synthetic full workflow, immutable publication and explicit exit freeze."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml
from test_lab import lab as lab_fixture
from test_lab_research_workflow import fingerprint
from test_trend_volatility_breakout_v1 import candles

from quant_lab.config import StrategyConfig, load_yaml
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import save_bundle
from quant_lab.lab_comparison import compare
from quant_lab.lab_evidence import completed_run
from quant_lab.lab_runner import prepare, run
from quant_lab.lab_schema import Experiment, resolve
from quant_lab.lab_trend_expansion import (
    EXPERIMENTS,
    EXPORTS,
    FAMILIES,
    distribution,
    main,
    prepare_exits,
    publish,
    region_neighbors,
    report,
)
from quant_lab.strategies.registry import StrategyRegistry

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sources(tmp_path):
    root, path, base, frame = lab_fixture.__wrapped__(tmp_path)
    request = HistoryRequest(
        symbol="ETH/USDT",
        start=datetime(2022, 1, 2, tzinfo=UTC),
        end=datetime(2022, 1, 18, tzinfo=UTC),
        warmup_bars=24,
    )
    eth = save_bundle(root / "data", frame, request, [])
    registry = StrategyRegistry().discover()
    strategies = (
        "ema_pullback",
        "atr_volatility_breakout",
        "donchian_trend_breakout",
        "donchian_atr_breakout",
    )
    plans = []
    for family, name, identity in zip(FAMILIES, strategies, EXPERIMENTS, strict=True):
        params = registry.implementation(name).parameter_model().model_dump()
        if family != "pullback":
            params.update(trend_length=10, slope_lookback=2, atr_length=3, exit_length=3)
            if "fast_length" in params:
                params["fast_length"] = 3
            if "breakout_length" in params:
                params["breakout_length"] = 3
        template = StrategyConfig(name=name, enabled=True, parameters=params)
        profile = root / "configs" / (family + ".yaml")
        profile.write_text(yaml.safe_dump(template.model_dump()), encoding="utf-8")
        raw = copy.deepcopy(base)
        raw.update(
            experiment_id=identity,
            strategy=dict(id=name, config="../" + profile.name),
            strategy_parameters={}
            if family == "pullback"
            else dict(atr_stop_multiplier=[1.5, 2.0]),
            modes=["LONG_ONLY"]
            if family == "pullback"
            else ["LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"],
        )
        raw["execution"]["market_mode"] = "synthetic"
        raw["validation"]["train"]["start"] = datetime(2022, 1, 5, tzinfo=UTC)
        raw["validation"]["walk_forward"] = []
        raw["markets"][0]["warmup_bars"] = 70
        raw["markets"].append(
            dict(symbol="ETHUSDT", timeframe="1h", dataset="../../data/" + eth.name, warmup_bars=70)
        )
        exp = Experiment.model_validate(raw)
        file = root / "configs/experiments" / (identity + ".yaml")
        file.write_text(yaml.safe_dump(exp.model_dump()), encoding="utf-8")
        plans.append((file, exp))
    outputs = [run(p, e, root) for p, e in plans]
    return root, outputs


def test_distribution_correct_denominators_and_nulls():
    def trades(values):
        return [dict(net_pnl=v, side="long" if i % 2 else "short") for i, v in enumerate(values)]

    out = distribution(trades([-1.0] * 98 + [50.0, 150.0]))
    assert out["top_1pct_net_pnl"] == 150.0
    assert out["top_1pct_net_share_pct"] == pytest.approx(150 / 102 * 100)
    assert out["net_pnl_without_best"] == -48.0
    assert out["median_winner"] == 100.0 and out["median_loser"] == -1.0
    assert distribution(trades([-1.0, 0.0]))["top_1pct_net_share_pct"] is None
    assert distribution([])["median_winner"] is None
    assert distribution(trades([2.0, 3.0]))["payoff_ratio"] is None


def test_report_publish_and_standard_compare_sources_immutable(sources, monkeypatch):
    root, runs = sources
    before = [fingerprint(p) for p in runs]
    monkeypatch.setattr(
        "quant_lab.lab_runner.evaluate",
        lambda *a: pytest.fail("No simulation in report/publication"),
    )
    directory = report(root, [p.name for p in runs])
    table = pd.read_csv(directory / "summary.csv")
    assert set(table.family) == set(FAMILIES)
    assert set(table.symbol) == {"BTCUSDT", "ETHUSDT"}
    assert set(table[table.family != "pullback"]["mode"]) == {
        "LONG_ONLY",
        "SHORT_ONLY",
        "LONG_SHORT",
    }
    assert table[table.family == "pullback"]["mode"].eq("LONG_ONLY").all()
    assert table["total_modeled_costs"].notna().all()
    neighbors = pd.read_csv(directory / "parameter_robustness.csv")
    assert neighbors.period.eq("train").all() and neighbors.scenario.eq("base").all()
    assert set(neighbors.parameter) == {"atr_stop_multiplier"}
    comparison = compare(root, list(EXPERIMENTS))
    assert set(pd.read_csv(comparison / "comparison.csv").symbol) == {"BTCUSDT", "ETHUSDT"}
    publication = publish(root, directory.name)
    dest = Path(publication["publication_directory"])
    assert set(publication["published"]) == set(EXPORTS) | {"metadata.json"}
    assert not list(dest.glob("*.parquet")) and not list(dest.glob("*.sqlite"))
    assert str(root) not in (dest / "sources.json").read_text()
    assert [fingerprint(p) for p in runs] == before
    with pytest.raises(FileExistsError):
        publish(root, directory.name)
    with pytest.raises(ValueError, match="file limit"):
        publish(root, directory.name, max_bytes=1)
    assert main(["--root", str(root), "trend-expansion", "validate"]) == 0
    (directory / "summary.csv").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        publish(root, directory.name)


def test_prepare_exits_freezes_entry_without_simulation(sources, monkeypatch):
    root, runs = sources
    evidence = completed_run(root, runs[1].name)
    candidate = evidence["metrics"].query('period == "train" and scenario == "base"').iloc[0]
    before = fingerprint(runs[1])
    monkeypatch.setattr("quant_lab.lab_runner.evaluate", lambda *a: pytest.fail("No simulation"))
    result = prepare_exits(
        root,
        runs[1].name,
        candidate.configuration_id,
        "Human review of TRAIN regions and adverse diagnostics; exploratory history",
        "exit_test",
    )
    assert len(result["experiments"]) == 4
    for name in result["experiments"]:
        path, exp = resolve(root / "configs/experiments", name)
        context = prepare(path, exp, full=True)
        assert len(context["parameters"]) == 1
        assert exp.modes == [candidate["mode"]]
        assert exp.markets[0].symbol == candidate.symbol
        params = json.loads(candidate.parameters)
        assert all(
            context["parameters"][0][k] == v for k, v in params.items() if k != "exit_method"
        )
        assert context["template"].risk.trailing_basis == "close"
    assert fingerprint(runs[1]) == before
    with pytest.raises(FileExistsError):
        prepare_exits(root, runs[1].name, candidate.configuration_id, "Same decision", "exit_test")
    benchmark = completed_run(root, runs[0].name)
    with pytest.raises(ValueError, match="three comparable"):
        prepare_exits(
            root,
            runs[0].name,
            benchmark["metrics"].iloc[0].configuration_id,
            "Keep benchmark frozen",
            "invalid",
        )


def test_report_rejects_partial_or_mixed_protocol(sources):
    root, runs = sources
    with pytest.raises(ValueError, match="order"):
        report(root, list(reversed([p.name for p in runs])))
    data = json.loads((runs[0] / "outcome.json").read_text())
    data["status"] = "FAILED"
    (runs[0] / "outcome.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="COMPLETE"):
        report(root, [p.name for p in runs])


def test_region_neighbors_never_consults_test():
    frame = pd.DataFrame(
        [
            dict(
                family="x",
                symbol="BTCUSDT",
                timeframe="1h",
                mode="LONG_ONLY",
                period=period,
                scenario="base",
                parameters=json.dumps(dict(length=length)),
                configuration_id=str(length),
                expectancy=value,
                profit_factor=1.1,
                return_pct=1.0,
                max_drawdown_pct=2.0,
                closed_trades=100,
            )
            for period, value in (("train", 1.0), ("test", -999.0))
            for length in (30, 40, 50)
        ]
    )
    neighbors = region_neighbors(frame)
    assert len(neighbors) == 2 and neighbors.both_positive_expectancy.all()
    assert not ((neighbors.value_a == 30) & (neighbors.value_b == 50)).any()


def test_repository_protocols_strict_and_comparable():
    registry = StrategyRegistry().discover()
    grids = []
    for identity in EXPERIMENTS:
        path, exp = resolve(ROOT / "configs/experiments", identity)
        cls = registry.implementation(exp.strategy.id)
        template = load_yaml(path.parent / exp.strategy.config, StrategyConfig)
        grids.append(
            [
                cls.parameter_model.model_validate(template.parameters | p).model_dump()
                for p in exp.grid()
            ]
        )
        assert all(m.timeframe == "1h" and m.warmup_bars == 1000 for m in exp.markets)
        assert set(m.symbol for m in exp.markets) == {"BTCUSDT", "ETHUSDT"}
        assert exp.costs.model_dump() == dict(
            trading_fee_pct=0.05, slippage_pct=0.03, spread_pct=0.01
        )
        assert exp.validation.test.start == datetime(2025, 7, 1, tzinfo=UTC)
    assert list(map(len, grids)) == [1, 6, 3, 6]
    assert registry.implementation("ema_pullback").lab_modes == ("LONG_ONLY",)


@pytest.mark.parametrize(
    "name", ["donchian_trend_breakout", "atr_volatility_breakout", "donchian_atr_breakout"]
)
def test_real_strategy_signal_enters_next_open_using_signal_atr(name):
    from quant_lab.config import AppConfig, RiskConfig
    from quant_lab.execution_config import ExecutionConfig
    from quant_lab.features import atr
    from quant_lab.study_backend import Segment, StudyBackend

    s = StrategyRegistry().discover().create(StrategyConfig(name=name, enabled=True))
    frame = candles()
    frame["high"] = frame.close + 1
    frame["low"] = frame.close - 1
    last = frame.iloc[-1].copy()
    entry_reference = float(last.close + 1)
    extra = pd.DataFrame(
        [
            dict(
                open=entry_reference,
                high=entry_reference + 0.1,
                low=entry_reference - 0.1,
                close=entry_reference,
                volume=10.0,
            )
        ]
        * 2,
        index=pd.date_range(frame.index[-1] + pd.Timedelta(hours=1), periods=2, freq="h", tz="UTC"),
    )
    all_candles = pd.concat([frame, extra])
    signals = s.generate_signals(all_candles)
    assert signals.long_entries[1199] and not any(signals.long_entries[:1199])
    segment = Segment("BTCUSDT", "1h", frame.index[1198], extra.index[-1] + pd.Timedelta(hours=1))
    distances = atr(all_candles, 14) * 2
    result = StudyBackend().run(
        all_candles,
        signals,
        distances,
        segment,
        AppConfig(),
        RiskConfig(),
        ExecutionConfig(
            quantity_step=0.000001,
            min_quantity=0.000001,
            min_notional=1.0,
            filter_assumption="Synthetic next-open regression",
        ),
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_time == extra.index[0] and trade.signal_close == extra.index[0]
    assert trade.entry_reference == entry_reference
    assert trade.stop == pytest.approx(trade.entry_price - distances.iloc[1199])
    assert trade.target == pytest.approx(trade.entry_price + distances.iloc[1199] * 2)
