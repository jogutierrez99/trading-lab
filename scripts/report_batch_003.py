"""Render descriptive reports from immutable Batch 003 results, without rerunning signals."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from quant_lab.batch_003_analysis import LABEL
from quant_lab.metrics import daily_returns


def render(root):
    metrics = pd.read_csv(root / "metrics.csv")
    selections = json.loads((root / "selection_train.json").read_text())
    classes = json.loads((root / "classifications.json").read_text())
    wf = json.loads((root / "walk_forward.json").read_text())["summary"]
    mc = json.loads((root / "monte_carlo.json").read_text())
    charts = root / "charts"
    plt.rcParams.update({"figure.dpi": 120, "font.size": 9, "axes.grid": True, "grid.alpha": 0.2})

    def rows(part):
        return metrics[
            (metrics.partition == part) & (metrics.costs == "base") & (metrics.benchmark_pct.isna())
        ]

    def selected(name, part, cost="base"):
        return metrics[
            (metrics.strategy == name)
            & (metrics.candidate == selections[name]["candidate"])
            & (metrics.partition == part)
            & (metrics.costs == cost)
            & metrics.benchmark_pct.isna()
        ].iloc[0]

    def save(fig, name):
        target = charts / name
        if target.exists():
            raise FileExistsError(target)
        fig.tight_layout(rect=(0, 0, 1, 0.96))
        fig.savefig(target)
        plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(12, 9))
    combined = pd.concat(
        [
            rows("full_baseline_diagnostic"),
            rows("reference_full"),
            metrics[
                (metrics.partition == "benchmark_full_baseline_diagnostic")
                & (metrics.costs == "base")
            ],
        ]
    )
    for _, row in combined.iterrows():
        e = pd.read_parquet(root / "equity" / f"{row.experiment_id}.parquet").equity
        label = f"B&H {row.benchmark_pct:g}%" if pd.notna(row.benchmark_pct) else row.candidate
        axes[0].plot(e.index, e, label=label, linewidth=1)
    axes[0].legend(ncol=3, fontsize=7)
    axes[0].set_ylabel("USDT; cuentas independientes")
    names = list(selections)
    x = np.arange(4)
    for i, part in enumerate(("validation", "test", "final_holdout")):
        axes[1].bar(
            x + (i - 1) * 0.25,
            [selected(n, part).return_pct for n in names],
            width=0.25,
            label=part,
        )
    axes[1].set_xticks(x, names)
    axes[1].set_ylabel("Retorno neto %; variante seleccionada")
    axes[1].legend()
    fig.suptitle(
        f"Batch 003 — {LABEL}\n"
        "Arriba: bases y referencias congeladas, mismo periodo; abajo: selección train"
    )
    save(fig, "overview.png")
    regime_names = ["BULL_TREND", "BEAR_TREND", "SIDEWAYS", "HIGH_VOLATILITY", "LOW_VOLATILITY"]
    comparison = {}
    for name in names:
        row = rows("full_baseline_diagnostic").query("strategy == @name").iloc[0]
        ident = row.experiment_id
        doc = json.loads((root / ident / "result.json").read_text())
        frame = pd.read_parquet(root / "equity" / f"{ident}.parquet")
        e = frame.equity
        daily = daily_returns(e)
        pnl = np.array([t["net_pnl"] for t in doc["trades"]])
        returns = [t["net_pnl"] / (t["quantity"] * t["entry_price"]) * 100 for t in doc["trades"]]
        reg = {k: v for axis in doc["regimes"]["axes"].values() for k, v in axis.items()}
        comparison[name] = [
            reg.get(n, {}).get("trade_return_contribution_pct", 0) for n in regime_names
        ]
        fig, ax = plt.subplots(4, 2, figsize=(14, 16))
        ax = ax.ravel()
        ax[0].plot(e.index, e)
        ax[0].set_title("Equity (USDT)")
        ax[1].fill_between(e.index, (e / e.cummax() - 1) * 100, 0)
        ax[1].set_title("Drawdown %")
        months = pd.Series(doc["monthly_returns_pct"])
        ax[2].bar(np.arange(len(months)), months.values)
        ax[2].set_xticks(np.arange(0, len(months), 4), months.index[::4], rotation=45)
        ax[2].set_title("Retorno mensual %")
        rolling = daily.rolling(90).mean() / daily.rolling(90).std() * np.sqrt(365)
        ax[3].plot(rolling.index, rolling)
        ax[3].set_title("Sharpe móvil 90 días")
        ax[4].hist(returns, bins=25)
        ax[4].set_title(f"Retorno neto / nocional entrada % ({len(pnl)} trades)")
        ax[5].plot(frame.index, frame.close_exposure * 100)
        ax[5].axhline(25, color="red", linestyle="--")
        ax[5].set_title("Exposición al cierre %; límite25% aplicado al entrar")
        sample = root / "mc_samples" / f"{ident}.npy"
        if sample.exists():
            ax[6].hist(np.load(sample)[:, 1], bins=40)
        else:
            ax[6].text(0.1, 0.5, "Menos de30 trades: no simulado", transform=ax[6].transAxes)
        ax[6].set_title("MC: DD entre trades % (10.000 permutaciones)")
        ax[7].bar(np.arange(5), comparison[name])
        ax[7].set_xticks(np.arange(5), regime_names, rotation=35, ha="right")
        ax[7].set_title("Contribución PnL % / capital inicial por señal; ejes solapados")
        fig.suptitle(f"{row.candidate} — BASE, histórico completo descriptivo\n{LABEL}")
        save(fig, f"{name}.png")
    fig, ax = plt.subplots(figsize=(13, 6))
    for i, name in enumerate(names):
        ax.bar(np.arange(5) + (i - 1.5) * 0.2, comparison[name], width=0.2, label=name)
    ax.set_xticks(np.arange(5), regime_names)
    ax.legend()
    ax.set_ylabel("Contribución neta % del capital inicial")
    fig.suptitle(
        f"Bases, periodo completo — {LABEL}\n"
        "Tendencia y volatilidad son ejes separados; no sumar ambos"
    )
    save(fig, "regime_comparison.png")

    def f(v):
        return "N/D" if v is None or pd.isna(v) else f"{v:.2f}"

    lines = [
        "# Batch 003 — diagnóstico con histórico reutilizado",
        "",
        LABEL,
        "",
        (
            "10.000 USDT por ejecución independiente. BTC/USDT spot 1h, solo "
            "largos. Sin cartera conjunta ni apalancamiento."
        ),
        (
            "Train: 2023-06-04 a2024-07-01; validation: hasta2025-01-01; test: "
            "hasta2025-07-01; final: hasta2026-01-01. UTC, fin exclusivo. 1.536 "
            "barras previas de contexto en cada ejecución."
        ),
        (
            "Todo el histórico ya estaba observado. Ni los tramos posteriores a "
            "train ni el walk-forward constituyen validación independiente de las "
            "hipótesis."
        ),
        "",
        (
            "| Strategy | Selected Variant | Train % | Validation % | Test % | "
            "Holdout % | Adverse % | WF Return % | Positive WF Folds % | Max DD % "
            "| Sharpe | PF | Trades | Classification |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for n in names:
        final = selected(n, "final_holdout")
        vals = [
            selected(n, p).return_pct for p in ("train", "validation", "test", "final_holdout")
        ] + [
            selected(n, "final_holdout", "adverse").return_pct,
            wf[n]["compounded_return_pct"],
            wf[n]["positive_folds_pct"],
            final.max_drawdown_pct,
            final.sharpe,
            final.profit_factor,
        ]
        lines.append(
            f"| {n} | {selections[n]['candidate']} | "
            + " | ".join(f(v) for v in vals)
            + f" | {final.closed_trades} | {LABEL} / {classes[n]['diagnostic']} |"
        )
    lines += [
        "",
        (
            "DD, Sharpe, PF y trades de la tabla corresponden al tramo final con "
            "costes base. Adverse usa una simulación nueva del mismo tramo. "
            "Variantes rechazadas continúan únicamente como diagnóstico."
        ),
        "",
        "## Respuestas a las 11 preguntas",
        "",
    ]
    eligible = [v for c in selections.values() for v in c["eligible_variants"]]
    lines.append("1. Superaron train: " + (", ".join(eligible) or "ninguna") + ".")
    lines.append(
        "2. Llegaron a validation las cuatro selecciones congeladas; solo las "
        "elegibles avanzan como hipótesis aceptadas en train. Las restantes "
        "son bases diagnósticas."
    )
    for number, part, text, cost in (
        (3, "validation", "Validation positiva", "base"),
        (4, "test", "Test positivo", "base"),
        (5, "final_holdout", "Tramo final positivo", "base"),
        (6, "final_holdout", "Tramo final positivo con costes adversos", "adverse"),
    ):
        positive = [n for n in names if selected(n, part, cost).return_pct > 0]
        lines.append(
            f"{number}. {text}: "
            + (", ".join(positive) or "ninguna")
            + ". Positivo describe retorno, no robustez ni elegibilidad."
        )
    lines.append(
        (
            "7. Walk-forward utiliza la misma selección inicial en cuatro folds "
            "12m/3m. Resultados compuestos: "
        )
        + "; ".join(
            f"{n}: {f(wf[n]['compounded_return_pct'])}%, "
            f"{f(wf[n]['positive_folds_pct'])}% de folds positivos"
            for n in names
        )
        + ". Tests se solapan con validation/test estáticos; no duplicar evidencia."
    )
    lines.append(
        "8. Monte Carlo reordena PnLs monetarios fijos: el retorno final "
        "permanece constante. Evalúa sensibilidad de DD entre operaciones y "
        "rachas al orden; no predice resultados ni representa DD intrabar."
    )
    for n in names:
        ident = rows("full_baseline_diagnostic").query("strategy == @n").iloc[0].experiment_id
        item = mc[ident]
        if item["status"] == "completed":
            q = item["percentiles"]["drawdown_pct"]
            lines.append(
                f"   - {n}, base completa: DD MC p5/p50/p95={f(q['5'])}/{f(q['50'])}/{f(q['95'])}%."
            )
    lines.append(
        "9. Regímenes, bases completas: contribución neta atribuida al "
        "régimen de la señal (tendencia y volatilidad se solapan):"
    )
    for n in names:
        lines.append(
            "   - "
            + n
            + ": "
            + "; ".join(f"{r} {f(v)}%" for r, v in zip(regime_names, comparison[n], strict=True))
            + "."
        )
    lines.append(
        "10. Las hipótesis con train rechazado o pérdidas en tramos "
        "posteriores quedan sin respaldo en este experimento; no es una "
        "refutación universal. Clasificaciones completas arriba; ninguna "
        "ROBUST."
    )
    positive = [
        n
        for n in names
        if selections[n]["train_eligible"] and selected(n, "final_holdout").return_pct > 0
    ]
    lines.append(
        "11. Candidatas a investigar en Batch004: "
        + (
            ", ".join(positive)
            if positive
            else "ninguna demuestra una ventaja suficientemente consistente"
        )
        + (
            ". Cualquier hipótesis derivada de regímenes exige un lote nuevo y "
            "datos no observados, sin retocar este lote."
        )
    )
    lines += [
        "",
        "## Comparación en periodos idénticos",
        "",
        (
            "Referencias Batch001/002: parámetros seleccionados originales, sin "
            "reoptimización; recreadas con contexto de1.536 horas. Sus cifras "
            "históricas originales permanecen intactas. No equiparar esas cifras "
            "de periodos distintos con estas ejecuciones."
        ),
        "",
        "| Referencia | Periodo | Retorno % | DD % | Trades |",
        "|---|---|---:|---:|---:|",
    ]
    refs = metrics[
        (
            metrics.partition.isin(
                [
                    "reference_full",
                    "reference_final",
                    "benchmark_full_baseline_diagnostic",
                    "benchmark_final_holdout",
                ]
            )
        )
        & (metrics.costs == "base")
    ]
    for _, r in refs.iterrows():
        label = f"B&H {r.benchmark_pct:g}%" if pd.notna(r.benchmark_pct) else r.candidate
        lines.append(
            f"| {label} | {r.partition} | {f(r.return_pct)} | "
            f"{f(r.max_drawdown_pct)} | {r.closed_trades} |"
        )
    lines += [
        "",
        "## Convenciones y auditoría",
        "",
        (
            "Gross usa precios de referencia de los mismos trades reales. No "
            "equivale al escenario zero, que se vuelve a ejecutar con costes cero. "
            "Comisiones, slippage y spread se concilian con neto."
        ),
        (
            "El límite25% se aplica al entrar e incluye comisión; la exposición "
            "de mercado puede superar25% después. Riesgo inicial estimado al "
            "stop<=0,5%; gaps pueden superar esa pérdida. Trailing basado en "
            "cierre se actualiza para la vela siguiente y nunca se aleja."
        ),
        (
            "Pullback: la vela anterior toca/cruza EMA; la actual confirma "
            "recuperación. EMA4h solo desde su cierre; ROC60d requiere1.440 horas "
            "previas. Nunca se cruza marzo2023; legacy se ejecuta aparte "
            "desde2022-02-03 a2023-03-01."
        ),
        (
            "Los regímenes usan dos ejes causales, con umbral lateral0,25% y "
            "percentiles30/70 de720 observaciones anteriores. PnL por trades se "
            "atribuye a la señal; PnL por barra al régimen conocido al inicio. "
            "Ver regime_analysis.json para ambos y exposure condicional."
        ),
        (
            "Plan y provenance se guardaron antes del primer backtest; selección "
            "antes de validation; marcador antes del final. verification.json "
            "certifica hashes anteriores, código congelado, ledger y "
            "conciliaciones. metrics.csv incluye todas las pérdidas y todos los "
            "escenarios; results/, equity/ y trades/ contienen cada ejecución."
        ),
        "",
        "![Overview](charts/overview.png)",
        "",
    ]
    target = root / "batch_003_summary.md"
    with target.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    render(parser.parse_args().run)
