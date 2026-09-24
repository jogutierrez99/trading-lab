"""Render a completed batch without rerunning or selecting any strategy."""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter

from quant_lab.metrics import daily_returns


def render(folder: Path, output_name: str = "charts") -> Path:
    metrics = pd.read_csv(folder / "metrics.csv")
    if Path(output_name).name != output_name:
        raise ValueError("Chart output must be a directory name within the run")
    output = folder / output_name
    output.mkdir(exist_ok=False)
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.2})
    chosen = metrics.loc[
        metrics.partition.isin(
            ["full_baseline_diagnostic", "test", "final_holdout", "legacy_baseline_diagnostic"]
        )
        & metrics.costs.eq("base")
    ]
    for row in chosen.itertuples():
        path = folder / row.experiment_id
        data = json.loads((path / "result.json").read_text(encoding="utf-8"))
        equity = pd.read_parquet(path / "equity.parquet").equity
        returns = daily_returns(equity)
        fig, axes = plt.subplots(3, 2, figsize=(13, 10), constrained_layout=True)
        fig.suptitle(f"{row.candidate} | {row.partition} | BTC spot 1h long | base costs")
        axes[0, 0].plot(equity.index, equity, color="#176787")
        axes[0, 0].set(title="Equity (USDT)", ylabel="USDT")
        dd = (equity / equity.cummax() - 1) * 100
        axes[0, 1].fill_between(dd.index, dd.values, color="#b95050", alpha=0.7)
        axes[0, 1].set(title="Drawdown (%)", ylabel="%")
        monthly = ((1 + returns).resample("MS").prod() - 1) * 100
        axes[1, 0].bar(
            monthly.index.strftime("%Y-%m"),
            monthly.values,
            color=["#247b68" if v >= 0 else "#b95050" for v in monthly],
        )
        axes[1, 0].set(title="Monthly net returns (%)", ylabel="%")
        axes[1, 0].tick_params(axis="x", rotation=55)
        rolling = returns.rolling(90).mean() / returns.rolling(90).std() * 365**0.5
        rolling = rolling.replace([float("inf"), -float("inf")], float("nan"))
        axes[1, 1].plot(rolling.index, rolling.values)
        axes[1, 1].set(title="Rolling Sharpe (90 daily observations)")
        if not rolling.notna().any():
            axes[1, 1].text(
                0.5, 0.5, "Insufficient observations", ha="center", transform=axes[1, 1].transAxes
            )
        pnl = [t["net_pnl"] for t in data["trades"]]
        if pnl:
            axes[2, 0].hist(pnl, bins=min(20, max(3, len(pnl) // 3)), color="#176787")
        else:
            axes[2, 0].text(0.5, 0.5, "No trades", transform=axes[2, 0].transAxes)
        axes[2, 0].set(title="Closed trade PnL", xlabel="USDT", ylabel="Trades")
        exposure = pd.read_parquet(path / "equity.parquet").close_exposure * 100
        axes[2, 1].plot(exposure.index, exposure.values, color="#80623e")
        axes[2, 1].set(title="End-of-bar notional exposure (%)", ylabel="% of equity")
        for axis in (axes[0, 0], axes[0, 1], axes[1, 1], axes[2, 1]):
            locator = AutoDateLocator(minticks=3, maxticks=5)
            axis.xaxis.set_major_locator(locator)
            axis.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        fig.savefig(output / f"{row.partition}_{row.candidate}.png", dpi=140)
        plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True, constrained_layout=True)
    full_row = metrics.loc[metrics.partition.eq("full_baseline_diagnostic")].iloc[0]
    full_equity = pd.read_parquet(folder / full_row.experiment_id / "equity.parquet").equity
    fig.suptitle(
        f"BTC spot 1h | {full_equity.index[0]:%Y-%m-%d} - "
        f"{full_equity.index[-1]:%Y-%m-%d} | baselines, descriptive only"
    )
    comparison = metrics.loc[
        metrics.partition.isin(["full_baseline_diagnostic", "benchmark_full_baseline_diagnostic"])
        & metrics.costs.eq("base")
    ]
    for row in comparison.itertuples():
        equity = pd.read_parquet(folder / row.experiment_id / "equity.parquet").equity
        label = (
            row.candidate if pd.isna(row.benchmark_pct) else f"Buy & hold {row.benchmark_pct:g}%"
        )
        style = "-" if pd.isna(row.benchmark_pct) else "--"
        axes[0].plot(equity.index, equity, style, label=label, linewidth=1.3)
        axes[1].plot(
            equity.index, (equity / equity.cummax() - 1) * 100, style, label=label, linewidth=1.3
        )
    axes[0].set(ylabel="Equity (USDT)")
    axes[1].set(ylabel="Drawdown (%)")
    axes[0].legend(loc="lower left", fontsize=9)
    fig.savefig(output / "overview.png", dpi=140)
    plt.close(fig)
    (output / "render_provenance.json").write_text(
        json.dumps(
            {
                "matplotlib": matplotlib.__version__,
                "plot_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "note": "Rendering existing results only; no backtests rerun.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output-name", default="charts")
    args = parser.parse_args()
    print(render(args.results, args.output_name).resolve())
