"""Record actual mandatory checks bound to the source hash before any study run."""

import json
import subprocess
import sys
from pathlib import Path

from quant_lab.cross_market_study import NAME, protect
from quant_lab.experiments import provenance

if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[1]
    root = repo / "reports" / NAME
    root.mkdir(parents=True, exist_ok=True)
    record = {"code_sha256": provenance(repo)["code_sha256"], "protected_previous": protect(repo)}
    for command in ("pytest -q", "ruff check .", "ruff format --check .", "pip check"):
        result = subprocess.run(
            [sys.executable, "-m", *command.split()], cwd=repo, capture_output=True, text=True
        )
        record[command] = {"exit_code": result.returncode, "output": result.stdout + result.stderr}
        print(command, result.returncode, result.stdout[-500:], flush=True)
    if provenance(repo)["code_sha256"] != record["code_sha256"]:
        raise RuntimeError("Source changed during verification")
    (root / "preflight.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    if any(
        record[c]["exit_code"]
        for c in ("pytest -q", "ruff check .", "ruff format --check .", "pip check")
    ):
        raise SystemExit(1)
