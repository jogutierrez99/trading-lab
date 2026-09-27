"""Exercise immutable reporting with a synthetic matrix before any market backtest."""

import json
from itertools import product

import pandas as pd

from quant_lab.batch_006 import persist
from quant_lab.batch_006_analysis import excursions, metrics, regimes_by_side
from quant_lab.batch_006_reporting import finalize
from quant_lab.config import CostsConfig, RiskConfig
from quant_lab.experiments import ExperimentStore
from quant_lab.perpetual_execution import run_perpetual


def test_synthetic_full_matrix_reporting_and_test_only_wf(tmp_path):
    index = pd.date_range("2020-01-01", periods=96, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=index
    )
    decisions = pd.DataFrame(
        {"le": False, "lx": False, "se": False, "sx": False, "distance": 10.0}, index=index
    )
    decisions.loc[index[1], "le"] = True
    decisions.loc[index[5], "lx"] = True
    decisions.loc[index[30], "se"] = True
    decisions.loc[index[40], "sx"] = True
    frame.loc[index[5], "open"] = 99.0
    frame.loc[index[40], "open"] = 100.5
    fund = pd.DataFrame({"rate": [0.001, 0.001]}, index=index[[2, 31]])
    labels = pd.DataFrame({"trend": "SIDEWAYS", "volatility_regime": "NORMAL_VOL"}, index=index)
    store = ExperimentStore(tmp_path, {"synthetic": True}, {"synthetic": True})
    for name in ("trades", "equity", "charts"):
        (store.path / name).mkdir()
    rows = []
    for mode, direction in (
        ("LONG_ONLY", "long"),
        ("SHORT_ONLY", "short"),
        ("LONG_SHORT", "combined"),
    ):
        result, sides, events = run_perpetual(
            frame,
            frame,
            fund,
            decisions,
            index[0],
            index[-1] + pd.Timedelta(hours=1),
            CostsConfig(),
            RiskConfig(take_profit_enabled=False),
            direction=direction,
        )
        quality, edge = excursions(frame, result, "1h")
        values = metrics(result, sides, quality)
        regimes = regimes_by_side(result, labels)
        for asset, tf, variant in product(
            ("BTCUSDT", "ETHUSDT"), ("1h", "4h", "1d"), ("A", "B", "C")
        ):
            for partition, scenario in product(
                (
                    "train",
                    "validation",
                    "test",
                    "final_holdout",
                    "full",
                    "wf_00_train",
                    "wf_00_test",
                ),
                ("zero", "base", "adverse"),
            ):
                meta = {
                    "asset": asset,
                    "timeframe": tf,
                    "variant": variant,
                    "mode": mode,
                    "partition": partition,
                    "costs": scenario,
                    "kind": "strategy",
                }
                id_ = store.start(meta)
                vals = values | ({"return_pct": 999.0} if partition == "wf_00_train" else {})
                persist(
                    store,
                    id_,
                    result,
                    sides,
                    {
                        "metadata": meta,
                        "metrics": vals,
                        "trades": [],
                        "entry_quality": quality,
                        "time_to_edge": edge,
                        "regimes": regimes,
                        "funding_events": events,
                    },
                )
                rows.append(meta | vals | {"experiment_id": id_})
    finalize(store, rows)
    comparison = pd.read_csv(store.path / "direction_comparison.csv")
    assert len(comparison) == 54
    assert (comparison.return_pct < 0).all()
    assert comparison.classification.str.contains("FAILED_TEMPORAL_VALIDATION").all()
    wf = json.loads((store.path / "walk_forward.json").read_text())
    assert {r["role"] for r in wf["windows"]} == {"train", "test"}
    assert all(w["positive_fold_ratio"] == 0 for w in wf["test_summary"])
    assert (store.path / "charts" / "long_short_equity_comparison.png").exists()
    assert len(list((store.path / "charts").glob("*.png"))) >= 30
    assert "20. " in (store.path / "summary.md").read_text()
