"""Frozen research gate, separate from the unchanged historical classifications."""

import json
import math

import pandas as pd

from quant_lab.experiments import write_json
from quant_lab.mtf_reporting import KEYS
from quant_lab.new_mtf_features import FAMILIES
from quant_lab.new_mtf_watchlist import enrich, write_classification
from quant_lab.study_report import markdown

CRITERIA = {
    "full_return_gt": 0,
    "full_pf_ge": 1.10,
    "full_expectancy_gt": 0,
    "full_sharpe_gt": 0,
    "full_drawdown_le": 20,
    "full_trades_ge": 100,
    "holdout_trades_ge": 20,
    "holdout_return_ge": 0,
    "holdout_expectancy_gt": 0,
    "holdout_pf_ge": 1,
    "positive_folds_ge": 9,
    "total_folds": 22,
    "adverse_return_gt": -10,
    "adverse_pf_ge": 0.90,
}
MEASURES = {
    "return": "return_pct",
    "pf": "profit_factor",
    "expectancy": "expectancy",
    "drawdown": "max_drawdown_pct",
    "trades": "closed_trades",
    "costs": "total_costs",
    "sharpe": "sharpe",
    "positive_folds": "positive_folds",
}


def classify_research(table: pd.DataFrame) -> pd.DataFrame:
    if table.duplicated(KEYS + ["partition", "costs"]).any():
        raise ValueError("Duplicate experiment rows")
    output = []
    for keys, group in table.groupby(KEYS, sort=True):

        def one(partition, costs, group=group):
            matches = group[(group.partition == partition) & (group.costs == costs)]
            if len(matches) != 1:
                raise ValueError(f"Missing or duplicate required row: {partition}/{costs}")
            return matches.iloc[0]

        full, hold, adverse = (
            one("full", "base"),
            one("final_holdout", "base"),
            one("full", "adverse"),
        )
        folds = group[(group.costs == "base") & group.partition.str.startswith("wf_")]
        expected = {f"wf_{i:02}_test" for i in range(22)}
        complete = set(folds.partition) == expected and len(folds) == 22
        positive = int((folds.return_pct > 0).sum())
        checks = {}
        for label, row, column, op in (
            ("full_return_gt", full, "return_pct", "gt"),
            ("full_pf_ge", full, "profit_factor", "ge"),
            ("full_expectancy_gt", full, "expectancy", "gt"),
            ("full_sharpe_gt", full, "sharpe", "gt"),
            ("full_drawdown_le", full, "max_drawdown_pct", "le"),
            ("full_trades_ge", full, "closed_trades", "ge"),
            ("holdout_trades_ge", hold, "closed_trades", "ge"),
            ("holdout_return_ge", hold, "return_pct", "ge"),
            ("holdout_expectancy_gt", hold, "expectancy", "gt"),
            ("holdout_pf_ge", hold, "profit_factor", "ge"),
            ("adverse_return_gt", adverse, "return_pct", "gt"),
            ("adverse_pf_ge", adverse, "profit_factor", "ge"),
        ):
            value, limit = row[column], CRITERIA[label]
            finite = value is not None and math.isfinite(float(value))
            checks[label] = bool(
                finite
                and (
                    value > limit
                    if op == "gt"
                    else value >= limit
                    if op == "ge"
                    else value <= limit
                )
            )
        checks["positive_folds_ge"] = positive >= CRITERIA["positive_folds_ge"]
        checks["complete_folds"] = complete and bool(
            folds.return_pct.map(lambda v: pd.notna(v) and math.isfinite(float(v))).all()
        )
        output.append(
            dict(zip(KEYS, keys, strict=True))
            | full.to_dict()
            | {
                "research_pass": all(checks.values()),
                "research_classification": "RESEARCH_PASS"
                if all(checks.values())
                else "RESEARCH_FAIL",
                "failed_criteria": ";".join(k for k, v in checks.items() if not v),
                "criteria_checks": json.dumps(checks, sort_keys=True),
                "holdout_return": hold.return_pct,
                "holdout_trades": hold.closed_trades,
                "holdout_expectancy": hold.expectancy,
                "holdout_pf": hold.profit_factor,
                "adverse_return": adverse.return_pct,
                "adverse_pf": adverse.profit_factor,
                "positive_folds": positive,
                "total_folds": len(folds),
                "positive_fold_ratio": positive / len(folds) if len(folds) else 0,
            }
        )
    return enrich(pd.DataFrame(output), CRITERIA)


