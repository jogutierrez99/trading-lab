"""Review one GitHub intake checkpoint without preparing or launching anything."""

import argparse
import json
import os
import sqlite3
from pathlib import Path

from trading_lab_orchestration.contracts import _unique, canonical
from trading_lab_orchestration.github_review import ReviewAuthorization, diagnose_issue
from trading_lab_orchestration.implementation_contracts import ImplementationPlan


def load(path, model):
    if path is None:
        return None
    raw = path.read_text(encoding="utf-8-sig")
    return model.model_validate_json(canonical(json.loads(raw, object_pairs_hook=_unique)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--authorization", type=Path)
    args = parser.parse_args()
    ledger = os.environ.get("TRADING_LAB_GLOBAL_API_DB")
    try:
        result = diagnose_issue(
            args.db,
            args.issue,
            ledger=Path(ledger) if ledger else None,
            task_id=args.task_id,
            plan=load(args.plan, ImplementationPlan),
            approval=load(args.authorization, ReviewAuthorization),
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        # Local plan/authorization contents are not needed to explain a malformed input.
        result = {"status": "REJECTED", "reason": type(exc).__name__, "execution_enabled": False}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 2 if result["status"] == "REJECTED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
