"""Independent sequential A/B driver. Local existing data only; no parameter search."""

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import pandas as pd

from quant_lab.config import StrictModel, load_yaml
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.mtf_data import load_frozen, load_quarters, prior_plan
from quant_lab.mtf_execution import settings
from quant_lab.mtf_series import inventory, run_batch
from quant_lab.new_mtf_features import FAMILIES
from quant_lab.new_mtf_preflight import require_preflight
from quant_lab.new_mtf_reporting import CRITERIA, classify_research, eligibility, report

OUTPUT = Path("results/new_mtf_strategies")


class ProtocolReferences(StrictModel):
    schema_version: int
    reference_plan: str
    reference_sha256: str
    matched_plan: str
    matched_sha256: str


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matrix(architectures=("V1", "V2"), pairs=None):
    pairs = (
        pairs if pairs is not None else [(a, f) for a in ("BTCUSDT", "ETHUSDT") for f in FAMILIES]
    )
    if any(a not in ("BTCUSDT", "ETHUSDT") or f not in FAMILIES for a, f in pairs):
        raise ValueError("Unknown asset/family")
    if any(v not in ("V1", "V2", "V4") for v in architectures):
        raise ValueError("Only V1/V2/V4 are supported")
    return [
        {"asset": a, "family": f, "architecture": v, "mode": "LONG_ONLY", "cohort": "matched"}
        for a, f in pairs
        for v in architectures
    ]


def frozen_protocol(repo):
    config = load_yaml(repo / "configs/profiles/new_mtf_strategies.yaml", ProtocolReferences)
    if config.schema_version != 1:
        raise ValueError("Unsupported protocol schema")
    documents = []
    for path, digest in (
        (config.reference_plan, config.reference_sha256),
        (config.matched_plan, config.matched_sha256),
    ):
        target = repo / path
        if sha(target) != digest:
            raise ValueError(f"Frozen reference changed: {path}")
        documents.append(read_json(target))
    reference, matched = documents
    previous = prior_plan()
    if any(previous[k] != reference[k] or matched[k] != reference[k] for k in ("splits", "folds")):
        raise ValueError("Historical partitions/folds differ")
    if len(reference["folds"]) != 22 or len(reference["matched_audit"]["excluded_days"]) != 18:
        raise ValueError("Expected frozen 22 folds and 18 excluded days")
    if settings().model_dump(mode="json") != reference["settings"] or settings().capital != 10000:
        raise ValueError("Inherited costs/risk/capital/settings changed")
    return reference, matched, config.model_dump(mode="json")


def matched_data(reference, matched):
    data, audit = load_frozen()
    # The recorded audit contains funding identities as well as contract/mark identities.
    if audit != reference["original_audit"]:
        raise ValueError("Frozen source/funding audit changed")
    quarters = load_quarters(data, matched=True)
    if quarters != reference["matched_audit"]:
        raise ValueError("Quarter sources or the exact 18 exclusions changed")

    def identity(rows):
        return {(r["asset"], r["timeframe"]): r["hash"] for r in rows}

    if identity(inventory(data)) != identity(matched["used_data"]):
        raise ValueError("Matched cohort content changed")
    return data


def seal(folder):
    write_json(
        folder / "artifact_manifest.json",
        {
            str(p.relative_to(folder)): sha(p)
            for p in sorted(folder.rglob("*"))
            if p.is_file() and p != folder / "artifact_manifest.json"
        },
    )


def verify_artifacts(folder):
    manifest = read_json(folder / "artifact_manifest.json")
    for name, digest in manifest.items():
        target = (folder / name).resolve()
        if not target.is_relative_to(folder.resolve()) or sha(target) != digest:
            raise ValueError(f"Source run artifact changed: {name}")
    if not {"plan.json", "provenance.json", "verification.json", "phase.json"} <= set(manifest):
        raise ValueError("Incomplete source run manifest")


