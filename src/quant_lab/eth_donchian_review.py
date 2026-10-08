"""Bounded immutable review of already observed ETH SHORT evidence."""

import argparse
import json
import math
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from quant_lab.experiments import provenance
from quant_lab.lab_eth_short_history import check_lock, validate
from quant_lab.lab_evidence import completed_run, new_id, read_json, sha256
from quant_lab.lab_publish import json_bytes, publish_files
from quant_lab.lab_robustness import assert_references, verify_record

POLICY = "configs/research/eth_donchian_short_prospective_v1.yaml"
OUTPUT = "research_results/trend_expansion/eth_donchian_short_review"
FAMILIES = ("atr", "donchian_atr")


class Protocol(BaseModel):
    """Research preregistration, deliberately not a ForwardConfig."""

    model_config = ConfigDict(extra="forbid", strict=True)
    study_id: Literal["eth_donchian_short_prospective_v1"]
    status: Literal["ARCHITECTURE_REVIEW_REQUIRED"]
    mode: Literal["signal_only"]
    trading_enabled: Literal[False]
    send_orders: Literal[False]
    allow_live_trading: Literal[False]
    freeze_time_utc: str
    earliest_signal_close_utc: str
    historical_report: str
    recent_publication: str
    minimum_calendar_days: Literal[180]
    minimum_closed_trades_per_candidate: Literal[100]
    minimum_positive_candidates_both_costs: Literal[4]
    minimum_positive_neighbor_edges_both_costs: Literal[4]
    maximum_drawdown_pct: Literal[15.0]
    bootstrap_block_days: Literal[7]
    bootstrap_replicates: Literal[10000]
    bootstrap_seed: Literal[271828]
    familywise_alpha: Literal[0.05]
    file_sha256: dict[str, str] = Field(min_length=1)


def checked_path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Evidence path escapes repository")
    return path


def load_protocol(root):
    policy = Protocol.model_validate(yaml.safe_load((root / POLICY).read_text(encoding="utf-8")))
    freeze = pd.Timestamp(policy.freeze_time_utc)
    start = pd.Timestamp(policy.earliest_signal_close_utc)
    if freeze.tzinfo is None or start.tzinfo is None or start <= freeze:
        raise ValueError("Prospective signal boundary must follow UTC preregistration")
    for name, digest in policy.file_sha256.items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError(f"Review source hash mismatch: {name}")
    check_lock(root)
    return policy


def close(actual, expected, label):
    if not math.isfinite(float(actual)) or not math.isclose(
        actual, expected, rel_tol=1e-9, abs_tol=1e-7
    ):
        raise ValueError(f"Trade accounting mismatch: {label}")


def audit_trade(trade, costs):
    """Independently check saved fills/accounting; never rebuild equity."""
    if trade["side"] != "short":
        raise ValueError("Effective direction is not SHORT")
    signal, entry = pd.Timestamp(trade["signal_close"]), pd.Timestamp(trade["entry_time"])
    if signal.tzinfo is None or entry.tzinfo is None or entry != signal:
        raise ValueError("Expected next hourly open at the signal candle close")
    quantity, price, exit_price = (trade[k] for k in ("quantity", "entry_price", "exit_price"))
    stop, target = trade["stop"], trade["target"]
    if not (quantity > 0 and stop > price > target > 0):
        raise ValueError("Invalid SHORT protective levels")
    close(price - target, 2 * (stop - price), "2R target")
    fee = costs["trading_fee_pct"] / 100
    slip = costs["slippage_pct"] / 100
    half_spread = costs["spread_pct"] / 200
    adverse = slip + half_spread
    ref_entry, ref_exit = trade["entry_reference"], trade["exit_reference"]
    close(price, ref_entry * (1 - adverse), "entry fill")
    close(exit_price, ref_exit * (1 + adverse), "exit fill")
    close(trade["entry_fee"], quantity * price * fee, "entry fee")
    close(trade["exit_fee"], quantity * exit_price * fee, "exit fee")
    close(
        trade["net_pnl"],
        quantity * (price - exit_price) - trade["entry_fee"] - trade["exit_fee"],
        "SHORT PnL",
    )
    close(trade["slippage_cost"], quantity * (ref_entry + ref_exit) * slip, "slippage")
    close(trade["spread_cost"], quantity * (ref_entry + ref_exit) * half_spread, "spread")
    stopped = stop * (1 + adverse)
    expected = quantity * (stopped - price + fee * (price + stopped))
    close(trade["expected_stop_loss"], expected, "cost-aware stop risk")
    budget = trade["risk_budget"]
    if budget <= 0 or expected > budget + 1e-7:
        raise ValueError("Entry stop risk exceeds frozen budget")
    # Risk budget is 1% of equity at entry. MTM exposure later may exceed this entry cap.
    if quantity * price * (1 + fee) > (budget / 0.01) * 0.25 + 1e-7:
        raise ValueError("Entry exceeds 25% fee-inclusive capital cap")


