"""Frozen ETH SHORT parameter regions, named historical falsification and compact audit."""

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
from quant_lab.lab_challenge import prepare_challenge, resolve_challenge, run_challenge
from quant_lab.lab_data import inspect_bundle, load_bundle
from quant_lab.lab_evidence import assert_unchanged, completed_run, new_id, read_json, sha256
from quant_lab.lab_publish import COMPACT_COLUMNS, json_bytes, publish_files, run_metadata
from quant_lab.lab_robustness import assert_references, verify_record
from quant_lab.lab_runner import window
from quant_lab.lab_trend_expansion import ADDED_COLUMNS, distribution, region_neighbors

STUDY = "eth_short_historical_falsification_v1"
FAMILIES = ("atr", "donchian_atr")
EXPERIMENTS = tuple(f"{STUDY}_{f}" for f in FAMILIES)
LOCK = f"configs/research/{STUDY}.yaml"
EXPORTS = (
    "summary.csv",
    "year_comparison.csv",
    "strategy_comparison.csv",
    "base_adverse_comparison.csv",
    "parameter_robustness.csv",
    "trade_distribution.csv",
    "outlier_dependency.csv",
    "regime_comparison.csv",
    "falsification_scorecard.csv",
    "conclusions.md",
    "sources.json",
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
    "year",
    "scenario",
)
WARNING = (
    "This historical challenge is a falsification study of frozen hypotheses. "
    "It does not constitute paper or live trading approval and does not establish "
    "future profitability."
)


