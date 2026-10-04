import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from test_lab import lab as lab_fixture

from quant_lab.lab_classification import classify
from quant_lab.lab_cli import main
from quant_lab.lab_comparison import compare
from quant_lab.lab_evidence import completed_run, recorded_data_valid
from quant_lab.lab_publish import publish, publish_comparison
from quant_lab.lab_runner import run
from quant_lab.lab_schema import Experiment

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "configs/research/lab_classification_v1.yaml"


@pytest.fixture
def saved(tmp_path):
    root, path, raw, _ = lab_fixture.__wrapped__(tmp_path)
    exp = Experiment.model_validate(raw)
    source = run(path, exp, root)
    return root, path, exp, source


def fingerprint(path):
    return {
        str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.rglob("*")
        if p.is_file()
    }


def test_classify_and_publish_without_simulation_or_source_mutation(saved, monkeypatch):
    root, _, _, source = saved
    before = fingerprint(source)
    monkeypatch.setattr("quant_lab.lab_runner.evaluate", lambda *a: pytest.fail("No rerun"))
    assert recorded_data_valid(completed_run(root, "example"))
    output = classify(root, "example", POLICY)
    document = json.loads((output / "classification.json").read_text())
    assert document["classification_schema_version"] == 1
    assert len(document["candidates"]) == 2
    result = publish(root, "example")
    dest = Path(result["publication_directory"])
    assert dest.is_relative_to(root / "research_results")
    assert "classification.json" in result["published"]
    assert not list(dest.rglob("*.parquet")) and not list(dest.rglob("*.sqlite"))
    assert not (dest / "metrics.csv").exists()
    metadata = json.loads((dest / "metadata.json").read_text())
    assert metadata["run_id"] == source.name
    assert metadata["source"].startswith("results/")
    assert str(root) not in (dest / "metadata.json").read_text()
    for name, digest in metadata["artifacts_sha256"].items():
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == digest
    compact = pd.read_csv(dest / "metrics_compact.csv")
    assert not compact.period.str.match(r"wf_\d+_train").any()
    assert fingerprint(source) == before
    with pytest.raises(FileExistsError):
        publish(root, "example")


def test_publication_limit_is_explicit_and_failures_leave_source_unchanged(saved):
    root, _, _, source = saved
    (source / "ai_summary.md").write_text("x" * 40000)
    before = fingerprint(source)
    result = publish(root, "example", max_bytes=20000)
    assert result["skipped"]["ai_summary.md"]["reason"] == "size_limit"
    assert not (Path(result["publication_directory"]) / "ai_summary.md").exists()
    assert fingerprint(source) == before


def test_reject_incomplete_and_changed_source(saved):
    root, _, _, source = saved
    classify(root, "example", POLICY)
    p = source / "metrics.csv"
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Stale classification"):
        publish(root, "example")
    (source / "outcome.json").write_text('{"status":"FAILED"}')
    with pytest.raises(ValueError, match="COMPLETE"):
        classify(root, "example", POLICY)


def test_compare_shows_classification_and_publishes_legacy_comparison(saved, monkeypatch):
    root, path, exp, _ = saved
    second = exp.model_copy(update={"experiment_id": "second"})
    run(path, second, root)
    classify(root, "example", POLICY)
    monkeypatch.setattr("quant_lab.lab_runner.evaluate", lambda *a: pytest.fail("No rerun"))
    directory = compare(root, ["example", "second"])
    source = json.loads((directory / "sources.json").read_text())
    assert source[0]["research_classification"]["counts"]
    assert source[1]["research_classification"] is None
    table = pd.read_csv(directory / "comparison.csv")
    assert "legacy_PASS" in table and "PASS" in table
    original = (directory / "comparison.csv").read_bytes()
    (directory / "comparison.csv").write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="artifact hash"):
        publish_comparison(root, directory.name)
    (directory / "comparison.csv").write_bytes(original)
    # Older comparisons had no terminal marker, but did have a full artifact set.
    (directory / "outcome.json").unlink()
    before = fingerprint(directory)
    result = publish_comparison(root, directory.name)
    assert "sources.json" in result["published"]
    assert fingerprint(directory) == before
    assert main(["--root", str(root), "classify", "example", "--policy", str(POLICY)]) == 0
    assert main(["--root", str(root), "report", "example"]) == 0


def test_publisher_never_copies_unlisted_files(saved):
    root, _, _, source = saved
    (source / "secret.env").write_text("do not publish")
    (source / "dataset.parquet").write_bytes(b"do not publish")
    result = publish(root, source.name)
    assert set(result["published"]) <= {
        "ai_summary.md",
        "summary.md",
        "leaderboard.csv",
        "metrics_compact.csv",
        "metadata.json",
    }
