"""Frozen RMM challenge: ordinary lab execution, read-only compact diagnostics.

No optimizer, backtest engine, promotion or operational integration lives here.
"""

import json
import math
from pathlib import Path

import pandas as pd
import yaml

from quant_lab.config import _read_mapping, load_yaml
from quant_lab.experiments import write_json
from quant_lab.lab_evidence import assert_unchanged, completed_run, new_id, sha256
from quant_lab.lab_resume import Recovery, canonical
from quant_lab.lab_runner import prepare
from quant_lab.lab_schema import Experiment

FOLDER = "research_results/risk_managed_momentum_v1_final_falsification"
LOCK = "configs/research/rmm_falsification_v1.yaml"
VARIANTS = ("scaled_180", "fixed_180", "scaled_150", "scaled_210")
METRICS = (
    "return_pct",
    "cagr_pct",
    "sharpe",
    "sortino",
    "max_drawdown_pct",
    "profit_factor",
    "expectancy",
    "closed_trades",
    "annualized_volatility_pct",
    "average_close_exposure_pct",
    "long_contribution",
    "short_contribution",
    "long_trades",
    "short_trades",
    "fees_paid",
    "slippage_cost_closed_trades",
    "spread_cost_closed_trades",
    "total_modeled_costs",
    "realized_net_pnl",
    "average_entry_scaling_pct",
)
IDENTITY = (
    "candidate",
    "variant",
    "symbol",
    "timeframe",
    "mode",
    "period",
    "scenario",
    "start",
    "end",
    "run_id",
    "backtest_id",
)


def frozen(root: Path) -> dict:
    lock = _read_mapping(root / LOCK)
    if sha256(root / FOLDER / "frozen_candidates.yaml") != lock["frozen_sha256"]:
        raise ValueError("Frozen candidates/criteria changed; create a new challenge version")
    spec = _read_mapping(root / FOLDER / "frozen_candidates.yaml")
    for name, expected in spec["file_sha256"].items():
        if sha256(root / name) != expected:
            raise ValueError(f"Frozen protocol changed: {name}; create a new challenge version")
    if tuple(spec["experiments"]) != VARIANTS:
        raise ValueError("Frozen variant order mismatch")
    return spec


def validate(root: Path, full: bool = False) -> dict:
    spec = frozen(root)
    entries = []
    for variant, plan in spec["experiments"].items():
        path = root / "configs/experiments" / (plan["experiment_id"] + ".yaml")
        exp = load_yaml(path, Experiment)
        if exp.model_dump(mode="json") != plan:
            raise ValueError("Frozen experiment mismatch")
        context = prepare(path, exp, full=full)
        entries.append(
            dict(variant=variant, experiment_id=exp.experiment_id, backtests=context["backtests"])
        )
    return dict(
        status="VALID",
        validation="FULL" if full else "FAST",
        experiments=entries,
        backtests=sum(e["backtests"] for e in entries),
        note="No backtests executed; POST-SELECTION FALSIFICATION / ROBUSTNESS CHALLENGE",
    )


def concentration(pnl: list[float]) -> dict:
    """Arithmetic deletion only: no equity, resimulation or counterfactual Sharpe."""
    profits = sorted((p for p in pnl if p > 0), reverse=True)
    total, gross = sum(pnl), sum(profits)
    result = dict(
        total_trades=len(pnl),
        net_pnl=total,
        gross_positive_pnl=gross,
        worst_trade_pnl=min(pnl) if pnl else None,
        diagnostic="DESCRIPTIVE_DELETION_NOT_EXECUTABLE_BACKTEST",
    )
    for n in (1, 3, 5):
        top = sum(profits[:n])
        result |= {
            f"top_{n}_pnl": top,
            f"top_{n}_net_profit_share_pct": 100 * top / total if total > 0 else None,
            f"top_{n}_gross_profit_share_pct": 100 * top / gross if gross else None,
            f"leave_top_{n}_out_pnl": total - top,
            f"removed_top_{n}_trades": min(n, len(profits)),
        }
    return result


def wf_summary(table: pd.DataFrame) -> pd.DataFrame:
    tests = table[table.period.str.fullmatch(r"wf_\d+_test")]
    summaries = []
    for key, group in tests.groupby(["candidate", "variant", "scenario"], sort=True):
        values = group.return_pct
        row = dict(zip(("candidate", "variant", "scenario"), key, strict=True))
        row |= dict(
            folds=len(group),
            positive_folds=int((values > 0).sum()),
            negative_folds=int((values < 0).sum()),
            zero_folds=int((values == 0).sum()),
            worst_return_pct=values.min(),
            best_return_pct=values.max(),
            return_std_pct=values.std(ddof=1),
            return_iqr_pct=values.quantile(0.75) - values.quantile(0.25),
        )
        for metric in METRICS:
            row["median_" + metric] = (
                group[metric].median() if group[metric].notna().any() else None
            )
        summaries.append(row)
    return pd.DataFrame(summaries)


