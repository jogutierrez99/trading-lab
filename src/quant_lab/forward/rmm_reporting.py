"""Separate observed demo execution and modeled independent shadow accounts."""

from collections import Counter
from statistics import mean

import pandas as pd

from quant_lab.forward.shadow_reporting import render, stats, write_csv
from quant_lab.forward.store import encode


def report(store):
    state = store.restore() or {}
    orders, fills = store.rows("orders"), store.rows("fills")
    trades = state.get("demo_trades", [])
    events = store.rows("events", session=True)
    write_csv(store.path / "demo_orders.csv", orders)
    write_csv(store.path / "demo_fills.csv", fills)
    write_csv(store.path / "demo_trades.csv", trades)
    write_csv(
        store.path / "demo_expected_vs_observed.csv", [r for r in orders if r.get("exchange")]
    )
    comparisons = [r for r in orders if r["status"] == "FILLED"]
    nets = [
        t["net_pnl_excluding_funding"]
        for t in trades
        if t.get("net_pnl_excluding_funding") is not None
    ]
    equity, peak, drawdown = 10000.0, 10000.0, 0.0
    for net in nets:
        equity += net
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak * 100)
    metrics = dict(
        closed_trades=len(trades),
        wins=sum(n > 0 for n in nets),
        losses=sum(n < 0 for n in nets),
        gross_pnl=sum(t["gross_pnl"] for t in trades),
        net_pnl_excluding_funding=sum(nets) if len(nets) == len(trades) else None,
        funding="unknown; not invented",
        equity_excluding_funding=state.get("demo_equity_excluding_funding", 10000.0),
        expectancy=mean(nets) if nets else None,
        win_rate=sum(n > 0 for n in nets) / len(nets) if nets else None,
        profit_factor=sum(n for n in nets if n > 0) / -sum(n for n in nets if n < 0)
        if any(n < 0 for n in nets)
        else None,
        open_position=state.get("demo_position"),
        pending_order=state.get("demo_pending_order"),
        realized_drawdown_pct_excluding_funding=drawdown if len(nets) == len(trades) else None,
        average_holding_seconds=mean(t["holding_seconds"] for t in trades) if trades else None,
        average_mfe=mean(t["mfe_pnl"] for t in trades) if trades else None,
        average_mae=mean(t["mae_pnl"] for t in trades) if trades else None,
        total_fees_by_currency=dict(sum_fees(fills)),
        average_sizing_deviation=mean(r["sizing_deviation"] for r in comparisons)
        if comparisons
        else None,
        average_latency_ms=mean(r["latency_ms"] for r in comparisons) if comparisons else None,
        average_slippage_bps=mean(r["slippage_bps"] for r in comparisons) if comparisons else None,
    )
    runtime = (
        pd.Timestamp(store.metadata.get("end") or pd.Timestamp.now(tz="UTC"))
        - pd.Timestamp(store.metadata["start"])
    ).total_seconds()
    restart_count = (
        store.db.execute(
            "SELECT count(*) FROM sessions WHERE json_extract(data,'$.stream_id')=?",
            (store.stream,),
        ).fetchone()[0]
        - 1
    )
    counts = dict(Counter(e["kind"] for e in events)) | dict(
        runtime_seconds=runtime, restarts=restart_count
    )
    demo = "## OKX DEMO FILLED\n\n" + encode(metrics)
    (store.path / "demo_pnl.md").write_text(demo + "\n", encoding="utf-8")
    shadow = state.get("shadow_positions", {})
    if store.gaps(unresolved=True):
        shadow = {
            k: p | {"coverage": "DATA_GAP"} if p["status"] == "OPEN" else p
            for k, p in shadow.items()
        }
    shadow_text = render(store.path, shadow)
    shadow_metrics = []
    for name in store.metadata["config"]["forward"]["strategies"]:
        subset = [p for p in shadow.values() if p["strategy"] == name]
        closed = sorted(
            (p for p in subset if p["status"] == "CLOSED"), key=lambda p: p["exit_timestamp"]
        )
        virtual, top, dd = 10000.0, 10000.0, 0.0
        for p in closed:
            virtual += p["realized_pnl_net"]
            top = max(top, virtual)
            dd = max(dd, (top - virtual) / top * 100)
        opened = [p for p in subset if p["status"] == "OPEN"]
        shadow_metrics.append(
            stats(subset)
            | dict(
                strategy=name,
                role="SHADOW_CANDIDATE" if name.endswith("shadow") else "MAIN",
                realized_drawdown_pct=dd,
                expectancy=mean(p["realized_pnl_net"] for p in closed) if closed else None,
                average_holding_seconds=mean(p["holding_seconds"] for p in closed)
                if closed
                else None,
                total_fees=sum(p["entry_fee"] + p["exit_fee"] for p in subset),
                modeled_spread=sum(p["entry_spread"] + p["exit_spread"] for p in subset),
                modeled_slippage=sum(p["entry_slippage"] + p["exit_slippage"] for p in subset),
                current_exposure_pct=sum(p["quantity"] * p["current_price"] for p in opened)
                / virtual
                * 100
                if virtual > 0 and all(p["coverage"] == "CONTINUOUS" for p in opened)
                else None,
            )
        )
    write_csv(store.path / "rmm_shadow_metrics.csv", shadow_metrics)
    shadow_text += "\n\n## Independent shadow metrics\n\n" + encode(shadow_metrics)
    (store.path / "shadow_pnl_summary.md").write_text(shadow_text, encoding="utf-8")
    text = "\n\n".join(
        [
            "# RMM 4h forward",
            encode(store.metadata),
            "## Operational metrics",
            encode(counts),
            "## Execution assumptions",
            "Independent 10,000 virtual accounts; only selected MAIN routes demo orders. "
            "BASE costs apply to shadow only. Demo fee currencies/fills remain observed; "
            "net/equity exclude unknown funding. "
            "Exchange mark PnL is separately in broker_state.csv. "
            "Market fills after confirmed close differ from historical next-open fills. "
            "Pending/partial fills pause new submissions and are reconciled on heartbeat. "
            "Ambiguous/rejected orders stop execution for review.",
            shadow_text,
            demo,
        ]
    )
    for name in ("summary.md", "ai_summary.md"):
        (store.path / name).write_text(text + "\n", encoding="utf-8")


def sum_fees(fills):
    totals = Counter()
    for fill in fills:
        if fill.get("fee") is not None:
            totals[fill.get("feeCcy", "unknown")] += float(fill["fee"])
    return totals
