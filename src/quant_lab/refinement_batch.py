"""Small fixed eight-configuration confirmation on the unchanged MTF03 cohort."""

import csv
import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from quant_lab.batch_006 import CLASSIFICATION, persist, unlock_holdout
from quant_lab.batch_006_analysis import metrics
from quant_lab.cross_market_study import clean_json
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.mtf_data import load_frozen, load_quarters
from quant_lab.mtf_execution import settings
from quant_lab.mtf_series import inventory, schedule, verify
from quant_lab.refinement_execution import CASES, prepare_case, run_case
from quant_lab.refinement_policy import guards
from quant_lab.refinement_reporting import PAPER_RULES, finish

NAME = "batch_execution_refinement"
REFERENCE = Path("results/batch_mtf_03_architectures/20260926T231820Z-44cc4dedd4ab")


def protect(repo):
    record = json.loads(
        (repo / "reports" / NAME / "protected_previous.json").read_text(encoding="utf-8")
    )

    def check(item):
        name, sha = item
        p = repo / name
        return name if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != sha else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        changed = [p for p in pool.map(check, record.items()) if p]
    if changed:
        raise ValueError(f"Historical artifacts changed: {changed[:10]}")
    return {"files": len(record), "unchanged": True}


class CsvSink:
    def __init__(self, path, columns):
        self.handle = path.open("x", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.handle, fieldnames=columns)
        self.writer.writeheader()

    def write(self, rows):
        self.writer.writerows(rows)

    def close(self):
        self.handle.close()


