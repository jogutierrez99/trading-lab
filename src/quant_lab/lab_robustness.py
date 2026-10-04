"""Second-phase fixed-candidate WF TEST evidence, without changing source runs."""

import ast
import json
import math
import re
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quant_lab.config import load_yaml
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.lab_classification_policy import ClassificationPolicy
from quant_lab.lab_evidence import assert_unchanged, completed_run, read_json, sha256
from quant_lab.lab_resume import canonical, compatible_code
from quant_lab.lab_runner import evaluate, parameter_risk, prepare
from quant_lab.lab_schema import Experiment
from quant_lab.metrics import summarize


def records(frame):
    return json.loads(frame.to_json(orient="records", double_precision=15))


def parameters(value):
    return json.loads(value) if isinstance(value, str) else value


def cell(row):
    return row["configuration_id"], row["period"], row["scenario"]


def checked_rows(evidence, rows):
    """Only exact source candidates, prescribed dates and scenarios may be merged."""
    identities = {r["configuration_id"]: r for r in records(evidence["metrics"])}
    periods = {
        f"wf_{i}_test": f["test"]
        for i, f in enumerate(evidence["plan"]["validation"]["walk_forward"])
    }
    scenarios = {"base", *evidence["plan"]["validation"]["cost_stress"]}
    seen = set()
    for row in rows:
        if cell(row) in seen:
            raise ValueError("Duplicate fixed-candidate evidence cell")
        seen.add(cell(row))
        original = identities.get(row["configuration_id"])
        if original is None or row["period"] not in periods or row["scenario"] not in scenarios:
            raise ValueError("Unknown fixed-candidate evidence identity")
        if (
            row["status"] != "completed"
            or any(row[k] != original[k] for k in ("symbol", "timeframe", "mode"))
            or parameters(row["parameters"]) != parameters(original["parameters"])
        ):
            raise ValueError("Frozen candidate parameters/market mismatch")
        if any(
            pd.Timestamp(row[k]) != pd.Timestamp(periods[row["period"]][k])
            for k in ("start", "end")
        ):
            raise ValueError("Fixed-candidate fold dates mismatch")
    return rows


def merge_fixed(evidence, fixed_rows):
    original = records(evidence["metrics"])
    known = {cell(r): r for r in original}
    for row in checked_rows(evidence, fixed_rows):
        if cell(row) in known:
            before = known[cell(row)]
            if set(before) != set(row) or any(
                not math.isclose(before[k], row[k], rel_tol=1e-12, abs_tol=1e-12)
                if isinstance(before[k], (int, float)) and isinstance(row[k], (int, float))
                else before[k] != row[k]
                for k in before
            ):
                raise ValueError("Fixed evidence conflicts with existing source cell")
        else:
            known[cell(row)] = row
    return pd.DataFrame(known.values())


def latest_robustness(root, evidence):
    base = root / "reports/lab-robustness" / evidence["header"]["run_id"]
    complete = []
    for path in base.glob("*/robustness.json"):
        outcome = path.parent / "outcome.json"
        if outcome.exists() and read_json(outcome).get("status") == "COMPLETE":
            complete.append(path)
    if not complete:
        return None
    path = max(complete, key=lambda p: (read_json(p)["created_at"], p.parent.name))
    outcome, document = read_json(path.parent / "outcome.json"), read_json(path)
    expected = {
        "robustness.json",
        "metrics.csv",
        "summary.md",
        "plan.json",
        "provenance.json",
        "request.json",
    }
    if set(outcome.get("sha256", {})) != expected or any(
        sha256(path.parent / name) != value for name, value in outcome["sha256"].items()
    ):
        raise ValueError("Robustness artifact hash mismatch")
    if (
        document["source_sha256"] != evidence["source_sha256"]
        or document["source_run_id"] != evidence["header"]["run_id"]
    ):
        raise ValueError("Stale robustness: source hashes changed")
    if document["scope"] != "fixed_candidate_robustness":
        raise ValueError("Invalid robustness evidence scope")
    frame = pd.read_csv(path.parent / "metrics.csv")
    rows = checked_rows(evidence, records(frame))
    if len(rows) != document["evidence_cells"] or len(rows) != outcome["evidence_cells"]:
        raise ValueError("Robustness evidence count mismatch")
    merge_fixed(evidence, rows)
    return path, document, rows