def source_frames(root, policy):
    historical = checked_path(root, policy.historical_report)
    recent = checked_path(root, policy.recent_publication)
    outcome = read_json(historical / "outcome.json")
    if outcome["status"] != "COMPLETE":
        raise ValueError("Historical report incomplete")
    for name, digest in outcome["sha256"].items():
        if sha256(checked_path(historical, name)) != digest:
            raise ValueError("Historical report artifact hash mismatch")
    metadata = read_json(recent / "metadata.json")
    for name, digest in metadata["artifacts_sha256"].items():
        if sha256(checked_path(recent, name)) != digest:
            raise ValueError("Recent publication artifact hash mismatch")
    frames = []
    for label, path in (("historical", historical), ("recent", recent)):
        frame = pd.read_csv(path / "summary.csv")
        frame = frame[frame.family.isin(FAMILIES)].copy()
        frame["evidence_source"] = label
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    identities = frames[0].set_index("configuration_id").candidate_id.to_dict()
    result["candidate_id"] = result.configuration_id.map(identities)
    if result.candidate_id.isna().any():
        raise ValueError("Unknown recent configuration outside frozen twelve candidates")
    return result, historical, recent


def audit_records(root, frame, historical, recent):
    references, ledger_hashes, sources, audits = [], {}, [], []
    for label, path in (("historical", historical), ("recent", recent)):
        for source in read_json(path / "sources.json"):
            if source["family"] not in FAMILIES:
                continue
            evidence = completed_run(root, source["run_id"])
            if evidence["source_sha256"] != source["source_sha256"]:
                raise ValueError("Original run hashes differ from published source")
            rows = evidence["metrics"]
            if label == "recent":
                rows = rows[rows.period.eq("test")]
            for row in rows.to_dict("records"):
                clean = {
                    k: v for k, v in row.items() if not isinstance(v, float) or not math.isnan(v)
                }
                ref = verify_record(evidence["path"], clean, ledger_hashes)
                document = read_json(Path(ref["folder"]) / "result.json")
                if document["metrics"]["direction"] != "short":
                    raise ValueError("Effective engine direction mismatch")
                for trade in document["trades"]:
                    audit_trade(trade, document["metrics"]["costs"])
                references.append(ref)
                audits.append(dict(backtest_id=row["backtest_id"], trades=len(document["trades"])))
            sources.append(dict(evidence_source=label, **source))
    audited = {a["backtest_id"] for a in audits}
    expected = frame[(frame.evidence_source == "historical") | frame.period.eq("test")]
    if audited != set(expected.backtest_id) or len(audits) != 96:
        raise ValueError("Expected 72 historical plus 24 recent TEST records")
    assert_references(references)
    return sources, references, audits


