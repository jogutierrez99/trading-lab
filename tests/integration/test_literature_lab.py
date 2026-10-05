import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quant_lab.config import load_yaml
from quant_lab.lab_comparison import compare
from quant_lab.lab_publish import publish, publish_comparison
from quant_lab.lab_runner import prepare, run
from quant_lab.lab_schema import Experiment
from quant_lab.literature_data import complete_days, load_aux
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.study_data import audit, digest

ROOT = Path(__file__).resolve().parents[2]
NAMES = [
    "donchian_trend_v1_btc_eth_4h",
    "risk_managed_momentum_v1_btc_eth_4h",
    "risk_managed_momentum_v1_btc_eth_1d",
    "rsi_momentum_regime_v1_btc_eth_4h",
    "funding_conditional_momentum_v1_btc_eth_1h",
]


def write_aux(root, candles):
    idx = pd.date_range(candles.index[0], periods=40, freq="8h") + pd.Timedelta(milliseconds=1)
    fund = pd.DataFrame({"rate": np.sin(np.arange(40)) * 0.001, "interval_hours": 8.0}, index=idx)
    mark = candles.copy()
    origins = {"funding": {"fixture": True}, "mark": {"fixture": True}}
    identity = hashlib.sha256(
        (
            "BTCUSDT"
            + fund.to_json(date_format="iso", double_precision=15)
            + digest(mark, "BTCUSDT", "1h")
            + json.dumps(origins, sort_keys=True)
        ).encode()
    ).hexdigest()
    target = root / "aux" / identity
    target.mkdir(parents=True)
    fund.to_parquet(target / "funding.parquet")
    mark.to_parquet(target / "mark.parquet")
    meta = {
        "dataset_id": identity,
        "symbol": "BTCUSDT",
        "source_funding": origins["funding"],
        "source_mark": origins["mark"],
        "funding_start": str(fund.index[0]),
        "funding_end": str(fund.index[-1]),
    }
    meta |= {
        name + "_sha256": hashlib.sha256((target / (name + ".parquet")).read_bytes()).hexdigest()
        for name in ("funding", "mark")
    }
    (target / "manifest.json").write_text(json.dumps(meta))
    return target, meta