def verify_record(directory, row, ledger_hashes=None):
    """Audit a requested cell's ledger, result, metadata and equity, including resume refs."""
    record = row["backtest_id"]
    if not re.fullmatch(r"[0-9a-f]{32}", record):
        raise ValueError("Invalid robustness backtest identity")
    reuse = directory / "reuse.json"
    references = read_json(reuse).get("artifacts", {}) if reuse.exists() else {}
    folder = Path(references.get(record, str((directory / record).resolve())))
    if not folder.is_absolute() or folder.name != record:
        raise ValueError("Invalid reused artifact location")
    uri = (directory / "ledger.sqlite").resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        ledger = db.execute(
            "SELECT status,metadata,result_sha256 FROM experiments WHERE id=?", (record,)
        ).fetchone()
    if ledger is None or ledger[0] != "completed":
        raise ValueError("Robustness source ledger record not completed")
    metadata = json.loads(ledger[1])
    if (
        read_json(folder / "metadata.json") != metadata
        or sha256(folder / "result.json") != ledger[2]
    ):
        raise ValueError("Robustness result/metadata hash mismatch")
    document = read_json(folder / "result.json")
    result = document["metrics"]
    if (
        result["backtest_id"] != record
        or result["status"] != "completed"
        or any(result.get(k) != v for k, v in metadata.items())
    ):
        raise ValueError("Robustness result identity mismatch")
    if sha256(folder / "equity.parquet") != document["equity_sha256"]:
        raise ValueError("Robustness equity hash mismatch")
    for key, value in row.items():
        if key in {"filter_status", "filter_reasons"}:
            continue  # Legacy report annotations are not execution metrics.
        saved = result.get(key)
        if key == "parameters":
            same = parameters(value) == saved
        elif key in {"costs", "resolved_risk"} and isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                decoded = ast.literal_eval(value)
            same = decoded == saved
        elif isinstance(value, (int, float)) and isinstance(saved, (int, float)):
            same = math.isclose(value, saved, rel_tol=1e-12, abs_tol=1e-12)
        else:
            same = value == saved
        if not same:
            raise ValueError(f"Robustness metrics/result mismatch: {key}")
    hashes = {
        name: sha256(folder / name) for name in ("metadata.json", "result.json", "equity.parquet")
    }
    ledger_hashes = ledger_hashes if ledger_hashes is not None else {}
    key = str(directory.resolve())
    if key not in ledger_hashes:
        ledger_hashes[key] = sha256(directory / "ledger.sqlite")
    return {
        "backtest_id": record,
        "directory": str(directory.resolve()),
        "folder": str(folder),
        "sha256": hashes,
        "ledger_sha256": ledger_hashes[key],
        "reuse_sha256": sha256(reuse) if reuse.exists() else None,
        "request_sha256": sha256(directory / "request.json")
        if (directory / "request.json").exists()
        else None,
    }


def assert_references(references):
    checked_ledgers = {}
    for ref in references:
        directory, folder = Path(ref["directory"]), Path(ref["folder"])
        key = str(directory.resolve())
        if key not in checked_ledgers:
            checked_ledgers[key] = sha256(directory / "ledger.sqlite")
        if checked_ledgers[key] != ref["ledger_sha256"] or any(
            sha256(folder / name) != value for name, value in ref["sha256"].items()
        ):
            raise ValueError("Robustness source artifacts changed")
        if (
            ref["reuse_sha256"] is not None
            and sha256(directory / "reuse.json") != ref["reuse_sha256"]
        ):
            raise ValueError("Robustness reuse references changed")
        if (
            ref.get("request_sha256") is not None
            and sha256(directory / "request.json") != ref["request_sha256"]
        ):
            raise ValueError("Robustness request changed")


def additional_cells(root, evidence, code, requested):
    """Recover completed cells from compatible supplements, including interruptions."""
    if not requested:
        return {}
    found = {}
    base = root / "reports/lab-robustness" / evidence["header"]["run_id"]
    for path in sorted(base.glob("*/request.json")):
        request = read_json(path)
        if (
            request["source_sha256"] != evidence["source_sha256"]
            or request["scope"] != "fixed_candidate_robustness"
        ):
            raise ValueError("Interrupted robustness source/scope mismatch")
        compatible_code(read_json(path.parent / "provenance.json"), code)
        if canonical(read_json(path.parent / "plan.json")) != canonical(evidence["plan"]):
            raise ValueError("Interrupted robustness plan mismatch")
        uri = (path.parent / "ledger.sqlite").resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            entries = db.execute(
                "SELECT id,metadata FROM experiments WHERE status='completed'"
            ).fetchall()
        for record, metadata in entries:
            key = cell(json.loads(metadata))
            if key not in requested or key in found:
                continue
            row = read_json(path.parent / record / "result.json")["metrics"]
            for field in ("parameters", "costs", "resolved_risk"):
                if field in row:
                    row[field] = json.dumps(row[field], sort_keys=True)
            row = {k: row.get(k) for k in evidence["metrics"].columns}
            checked_rows(evidence, [row])
            found[key] = row, path.parent
    return found