def eligibility(table: pd.DataFrame) -> dict:
    expected = {(a, f, v) for a in ("BTCUSDT", "ETHUSDT") for f in FAMILIES for v in ("V1", "V2")}
    actual = set(table[["asset", "family", "architecture"]].itertuples(index=False, name=None))
    if (
        actual != expected
        or len(table) != 16
        or not table["mode"].eq("LONG_ONLY").all()
        or not table.cohort.eq("matched").all()
    ):
        raise ValueError(
            "Phase A must contain exactly the frozen 16 matched LONG_ONLY configurations"
        )
    result = {
        "eligible": [],
        "not_eligible": [],
        "reason": "V1 or V2 must pass every frozen criterion",
    }
    for (asset, family), group in table.groupby(["asset", "family"], sort=True):
        passed = group.loc[group.research_pass, "architecture"].tolist()
        result["eligible" if passed else "not_eligible"].append(
            {
                "asset": asset,
                "family": family,
                "passed_architectures": passed,
                "reason": "RESEARCH_PASS in " + ", ".join(passed)
                if passed
                else "Neither V1 nor V2 passed",
            }
        )
    return result


def comparisons(table, target="V2"):
    output = []
    for (asset, family), group in table.groupby(["asset", "family"], sort=True):
        indexed = group.set_index("architecture")
        if target not in indexed.index:
            continue
        if target == "V2":
            baseline = indexed.loc["V1"]
            version = "V1"
        else:
            # Frozen descriptive ordering, used only for the requested delta reference.
            ranked = group[group.architecture.isin(["V1", "V2"])].sort_values(
                ["return_pct", "sharpe", "architecture"],
                ascending=[False, False, True],
                na_position="last",
            )
            if ranked.empty:
                continue
            baseline, version = ranked.iloc[0], ranked.iloc[0].architecture
        candidate = indexed.loc[target]
        record = {"asset": asset, "family": family, "baseline": version, "target": target}
        for name, column in MEASURES.items():
            record["baseline_" + name] = baseline[column]
            record["target_" + name] = candidate[column]
            record["delta_" + name] = candidate[column] - baseline[column]
        for name, positive in (
            ("return", True),
            ("drawdown", False),
            ("trades", False),
            ("costs", False),
            ("expectancy", True),
            ("positive_folds", True),
        ):
            value = record["delta_" + name]
            record["improved_" + name] = (
                bool(value > 0 if positive else value < 0) if pd.notna(value) else None
            )
        output.append(record)
    return pd.DataFrame(output)


def report(folder, phase, preceding=None):
    table = pd.read_csv(folder / "results.csv")
    classified = classify_research(table)
    historical = pd.read_csv(folder / "comparison.csv")[KEYS + ["classification"]]
    classified = classified.merge(historical, on=KEYS, validate="one_to_one")
    classified.to_csv(folder / "research_pass.csv", index=False)
    watchlist = write_classification(folder, classified)
    for name, mask in (
        ("segment_metrics", table.partition.str.startswith("segment_")),
        ("fold_metrics", table.partition.str.startswith("wf_")),
        ("holdout", table.partition == "final_holdout"),
        ("cost_sensitivity", table.partition == "full"),
    ):
        table.loc[mask].to_csv(folder / (name + ".csv"), index=False)
    joined = (
        pd.concat([preceding, classified], ignore_index=True)
        if preceding is not None
        else classified
    )
    delta = comparisons(joined, "V4" if phase == "b" else "V2")
    delta.to_csv(folder / "architecture_deltas.csv", index=False)
    columns = [
        "asset",
        "family",
        "architecture",
        "return_pct",
        "max_drawdown_pct",
        "profit_factor",
        "sharpe",
        "expectancy",
        "closed_trades",
        "holdout_return",
        "holdout_trades",
        "positive_folds",
        "total_folds",
        "adverse_return",
        "research_classification",
    ]
    if phase == "a":
        write_json(folder / "v4_eligibility.json", eligibility(classified))
    text = "\n\n".join(
        [
            "# Nuevas familias MTF — Fase " + phase.upper(),
            "RESEARCH_PASS solo autoriza investigación V4 adicional. "
            "No valida paper/live ni beneficios futuros. "
            "La selección usa historia y holdout ya observados; V4 no es un holdout independiente.",
            markdown(joined, columns),
            "## Comparación objetiva de arquitecturas",
            "Deltas = destino menos referencia. Estabilidad = número de folds positivos. "
            "Para V4, referencia V1/V2 por retorno FULL BASE, luego Sharpe y V1 en empate. "
            "Esta referencia descriptiva no altera elegibilidad ni parámetros.",
            markdown(delta, list(delta.columns)) if not delta.empty else "Sin comparaciones.",
            "Criterios congelados: " + json.dumps(CRITERIA, sort_keys=True),
            "Métricas ausentes/no finitas fallan el criterio; "
            "PF indefinido no se convierte a infinito. "
            "Clasificación histórica conservada en comparison.csv; "
            "reglas nuevas en research_pass.csv.",
        ]
    )
    # This folder was just created for this run; no historical report is edited.
    (folder / "summary.md").write_text(text + "\n\n" + watchlist, encoding="utf-8")
    return classified
