"""Rebuildable shadow views, grouped by independent alternative and currency."""

import csv
import json
from statistics import mean, median


def write_csv(path, rows, fields=()):
    names = sorted({k for r in rows for k in r}) or list(fields) or ["no_records"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def stats(rows):
    closed = [p for p in rows if p["status"] == "CLOSED"]
    opened = [p for p in rows if p["status"] == "OPEN"]
    usable = [p for p in opened if p["coverage"] == "CONTINUOUS"]
    wins = [p["realized_pnl_net"] for p in closed if p["realized_pnl_net"] > 0]
    losses = [p["realized_pnl_net"] for p in closed if p["realized_pnl_net"] < 0]
    return dict(
        open_positions=len(opened),
        closed_positions=len(closed),
        unknown_or_stale_open_positions=len(opened) - len(usable),
        realized_gross_pnl=sum(p["realized_pnl_gross"] for p in closed),
        realized_net_pnl=sum(p["realized_pnl_net"] for p in closed),
        realized_costs=sum(p["total_cost"] for p in closed),
        estimated_open_costs=sum(p["entry_cost"] + p["estimated_exit_cost"] for p in usable),
        unrealized_gross_pnl=sum(p["unrealized_pnl_gross"] for p in usable) if usable else None,
        unrealized_net_pnl_estimate=sum(p["unrealized_pnl_net_estimate"] for p in usable)
        if usable
        else None,
        wins=len(wins),
        losses=len(losses),
        breakeven=len(closed) - len(wins) - len(losses),
        win_rate=100 * len(wins) / len(closed) if closed else None,
        average_winner=mean(wins) if wins else None,
        average_loser=mean(losses) if losses else None,
        profit_factor=sum(wins) / -sum(losses) if losses else None,
        average_mfe=mean(p["mfe_pnl"] for p in closed) if closed else None,
        average_mae=mean(p["mae_pnl"] for p in closed) if closed else None,
        sample_note="Descriptive only; no statistical superiority or significance claimed",
    )


def comparison(rows):
    groups = {}
    for p in rows:
        if p.get("signal_id"):
            key = (p["signal_id"], p["instrument"], p["side"], p["settlement_currency"])
            pair = groups.setdefault(key, {})
            if p["execution_policy"] in pair:
                raise ValueError("Ambiguous duplicate alternative for signal")
            pair[p["execution_policy"]] = p
    result = []
    for (signal, instrument, side, currency), pair in groups.items():
        if not {"BASELINE", "OPTIONAL_15M_FILL"} <= pair.keys():
            continue
        b, o = pair["BASELINE"], pair["OPTIONAL_15M_FILL"]
        improvement = (b["entry_price"] - o["entry_price"]) * (1 if side == "LONG" else -1)
        complete = all(p["status"] == "CLOSED" and p["coverage"] == "CONTINUOUS" for p in (b, o))
        r = dict(
            signal_id=signal,
            instrument=instrument,
            side=side,
            settlement_currency=currency,
            baseline_entry=b["entry_price"],
            optimized_entry=o["entry_price"],
            entry_improvement_abs=improvement,
            entry_improvement_pct=100 * improvement / b["entry_price"],
            paired_closed=complete,
            pnl_difference=o["realized_pnl_net"] - b["realized_pnl_net"] if complete else None,
        )
        for prefix, p in (("baseline", b), ("optimized", o)):
            r.update(
                {
                    prefix + "_exit": p["exit_price"],
                    prefix + "_net_pnl": p["realized_pnl_net"],
                    prefix + "_MFE": p["mfe_pnl"],
                    prefix + "_MAE": p["mae_pnl"],
                    prefix + "_status": p["status"],
                    prefix + "_coverage": p["coverage"],
                }
            )
        result.append(r)
    return result


def render(path, positions, *, reconstructed=False):
    rows = sorted(positions.values(), key=lambda p: p["shadow_position_id"])
    suffix = "_reconstructed" if reconstructed else ""
    write_csv(path / f"shadow_positions{suffix}.csv", rows, ["shadow_position_id", "status"])
    # CSV is a deterministic projection; the journal's CLOSED events are append-only.
    write_csv(
        path / f"shadow_trades{suffix}.csv",
        [p for p in rows if p["status"] == "CLOSED"],
        ["shadow_position_id", "realized_pnl_net"],
    )
    pairs = comparison(rows)
    write_csv(path / "entry_timing_comparison.csv", pairs, ["signal_id", "pnl_difference"])
    sections = [
        "## Shadow Trading",
        "HYPOTHETICAL / SHADOW RESULTS. No real or demo executions. "
        "Accounts = independent alternatives, not a combined portfolio. "
        "Funding/liquidations not modelled. Open PnL is as-of the last verified bar, "
        "not a live quote. "
        "Gross fill PnL already includes spread/slippage; subtract fees only for net. "
        "Total cost separately attributes fees + modeled spread/slippage. "
        "MFE/MAE are observational bounds when entry/stop intrabar ordering is unknown.",
    ]
    for strategy, currency in sorted({(p["strategy"], p["settlement_currency"]) for p in rows}):
        subset = [
            p for p in rows if (p["strategy"], p["settlement_currency"]) == (strategy, currency)
        ]
        sections += [f"### {strategy} ({currency})", json.dumps(stats(subset), sort_keys=True)]
    for p in rows:
        if p["status"] == "OPEN":
            sections += ["### OPEN", json.dumps(p, sort_keys=True)]
    sections += [
        "## Entry Timing Comparison",
        "Final PnL comparisons require both alternatives CLOSED; no combined portfolio.",
    ]
    for currency in sorted({p["settlement_currency"] for p in pairs}):
        subset = [p for p in pairs if p["settlement_currency"] == currency]
        closed = [p for p in subset if p["paired_closed"]]
        values = [p["entry_improvement_abs"] for p in subset]
        total = dict(
            currency=currency,
            paired_signals=len(subset),
            paired_closed=len(closed),
            optimized_entry_better_count=sum(v > 0 for v in values),
            optimized_entry_worse_count=sum(v < 0 for v in values),
            average_entry_improvement=mean(values),
            median_entry_improvement=median(values),
            baseline_total_net_pnl=sum(p["baseline_net_pnl"] for p in closed) if closed else None,
            optimized_total_net_pnl=sum(p["optimized_net_pnl"] for p in closed) if closed else None,
            pnl_delta=sum(p["pnl_difference"] for p in closed) if closed else None,
            baseline_win_rate=100 * sum(p["baseline_net_pnl"] > 0 for p in closed) / len(closed)
            if closed
            else None,
            optimized_win_rate=100 * sum(p["optimized_net_pnl"] > 0 for p in closed) / len(closed)
            if closed
            else None,
        )
        sections.append(json.dumps(total, sort_keys=True))
    sections += [json.dumps(p, sort_keys=True) for p in pairs]
    return "\n\n".join(sections) + "\n"
