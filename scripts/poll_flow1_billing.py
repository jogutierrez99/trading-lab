"""One persistent billing tick, suitable for a disabled Windows scheduled task."""

import argparse
import json
import os

from trading_lab_orchestration.audit_openai import load_openai_key
from trading_lab_orchestration.billing_worker import load_config, tick


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    previous = os.environ.get("OPENAI_ADMIN_KEY")
    previous_ledger = os.environ.get("TRADING_LAB_GLOBAL_API_DB")
    try:
        config = load_config(args.config)
        if previous_ledger is None:
            os.environ["TRADING_LAB_GLOBAL_API_DB"] = config["ledger"]
        key = previous or load_openai_key(config["secrets_env_file"], "OPENAI_ADMIN_KEY")
        if key:
            os.environ["OPENAI_ADMIN_KEY"] = key
        result = tick(config)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2
    finally:
        if previous is None:
            os.environ.pop("OPENAI_ADMIN_KEY", None)
        else:
            os.environ["OPENAI_ADMIN_KEY"] = previous
        if previous_ledger is None:
            os.environ.pop("TRADING_LAB_GLOBAL_API_DB", None)


if __name__ == "__main__":
    raise SystemExit(main())
