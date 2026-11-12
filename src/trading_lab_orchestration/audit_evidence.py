"""Bounded read-only primary evidence review. Does not import or execute strategies."""

import csv
import io
import json
import sqlite3
from pathlib import Path

from .execution import Executor
from .execution_inputs import resolve_implementation
from .workspaces import file_hash


class Evidence:
    def __init__(self, request):
        self.request = request
        self.refs = {}
        self.bytes = 0

    def file(self, key, path, sha=None):
        path = Path(path).absolute()
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Evidence links are forbidden")
        if key in self.refs:
            raise ValueError("Duplicate evidence key")
        self.bytes += path.stat().st_size
        if len(self.refs) >= self.request.max_files or self.bytes > self.request.max_total_bytes:
            raise ValueError("Audit evidence limit exceeded")
        actual = file_hash(path)
        if sha is not None and actual != sha:
            raise ValueError("Evidence hash mismatch: " + key)
        self.refs[key] = {"path": str(path), "sha256": actual}
        return path

    def json(self, key, path, sha=None):
        return json.loads(self.file(key, path, sha).read_text(encoding="utf-8-sig"))

    def recheck(self):
        if any(file_hash(Path(r["path"])) != r["sha256"] for r in self.refs.values()):
            raise ValueError("Evidence changed during audit")


def within(root, name):
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or path == root:
        raise ValueError("Evidence escapes its declared root")
    return path


def verify_source(store, row):
    # Existing read-only 4.3 verification: seals, source repair, native proof, final
    # tree, input/runtime hashes. No validate/run method and no strategy import.
    return Executor(store)._load(row)