def phase_a_source(repo, source, code):
    if source is None:
        candidates = []
        for path in sorted((repo / OUTPUT).glob("*/phase.json")):
            if read_json(path).get("phase") == "a":
                candidates.append(path.parent)
        if not candidates:
            raise ValueError("No completed phase A; execute --phase a first")
        source = candidates[-1]
    source = (repo / source).resolve()
    verify_artifacts(source)
    if read_json(source / "phase.json").get("phase") != "a":
        raise ValueError("Phase B requires a phase A source")
    if read_json(source / "provenance.json")["code_sha256"] != code["code_sha256"]:
        raise ValueError("Phase A source code differs; do not mix experiments")
    if read_json(source / "verification.json")["status"] != "completed":
        raise ValueError("Phase A incomplete")
    child = (source / read_json(source / "phase.json")["batch"]).resolve()
    if not child.is_relative_to(source):
        raise ValueError("Batch must belong to source run")
    table = pd.read_csv(child / "results.csv")
    classified = classify_research(table)
    gate = eligibility(classified)
    if gate != read_json(child / "v4_eligibility.json"):
        raise ValueError("Eligibility does not match phase A results")
    return source, classified, gate


def run_phase(repo, phase, code, preflight, reference, matched, references, source=None):
    preceding, gate, parent_a = None, None, None
    configs = matrix()
    if phase == "b":
        parent_a, preceding, gate = phase_a_source(repo, source, code)
        configs = matrix(("V4",), [(r["asset"], r["family"]) for r in gate["eligible"]])
    protocol = {k: reference[k] for k in ("splits", "folds", "settings", "matched_audit")}
    protocol |= {
        "phase": phase,
        "references": references,
        "research_criteria": CRITERIA,
        "preflight": preflight,
        "matrix": configs,
        "phase_a_source": str(parent_a) if parent_a else None,
        "rules": "docs/new-mtf-strategies.md; fixed parameters, LONG_ONLY, matched cohort",
    }
    data = matched_data(reference, matched) if configs else None
    parent = ExperimentStore(repo / OUTPUT, protocol, code)
    for name in code["files"]:
        target = parent.path / "source_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, target)
    shutil.copyfile(repo / "docs/new-mtf-strategies.md", parent.path / "protocol.md")
    write_json(parent.path / "config.json", configs)
    batch = None
    if configs:
        batch, _ = run_batch(
            repo, str(parent.path / ("phase_" + phase)), data, configs, protocol, code
        )
        report(batch, phase, preceding)
        if phase == "b":
            write_json(batch / "v4_eligibility.json", gate)
        seal(batch)
        (parent.path / "summary.md").write_text(
            (batch / "summary.md").read_text(encoding="utf-8"), encoding="utf-8"
        )
    else:
        write_json(parent.path / "v4_eligibility.json", gate)
        (parent.path / "summary.md").write_text(
            "# Fase B omitida\n\nNinguna V1/V2 obtuvo RESEARCH_PASS. Cero ejecuciones V4.\n",
            encoding="utf-8",
        )
    if provenance(repo)["code_sha256"] != code["code_sha256"]:
        raise ValueError("Code changed during execution; run is not completed")
    write_json(
        parent.path / "phase.json",
        {"phase": phase, "batch": str(batch.relative_to(parent.path)) if batch else None},
    )
    write_json(
        parent.path / "verification.json",
        {
            "status": "completed",
            "code_unchanged": True,
            "configurations": len(configs),
            "v4_skipped": not configs,
        },
    )
    seal(parent.path)
    print("COMPLETE", parent.path, flush=True)
    return parent.path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--phase", choices=("a", "b", "analyze"))
    choice.add_argument("--all", action="store_true")
    parser.add_argument(
        "--from-run", type=Path, help="Explicit phase A parent; otherwise latest completed A"
    )
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    os.chdir(repo)  # Legacy data helpers intentionally resolve paths from the repo root.
    try:
        code = provenance(repo)
        preflight = require_preflight(repo, code)
        if args.phase == "analyze":
            source, classified, gate = phase_a_source(repo, args.from_run, code)
            print(source)
            print(
                classified[
                    [
                        "asset",
                        "family",
                        "architecture",
                        "research_classification",
                        "failed_criteria",
                    ]
                ].to_string(index=False)
            )
            print(json.dumps(gate, indent=2))
            return 0
        if args.from_run and (args.all or args.phase == "a"):
            raise ValueError("--from-run only applies to phase b/analyze")
        reference, matched, references = frozen_protocol(repo)
        source = args.from_run
        if args.all or args.phase == "a":
            source = run_phase(repo, "a", code, preflight, reference, matched, references)
        if args.all or args.phase == "b":
            run_phase(repo, "b", code, preflight, reference, matched, references, source)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
