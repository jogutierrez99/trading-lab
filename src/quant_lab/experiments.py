"""Local immutable experiment artifacts with a SQLite lifecycle ledger."""

import hashlib
import importlib.metadata
import json
import platform
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, default=str, allow_nan=False)
        handle.write("\n")


def provenance(root: Path) -> dict:
    files = sorted(
        p
        for folder, pattern in (
            ("src", "*.py"),
            ("scripts", "*.py"),
            ("configs", "*.yaml"),
            ("tests", "*.py"),
        )
        for p in (root / folder).rglob(pattern)
    ) + [root / "pyproject.toml"]
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

    def git(*args):
        try:
            result = subprocess.run(
                ["git", *args], cwd=root, text=True, capture_output=True, check=False
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except OSError:
            return None

    return {
        "code_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        "files": hashes,
        "git_revision": git("rev-parse", "HEAD"),
        "git_status": git("status", "--short"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("pandas", "numpy", "pyarrow", "pydantic", "PyYAML")
        },
    }


class ExperimentStore:
    def __init__(self, output: Path, plan: dict, code: dict):
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
        self.path = output / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        write_json(self.path / "plan.json", plan)
        write_json(self.path / "provenance.json", code)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE experiments (id TEXT PRIMARY KEY, status TEXT NOT NULL, "
                "created TEXT NOT NULL, metadata TEXT NOT NULL, "
                "result_sha256 TEXT, error TEXT)"
            )

    def connect(self):
        return sqlite3.connect(self.path / "ledger.sqlite")

    def start(self, metadata: dict) -> str:
        experiment_id = uuid4().hex
        folder = self.path / experiment_id
        folder.mkdir(exist_ok=False)
        write_json(folder / "metadata.json", metadata)
        with self.connect() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?, 'started', ?, ?, NULL, NULL)",
                (
                    experiment_id,
                    datetime.now(UTC).isoformat(),
                    json.dumps(metadata, default=str, allow_nan=False),
                ),
            )
        return experiment_id

    def finish(self, experiment_id: str, document: dict, status: str = "completed") -> None:
        if status not in {"completed", "failed", "skipped"}:
            raise ValueError("Invalid terminal experiment status")
        with self.connect() as db:
            row = db.execute(
                "SELECT status FROM experiments WHERE id=?", (experiment_id,)
            ).fetchone()
            if row != ("started",):
                raise ValueError("Experiment is absent or already finalized")
            path = self.path / experiment_id / "result.json"
            write_json(path, document)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            db.execute(
                "UPDATE experiments SET status=?, result_sha256=?, error=? WHERE id=?",
                (status, digest, document.get("error"), experiment_id),
            )
