"""Exercise report, immutable hash replay and lifecycle outputs before historical runs."""

import hashlib
from dataclasses import asdict

import pandas as pd

from quant_lab.batch_006 import persist
from quant_lab.batch_006_analysis import metrics
from quant_lab.config import CostsConfig, RiskConfig
from quant_lab.experiments import ExperimentStore
from quant_lab.mtf_clock import execute
from quant_lab.refinement_batch import CsvSink
from quant_lab.refinement_reporting import finish


def test_immutable_hash_replay_and_reporting(tmp_path):
    idx = pd.date_range("2020-01-01", periods=80, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx
    )
    d = pd.DataFrame(
        {"le": False, "se": False, "lx": False, "sx": False, "distance": 5.0}, index=idx
    )
    d.loc[idx[1], "le"] = True
    funding = pd.DataFrame({"rate": []}, index=pd.DatetimeIndex([], tz="UTC"))
    store = ExperimentStore(tmp_path, {}, {})
    (store.path / "trades").mkdir()
    (store.path / "equity").mkdir()
    digests = []
    values = None
    for _ in range(2):
        result, sides, events = execute(
            frame,
            frame,
            funding,
            d,
            idx[0],
            idx[-1] + pd.Timedelta(hours=1),
            CostsConfig(),
            RiskConfig(max_holding_bars=72, take_profit_enabled=False),
        )
        id_ = store.start({})
        doc = {"trades": [asdict(t) for t in result.trades]}
        persist(store, id_, result, sides, doc)
        digests.append((doc["equity_sha256"], doc["trades_sha256"]))
        assert (
            hashlib.sha256((store.path / "trades" / (id_ + ".json")).read_bytes()).hexdigest()
            == doc["trades_sha256"]
        )
        values = metrics(
            result, sides, {"summary": {s: {"mfe_mae_ratio": None} for s in ("long", "short")}}
        )
    assert digests[0] == digests[1]
    rows = []
    stats = {
        "signals_generated": 2,
        "signals_executed": 1,
        "signals_expired": 1,
        "signals_invalidated": 0,
        "signals_consumed": 1,
        "duplicate_entries_prevented": 0,
        "cooldown_entries_blocked": 0,
        "extension_entries_blocked": 0,
        "average_time_to_entry": 0.0,
        "trades_per_signal": 0.5,
    }
    for version in ("V2", "V2.1"):
        for partition in (
            "train",
            "validation",
            "test",
            "final_holdout",
            "full",
            "wf_00_test",
            "segment_00",
        ):
            for scenario in ("zero", "base", "adverse"):
                rows.append(
                    values
                    | stats
                    | {
                        "asset": "BTCUSDT",
                        "family": "donchian",
                        "architecture": version,
                        "mode": "LONG_ONLY",
                        "cohort": "matched",
                        "partition": partition,
                        "costs": scenario,
                        "total_costs": values["total_execution_costs"] + values["funding_cost"],
                        "time_in_market_pct": 10.0,
                    }
                )
    _full, pairs, candidates = finish(store.path, rows)
    assert pairs[0]["delta_return"] == 0
    assert candidates[0]["operational_label"] == "ARCHIVE_NO_PAPER"
    assert (store.path / "holdout.csv").exists()
    sink = CsvSink(store.path / "signal_lifecycle.csv", ["signal_id", "action"])
    sink.write([{"signal_id": "id", "action": "ENTER"}])
    sink.close()
    assert pd.read_csv(store.path / "signal_lifecycle.csv").action.iloc[0] == "ENTER"
