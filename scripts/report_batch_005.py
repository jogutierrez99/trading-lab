"""Render descriptive reports from immutable Batch 005 results, without rerunning signals."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from quant_lab.batch_004_analysis import LABEL
from quant_lab.metrics import daily_returns


def render(root):

    metrics = pd.read_csv(root / "metrics.csv")

    selections = json.loads((root / "selection_train.json").read_text())

    classes = json.loads((root / "classifications.json").read_text())

    wf = json.loads((root / "walk_forward.json").read_text())["summary"]

    mc = json.loads((root / "monte_carlo.json").read_text())

    costs = json.loads((root / "cost_analysis.json").read_text())["strategies"]

    quality = json.loads((root / "entry_quality.json").read_text())
    edge = json.loads((root / "time_to_edge.json").read_text())
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
        f"Batch 005 — {LABEL}\n"
        "Arriba: bases y referencias congeladas, mismo periodo; abajo: selección train"
    )

    save(fig, "overview.png")

    regime_names = [
        "BULL_TREND",
        "BEAR_TREND",
        "SIDEWAYS",
        "HIGH_VOLATILITY",
        "NORMAL_VOLATILITY",
        "LOW_VOLATILITY",
    ]

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

        fig, ax = plt.subplots(6, 2, figsize=(16, 24))

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

        for method in ("reshuffling", "bootstrap"):
            sample = root / "mc_samples" / f"{ident}_{method}.npy"

            if sample.exists():
                array = np.load(sample)

                ax[6].hist(array[:, 1], bins=40, alpha=0.5, label=method)

                ax[9].hist(array[:, 0], bins=40, alpha=0.5, label=method)

        if mc[ident]["status"] != "completed":
            ax[6].text(0.1, 0.5, "Menos de 30 trades", transform=ax[6].transAxes)

            ax[9].text(0.1, 0.5, "Menos de 30 trades", transform=ax[9].transAxes)

        else:
            ax[6].legend()

            ax[9].legend()

        ax[6].set_title("MC: DD entre trades %; 10.000 muestras por metodo")

        ax[9].set_title("MC: retorno terminal %; PnLs fijos, no pronostico")

        ax[8].bar(
            ["zero", "base", "adverse"],
            [selected(name, "final_holdout", c).return_pct for c in ("zero", "base", "adverse")],
        )

        ax[8].set_title("Costes: variante SELECCIONADA, tramo FINAL, retorno %")

        ax[7].bar(np.arange(6), comparison[name])

        ax[7].set_xticks(np.arange(6), regime_names, rotation=35, ha="right")

        ax[7].set_title("Contribución PnL % / capital inicial por señal; ejes solapados")

        q = quality[ident]
        ax[10].scatter(
            [t["mae_pct"] for t in q["trades"]],
            [t["mfe_pct"] for t in q["trades"]],
            s=12,
            alpha=0.6,
        )
        ax[10].set_xlabel("MAE % (magnitud, limite inferior si intravela)")
        ax[10].set_ylabel("MFE % (limite inferior si intravela)")
        ax[10].set_title("Excursiones durante la operacion; incertidumbre OHLC")
        hours = [6, 12, 24, 48, 72]
        stats = edge[ident]["summary"]
        for statistic in ("mean", "median"):
            ax[11].plot(
                hours, [stats[str(h)][statistic] for h in hours], marker="o", label=statistic
            )
        ax[11].set_xticks(hours)
        ax[11].axhline(0, color="gray", linewidth=0.6)
        ax[11].set_title("Retorno del activo a horizonte fijo %, antes de costes")
        ax[11].set_xlabel("Horas desde entrada (sin cruzar particion)")
        ax[11].legend()
        fig.suptitle(f"{row.candidate} — BASE, histórico completo descriptivo\n{LABEL}")

        for i in (0, 1, 3, 5):
            ax[i].tick_params(axis="x", rotation=30)

        save(fig, f"{name}.png")

    fig, ax = plt.subplots(figsize=(13, 6))

    for i, name in enumerate(names):
        ax.bar(np.arange(6) + (i - 1.5) * 0.2, comparison[name], width=0.2, label=name)

    ax.set_xticks(np.arange(6), regime_names)

    ax.legend()

    ax.set_ylabel("Contribución neta % del capital inicial")

    fig.suptitle(
        f"Bases, periodo completo — {LABEL}\n"
        "Tendencia y volatilidad son ejes separados; no sumar ambos"
    )

    save(fig, "regime_comparison.png")

    fig, ax = plt.subplots(figsize=(13, 6))

    for i, cost in enumerate(("zero", "base", "adverse")):
        ax.bar(
            np.arange(4) + (i - 1) * 0.25,
            [selected(n, "final_holdout", cost).return_pct for n in names],
            width=0.25,
            label=cost,
        )

    ax.set_xticks(np.arange(4), names)

    ax.set_ylabel("Retorno final %")

    ax.legend()

    fig.suptitle(f"Costes, seleccion congelada — {LABEL}")

    save(fig, "cost_comparison.png")

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    tests = json.loads((root / "walk_forward.json").read_text())["test_only"]

    for i, n in enumerate(names):
        values = [r["return_pct"] for r in tests if r["strategy"] == n]

        axes[0].bar(np.arange(4) + (i - 1.5) * 0.2, values, width=0.2, label=n)

    axes[0].set_xticks(np.arange(4), ["2024 Q3", "2024 Q4", "2025 Q1", "2025 Q2"])

    axes[0].set_ylabel("Retorno test fold %")

    axes[0].legend(fontsize=8)

    axes[1].bar(np.arange(4), [wf[n]["compounded_return_pct"] for n in names])

    axes[1].set_xticks(np.arange(4), names, rotation=20)

    axes[1].set_ylabel("Retorno compuesto solo tests %")

    fig.suptitle(f"Walk-forward, sin reseleccion — {LABEL}")

    save(fig, "walk_forward_comparison.png")

    fig, axes = plt.subplots(2, 1, figsize=(13, 10))
    for i, metric in enumerate(("mean_mfe_pct", "mean_mae_pct")):
        axes[0].bar(
            np.arange(4) + (i - 0.5) * 0.3,
            [selected(n, "final_holdout")[metric] for n in names],
            width=0.3,
            label=metric,
        )
    axes[0].set_xticks(np.arange(4), names)
    axes[0].set_ylabel("Excursion media %; cotas inferiores si intravela")
    axes[0].legend()
    for n in names:
        ident = selected(n, "final_holdout").experiment_id
        summary = edge[ident]["summary"]
        axes[1].plot(
            [6, 12, 24, 48, 72],
            [summary[str(h)]["mean"] for h in (6, 12, 24, 48, 72)],
            marker="o",
            label=n,
        )
    axes[1].axhline(0, color="gray", linewidth=0.6)
    axes[1].set_xlabel("Horas desde entrada")
    axes[1].set_ylabel("Retorno medio del activo %, antes de costes")
    axes[1].legend()
    fig.suptitle(f"Calidad de entrada, seleccion FINAL — {LABEL}")
    save(fig, "entry_quality_comparison.png")

    def f(v):

        return "N/D" if v is None or pd.isna(v) else f"{v:.2f}"

    lines = [
        "# Batch 005 — resultados diagnosticos",
        "",
        LABEL,
        "",
        (
            "BTC/USDT spot 1h, solo largos. Capital independiente de 10.000 USDT "
            "por ejecucion, sin cartera ni apalancamiento."
        ),
        (
            "Inventario local: no hay BTC de 2026 ni ETH. Primario continuo "
            "disponible abril 2023-diciembre 2025. Datos ya observados; ninguna "
            "validacion independiente."
        ),
        (
            "Train 2023-06-04–2024-07-01; validation hasta 2025-01-01; test "
            "hasta 2025-07-01; final hasta 2026-01-01. UTC, fin exclusivo. "
            "Warmup comun: 1.536 horas por particion."
        ),
        "",
        (
            "| Strategy | Selected Variant | Train % | Validation % | Test % | "
            "Holdout % | Zero Cost % | Base Cost % | Adverse % | WF % | Positive "
            "WF Folds % | Max DD % | Sharpe | PF | Trades | MFE/MAE | Classification |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]

    for n in names:
        final = selected(n, "final_holdout")

        values = [
            selected(n, p).return_pct for p in ("train", "validation", "test", "final_holdout")
        ]

        values += [selected(n, "final_holdout", c).return_pct for c in ("zero", "base", "adverse")]

        values += [
            wf[n]["compounded_return_pct"],
            wf[n]["positive_folds_pct"],
            final.max_drawdown_pct,
            final.sharpe,
            final.profit_factor,
        ]

        lines.append(
            f"| {n} | {selections[n]['candidate']} | "
            + " | ".join(f(v) for v in values)
            + f" | {final.closed_trades} | {f(final.mfe_mae_ratio)} | "
            f"{LABEL} / {classes[n]['diagnostic']} |"
        )

    lines += [
        "",
        (
            "Costes zero/base/adverse, DD, Sharpe, PF y trades de la tabla "
            "corresponden al mismo tramo FINAL. Los otros retornos usan costes "
            "base. El rechazo en train mantiene solo la base como diagnostico, "
            "sin promoverla."
        ),
        "",
        "## Respuestas a las 15 preguntas",
        "",
    ]

    eligible = [v for c in selections.values() for v in c["eligible_variants"]]

    lines.append(
        "1. Elegibles en train: "
        + (", ".join(eligible) or "ninguna")
        + ". Criterios: net>0, Sharpe>0, PF>1, >=40 trades, DD<20%."
    )

    lines.append(
        "2. Selecciones congeladas: "
        + "; ".join(
            n
            + ": "
            + c["candidate"]
            + (" (elegible)" if c["train_eligible"] else " (base diagnostica)")
            for n, c in selections.items()
        )
        + ". Mayor Sharpe; empates exactos por menor DD, mayor PF, ID."
    )

    for number, part, cost in (
        (3, "validation", "base"),
        (4, "test", "base"),
        (5, "final_holdout", "base"),
        (6, "final_holdout", "adverse"),
    ):
        lines.append(
            f"{number}. {part}/{cost}: "
            + "; ".join(f"{n}: {f(selected(n, part, cost).return_pct)}%" for n in names)
            + ". Retorno positivo no equivale a robustez."
        )

    lines.append(
        "7. Walk-forward fijo 12m/3m: "
        + "; ".join(
            f"{n}: {f(wf[n]['compounded_return_pct'])}%, "
            f"{f(wf[n]['positive_folds_pct'])}% folds positivos"
            for n in names
        )
        + (
            ". Cuatro cuentas independientes; se compone solo test. Se solapa "
            "con validation/test estaticos."
        )
    )

    lines.append(
        "8. Monte Carlo: 10.000 reshufflings y 10.000 bootstraps por "
        "ejecucion con >=30 trades. PnLs monetarios fijos: reshuffling "
        "conserva retorno terminal; bootstrap lo varia. Ignora dependencia "
        "temporal/regimenes, sizing y reejecucion; DD entre trades, no "
        "intrabar ni pronostico."
    )

    for n in names:
        ident = rows("full_baseline_diagnostic").query("strategy == @n").iloc[0].experiment_id

        item = mc[ident]

        if item["status"] != "completed":
            lines.append(f"   - {n}, base completa: insuficientes trades.")

            continue

        for method, record in item["methods"].items():
            dd = record["percentiles"]["drawdown_pct"]

            terminal = record["percentiles"]["return_pct"]

            lines.append(
                f"   - {n}, base completa, {method}: DD p5/p50/p95 "
                f"{f(dd['5'])}/{f(dd['50'])}/{f(dd['95'])}%; retorno terminal p5/p50/p95 "
                f"{f(terminal['5'])}/{f(terminal['50'])}/{f(terminal['95'])}%."
            )

    lines.append(
        "9. Contribucion neta por regimen de la senal, bases completas, % "
        "capital inicial. Los dos ejes se solapan; no sumarlos:"
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
        "10. Impacto de costes en tramo final, puntos porcentuales entre "
        "reejecuciones completas (no resta posterior de comisiones):"
    )

    for n in names:
        c = costs[n]["final_holdout"]

        lines.append(
            f"   - {n}: zero-base={f(c['cost_drag_pct_points'])}; "
            f"base-adverse={f(c['adverse_drag_pct_points'])}."
        )

    lines.append(
        "11. Calidad de entrada en tramo final/base: MFE/MAE antes de "
        "costes; cotas inferiores cuando la salida intravela impide "
        "conocer extremos exactos. El ratio no identifica por si solo "
        "buena entrada o mala salida."
    )
    for n in names:
        record = quality[selected(n, "final_holdout").experiment_id]
        q = record["summary"]
        lines.append(
            f"   - {n}: MFE media/mediana {f(q['mfe_pct']['mean'])}/{f(q['mfe_pct']['median'])}%; "
            f"MAE media/mediana {f(q['mae_pct']['mean'])}/{f(q['mae_pct']['median'])}%; "
            f"ratio de medias {f(record['ratio_of_mean_mfe_mae'])}; "
            f"{record['intrabar_censored_trades']} salidas intravela con cotas."
        )
        lines.append(
            f"     Tiempo medio hasta extremo observado: MFE intervalo "
            f"[{f(q['time_to_mfe_hours_lower']['mean'])}, "
            f"{f(q['time_to_mfe_hours_upper']['mean'])}]h; "
            f"MAE [{f(q['time_to_mae_hours_lower']['mean'])}, "
            f"{f(q['time_to_mae_hours_upper']['mean'])}]h."
        )
    lines.append(
        "12. Time-to-edge final/base: media/mediana de retorno bruto del "
        "activo y n disponible, incluso tras salida; nunca fuera de "
        "particion. No son retornos de la estrategia ni muestras "
        "independientes."
    )
    for n in names:
        summary = edge[selected(n, "final_holdout").experiment_id]["summary"]
        lines.append(
            "   - "
            + n
            + ": "
            + "; ".join(
                f"{h}h {f(summary[str(h)]['mean'])}/{f(summary[str(h)]['median'])}% "
                f"(n={summary[str(h)]['n']})"
                for h in (6, 12, 24, 48, 72)
            )
            + "."
        )
    favorable = [
        n
        for n in names
        if selections[n]["train_eligible"]
        and all(selected(n, p).return_pct > 0 for p in ("validation", "test", "final_holdout"))
        and selected(n, "final_holdout", "adverse").return_pct > 0
        and wf[n]["positive_folds_pct"] >= 75
    ]

    lines.append(
        (
            "13. Evidencia descriptiva favorable conjunta (train elegible, "
            "validation/test/final/adverse positivos y >=75% folds positivos): "
        )
        + (", ".join(favorable) or "ninguna")
        + ". Aun cumpliendolo, historia reutilizada impide declarar ROBUST."
    )

    weakened = [n for n in names if n not in favorable]

    lines.append(
        "14. Hipotesis debilitadas o insuficientes: "
        + (", ".join(weakened) or "ninguna bajo el criterio conjunto anterior")
        + ". No eliminar perdidas ni interpretar este diagnostico como refutacion universal."
    )

    lines.append(
        "15. Batch006: "
        + (
            "replicar " + ", ".join(favorable) + " con datos no observados"
            if favorable
            else (
                "no hay candidata respaldada por el criterio conjunto; priorizar "
                "datos no observados antes de derivar mas filtros del mismo historico"
            )
        )
        + ". Cualquier cambio de reglas pertenece al lote siguiente; Batch005 permanece congelado."
    )

    lines += [
        "",
        "## Benchmarks y referencias, mismos periodos",
        "",
        (
            "REFERENCE_DIAGNOSTIC: quince selecciones originales de "
            "Batch001/002/003/004, sin reoptimizar, reejecutadas con 1.536 horas de "
            "contexto sobre los mismos periodos completo/final. No comparar "
            "cifras originales de periodos distintos."
        ),
        "",
        (
            "| Referencia | Periodo | Return % | DD % | Vol anual % | Sharpe | "
            "Exposure medio % | Trades |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|",
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
            f"| {label} | {r.partition} | {f(r.return_pct)} | {f(r.max_drawdown_pct)} | "
            f"{f(r.annualized_volatility_pct)} | {f(r.sharpe)} | "
            f"{f(r.average_close_exposure_pct)} | {r.closed_trades} |"
        )

    lines += [
        "",
        "## Convenciones e integridad",
        "",
        (
            "Channel retest: nivel/tolerancia congelados al breakout, retest posterior dentro24h, "
            "confirmacion en vela posterior; stop bajo low retest menos0,01 "
            "ATR, cap2,5 ATR comprobado al open. "
            "RSI reset consume un downcross y posterior upcross50 dentro48h. Aceleracion: "
            "fast12/24/48, slow72, comparacion fast de hace24h. Contraccion: "
            "conteo24 velas previas."
        ),
        (
            "Regimenes: distancia relativa EMA50/200 <=0,25% lateral; "
            "volatilidad frente a p30/p70 anteriores720. Gross por trade usa "
            "referencias antes de costes de los mismos fills; no equivale al "
            "escenario zero. Gross/net/costes y ambos ejes de regimen concilian "
            "con equity."
        ),
        (
            "Cap inicial25% incluyendo comision, riesgo estimado al stop<=0,5%; "
            "exposicion puede variar al mantener y gaps pueden superar perdida "
            "esperada. Trailing de cierre efectivo en vela siguiente, nunca se "
            "aleja. Todas las posiciones se liquidan al final de cada cuenta."
        ),
        (
            "Legacy 2022-02-03–2023-03-01 es diagnostico separado; nunca cruzar "
            "marzo2023 ni concatenar equity de ambos tramos. Datos e historicos "
            "previos protegidos con hashes antes/despues. Ver "
            "plan/provenance/verification y ledger."
        ),
        (
            "MC disponible por cada ejecucion elegible; <30 trades se registra "
            "como insuficiente. No sumar evidencia de folds solapados ni agregar "
            "cuentas como cartera. Semillas, percentiles, riesgo de equity no "
            "positiva y probabilidades descriptivas en monte_carlo.json."
        ),
        (
            "Las 12 variantes y todos los escenarios, incluidos rechazos y "
            "perdidas, estan en metrics.csv. Artefactos adicionales: "
            "cost_analysis.json, regime_analysis.json, walk_forward.json y "
            "carpetas results/equity/trades/charts."
        ),
        "",
        "![Overview](charts/overview.png)",
        "",
    ]

    with (root / "batch_005_summary.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("run", type=Path)

    render(parser.parse_args().run)
