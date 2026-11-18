"""Check the frozen bundle or run a synthetic, temporary 5.5B acceptance only."""

import argparse
import json
from pathlib import Path

from trading_lab_orchestration.historical_pilot import authorization_proposal, run_synthetic
from trading_lab_orchestration.historical_pilot_contract import (
    BlockedDataset,
    frozen_plan,
    preflight_dataset,
)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(required=True, dest="command")
    data = sub.add_parser("check-data")
    data.add_argument("--data-repo", type=Path, required=True)
    proposal = sub.add_parser("proposal")
    proposal.add_argument("--data-repo", type=Path, required=True)
    proposal.add_argument("--coordinator-db", type=Path, required=True)
    synthetic = sub.add_parser("synthetic")
    synthetic.add_argument("--registry", type=Path, required=True)
    synthetic.add_argument("--scratch", type=Path, required=True)
    args = cli.parse_args()
    try:
        if args.command == "check-data":
            _, answer = preflight_dataset(
                args.data_repo, frozen_plan(Path(__file__).resolve().parents[1]).cases
            )
        elif args.command == "proposal":
            permit, job, evidence = authorization_proposal(args.data_repo, args.coordinator_db)
            answer = {
                "status": "PROPOSAL_ONLY",
                "permit": permit.model_dump(mode="json"),
                "job": job.model_dump(mode="json"),
                "preflight": evidence,
            }
        else:
            result = run_synthetic(args.registry, args.scratch)
            answer = {key: result[key] for key in ("status", "audit", "stdout_sha256")}
    except BlockedDataset as exc:
        print(json.dumps({"status": "BLOCKED_DATASET", "reason": str(exc)}))
        return 2
    print(json.dumps(answer, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
