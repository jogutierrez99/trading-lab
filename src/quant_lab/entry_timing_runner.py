"""Sequential paired study, gated by complete numerical baseline reproduction."""

import argparse
import os
import shutil
from contextlib import ExitStack
from dataclasses import asdict, fields
from pathlib import Path

from quant_lab.batch_006 import persist, unlock_holdout
from quant_lab.entry_timing_execution import CASES, prepare_case, run_case
from quant_lab.entry_timing_protocol import (
    DEFAULT_CONFIG,
    compare_baseline,
    context,
    load_protocol,
    measure,
)
from quant_lab.entry_timing_reporting import CRITERIA, finish
from quant_lab.execution_policies.timing_15m import Opportunity, timing_metrics
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.mtf_execution import settings
from quant_lab.mtf_series import inventory, verify
from quant_lab.new_mtf_runner import seal, verify_artifacts
from quant_lab.perpetual_execution import PerpetualTrade
from quant_lab.refinement_batch import CsvSink


def baseline_smoke(data, windows, child, references):
    """Three historical FULL/BASE replays only; no experimental executions."""
    partition, start, end = next(w for w in windows if w[0] == "full")
    reproduced = []
    for case in CASES:
        print("REPLAY", case, partition, "base", flush=True)
        prepared = prepare_case(data[case[0]], *case)
        result, sides, events, _records, _lifecycle = run_case(
            prepared, case, "baseline", start, end, settings().costs["base"], True
        )
        values, _ = measure(result, sides, start, end, "baseline", True)
        reproduced.append(
            compare_baseline(
                child, references[(*case, partition, "base")], result, sides, values, events
            )
        )
    return reproduced