def tiny(root, name):
    raw = yaml.safe_load((ROOT / "configs/experiments" / (name + ".yaml")).read_text())
    strategy = raw["strategy"]["id"]
    tf = raw["markets"][0]["timeframe"]
    cls = StrategyRegistry().discover().implementation(strategy)
    parameters = {
        k: v
        for k, v in {
            "ema_period": 2,
            "adx_period": 2,
            "adx_threshold": 1.0,
            "rsi_period": 2,
            "atr_period": 2,
            "momentum_lookback": 4,
            "volatility_period": 4,
            "donchian_lookback": 3,
            "funding_window": 10,
            "breakout_strength_min": 0.01,
        }.items()
        if k in cls.parameter_model.model_fields
    }
    base = cls.parameter_model.model_validate(parameters).model_dump()
    times = pd.date_range("2020-01-01", periods=300, freq=tf, tz="UTC")
    price = 100 + np.sin(np.arange(300) / 4) * 8 + np.arange(300) * 0.01
    c = pd.DataFrame(
        {
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price + np.sin(np.arange(300)) * 0.2,
            "volume": 1.0,
        },
        index=times,
    )
    quality = audit(c, "BTCUSDT", tf)
    target = root / "prices" / quality["hash"]
    target.mkdir(parents=True, exist_ok=True)
    c.to_parquet(target / "candles.parquet")
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "audit": quality,
                "parquet_sha256": hashlib.sha256(
                    (target / "candles.parquet").read_bytes()
                ).hexdigest(),
            }
        )
    )
    market = {
        "symbol": "BTCUSDT",
        "timeframe": tf,
        "dataset": str(target),
        "dataset_id": quality["hash"],
        "warmup_bars": cls.required_warmup(base, tf),
    }
    if strategy.startswith("funding"):
        aux, meta = write_aux(root, c)
        market["perpetual_data"] = {"dataset": str(aux), "dataset_id": meta["dataset_id"]}
    points = [times[i].to_pydatetime() for i in (100, 140, 180, 220)]
    raw |= {
        "markets": [market],
        "strategy_parameters": {k: [v] for k, v in base.items()},
        "diagnostic_periods": {"diagnostic_small": {"start": points[0], "end": points[-1]}},
    }
    raw["validation"] |= {
        label: {"start": points[i], "end": points[i + 1]}
        for i, label in enumerate(("train", "validation", "test"))
    }
    path = root / "configs/experiments" / (name + ".yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path, Experiment.model_validate(raw)


@pytest.mark.parametrize("name", NAMES)
def test_frozen_experiments_no_search(name):
    path = ROOT / "configs/experiments" / (name + ".yaml")
    exp = load_yaml(path, Experiment)
    context = prepare(path, exp)
    assert exp.combinations == 1 and len(context["parameters"]) == 1
    assert exp.validation.walk_forward == []
    assert context["backtests"] == (84 if name.endswith("1d") else 120)
    assert exp.modes == ["LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"]


def test_real_pipeline_small_windows_modes_funding_resume_publication_compare(tmp_path):
    root = tmp_path
    shutil.copytree(ROOT / "configs", root / "configs")
    shutil.copyfile(ROOT / "pyproject.toml", root / "pyproject.toml")
    shutil.copytree(ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    runs = []
    for name in NAMES:
        path, exp = tiny(root, name)
        assert prepare(path, exp, full=True)["backtests"] == 24
        source = run(path, exp, root)
        runs.append(source)
        table = pd.read_csv(source / "metrics.csv")
        assert len(table) == 24 and table.status.eq("completed").all()
        assert table.closed_trades.sum() > 0
        assert table.loc[table["mode"] == "LONG_ONLY", "short_trades"].eq(0).all()
        assert table.loc[table["mode"] == "SHORT_ONLY", "long_trades"].eq(0).all()
        for row in table.to_dict("records"):
            funding = 0 if pd.isna(row["funding_pnl"]) else row["funding_pnl"]
            additional = row.get("bankruptcy_adjustment", 0) - row.get("liquidation_fees", 0)
            assert row["gross_price_pnl"] - row[
                "total_modeled_costs"
            ] + funding + additional == pytest.approx(row["realized_net_pnl"])
        if name.startswith("funding"):
            assert table.market_mode.eq("perpetual").all()
            assert table.funding_note.str.contains("funding_included_in_PnL").all()
            assert table.funding_events.sum() > 0
            for value in table.conditional_results:
                assert set(json.loads(value)) == {
                    "negative_positive",
                    "negative_negative",
                    "positive_negative",
                    "positive_positive",
                }
        before = (source / "metrics.csv").read_bytes()
        recovered = run(path, exp, root, resume=source.name, check_only=True)
        assert recovered["verified_reusable"] == 24 and recovered["pending_backtests"] == 0
        publication = publish(root, source.name)
        compact = pd.read_csv(Path(publication["publication_directory"]) / "metrics_compact.csv")
        assert len(compact) == 24 and {"cagr_pct", "sortino", "long_contribution"} <= set(compact)
        assert (source / "metrics.csv").read_bytes() == before
    comparison = compare(root, NAMES)
    table = pd.read_csv(comparison / "comparison.csv")
    assert {"symbol", "timeframe"} <= set(table)
    assert len(table) == 120
    assert "comparison.csv" in publish_comparison(root, comparison.name)["published"]


def test_auxiliary_tamper_and_missing_mark_are_fail_closed(tmp_path):
    times = pd.date_range("2020-01-01", periods=72, freq="h", tz="UTC")
    c = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=times
    )
    path, meta = write_aux(tmp_path, c)
    info = {"path": str(path), "manifest": meta}
    aux = load_aux(info)
    assert len(complete_days(aux)) == 3
    aux["mark"] = aux["mark"].drop(times[30])
    assert len(complete_days(aux)) == 2
    with (path / "funding.parquet").open("ab") as file:
        file.write(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        load_aux(info)
