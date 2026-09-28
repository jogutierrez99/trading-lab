"""Classify existing phase A metrics into a new immutable companion report."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_lab.experiments import provenance, write_json
from quant_lab.new_mtf_reporting import CRITERIA, classify_research, eligibility
from quant_lab.new_mtf_watchlist import MINIMUMS, write_classification


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_metrics(source):
    """Validate only classification inputs; no scan of thousands of trade artifacts."""
    manifest = read(source / "artifact_manifest.json")
    verified = {}

    def checked(relative):
        path = (source / relative).resolve()
        if not path.is_relative_to(source.resolve()):
            raise ValueError("Source path escapes run")
        key = str(path.relative_to(source.resolve()))
        expected = manifest.get(key)
        if expected is None or digest(path) != expected:
            raise ValueError(f"Classification input missing or changed: {key}")
        verified[key] = expected
        return path

    phase = read(checked("phase.json"))
    verification = read(checked("verification.json"))
    plan = read(checked("plan.json"))
    if phase.get("phase") != "a" or verification.get("status") != "completed":
        raise ValueError("Source must be a completed phase A")
    if plan.get("research_criteria") != CRITERIA:
        raise ValueError("Source RESEARCH_PASS thresholds differ from frozen criteria")
    child = Path(phase["batch"])
    if read(checked(child / "verification.json")).get("status") != "completed":
        raise ValueError("Phase A batch incomplete")
    table = pd.read_csv(checked(child / "results.csv"))
    classified = classify_research(table)
    gate = eligibility(classified)
    if gate != read(checked(child / "v4_eligibility.json")):
        raise ValueError("Original RESEARCH_PASS eligibility differs; refusing reclassification")
    summary = checked("summary.md").read_text(encoding="utf-8")
    source_code = read(checked("provenance.json"))["code_sha256"]
    return classified, verified, summary, source_code


def select_source(repo, run_id=None):
    root = repo / "results/new_mtf_strategies"
    if run_id is not None:
        if Path(run_id).name != run_id or run_id in (".", ".."):
            raise ValueError("--run must be a run_id, not a path")
        source = root / run_id
        return source, source_metrics(source), []
    skipped = []
    for source in sorted(root.glob("*"), reverse=True):
        if not source.is_dir():
            continue
        try:
            if read(source / "plan.json").get("phase") != "a":
                continue
            return source, source_metrics(source), skipped
        except (OSError, ValueError, KeyError, TypeError) as exc:
            skipped.append({"run_id": source.name, "reason": str(exc)})
    raise ValueError(f"No valid completed phase A found; rejected: {skipped}")


def classify_existing(repo: Path, run_id=None):
    source, (classified, verified, original_summary, source_code), skipped = select_source(
        repo, run_id
    )
    report_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    output = repo / "reports/new_mtf_classification" / source.name / report_id
    output.mkdir(parents=True, exist_ok=False)
    extension = write_classification(output, classified)
    (output / "summary.md").write_text(
        "# Classification supplement\n\n"
        f"Source: {source}\n\nOriginal historical summary follows unchanged.\n\n"
        + original_summary
        + "\n\n"
        + extension,
        encoding="utf-8",
    )
    write_json(output / "provenance.json", provenance(repo))
    unchanged = all(digest(source / name) == expected for name, expected in verified.items())
    if not unchanged:
        raise ValueError("Source changed during classification")
    write_json(
        output / "verification.json",
        {
            "status": "completed",
            "source_run": str(source),
            "source_code_sha256": source_code,
            "source_inputs": verified,
            "source_unchanged": True,
            "backtests_executed": 0,
            "research_pass_unchanged": True,
            "v4_eligibility_unchanged": True,
            "research_pass_criteria": CRITERIA,
            "near_pass_minimums": MINIMUMS,
            "maximum_failed_pass_criteria": 2,
            "skipped_invalid_runs": skipped,
            "validation_scope": "Classification inputs only; trading artifacts were not re-audited",
        },
    )
    write_json(
        output / "artifact_manifest.json",
        {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
    print("CLASSIFIED", output, flush=True)
    print(
        classified[
            [
                "asset",
                "family",
                "architecture",
                "research_classification",
                "failed_pass_criteria_count",
            ]
        ].to_string(index=False)
    )
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", help="Phase A run_id; default: latest valid completed A")
    args = parser.parse_args(argv)
    try:
        classify_existing(Path(__file__).resolve().parents[2], args.run)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    return 0
