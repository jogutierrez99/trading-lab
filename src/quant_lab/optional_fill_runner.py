"""Six frozen pairs: reproduce original baselines before causal fill execution."""

import argparse
import os
import shutil
from contextlib import ExitStack
from dataclasses import asdict, fields
from pathlib import Path

from quant_lab.batch_006 import persist, unlock_holdout
from quant_lab.entry_timing_protocol import compare_baseline, measure
from quant_lab.execution_policies.optional_15m_fill import BaselineEntry, fill_metrics, pair_record
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.mtf_execution import settings
from quant_lab.mtf_series import inventory, verify
from quant_lab.new_mtf_runner import read_json, seal
from quant_lab.optional_fill_execution import (
    baseline_pairs,
    baseline_run,
    entry_stream,
    optimized_run,
    prepare_case,
    restore_entries,
    serialize_entries,
)
from quant_lab.optional_fill_protocol import DEFAULT_CONFIG, context, load_protocol, verify_source
from quant_lab.optional_fill_reporting import CRITERIA, report
from quant_lab.perpetual_execution import PerpetualTrade
from quant_lab.refinement_batch import CsvSink


class PairFailure(ValueError):
    """A failed numerical baseline or execution invariant must exclude its pair."""


def reproduce(child, reference, result, sides, values, events):
    try:
        return compare_baseline(child, reference, result, sides, values, events)
    except ValueError as exc:
        raise PairFailure("BASELINE_REPRODUCTION_FAILED: " + str(exc)) from exc