def execution_context(root, evidence):
    exp = Experiment.model_validate_json(json.dumps(evidence["plan"]))

    # Standard-library UTC matches the frozen YAML and the audited Pandas index;
    # Pydantic JSON's TzInfo otherwise mixes timezone types in StudyBackend equity.
    def utc_period(period):
        return period.model_copy(
            update={k: getattr(period, k).astimezone(UTC) for k in ("start", "end")}
        )

    exp = exp.model_copy(
        update={
            "validation": exp.validation.model_copy(
                update={
                    **{
                        k: utc_period(getattr(exp.validation, k))
                        for k in ("train", "validation", "test")
                    },
                    "walk_forward": [
                        f.model_copy(
                            update={"train": utc_period(f.train), "test": utc_period(f.test)}
                        )
                        for f in exp.validation.walk_forward
                    ],
                }
            )
        }
    )
    # Paths stay YAML-relative, but the input is the frozen plan, never today's YAML.
    path = root / "configs/experiments" / (exp.experiment_id + ".yaml")
    context = prepare(path, exp, full=True)
    saved = evidence["resolved"]
    current = {
        "app": context["app"].model_dump(mode="json"),
        "strategy": context["template"].model_dump(mode="json"),
        "parameters": context["parameters"],
        "datasets": context["datasets"],
        "backend": "study_backend_v1",
        "execution": exp.execution.model_dump(),
        "parameter_risks": [
            parameter_risk(
                context["registry"].implementation(exp.strategy.id), context["template"].risk, p
            ).model_dump(mode="json")
            for p in context["parameters"]
        ]
        if context["registry"].implementation(exp.strategy.id).lab_risk_parameters
        else None,
    }
    if canonical(saved) != canonical(current):
        raise ValueError("Robustness frozen configuration/dataset mismatch")
    code = provenance(root)
    compatible_code(evidence["provenance"], code)
    context["execution"] = exp.execution
    return exp, context, code