def run(repo, config=DEFAULT_CONFIG):
    # Import here to keep preflight's minimal replay independent of runner admission.
    from quant_lab.entry_timing_preflight import require_preflight

    code = provenance(repo)
    protocol = load_protocol(repo, config)
    receipt = require_preflight(repo, code, protocol)
    print("VERIFY datasets, source artifacts and frozen protocol", flush=True)
    data, early, late, boundary, reference, child, references = context(repo, protocol, code)
    plan = {
        "name": "entry_timing_15m",
        "config": protocol.model_dump(mode="json"),
        "code_sha256": code["code_sha256"],
        "preflight": receipt,
        "windows": [(n, str(a), str(b)) for n, a, b in early + late],
        "used_data": inventory(data),
        "criteria": CRITERIA,
        **{k: reference[k] for k in ("splits", "folds", "settings", "matched_audit")},
        "expected_executions": 1008,
        "baseline_executions_before_timing": 504,
        "source_batch": str(child.relative_to(repo)),
    }
    parent = ExperimentStore(repo / "results/entry_timing_15m", plan, code)
    write_json(parent.path / "config.json", protocol.model_dump(mode="json"))
    for name in code["files"]:
        target = parent.path / "source_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, target)
    shutil.copyfile(repo / "docs/entry-timing-15m.md", parent.path / "protocol.md")
    print("RUN", parent.path, flush=True)
    rows, replay, baseline_entries = [], [], {}
    children = []
    try:
        prepared = {case: prepare_case(data[case[0]], *case) for case in CASES}
        with ExitStack() as stack:
            meta_columns = [
                "asset",
                "family",
                "architecture",
                "variant",
                "partition",
                "costs",
                "start",
                "end",
                "experiment_id",
            ]

            def sink(name, columns):
                value = CsvSink(
                    parent.path / (name + ".csv"), list(dict.fromkeys(meta_columns + columns))
                )
                stack.callback(value.close)
                return value

            signal_sink = sink(
                "signals",
                [f.name for f in fields(Opportunity)]
                + [
                    "status",
                    "entry_time",
                    "entry_price",
                    "bars_waited_15m",
                    "minutes_waited",
                    "distance_from_signal_atr",
                    "reason",
                ],
            )
            lifecycle_sink = sink("signal_lifecycle", ["signal_id", "time", "status", "reason"])
            trade_sink = sink("trades", ["signal_id"] + [f.name for f in fields(PerpetualTrade)])
            for variant in ("baseline", "timing"):
                if variant == "timing":
                    if len(replay) != 504 or any(r["status"] != "reproduced" for r in replay):
                        raise ValueError(
                            "ABORT: complete baseline reproduction required before timing"
                        )
                    if provenance(repo)["code_sha256"] != code["code_sha256"]:
                        raise ValueError("Code changed during baseline reproduction")
                    write_json(parent.path / "baseline_reproduction.json", replay)
                store = ExperimentStore(parent.path / variant, plan | {"variant": variant}, code)
                children.append(store.path)
                for name in ("equity", "trades"):
                    (store.path / name).mkdir()
                for stage, windows in (("early", early), ("late", late)):
                    if stage == "late":
                        unlock_holdout(store, len(early) * 9, boundary, code["code_sha256"])
                    for partition, start, end in windows:
                        for case in CASES:
                            for scenario, costs in settings().costs.items():
                                meta = dict(
                                    zip(("asset", "family", "architecture"), case, strict=True)
                                ) | {
                                    "variant": variant,
                                    "partition": partition,
                                    "costs": scenario,
                                    "start": str(start),
                                    "end": str(end),
                                }
                                identifier = store.start(meta)
                                try:
                                    result, sides, events, records, lifecycle = run_case(
                                        prepared[case],
                                        case,
                                        variant,
                                        start,
                                        end,
                                        costs,
                                        scenario != "zero",
                                    )
                                    values, extra = measure(
                                        result, sides, start, end, variant, scenario != "zero"
                                    )
                                    key = (*case, partition, scenario)
                                    if variant == "baseline":
                                        replay.append(
                                            compare_baseline(
                                                child,
                                                references[key],
                                                result,
                                                sides,
                                                values,
                                                events,
                                            )
                                        )
                                        baseline_entries[key] = {
                                            r["signal_id"]: r["entry_price"]
                                            for r in records
                                            if r["status"] == "CONSUMED"
                                        }
                                    stats = timing_metrics(
                                        records,
                                        baseline_entries[key] if variant == "timing" else None,
                                    )
                                    baseline_count = len(baseline_entries[key])
                                    stats["trade_retention_rate"] = (
                                        len(result.trades) / baseline_count
                                        if baseline_count
                                        else None
                                    )
                                    stats["sample_warning"] = (
                                        stats["trade_retention_rate"] is not None
                                        and stats["trade_retention_rate"] < 0.30
                                    )
                                    trades = [asdict(t) for t in result.trades]
                                    persist(
                                        store,
                                        identifier,
                                        result,
                                        sides,
                                        {
                                            "metadata": meta,
                                            "metrics": values | extra,
                                            "timing_metrics": stats,
                                            "trades": trades,
                                            "funding_events": events,
                                            "rejections": [asdict(r) for r in result.rejections],
                                        },
                                    )
                                    link = {
                                        r["entry_time"]: r["signal_id"]
                                        for r in records
                                        if r["status"] == "CONSUMED"
                                    }
                                    trace = meta | {"experiment_id": identifier}
                                    signal_sink.write(trace | r for r in records)
                                    lifecycle_sink.write(trace | r for r in lifecycle)
                                    trade_sink.write(
                                        trace | t | {"signal_id": link[t["entry_time"]]}
                                        for t in trades
                                    )
                                    rows.append(trace | values | extra | stats)
                                except Exception as exc:
                                    with store.connect() as db:
                                        status = db.execute(
                                            "SELECT status FROM experiments WHERE id=?",
                                            (identifier,),
                                        ).fetchone()[0]
                                    if status == "started":
                                        store.finish(identifier, {"error": str(exc)}, "failed")
                                    raise
                        print(
                            variant.upper(), partition, "completed", len(rows), "/ 1008", flush=True
                        )
                verify(store, 504)
        if provenance(repo)["code_sha256"] != code["code_sha256"]:
            raise ValueError("Code changed during experiment")
        verify_artifacts(repo / protocol.source_run)
        finish(parent.path, rows, plan, replay)
        write_json(
            parent.path / "verification.json",
            {
                "status": "completed",
                "executions": len(rows),
                "baselines_reproduced": len(replay),
                "children_verified": [str(p.relative_to(parent.path)) for p in children],
                "code_unchanged": True,
                "source_artifacts_unchanged": True,
            },
        )
        seal(parent.path)
    except Exception as exc:
        write_json(
            parent.path / "failure.json",
            {
                "status": "failed",
                "error": str(exc),
                "completed_executions": len(rows),
                "reproduced_baselines": len(replay),
            },
        )
        raise
    print("COMPLETE", parent.path, flush=True)
    return parent.path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    os.chdir(repo)
    try:
        run(repo, args.config)
        return 0
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
