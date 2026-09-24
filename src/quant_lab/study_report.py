"""Static study artifacts, descriptive comparisons and explicitly limited conclusions."""

import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def fmt(value):
    return "NA" if pd.isna(value) else f"{value:.2f}"


def markdown(frame, columns):
    out = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for _, row in frame.iterrows():
        out.append(
            "| "
            + " | ".join(
                fmt(row[c]) if isinstance(row[c], (float, np.floating)) else str(row[c])
                for c in columns
            )
            + " |"
        )
    return "\n".join(out)


def report(path):
    df = pd.read_csv(path / "timeframe_comparison.csv")
    valid = df[df.status == "EVALUATED"].copy()
    summaries = json.loads((path / "cross_asset_analysis.json").read_text())
    overlaps = json.loads((path / "signal_overlap.json").read_text())
    correlations = json.loads((path / "correlations.json").read_text())
    audit = json.loads((path / "dataset_audit.json").read_text())
    plots = path / "charts"
    plots.mkdir(exist_ok=True)
    plt.rcParams.update({"figure.dpi": 130, "font.size": 9})
    for column, filename in (
        ("return_pct", "timeframe_return_comparison"),
        ("sharpe", "timeframe_sharpe_comparison"),
        ("profit_factor", "timeframe_pf_comparison"),
        ("cost_drag", "timeframe_cost_drag"),
        ("positive_year_ratio", "positive_year_ratio"),
        ("mfe_mae_ratio", "MFE_MAE_comparison"),
    ):
        pivot = valid.pivot_table(
            index="strategy", columns="timeframe", values=column, aggfunc="median"
        ).reindex(columns=["1h", "4h", "1d"])
        ax = pivot.plot.barh(figsize=(12, 9), width=0.8)
        ax.set_title(f"{column}: mediana BTC/ETH; cuentas independientes")
        ax.axvline(0, color="black", linewidth=0.6)
        ax.figure.tight_layout()
        ax.figure.savefig(plots / (filename + ".png"))
        plt.close(ax.figure)
    for asset in ("BTCUSDT", "ETHUSDT"):
        pivot = (
            valid[valid.asset == asset]
            .pivot(index="strategy", columns="timeframe", values="return_pct")
            .reindex(columns=["1h", "4h", "1d"])
        )
        ax = pivot.plot.barh(figsize=(12, 9))
        ax.set_title(f"{asset}: retorno neto BASE, periodo completo (%)")
        ax.figure.tight_layout()
        ax.figure.savefig(plots / (asset[:3] + "_1h_vs_4h_vs_1d.png"))
        plt.close(ax.figure)
    ax = valid.pivot_table(
        index="strategy", columns="asset", values="return_pct", aggfunc="median"
    ).plot.barh(figsize=(12, 9))
    ax.set_title("Mediana descriptiva de retornos por activo; no ranking")
    ax.figure.tight_layout()
    ax.figure.savefig(plots / "cross_asset_comparison.png")
    plt.close(ax.figure)
    for asset in ("BTCUSDT", "ETHUSDT"):
        key = asset + "/4h"
        for kind in ("strategy_correlation", "signal_overlap"):
            names = sorted(correlations[key]["matrix"])
            if kind == "strategy_correlation":
                mat = (
                    pd.DataFrame(correlations[key]["matrix"])
                    .reindex(index=names, columns=names)
                    .to_numpy(dtype=float)
                )
            else:
                mat = np.full((len(names), len(names)), np.nan)
                for pair in overlaps[key]:
                    i, j = names.index(pair["a"]), names.index(pair["b"])
                    mat[i, j] = mat[j, i] = pair["holding_bar_jaccard_pct"]
            fig, ax = plt.subplots(figsize=(12, 10))
            heat = ax.imshow(
                mat,
                cmap="coolwarm" if kind == "strategy_correlation" else "viridis",
                vmin=-1 if kind == "strategy_correlation" else 0,
                vmax=1 if kind == "strategy_correlation" else 100,
            )
            ax.set_xticks(range(len(names)), names, rotation=90)
            ax.set_yticks(range(len(names)), names)
            ax.set_title(f"{asset} 4h: {kind}; BASE, full period")
            fig.colorbar(heat, ax=ax)
            fig.tight_layout()
            fig.savefig(plots / f"{kind}_heatmap_{asset}.png")
            plt.close(fig)

    def names(flag):
        return ", ".join(n for n, d in summaries.items() if flag in d["flags"]) or "ninguna"

    paired = valid.pivot(index=["strategy", "asset"], columns="timeframe", values="return_pct")
    pairs = paired[["1h", "4h"]].dropna()
    improvement = pairs["4h"] - pairs["1h"]
    daily = valid[valid.timeframe == "1d"]
    cost_sensitive = names("COST_SENSITIVE")
    mf = valid[(valid.mfe_mae_ratio > 1) & (valid.return_pct < 0)]
    descriptions = [f"{r.strategy}/{r.asset}/{r.timeframe}" for r in mf.itertuples()]
    duplicate = [
        (key, p)
        for key, ps in overlaps.items()
        for p in ps
        if (p["holding_bar_jaccard_pct"] or 0) >= 80
    ]
    stable = valid[valid.positive_year_ratio >= 0.6]
    by_asset = valid.groupby(["strategy", "asset"]).return_pct.max().unstack()
    btc_only = (
        ", ".join(by_asset.index[(by_asset.BTCUSDT > 0) & (by_asset.ETHUSDT <= 0)]) or "ninguna"
    )
    entry_candidates = valid[(valid.mfe_mae_ratio <= 1) & (valid.return_pct < 0)]
    entry_names = (
        ", ".join(f"{r.strategy}/{r.asset}/{r.timeframe}" for r in entry_candidates.itertuples())
        or "ninguna"
    )
    recommendation = (
        "B: investigar 4h en un protocolo nuevo"
        if (improvement > 0).mean() > 0.5
        else "D: mantener multiples timeframes en investigacion"
    )
    if len(mf):
        recommendation += "; F: estudiar captura de MFE y salidas"
    four_stats = {}
    for asset in ("BTCUSDT", "ETHUSDT"):
        part = valid[(valid.asset == asset) & (valid.timeframe == "4h")]
        four_stats[asset] = (
            f"{int((part.return_pct > 0).sum())}/{len(part)} positivas; "
            f"retorno mediano {fmt(part.return_pct.median())}%, "
            f"Sharpe mediano {fmt(part.sharpe.median())}, "
            f"PF mediano {fmt(part.profit_factor.median())}."
        )
    lines = [
        "# Cross-market timeframe study 001",
        "",
        (
            "Estudio descriptivo congelado. Sin optimizacion, nuevas "
            "estrategias, cartera ni operativa real."
        ),
        (
            f"114 combinaciones previstas; {len(valid)} ejecutadas "
            f"y {len(df) - len(valid)} no representables sin "
            f"cambiar hipotesis."
        ),
        (
            f"Datos comunes: {audit['common_days']} dias completos. "
            f"Los originales, exclusiones y discrepancias estan "
            f"en dataset_audit.json."
        ),
        (
            "ETH es CROSS_ASSET_VALIDATION bajo la traduccion temporal "
            "congelada. BTC conserva el sesgo de historia observada;2026 "
            "aparece separado en annual_metrics.csv."
        ),
        (
            "Cada cuenta parte de10000USDT. Los retornos de cuentas distintas "
            "nunca se suman. Los huecos cierran posiciones y reinician "
            "indicadores; el efectivo queda inmovil hasta el siguiente tramo."
        ),
        (
            "Splits50/20/15/15 de tiempo calendario. El holdout se desbloqueo "
            "solo tras todos los runs train/validation/test, sin seleccion. "
            "Full y anual son diagnosticos posteriores, no nuevas pruebas "
            "independientes."
        ),
        "",
        (
            f"1. **1h a4h:** mejoran {int((improvement > 0).sum())}/{len(improvement)} "
            f"pares comparables; diferencia mediana {fmt(improvement.median())} "
            f"puntos de retorno. No implica elegir4h retrospectivamente."
        ),
        (
            f"2. **1d:** {int((daily.return_pct > 0).sum())}/{len(daily)} "
            f"combinaciones positivas; retorno mediano {fmt(daily.return_pct.median())}%, "
            f"operaciones medianas {fmt(daily.closed_trades.median())}."
        ),
        (
            f"3. **Costes:** familias con cambio de signo al "
            f"introducir costes: {cost_sensitive}. cost_analysis.json "
            f"separa zero/base/adverse y gross-profit denominator; "
            f"el cambio de frecuencia no demuestra causalidad "
            f"por si solo."
        ),
        (
            f"4. **Generalizacion BTC/ETH:** cumplen el criterio "
            f"descriptivo predefinido CROSS_MARKET_PROMISING: "
            f"{names('CROSS_MARKET_PROMISING')}."
        ),
        (
            f"5. **Solo BTC positivo en alguna combinacion:** {btc_only}. "
            f"Las tablas distinguen que activo es positivo; esta "
            f"flag no significa automaticamente BTC-only."
        ),
        (
            f"6. **Dependencia del timeframe:** {names('TIMEFRAME_DEPENDENT')}; "
            f"medianas positivas en alguno y no positivas en "
            f"otro."
        ),
        (
            f"7. **Varios anos positivos:** {len(stable)} combinaciones "
            f"tienen al menos60% de anos calendario completos "
            f"positivos. Los anos parciales se informan pero "
            f"no entran en ese porcentaje."
        ),
        "8. **MFE/MAE>1 con PnL negativo:** "
        + (", ".join(descriptions) or "ninguna")
        + (
            ". Son cocientes de medias de cotas inferiores; no identifican el "
            "recorrido intrabar verdadero."
        ),
        (
            "9. **Salidas:** las combinaciones enumeradas en el punto8 motivan estudiar captura del"
            " recorrido favorable. No prueban un fallo de salida: secuencia "
            "intrabar, costes y seleccion de operaciones tambien influyen."
        ),
        (
            f"10. **Entradas candidatas a revision (MFE/MAE<=1 y PnL<0):** {entry_names}. "
            "El follow-through por horizonte permite"
            " revisar la hipotesis; time_to_edge.json muestra horizontes y "
            "censura. Este estudio no identifica causalmente entrada frente a "
            "salida."
        ),
        "11. **Duplicacion:** "
        + (
            "; ".join(
                f"{k}: {p['a']} / {p['b']} ({p['holding_bar_jaccard_pct']:.1f}% holding Jaccard)"
                for k, p in duplicate
            )
            or "ningun par supera80% de holding Jaccard"
        )
        + ". Comparar tambien correlacion diaria; no son medidas equivalentes.",
        (
            f"12. **BTC4h:** {four_stats['BTCUSDT']} Ver4h_analysis.md; cuenta "
            "independiente para cada estrategia."
        ),
        (
            f"13. **ETH4h:** {four_stats['ETHUSDT']} Mismo protocolo, sin ajustes tras "
            "observar ETH; ver4h_analysis.md."
        ),
        (
            f"14. **Investigacion posterior:** {recommendation}. "
            "Recomendacion exploratoria basada en estos diagnosticos, no seleccion de "
            "timeframe para invertir. Cualquier estudio posterior exige nuevo plan "
            "predefinido y datos futuros; no se crea Batch006."
        ),
        "",
        (
            "Mercados/timeframes positivos usan la mediana de combinaciones "
            "evaluables. PF sin perdidas y ratios sin denominador quedan NA, "
            "no infinito. >=30 trades es solo un umbral descriptivo."
        ),
        (
            "Monte Carlo: full/base con>=30 operaciones,10000 permutaciones "
            "y10000 bootstrap, semillas y muestras guardadas. PnL nominal "
            "fijo, sin re-sizing; no pronostico."
        ),
        (
            "La estabilidad anual usa reinicios independientes cada ano (con "
            "warmup causal), por tanto sus retornos no son una descomposicion "
            "aditiva del run full."
        ),
        "",
        markdown(
            df.fillna({"reason": ""}),
            [
                "strategy",
                "asset",
                "timeframe",
                "return_pct",
                "sharpe",
                "profit_factor",
                "max_drawdown_pct",
                "closed_trades",
                "trades_per_year",
                "cost_drag",
                "mfe_mae_ratio",
                "positive_year_ratio",
                "classification",
                "status",
            ],
        ),
    ]
    (path / "summary.md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    four = [
        "# Diagnostico4h frente a1h",
        "",
        (
            "Mismos parametros, hipotesis y fechas comparables; no seleccion "
            "posterior. Excluye MTF4h por incompatibilidad conceptual."
        ),
        "",
    ]
    for asset in ("BTCUSDT", "ETHUSDT"):
        group = valid[(valid.asset == asset) & valid.timeframe.isin(["1h", "4h"])].sort_values(
            ["strategy", "timeframe"]
        )
        four += [
            asset,
            "",
            markdown(
                group,
                [
                    "strategy",
                    "timeframe",
                    "closed_trades",
                    "gross_return_pct",
                    "return_pct",
                    "cost_drag",
                    "sharpe",
                    "profit_factor",
                    "max_drawdown_pct",
                    "mean_mfe_pct",
                    "mean_mae_pct",
                    "mfe_mae_ratio",
                    "positive_year_ratio",
                ],
            ),
            "",
        ]
    (path / "4h_analysis.md").write_text("\n".join(four), encoding="utf-8")
