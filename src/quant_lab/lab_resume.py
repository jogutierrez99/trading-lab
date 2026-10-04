"""Verified continuation runs; source artifacts are read-only and never copied.

The new ledger retains original backtest IDs. reuse.json locates their immutable
files in original runs; keep those directories when archiving a continuation.
"""

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

from quant_lab.experiments import write_json

# Exact reviewed transition: only recovery plumbing around the original loop.
# Both sides must match; a future runner edit requires another compatibility audit.
RUNNER_TRANSITION = (
    "e252d626ffa4ad75e78387c7f42a103798e4282acc0d8c0622780d9099859d64",
    "de643e76be21cad7d0f5035d3e4c8df484031fb678909ed21d0e3c98d6c60f04",
)


def canonical(value):
    return json.dumps(value, sort_keys=True, default=str, allow_nan=False)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def select_source(directory: Path, name: str) -> Path:
    if name == "latest":
        candidates = sorted(p.parent for p in directory.glob("*/run.json"))
        if not candidates:
            raise ValueError(f"No lab runs to resume: {directory.name}")
        return max(candidates, key=lambda p: (read_json(p / "run.json")["created_at"], p.name))
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", name):
        raise ValueError("--resume expects a run ID or latest")
    source = directory / name
    if not (source / "run.json").is_file():
        raise ValueError(f"Run does not exist: {source}")
    return source


def compatible_code(saved, current):
    for name in ("python", "dependencies", "platform"):
        if not saved.get(name) or saved.get(name) != current.get(name):
            raise ValueError(
                f"Resume environment mismatch: {name}; use the original Python/environment"
            )

    def relevant(files):
        result = {}
        for name, value in files.items():
            name = name.replace("\\", "/")
            # Forward observers and CLI dispatch cannot affect offline backtests.
            if name.startswith("src/") and not name.startswith("src/quant_lab/forward/"):
                if name not in {"src/quant_lab/lab_cli.py", "src/quant_lab/lab_resume.py"}:
                    result[name] = value
        return result

    before, after = relevant(saved["files"]), relevant(current["files"])
    differences = []
    for name in before.keys() | after.keys():
        if before.get(name) == after.get(name):
            continue
        if (
            name == "src/quant_lab/lab_runner.py"
            and (before.get(name), after.get(name)) == RUNNER_TRANSITION
        ):
            continue
        differences.append(name)
    if differences:
        raise ValueError(f"Resume code mismatch: {', '.join(sorted(differences))}")


