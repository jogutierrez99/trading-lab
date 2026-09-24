"""Post-run price excursions and fixed-horizon follow-through, never trading inputs."""

import numpy as np
import pandas as pd

HORIZONS = (6, 12, 24, 48, 72)


def summarize_values(values):
    clean = [v for v in values if v is not None]
    return {
        "n": len(clean),
        "mean": float(np.mean(clean)) if clean else None,
        "median": float(np.median(clean)) if clean else None,
    }


def entry_diagnostics(frame, result):
    quality, edges = [], []
    for i, t in enumerate(result.trades):
        if t.side != "long":
            raise ValueError("Batch005 excursion analysis supports long trades only")
        entry = pd.Timestamp(t.entry_time)
        exit_bar = pd.Timestamp(t.exit_bar_open)
        # Complete bars before the exit bar were certainly traversed while in position.
        complete = frame.loc[(frame.index >= entry) & (frame.index < exit_bar)]
        if t.exit_timing == "close":
            complete = frame.loc[(frame.index >= entry) & (frame.index <= exit_bar)]
        highs = [(t.entry_reference, 0.0, 0.0)]
        lows = [(t.entry_reference, 0.0, 0.0)]
        for time, row in complete.iterrows():
            hours = (time - entry).total_seconds() / 3600
            highs.append((float(row.high), hours, hours + 1))
            lows.append((float(row.low), hours, hours + 1))
        exit_hours = (exit_bar - entry).total_seconds() / 3600
        bounds = (
            (exit_hours, exit_hours + 1)
            if t.exit_timing == "intrabar"
            else (
                (exit_hours + 1, exit_hours + 1)
                if t.exit_timing == "close"
                else (exit_hours, exit_hours)
            )
        )
        highs.append((t.exit_reference, *bounds))
        lows.append((t.exit_reference, *bounds))
        peak = max(highs, key=lambda x: x[0])
        trough = min(lows, key=lambda x: x[0])
        upper_peak, lower_trough = peak[0], trough[0]
        if t.exit_timing == "intrabar":
            upper_peak = max(upper_peak, float(frame.loc[exit_bar, "high"]))
            lower_trough = min(lower_trough, float(frame.loc[exit_bar, "low"]))
        mfe = (peak[0] / t.entry_reference - 1) * 100
        mae = (1 - trough[0] / t.entry_reference) * 100
        quality.append(
            {
                "trade_index": i,
                "entry_time": str(entry),
                "exit_bar_open": str(exit_bar),
                "mfe_pct": mfe,
                "mae_pct": mae,
                "mfe_mae_ratio": mfe / mae if mae > 0 else None,
                "mfe_upper_bound_pct": (upper_peak / t.entry_reference - 1) * 100,
                "mae_upper_bound_pct": (1 - lower_trough / t.entry_reference) * 100,
                "intrabar_censored": t.exit_timing == "intrabar",
                "time_to_mfe_hours_lower": peak[1],
                "time_to_mfe_hours_upper": peak[2],
                "time_to_mae_hours_lower": trough[1],
                "time_to_mae_hours_upper": trough[2],
            }
        )
        returns = {}
        for h in HORIZONS:
            bar = entry + pd.Timedelta(hours=h - 1)
            # The close at entry+h is unavailable outside this partition, even if a
            # parent dataset has future data. Continuing after trade exit is intentional.
            returns[str(h)] = (
                float((frame.loc[bar, "close"] / t.entry_reference - 1) * 100)
                if (bar in frame.index and bar + pd.Timedelta(hours=1) <= result.equity.index[-1])
                else None
            )
        edges.append({"trade_index": i, "entry_time": str(entry), "returns_pct": returns})
    fields = (
        "mfe_pct",
        "mae_pct",
        "mfe_mae_ratio",
        "mfe_upper_bound_pct",
        "mae_upper_bound_pct",
        "time_to_mfe_hours_lower",
        "time_to_mfe_hours_upper",
        "time_to_mae_hours_lower",
        "time_to_mae_hours_upper",
    )
    summary = {key: summarize_values([r[key] for r in quality]) for key in fields}
    mean_mfe, mean_mae = summary["mfe_pct"]["mean"], summary["mae_pct"]["mean"]
    ratio = mean_mfe / mean_mae if mean_mae is not None and mean_mae > 0 else None
    q = {
        "trades": quality,
        "summary": summary,
        "ratio_of_mean_mfe_mae": ratio,
        "intrabar_censored_trades": sum(r["intrabar_censored"] for r in quality),
        "convention": "Before-cost price excursions relative to entry reference; MAE "
        "positive magnitude. "
        "Open exits exclude exit-bar H/L. Intrabar exits use certain prior extrema and exit price "
        "as lower bounds; full exit-bar extrema only as upper bounds. Ratio of lower bounds is "
        "descriptive, not an identified true excursion ratio. Times are first-extremum hour "
        "intervals (not exact event times), conditional on observed/lower-bound extrema.",
    }
    edge_summary = {
        str(h): summarize_values([r["returns_pct"][str(h)] for r in edges]) for h in HORIZONS
    }
    for item in edge_summary.values():
        item["censored"] = len(edges) - item["n"]
    e = {
        "trades": edges,
        "summary": edge_summary,
        "convention": "Asset close at entry+h hours / entry opening reference -1, before costs. "
        "May extend after exit but never beyond partition. Missing horizons are censored, "
        "not zero. Overlapping signals/horizons are not independent observations. "
        "Post-run diagnostics only; no evidence by themselves of an actionable edge.",
    }
    metrics = {
        "mean_mfe_pct": mean_mfe,
        "median_mfe_pct": summary["mfe_pct"]["median"],
        "mean_mae_pct": mean_mae,
        "median_mae_pct": summary["mae_pct"]["median"],
        "mfe_mae_ratio": ratio,
        "excursion_intrabar_censored_trades": q["intrabar_censored_trades"],
    }
    return q, e, metrics