def evidence_catalog(frame):
    rows = frame[["evidence_source", "period", "start", "end"]].drop_duplicates().copy()
    rows["observed"] = True
    rows["reused_in_this_review"] = True
    rows["independent_available"] = False
    rows["prior_use"] = rows.period.map(
        lambda p: (
            "TRAIN selection"
            if p == "train"
            else "observed validation"
            if p == "validation"
            else "post-TEST historical falsification"
            if p.startswith("HISTORICAL_CHALLENGE")
            else "consumed final TEST; influenced frozen hypotheses"
            if p == "test"
            else "adaptive WF TEST; not evidence for each fixed winner"
            if p.startswith("wf_")
            else "retrospective diagnostic"
        )
    )
    rows["overlapping_periods"] = [
        ";".join(
            f"{r.evidence_source}:{r.period}"
            for r in rows.itertuples()
            if (r.evidence_source, r.period) != (row.evidence_source, row.period)
            and pd.Timestamp(r.start) < pd.Timestamp(row.end)
            and pd.Timestamp(r.end) > pd.Timestamp(row.start)
        )
        for row in rows.itertuples()
    ]
    rows["independence_note"] = (
        "Already observed; earlier project exposure unknown; never pool overlaps"
    )
    future = dict(
        evidence_source="prospective",
        period="not_collected",
        start="2026-10-09T00:00:00Z",
        end=None,
        observed=False,
        reused_in_this_review=False,
        independent_available=False,
        prior_use="future collection after adapter acceptance; no observations yet",
        overlapping_periods="",
        independence_note="Independent evidence still unavailable; never backfill missed days",
    )
    return pd.concat([rows, pd.DataFrame([future])], ignore_index=True)


def inventory(root):
    rows = []
    for path in sorted((root / "data").rglob("manifest.json")):
        if "ETHUSDT" not in path.parts:
            continue
        manifest = read_json(path)
        audit = manifest.get("audit", {})
        timeframe = audit.get("timeframe", manifest.get("timeframe"))
        if timeframe != "1h":
            continue
        rows.append(
            dict(
                path=path.relative_to(root).as_posix(),
                sha256=sha256(path),
                end=audit.get("end", manifest.get("end")),
                status=audit.get("status", "unknown"),
            )
        )
    return rows


def neighbors(frame):
    """One-coordinate adjacent edges, evaluated descriptively for each existing cell."""
    output = []
    hybrid = frame[frame.family.eq("donchian_atr")]
    for key, group in hybrid.groupby(["evidence_source", "period", "scenario"]):
        if len(group) != 6:
            continue  # Adaptive WF winners cannot stand in for the fixed region.
        candidates = [(row, json.loads(row.parameters)) for row in group.itertuples()]
        for i, (a, pa) in enumerate(candidates):
            for b, pb in candidates[i + 1 :]:
                changed = [k for k in pa if pa[k] != pb[k]]
                if len(changed) != 1:
                    continue
                parameter = changed[0]
                values = sorted({p[parameter] for _, p in candidates})
                if abs(values.index(pa[parameter]) - values.index(pb[parameter])) != 1:
                    continue
                known = all(
                    pd.notna(v)
                    for v in (a.expectancy, b.expectancy, a.profit_factor, b.profit_factor)
                )
                positive_a = known and a.expectancy > 0 and a.profit_factor > 1
                positive_b = known and b.expectancy > 0 and b.profit_factor > 1
                label = (
                    "INSUFFICIENT_EVIDENCE"
                    if not known or min(a.closed_trades, b.closed_trades) < 20
                    else "REGION_ESTABLE"
                    if positive_a and positive_b
                    else "RESULTADO_AISLADO_EN_ARISTA"
                    if positive_a != positive_b
                    else "REGION_SENSIBLE_O_NEGATIVA"
                )
                output.append(
                    dict(
                        evidence_source=key[0],
                        period=key[1],
                        scenario=key[2],
                        parameter=parameter,
                        candidate_a=a.candidate_id,
                        candidate_b=b.candidate_id,
                        backtest_id_a=a.backtest_id,
                        backtest_id_b=b.backtest_id,
                        return_pct_a=a.return_pct,
                        return_pct_b=b.return_pct,
                        expectancy_a=a.expectancy,
                        expectancy_b=b.expectancy,
                        profit_factor_a=a.profit_factor,
                        profit_factor_b=b.profit_factor,
                        closed_trades_a=a.closed_trades,
                        closed_trades_b=b.closed_trades,
                        descriptive_region=label,
                    )
                )
    return pd.DataFrame(output)