def ablation(table: pd.DataFrame, timing: dict) -> pd.DataFrame:
    keys = ["candidate", "period", "scenario"]
    left = table[table.variant == "scaled_180"]
    right = table[table.variant == "fixed_180"]
    paired = left.merge(right, on=keys, suffixes=("_scaled", "_fixed"), validate="one_to_one")
    for metric in METRICS:
        paired["scaled_minus_fixed_" + metric] = (
            paired[metric + "_scaled"] - paired[metric + "_fixed"]
        )
    fixed_exposure = paired.average_close_exposure_pct_fixed
    paired["scaled_to_fixed_exposure_ratio"] = (
        paired.average_close_exposure_pct_scaled / fixed_exposure.where(fixed_exposure > 0)
    )
    for suffix in ("scaled", "fixed"):
        exposure = paired["average_close_exposure_pct_" + suffix]
        for metric in ("return_pct", "max_drawdown_pct"):
            paired[metric + "_per_exposure_" + suffix] = paired[
                metric + "_" + suffix
            ] / exposure.where(exposure > 0)
    paired["trade_timing_identical"] = [
        timing[a] == timing[b]
        for a, b in zip(paired.backtest_id_scaled, paired.backtest_id_fixed, strict=True)
    ]
    return paired


def guidelines(table, wf, concentrations, paired, spec):
    """Predeclared adverse evidence flags, never an automatic demo approval."""
    results = {}
    rules = spec["guidelines"]
    for candidate in spec["candidates"]:
        core = table[(table.candidate == candidate) & (table.variant == "scaled_180")]
        main = core[core.period.isin(["train", "validation", "test"])]
        flags = []
        for scenario in ("base", "adverse"):
            fold = wf[
                (wf.candidate == candidate)
                & (wf.variant == "scaled_180")
                & (wf.scenario == scenario)
            ].iloc[0]
            if fold.negative_folds > fold.folds / 2:
                flags.append("FAIL_TEMPORAL:" + scenario)
        adverse = main[main.scenario == "adverse"]
        if ((adverse.return_pct <= 0) | (adverse.expectancy <= 0)).sum() >= 2:
            flags.append("FAIL_COST")
        base = main[main.scenario == "base"]
        later = base[base.period.isin(["validation", "test"])]
        if (base[base.period == "train"].return_pct > 0).all() and (later.return_pct <= 0).all():
            flags.append("FAIL_GENERALIZATION")
        neighbors = table[
            (table.candidate == candidate)
            & table.variant.isin(["scaled_150", "scaled_210"])
            & (table.scenario == "base")
            & table.period.isin(["validation", "test"])
        ]
        if (later.return_pct > 0).all() and (neighbors.return_pct <= 0).all():
            flags.append("FAIL_ROBUSTNESS")
        pool = concentrations[
            (concentrations.candidate == candidate)
            & (concentrations.variant == "scaled_180")
            & (concentrations.period == "pooled_temporal_segments")
        ]
        fragile = (pool.net_pnl > 0) & (
            (pool.leave_top_3_out_pnl <= 0)
            | (pool.top_3_net_profit_share_pct >= rules["concentration_top3_net_share_pct"])
        )
        if fragile.any():
            flags.append("FAIL_CONCENTRATION")
        pairs = paired[
            (paired.candidate == candidate)
            & paired.period.isin(["train", "validation", "test"])
            & (paired.scenario == "base")
        ]
        ratio = pairs.scaled_to_fixed_exposure_ratio
        comparable = ratio.between(
            1 / rules["ablation_maximum_exposure_ratio"], rules["ablation_maximum_exposure_ratio"]
        ).all()
        ablation_ready = (
            comparable
            and pairs.trade_timing_identical.all()
            and pairs[["sharpe_scaled", "sharpe_fixed"]].notna().all().all()
        )
        no_risk_gain = (pairs.sharpe_scaled <= pairs.sharpe_fixed) & (
            pairs.max_drawdown_pct_scaled
            >= pairs.max_drawdown_pct_fixed * (1 - rules["ablation_dd_relative_tolerance"])
        )
        if ablation_ready and no_risk_gain.all():
            flags.append("FAIL_RISK_MANAGEMENT")
        sharpe_gain = pairs.sharpe_scaled.median() - pairs.sharpe_fixed.median()
        scaled_dd, fixed_dd = (
            pairs.max_drawdown_pct_scaled.median(),
            pairs.max_drawdown_pct_fixed.median(),
        )
        risk_improved = ablation_ready and (
            (sharpe_gain >= rules["ablation_sharpe_min_gain"] and scaled_dd <= fixed_dd * 1.05)
            or (scaled_dd <= fixed_dd * 0.95 and sharpe_gain >= 0)
        )
        sufficient = (
            base.closed_trades.sum() >= rules["minimum_temporal_trades"]
            and (main.closed_trades >= rules["minimum_period_trades"]).all()
        )
        good_main = (
            (main.return_pct > 0)
            & (main.expectancy > 0)
            & (main.profit_factor > 1)
            & (main.max_drawdown_pct <= rules["maximum_drawdown_pct"])
        ).all()
        folds = wf[(wf.candidate == candidate) & (wf.variant == "scaled_180")]
        good_wf = (folds.positive_folds > folds.folds * rules["minimum_positive_wf_fraction"]).all()
        stable = (neighbors.return_pct > 0).all()
        provisional = (
            "REJECTED"
            if flags
            else "PROMISING_BUT_UNCONFIRMED"
            if sufficient and good_main and good_wf and stable and risk_improved
            else "INCONCLUSIVE"
        )
        results[candidate] = dict(
            classification="INCONCLUSIVE",
            provisional_classification=provisional,
            review_status="HUMAN_REVIEW_REQUIRED",
            flags=flags,
            sufficient_trades=bool(sufficient),
            ablation_comparable=bool(ablation_ready),
            risk_improved=bool(risk_improved),
            demo_approved=False,
            reason="Review all diagnostics and exceptions; no automatic demo recommendation",
        )
    return results


