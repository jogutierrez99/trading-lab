"""Frozen sequential MTF experiments, with explicit matched-date controls."""

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
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.mtf_data import load_frozen, load_quarters, prior_plan, quarter_audit
from quant_lab.mtf_execution import (
    FAMILIES,
    configuration,
    diagnostics,
    execute_window,
    prepare,
    settings,
)
from quant_lab.mtf_reporting import KEYS, finish_batch, finish_series
from quant_lab.study_data import audit
from quant_lab.study_execution import continuous_blocks

NAME = "batch_mtf_01_baseline"


def protect(repo):
    record = json.loads(
        (repo / "reports" / NAME / "protected_previous.json").read_text(encoding="utf-8")
    )

    def check(pair):
        name, expected = pair
        path = repo / name
        return (
            name
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            else None
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        changed = [p for p in pool.map(check, record.items()) if p]
    if changed:
        raise ValueError(f"Protected files changed: {changed[:10]}")
    return {"files": len(record), "unchanged": True}


def schedule(data, previous):
    splits = [(n, pd.Timestamp(a), pd.Timestamp(b)) for n, a, b in previous["splits"]]
    start, end = splits[0][1], splits[-1][2]
    windows = splits + [("full", start, end)]
    windows += [
        (f"wf_{i:02}_test", pd.Timestamp(b), pd.Timestamp(c))
        for i, (_a, b, c) in enumerate(previous["folds"])
    ]
    windows += [
        (f"segment_{i:02}", f.index[0], f.index[-1] + pd.Timedelta(hours=1))
        for i, f in enumerate(continuous_blocks(data["BTCUSDT"]["frames"]["1h"], "1h"))
    ]
    boundary = splits[-1][1]
    return (
        [w for w in windows if w[2] <= boundary],
        [w for w in windows if w[2] > boundary],
        boundary,
    )


def matrix(architectures, cohort):
    return [
        {"asset": a, "family": f, "architecture": v, "mode": "LONG_ONLY", "cohort": cohort}
        for a in ("BTCUSDT", "ETHUSDT")
        for f in FAMILIES
        for v in architectures
    ]


def inventory(data):
    result = []
    for asset, item in data.items():
        for key, frame in (("contract", item["frames"]["1h"]), ("mark", item["mark"])):
            result.append(audit(frame, asset + "_" + key, "1h"))
        for key in ("quarter", "quarter_mark"):
            if key in item:
                result.append(quarter_audit(item[key], asset + "_" + key))
    return result


def verify(store, expected):
    with store.connect() as db:
        records = db.execute("SELECT id,status,result_sha256 FROM experiments").fetchall()
    if len(records) != expected:
        raise ValueError("Incomplete experiment matrix")
    for id_, status, sha in records:
        path = store.path / id_ / "result.json"
        if status != "completed" or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError("Ledger integrity failure")
        doc = json.loads(path.read_text(encoding="utf-8"))
        for kind, ext in (("equity", ".parquet"), ("trades", ".json")):
            if (
                hashlib.sha256((store.path / kind / (id_ + ext)).read_bytes()).hexdigest()
                != doc[kind + "_sha256"]
            ):
                raise ValueError("Artifact integrity failure")
    write_json(
        store.path / "verification.json",
        {"status": "completed", "executions": expected, "ledger_and_artifacts_verified": True},
    )


def run_batch(repo, name, data, configs, protocol, code, preceding=None):
    early, late, boundary = schedule(data, protocol)
    resolved = [
        c
        | {
            "config": configuration(
                c["asset"], c["family"], c["architecture"], c["mode"]
            ).model_dump(mode="json")
        }
        for c in configs
    ]
    plan = protocol | {
        "name": name,
        "matrix": resolved,
        "used_data": inventory(data),
        "windows": [(n, str(a), str(b)) for n, a, b in early + late],
    }
    store = ExperimentStore(repo / "results" / name, plan, code)
    print("RUN", name, store.path, flush=True)
    write_json(store.path / "config.json", resolved)
    for folder in ("equity", "trades"):
        (store.path / folder).mkdir()
    prepared = {}
    for c in resolved:
        config = configuration(c["asset"], c["family"], c["architecture"], c["mode"])
        prepared[tuple(c[k] for k in KEYS)] = (config, prepare(data[c["asset"]], config))
    rows = []
    inherited = settings()
    with (store.path / "trades.csv").open("x", newline="", encoding="utf-8") as output:
        writer = None
        for phase, windows in (("early", early), ("late", late)):
            if phase == "late":
                unlock_holdout(
                    store,
                    len(early) * len(configs) * len(inherited.costs),
                    boundary,
                    code["code_sha256"],
                )
            for partition, left, right in windows:
                for c in configs:
                    config, blocks = prepared[tuple(c[k] for k in KEYS)]
                    for scenario, costs in inherited.costs.items():
                        meta = c | {
                            "partition": partition,
                            "costs": scenario,
                            "start": str(left),
                            "end": str(right),
                            "timeframe": config.market.timeframe,
                        }
                        id_ = store.start(meta)
                        try:
                            result, sides, events = execute_window(
                                blocks,
                                config,
                                left,
                                right,
                                costs,
                                inherited.capital,
                                scenario != "zero",
                            )
                            diag = diagnostics(blocks, config, left, right, result, sides)
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
                            values.pop("long_mfe_mae")
                            values.pop("short_mfe_mae")
                            values["average_holding_hours"] = (
                                values["average_holding_bars"]
                                * (0.25 if config.market.timeframe == "15m" else 1)
                                if values["average_holding_bars"] is not None
                                else None
                            )
                            values["total_costs"] = (
                                values["total_execution_costs"] + values["funding_cost"]
                            )
                            values["average_trade"] = values["expectancy"]
                            trades = [asdict(t) for t in result.trades]
                            persist(
                                store,
                                id_,
                                result,
                                sides,
                                {
                                    "metadata": meta,
                                    "metrics": values,
                                    "diagnostics": diag,
                                    "trades": trades,
                                    "funding_events": events,
                                    "rejections": [asdict(r) for r in result.rejections],
                                },
                            )
                            for t in trades:
                                record = meta | {"experiment_id": id_} | t
                                if writer is None:
                                    writer = csv.DictWriter(output, fieldnames=list(record))
                                    writer.writeheader()
                                writer.writerow(record)
                            rows.append(meta | values | diag["counts"] | {"experiment_id": id_})
                        except Exception as exc:
                            with store.connect() as db:
                                status = db.execute(
                                    "SELECT status FROM experiments WHERE id=?", (id_,)
                                ).fetchone()[0]
                            if status == "started":
                                store.finish(id_, {"error": str(exc)}, "failed")
                            raise
                print(name, partition, "completed", len(rows), flush=True)
    comparison = finish_batch(store, rows, preceding)
    verify(store, len(configs) * len(inherited.costs) * (len(early) + len(late)))
    return store.path, comparison


def run(repo: Path):
    protected = protect(repo)
    code = provenance(repo)
    preflight = json.loads((repo / "reports" / NAME / "preflight.json").read_text(encoding="utf-8"))
    if preflight["code_sha256"] != code["code_sha256"] or any(
        v["exit_code"] for v in preflight["checks"].values()
    ):
        raise ValueError("Required preflight failed or source changed")
    original, original_audit = load_frozen()
    matched, _ = load_frozen()
    matched_audit = load_quarters(matched, matched=True)
    prior = prior_plan()
    protocol = {
        "splits": prior["splits"],
        "folds": prior["folds"],
        "settings": settings().model_dump(mode="json"),
        "classification": CLASSIFICATION,
        "original_audit": original_audit,
        "matched_audit": matched_audit,
        "preflight": preflight,
        "protected": protected,
        "rules": (
            "See source_snapshot and docs/mtf-series-design.md. No "
            "optimization. Closed-candle features only; next-open entry; 1h "
            "ATR risk, 72 elapsed hours, inherited funding/cost/margin model."
        ),
        "selection": (
            "Only matched LONG_ONLY PROMISING_BUT_UNCONFIRMED rows qualify for"
            " phase04. Observed holdout selection is diagnostic, not pristine "
            "OOS."
        ),
        "matrices": {
            "01": matrix(["V1"], "original"),
            "02": matrix(["V2"], "original"),
            "03": matrix(["V1", "V2", "V3", "V4"], "matched"),
        },
    }
    parent = ExperimentStore(repo / "results" / "mtf_series", protocol, code)
    for name in code["files"]:
        target = parent.path / "source_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, target)
    shutil.copyfile(repo / "docs" / "mtf-series-design.md", parent.path / "protocol.md")
    print("SERIES", parent.path, flush=True)
    comparisons = []
    paths = []
    for number, name, data in (
        ("01", NAME, original),
        ("02", "batch_mtf_02_regime", original),
        ("03", "batch_mtf_03_architectures", matched),
    ):
        path, comparison = run_batch(
            repo,
            name,
            data,
            protocol["matrices"][number],
            protocol,
            code,
            comparisons[-1] if number == "02" else None,
        )
        paths.append(str(path))
        comparisons.append(comparison)
        write_json(
            parent.path / ("phase_" + number + ".json"), {"path": str(path), "status": "completed"}
        )
    selected = (
        comparisons[-1]
        .loc[comparisons[-1].classification.str.contains("PROMISING_BUT_UNCONFIRMED"), KEYS]
        .to_dict("records")
    )
    eligibility = {
        "criteria": CLASSIFICATION["PROMISING_BUT_UNCONFIRMED"],
        "selected": selected,
        "status": "eligible" if selected else "skipped_no_survivors",
    }
    write_json(parent.path / "phase_04_eligibility.json", eligibility)
    if selected:
        configs = [c | {"mode": m} for c in selected for m in ("SHORT_ONLY", "LONG_SHORT")]
        path, comparison = run_batch(
            repo, "batch_mtf_04_directional", matched, configs, protocol, code, comparisons[-1]
        )
        paths.append(str(path))
        comparisons.append(comparison)
    else:
        (parent.path / "phase_04.md").write_text(
            (
                "# MTF 04\n\nNo matched LONG_ONLY configuration passed the inherited"
                " eligibility rules. No directional performance runs were "
                "authorized by the frozen protocol; mode implementations were "
                "unit-tested.\n"
            ),
            encoding="utf-8",
        )
    finish_series(parent.path, comparisons, eligibility)
    if provenance(repo)["code_sha256"] != code["code_sha256"]:
        raise ValueError("Frozen code changed during execution")
    write_json(
        parent.path / "verification.json",
        {
            "status": "completed",
            "phases": paths,
            "protected": protect(repo),
            "code_unchanged": True,
        },
    )
    for folder in [Path(p) for p in paths] + [parent.path]:
        write_json(
            folder / "artifact_manifest.json",
            {
                str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(folder.rglob("*"))
                if p.is_file()
            },
        )
    print("COMPLETE", parent.path, flush=True)
    return parent.path
