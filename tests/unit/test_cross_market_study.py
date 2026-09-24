"""Causal translations, archive integrity and multi-timeframe execution regressions."""

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quant_lab.backtest import ReferenceBackend
from quant_lab.batch import COSTS, Candidate, resolve_candidate
from quant_lab.config import AppConfig, RiskConfig, load_research_config
from quant_lab.cross_market_study import execution_config
from quant_lab.history import HistoryRequest
from quant_lab.strategies.base import Signals
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.study_analysis import jaccard, overlaps, stability
from quant_lab.study_backend import Segment, StudyBackend
from quant_lab.study_data import (
    aggregate_check,
    audit,
    days_to_bars,
    digest,
    download_one,
    hours_to_bars,
    pages,
    parse,
)
from quant_lab.study_excursions import entry_diagnostics
from quant_lab.study_execution import continuous_blocks, execute, prepare_blocks
from quant_lab.study_features import prepare, unsupported
from quant_lab.study_plan import CHOICES, matrix, windows

ROOT = Path(__file__).resolve().parents[2]


def candles(n=2000, tf="1h"):
    rng = np.random.default_rng(17)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, n)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": np.ones(n),
        },
        index=pd.date_range("2020-01-01", periods=n, freq=tf, tz="UTC"),
    )


@pytest.fixture(scope="module")
def strategies():
    registry = StrategyRegistry().discover()
    result = []
    for batch, choices in CHOICES.items():
        folder = ROOT / f"configs/profiles/batch_{batch:03}"
        research = load_research_config(folder / "app.yaml")
        candidates = yaml.safe_load((folder / "batch.yaml").read_text())["candidates"]
        for choice in choices:
            raw = next(c for c in candidates if c["id"] == choice)
            cfg = resolve_candidate(research, Candidate.model_validate(raw)).strategies[0]
            result.append(registry.create(cfg))
    return result


@pytest.mark.parametrize("tf,hours", [("1h", 1), ("4h", 4), ("1d", 24)])
def test_exact_durations(tf, hours):
    assert days_to_bars(30, tf) == 720 // hours
    assert hours_to_bars(48, tf) == 48 // hours
    with pytest.raises(ValueError):
        hours_to_bars(0, tf)
    with pytest.raises(ValueError):
        hours_to_bars(1.5, tf)
    with pytest.raises(ValueError):
        hours_to_bars(12, "1d")


def test_original_hourly_signals_and_features_preserved(strategies):
    frame = candles()
    for strategy in strategies:
        original = strategy.prepare_features(frame)
        translated = prepare(strategy, frame, "1h")
        pd.testing.assert_frame_equal(original, translated)
        assert strategy.generate_long_entries(original) == strategy.generate_long_entries(
            translated
        )


@pytest.mark.parametrize("tf", ["1h", "4h", "1d"])
def test_all_translations_are_prefix_invariant(strategies, tf):
    frame = candles(tf=tf)
    for strategy in strategies:
        if unsupported(strategy.name, tf):
            with pytest.raises(ValueError):
                prepare(strategy, frame, tf)
            continue
        whole = prepare(strategy, frame, tf)
        prefix = prepare(strategy, frame.iloc[:1700], tf)
        pd.testing.assert_frame_equal(whole.iloc[:1700], prefix)
        assert strategy.generate_long_entries(whole)[:1700] == strategy.generate_long_entries(
            prefix
        )


def test_audit_rejects_and_hash_separates_assets():
    frame = candles(24)
    assert audit(frame, "BTCUSDT", "1h")["status"] == "VALID"
    assert digest(frame, "BTCUSDT", "1h") != digest(frame, "ETHUSDT", "1h")
    missing = frame.drop(frame.index[5:8])
    result = audit(missing, "BTCUSDT", "1h")
    assert result["missing_bars"] == 3 and result["largest_gap"] == 3
    assert result["status"] == "VALID_WITH_GAPS"
    assert audit(pd.concat([frame, frame.iloc[:1]]), "BTCUSDT", "1h")["status"] == "INVALID"
    assert audit(frame.iloc[::-1], "BTCUSDT", "1h")["status"] == "INVALID"
    frame.iloc[0, frame.columns.get_loc("volume")] = -1
    assert audit(frame, "BTCUSDT", "1h")["status"] == "INVALID"


def test_aggregation_volume_discrepancies_and_partial_groups():
    frame = candles(48)
    direct = frame.resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    assert aggregate_check(frame, direct, "4h")["status"] == "PASS"
    direct.iloc[3, 4] += 1
    assert aggregate_check(frame, direct, "4h")["mismatches"] == 1
    partial = frame.drop(frame.index[0])
    assert aggregate_check(partial, direct, "4h")["compared_bars"] == 11