def verified_sources(root, identifiers, spec):
    sources, audits = [], []
    for variant, identifier in zip(VARIANTS, identifiers, strict=True):
        evidence = completed_run(root, identifier)
        if evidence["plan"] != spec["experiments"][variant]:
            raise ValueError(f"Run does not match frozen {variant}")
        code = evidence["provenance"]
        saved = {k.replace("\\", "/"): v for k, v in code["files"].items()}
        if saved.get(LOCK) != sha256(root / LOCK):
            raise ValueError("Source run freeze lock mismatch; criteria changed after execution")
        if any(saved.get(k) != v for k, v in spec["file_sha256"].items()):
            raise ValueError("Source run code/config differs from frozen challenge")
        recovery = Recovery(evidence["path"], evidence["plan"], evidence["resolved"], code)
        if not recovery.already_complete():
            raise ValueError("Source ledger/results/equity incomplete or corrupt")
        exp = Experiment.model_validate_json(json.dumps(evidence["plan"]))
        context = prepare(root / "configs/experiments" / (exp.experiment_id + ".yaml"), exp)
        for key, value in (
            ("app", context["app"].model_dump(mode="json")),
            ("strategy", context["template"].model_dump(mode="json")),
            ("parameters", context["parameters"]),
            ("datasets", context["datasets"]),
            ("execution", exp.execution.model_dump(mode="json")),
        ):
            if canonical(evidence["resolved"][key]) != canonical(value):
                raise ValueError(f"Frozen resolved {key} mismatch")
        if evidence["resolved"]["backend"] != "study_backend_v1":
            raise ValueError("Frozen backend mismatch")
        expected = {
            (m.symbol, mode, label, scenario)
            for m in exp.markets
            for mode in exp.modes
            for label, _ in exp.periods()
            for scenario in ("base", "adverse")
        }
        actual = {
            (r["row"]["symbol"], r["row"]["mode"], r["row"]["period"], r["row"]["scenario"])
            for r in recovery.records.values()
        }
        if actual != expected or len(recovery.records) != len(expected):
            raise ValueError("Missing/extra frozen evidence cells")
        params = next(exp.grid())
        periods = dict(exp.periods())
        csv_rows = evidence["metrics"].set_index("backtest_id")
        for record in recovery.records.values():
            row = record["row"]
            if row["parameters"] != params or row["timeframe"] != "4h":
                raise ValueError("Frozen parameters/timeframe mismatch")
            period = periods[row["period"]]
            if (
                row["start"] != period.start.isoformat()
                or row["end"] != period.end.isoformat()
                or row["costs"] != context["scenarios"][row["scenario"]].model_dump()
            ):
                raise ValueError("Frozen period/cost mismatch")
            csv_row = csv_rows.loc[record["id"]]
            for key in ("return_pct", "closed_trades", "realized_net_pnl"):
                if not math.isclose(
                    float(csv_row[key]), float(row[key]), rel_tol=1e-10, abs_tol=1e-10
                ):
                    raise ValueError("metrics.csv differs from verified ledger result")
        sources.append((variant, evidence))
        audits.append(recovery)
    if len({e["provenance"]["code_sha256"] for _, e in sources}) != 1:
        raise ValueError("Challenge runs must use the same code/environment provenance")
    if len({canonical(e["provenance"]["dependencies"]) for _, e in sources}) != 1:
        raise ValueError("Challenge dependency mismatch")
    return sources, audits


