import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from test_lab import lab as lab_fixture

from quant_lab import lab_runner
from quant_lab.lab_cli import main
from quant_lab.lab_resume import RUNNER_TRANSITION, Recovery, compatible_code, select_source
from quant_lab.lab_schema import Experiment


@pytest.fixture(name="lab")
def resume_lab(tmp_path):
    return lab_fixture.__wrapped__(tmp_path)


def freeze(path):
    return {
        str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.rglob("*")
        if p.is_file()
    }


def interrupted(lab, monkeypatch, after=13):
    root, path, raw, _ = lab
    original = lab_runner.evaluate
    calls = []

    def evaluate(*args):
        if len(calls) == after:
            raise OSError(28, "Synthetic disk full")
        calls.append(1)
        return original(*args)

    with monkeypatch.context() as patch:
        patch.setattr(lab_runner, "evaluate", evaluate)
        with pytest.raises(OSError, match="disk full"):
            lab_runner.run(path, Experiment.model_validate(raw), root)
    return select_source(root / "results/example", "latest")


def test_resume_recovers_only_missing_or_corrupt_and_matches_fresh(lab, monkeypatch):
    root, path, raw, _ = lab
    exp = Experiment.model_validate(raw)
    source = interrupted(lab, monkeypatch)
    folders = sorted(source.glob("*/result.json"))
    folders[0].write_text('{"truncated":', encoding="utf-8")
    folders[1].with_name("equity.parquet").write_bytes(b"broken equity")
    before = freeze(source)
    original = lab_runner.evaluate
    calls = []

    def evaluate(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(lab_runner, "evaluate", evaluate)
    audit = lab_runner.run(path, exp, root, resume=source.name, check_only=True)
    assert audit["verified_reusable"] == 11
    assert audit["pending_backtests"] == 7
    assert len(audit["invalid_or_unfinished"]) == 3
    assert not calls
    assert freeze(source) == before
    resumed = lab_runner.run(path, exp, root, resume=source.name)
    assert len(calls) == 7
    assert freeze(source) == before
    reuse = json.loads((resumed / "reuse.json").read_text())
    assert len(reuse["artifacts"]) == 11
    assert len(list(resumed.glob("*/equity.parquet"))) == 7
    with sqlite3.connect(resumed / "ledger.sqlite") as db:
        assert db.execute("SELECT status,count(*) FROM experiments GROUP BY status").fetchall() == [
            ("completed", 18)
        ]
    fresh = lab_runner.run(path, exp, root)
    a = pd.read_csv(resumed / "metrics.csv").drop(columns="backtest_id")
    b = pd.read_csv(fresh / "metrics.csv").drop(columns="backtest_id")
    pd.testing.assert_frame_equal(a, b)
    assert json.loads((resumed / "summary.json").read_text()) == json.loads(
        (fresh / "summary.json").read_text()
    )
    calls.clear()
    assert lab_runner.run(path, exp, root, resume=resumed.name) == resumed
    assert not calls


def test_second_interruption_preserves_lineage(lab, monkeypatch):
    root, path, raw, _ = lab
    exp = Experiment.model_validate(raw)
    source = interrupted(lab, monkeypatch, after=8)
    original = lab_runner.evaluate
    calls = []

    def evaluate(*args):
        if len(calls) == 2:
            raise OSError(28, "second disk full")
        calls.append(1)
        return original(*args)

    with monkeypatch.context() as patch:
        patch.setattr(lab_runner, "evaluate", evaluate)
        with pytest.raises(OSError):
            lab_runner.run(path, exp, root, resume=source.name)
    second = select_source(root / "results/example", "latest")
    before = (freeze(source), freeze(second))
    audit = lab_runner.run(path, exp, root, resume="latest", check_only=True)
    assert audit["verified_reusable"] == 10
    assert audit["pending_backtests"] == 8
    final = lab_runner.run(path, exp, root, resume="latest")
    refs = json.loads((final / "reuse.json").read_text())["artifacts"]
    assert sum(Path(p).parent == source for p in refs.values()) == 8
    assert sum(Path(p).parent == second for p in refs.values()) == 2
    assert (freeze(source), freeze(second)) == before


@pytest.mark.parametrize("change", ["plan", "resolved", "environment", "code"])
def test_resume_rejects_incompatible_inputs(lab, monkeypatch, change):
    root, path, raw, _ = lab
    source = interrupted(lab, monkeypatch, after=1)
    filename = {"plan": "plan.json", "resolved": "resolved.json"}.get(change, "provenance.json")
    target = source / filename
    content = json.loads(target.read_text())
    if change == "plan":
        content["initial_cash"] = 999
    elif change == "resolved":
        content["datasets"][0]["parquet_sha256"] = "wrong"
    elif change == "environment":
        content["dependencies"]["numpy"] = "other"
    else:
        content["files"]["src/quant_lab/strategies/trend_following.py"] = "changed"
    target.write_text(json.dumps(content), encoding="utf-8")
    before = freeze(source)
    with pytest.raises(ValueError, match="mismatch"):
        lab_runner.run(path, Experiment.model_validate(raw), root, resume=source.name)
    assert freeze(source) == before
    assert len(list((root / "results/example").iterdir())) == 1


def test_cli_check_does_not_run_or_write(lab, monkeypatch, capsys):
    root, _, _, _ = lab
    source = interrupted(lab, monkeypatch, after=1)
    before = freeze(source)
    monkeypatch.setattr(lab_runner, "evaluate", lambda *args: pytest.fail("No simulation allowed"))
    assert main(["--root", str(root), "run", "example", "--resume", "--check"]) == 0
    assert json.loads(capsys.readouterr().out)["verified_reusable"] == 1
    assert freeze(source) == before


def test_legacy_transition_is_exact_and_fails_closed():
    path = Path(lab_runner.__file__)
    current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert current_hash not in RUNNER_TRANSITION
    base = {
        "python": "3.13.2",
        "dependencies": {"numpy": "2.2.4"},
        "platform": "Windows-test",
        "files": {"src\\quant_lab\\lab_runner.py": RUNNER_TRANSITION[0]},
    }
    current = copy.deepcopy(base)
    current["files"]["src\\quant_lab\\lab_runner.py"] = RUNNER_TRANSITION[1]
    compatible_code(base, current)
    current["files"]["src\\quant_lab\\lab_runner.py"] = current_hash
    with pytest.raises(ValueError, match="code mismatch"):
        compatible_code(base, current)
    current["files"]["src\\quant_lab\\lab_runner.py"] = "future unreviewed edit"
    with pytest.raises(ValueError, match="code mismatch"):
        compatible_code(base, current)


def test_source_change_during_audit_is_rejected(lab, monkeypatch):
    root, path, raw, _ = lab
    source = interrupted(lab, monkeypatch, after=2)
    from quant_lab import lab_resume

    original = lab_resume.digest

    def digest(target):
        value = original(target)
        if target.name == "equity.parquet":
            with sqlite3.connect(source / "ledger.sqlite") as db:
                db.execute("UPDATE experiments SET error='concurrent modification'")
        return value

    monkeypatch.setattr(lab_resume, "digest", digest)
    with pytest.raises(ValueError, match="Source changed"):
        lab_runner.run(path, Experiment.model_validate(raw), root, resume=source.name)
    assert len(list((root / "results/example").iterdir())) == 1


def test_duplicate_work_identity_is_rejected(lab, monkeypatch):
    import shutil

    root, path, raw, _ = lab
    source = interrupted(lab, monkeypatch, after=1)
    original = next(source.glob("*/result.json"))
    record = "f" * 32
    target = source / record
    shutil.copytree(original.parent, target)
    result = json.loads((target / "result.json").read_text())
    result["metrics"]["backtest_id"] = record
    (target / "result.json").write_text(json.dumps(result), encoding="utf-8")
    with sqlite3.connect(source / "ledger.sqlite") as db:
        row = db.execute(
            "SELECT created,metadata FROM experiments WHERE id=?", (original.parent.name,)
        ).fetchone()
        db.execute(
            "INSERT INTO experiments VALUES (?, 'completed', ?, ?, ?, NULL)",
            (record, *row, hashlib.sha256((target / "result.json").read_bytes()).hexdigest()),
        )
    with pytest.raises(RuntimeError, match="Duplicate"):
        lab_runner.run(path, Experiment.model_validate(raw), root, resume=source.name)


def test_incompatible_wf_rows_cannot_complete():
    recovery = Recovery.__new__(Recovery)
    recovery.records = {"extra": {}}
    recovery.used = set()
    with pytest.raises(ValueError, match="WF winners"):
        recovery.assert_consumed()


def test_latest_uses_creation_timestamp_not_random_uuid(tmp_path):
    earlier = tmp_path / "20260930T000000Z-ffffffffffff"
    later = tmp_path / "20260930T000000Z-000000000000"
    for folder, timestamp in ((earlier, ".100000"), (later, ".900000")):
        folder.mkdir()
        (folder / "run.json").write_text(
            json.dumps({"created_at": "2026-09-30T00:00:00" + timestamp + "+00:00"}),
            encoding="utf-8",
        )
    assert select_source(tmp_path, "latest") == later