def archive(asset="BTCUSDT", tf="1h", stamp="2020-01-01"):
    first = pd.Timestamp(stamp, tz="UTC")
    row = [
        first.value // 10**6,
        100,
        102,
        98,
        101,
        5,
        (first + pd.Timedelta(tf)).value // 10**6 - 1,
        0,
        1,
        0,
        0,
        0,
    ]
    content = (",".join(map(str, row)) + "\n").encode()
    out = io.BytesIO()
    name = f"{asset}-{tf}-{stamp}"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(name + ".csv", content)
    payload = out.getvalue()
    return payload, content, name


def test_downloader_resume_checksum_and_asset_separation(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        asset = "ETHUSDT" if "ETHUSDT" in url else "BTCUSDT"
        payload, _, name = archive(asset)
        return (
            f"{hashlib.sha256(payload).hexdigest()}  {name}.zip".encode()
            if url.endswith("CHECKSUM")
            else payload
        )

    a = download_one(tmp_path, "BTCUSDT", "1h", "2020-01-01T00:00Z", "2020-01-02T00:00Z", fetch)
    before = len(calls)
    assert (
        download_one(tmp_path, "BTCUSDT", "1h", "2020-01-01T00:00Z", "2020-01-02T00:00Z", fetch)
        == a
    )
    assert len(calls) == before
    b = download_one(tmp_path, "ETHUSDT", "1h", "2020-01-01T00:00Z", "2020-01-02T00:00Z", fetch)
    assert a != b
    manifest = json.loads((Path(a) / "manifest.json").read_text())
    raw = tmp_path / "BTCUSDT/1h/raw" / (manifest["sources"][0]["sha256"] + ".zip")
    raw.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="No reliable"):
        download_one(tmp_path, "BTCUSDT", "1h", "2020-01-01T00:00Z", "2020-01-02T00:00Z", fetch)


def test_pagination_and_microseconds():
    result = list(pages("2020-01-01T00:00Z", "2020-03-03T00:00Z"))
    assert [r[0] for r in result] == ["monthly", "monthly", "daily", "daily"]
    _, content, _ = archive()
    frame = parse(content, "1h")
    row = content.decode().strip().split(",")
    row[0] = str(int(row[0]) * 1000)
    row[6] = str(int(row[6]) * 1000 + 999)
    pd.testing.assert_frame_equal(frame, parse((",".join(row) + "\n").encode(), "1h"))


@pytest.mark.parametrize("tf", ["1h", "4h", "1d"])
def test_next_open_costs_and_excursion_duration(tf):
    frame = candles(5, tf)
    sig = Signals(
        (True, False, False, False, False),
        (False, False, True, False, False),
        (False,) * 5,
        (False,) * 5,
    )
    history = Segment("BTCUSDT", tf, frame.index[0], frame.index[-1] + pd.Timedelta(tf))
    risk = RiskConfig(sizing_method="fixed_notional", stop_enabled=False, take_profit_enabled=False)
    result = StudyBackend().run(
        frame,
        sig,
        pd.Series(1.0, index=frame.index),
        history,
        AppConfig(costs=COSTS["base"]),
        risk,
        execution_config("BTCUSDT"),
    )
    trade = result.trades[0]
    assert trade.entry_time == frame.index[1] == trade.signal_close
    assert trade.exit_bar_open == frame.index[3]
    assert trade.entry_price == pytest.approx(frame.open.iloc[1] * 1.00025)
    assert trade.entry_fee > 0 and trade.exit_fee > 0
    q, e, _ = entry_diagnostics(frame, result, tf)
    assert "1_bars" in e["summary"] and "168_hours" in e["summary"]
    upper = q["trades"][0]["time_to_mfe_hours_upper"]
    lower = q["trades"][0]["time_to_mfe_hours_lower"]
    assert upper - lower <= pd.Timedelta(tf).total_seconds() / 3600
    assert e["summary"]["24_bars"]["censored"] == 1
    if tf == "1h":
        old = ReferenceBackend().run(
            frame,
            sig,
            pd.Series(1.0, index=frame.index),
            HistoryRequest(
                start=datetime(2020, 1, 1, tzinfo=UTC),
                end=datetime(2020, 1, 1, 5, tzinfo=UTC),
                warmup_bars=0,
            ),
            AppConfig(costs=COSTS["base"]),
            risk,
            execution_config("BTCUSDT"),
        )
        assert old.trades == result.trades
        pd.testing.assert_series_equal(old.equity, result.equity)