def robust(root: Path, identifier: str, policy_path: Path | None = None) -> dict:
    from quant_lab.lab_classification import classify, classify_evidence

    policy_path = policy_path or root / "configs/research/lab_classification_v1.yaml"
    policy = load_yaml(policy_path, ClassificationPolicy)
    evidence = completed_run(root, identifier)
    initial = classify_evidence(evidence, policy)
    candidates = [c for c in initial["candidates"] if c["RESEARCH_PASS"] and c["OOS_PASS"]]
    previous = latest_robustness(root, evidence)
    exp = context = code = None
    if candidates:
        exp, context, code = execution_context(root, evidence)
        if len(exp.validation.walk_forward) != policy.robustness.required_folds:
            raise ValueError("Robustness requires all prescribed WF folds")
        if previous:
            compatible_code(read_json(previous[0].parent / "provenance.json"), code)
    source_cells = {cell(r): r for r in records(evidence["metrics"])}
    old_cells = {cell(r): r for r in previous[2]} if previous else {}
    old_refs = {r["backtest_id"]: r for r in previous[1]["references"]} if previous else {}
    pending, rows, references, ledger_hashes = [], [], [], {}
    wanted = {
        (c["configuration_id"], f"wf_{i}_test", scenario)
        for c in candidates
        for i in range(len(exp.validation.walk_forward))
        for scenario in ("base", policy.adverse_scenario)
    }
    extra = (
        additional_cells(root, evidence, code, wanted - source_cells.keys() - old_cells.keys())
        if candidates
        else {}
    )
    for candidate in candidates:
        identity = candidate["configuration_id"]
        for key, row in source_cells.items():
            if (
                key[0] == identity
                and key[1] in {"train", "validation", "test"}
                and key[2] in {"base", policy.adverse_scenario}
            ):
                references.append(verify_record(evidence["path"], row, ledger_hashes))
        for i, fold in enumerate(exp.validation.walk_forward):
            for scenario in ("base", policy.adverse_scenario):
                key = identity, f"wf_{i}_test", scenario
                row = source_cells.get(key) or old_cells.get(key)
                if row is None and key in extra:
                    row = extra[key][0]
                if row is not None:
                    directory = (
                        evidence["path"]
                        if key in source_cells
                        else (
                            Path(old_refs[row["backtest_id"]]["directory"])
                            if key in old_cells
                            else extra[key][1]
                        )
                    )
                    references.append(verify_record(directory, row, ledger_hashes))
                    rows.append(row)
                else:
                    pending.append((candidate, i, fold.test, scenario))
    assert_unchanged(evidence)
    assert_references(references)
    code = code or provenance(root)
    store = ExperimentStore(
        root / "reports/lab-robustness" / evidence["header"]["run_id"], evidence["plan"], code
    )
    write_json(
        store.path / "request.json",
        {
            "scope": "fixed_candidate_robustness",
            "source_sha256": evidence["source_sha256"],
            "eligible_candidates": [c["configuration_id"] for c in candidates],
            "policy_sha256": sha256(policy_path),
        },
    )
    executed = 0
    try:
        for candidate, i, period, scenario in pending:
            market_index = next(
                j
                for j, m in enumerate(exp.markets)
                if (m.symbol, m.timeframe) == (candidate["symbol"], candidate["timeframe"])
            )
            costs = context["scenarios"][scenario]
            params = candidate["parameters"]
            cls = context["registry"].implementation(exp.strategy.id)
            meta = {
                **{
                    k: candidate[k]
                    for k in ("configuration_id", "symbol", "timeframe", "mode", "parameters")
                },
                "strategy": exp.strategy.id,
                "strategy_version": context["template"].version,
                "period": f"wf_{i}_test",
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
                "scenario": scenario,
                "costs": costs.model_dump(),
            }
            if cls.lab_risk_parameters:
                meta["resolved_risk"] = parameter_risk(
                    cls, context["template"].risk, params
                ).model_dump(mode="json")
            record = store.start(meta)
            try:
                result = evaluate(
                    context,
                    context["frames"][market_index],
                    exp.markets[market_index],
                    candidate["mode"],
                    params,
                    period,
                    costs,
                )
                row = (
                    meta
                    | summarize(result)
                    | {
                        "backtest_id": record,
                        "status": "completed",
                        "long_contribution": sum(
                            t.net_pnl for t in result.trades if t.side == "long"
                        ),
                        "short_contribution": sum(
                            t.net_pnl for t in result.trades if t.side == "short"
                        ),
                        "long_trades": sum(t.side == "long" for t in result.trades),
                        "short_trades": sum(t.side == "short" for t in result.trades),
                    }
                )
                pd.DataFrame({"equity": result.equity, "exposure": result.exposure}).to_parquet(
                    store.path / record / "equity.parquet"
                )
                store.finish(
                    record,
                    {
                        "metrics": row,
                        "equity_sha256": sha256(store.path / record / "equity.parquet"),
                        "trades": [asdict(t) for t in result.trades],
                        "rejections": [asdict(r) for r in result.rejections],
                    },
                )
            except (ValueError, RuntimeError, ArithmeticError) as exc:
                store.finish(record, {"error": str(exc)}, "failed")
                raise
            row["parameters"] = json.dumps(params)
            row["costs"] = str(row["costs"])
            if "resolved_risk" in row:
                row["resolved_risk"] = str(row["resolved_risk"])
            # Persist exactly the source CSV schema for deterministic merging.
            rows.append({k: row.get(k) for k in evidence["metrics"].columns})
            executed += 1
        checked_rows(evidence, rows)
        pd.DataFrame(rows, columns=evidence["metrics"].columns).to_csv(
            store.path / "metrics.csv", index=False
        )
        # Reference new rows via the same ledger/result verification used for reused work.
        for row in records(pd.read_csv(store.path / "metrics.csv")):
            if row["backtest_id"] not in {r["backtest_id"] for r in references}:
                references.append(verify_record(store.path, row, ledger_hashes))
        document = {
            "robustness_schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "scope": "fixed_candidate_robustness",
            "source_run_id": evidence["header"]["run_id"],
            "source_sha256": evidence["source_sha256"],
            "policy_sha256": sha256(policy_path),
            "policy": policy.model_dump(mode="json"),
            "eligible_candidates": [c["configuration_id"] for c in candidates],
            "evidence_cells": len(rows),
            "executed_backtests": executed,
            "reused_backtests": len(rows) - executed,
            "references": references,
            "message": "0 candidates eligible for robustness evaluation"
            if not candidates
            else f"{len(candidates)} candidates eligible for robustness evaluation",
        }
        write_json(store.path / "robustness.json", document)
        text = (
            f"# Fixed candidate robustness: {identifier}\n\n{document['message']}\n\n"
            + f"Executed {executed}; reused {len(rows) - executed}. "
            + "Only frozen WF TEST BASE/ADVERSE.\n"
            + "Walk-forward selection remains the original TRAIN-selected procedure.\n"
        )
        (store.path / "summary.md").write_text(text, encoding="utf-8")
        assert_unchanged(evidence)
        assert_references(references)
        names = (
            "robustness.json",
            "metrics.csv",
            "summary.md",
            "plan.json",
            "provenance.json",
            "request.json",
        )
        write_json(
            store.path / "outcome.json",
            {
                "status": "COMPLETE",
                "evidence_cells": len(rows),
                "sha256": {n: sha256(store.path / n) for n in names},
            },
        )
    except BaseException as exc:
        write_json(store.path / "outcome.json", {"status": "FAILED", "error": str(exc)})
        raise
    classification = classify(root, evidence["header"]["run_id"], policy_path)
    return {
        "robustness_directory": str(store.path),
        "classification_directory": str(classification),
        "eligible_candidates": len(candidates),
        "executed_backtests": executed,
        "reused_backtests": len(rows) - executed,
        "message": document["message"],
    }