def review(store, request, evidence):
    with store.connection() as conn:
        row = conn.execute(
            "SELECT * FROM executions WHERE execution_id=?", (request.execution_id,)
        ).fetchone()
        if not row:
            raise ValueError("Execution not registered")
        row = dict(row)
        task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (row["task_id"],)).fetchone()
        candidate = conn.execute(
            "SELECT * FROM candidates WHERE candidate_id=?", (task["candidate_id"],)
        ).fetchone()
        attempts = [
            dict(x)
            for x in conn.execute(
                "SELECT number,status,attempt_id FROM attempts WHERE task_id=? ORDER BY number",
                (task["task_id"],),
            )
        ]
    if row["status"] != "SUCCEEDED":
        raise ValueError("Execution is not SUCCEEDED")
    if (row["task_id"], task["candidate_id"], row["manual_repair_id"] or row["attempt_id"]) != (
        request.task_id,
        request.candidate_id,
        request.implementation_id,
    ):
        raise ValueError("Registered execution identity mismatch")
    root = Path(row["root"]).resolve()
    receipt_path = Path(request.execution_receipt).resolve()
    if not receipt_path.is_relative_to(root) or receipt_path.name != "receipt.json":
        raise ValueError("Execution receipt outside registered root")
    receipt = evidence.json("execution_receipt", receipt_path, request.execution_receipt_sha256)
    for key in ("execution_id", "task_id", "candidate_id", "implementation_id", "run_id"):
        if receipt.get(key) != getattr(request, key):
            raise ValueError("Receipt identity mismatch: " + key)
    if (
        receipt["execution_status"] != "SUCCEEDED"
        or receipt["process"]["exit_code"] != 0
        or receipt["process"]["timed_out"]
    ):
        raise ValueError("Receipt does not establish successful completion")
    req = evidence.json("execution_request", root / "request.json", row["request_sha256"])
    for key in ("execution_id", "task_id", "candidate_id", "implementation_id"):
        if req.get(key) != getattr(request, key):
            raise ValueError("Execution request identity mismatch: " + key)
    for key, expected in {
        "request_sha256": row["request_sha256"],
        "source_attempt_id": row["attempt_id"],
        "manual_repair_id": row["manual_repair_id"],
        "implementation_origin": req["implementation_origin"],
        "base_commit": req["base_commit"],
        "implementation_receipt_sha256": req["implementation_receipt_sha256"],
    }.items():
        if receipt.get(key) != expected:
            raise ValueError("Execution receipt lineage mismatch: " + key)
    artifacts = receipt["artifacts_sha256"]
    if not artifacts or len(artifacts) > request.max_files:
        raise ValueError("Missing or excessive execution artifact manifest")
    for name, sha in artifacts.items():
        evidence.file("artifact:" + name, within(root, name), sha)
    # Pre-bound all trees read by the inherited source validator before calling it.
    with store.connection() as conn:
        source = conn.execute(
            "SELECT root,workspace FROM attempts WHERE attempt_id=?", (row["attempt_id"],)
        ).fetchone()
        repair = (
            conn.execute(
                "SELECT root FROM manual_repairs WHERE repair_id=?", (row["manual_repair_id"],)
            ).fetchone()
            if row["manual_repair_id"]
            else None
        )
    for label, directory in [
        ("execution_tree", Path(req["workspace"])),
        ("source_tree", Path(source["root"])),
    ] + ([("repair_tree", Path(repair["root"]))] if repair else []):
        for path in directory.rglob("*"):
            if path.is_file() and ".git" not in path.relative_to(directory).parts[:-1]:
                evidence.file(label + ":" + path.relative_to(directory).as_posix(), path)
    for path, sha in (req["input_files"] | req["runtime_files"]).items():
        evidence.file("input:" + path, path, sha)
    native = verify_source(store, row)
    if native.implementation_id != request.implementation_id:
        raise ValueError("Verified source implementation mismatch")
    _, _, implementation_path, implementation = resolve_implementation(
        store, request.implementation_id
    )
    evidence.file(
        "implementation_receipt", implementation_path, req["implementation_receipt_sha256"]
    )
    if (
        implementation["files"] != req["implementation_final_files"]
        or receipt["implementation_final_files"] != implementation["files"]
    ):
        raise ValueError("Final implementation identity mismatch")
    manifest = json.loads(candidate["manifest_json"])
    from .contracts import digest

    if digest(candidate["manifest_json"]) != candidate["manifest_sha256"]:
        raise ValueError("Hypothesis manifest hash mismatch")
    run_dir = Path(req["results"]) / request.experiment_id / request.run_id

    def native_json(name):
        path = run_dir / name
        relative = path.relative_to(root).as_posix()
        if relative not in artifacts:
            raise ValueError("Native evidence missing from receipt: " + name)
        return evidence.json("native:" + name, path, artifacts[relative])

    run = native_json("run.json")
    outcome = native_json("outcome.json")
    summary = native_json("summary.json")
    resolved = native_json("resolved.json")
    plan = native_json("plan.json")
    provenance = native_json("provenance.json")
    native_json("environment.json")
    if (
        req["plan"]["protocol"] != request.protocol
        or evidence.refs["native:resolved.json"]["sha256"] != request.resolved_configuration_sha256
        or {d["dataset_id"]: d["manifest_sha256"] for d in req["plan"]["datasets"]}
        != request.dataset_manifest_sha256
    ):
        raise ValueError("Audit protocol/configuration/dataset pins mismatch")
    if (run["experiment_id"], run["run_id"], run["kind"]) != (
        request.experiment_id,
        request.run_id,
        "lab_experiment_v1",
    ) or outcome["status"] != "COMPLETE":
        raise ValueError("Native run identity/outcome mismatch")
    ledger = run_dir / "ledger.sqlite"
    relative = ledger.relative_to(root).as_posix()
    evidence.file("native:ledger.sqlite", ledger, artifacts[relative])
    with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        records = conn.execute(
            "SELECT id,status,result_sha256,metadata FROM experiments LIMIT ?",
            (request.max_files + 1,),
        ).fetchall()
    expected = run["expected_backtests"]
    if (
        not (
            len(records)
            == expected
            == outcome["backtests"]
            == summary["total_backtests"]
            == summary["valid_backtests"]
        )
        or summary["failed_backtests"] != 0
        or expected > req["plan"]["max_backtests"]
    ):
        raise ValueError("Native counts/denominators inconsistent")
    metrics = []
    for identifier, status, sha, metadata in records:
        if status != "completed":
            raise ValueError("Native ledger contains incomplete records")
        # The runner stores results under backtests/<id>/result.json.
        candidates = [n for n in artifacts if n.endswith("/" + identifier + "/result.json")]
        if len(candidates) != 1:
            raise ValueError("Missing or ambiguous native result: " + identifier)
        result = evidence.json("result:" + identifier, within(root, candidates[0]), sha)
        native_metrics = result["metrics"]
        if native_metrics["backtest_id"] != identifier or native_metrics["status"] != status:
            raise ValueError("Result/ledger identity mismatch")
        if len(result["trades"]) != native_metrics["closed_trades"]:
            raise ValueError("Native trades denominator mismatch")
        if any(native_metrics.get(k) != v for k, v in json.loads(metadata).items()):
            raise ValueError("Result/ledger metadata mismatch")
        equity = [n for n in artifacts if n.endswith("/" + identifier + "/equity.parquet")]
        if len(equity) != 1 or artifacts[equity[0]] != result["equity_sha256"]:
            raise ValueError("Result/equity hash mismatch")
        metrics.append(
            {"backtest_id": identifier, "metadata": json.loads(metadata), "result": result}
        )
    classifications = []
    for name in ("leaderboard.csv", "metrics.csv"):
        path = run_dir / name
        relative = path.relative_to(root).as_posix()
        evidence.file("native:" + name, path, artifacts[relative])
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
        if len(rows) > request.max_files:
            raise ValueError("Too many metrics rows")
        if name == "metrics.csv" and (
            len(rows) != expected or {r["backtest_id"] for r in rows} != {r[0] for r in records}
        ):
            raise ValueError("Metrics/ledger denominators mismatch")
        if (
            name == "metrics.csv"
            and sum(r["filter_status"] == "FAIL" for r in rows)
            != summary["filter_rejected_backtests"]
        ):
            raise ValueError("Metrics/summary filter counts mismatch")
        if name == "leaderboard.csv" and (
            len(rows) != summary["configurations"]
            or sum(r["filter_status"] == "PASS" for r in rows) != summary["survivors"]
        ):
            raise ValueError("Leaderboard/summary counts mismatch")
        classifications.append(
            {"protocol": req["plan"]["protocol"], "source": "native:" + name, "rows": rows}
        )
    comparison = {}
    if req["plan"].get("comparison") is not None:
        from .rmm_comparison import comparison_report

        saved = evidence.json(
            "paired_comparison", root / "comparison.json", artifacts["comparison.json"]
        )
        worker = evidence.json(
            "paired_worker", root / "runner-result.json", artifacts["runner-result.json"]
        )
        if saved != comparison_report(root, native, run_dir, worker, Executor._approval(row)):
            raise ValueError("Sealed RMM comparison does not match both native ledgers")
        comparison["paired_comparison"] = saved
    evidence.recheck()
    return {
        "runner_status": outcome["status"],
        "summary": summary,
        "native_results": metrics,
        "original_classifications": classifications,
        "synthetic": all(d["kind"] == "SYNTHETIC" for d in req["plan"]["datasets"]),
        "scope": req["plan"]["scope"],
        "protocol": req["plan"]["protocol"],
        "protocol_sha256": evidence.refs["native:plan.json"]["sha256"],
        "resolved_configuration": resolved,
        "execution_plan": req["plan"],
        "runner_plan": plan,
        "dataset_identity": req["plan"]["datasets"],
        "base_commit": req["base_commit"],
        "final_files": req["implementation_final_files"],
        "implementation_origin": req["implementation_origin"],
        "implementation_provenance": {
            k: implementation.get(k)
            for k in (
                "author",
                "authorization",
                "source_attempt_id",
                "source_receipt_sha256",
                "source_operator_format_repair",
                "operator_format_repair",
                "version_amendment",
                "model_invocations",
            )
        },
        "implementation_checks": implementation.get("checks"),
        "native_interface": implementation.get("native_interface"),
        "hypothesis_manifest_sha256": candidate["manifest_sha256"],
        "selection_history": manifest.get("evaluation_plan"),
        "search_history": manifest.get("novelty"),
        "model_development_attempts": attempts,
        "code_provenance": provenance,
        "independent_economic_evidence": False,
    } | comparison