def run(repo):
    protected = protect(repo)
    code = provenance(repo)
    preflight = json.loads((repo / "reports" / NAME / "preflight.json").read_text(encoding="utf-8"))
    if preflight["code_sha256"] != code["code_sha256"] or any(
        v["exit_code"] for v in preflight["checks"].values()
    ):
        raise ValueError("Preflight failed or stale")
    previous = json.loads((REFERENCE / "plan.json").read_text(encoding="utf-8"))
    data, _ = load_frozen()
    audit = load_quarters(data, matched=True)
    if (
        audit["excluded_days"] != previous["matched_audit"]["excluded_days"]
        or inventory(data) != previous["used_data"]
    ):
        raise ValueError("Cohort differs from frozen MTF03")
    early, late, boundary = schedule(data, previous)
    if [(n, str(a), str(b)) for n, a, b in early + late] != [tuple(w) for w in previous["windows"]]:
        raise ValueError("Temporal windows changed")
    prepared = {c: prepare_case(data[c[0]], *c) for c in CASES}
    configs = [
        {
            "asset": a,
            "family": f,
            "architecture": v,
            "baseline": base,
            "mode": "LONG_ONLY",
            "cohort": "matched",
            "signal_config": prepared[(a, f, base)][0].model_dump(mode="json"),
            "execution_guards": guards().model_dump() if v.endswith(".1") else None,
        }
        for a, f, base in CASES
        for v in (base, base + ".1")
    ]
    plan = {
        "name": NAME,
        "reference": str(REFERENCE),
        "matrix": configs,
        "settings": settings().model_dump(mode="json"),
        "used_data": inventory(data),
        "excluded_days": audit["excluded_days"],
        "splits": previous["splits"],
        "folds": previous["folds"],
        "windows": previous["windows"],
        "historical_classification": CLASSIFICATION,
        "paper_rules": PAPER_RULES,
        "preflight": preflight,
        "protected": protected,
        "selection": "Four user-requested pairs only; observed-history confirmation, no tuning.",
    }
    store = ExperimentStore(repo / "results" / NAME, plan, code)
    print("RUN", store.path, flush=True)
    write_json(store.path / "config.json", configs)
    for folder in ("equity", "trades", "source_snapshot"):
        (store.path / folder).mkdir()
    for name in code["files"]:
        target = store.path / "source_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, target)
    shutil.copyfile(repo / "docs/execution-refinement-design.md", store.path / "protocol.md")
    reference = pd.read_csv(REFERENCE / "results.csv").set_index(
        ["asset", "family", "architecture", "partition", "costs"]
    )
    metadata = ["experiment_id", "asset", "family", "architecture", "partition", "costs"]
    signals_columns = [
        "signal_id",
        "direction",
        "signal_timestamp",
        "signal_price",
        "signal_reference_level",
        "regime_state",
        "expiry_timestamp",
        "atr",
        "status",
        "consumed",
        "invalidated",
        "expiry_reason",
        "entry_time",
        "signal_age",
        "time_to_entry",
        "entry_distance_atr",
    ]
    from dataclasses import fields

    from quant_lab.perpetual_execution import PerpetualTrade

    sinks = {
        "signals": CsvSink(store.path / "signals.csv", metadata + signals_columns),
        "lifecycle": CsvSink(
            store.path / "signal_lifecycle.csv",
            metadata + ["time", "signal_id", "action", "reason", "distance_atr", "entry_price"],
        ),
        "trades": CsvSink(
            store.path / "trades.csv",
            metadata
            + [f.name for f in fields(PerpetualTrade)]
            + ["signal_id", "origin_signal_timestamp"],
        ),
        "equity": CsvSink(
            store.path / "equity.csv", metadata + ["time", "equity", "exposure", "side"]
        ),
    }
    rows = []
    replays = 0
    inherited = settings()
    try:
        for phase, windows in (("early", early), ("late", late)):
            if phase == "late":
                unlock_holdout(store, len(early) * 8 * 3, boundary, code["code_sha256"])
            for partition, start, end in windows:
                for c in configs:
                    for scenario, costs in inherited.costs.items():
                        meta = {
                            k: c[k] for k in ("asset", "family", "architecture", "mode", "cohort")
                        } | {
                            "partition": partition,
                            "costs": scenario,
                            "start": str(start),
                            "end": str(end),
                        }
                        id_ = store.start(meta)
                        try:
                            key = (c["asset"], c["family"], c["baseline"])
                            result, sides, events, stats, signals, lifecycle = run_case(
                                prepared[key],
                                c["asset"],
                                c["family"],
                                c["architecture"],
                                start,
                                end,
                                costs,
                                scenario != "zero",
                            )
                            values = metrics(
                                result,
                                sides,
                                {
                                    "summary": {
                                        s: {"mfe_mae_ratio": None} for s in ("long", "short")
                                    }
                                },
                                scenario != "zero",
                            )
                            for side in ("long", "short"):
                                values.pop(side + "_mfe_mae")
                            tf = prepared[key][0].market.timeframe
                            values["average_holding_hours"] = (
                                values["average_holding_bars"] * (0.25 if tf == "15m" else 1)
                                if values["average_holding_bars"] is not None
                                else None
                            )
                            values.update(
                                total_costs=values["total_execution_costs"]
                                + values["funding_cost"],
                                average_trade=values["expectancy"],
                                time_in_market_pct=float((sides.iloc[1:] != 0).mean() * 100),
                            )
                            trades = [asdict(t) for t in result.trades]
                            document = {
                                "metadata": meta,
                                "metrics": values,
                                "execution_metrics": stats,
                                "trades": trades,
                                "funding_events": events,
                                "rejections": [asdict(r) for r in result.rejections],
                            }
                            persist(store, id_, result, sides, document)
                            if not c["architecture"].endswith(".1"):
                                ref_id = reference.loc[
                                    (
                                        c["asset"],
                                        c["family"],
                                        c["architecture"],
                                        partition,
                                        scenario,
                                    ),
                                    "experiment_id",
                                ]
                                ref = json.loads(
                                    (REFERENCE / ref_id / "result.json").read_text(encoding="utf-8")
                                )
                                if any(
                                    document[k + "_sha256"] != ref[k + "_sha256"]
                                    for k in ("equity", "trades")
                                ):
                                    raise ValueError("Baseline does not exactly reproduce MTF03")
                                replays += 1
                            context = {k: meta[k] for k in metadata if k != "experiment_id"} | {
                                "experiment_id": id_
                            }
                            sinks["signals"].write(context | s for s in signals)
                            sinks["lifecycle"].write(context | e for e in lifecycle)
                            linked = {s["entry_time"]: s for s in signals if s["consumed"]}
                            sinks["trades"].write(
                                context
                                | t
                                | {
                                    "signal_id": linked[t["entry_time"]]["signal_id"],
                                    "origin_signal_timestamp": linked[t["entry_time"]][
                                        "signal_timestamp"
                                    ],
                                }
                                for t in trades
                            )
                            equity = pd.DataFrame(
                                {
                                    "time": result.equity.index,
                                    "equity": result.equity.to_numpy(),
                                    "exposure": result.exposure.to_numpy(),
                                    "side": sides.to_numpy(),
                                }
                            )
                            for column, value in context.items():
                                equity[column] = value
                            equity[metadata + ["time", "equity", "exposure", "side"]].to_csv(
                                sinks["equity"].handle, index=False, header=False
                            )
                            rows.append(meta | values | stats | {"experiment_id": id_})
                        except Exception as exc:
                            with store.connect() as db:
                                status = db.execute(
                                    "SELECT status FROM experiments WHERE id=?", (id_,)
                                ).fetchone()[0]
                            if status == "started":
                                store.finish(id_, {"error": str(exc)}, "failed")
                            write_json(
                                store.path / "failure.json",
                                {"experiment_id": id_, "error": str(exc)},
                            )
                            raise
                print("DONE", partition, len(rows), "baseline_replays", replays, flush=True)
    finally:
        for sink in sinks.values():
            sink.close()
    verify(store, 8 * 3 * (len(early) + len(late)))
    if replays != 4 * 3 * (len(early) + len(late)):
        raise ValueError("Missing baseline replay")
    finish(store.path, rows)
    if code["code_sha256"] != provenance(repo)["code_sha256"]:
        raise ValueError("Code changed during run")
    write_json(
        store.path / "final_verification.json",
        clean_json(
            {
                "status": "completed",
                "runs": len(rows),
                "exact_baseline_replays": replays,
                "protected": protect(repo),
                "code_unchanged": True,
                "preflight": preflight,
            }
        ),
    )
    files = sorted(p for p in store.path.rglob("*") if p.is_file())

    def fingerprint(p):
        with p.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        return str(p.relative_to(store.path)), digest

    with ThreadPoolExecutor(max_workers=8) as pool:
        manifest = dict(pool.map(fingerprint, files))
    write_json(store.path / "artifact_manifest.json", manifest)
    print("COMPLETE", store.path, flush=True)
    return store.path