def run(repo, config=DEFAULT_CONFIG):
    from quant_lab.optional_fill_preflight import require_preflight

    code = provenance(repo)
    protocol = load_protocol(repo, config)
    receipt = require_preflight(repo, code, protocol)
    print("VERIFY frozen sources and matched datasets", flush=True)
    data, early, late, boundary, reference, sources, references = context(repo, protocol)
    scenarios = settings().costs
    count = len(early + late) * len(scenarios)
    plan = {
        "name": "optional_15m_fill",
        "config": protocol.model_dump(mode="json"),
        "code_sha256": code["code_sha256"],
        "preflight": receipt,
        "criteria": CRITERIA,
        "expected_executions": count * len(protocol.configurations) * 2,
        "used_data": inventory(data),
        "windows": [(n, str(a), str(b)) for n, a, b in early + late],
        **{k: reference[k] for k in ("splits", "folds", "settings", "matched_audit")},
    }
    parent = ExperimentStore(repo / "results/optional_15m_fill", plan, code)
    write_json(parent.path / "config.json", protocol.model_dump(mode="json"))
    for name in code["files"]:
        target = parent.path / "source_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, target)
    shutil.copyfile(repo / "docs/optional-15m-fill.md", parent.path / "protocol.md")
    print("RUN", parent.path, flush=True)
    rows, reproduction, failed, prepared, baseline_paths = [], [], {}, {}, {}
    verified_children = []
    try:
        with ExitStack() as stack:
            meta_fields = [
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
                    parent.path / (name + ".csv"), list(dict.fromkeys(meta_fields + columns))
                )
                stack.callback(value.close)
                return value

            sample = BaselineEntry("", "", None, None, 1.0, 1.0, 2.0, 1.0, 1.0)
            pairs_sink = sink("trade_pairs", list(pair_record(sample)))
            trades_sink = sink(
                "trades",
                ["baseline_trade_id", "signal_id"] + [f.name for f in fields(PerpetualTrade)],
            )
            for variant in ("baseline", "optimized"):
                if provenance(repo)["code_sha256"] != code["code_sha256"]:
                    raise ValueError("Code changed after preflight/during execution")
                for case in protocol.configurations:
                    key = case.key
                    if key in failed:
                        continue
                    if variant == "baseline":
                        prepared[key] = prepare_case(data[case.asset], key)
                    else:
                        observed = [
                            r
                            for r in reproduction
                            if (r["asset"], r["family"], r["architecture"]) == key
                        ]
                        if len(observed) != count or any(
                            r["status"] != "reproduced" for r in observed
                        ):
                            raise ValueError(
                                "Baseline gate incomplete; no experimental execution allowed"
                            )
                    store = ExperimentStore(
                        parent.path / variant / "_".join(key),
                        plan | {"case": case.model_dump(), "variant": variant},
                        code,
                    )
                    for name in ("equity", "trades"):
                        (store.path / name).mkdir()
                    try:
                        for phase, windows in (("early", early), ("late", late)):
                            if phase == "late":
                                unlock_holdout(
                                    store,
                                    len(early) * len(scenarios),
                                    boundary,
                                    code["code_sha256"],
                                )
                            for partition, start, end in windows:
                                for scenario, costs in scenarios.items():
                                    meta = {
                                        "asset": case.asset,
                                        "family": case.family,
                                        "architecture": case.architecture,
                                        "variant": variant,
                                        "partition": partition,
                                        "costs": scenario,
                                        "start": str(start),
                                        "end": str(end),
                                    }
                                    identifier = store.start(meta)
                                    pair_key = (key, partition, scenario)
                                    try:
                                        if variant == "baseline":
                                            result, sides, events = baseline_run(
                                                prepared[key], start, end, costs, scenario != "zero"
                                            )
                                            entries = entry_stream(
                                                prepared[key],
                                                key,
                                                partition,
                                                scenario,
                                                result.trades,
                                            )
                                            records = baseline_pairs(entries)
                                        else:
                                            doc = read_json(baseline_paths[pair_key])
                                            entries = restore_entries(doc["entry_opportunities"])
                                            try:
                                                result, sides, events, records = optimized_run(
                                                    prepared[key],
                                                    key,
                                                    entries,
                                                    start,
                                                    end,
                                                    costs,
                                                    scenario != "zero",
                                                )
                                            except AssertionError as exc:
                                                raise PairFailure(
                                                    "EXECUTION_INVARIANT_FAILED: " + str(exc)
                                                ) from exc
                                        values, extra = measure(
                                            result,
                                            sides,
                                            start,
                                            end,
                                            "timing" if variant == "optimized" else "baseline",
                                            scenario != "zero",
                                        )
                                        if variant == "baseline":
                                            try:
                                                audit = reproduce(
                                                    sources[case.source],
                                                    references[key][partition, scenario],
                                                    result,
                                                    sides,
                                                    values,
                                                    events,
                                                )
                                            except PairFailure as exc:
                                                reproduction.append(
                                                    meta
                                                    | {
                                                        "status": "BASELINE_REPRODUCTION_FAILED",
                                                        "error": str(exc),
                                                    }
                                                )
                                                raise
                                            reproduction.append(meta | audit)
                                        stats = fill_metrics(records)
                                        persist(
                                            store,
                                            identifier,
                                            result,
                                            sides,
                                            {
                                                "metadata": meta,
                                                "metrics": values | extra,
                                                "fill_metrics": stats,
                                                "trades": [asdict(t) for t in result.trades],
                                                "funding_events": events,
                                                "rejections": [
                                                    asdict(r) for r in result.rejections
                                                ],
                                                "entry_opportunities": serialize_entries(entries),
                                            },
                                        )
                                        if variant == "baseline":
                                            baseline_paths[pair_key] = (
                                                store.path / identifier / "result.json"
                                            )
                                        trace = meta | {"experiment_id": identifier}
                                        if variant == "optimized":
                                            pairs_sink.write(trace | r for r in records)
                                        mapping = {
                                            r["experimental_entry_time"]: r
                                            for r in records
                                            if r["status"] == "ENTERED"
                                        }
                                        for trade in result.trades:
                                            link = mapping[trade.entry_time]
                                            trades_sink.write(
                                                [
                                                    trace
                                                    | asdict(trade)
                                                    | {
                                                        k: link[k]
                                                        for k in ("baseline_trade_id", "signal_id")
                                                    }
                                                ]
                                            )
                                        rows.append(trace | values | extra | stats)
                                    except Exception as exc:
                                        with store.connect() as db:
                                            state = db.execute(
                                                "SELECT status FROM experiments WHERE id=?",
                                                (identifier,),
                                            ).fetchone()[0]
                                        if state == "started":
                                            store.finish(identifier, {"error": str(exc)}, "failed")
                                        raise
                                print(
                                    variant.upper(),
                                    key,
                                    partition,
                                    "completed",
                                    len(rows),
                                    flush=True,
                                )
                        verify(store, count)
                        verified_children.append(str(store.path.relative_to(parent.path)))
                    except PairFailure as exc:
                        failed[key] = str(exc)
                        write_json(
                            store.path / "pair_failure.json",
                            {"status": "PAIR_ABORTED", "error": str(exc)},
                        )
                        print("PAIR ABORTED", key, str(exc), flush=True)
        if provenance(repo)["code_sha256"] != code["code_sha256"]:
            raise ValueError("Code changed during experiment")
        for source in protocol.sources.values():
            verify_source(repo, source)
        report(parent.path, rows, reproduction, plan, failed)
        write_json(
            parent.path / "verification.json",
            {
                "status": "completed_with_failed_pairs" if failed else "completed",
                "executions": len(rows),
                "expected_executions": plan["expected_executions"],
                "failed_pairs": {"/".join(k): v for k, v in failed.items()},
                "verified_children": verified_children,
                "code_unchanged": True,
                "prior_artifacts_unchanged": True,
            },
        )
        seal(parent.path)
    except Exception as exc:
        write_json(
            parent.path / "failure.json",
            {"status": "failed", "error": str(exc), "completed_executions": len(rows)},
        )
        raise
    print("FINISHED", parent.path, "failed pairs:", len(failed), flush=True)
    return parent.path, not failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    os.chdir(repo)
    try:
        _, passed = run(repo, args.config)
        return 0 if passed else 1
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
