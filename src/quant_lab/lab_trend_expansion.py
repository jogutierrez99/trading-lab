"""Trend Expansion protocol around existing lab runs, audits and bounded publication."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from quant_lab.config import StrategyConfig
from quant_lab.experiments import provenance, write_json
from quant_lab.lab_evidence import assert_unchanged, completed_run, new_id, read_json, sha256
from quant_lab.lab_publish import COMPACT_COLUMNS, json_bytes, publish_files, run_metadata
from quant_lab.lab_resume import compatible_code
from quant_lab.lab_robustness import assert_references, parameters, verify_record
from quant_lab.lab_runner import prepare
from quant_lab.lab_schema import Experiment, resolve
from quant_lab.strategies.registry import StrategyRegistry

FAMILIES = ("pullback", "atr", "donchian", "donchian_atr")
EXPERIMENTS = tuple(f"trend_expansion_entry_{family}_v1" for family in FAMILIES)
EXPORTS = (
    "experiment_manifest.csv",
    "summary.csv",
    "family_comparison.csv",
    "long_short_comparison.csv",
    "base_adverse_comparison.csv",
    "parameter_robustness.csv",
    "trade_distribution.csv",
    "conclusions.md",
    "sources.json",
)
WARNING = (
    "Estas pruebas constituyen investigaci\u00f3n hist\u00f3rica y "
    "generaci\u00f3n/falsaci\u00f3n de hip\u00f3tesis. No demuestran rentabilidad futura "
    "ni constituyen por s\u00ed mismas aprobaci\u00f3n para paper/live trading."
)
ADDED_COLUMNS = (
    "payoff_ratio",
    "average_cost_per_trade",
    "median_winner",
    "median_loser",
    "pnl_p01",
    "pnl_p05",
    "pnl_p50",
    "pnl_p95",
    "pnl_p99",
    "top_1pct_net_pnl",
    "top_5pct_net_pnl",
    "top_10pct_net_pnl",
    "top_1pct_net_share_pct",
    "top_5pct_net_share_pct",
    "top_10pct_net_share_pct",
    "net_pnl_without_best",
    "single_best_net_pnl",
    "long_expectancy",
    "short_expectancy",
    "long_profit_factor",
    "short_profit_factor",
)


def validate(root, full=False):
    rows = []
    for name in EXPERIMENTS:
        path, exp = resolve(root / "configs/experiments", name)
        context = prepare(path, exp, full=full)
        rows.append(
            dict(
                experiment=name,
                configurations=len(context["parameters"]),
                backtests=context["backtests"],
            )
        )
    return dict(
        status="VALID",
        validation="FULL" if full else "FAST",
        experiments=rows,
        backtests=sum(r["backtests"] for r in rows),
        backtests_executed=0,
    )


def distribution(trades):
    pnl = pd.Series([t["net_pnl"] for t in trades], dtype=float)
    winners, losers = pnl[pnl > 0], pnl[pnl < 0]
    n, total = len(pnl), float(pnl.sum())
    ordered = pnl.sort_values(ascending=False)
    out = dict(
        median_winner=float(winners.median()) if len(winners) else None,
        median_loser=float(losers.median()) if len(losers) else None,
        payoff_ratio=float(winners.mean() / -losers.mean())
        if len(winners) and len(losers)
        else None,
        single_best_net_pnl=float(ordered.iloc[0]) if n else None,
        net_pnl_without_best=total - float(ordered.iloc[0]) if n else None,
    )
    for q in (1, 5, 50, 95, 99):
        out[f"pnl_p{q:02d}"] = float(pnl.quantile(q / 100)) if n else None
    for pct in (1, 5, 10):
        count = int(np.ceil(n * pct / 100))
        amount = float(ordered.iloc[:count].sum()) if n else None
        out[f"top_{pct}pct_net_pnl"] = amount
        out[f"top_{pct}pct_net_share_pct"] = 100 * amount / total if n and total > 0 else None
    for side in ("long", "short"):
        values = [t["net_pnl"] for t in trades if t["side"] == side]
        gains, losses = sum(max(v, 0) for v in values), -sum(min(v, 0) for v in values)
        out[f"{side}_expectancy"] = sum(values) / len(values) if values else None
        out[f"{side}_profit_factor"] = gains / losses if losses else None
    return out


def region_neighbors(frame):
    # One coordinate at a time, consecutive predeclared values, TRAIN/base only.
    train = frame[(frame.period == "train") & (frame.scenario == "base")]
    rows = []
    for identity, group in train.groupby(["family", "symbol", "timeframe", "mode"], sort=True):
        records = group.to_dict("records")
        decoded = [parameters(r["parameters"]) for r in records]
        keys = sorted(decoded[0])
        levels = {k: sorted({json.dumps(p[k], sort_keys=True) for p in decoded}) for k in keys}
        for i, first in enumerate(records):
            for j in range(i + 1, len(records)):
                differing = [k for k in keys if decoded[i][k] != decoded[j][k]]
                if len(differing) != 1:
                    continue
                key = differing[0]
                values = levels[key]
                # Numerical ordering instead of lexical ordering.
                values = sorted(json.loads(v) for v in values)
                if abs(values.index(decoded[i][key]) - values.index(decoded[j][key])) != 1:
                    continue
                second = records[j]
                row = dict(zip(("family", "symbol", "timeframe", "mode"), identity, strict=True))
                row |= dict(
                    parameter=key,
                    value_a=decoded[i][key],
                    value_b=decoded[j][key],
                    configuration_a=first["configuration_id"],
                    configuration_b=second["configuration_id"],
                    period="train",
                    scenario="base",
                )
                for metric in (
                    "expectancy",
                    "profit_factor",
                    "return_pct",
                    "max_drawdown_pct",
                    "closed_trades",
                ):
                    row[metric + "_a"], row[metric + "_b"] = first[metric], second[metric]
                row["both_positive_expectancy"] = bool(
                    pd.notna(first["expectancy"])
                    and pd.notna(second["expectancy"])
                    and first["expectancy"] > 0
                    and second["expectancy"] > 0
                )
                rows.append(row)
    return pd.DataFrame(
        rows,
        columns=[
            "family",
            "symbol",
            "timeframe",
            "mode",
            "parameter",
            "value_a",
            "value_b",
            "configuration_a",
            "configuration_b",
            "period",
            "scenario",
            *[
                m + s
                for m in (
                    "expectancy",
                    "profit_factor",
                    "return_pct",
                    "max_drawdown_pct",
                    "closed_trades",
                )
                for s in ("_a", "_b")
            ],
            "both_positive_expectancy",
        ],
    )


def descriptive_families(frame):
    metrics = [
        c
        for c in (
            "return_pct",
            "max_drawdown_pct",
            "expectancy",
            "profit_factor",
            "closed_trades",
            "sharpe",
            "sortino",
            "average_close_exposure_pct",
            "total_modeled_costs",
        )
        if c in frame
    ]
    keys = ["family", "symbol", "timeframe", "mode", "period", "scenario"]
    groups = frame.groupby(keys, sort=True, dropna=False)
    medians = groups[metrics].median().rename(columns=lambda c: "median_" + c)
    return medians.join(groups.size().rename("configurations")).reset_index()


def paired_costs(frame):
    keys = [
        "family",
        "experiment_id",
        "run_id",
        "configuration_id",
        "symbol",
        "timeframe",
        "mode",
        "period",
    ]
    metrics = [
        "return_pct",
        "expectancy",
        "profit_factor",
        "max_drawdown_pct",
        "closed_trades",
        "total_modeled_costs",
    ]
    base = frame[frame.scenario == "base"][keys + metrics]
    adverse = frame[frame.scenario == "adverse"][keys + metrics]
    out = base.merge(
        adverse,
        on=keys,
        suffixes=("_base", "_adverse"),
        validate="one_to_one",
        how="outer",
        indicator=True,
    )
    if not out._merge.eq("both").all():
        raise ValueError("Missing matched BASE/ADVERSE cell")
    for metric in metrics:
        out[metric + "_delta"] = out[metric + "_adverse"] - out[metric + "_base"]
    return out.drop(columns="_merge")


def conclusions(frame):
    headings = (
        "Scope",
        "Strategies",
        "Markets",
        "Periods",
        "Cost assumptions",
        "Results",
        "LONG vs SHORT",
        "BTC vs ETH",
        "BASE vs ADVERSE",
        "Parameter robustness",
        "Trade distribution / convexity",
        "Failure modes",
        "Survivors",
        "Rejected hypotheses",
        "Limitations",
        "Next recommended experiment",
    )
    content = {
        "Scope": WARNING
        + "\n\nReused historical evidence; no independent new holdout and no automatic winner.",
        "Strategies": (
            "Pullback: unchanged ema_pullback, LONG_ONLY with original EMA signal"
            " exit. Other three families share ATR14 x2 / 2R baseline; hybrid "
            "reuses frozen entry implementation."
        ),
        "Markets": (
            "BTCUSDT and ETHUSDT 1h. Synthetic collateralized execution on USD-M "
            "prices; funding/borrow/liquidations not modelled."
        ),
        "Periods": (
            "Frozen ordinary train/validation/test and four TRAIN-selected WF "
            "folds. Capital resets per period. WF TEST belongs to adaptive "
            "selection, not each fixed candidate; overlapping windows must not be"
            " pooled."
        ),
        "Cost assumptions": (
            "BASE fee/slippage/full spread: 0.05/0.03/0.01%. ADVERSE: "
            "0.10/0.06/0.02%. Fees both sides and half-spread per fill."
        ),
        "Results": (
            "Descriptive per-family medians in family_comparison.csv; every cell "
            "in summary.csv. No ROI winner or automatic eligibility.\n\n"
        )
        + "\n\n".join(
            f"### {label}\n\n{len(frame[frame.family == family])} audited cells; "
            "human interpretation pending."
            for family, label in zip(
                FAMILIES,
                ("Trend Pullback", "ATR Volatility Breakout", "Donchian", "Donchian + ATR"),
                strict=True,
            )
        ),
        "LONG vs SHORT": (
            "Inspect long_short_comparison.csv. Pullback SHORT/combined "
            "unsupported; absent rows are not zero results. Combined side PnL is "
            "not independent side return/DD."
        ),
        "BTC vs ETH": (
            "Inspect family_comparison.csv by symbol; no cross-asset pooling or portfolio."
        ),
        "BASE vs ADVERSE": (
            "Paired actual reruns in base_adverse_comparison.csv; "
            "costs can change sizing and trades."
        ),
        "Parameter robustness": (
            "Adjacent one-coordinate TRAIN/base neighbors only; full regions "
            "predeclared. Inspect parameter_robustness.csv, not isolated best "
            "TEST cells. Benchmark has one frozen configuration."
        ),
        "Trade distribution / convexity": (
            "trade_distribution.csv contains net-PnL quantiles and top "
            "ceil(N*pct/100) trades. Net shares null for total net PnL <= 0 and "
            "may exceed 100% otherwise. Removing the best PnL is a descriptive "
            "sum, not a resimulation or reconstructed DD."
        ),
        "Failure modes": (
            "Review expectancy, PF, trade sufficiency, DD, missing metrics, "
            "asymmetric sides, unstable TRAIN neighbors and outlier dependence "
            "together. Undefined values remain empty."
        ),
        "Survivors": (
            "PENDING HUMAN REVIEW. No survivor selected automatically; justify "
            "sufficient evidence before preparing exit experiments."
        ),
        "Rejected hypotheses": "PENDING HUMAN REVIEW. No hard-coded new approval/rejection rule.",
        "Limitations": (
            "OHLC ordering unknown: next-open decisions, stop-first and close-"
            "based trailing effective next bar. Benchmark has different signal "
            "exit/RSI and only LONG; entry attribution is approximate. Multiple "
            "comparisons, reused history, synthetic shorts, gaps rejected "
            "including warmup. No independent inference from adaptive WF winner "
            "to fixed parameters. Correlation deferred."
        ),
        "Next recommended experiment": (
            "After explicit evidence review, freeze a source run/configuration "
            "with prepare-exits; compare only four exit architectures without "
            "retuning entry parameters. Reused TEST remains exploratory. Future "
            "independent evidence requires a separate protocol."
        ),
    }
    return (
        "# Trend Expansion V1 conclusions\n\n"
        + "\n\n".join(f"## {h}\n\n{content[h]}" for h in headings)
        + "\n"
    )


def report(root, identifiers=None):
    identifiers = identifiers or list(EXPERIMENTS)
    if len(identifiers) != 4 or len(set(identifiers)) != 4:
        raise ValueError(
            "Provide four distinct runs in pullback, atr, donchian, donchian_atr order"
        )
    sources, rows, refs, evidence_sources = [], [], [], []
    common = None
    ledger_hashes = {}
    for family, expected, identifier in zip(FAMILIES, EXPERIMENTS, identifiers, strict=True):
        evidence = completed_run(root, identifier)
        evidence_sources.append(evidence)
        if evidence["header"]["experiment_id"] != expected:
            raise ValueError("Unexpected Trend Expansion experiment/order")
        _, definition = resolve(root / "configs/experiments", expected)
        if definition.model_dump(mode="json") != evidence["plan"]:
            raise ValueError("Frozen run plan differs from current experiment definition")
        # Comparable data, periods, costs, execution, capital and risk across families.
        resolved = evidence["resolved"]
        signature = dict(
            validation=evidence["plan"]["validation"],
            datasets=[
                (d["symbol"], d["timeframe"], d["dataset_id"], d["parquet_sha256"])
                for d in resolved["datasets"]
            ],
            execution=resolved["execution"],
            app=resolved["app"],
            risk=resolved["strategy"]["risk"],
            code=evidence["provenance"]["code_sha256"],
        )
        if common is not None and signature != common:
            raise ValueError("Incompatible periods/datasets/costs/risk/code across family sources")
        common = signature
        sources.append(
            run_metadata(evidence, root, None)
            | dict(
                family=family,
                parameters=resolved["parameters"],
                original_plan=evidence["plan"],
                resolved_strategy=resolved["strategy"],
                parameter_risks=resolved.get("parameter_risks"),
                app=resolved["app"],
                git_status=evidence["provenance"].get("git_status"),
            )
        )
        for row in evidence["metrics"].to_dict("records"):
            clean = {k: v for k, v in row.items() if not (isinstance(v, float) and np.isnan(v))}
            ref = verify_record(evidence["path"], clean, ledger_hashes)
            refs.append(ref)
            document = read_json(Path(ref["folder"]) / "result.json")
            saved = document["metrics"]
            trades = document["trades"]
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
            out["parameters"] = json.dumps(saved["parameters"], sort_keys=True)
            rows.append(out)
        assert_unchanged(evidence)
    assert_references(refs)
    for evidence in evidence_sources:
        assert_unchanged(evidence)
    frame = pd.DataFrame(rows)
    tables = {
        "summary.csv": frame,
        "family_comparison.csv": descriptive_families(frame),
        "long_short_comparison.csv": frame[
            [
                c
                for c in (
                    "family",
                    "experiment_id",
                    "run_id",
                    "configuration_id",
                    "symbol",
                    "timeframe",
                    "mode",
                    "period",
                    "scenario",
                    "long_trades",
                    "short_trades",
                    "long_contribution",
                    "short_contribution",
                    "long_expectancy",
                    "short_expectancy",
                    "long_profit_factor",
                    "short_profit_factor",
                )
                if c in frame
            ]
        ],
        "base_adverse_comparison.csv": paired_costs(frame),
        "parameter_robustness.csv": region_neighbors(frame),
        "trade_distribution.csv": frame[
            [
                c
                for c in (
                    "family",
                    "run_id",
                    "backtest_id",
                    "configuration_id",
                    "symbol",
                    "timeframe",
                    "mode",
                    "period",
                    "scenario",
                    "closed_trades",
                    *ADDED_COLUMNS,
                )
                if c in frame
            ]
        ],
        "experiment_manifest.csv": pd.DataFrame(
            [
                dict(
                    family=s["family"],
                    experiment_id=s["experiment"],
                    run_id=s["run_id"],
                    strategy=s["strategy"],
                    version=s["strategy_version"],
                    code_sha256=s["code_hash"],
                    git_revision=s["git_commit"],
                    configurations=len(s["parameters"]),
                )
                for s in sources
            ]
        ),
    }
    directory = root / "reports/trend-expansion" / new_id()
    directory.mkdir(parents=True, exist_ok=False)
    for name, table in tables.items():
        table.to_csv(directory / name, index=False, mode="x")
    write_json(directory / "sources.json", sources)
    write_json(directory / "audit.json", refs)
    (directory / "conclusions.md").write_text(conclusions(frame), encoding="utf-8")
    write_json(
        directory / "outcome.json",
        dict(
            status="COMPLETE",
            report_id=directory.name,
            backtests_executed=0,
            source_rows=len(frame),
            sha256={n: sha256(directory / n) for n in (*EXPORTS, "audit.json")},
        ),
    )
    return directory


def publish(root, identifier="latest", max_bytes=5_000_000):
    base = root / "reports/trend-expansion"
    if identifier == "latest":
        found = sorted(base.glob("*/outcome.json"))
        if not found:
            raise ValueError("No Trend Expansion reports")
        identifier = found[-1].parent.name
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", identifier):
        raise ValueError("Expected report ID")
    directory = base / identifier
    outcome = read_json(directory / "outcome.json")
    if outcome.get("status") != "COMPLETE" or outcome.get("backtests_executed") != 0:
        raise ValueError("Incomplete Trend Expansion report")
    if set(outcome["sha256"]) != {*EXPORTS, "audit.json"}:
        raise ValueError("Report allowlist mismatch")
    if any(sha256(directory / n) != digest for n, digest in outcome["sha256"].items()):
        raise ValueError("Trend Expansion report hash mismatch")
    sources = read_json(directory / "sources.json")
    for source in sources:
        evidence = completed_run(root, source["run_id"])
        if evidence["source_sha256"] != source["source_sha256"]:
            raise ValueError("Trend Expansion source changed")
    assert_references(read_json(directory / "audit.json"))
    payloads = {
        n: json_bytes(sources, root) if n == "sources.json" else (directory / n).read_bytes()
        for n in EXPORTS
    }
    # Mandatory compact set: never silently omit a comparison due to file limits.
    if any(len(v) > max_bytes for v in payloads.values()):
        raise ValueError("Compact report exceeds file limit; increase --max-file-mb")
    return publish_files(
        root / "research_results/trend_expansion" / identifier,
        payloads,
        dict(
            report_id=identifier,
            sources=sources,
            evidence_scope=(
                "REUSED_HISTORY_EXPLORATORY; no automatic survivor or paper/live approval"
            ),
            report_sha256=outcome["sha256"],
        ),
        root,
        max_bytes,
    )


def prepare_exits(root, run_id, configuration_id, decision, experiment_prefix):
    """Freeze exactly one human-nominated entry; never select from a performance table."""
    evidence = completed_run(root, run_id)
    if evidence["header"]["experiment_id"] not in EXPERIMENTS[1:]:
        raise ValueError("Exit research supports only the three comparable breakout families")
    _, definition = resolve(root / "configs/experiments", evidence["header"]["experiment_id"])
    if definition.model_dump(mode="json") != evidence["plan"]:
        raise ValueError("Source plan differs from the frozen entry definition")
    compatible_code(evidence["provenance"], provenance(root))
    cells = evidence["metrics"]
    candidates = cells[
        (cells.configuration_id == configuration_id)
        & (cells.period == "train")
        & (cells.scenario == "base")
    ]
    if len(candidates) != 1 or not decision.strip():
        raise ValueError(
            "Require one source TRAIN configuration and explicit human decision rationale"
        )
    row = candidates.iloc[0].to_dict()
    ref = verify_record(
        evidence["path"],
        {k: v for k, v in row.items() if not (isinstance(v, float) and np.isnan(v))},
    )
    original = read_json(Path(ref["folder"]) / "result.json")["metrics"]
    p = original["parameters"]
    outputs = []
    pending = []
    for method, take_profit, trailing, signal in (
        ("fixed_rr", True, None, "risk"),
        ("atr_trailing", True, 2.0, "risk"),
        ("donchian_exit", False, None, "donchian"),
        ("atr_trailing_no_tp", False, 2.0, "risk"),
    ):
        name = experiment_prefix + "_" + method
        profile = root / "configs/profiles/trend_expansion" / (name + ".yaml")
        experiment_path = root / "configs/experiments" / (name + ".yaml")
        risk = evidence["resolved"]["strategy"]["risk"] | dict(
            take_profit_enabled=take_profit,
            trailing_atr_multiplier=trailing,
            trailing_basis="close",
        )
        profile_raw = evidence["resolved"]["strategy"] | dict(
            parameters=p | dict(exit_method=signal), risk=risk
        )
        plan = evidence["plan"] | dict(
            experiment_id=name,
            created_at=datetime.now(UTC),
            description=(
                "Exit research after explicit human nomination; "
                "reused history, not independent holdout. "
            )
            + decision,
            strategy=dict(
                id=profile_raw["name"], config="../profiles/trend_expansion/" + profile.name
            ),
            markets=[
                m
                for m in evidence["plan"]["markets"]
                if (m["symbol"], m["timeframe"]) == (row["symbol"], row["timeframe"])
            ],
            modes=[row["mode"]],
            strategy_parameters={k: [v] for k, v in profile_raw["parameters"].items()},
        )
        # Stored plans are JSON: strict Python validation does not parse date strings.
        exp = Experiment.model_validate_json(json.dumps(plan, default=str))
        StrategyRegistry().discover().create(StrategyConfig.model_validate(profile_raw))
        pending.extend(((profile, profile_raw), (experiment_path, exp.model_dump())))
        outputs.append(exp.experiment_id)
    receipt = root / "configs/profiles/trend_expansion" / (experiment_prefix + "_freeze.json")
    if any(path.exists() for path, _ in pending) or receipt.exists():
        raise FileExistsError("Exit experiment/profile/freeze already exists")
    assert_unchanged(evidence)
    assert_references([ref])
    for path, raw in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            yaml.safe_dump(raw, handle, sort_keys=False)
    write_json(
        receipt,
        dict(
            source=run_metadata(evidence, root, None),
            configuration_id=configuration_id,
            entry_parameters=p,
            decision=decision,
            selection_basis=(
                "explicit human nomination; no code selection; must not use TEST to retune"
            ),
            experiments=outputs,
        ),
    )
    return dict(experiments=outputs, freeze=str(receipt), backtests_executed=0)


def main(argv: list[str] | None = None) -> int:
    """Add protocol commands at the entrypoint without editing hash-frozen lab_cli."""
    import argparse
    import sys

    from quant_lab.lab_cli import main as ordinary_main

    argv = list(sys.argv[1:] if argv is None else argv)
    prefix = argparse.ArgumentParser(add_help=False)
    prefix.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    options, remaining = prefix.parse_known_args(argv)
    if remaining and remaining[0] == "eth-short-regime":
        from quant_lab.lab_eth_short_regime import main as regime_main

        return regime_main(options.root.resolve(), remaining[1:])
    if not remaining or remaining[0] != "trend-expansion":
        # Preserve the original CLI and its frozen protocols exactly.
        return ordinary_main(argv)
    parser = argparse.ArgumentParser(prog="lab.py trend-expansion", description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    validator = commands.add_parser("validate")
    validator.add_argument("--full", action="store_true")
    reporter = commands.add_parser("report")
    reporter.add_argument("--runs", nargs=4, metavar="RUN_ID")
    publisher = commands.add_parser("publish")
    publisher.add_argument("identifier", nargs="?", default="latest")
    publisher.add_argument("--max-file-mb", type=float, default=5.0)
    exits = commands.add_parser(
        "prepare-exits", help="Freeze a human-nominated entry; no simulation"
    )
    exits.add_argument("--run", required=True)
    exits.add_argument("--configuration", required=True)
    exits.add_argument("--decision", required=True)
    exits.add_argument("--id", required=True)
    args = parser.parse_args(remaining[1:])
    root = options.root.resolve()
    try:
        if args.action == "validate":
            result = validate(root, full=args.full)
        elif args.action == "report":
            result = dict(report_directory=str(report(root, args.runs)))
        elif args.action == "publish":
            result = publish(root, args.identifier, int(args.max_file_mb * 1_000_000))
        else:
            result = prepare_exits(root, args.run, args.configuration, args.decision, args.id)
        print(json.dumps(result, indent=2, default=str, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
