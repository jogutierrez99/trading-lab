"""Bounded allowlist publication to the Git research notebook; never commit or push."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quant_lab.lab_classification import latest_classification
from quant_lab.lab_evidence import assert_unchanged, completed_run, portable, read_json, sha256

COMPACT_COLUMNS = (
    "configuration_id",
    "candidate_id",
    "symbol",
    "timeframe",
    "mode",
    "parameters",
    "period",
    "scenario",
    "start",
    "end",
    "closed_trades",
    "strategy",
    "strategy_version",
    "win_rate_pct",
    "return_pct",
    "profit_factor",
    "sharpe",
    "expectancy",
    "max_drawdown_pct",
    "fees_paid",
    "average_win",
    "average_loss",
    "average_trade",
    "average_close_exposure_pct",
    "average_holding_hours",
    "slippage_cost_closed_trades",
    "spread_cost_closed_trades",
    "gross_price_pnl",
    "gross_return_pct",
    "total_modeled_costs",
    "cost_gross_profit_ratio",
    "top_5_profit_share_pct",
    "long_setup_count",
    "short_setup_count",
    "setups_traded_pct",
    "midpoint_exit_pct",
    "regime_exit_losses",
    "funding_pnl",
    "funding_note",
    "filter_status",
    "research_classification",
)


def family(strategy: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", strategy):
        raise ValueError("Invalid strategy publication identity")
    return re.sub(r"_v[0-9]+$", "", strategy)


def clean_text(text: str, root: Path) -> str:
    for prefix in (
        str(root.resolve()).replace("\\", "\\\\"),
        str(root.resolve()),
        root.resolve().as_posix(),
    ):
        text = text.replace(prefix + "\\", "").replace(prefix + "/", "").replace(prefix, "<repo>")
    return text


def clean_json(value, root: Path):
    if isinstance(value, dict):
        return {k: clean_json(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_json(v, root) for v in value]
    if isinstance(value, str):
        text = clean_text(value, root)
        if re.match(r"^[A-Za-z]:[\\/]", text):
            return "unknown_external_local_path"
        return text.replace("\\", "/")
    return value


def json_bytes(value, root: Path) -> bytes:
    return (json.dumps(clean_json(value, root), indent=2, allow_nan=False) + "\n").encode()


def publish_files(
    directory: Path, payloads: dict[str, bytes], metadata: dict, root: Path, max_bytes: int
) -> dict:
    if max_bytes < 1:
        raise ValueError("Publication file limit must be positive")
    accepted, skipped = {}, {}
    for name, data in payloads.items():
        if len(data) > max_bytes:
            skipped[name] = {"bytes": len(data), "limit": max_bytes, "reason": "size_limit"}
        else:
            accepted[name] = data
    metadata = metadata | {
        "publication_schema_version": 1,
        "published_at": datetime.now(UTC).isoformat(),
        "max_file_bytes": max_bytes,
        "skipped": skipped,
        "artifacts_sha256": {
            name: hashlib.sha256(data).hexdigest() for name, data in accepted.items()
        },
        "note": "Compact research notebook, not full backtest storage. "
        "Legacy PASS is not paper eligibility. No Git commit/push performed.",
    }
    serialized = json_bytes(metadata, root)
    if len(serialized) > max_bytes:
        raise ValueError(
            "metadata.json exceeds size limit; nothing published (increase --max-file-mb)"
        )
    directory.mkdir(parents=True, exist_ok=False)
    for name, data in accepted.items():
        with (directory / name).open("xb") as handle:
            handle.write(data)
    # Written last: a partial directory is never a completed publication.
    with (directory / "metadata.json").open("xb") as handle:
        handle.write(serialized)
    return {
        "publication_directory": str(directory),
        "published": [*accepted, "metadata.json"],
        "skipped": skipped,
    }


def run_metadata(evidence: dict, root: Path, classification: dict | None) -> dict:
    plan, resolved, code = evidence["plan"], evidence["resolved"], evidence["provenance"]
    return {
        "experiment": evidence["header"]["experiment_id"],
        "run_id": evidence["header"]["run_id"],
        "strategy": plan["strategy"]["id"],
        "strategy_version": resolved["strategy"].get("version"),
        "code_hash": code.get("code_sha256"),
        "git_commit": code.get("git_revision"),
        "environment": {k: code.get(k) for k in ("python", "platform", "dependencies")},
        "datasets": [
            {
                k: d.get(k)
                for k in ("symbol", "timeframe", "dataset_id", "parquet_sha256", "start", "end")
            }
            for d in resolved.get("datasets", [])
        ],
        "markets": [
            {k: m[k] for k in ("symbol", "timeframe", "warmup_bars")} for m in plan["markets"]
        ],
        "execution_assumptions": resolved.get("execution"),
        "cost_assumptions": {
            "base": resolved["app"]["costs"],
            "stress": plan.get("validation", plan.get("historical_challenge", {})).get(
                "cost_stress"
            ),
        },
        "validation": plan.get("validation"),
        "historical_challenge": plan.get("historical_challenge"),
        "selection_context": plan.get(
            "selection_context",
            "unknown; retrospective classification is not independent validation",
        ),
        "candidates": resolved.get("candidates"),
        "classification": {
            "counts": classification["counts"],
            "policy": classification["policy"],
            "scope": classification["scope"],
        }
        if classification
        else None,
        "source": portable(evidence["path"], root),
        "source_sha256": evidence["source_sha256"],
    }


def publish(root: Path, identifier: str, max_bytes: int = 5_000_000) -> dict:
    evidence = completed_run(root, identifier)
    path, plan, frame = evidence["path"], evidence["plan"], evidence["metrics"]
    supplementary = latest_classification(root, evidence)
    document = supplementary[1] if supplementary else None
    payloads = {}
    source_hashes = dict(evidence["source_sha256"])
    for name in ("ai_summary.md", "summary.md", "leaderboard.csv"):
        file = path / name
        if file.exists():
            source_hashes[name] = sha256(file)
            payloads[name] = clean_text(file.read_text(encoding="utf-8"), root).encode()
    if supplementary:
        class_path, document = supplementary
        payloads["classification.json"] = json_bytes(document, root)
        payloads["classification.md"] = clean_text(
            class_path.with_suffix(".md").read_text(encoding="utf-8"), root
        ).encode()
        if document.get("fixed_robustness_source"):
            from quant_lab.lab_robustness import latest_robustness

            fixed = latest_robustness(root, evidence)
            payloads["robustness.json"] = json_bytes(fixed[1], root)
            payloads["robustness_summary.md"] = clean_text(
                (fixed[0].parent / "summary.md").read_text(encoding="utf-8"), root
            ).encode()
            payloads["robustness_metrics_compact.csv"] = (
                pd.DataFrame(fixed[2], columns=frame.columns)[
                    [c for c in COMPACT_COLUMNS if c in frame]
                ]
                .to_csv(index=False)
                .encode()
            )
    if evidence["header"]["kind"] == "lab_challenge_v1":
        compact = frame.copy()
    else:
        # Selection of compact examples uses TRAIN-ranked source order only.
        board = pd.read_csv(path / "leaderboard.csv")
        identities = board.head(plan["ranking"]["top_n"]).configuration_id
        selected_wf = frame.period.str.match(r"^wf_\d+_test$")
        compact = frame[
            (
                frame.configuration_id.isin(identities)
                & frame.period.isin(["train", "validation", "test"])
            )
            | selected_wf
            | frame.period.isin(plan.get("diagnostic_periods", {}))
        ].copy()
    if document:
        labels = {
            c["configuration_id"]: c["research_classification"] for c in document["candidates"]
        }
        compact["research_classification"] = compact.configuration_id.map(labels)
    columns = [name for name in COMPACT_COLUMNS if name in compact]
    payloads["metrics_compact.csv"] = compact[columns].to_csv(index=False).encode()
    metadata = run_metadata(evidence, root, document) | {
        "source_sha256": source_hashes,
        "compact_selection": "All challenge rows, or TRAIN-ranked top_n main rows "
        "plus all selected WF TEST rows and predefined diagnostic periods. No TEST ranking.",
        "compact_rows": len(compact),
        "source_rows": len(frame),
        "classification_source": portable(supplementary[0], root) if supplementary else None,
        "classification_sha256": sha256(supplementary[0]) if supplementary else None,
    }
    assert_unchanged(evidence | {"source_sha256": source_hashes})
    destination = (
        root
        / "research_results"
        / family(plan["strategy"]["id"])
        / plan["experiment_id"]
        / path.name
    )
    return publish_files(destination, payloads, metadata, root, max_bytes)


def publish_comparison(root: Path, identifier: str, max_bytes: int = 5_000_000) -> dict:
    base = root / "reports/lab-comparison"
    if identifier == "latest":
        paths = sorted(base.glob("*/sources.json"))
        if not paths:
            raise ValueError("No comparisons available")
        identifier = paths[-1].parent.name
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", identifier):
        raise ValueError("Expected comparison ID or latest")
    path = base / identifier
    names = (
        "ai_summary.md",
        "summary.md",
        "comparison.csv",
        "sources.json",
        "train_ranked_examples.json",
    )
    # Old comparisons predate outcome.json: require their complete file set and
    # verify each pinned COMPLETE source + recorded source hashes, never infer from mtime.
    for name in (*names, "comparison.json"):
        if not (path / name).is_file():
            raise ValueError(f"Incomplete comparison: missing {name}")
    sources = read_json(path / "sources.json")
    if len(sources) < 2:
        raise ValueError("Incomplete comparison sources")
    metadata_sources = []
    for source in sources:
        evidence = completed_run(root, source["run_id"])
        if source["experiment"] != evidence["header"]["experiment_id"]:
            raise ValueError("Comparison source identity mismatch")
        for name, value in source["sha256"].items():
            if Path(name).name != name or sha256(evidence["path"] / name) != value:
                raise ValueError("Comparison source hash mismatch")
        metadata_sources.append(run_metadata(evidence, root, None))
    hashes = {name: sha256(path / name) for name in (*names, "comparison.json")}
    if (path / "outcome.json").exists():
        outcome = read_json(path / "outcome.json")
        if outcome.get("status") != "COMPLETE":
            raise ValueError("Comparison is not COMPLETE")
        if "sha256" in outcome and outcome["sha256"] != hashes:
            raise ValueError("Comparison artifact hash mismatch")
    table = pd.read_csv(path / "comparison.csv")
    records = read_json(path / "comparison.json")
    if len(table) != len(records) or set(table.experiment) != {s["experiment"] for s in sources}:
        raise ValueError("Comparison artifact count/source mismatch")
    payloads = {
        name: json_bytes(read_json(path / name), root)
        if name.endswith(".json")
        else clean_text((path / name).read_text(encoding="utf-8"), root).encode()
        for name in names
    }
    families = {family(s["strategy"]["id"]) for s in sources}
    group = next(iter(families)) if len(families) == 1 else "cross_family"
    destination = root / "research_results" / group / "comparison" / identifier
    return publish_files(
        destination,
        payloads,
        {
            "comparison_id": identifier,
            "source": portable(path, root),
            "sources": metadata_sources,
            "source_sha256": hashes,
            "classification": [s.get("research_classification") for s in sources],
        },
        root,
        max_bytes,
    )
