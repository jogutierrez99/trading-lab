"""ETH SHORT post-selection regime challenge using ordinary immutable lab runs."""

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from quant_lab.eth_short_regimes import (
    MINIMUM_TRADES,
    outlier_rows,
    pnl_statistics,
    regime_features,
    regime_rows,
    tag_trades,
)
from quant_lab.experiments import write_json
from quant_lab.lab_data import inspect_bundle, load_bundle
from quant_lab.lab_evidence import assert_unchanged, completed_run, new_id, read_json, sha256
from quant_lab.lab_publish import COMPACT_COLUMNS, json_bytes, publish_files, run_metadata
from quant_lab.lab_robustness import assert_references, verify_record
from quant_lab.lab_runner import prepare, run, window
from quant_lab.lab_schema import resolve
from quant_lab.lab_trend_expansion import (
    ADDED_COLUMNS,
    descriptive_families,
    distribution,
    paired_costs,
    region_neighbors,
)

STUDY = "eth_short_regime_challenge_v1"
FAMILIES = ("atr", "donchian_atr", "donchian")
EXPERIMENTS = tuple(f"{STUDY}_{family}" for family in FAMILIES)
LOCK = f"configs/research/{STUDY}.yaml"
EXPORTS = (
    "summary.csv",
    "strategy_comparison.csv",
    "regime_comparison.csv",
    "walk_forward_summary.csv",
    "base_adverse_comparison.csv",
    "parameter_robustness.csv",
    "trade_distribution.csv",
    "outlier_dependency.csv",
    "conclusions.md",
    "sources.json",
)
WARNING = (
    "This study is exploratory regime analysis based on hypotheses generated after observing "
    "previous TEST results. It is not an independent holdout and does not constitute "
    "paper-trading approval."
)
IDENTITY = (
    "family",
    "experiment_id",
    "run_id",
    "backtest_id",
    "configuration_id",
    "symbol",
    "timeframe",
    "mode",
    "period",
    "scenario",
)


