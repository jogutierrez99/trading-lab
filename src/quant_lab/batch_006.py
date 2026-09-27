"Frozen Bollinger long/short research matrix with perpetual funding and margin."

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from quant_lab.backtest import BacktestResult
from quant_lab.batch import COSTS
from quant_lab.batch_006_analysis import excursions, metrics, regimes_by_side, signal_follow_through
from quant_lab.batch_006_execution import (
    MODES,
    configuration,
    execute_window,
    prepare_market,
    walk_forward_windows,
)
from quant_lab.cross_market_study import clean_json
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.futures_data import ROOT, load_audited
from quant_lab.perpetual_execution import FuturesAssumptions
from quant_lab.study_data import HOURS, audit
from quant_lab.study_plan import windows

NAME = "batch_006_bollinger_long_short"
CLASSIFICATION = {
    "DIAGNOSTIC_ONLY": (
        "Always; newly simulated perpetual instrument but underlying "
        "market history already observed."
    ),
    "MARGIN_MODEL_ASSUMED": (
        "Always; fixed maintenance/clearance assumptions, not exchange-"
        "perfect liquidation reconstruction."
    ),
    "INSUFFICIENT_DATA": "Full/base<30 trades or holdout/base<30 trades.",
    "FAILED_AFTER_COSTS": "Full/zero>0 and full/base<=0.",
    "COST_SENSITIVE": "Full/base>0 and full/adverse<=0.",
    "FAILED_TEMPORAL_VALIDATION": "Any validation/test/holdout base return<=0.",
    "PROMISING_BUT_UNCONFIRMED": (
        "Full/base>0 PF>1 Sharpe>0, each validation/test/holdout base>0 "
        "and>=30 holdout trades,>=50% WF test/base folds positive."
    ),
}


def protect(repo):
    record = json.loads((repo / "reports" / NAME / "protected_previous.json").read_text())
    changed = [
        p
        for p, h in record.items()
        if not (repo / p).exists() or hashlib.sha256((repo / p).read_bytes()).hexdigest() != h
    ]
    if changed:
        raise ValueError(f"Previous artifacts changed: {changed[:10]}")
    return {"files": len(record), "unchanged": True}


def load_common():
    data, quality = load_audited(ROOT)
    common = None
    for item in data.values():
        days = item["frames"]["1h"].index.floor("D").unique()
        common = days if common is None else common.intersection(days)
    for item in data.values():
        item["frames"] = {
            tf: f.loc[f.index.floor("D").isin(common)] for tf, f in item["frames"].items()
        }
        item["mark"] = item["mark"].loc[item["mark"].index.floor("D").isin(common)]
        item["funding"] = item["funding"].loc[item["funding"].index.floor("D").isin(common)]
    return data, quality


def unlock_holdout(store, expected, boundary, code_sha256):
    """Unlock only after all planned earlier executions are successfully recorded."""
    with store.connect() as db:
        records = db.execute("SELECT status,metadata FROM experiments").fetchall()
    if len(records) != expected or any(
        status != "completed" or pd.Timestamp(json.loads(meta)["end"]) > boundary
        for status, meta in records
    ):
        raise ValueError("Holdout remains locked: earlier matrix incomplete or invalid")
    write_json(
        store.path / "holdout_unlock.json",
        {
            "completed_prior_runs": expected,
            "code_sha256": code_sha256,
            "rule": "All pre-holdout frozen tests complete; no selection.",
        },
    )