def report(root: Path, identifiers: list[str]) -> Path:
    """Consume four explicit run IDs and publish bounded diagnostics in a new folder."""
    if len(identifiers) != 4 or any(
        identifier.startswith("rmm_") or identifier == "latest" for identifier in identifiers
    ):
        raise ValueError(
            "Supply four explicit run IDs in scaled180/fixed180/scaled150/scaled210 order"
        )
    spec = frozen(root)
    sources, audits = verified_sources(root, identifiers, spec)
    rows, concentrations, exc, timing = [], [], [], {}
    pools = {}
    for (variant, evidence), recovery in zip(sources, audits, strict=True):
        for record in recovery.records.values():
            row = record["row"]
            candidate = next(
                k
                for k, v in spec["candidates"].items()
                if v == dict(symbol=row["symbol"], mode=row["mode"])
            )
            identity = {k: row[k] for k in IDENTITY if k in row}
            identity |= dict(
                candidate=candidate, variant=variant, run_id=evidence["header"]["run_id"]
            )
            compact = identity | {k: row.get(k) for k in METRICS}
            document = json.loads((Path(record["folder"]) / "result.json").read_text())
            trades = document["trades"]
            pnl = [t["net_pnl"] for t in trades]
            compact["worst_trade_pnl"] = min(pnl) if pnl else None
            rows.append(compact)
            concentrations.append(identity | concentration(pnl))
            timing[record["id"]] = [
                (t["signal_close"], t["entry_time"], t["exit_bar_open"], t["side"]) for t in trades
            ]
            if row["period"] in {"train", "validation", "test"}:
                pools.setdefault((candidate, variant, row["scenario"]), []).extend(pnl)
            entries = row.get("entry_diagnostics", [])
            for side in ("long", "short"):
                for outcome in ("all", "winners", "losers"):
                    subset = [
                        r
                        for r in entries
                        if r["side"] == side
                        and (
                            outcome == "all"
                            or (r["net_pnl"] > 0 if outcome == "winners" else r["net_pnl"] < 0)
                        )
                    ]
                    values = {
                        field: sum(r[field] for r in subset) / len(subset) if subset else None
                        for field in (
                            "mfe_pct",
                            "mae_pct",
                            "mfe_upper_bound_pct",
                            "mae_upper_bound_pct",
                        )
                    }
                    exc.append(
                        identity
                        | dict(
                            side=side,
                            outcome=outcome,
                            trades=len(subset),
                            status="CONSERVATIVE_OHLC_BOUNDS"
                            if entries or not trades
                            else "NOT_AVAILABLE_WITH_CURRENT_BACKEND",
                        )
                        | values
                    )
    for (candidate, variant, scenario), pnl in pools.items():
        concentrations.append(
            dict(
                candidate=candidate,
                variant=variant,
                scenario=scenario,
                period="pooled_temporal_segments",
                pooling="DISJOINT_PERIODS_INDEPENDENT_CAPITAL_NOT_COMPOUNDED",
            )
            | concentration(pnl)
        )
    table = pd.DataFrame(rows).sort_values(["candidate", "variant", "period", "scenario"])
    wf = wf_summary(table)
    paired = ablation(table, timing)
    conc = pd.DataFrame(concentrations)
    conclusions = guidelines(table, wf, conc, paired, spec)
    directory = root / FOLDER / new_id()
    directory.mkdir(parents=True, exist_ok=False)
    exports = {
        "compact_metrics.csv": table,
        "walk_forward.csv": table[table.period.str.startswith("wf_")],
        "walk_forward_summary.csv": wf,
        "sizing_ablation.csv": paired,
        "parameter_robustness.csv": table[table.variant != "fixed_180"].assign(
            lookback=lambda x: x.variant.str[-3:].astype(int)
        ),
        "yearly_diagnostics.csv": table[table.period.str.startswith("diagnostic_")],
        "concentration_diagnostics.csv": conc,
        "mfe_mae.csv": pd.DataFrame(exc),
        "long_short_diagnostics.csv": table[
            list(IDENTITY)
            + [
                "long_contribution",
                "short_contribution",
                "long_trades",
                "short_trades",
                "total_modeled_costs",
            ]
        ],
    }
    try:
        for name, frame in exports.items():
            frame.to_csv(directory / name, index=False, mode="x")
            if (directory / name).stat().st_size > 5_000_000:
                raise ValueError(f"Compact export exceeds 5MB: {name}")
        with (directory / "frozen_candidates.yaml").open("x", encoding="utf-8") as handle:
            yaml.safe_dump(spec, handle, sort_keys=False)
        write_json(
            directory / "conclusion.json",
            dict(
                evidence_scope=spec["evidence_scope"],
                candidates=conclusions,
                demo_requires_human_review=True,
            ),
        )
        metadata = dict(
            report_id=directory.name,
            evidence_scope=spec["evidence_scope"],
            frozen_sha256=sha256(root / FOLDER / "frozen_candidates.yaml"),
            sources=[
                dict(
                    variant=v,
                    run_id=e["header"]["run_id"],
                    experiment_id=e["header"]["experiment_id"],
                    source_sha256=e["source_sha256"],
                    code_sha256=e["provenance"]["code_sha256"],
                    git_revision=e["provenance"].get("git_revision"),
                    git_status=e["provenance"].get("git_status"),
                    environment={
                        k: e["provenance"].get(k) for k in ("python", "platform", "dependencies")
                    },
                    datasets=e["resolved"]["datasets"],
                    sizing_model=e["resolved"]["strategy"]["risk"],
                    backend=e["resolved"]["backend"],
                    ledger_sha256=a.ledger_hash,
                )
                for (v, e), a in zip(sources, audits, strict=True)
            ],
            file_sha256={name: sha256(directory / name) for name in exports},
        )
        write_json(directory / "metadata.json", metadata)
        text = (
            "# RMM final falsification\n\n"
            "POST-SELECTION FALSIFICATION / ROBUSTNESS CHALLENGE. "
            "Reused history; not a true unseen holdout.\n\n"
        )
        text += "Ledger/result/equity SHA256 verified; no backtests executed by this report.\n\n"
        text += "| Candidate | Provisional evidence | Flags | Final review |\n|---|---|---|---|\n"
        for candidate, conclusion in conclusions.items():
            text += (
                f"| {candidate} | {conclusion['provisional_classification']} | "
                f"{', '.join(conclusion['flags']) or 'none'} | HUMAN_REVIEW_REQUIRED |\n"
            )
        text += (
            "\nAll final classifications remain INCONCLUSIVE pending human review. "
            "No demo approval. Inspect every candidate, cost, year and fold; "
            "no neighbor replacement or retrospective winner.\n\n"
            "Fixed control is 15% of entry equity (constant fraction, not constant dollars), "
            "midpoint of original 5–25% caps. Exposure is not empirically matched. "
            "Read sizing_ablation exposure ratios and trade timing before attributing a "
            "risk improvement. PF and ratios undefined without losses/positive denominator "
            "remain empty.\n\n"
            "Annual accounts and temporal/WF windows overlap across diagnostics; never "
            "sum their trades or profits. Pooled temporal concentration uses only disjoint "
            "train/validation/test accounts with independently reset capital, not a "
            "compounded strategy. Leave-best-out deletes PnL descriptively without "
            "reconstructing equity. MFE/MAE are conservative OHLC bounds. Synthetic "
            "shorts omit funding, borrow and liquidation.\n\n"
            "Return/exposure and DD/exposure are descriptive ratios, not exposure-matched "
            "resimulations. Regime/exceptional-move dependence and short diversification "
            "require human review; side PnL alone does not establish diversification.\n"
        )
        for name in ("summary.md", "ai_summary.md"):
            with (directory / name).open("x", encoding="utf-8") as handle:
                handle.write(text)
        for (_, evidence), audit in zip(sources, audits, strict=True):
            assert_unchanged(evidence)
            audit.assert_source_stable()
        write_json(
            directory / "outcome.json",
            dict(status="COMPLETE", backtests_executed=0, source_rows=len(table)),
        )
    except BaseException:
        write_json(directory / "outcome.json", dict(status="FAILED", usable_evidence=False))
        raise
    return directory
