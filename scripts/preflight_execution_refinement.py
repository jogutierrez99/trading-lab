"""Bind required technical checks to the exact confirmation code."""

import json
import subprocess
import sys
from pathlib import Path

from quant_lab.experiments import provenance

if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[1]
    checks = {}
    for args in (
        ["pytest", "-q"],
        ["ruff", "check", "."],
        ["ruff", "format", "--check", "."],
        ["pip", "check"],
    ):
        result = subprocess.run(
            [sys.executable, "-m", *args], cwd=repo, text=True, capture_output=True
        )
        checks[" ".join(args)] = {
            "exit_code": result.returncode,
            "output": result.stdout + result.stderr,
        }
        print(" ".join(args), result.returncode, flush=True)
    target = repo / "reports/batch_execution_refinement/preflight.json"
    target.write_text(
        json.dumps({"code_sha256": provenance(repo)["code_sha256"], "checks": checks}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    sys.exit(int(any(v["exit_code"] for v in checks.values())))
