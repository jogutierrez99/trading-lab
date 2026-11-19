"""Schema 1. All scientific records and events are append-only."""

APPLICATION_ID = 0x544C4331
VERSION = 1
REFERENCES = {
    "strategies": {},
    "versions": {"strategy_id": "strategies"},
    "experiments": {"version_id": "versions"},
    "runs": {"experiment_id": "experiments"},
    "case_results": {"run_id": "runs"},
    "artifacts": {"run_id": "runs"},
    "research_decisions": {"strategy_id": "strategies", "version_id": "versions", "run_id": "runs"},
}


def ddl():
    statements = []
    for table, refs in REFERENCES.items():
        columns = [
            "id TEXT PRIMARY KEY",
            "payload TEXT NOT NULL",
            "sha256 TEXT NOT NULL",
            "registered_at_utc TEXT NOT NULL",
        ]
        columns.extend(
            f"{key} TEXT "
            + ("" if table == "research_decisions" and key != "strategy_id" else "NOT NULL ")
            + f"REFERENCES {parent}(id)"
            for key, parent in refs.items()
        )
        statements.append(f"CREATE TABLE {table} ({', '.join(columns)})")
        statements.append(f"CREATE UNIQUE INDEX {table}_content ON {table}(sha256)")
    for table in ("versions", "experiments"):
        statements.append(
            f"CREATE UNIQUE INDEX {table}_definition ON {table}(json_remove(payload,'$.id'))"
        )
    statements.append(
        "CREATE UNIQUE INDEX case_identity ON case_results"
        "(run_id,json_extract(payload,'$.segment'),json_extract(payload,'$.scenario'))"
    )
    statements.append(
        "CREATE TABLE catalog_events (event_id INTEGER PRIMARY KEY, kind TEXT NOT NULL,"
        " source TEXT NOT NULL, fingerprint TEXT NOT NULL, occurred_at_utc TEXT NOT NULL)"
    )
    for table in (*REFERENCES, "catalog_events"):
        for op in ("UPDATE", "DELETE"):
            statements.append(
                f"CREATE TRIGGER {table}_no_{op.lower()} BEFORE {op} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable catalogue record'); END"
            )
    return statements