def check_lock(root: Path) -> dict:
    lock = yaml.safe_load((root / LOCK).read_text(encoding="utf-8"))
    if lock["study_id"] != STUDY or lock["minimum_descriptive_trades"] != MINIMUM_TRADES:
        raise ValueError("Unexpected ETH SHORT frozen protocol")
    for name, digest in lock["file_sha256"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or sha256(path) != digest:
            raise ValueError(f"ETH SHORT protocol hash mismatch: {name}")
    return lock


def validate(root: Path, full: bool = False) -> dict:
    check_lock(root)
    rows = []
    for name in EXPERIMENTS:
        path, exp = resolve(root / "configs/experiments", name)
        if (
            exp.modes != ["SHORT_ONLY"]
            or len(exp.markets) != 1
            or (exp.markets[0].symbol, exp.markets[0].timeframe) != ("ETHUSDT", "1h")
        ):
            raise ValueError("Study requires ETHUSDT 1h SHORT_ONLY")
        context = prepare(path, exp, full=full)
        rows.append(
            dict(
                experiment=name,
                configurations=len(context["parameters"]),
                backtests=context["backtests"],
            )
        )
    return dict(
        study=STUDY,
        status="VALID",
        validation="FULL" if full else "FAST",
        experiments=rows,
        backtests=sum(r["backtests"] for r in rows),
        backtests_executed=0,
    )


def run_study(root: Path) -> dict:
    # All sources checked before creating any run; explicit CLI run is the heavy operation.
    validate(root, full=True)
    outputs = []
    for name in EXPERIMENTS:
        path, exp = resolve(root / "configs/experiments", name)
        outputs.append(str(run(path, exp, root)))
    return dict(study=STUDY, run_directories=outputs)


def walk_forward_summary(frame: pd.DataFrame) -> pd.DataFrame:
    selected = frame[frame.period.str.fullmatch(r"wf_\d+_test")]
    rows = []
    for (family, scenario), group in selected.groupby(["family", "scenario"], sort=True):
        folds = group.period.nunique()
        if folds != 4 or len(group) != 4:
            raise ValueError("Expected four distinct adaptive WF TEST folds per family/scenario")

        def statistic(column, method, fold_group=group):
            values = fold_group[column].dropna()
            return getattr(values, method)() if len(values) else np.nan

        rows.append(
            dict(
                family=family,
                scenario=scenario,
                folds=folds,
                positive_folds=int((group.return_pct > 0).sum()),
                negative_folds=int((group.return_pct < 0).sum()),
                zero_folds=int((group.return_pct == 0).sum()),
                profitable_ratio=f"{int((group.return_pct > 0).sum())}/{folds}",
                min_expectancy=statistic("expectancy", "min"),
                max_expectancy=statistic("expectancy", "max"),
                median_expectancy=statistic("expectancy", "median"),
                min_profit_factor=statistic("profit_factor", "min"),
                max_profit_factor=statistic("profit_factor", "max"),
                median_profit_factor=statistic("profit_factor", "median"),
                undefined_profit_factor_folds=int(group.profit_factor.isna().sum()),
                positive_expectancy_folds=int((group.expectancy > 0).sum()),
                minimum_fold_trades=int(group.closed_trades.min()),
                insufficient_sample_folds=int((group.closed_trades < MINIMUM_TRADES).sum()),
                selection="TRAIN-selected adaptive policy; not evidence for each fixed candidate",
                fold_configuration_ids=json.dumps(
                    group.sort_values("period").configuration_id.tolist()
                ),
            )
        )
    return pd.DataFrame(rows)


def conclusions(frame, wf, regimes, outliers, lock):
    comparison = descriptive_families(frame)
    sections = {
        "Scope": (
            "ETHUSDT 1h SHORT_ONLY; two hypotheses and one control. Synthetic "
            "USD-M prices; no funding, borrowing or liquidations."
        ),
        "Previous evidence": lock["previous_evidence"],
        "Methodological warning": WARNING,
        "Strategies": (
            "### ATR Volatility Breakout\n\nMain hypothesis; impulse 0.75/1/1.25"
            " ATR, expansion 1.1/1.25.\n\n### Donchian + ATR\n\nMain hypothesis; "
            "Donchian 30/40/50, expansion 1.1/1.25.\n\n### Donchian control\n\n"
            "Control only; Donchian 30/40/50. EMA200 slope filter and ATR14 x2"
            " / RR2 unchanged for all families."
        ),
        "Temporal Stability": (
            "Original TRAIN/VALIDATION/TEST unchanged. diagnostic_year_2023 "
            "through diagnostic_year_2026 are separate annual reruns, "
            "2023/2026 partial. Capital resets; these overlap main/WF windows "
            "and must not be pooled. Annual evidence includes prior unselected"
            " history; it is exploratory."
        ),
        "Walk Forward": (
            "Four original folds; selection uses TRAIN Sharpe/base only. "
            "Adaptive policy evidence, never assigned to each fixed candidate."
            "\n\n"
        )
        + "\n".join(
            f"- {r.family} {r.scenario}: positive {r.profitable_ratio}, "
            f"negative {r.negative_folds}/4; median PF {r.median_profit_factor:.4g}; "
            f"median expectancy {r.median_expectancy:.4g}; "
            f"insufficient folds {r.insufficient_sample_folds}."
            for r in wf.itertuples()
        ),
        "BASE vs ADVERSE": (
            "Actual matched reruns; BASE fee/slippage/spread 0.05/0.03/0.01%, "
            "ADVERSE 0.10/0.06/0.02%. Fees both sides and half-spread each "
            "fill. Sizing/trades may change. Read base_adverse_comparison.csv."
        ),
        "Regime Analysis": (
            "### Trend direction\n\nBearish: close below EMA200 AND "
            "EMA200[t]-EMA200[t-5]<0. Bullish: both opposite; otherwise mixed."
            "\n\n### Volatility\n\nATR14[t] divided by mean ATR14[t-50:t-1]; high "
            ">=1.1, ordinary <1.1. Undefined warmup is unavailable.\n\n### "
            "Combined\n\nCross of trend and volatility; explicit empty buckets. "
            "Labels sampled at signal close with the same period warmup as "
            "execution, reset at gaps. No regime filters added. Every bucket "
            "has count, PF, expectancy, sample status and trade/net PnL "
            "shares. No pooled candidate evidence or return/DD from bucket "
            "PnL."
        ),
        "Parameter robustness": (
            "All original neighbors retained; parameter_robustness.csv "
            "compares adjacent one-coordinate TRAIN/base pairs. No TEST "
            "ranking or parameter reselection; summary retains every fixed "
            "candidate main/annual cell."
        ),
        "Trade distribution": (
            "Per-cell wins/losses/breakevens, win rate, payoff, mean/median "
            "winners and losers, net median and percentiles, top "
            "ceil(N*pct/100) at 1/5/10%. Net shares undefined for non-positive"
            " total, may exceed 100%. Read trade_distribution.csv."
        ),
        "Outlier dependency": (
            "Complete and deletion of best/top5%/top10% net trades: count, net"
            " PnL, expectancy and PF. Descriptive deletion only; costs already"
            " netted, no execution rerun, return or DD. Read "
            "outlier_dependency.csv."
        ),
        "Findings": "Descriptive TEST family medians (all neighbors, no winner selection):\n\n"
        + "\n".join(
            f"- {r.family} {r.scenario}: {r.configurations} configurations; "
            f"median return {r.median_return_pct:.4g}%; expectancy {r.median_expectancy:.4g}; "
            f"PF {r.median_profit_factor:.4g}; trades {r.median_closed_trades:.4g}."
            for r in comparison[comparison.period == "test"].itertuples()
        )
        + f"\n\n{int((regimes.sample_status == 'INSUFFICIENT_SAMPLE').sum())}/{len(regimes)} "
        "regime cells have insufficient samples. "
        + str(int(((outliers.diagnostic != "complete") & (outliers.net_pnl <= 0)).sum()))
        + " deletion cells have non-positive remaining net PnL. "
        "These overlapping descriptive counts are not independent tests. "
        "Review hybrid vs control and ATR vs hybrid within the same period/scenario "
        "and neighboring regions; inspect negative periods without ranking TEST.",
        "Rejected hypotheses": (
            "PENDING HUMAN REVIEW. Labels: REJECTED, REGIME_DEPENDENT, "
            "ROBUST_RESEARCH_SURVIVOR, INSUFFICIENT_SAMPLE. Fewer than 20 "
            "trades marks insufficient descriptive sample, never a "
            "profitability gate. No automatic economic classification."
        ),
        "Surviving hypotheses": (
            "PENDING HUMAN REVIEW. REGIME_DEPENDENT requires documented "
            "concentration with sufficient bucket samples; "
            "ROBUST_RESEARCH_SURVIVOR requires explicit joint review of "
            "periods, costs, neighbors and outliers. Neither grants paper/live"
            " eligibility. No new numeric approval gates."
        ),
        "Limitations": (
            "Post-selection and multiple comparisons; reused TEST, dependent "
            "candidates/overlapping periods, limited samples, no confidence "
            "inference or portfolio. Shared EMA slope short entry rule can "
            "structurally concentrate trades in bearish labels, and ATR entry "
            "thresholds in high ATR labels: concentration alone is not proof "
            "of conditional edge. Conditional trade PnL lacks "
            "opportunity/exposure controls. Calendar boundaries force "
            "liquidation. OHLC ambiguity and conservative stop-first ordering "
            "unchanged. Undefined PF with no losses is missing, not infinity "
            "or failure. No independent holdout or future profits inferred."
        ),
        "Next falsification experiment": (
            "NEXT HYPOTHESIS ONLY: after human review, predeclare any "
            "bearish/high-volatility restriction and a fresh independent "
            "temporal protocol before observing new results. Do not implement "
            "filters, retune on this TEST or incorporate into "
            "forward/OKX/paper."
        ),
    }
    return (
        "# ETH SHORT regime challenge V1\n\n"
        + "\n\n".join(f"## {h}\n\n{v}" for h, v in sections.items())
        + "\n"
    )


def report(root: Path, identifiers=None) -> Path:
    lock = check_lock(root)
    lock_hash = sha256(root / LOCK)
    identifiers = identifiers or list(EXPERIMENTS)
    if len(identifiers) != 3 or len(set(identifiers)) != 3:
        raise ValueError("Provide three distinct runs in atr, donchian_atr, donchian order")
    sources, rows, refs, evidences, regimes, outliers = [], [], [], [], [], []
    ledger_hashes, common, dataset = {}, None, None
    dataset_hashes = {}
    for family, expected, identifier in zip(FAMILIES, EXPERIMENTS, identifiers, strict=True):
        evidence = completed_run(root, identifier)
        recorded_files = {
            p.replace("\\", "/"): digest for p, digest in evidence["provenance"]["files"].items()
        }
        if recorded_files.get(LOCK) != lock_hash:
            raise ValueError("Run was not executed with the frozen study protocol")
        if evidence["header"]["experiment_id"] != expected:
            raise ValueError("Unexpected ETH SHORT experiment/order")
        path, exp = resolve(root / "configs/experiments", expected)
        if exp.model_dump(mode="json") != evidence["plan"]:
            raise ValueError("Frozen run plan differs from current experiment")
        resolved = evidence["resolved"]
        signature = dict(
            validation=evidence["plan"]["validation"],
            diagnostics=evidence["plan"]["diagnostic_periods"],
            datasets=[(d["dataset_id"], d["parquet_sha256"]) for d in resolved["datasets"]],
            execution=resolved["execution"],
            app=resolved["app"],
            risk=resolved["strategy"]["risk"],
            code=evidence["provenance"]["code_sha256"],
        )
        if common is not None and common != signature:
            raise ValueError("Incompatible source datasets/periods/costs/risk/code")
        common = signature
        market = exp.markets[0]
        info = inspect_bundle(path.parent, market)
        if (info["dataset_id"], info["parquet_sha256"]) != signature["datasets"][0]:
            raise ValueError("Regime source dataset differs from execution")
        if dataset is None:
            dataset = load_bundle(info)
            folder = Path(info["path"])
            dataset_hashes = {
                str(folder / n): sha256(folder / n) for n in ("candles.parquet", "manifest.json")
            }
        feature_views = {
            label: regime_features(window(dataset, market, period)[0])
            for label, period in exp.periods()
        }
        sources.append(
            run_metadata(evidence, root, None)
            | dict(
                family=family,
                original_plan=evidence["plan"],
                resolved_strategy=resolved["strategy"],
                parameters=resolved["parameters"],
                parameter_risks=resolved.get("parameter_risks"),
                app=resolved["app"],
                git_status=evidence["provenance"].get("git_status"),
                study_protocol=lock,
                study_protocol_sha256=lock_hash,
                methodological_warning=WARNING,
            )
        )
        for raw in evidence["metrics"].to_dict("records"):
            clean = {k: v for k, v in raw.items() if not (isinstance(v, float) and np.isnan(v))}
            ref = verify_record(evidence["path"], clean, ledger_hashes)
            refs.append(ref)
            document = read_json(Path(ref["folder"]) / "result.json")
            saved, trades = document["metrics"], document["trades"]
            if (saved["symbol"], saved["timeframe"], saved["mode"]) != (
                "ETHUSDT",
                "1h",
                "SHORT_ONLY",
            ):
                raise ValueError("Unexpected market/mode in ETH SHORT result")
            costs = (
                saved["fees_paid"]
                + saved["slippage_cost_closed_trades"]
                + saved["spread_cost_closed_trades"]
            )
            out = {k: saved.get(k) for k in (*COMPACT_COLUMNS, *ADDED_COLUMNS)}
            out |= dict(
                family=family,
                experiment_id=expected,
                run_id=evidence["header"]["run_id"],
                backtest_id=saved["backtest_id"],
                total_modeled_costs=costs,
                average_cost_per_trade=costs / len(trades) if trades else None,
                **distribution(trades),
            )
            out |= pnl_statistics([t["net_pnl"] for t in trades])
            out["parameters"] = json.dumps(saved["parameters"], sort_keys=True)
            out["classification"] = "INSUFFICIENT_SAMPLE" if len(trades) < MINIMUM_TRADES else None
            out["classification_status"] = "human_review_required"
            rows.append(out)
            identity = {k: out[k] for k in IDENTITY}
            regimes.extend(
                regime_rows(identity, tag_trades(trades, feature_views[saved["period"]]))
            )
            outliers.extend(outlier_rows(identity, trades))
        evidences.append(evidence)
    assert_references(refs)
    for evidence in evidences:
        assert_unchanged(evidence)
    if any(sha256(Path(p)) != digest for p, digest in dataset_hashes.items()):
        raise ValueError("Dataset changed during regime reporting")
    check_lock(root)
    frame, regime_table, outlier_table = (
        pd.DataFrame(rows),
        pd.DataFrame(regimes),
        pd.DataFrame(outliers),
    )
    wf = walk_forward_summary(frame)
    tables = {
        "summary.csv": frame,
        "strategy_comparison.csv": descriptive_families(frame),
        "regime_comparison.csv": regime_table,
        "walk_forward_summary.csv": wf,
        "base_adverse_comparison.csv": paired_costs(frame),
        "parameter_robustness.csv": region_neighbors(frame),
        "trade_distribution.csv": frame[
            [
                *IDENTITY,
                "winners",
                "losers",
                "breakeven_trades",
                "closed_trades",
                "win_rate_pct",
                "average_win",
                "average_loss",
                "median_net_pnl",
                *ADDED_COLUMNS,
            ]
        ],
        "outlier_dependency.csv": outlier_table,
    }
    directory = root / "reports/eth-short-regime" / new_id()
    directory.mkdir(parents=True, exist_ok=False)
    for name, table in tables.items():
        table.to_csv(directory / name, index=False, mode="x")
    write_json(directory / "sources.json", sources)
    write_json(
        directory / "audit.json",
        dict(references=refs, dataset_hashes=dataset_hashes, protocol_sha256=lock_hash),
    )
    (directory / "conclusions.md").write_text(
        conclusions(frame, wf, regime_table, outlier_table, lock), encoding="utf-8"
    )
    write_json(
        directory / "outcome.json",
        dict(
            status="COMPLETE",
            study=STUDY,
            backtests_executed=0,
            sha256={name: sha256(directory / name) for name in (*EXPORTS, "audit.json")},
        ),
    )
    return directory


def publish(root: Path, identifier="latest", max_bytes=5_000_000) -> dict:
    check_lock(root)
    base = root / "reports/eth-short-regime"
    if identifier == "latest":
        found = sorted(base.glob("*/outcome.json"))
        if not found:
            raise ValueError("No ETH SHORT regime reports")
        identifier = found[-1].parent.name
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", identifier):
        raise ValueError("Expected report ID")
    directory = base / identifier
    outcome = read_json(directory / "outcome.json")
    if (
        outcome.get("status") != "COMPLETE"
        or outcome.get("backtests_executed") != 0
        or outcome.get("study") != STUDY
    ):
        raise ValueError("Incomplete ETH SHORT report")
    if set(outcome["sha256"]) != {*EXPORTS, "audit.json"}:
        raise ValueError("Report allowlist mismatch")
    if any(sha256(directory / n) != digest for n, digest in outcome["sha256"].items()):
        raise ValueError("ETH SHORT report hash mismatch")
    sources = read_json(directory / "sources.json")
    for source in sources:
        if completed_run(root, source["run_id"])["source_sha256"] != source["source_sha256"]:
            raise ValueError("ETH SHORT source changed")
    audit = read_json(directory / "audit.json")
    if audit["protocol_sha256"] != sha256(root / LOCK):
        raise ValueError("Study protocol changed")
    if any(sha256(Path(p)) != digest for p, digest in audit["dataset_hashes"].items()):
        raise ValueError("Regime dataset changed")
    assert_references(audit["references"])
    payloads = {
        n: json_bytes(sources, root) if n == "sources.json" else (directory / n).read_bytes()
        for n in EXPORTS
    }
    if any(len(v) > max_bytes for v in payloads.values()):
        raise ValueError("Compact report exceeds file limit; increase --max-file-mb")
    return publish_files(
        root / "research_results/trend_expansion/eth_short_regime" / identifier,
        payloads,
        dict(
            study=STUDY,
            report_id=identifier,
            sources=sources,
            evidence_scope=WARNING,
            report_sha256=outcome["sha256"],
        ),
        root,
        max_bytes,
    )


def main(root: Path, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="lab.py eth-short-regime", description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("run", help="Heavy local study: execute three ordinary experiments")
    validator = commands.add_parser("validate")
    validator.add_argument("--full", action="store_true")
    reporter = commands.add_parser(
        "report", aliases=["compare"], help="Audit and compare three completed runs; no simulation"
    )
    reporter.add_argument("--runs", nargs=3, metavar="RUN_ID")
    publisher = commands.add_parser("publish")
    publisher.add_argument("identifier", nargs="?", default="latest")
    publisher.add_argument("--max-file-mb", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        if args.action == "validate":
            result = validate(root, args.full)
        elif args.action == "run":
            result = run_study(root)
        elif args.action in ("report", "compare"):
            result = dict(report_directory=str(report(root, args.runs)), backtests_executed=0)
        else:
            result = publish(root, args.identifier, int(args.max_file_mb * 1_000_000))
        print(json.dumps(result, indent=2, default=str, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