class Recovery:
    def __init__(self, source: Path, plan: dict, resolved: dict, code: dict):
        self.source = source.resolve()
        self.records = {}
        self.invalid = []
        self.used = set()
        self.source_hashes = {
            name: digest(source / name)
            for name in ("run.json", "plan.json", "resolved.json", "provenance.json")
        }
        self.ledger_hash = digest(source / "ledger.sqlite")
        header = read_json(source / "run.json")
        if (
            header.get("kind") != "lab_experiment_v1"
            or header.get("experiment_id") != plan["experiment_id"]
        ):
            raise ValueError("Resume source is not the requested lab experiment")
        self.expected = header["expected_backtests"]
        count = len(resolved["parameters"]) * len(plan["markets"]) * len(plan["modes"])
        scenarios = 1 + len(plan["validation"]["cost_stress"])
        folds = len(plan["validation"]["walk_forward"])
        expected = count * scenarios * (3 + len(plan.get("diagnostic_periods", {})) + folds)
        expected += len(plan["markets"]) * len(plan["modes"]) * scenarios * folds
        if self.expected != expected:
            raise ValueError("Resume expected count does not match the frozen plan")
        for filename, current in (("plan.json", plan), ("resolved.json", resolved)):
            if canonical(read_json(source / filename)) != canonical(current):
                raise ValueError(
                    f"Resume configuration/dataset mismatch: {filename}; "
                    "restore the original inputs"
                )
        compatible_code(read_json(source / "provenance.json"), code)
        reuse_path = source / "reuse.json"
        if reuse_path.exists():
            self.source_hashes["reuse.json"] = digest(reuse_path)
        references = read_json(reuse_path)["artifacts"] if reuse_path.exists() else {}
        uri = (source / "ledger.sqlite").resolve().as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True) as db:
                if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise ValueError("Resume ledger failed integrity check")
                ledger = db.execute(
                    "SELECT id,status,created,metadata,result_sha256 FROM experiments"
                ).fetchall()
        except sqlite3.Error as exc:
            raise ValueError(f"Cannot read resume ledger: {exc}") from exc
        print(
            f"Auditing {source.name}: {len(ledger)} records (JSON + equity SHA256)", file=sys.stderr
        )
        for number, (record, status, created, metadata, result_hash) in enumerate(ledger, 1):
            if not re.fullmatch(r"[0-9a-f]{32}", record):
                raise ValueError("Invalid backtest ID in resume ledger")
            folder = Path(references.get(record, str(self.source / record)))
            try:
                if status != "completed":
                    raise ValueError(f"ledger status={status}")
                if not folder.is_absolute() or folder.name != record:
                    raise ValueError("Invalid source artifact location")
                meta = json.loads(metadata)
                if read_json(folder / "metadata.json") != meta:
                    raise ValueError("metadata/ledger mismatch")
                if digest(folder / "result.json") != result_hash:
                    raise ValueError("result SHA256 mismatch")
                document = read_json(folder / "result.json")
                row = document["metrics"]
                if row["status"] != "completed" or row["backtest_id"] != record:
                    raise ValueError("result identity/status mismatch")
                if any(row.get(k) != v for k, v in meta.items()):
                    raise ValueError("result metadata mismatch")
                if digest(folder / "equity.parquet") != document["equity_sha256"]:
                    raise ValueError("equity SHA256 mismatch")
                key = canonical(meta)
                if key in self.records:
                    raise RuntimeError("Duplicate completed work identity in source ledger")
                self.records[key] = {
                    "id": record,
                    "created": created,
                    "metadata": metadata,
                    "hash": result_hash,
                    "folder": str(folder),
                    "row": row,
                }
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.invalid.append({"backtest_id": record, "reason": str(exc)})
            if number % 1000 == 0:
                print(
                    f"Verified {number}/{len(ledger)}; reusable {len(self.records)}",
                    file=sys.stderr,
                )
        if len(self.records) > self.expected:
            raise ValueError("Resume ledger contains more results than expected")
        self.assert_source_stable()

    def assert_source_stable(self):
        hashes = self.source_hashes | {"ledger.sqlite": self.ledger_hash}
        if any(digest(self.source / name) != value for name, value in hashes.items()):
            raise ValueError("Source changed during audit; stop the original run first")

    def already_complete(self):
        try:
            outcome = read_json(self.source / "outcome.json")
        except (OSError, ValueError):
            return False
        return (
            outcome.get("status") == "COMPLETE"
            and len(self.records) == self.expected
            and not self.invalid
            and all(
                (self.source / name).is_file()
                for name in (
                    "summary.json",
                    "metrics.csv",
                    "leaderboard.csv",
                    "ai_summary.md",
                    "summary.md",
                )
            )
        )

    def summary(self):
        return {
            "source_run": str(self.source),
            "expected_backtests": self.expected,
            "verified_reusable": len(self.records),
            "pending_backtests": self.expected - len(self.records),
            "invalid_or_unfinished": self.invalid,
            "note": "Read-only audit; no backtests executed. "
            "Keep source directories for reused artifacts.",
        }

    def attach(self, store):
        # One transaction, no 35k copies of large equity files. Original hashes and
        # backtest IDs remain in the new ledger. References are flattened on retry.
        self.assert_source_stable()
        write_json(
            store.path / "reuse.json",
            self.summary()
            | {
                "source_ledger_sha256": self.ledger_hash,
                "source_metadata_sha256": self.source_hashes,
                "artifacts": {r["id"]: r["folder"] for r in self.records.values()},
            },
        )
        with store.connect() as db:
            db.executemany(
                "INSERT INTO experiments VALUES (?, 'completed', ?, ?, ?, NULL)",
                [(r["id"], r["created"], r["metadata"], r["hash"]) for r in self.records.values()],
            )

    def take(self, metadata):
        key = canonical(metadata)
        if key not in self.records:
            return None
        if key in self.used:
            raise ValueError("Repeated work identity during resume")
        self.used.add(key)
        return dict(self.records[key]["row"])

    def assert_consumed(self):
        if len(self.used) != len(self.records):
            raise ValueError("Source results do not match the reconstructed schedule/WF winners")