def run(repo: Path):
    protected = protect(repo)
    data, audits = load_common()
    start = data["BTCUSDT"]["frames"]["1h"].index[0]
    end = data["BTCUSDT"]["frames"]["1h"].index[-1] + pd.Timedelta(hours=1)
    splits = windows(start, end)
    folds = walk_forward_windows(start, end)
    configs = [
        {
            "asset": asset,
            "timeframe": tf,
            "variant": v,
            "mode": mode,
            "config": configuration(asset, tf, v, mode).model_dump(mode="json"),
        }
        for asset in data
        for tf in HOURS
        for v in ("A", "B", "C")
        for mode in MODES
    ]
    code = provenance(repo)
    preflight = json.loads((repo / "reports" / NAME / "preflight.json").read_text())
    if preflight["code_sha256"] != code["code_sha256"] or any(
        preflight[c]["exit_code"]
        for c in ("pytest -q", "ruff check .", "ruff format --check .", "pip check")
    ):
        raise ValueError("Mandatory preflight failed or stale")
    plan = {
        "name": NAME,
        "matrix": configs,
        "dataset_audit": audits,
        "used_data": [
            audit(f, asset + "_USD_M_PERPETUAL", tf)
            for asset, item in data.items()
            for tf, f in item["frames"].items()
        ],
        "costs": {k: v.model_dump() for k, v in COSTS.items()},
        "funding": (
            "Actual public funding rates. ZERO disables execution costs and "
            "funding; BASE/ADVERSE apply the SAME historical funding rates. No"
            " multiplier/stress invented for funding."
        ),
        "execution": asdict(FuturesAssumptions()),
        "execution_clock": (
            "1h underlying contract+mark bars for ALL strategy TFs; hourly "
            "stops/liquidation/funding. Signals only after full strategy-"
            "candle closes; next open, never stale repeated entries."
        ),
        "funding_order": (
            "Exact-boundary funding charged to position held immediately "
            "before boundary, then opening exits/entries. Source delays<1s "
            "retained and charged after opening actions, before intrabar "
            "fills; mark-open quote proxy. Larger offsets rejected."
        ),
        "margin": (
            "Isolated1x; initial margin=entry notional. Funding adjusts "
            "isolated margin. Maintenance=0.5% current marked notional; "
            "liquidation fee0.5%. Open mark breach precedes stops; ambiguous "
            "intrabar breach precedes stop and fills adverse hourly contract "
            "extreme. Bankruptcy adjustment caps losses at allocated isolated "
            "margin; insurance/ADL history unavailable."
        ),
        "translations": (
            "BB20 population std, RSI14 Wilder, ADX14 Wilder, ATR14 arithmetic"
            " TR, EMA200 recursive: intentional bars. Stop72elapsed "
            "hours=72/18/3 strategy bars. Regime quantiles previous30days; "
            "EMA50/200 bars. No parameter scaling beyond elapsed time."
        ),
        "splits": [(n, str(a), str(b)) for n, a, b in splits],
        "folds": [tuple(map(str, f)) for f in folds],
        "chronology": (
            "ALL train/validation/test and WF tests ending before holdout "
            "first. Then unlock final holdout; full and WF windows touching "
            "holdout follow. No selection or optimization."
        ),
        "classification": CLASSIFICATION,
        "selection": "None: all54 configurations retained.",
        "capital": (
            "10000USDT independent per run; max initial risk0.5%, initial "
            "notional+entry fee<=25%; no hedge/pyramiding/reversal. Segments "
            "liquidate before gaps and reset features; cash alone carries "
            "across gaps within a run."
        ),
        "benchmark": (
            "Per asset FULL: perpetual long buy&hold25/100%, same "
            "funding/cost/margin engine, no stop; enters second hourly open of"
            " each continuous segment. CASH zero. No short benchmark."
        ),
        "analysis": (
            "Daily UTC marked equity returns; sqrt365, risk-free0. Direction "
            "contributions /initial equity. Incremental short=combined net "
            "return minus LONG_ONLY net return; includes opportunity and "
            "sizing effects, not just short PnL. WF aggregates TEST returns "
            "only; training logged separately. All regimes attributed at "
            "signal close, not future path."
        ),
        "interpretation": (
            "NEW_INSTRUMENT_REUSED_MARKET_HISTORY; temporal partitions are "
            "diagnostics, not pristine unseen markets. Funding rates observed "
            "but mark notionals hourly proxies and margin historical tiers "
            "unavailable."
        ),
        "protected": protected,
        "preflight": preflight,
    }
    store = ExperimentStore(repo / "results" / NAME, plan, code)
    print("RUN", store.path, flush=True)
    for folder in ("trades", "equity", "charts"):
        (store.path / folder).mkdir()
    write_json(store.path / "dataset_audit.json", audits)
    pd.DataFrame(plan["used_data"]).to_csv(store.path / "dataset_inventory.csv", index=False)
    prepared = {}
    for c in configs:
        key = (c["asset"], c["timeframe"], c["variant"], c["mode"])
        prepared[key] = prepare_market(data[c["asset"]], *key)
    holdout = splits[-1][1]
    early = splits[:3]
    late = [splits[-1], ("full", start, end)]
    for i, (a, b, c) in enumerate(folds):
        target = early if c <= holdout else late
        target.extend([(f"wf_{i:02}_train", a, b), (f"wf_{i:02}_test", b, c)])
    rows = []
    for phase, window_list in (("pre_holdout", early), ("post_unlock", late)):
        if phase == "post_unlock":
            unlock_holdout(
                store, len(early) * len(configs) * len(COSTS), holdout, code["code_sha256"]
            )
        for partition, left, right in window_list:
            for c in configs:
                key = (c["asset"], c["timeframe"], c["variant"], c["mode"])
                signal_edge = signal_follow_through(prepared[key], left, right, c["timeframe"])
                for scenario, costs in COSTS.items():
                    meta = {k: c[k] for k in ("asset", "timeframe", "variant", "mode")} | {
                        "partition": partition,
                        "costs": scenario,
                        "start": str(left),
                        "end": str(right),
                        "kind": "strategy",
                    }
                    id_ = store.start(meta)
                    try:
                        result, sides, events, labels = execute_window(
                            prepared[key],
                            c["timeframe"],
                            c["variant"],
                            c["mode"],
                            left,
                            right,
                            costs,
                            scenario != "zero",
                        )
                        frame = data[c["asset"]]["frames"]["1h"].loc[
                            left : right - pd.Timedelta(hours=1)
                        ]
                        quality, edge = excursions(frame, result, c["timeframe"])
                        edge["all_signals"] = signal_edge
                        values = metrics(result, sides, quality, scenario != "zero")
                        regimes = regimes_by_side(result, labels)
                        document = {
                            "metadata": meta,
                            "metrics": values,
                            "trades": [asdict(t) for t in result.trades],
                            "funding_events": events,
                            "rejections": [asdict(r) for r in result.rejections],
                            "entry_quality": quality,
                            "time_to_edge": edge,
                            "regimes": regimes,
                        }
                        persist(store, id_, result, sides, document)
                        rows.append(meta | values | {"experiment_id": id_})
                    except Exception as exc:
                        store.finish(id_, {"error": str(exc)}, "failed")
                        raise
            print(f"DONE {partition}: {len(rows)}", flush=True)
    for asset in data:
        blocks = prepared[(asset, "1h", "A", "LONG_ONLY")]
        for size in (25, 100):
            for scenario, costs in COSTS.items():
                meta = {
                    "asset": asset,
                    "timeframe": "1h",
                    "variant": f"BUY_HOLD_{size}",
                    "mode": "LONG_ONLY",
                    "kind": "benchmark",
                    "partition": "full",
                    "costs": scenario,
                    "start": str(start),
                    "end": str(end),
                }
                id_ = store.start(meta)
                result, sides, events, _ = execute_window(
                    blocks, "1h", "A", "LONG_ONLY", start, end, costs, scenario != "zero", size
                )
                q, e = excursions(data[asset]["frames"]["1h"], result, "1h")
                values = metrics(result, sides, q, scenario != "zero")
                persist(
                    store,
                    id_,
                    result,
                    sides,
                    {
                        "metadata": meta,
                        "metrics": values,
                        "trades": [asdict(t) for t in result.trades],
                        "funding_events": events,
                        "entry_quality": q,
                        "time_to_edge": e,
                        "regimes": {},
                    },
                )
                rows.append(meta | values | {"experiment_id": id_})
        idx = pd.date_range(start, end, freq="h")
        result = BacktestResult(
            (),
            pd.Series(10000.0, index=idx),
            (),
            None,
            "long",
            "cash",
            pd.Series(0.0, index=idx),
            0.0,
        )
        sides = pd.Series(0, index=idx)
        q, e = excursions(data[asset]["frames"]["1h"], result, "1h")
        values = metrics(result, sides, q, False)
        meta = {
            "asset": asset,
            "timeframe": "1h",
            "variant": "CASH",
            "mode": "LONG_ONLY",
            "kind": "benchmark",
            "partition": "full",
            "costs": "zero",
            "start": str(start),
            "end": str(end),
        }
        id_ = store.start(meta)
        persist(
            store,
            id_,
            result,
            sides,
            {
                "metadata": meta,
                "metrics": values,
                "trades": [],
                "entry_quality": q,
                "time_to_edge": e,
                "funding_events": [],
                "regimes": {},
            },
        )
        rows.append(meta | values | {"experiment_id": id_})
    from quant_lab.batch_006_reporting import finalize

    finalize(store, rows)
    if provenance(repo)["code_sha256"] != code["code_sha256"]:
        raise ValueError("Frozen source changed during execution")
    with store.connect() as db:
        for id_, status, sha in db.execute("SELECT id,status,result_sha256 FROM experiments"):
            if (
                status != "completed"
                or hashlib.sha256((store.path / id_ / "result.json").read_bytes()).hexdigest()
                != sha
            ):
                raise ValueError("Ledger integrity failed")
            document = json.loads((store.path / id_ / "result.json").read_text())
            for directory, extension in (("equity", ".parquet"), ("trades", ".json")):
                digest = hashlib.sha256((store.path / directory / (id_ + extension)).read_bytes())
                if digest.hexdigest() != document[directory + "_sha256"]:
                    raise ValueError("Equity/trade artifact integrity failed")
    expected = len(configs) * len(COSTS) * (5 + 2 * len(folds)) + len(data) * (2 * len(COSTS) + 1)
    if len(rows) != expected:
        raise ValueError("Incomplete frozen experiment matrix")
    write_json(
        store.path / "verification.json",
        {
            "status": "completed",
            "executions": len(rows),
            "protected_previous": protect(repo),
            "code_unchanged": True,
            "equity_trade_hashes_verified": True,
            "preflight": preflight,
        },
    )
    write_json(
        store.path / "artifact_manifest.json",
        {
            str(p.relative_to(store.path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(store.path.rglob("*"))
            if p.is_file()
        },
    )
    print("COMPLETE", store.path, flush=True)
    return store.path


def persist(store, id_, result, sides, document):
    equity = store.path / "equity" / (id_ + ".parquet")
    pd.DataFrame({"equity": result.equity, "exposure": result.exposure, "side": sides}).to_parquet(
        equity
    )
    trades = store.path / "trades" / (id_ + ".json")
    write_json(trades, document["trades"])
    document["equity_sha256"] = hashlib.sha256(equity.read_bytes()).hexdigest()
    document["trades_sha256"] = hashlib.sha256(trades.read_bytes()).hexdigest()
    store.finish(id_, clean_json(document))