def check_lock(root: Path) -> dict:
    lock = yaml.safe_load((root / LOCK).read_text(encoding="utf-8"))
    if lock["study_id"] != STUDY or lock["minimum_descriptive_trades"] != MINIMUM_TRADES:
        raise ValueError("Unexpected historical falsification protocol")
    for name, digest in lock["file_sha256"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or sha256(path) != digest:
            raise ValueError(f"Historical protocol/source hash mismatch: {name}")
    return lock


def previous_sources(root: Path, lock: dict) -> dict:
    return {
        s["family"]: s
        for s in read_json(root / lock["previous_publication"] / "sources.json")
        if s["family"] in FAMILIES
    }


def check_context(spec, context, source):
    plan = source["original_plan"]
    if (
        spec.strategy.id != source["strategy"]
        or spec.markets[0].symbol != "ETHUSDT"
        or (spec.markets[0].timeframe != "1h" or spec.modes != ["SHORT_ONLY"])
    ):
        raise ValueError("Frozen scope requires ATR/hybrid ETHUSDT 1h SHORT_ONLY")
    if [c["parameters"] for c in context["candidates"]] != source["parameters"]:
        raise ValueError("Frozen whole parameter region differs from previous publication")
    if [c["risk"] for c in context["candidates"]] != source["parameter_risks"]:
        raise ValueError("Frozen per-configuration sizing/risk differs from previous publication")
    if context["template"].model_dump(mode="json") != source["resolved_strategy"]:
        raise ValueError("Frozen strategy/profile/risk differs from previous publication")
    if spec.markets[0].model_dump(mode="json") != plan["markets"][0] or (
        spec.execution.model_dump(mode="json") != plan["execution"]
        or spec.costs.model_dump(mode="json") != plan["costs"]
        or spec.initial_cash != plan["initial_cash"]
        or context["app"].model_dump(mode="json") != source["app"]
        or {k: v.model_dump(mode="json") for k, v in spec.historical_challenge.cost_stress.items()}
        != plan["validation"]["cost_stress"]
    ):
        raise ValueError("Frozen market/warmup/execution/capital/cost/app assumptions changed")


def validate(root: Path, full=False) -> dict:
    lock = check_lock(root)
    sources = previous_sources(root, lock)
    rows = []
    for family, name in zip(FAMILIES, EXPERIMENTS, strict=True):
        path, spec = resolve_challenge(root, name)
        context = prepare_challenge(path, spec, full=full)
        check_context(spec, context, sources[family])
        rows.append(
            dict(
                experiment=name,
                candidates=len(context["candidates"]),
                backtests=context["backtests"],
                periods=spec.historical_challenge.model_dump(mode="json"),
            )
        )
    return dict(
        status="VALID",
        study=STUDY,
        validation="FULL" if full else "FAST",
        experiments=rows,
        backtests=sum(r["backtests"] for r in rows),
        backtests_executed=0,
    )


def run_one(root: Path, name: str) -> Path:
    if name not in EXPERIMENTS:
        raise ValueError("Unexpected historical experiment")
    validate(root, full=True)
    path, spec = resolve_challenge(root, name)
    return run_challenge(path, spec, root)


def scorecard(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (family, year, scenario), group in frame.groupby(["family", "year", "scenario"]):
        row = dict(
            family=family,
            year=year,
            scenario=scenario,
            configurations=len(group),
            positive_configs=int((group.return_pct > 0).sum()),
            positive_configs_pct=100 * (group.return_pct > 0).mean(),
            pf_above_one_pct=100 * (group.profit_factor > 1).sum() / len(group),
            undefined_pf_configs=int(group.profit_factor.isna().sum()),
            positive_expectancy_pct=100 * (group.expectancy > 0).sum() / len(group),
            undefined_expectancy_configs=int(group.expectancy.isna().sum()),
            insufficient_sample_configs=int((group.closed_trades < MINIMUM_TRADES).sum()),
            worst_return_pct=group.return_pct.min(),
            best_return_pct=group.return_pct.max(),
            worst_configuration_ids=json.dumps(
                group.loc[group.return_pct == group.return_pct.min(), "configuration_id"].tolist()
            ),
            best_configuration_ids=json.dumps(
                group.loc[group.return_pct == group.return_pct.max(), "configuration_id"].tolist()
            ),
            best_worst_use="descriptive extrema only; no candidate selection",
            verdict=None,
            classification_status="manual_review_required",
        )
        for metric in (
            "return_pct",
            "profit_factor",
            "expectancy",
            "max_drawdown_pct",
            "sharpe",
            "sortino",
            "closed_trades",
            "total_modeled_costs",
            "average_close_exposure_pct",
        ):
            values = group[metric].dropna()
            row["median_" + metric] = values.median() if len(values) else None
            row["iqr_" + metric] = (
                values.quantile(0.75) - values.quantile(0.25) if len(values) else None
            )
        if row["insufficient_sample_configs"] == len(group):
            row["verdict"] = "INSUFFICIENT_SAMPLE"
        rows.append(row)
    return pd.DataFrame(rows)


def neighbors(frame):
    outputs = []
    for (period, scenario), group in frame.groupby(["period", "scenario"]):
        # Reuse exact adjacency logic, preserving each historical period/cost separately.
        table = region_neighbors(group.assign(period="train", scenario="base"))
        table["period"], table["scenario"] = period, scenario
        for metric in ("return_pct", "profit_factor", "expectancy", "max_drawdown_pct"):
            table[metric + "_delta"] = table[metric + "_b"] - table[metric + "_a"]
            table[metric + "_absolute_dispersion"] = table[metric + "_delta"].abs()
        outputs.append(table)
    return pd.concat(outputs, ignore_index=True)


def strategy_comparison(card):
    """Matched annual whole-region medians; never pair unrelated parameter IDs."""
    columns = [c for c in card if c.startswith("median_") or c.endswith("_pct")]
    columns = list(dict.fromkeys(["year", "scenario", "configurations", *columns]))
    paired = card[card.family == "atr"][columns].merge(
        card[card.family == "donchian_atr"][columns],
        on=["year", "scenario"],
        suffixes=("_atr", "_donchian_atr"),
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    if not paired._merge.eq("both").all():
        raise ValueError("Missing matched historical family region")
    for metric in ("return_pct", "profit_factor", "expectancy", "sharpe", "max_drawdown_pct"):
        key = "median_" + metric
        paired[key + "_hybrid_minus_atr"] = paired[key + "_donchian_atr"] - paired[key + "_atr"]
    return paired.drop(columns="_merge")


def costs_comparison(frame):
    keys = [k for k in IDENTITY if k not in ("backtest_id", "scenario")]
    metrics = [
        "return_pct",
        "profit_factor",
        "expectancy",
        "sharpe",
        "max_drawdown_pct",
        "closed_trades",
        "total_modeled_costs",
    ]
    columns = keys + ["backtest_id"] + metrics
    paired = frame[frame.scenario == "base"][columns].merge(
        frame[frame.scenario == "adverse"][columns],
        on=keys,
        how="outer",
        suffixes=("_base", "_adverse"),
        validate="one_to_one",
        indicator=True,
    )
    if not paired._merge.eq("both").all():
        raise ValueError("Missing BASE/ADVERSE pair")
    for metric in metrics:
        paired[metric + "_delta"] = paired[metric + "_adverse"] - paired[metric + "_base"]
    required = [
        f"{m}_{s}"
        for m in ("return_pct", "profit_factor", "expectancy")
        for s in ("base", "adverse")
    ]
    known = paired[required].notna().all(axis=1)
    base_positive = (
        (paired.return_pct_base > 0)
        & (paired.profit_factor_base > 1)
        & (paired.expectancy_base > 0)
    )
    adverse_positive = (
        (paired.return_pct_adverse > 0)
        & (paired.profit_factor_adverse > 1)
        & (paired.expectancy_adverse > 0)
    )
    paired["edge_disappears_adverse"] = pd.Series(pd.NA, index=paired.index, dtype="boolean")
    paired.loc[known, "edge_disappears_adverse"] = (base_positive & ~adverse_positive)[known]
    paired["edge_flag_definition"] = (
        "BASE return>0/PF>1/expectancy>0 loses conjunction in ADVERSE; diagnostic only"
    )
    return paired.drop(columns="_merge")


def conclusions(card, costs, previous):
    def display(table):
        columns = [
            "family",
            "year",
            "scenario",
            "positive_configs",
            "configurations",
            "median_return_pct",
            "median_profit_factor",
            "median_expectancy",
            "median_max_drawdown_pct",
        ]
        return "```csv\n" + table[columns].to_csv(index=False) + "```"

    sections = {
        "Scope": WARNING
        + "\n\nETHUSDT 1h SHORT_ONLY, two whole frozen regions; historical falsification only.",
        "Frozen hypotheses": (
            "Six ATR configurations and six Donchian+ATR configurations from "
            "the exact prior published resolved lists. Donchian pure excluded."
            " No ranking, optimization, new filters or exits."
        ),
        "Methodology": (
            "Existing named HistoricalChallenge schema and runner; causal "
            "close decisions, earliest next-open fills, conservative stop-"
            "first ordering, same sizing/caps and costs. Capital resets per "
            "year, liquidates at boundaries. No WF or fake TRAIN/TEST. All "
            "parameters and labels are predeclared."
        ),
        "Historical periods": (
            "UTC exclusive ends: 2020-02-11 16:00â†’2021-01-01; "
            "2021-01-01â†’2022-01-01; 2022-01-01â†’2023-01-01. Original "
            "request starts2020-01-01; exactly1000 available hours are warmup."
            " No invented prior history or outcome-dependent date changes."
        ),
        "Why these periods are falsification evidence": (
            "Earlier history is outside the principal recent selection "
            "windows, but hypotheses were selected after observing later TEST."
            " Earlier data may already have been used conceptually elsewhere "
            "in the project. This is additional historical falsification, not "
            "a virgin/future independent holdout; independence of prior "
            "project exposure is unknown."
        ),
        "ATR Volatility Breakout": display(card[card.family == "atr"]),
        "Donchian + ATR": display(card[card.family == "donchian_atr"]),
        "2020": "Partial calendar year after fixed warmup.\n\n" + display(card[card.year == 2020]),
        "2021": display(card[card.year == 2021]),
        "2022": display(card[card.year == 2022]),
        "Aggregate 2020-2022": (
            "Not executed: optional overlapping aggregate omitted. Annual "
            "account resets cannot be compounded or represented as continuous "
            "equity/return/DD. No pooled configuration or duplicate-cost "
            "evidence."
        ),
        "BASE vs ADVERSE": (
            "BASE fee/slippage/spread0.05/0.03/0.01%; ADVERSE0.10/0.06/0.02%. "
            "Actual reruns. All per-cell return/PF/expectancy/Sharpe deltas in"
            " base_adverse_comparison.csv. "
        )
        + str(int(costs.edge_disappears_adverse.fillna(False).sum()))
        + (
            " matched cells lose the descriptive BASE-positive conjunction in "
            "ADVERSE; missing metrics stay unknown. This flag is not a "
            "survivor gate."
        ),
        "Parameter robustness": (
            "Whole-region medians, dispersion/IQR, percentages with fixed "
            "denominator including undefined metrics (reported separately). "
            "Adjacent one-coordinate neighbors per year/scenario. Best/worst "
            "returns are descriptive extrema only, never selection. No "
            "arbitrary score or mandatory every-year-positive rule."
        ),
        "Trade distribution": (
            "Net winners/losers/breakevens, mean/median winners and losers, "
            "payoff, PnL quantiles and top ceil(N*pct/100) contributions "
            "at1/5/10%. Low win rate, many small losses and right-tail winners"
            " do not automatically reject a trend system; assess gains against"
            " losses and costs."
        ),
        "Outlier dependency": (
            "Complete and deletion of best/top5%/top10% net trade PnLs; "
            "descriptive count/net PnL/expectancy/PF, no resimulation, rebuilt"
            " return or DD. Do not change exits to suppress convexity. Missing"
            " PF without losers remains undefined."
        ),
        "Regime diagnostics": (
            "Exactly previous EMA200 price+slope5 and ATR14/previous mean50, "
            "high>=1.1. Same bearish/bullish/mixed/unavailable and "
            "high/ordinary/unavailable buckets. Signal-close tagging, "
            "execution-period warmup and gap resets unchanged; no trade "
            "filtering. Existing entry filters structurally concentrate "
            "labels; concentration alone does not establish conditional edge."
        ),
        "Comparison against recent 2025-2026 behavior": (
            "Reference only: fixed prior publication, no recent reruns, "
            "pooling, reselection or claim of new evidence. Historical context"
            " may falsify a recent regime-dependent interpretation. Prior TEST"
            " family medians:\n\n```csv\n"
        )
        + previous.query('period == "test" and family in ["atr", "donchian_atr"]')[
            ["family", "scenario", "median_return_pct", "median_profit_factor", "median_expectancy"]
        ].to_csv(index=False)
        + "```",
        "Rejected hypotheses": (
            "PENDING MANUAL REVIEW. No automatic rejection for low win rate, a"
            " negative year or dependence on right-tail winners."
        ),
        "Survivors": (
            "PENDING MANUAL REVIEW. Review expectancy, PF, ADVERSE, stability,"
            " sample size, neighbors, outliers and positive/negative years "
            "together; strongest cell cannot determine the verdict."
        ),
        "Limitations": (
            "Post-selection, conceptual overlap, synthetic execution on USD-M "
            "prices, funding/borrow/liquidations not modelled, annual "
            "resets/partial2020, dependent neighbors, limited samples, OHLC "
            "ambiguity. Twenty trades is a descriptive minimum, not "
            "statistical significance. No independent future holdout or new "
            "operational eligibility."
        ),
        "Final classification": (
            "Manual/descriptive labels only: REJECTED, REGIME_DEPENDENT, "
            "HISTORICAL_FALSIFICATION_SURVIVOR, INSUFFICIENT_SAMPLE. Economic "
            "verdicts pending; no arbitrary scoring or paper-candidate "
            "promotion."
        ),
        "Recommended next step": (
            "Review the whole two-family historical region jointly with recent"
            " reference evidence. If falsified, reject/archive or document "
            "regime dependence without retuning this challenge. If it "
            "survives, predeclare a separate independent future validation "
            "before observing outcomes; no forward/paper implementation "
            "authorized here."
        ),
    }
    return (
        "# ETH SHORT historical falsification V1\n\n"
        + "\n\n".join(f"## {heading}\n\n{text}" for heading, text in sections.items())
        + "\n"
    )


def report(root: Path, identifiers=None) -> Path:
    lock = check_lock(root)
    lock_hash = sha256(root / LOCK)
    previous = previous_sources(root, lock)
    identifiers = identifiers or list(EXPERIMENTS)
    if len(identifiers) != 2 or len(set(identifiers)) != 2:
        raise ValueError("Provide two distinct runs in ATR, hybrid order")
    sources, rows, regimes, outliers, refs, evidences = [], [], [], [], [], []
    common, data, data_hashes, ledger_hashes = None, None, {}, {}
    for family, name, identifier in zip(FAMILIES, EXPERIMENTS, identifiers, strict=True):
        evidence = completed_run(root, identifier)
        if (
            evidence["header"]["kind"] != "lab_challenge_v1"
            or evidence["header"]["experiment_id"] != name
        ):
            raise ValueError("Unexpected historical source/order")
        files = {p.replace("\\", "/"): h for p, h in evidence["provenance"]["files"].items()}
        if files.get(LOCK) != lock_hash:
            raise ValueError("Run did not use frozen historical protocol")
        path, spec = resolve_challenge(root, name)
        if spec.model_dump(mode="json") != evidence["plan"]:
            raise ValueError("Frozen historical run plan differs")
        context = prepare_challenge(path, spec, full=False)
        check_context(spec, context, previous[family])
        resolved = evidence["resolved"]
        if resolved["candidates"] != context["candidates"] or (
            resolved["strategy"] != context["template"].model_dump(mode="json")
            or resolved["app"] != context["app"].model_dump(mode="json")
        ):
            raise ValueError("Frozen resolved run differs from previous region/profile")
        signature = dict(
            periods=evidence["plan"]["historical_challenge"],
            datasets=[(d["dataset_id"], d["parquet_sha256"]) for d in resolved["datasets"]],
            execution=resolved["execution"],
            app=resolved["app"],
            risk=resolved["strategy"]["risk"],
            code=evidence["provenance"]["code_sha256"],
        )
        if common is not None and common != signature:
            raise ValueError("Incompatible historical source assumptions/code")
        common = signature
        market = spec.markets[0]
        info = inspect_bundle(path.parent, market)
        if signature["datasets"] != [(info["dataset_id"], info["parquet_sha256"])]:
            raise ValueError("Historical dataset differs from execution")
        if data is None:
            data = load_bundle(info)
            data_hashes = {
                str(Path(info["path"]) / n): sha256(Path(info["path"]) / n)
                for n in ("candles.parquet", "manifest.json")
            }
        views = {
            label: regime_features(window(data, market, period)[0])
            for label, period in spec.historical_challenge.periods()
        }
        sources.append(
            run_metadata(evidence, root, None)
            | dict(
                family=family,
                original_plan=evidence["plan"],
                resolved_strategy=resolved["strategy"],
                resolved_candidates=resolved["candidates"],
                app=resolved["app"],
                git_status=evidence["provenance"].get("git_status"),
                frozen_protocol=lock,
                protocol_sha256=lock_hash,
                previous_source=previous[family],
                evidence_scope=WARNING,
            )
        )
        for raw in evidence["metrics"].to_dict("records"):
            clean = {k: v for k, v in raw.items() if not (isinstance(v, float) and np.isnan(v))}
            ref = verify_record(evidence["path"], clean, ledger_hashes)
            refs.append(ref)
            saved = read_json(Path(ref["folder"]) / "result.json")
            metrics, trades = saved["metrics"], saved["trades"]
            if (metrics["symbol"], metrics["timeframe"], metrics["mode"]) != (
                "ETHUSDT",
                "1h",
                "SHORT_ONLY",
            ):
                raise ValueError("Unexpected historical trade scope")
            out = {k: metrics.get(k) for k in (*COMPACT_COLUMNS, *ADDED_COLUMNS)}
            costs = (
                metrics["fees_paid"]
                + metrics["slippage_cost_closed_trades"]
                + metrics["spread_cost_closed_trades"]
            )
            out |= dict(
                family=family,
                experiment_id=name,
                run_id=evidence["header"]["run_id"],
                backtest_id=metrics["backtest_id"],
                year=int(metrics["period"].rsplit("_", 1)[1]),
                total_modeled_costs=costs,
                average_cost_per_trade=costs / len(trades) if trades else None,
                long_contribution=sum(t["net_pnl"] for t in trades if t["side"] == "long"),
                short_contribution=sum(t["net_pnl"] for t in trades if t["side"] == "short"),
                **distribution(trades),
                **pnl_statistics([t["net_pnl"] for t in trades]),
            )
            out["parameters"] = json.dumps(metrics["parameters"], sort_keys=True)
            rows.append(out)
            identity = {k: out[k] for k in IDENTITY}
            regimes.extend(regime_rows(identity, tag_trades(trades, views[metrics["period"]])))
            outliers.extend(outlier_rows(identity, trades))
        evidences.append(evidence)
    assert_references(refs)
    for evidence in evidences:
        assert_unchanged(evidence)
    if any(sha256(Path(p)) != digest for p, digest in data_hashes.items()):
        raise ValueError("Historical dataset changed")
    check_lock(root)
    frame = pd.DataFrame(rows)
    card, paired = scorecard(frame), costs_comparison(frame)
    table = frame[
        [
            *IDENTITY,
            "closed_trades",
            "winners",
            "losers",
            "breakeven_trades",
            "win_rate_pct",
            "average_win",
            "average_loss",
            "median_net_pnl",
            *ADDED_COLUMNS,
        ]
    ]
    tables = {
        "summary.csv": frame,
        "year_comparison.csv": card,
        "strategy_comparison.csv": strategy_comparison(card),
        "falsification_scorecard.csv": card,
        "base_adverse_comparison.csv": paired,
        "parameter_robustness.csv": neighbors(frame),
        "trade_distribution.csv": table,
        "outlier_dependency.csv": pd.DataFrame(outliers),
        "regime_comparison.csv": pd.DataFrame(regimes),
    }
    directory = root / "reports/eth-short-history" / new_id()
    directory.mkdir(parents=True, exist_ok=False)
    for name, table in tables.items():
        table.to_csv(directory / name, index=False, mode="x")
    write_json(directory / "sources.json", sources)
    write_json(
        directory / "audit.json",
        dict(references=refs, dataset_hashes=data_hashes, protocol_sha256=lock_hash),
    )
    reference = pd.read_csv(root / lock["previous_publication"] / "strategy_comparison.csv")
    (directory / "conclusions.md").write_text(
        conclusions(card, paired, reference), encoding="utf-8"
    )
    write_json(
        directory / "outcome.json",
        dict(
            status="COMPLETE",
            study=STUDY,
            backtests_executed=0,
            sha256={n: sha256(directory / n) for n in (*EXPORTS, "audit.json")},
        ),
    )
    return directory


def publish(root: Path, identifier="latest", max_bytes=5_000_000) -> dict:
    check_lock(root)
    base = root / "reports/eth-short-history"
    if identifier == "latest":
        found = sorted(base.glob("*/outcome.json"))
        if not found:
            raise ValueError("No historical falsification reports")
        identifier = found[-1].parent.name
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", identifier):
        raise ValueError("Expected report ID")
    directory = base / identifier
    outcome = read_json(directory / "outcome.json")
    if (
        outcome.get("status") != "COMPLETE"
        or outcome.get("study") != STUDY
        or outcome.get("backtests_executed") != 0
    ):
        raise ValueError("Incomplete historical report")
    if set(outcome["sha256"]) != {*EXPORTS, "audit.json"} or any(
        sha256(directory / n) != digest for n, digest in outcome["sha256"].items()
    ):
        raise ValueError("Historical report allowlist/hash mismatch")
    sources, audit = read_json(directory / "sources.json"), read_json(directory / "audit.json")
    if audit["protocol_sha256"] != sha256(root / LOCK):
        raise ValueError("Historical protocol changed")
    for source in sources:
        if completed_run(root, source["run_id"])["source_sha256"] != source["source_sha256"]:
            raise ValueError("Historical run changed")
    assert_references(audit["references"])
    if any(sha256(Path(p)) != digest for p, digest in audit["dataset_hashes"].items()):
        raise ValueError("Historical dataset changed")
    payloads = {
        n: json_bytes(sources, root) if n == "sources.json" else (directory / n).read_bytes()
        for n in EXPORTS
    }
    if any(len(v) > max_bytes for v in payloads.values()):
        raise ValueError("Compact report exceeds file limit; increase --max-file-mb")
    return publish_files(
        root / "research_results/trend_expansion/eth_short_historical_falsification" / identifier,
        payloads,
        dict(
            study=STUDY,
            sources=sources,
            report_id=identifier,
            evidence_scope=WARNING,
            report_sha256=outcome["sha256"],
        ),
        root,
        max_bytes,
    )


def main(root: Path, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="lab.py eth-short-history", description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    validator = commands.add_parser("validate")
    validator.add_argument("--full", action="store_true")
    runner = commands.add_parser("run", help="Heavy local execution of one frozen family")
    runner.add_argument("experiment", choices=EXPERIMENTS)
    reporter = commands.add_parser("compare", aliases=["report"])
    reporter.add_argument("--runs", nargs=2, metavar="RUN_ID")
    publisher = commands.add_parser("publish")
    publisher.add_argument("identifier", nargs="?", default="latest")
    publisher.add_argument("--max-file-mb", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        if args.action == "validate":
            result = validate(root, args.full)
        elif args.action == "run":
            result = dict(run_directory=str(run_one(root, args.experiment)))
        elif args.action in ("compare", "report"):
            result = dict(report_directory=str(report(root, args.runs)), backtests_executed=0)
        else:
            result = publish(root, args.identifier, int(args.max_file_mb * 1_000_000))
        print(json.dumps(result, indent=2, default=str, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