def test_gap_and_partition_positions_do_not_carry(strategies):
    strategy = next(s for s in strategies if s.name == "time_series_momentum")
    frame = candles(1900).drop(candles(1900).index[1000:1024])
    assert len(continuous_blocks(frame, "1h")) == 2
    blocks = prepare_blocks(strategy, frame, "1h")
    start, end = frame.index[500], frame.index[-1] + pd.Timedelta(hours=1)
    result, _ = execute(
        strategy, blocks, "BTCUSDT", "1h", start, end, COSTS["base"], execution_config("BTCUSDT")
    )
    boundary = frame.index[999] + pd.Timedelta(hours=1)
    assert all(t.entry_time > start for t in result.trades)
    assert not any(t.entry_time < boundary < t.exit_bar_open for t in result.trades)
    assert result.open_position is None
    assert result.equity.loc[boundary : boundary + pd.Timedelta(hours=23)].nunique() == 1


def test_splits_overlap_and_annual_metrics():
    split = windows(pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC"))
    assert all(a[2] == b[1] for a, b in zip(split, split[1:], strict=False))
    assert jaccard({1, 2}, {2, 3}) == pytest.approx(100 / 3)
    assert jaccard(set(), set()) is None
    trade = {
        "entry_time": "2020-01-01T00:00Z",
        "exit_bar_open": "2020-01-01T04:00Z",
        "exit_timing": "open",
    }
    assert overlaps({"a": [trade], "b": [trade]}, "4h")[0]["holding_bar_jaccard_pct"] == 100
    annual = pd.DataFrame(
        {
            "complete_calendar_year": [True, True, False],
            "return_pct": [2, -1, 100],
            "profit_factor": [2, 0.5, 9],
            "sharpe": [1, -1, 9],
        }
    )
    assert stability(annual)["positive_year_ratio"] == 0.5
    assert stability(annual)["best_year"] == 2


def test_matrix_has_explicit_exclusions(strategies):
    configs = [{"candidate": s.name, "config": {"name": s.name}} for s in strategies]
    rows = matrix(configs)
    assert len(rows) == 114
    assert sum(r["reason"] is not None for r in rows) == 6


def test_hourly_backend_matches_all_frozen_strategies(strategies):
    from quant_lab.config import MarketsConfig, ResearchConfig
    from quant_lab.structural_execution import run_strategy005

    frame = candles()
    history = HistoryRequest(
        start=frame.index[0].to_pydatetime(),
        end=(frame.index[-1] + pd.Timedelta(hours=1)).to_pydatetime(),
        warmup_bars=0,
    )
    registry = StrategyRegistry().discover()
    for strategy in strategies:
        config = strategy.config
        research = ResearchConfig(
            app=AppConfig(costs=COSTS["base"]),
            markets=MarketsConfig(markets=[config.market]),
            risk=config.risk,
            strategies=(config,),
        )
        original = run_strategy005(
            frame, history, research, strategy.name, execution_config("BTCUSDT"), registry
        )
        translated, _ = execute(
            strategy,
            prepare_blocks(strategy, frame, "1h"),
            "BTCUSDT",
            "1h",
            frame.index[0],
            frame.index[-1] + pd.Timedelta(hours=1),
            COSTS["base"],
            execution_config("BTCUSDT"),
        )
        assert translated.trades == original.trades
        pd.testing.assert_series_equal(
            translated.equity, original.equity, check_names=False, check_freq=False
        )


def test_same_bar_stop_excursion_bounds_daily():
    frame = candles(3, "1d")
    frame.loc[:, ["open", "close"]] = 100.0
    frame.loc[:, "high"] = 110.0
    frame.loc[:, "low"] = 90.0
    signals = Signals((True, False, False), (False,) * 3, (False,) * 3, (False,) * 3)
    result = StudyBackend().run(
        frame,
        signals,
        pd.Series(5.0, index=frame.index),
        Segment("ETHUSDT", "1d", frame.index[0], frame.index[-1] + pd.Timedelta(days=1)),
        AppConfig(costs=COSTS["zero"]),
        RiskConfig(take_profit_enabled=False),
        execution_config("ETHUSDT"),
    )
    quality, _, _ = entry_diagnostics(frame, result, "1d")
    trade = quality["trades"][0]
    assert trade["mfe_pct"] == 0
    assert trade["mfe_upper_bound_pct"] == pytest.approx(10)
    assert trade["mae_pct"] == pytest.approx(5)
    assert trade["mae_upper_bound_pct"] == pytest.approx(10)
    assert trade["time_to_mae_hours_upper"] == 24
