"""Fast circuit contract, read-only compatibility and additive migration checks."""

import json
import os
import runpy
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_lab_orchestration.circuit_contracts import CircuitRequest
from trading_lab_orchestration.circuit_fixture import check_pulse_signal_contract
from trading_lab_orchestration.contracts import load_manifest
from trading_lab_orchestration.readonly import ReadOnlyStore
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import file_hash

ROOT = Path(__file__).resolve().parents[2]


def test_acceptance_profile_has_distinct_fingerprint_and_rejects_legacy_target():
    previous = CircuitRequest.model_validate_json(
        (ROOT / "examples/orchestration/circuit46.json").read_text()
    )
    raw = json.loads((ROOT / "examples/orchestration/circuit46_acceptance.json").read_text())
    final = CircuitRequest.model_validate_json(json.dumps(raw))
    assert final.manifest.fingerprint() != previous.manifest.fingerprint()
    raw["implementation"]["target"] = previous.implementation.target
    with pytest.raises(ValidationError):
        CircuitRequest.model_validate_json(json.dumps(raw))


@pytest.mark.skipif(os.name != "nt", reason="Windows acceptance profile")
def test_acceptance_cli_refuses_v6_before_initializing(tmp_path):
    from trading_lab_orchestration.cli import main

    store = Store(tmp_path / "operational.sqlite3")
    with store.transaction() as conn:
        for table in ("attempts", "executions", "manual_repairs"):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN process_identity_json")
        conn.execute("PRAGMA user_version=6")
    original = file_hash(store.path)
    assert (
        main(
            [
                "--db",
                str(store.path),
                "circuit-run",
                str(ROOT / "examples/orchestration/circuit46_acceptance.json"),
                "--artifacts",
                str(tmp_path / "out"),
            ]
        )
        != 0
    )
    assert file_hash(store.path) == original
    assert not (tmp_path / "out").exists()


def test_independent_pulse_oracle_rejects_wrong_signals_even_without_model_tests():
    from quant_lab.config import StrategyConfig

    cls = runpy.run_path(str(ROOT / "tests/fixtures/circuit_pulse_strategy.txt"))[
        "IntegrationCandlePulseV1"
    ]
    strategy = cls(StrategyConfig(name="integration_candle_pulse_v1"))
    assert check_pulse_signal_contract(strategy)["cases"] == 3
    strategy.generate_long_entries = lambda features: [False] * len(features)
    with pytest.raises(ValueError, match="contradict"):
        check_pulse_signal_contract(strategy)


@pytest.mark.parametrize(
    "change",
    [
        {"technical_repairs": 3},
        {"initial_attempts": 2},
        {"audit_mode": "MODEL_ASSISTED"},
        {"telegram": "SEND"},
        {"max_backtests": 7},
    ],
)
def test_fixed_budgets_and_no_model_auditor_or_send(change):
    raw = json.loads((ROOT / "examples/orchestration/circuit46.json").read_text())
    with pytest.raises(ValidationError):
        CircuitRequest.model_validate_json(json.dumps(raw | change))


def test_v5_readonly_and_v6_migration_preserve_previous_dossier(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    registered = store.register(load_manifest(ROOT / "examples/orchestration/manual_valid.json"))
    with store.transaction() as c:
        for table in ("attempts", "executions", "manual_repairs"):
            c.execute("ALTER TABLE " + table + " DROP COLUMN process_identity_json")
        c.execute("DROP TABLE circuits")
        c.execute("PRAGMA user_version=5")
        for number in (1, 2, 3):
            c.execute(
                "INSERT INTO attempts(attempt_id,task_id,number,status,repo,root,workspace,"
                "branch,base_commit,created_at_utc) "
                "VALUES(?,?,?,'FAILED','old','old','old','old','old','old')",
                ("old_" + str(number), registered["task_id"], number),
            )
    before = store.show(registered["task_id"])
    sha = file_hash(store.path)
    with ReadOnlyStore(store.path).snapshot() as readonly:
        assert readonly.show(registered["task_id"]) == before
    assert file_hash(store.path) == sha
    migrated = Store(store.path)
    after = migrated.show(registered["task_id"])
    for attempt in after["attempts"]:
        assert attempt.pop("process_identity_json") is None
    assert after == before
    with migrated.connection() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 7
        assert c.execute("SELECT count(*) FROM circuits").fetchone()[0] == 0
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
