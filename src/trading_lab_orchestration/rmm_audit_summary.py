"""Descriptive presentation of the verified RMM paired evidence."""

from statistics import median


def delta_overview(comparison):
    lines = []
    for period in comparison["periods"]:
        groups = []
        for asset in ("BTCUSDT", "ETHUSDT"):
            values = [
                row["delta_sharpe"]
                for row in comparison["paired_metrics"]
                if row["period"] == period and row["asset"] == asset
            ]
            defined = [value for value in values if value is not None]
            change = f"{median(defined):+.3f}" if defined else "indefinida"
            up = sum(value > 0 for value in defined)
            down = sum(value < 0 for value in defined)
            groups.append(
                f"{asset} {up}↑/{down}↓ de {len(values)}, mediana {change}"
                + (
                    f", {len(values) - len(defined)} sin dato"
                    if len(values) != len(defined)
                    else ""
                )
            )
        lines.append(f"{period.upper()}: " + " · ".join(groups))
    return lines


def paired_report_lines(comparison):
    branches = comparison["branches"]
    lines = [
        "## Comparación emparejada BASE",
        "",
        f"- RMM congelado: `{branches['baseline']['run_id']}`.",
        f"- Variante de 28 días: `{branches['variant']['run_id']}`.",
        "- Se verificaron los dos ledgers y los 12 pares de comparison.json contra el recibo.",
        "",
        *delta_overview(comparison),
        "",
        "Los cambios son variante menos baseline. "
        "Exposición y drawdown están en puntos porcentuales.",
        "Los casos por activo, modo y ventana son simulaciones separadas.",
        "",
        "| Ventana | Activo | Modo | Δ Sharpe neto | Δ Operaciones | "
        "Δ Exposición (pp) | Δ Drawdown (pp) |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in sorted(
        comparison["paired_metrics"],
        key=lambda item: (comparison["periods"].index(item["period"]), item["asset"], item["mode"]),
    ):
        cells = [row["period"].upper(), row["asset"], row["mode"]]
        for field, decimals in (
            ("sharpe", 3),
            ("closed_trades", 0),
            ("average_close_exposure_pct", 2),
            ("max_drawdown_pct", 2),
        ):
            before, after = row["baseline"][field], row["variant"][field]
            cells.append(
                "indefinido"
                if before is None or after is None
                else f"{after - before:+.{decimals}f}"
            )
        lines.append("| " + " | ".join(cells) + " |")
    return lines + ["", "Pendientes: TEST, ADVERSE y controles SMA28 y aleatorio.", ""]