def review(root, publish=False, full=False):
    policy = load_protocol(root)
    validation = validate(root, full=full)
    frame, historical, recent = source_frames(root, policy)
    sources, references, audits = audit_records(root, frame, historical, recent)
    available = inventory(root)
    ends = [pd.Timestamp(r["end"]) for r in available if r["end"]]
    latest = max(ends) if ends else None
    # A new dataset requires a new preregistered integrity review, never automatic backtesting.
    result = dict(
        status="REVIEWED",
        audited_records=len(audits),
        audited_trade_instances=sum(a["trades"] for a in audits),
        dataset_validation="FULL" if full else "FAST",
        newest_local_eth_1h_manifest_end=str(latest),
        new_local_manifest_after_observed_test=bool(
            latest and latest > pd.Timestamp("2026-09-26T00:00:00Z")
        ),
        statistical_decision="PROSPECTIVE_VALIDATION_REQUIRED",
        operational_decision=policy.status,
        backtests_executed=0,
        orders_sent=0,
    )
    if not publish:
        return result
    payloads = {}

    def csv(name, data):
        payloads[name] = data.to_csv(index=False).encode()

    selected = frame[
        (frame.evidence_source == "historical") | frame.period.isin(["train", "validation", "test"])
    ].copy()
    csv("summary.csv", selected)
    csv("historical_evidence.csv", evidence_catalog(frame))
    csv("parameter_robustness.csv", neighbors(frame))
    for export, source_name in (
        ("cost_sensitivity.csv", "base_adverse_comparison.csv"),
        ("outlier_dependency.csv", "outlier_dependency.csv"),
        ("regime_comparison.csv", "regime_comparison.csv"),
    ):
        parts = []
        for label, path in (("historical", historical), ("recent", recent)):
            data = pd.read_csv(path / source_name)
            data = data[data.family.eq("donchian_atr")].copy()
            if label == "recent":
                data = data[
                    data.period.isin(["train", "validation", "test"])
                    | data.period.str.startswith("diagnostic_year_")
                ]
            data["evidence_source"] = label
            parts.append(data)
        csv(export, pd.concat(parts, ignore_index=True))
    verdict = selected[selected.family.eq("donchian_atr")].copy()
    verdict["descriptive_verdict"] = "REGIME_DEPENDENT"
    verdict["statistical_decision"] = "PROSPECTIVE_VALIDATION_REQUIRED"
    csv(
        "candidate_verdicts.csv",
        verdict[
            [
                "candidate_id",
                "evidence_source",
                "period",
                "scenario",
                "return_pct",
                "profit_factor",
                "expectancy",
                "closed_trades",
                "descriptive_verdict",
                "statistical_decision",
            ]
        ],
    )
    for name in ("forward_readiness.md", "portfolio_compatibility.md", "conclusions.md"):
        payloads[name] = (root / "docs/eth-donchian-short-review" / name).read_bytes()
    payloads["prospective_protocol.yaml"] = (root / POLICY).read_bytes()
    payloads["sources.json"] = json_bytes(
        dict(
            review=result,
            validation=validation,
            sources=sources,
            audited_records=audits,
            references=references,
            local_eth_1h_manifest_inventory=available,
            review_provenance=provenance(root),
            protocol_sha256=sha256(root / POLICY),
            report_code_sha256=sha256(Path(__file__)),
            note="Trade instances across candidates/costs are dependent, not independent N. "
            "Recent non-TEST diagnostics reuse a hash-checked publication; "
            "their ledgers were not reaudited.",
        ),
        root,
    )
    # Recheck frozen inputs before exclusive publication. Never write into a source run/session.
    load_protocol(root)
    assert_references(references)
    return result | publish_files(root / OUTPUT / new_id(), payloads, result, root, 5_000_000)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "report"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--full", action="store_true", help="Verify pinned OHLCV bytes/fingerprint; no backtests"
    )
    args = parser.parse_args(argv)
    try:
        print(json.dumps(review(args.root.resolve(), args.action == "report", args.full), indent=2))
        return 0
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"Review refused: {error}\n")
