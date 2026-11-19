"""Manual catalogue commands. Imports are explicit and queries are read-only."""

import argparse
import json
import sqlite3

from .comparison import compare
from .ingestion import preview
from .models import Bundle
from .service import discover, joined_cases
from .store import Conflict, Store, default_path
from .verification import BlockedSource, read


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=default_path())
    parser.add_argument("--format", choices=("json", "text"), default="json")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "discover", "list", "stats", "verify", "migrate"):
        commands.add_parser(name)
    commands.choices["verify"].add_argument("--sources", action="store_true")
    commands.choices["verify"].add_argument("--record-event", action="store_true")
    for name in ("show", "versions", "experiments", "runs", "artifacts", "decisions"):
        command = commands.add_parser(name)
        command.add_argument("--id")
    register = commands.add_parser("register")
    register.add_argument("bundle", help="Reviewed declarative Bundle 1.0 JSON")
    for name in ("import-preview", "import-confirmed"):
        command = commands.add_parser(name)
        command.add_argument("--source", required=True)
        command.add_argument("--sealed-source", required=True)
        command.add_argument("--receipt-sha256", required=True)
    comparison = commands.add_parser("compare")
    for key in (
        "asset",
        "family",
        "timeframe",
        "version_id",
        "period_start_utc",
        "period_end_utc",
        "engine",
        "market_type",
        "scenario",
        "segment",
        "research_state",
        "verdict",
    ):
        comparison.add_argument("--" + key.replace("_", "-"))
    args = parser.parse_args(argv)
    code = 0
    try:
        if args.command.startswith("import-"):
            bundle = preview(args.source, args.sealed_source, args.receipt_sha256)
            if args.command == "import-preview":
                result = {"status": "VALIDATED_DRY_RUN", "bundle": bundle.model_dump(mode="json")}
            else:
                result = Store(args.db).ingest(bundle, args.source)
        else:
            store = Store(args.db)
            if args.command == "init":
                store.init()
                result = {"status": "OK", "schema": 1}
            elif args.command == "migrate":
                result = {"schema": store.migrate()}
            elif args.command == "discover":
                result = store.ingest(discover(), "StrategyRegistry.catalogue")
            elif args.command == "register":
                result = store.ingest(Bundle.model_validate_json(read(args.bundle)), args.bundle)
            elif args.command == "verify":
                result = store.verify()
                if args.sources:
                    from .verification import sha

                    for artifact in store.records("artifacts"):
                        if sha(read(artifact["reference"])) != artifact["sha256"]:
                            raise BlockedSource("Referenced artifact changed")
                    result["sources"] = "HASH_VERIFIED"
                if args.record_event:
                    store.record_verification(result)
            elif args.command == "compare":
                keys = vars(args).copy()
                for key in ("db", "format", "command"):
                    keys.pop(key)
                result = compare(joined_cases(store, **keys))
            elif args.command == "stats":
                result = {
                    table: len(store.records(table))
                    for table in (
                        "strategies",
                        "versions",
                        "experiments",
                        "runs",
                        "case_results",
                        "artifacts",
                        "research_decisions",
                    )
                }
            else:
                table = {
                    "list": "strategies",
                    "show": "strategies",
                    "decisions": "research_decisions",
                }.get(args.command, args.command)
                result = store.records(table)
                identity = getattr(args, "id", None)
                if identity:
                    result = [
                        r
                        for r in result
                        if r["id"] == identity
                        or r.get("strategy_id") == identity
                        or r.get("version_id") == identity
                        or r.get("experiment_id") == identity
                        or r.get("run_id") == identity
                    ]
                    if not result:
                        raise FileNotFoundError("Catalogue identity was not found")
    except FileNotFoundError:
        result, code = {"status": "NOT_FOUND"}, 3
    except Conflict as exc:
        result, code = {"status": "CONFLICT", "reason": str(exc)}, 4
    except BlockedSource as exc:
        result, code = {"status": "BLOCKED_SOURCE", "reason": str(exc)}, 5
    except (ValueError, sqlite3.Error, OSError) as exc:
        result, code = {"status": "INTEGRITY_ERROR", "reason": str(exc)}, 6
    print(json.dumps(result, indent=2 if args.format == "text" else None, allow_nan=False))
    return code
