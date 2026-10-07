# ETH SHORT regime challenge V1

Study ID: `eth_short_regime_challenge_v1`. **POST-SELECTION EXPLORATORY
REGIME ANALYSIS**. The user's previous ETH SHORT TEST interpretation motivates
these hypotheses; this implementation does not independently re-audit that previous
economic evidence or assert it is profitable.

> This study is exploratory regime analysis based on hypotheses generated after
> observing previous TEST results. It is not an independent holdout and does not
> constitute paper-trading approval.

## Frozen scope

Only ETHUSDT, 1h, SHORT_ONLY. Main hypotheses: `atr_volatility_breakout` and
`donchian_atr_breakout`; `donchian_trend_breakout` is control only. No signal changes,
new entry filters, BTC/LONG/combined, new strategy families, or forward/OKX integration.
The existing [Trend Expansion protocol](trend-expansion-v1.md) and original YAMLs
remain unchanged. Three new ordinary experiments use the same enabled profiles:

| Experiment suffix | Frozen grid | Configurations | Backtests |
|---|---|---:|---:|
| `_atr` | impulse 0.75/1/1.25; expansion 1.1/1.25 | 6 | 140 |
| `_donchian_atr` | channel 30/40/50; expansion 1.1/1.25 | 6 | 140 |
| `_donchian` | channel 30/40/50 | 3 | 74 |

Total **354**, for local user execution. ATR14, previous ATR mean50, EMA200 slope5,
stop2ATR and RR2 stay fixed. No selection of the best TEST configuration.
Risk/execution/capital inherit the existing profiles and original experiments.
The pinned local ETH bundle is
`1006e4cb8296ab8d1574317f2927c7feb975bbd25a5f195a8c7d97a17d7b70e4`, warmup1000.
Missing/corrupt data fails; nothing is downloaded or silently substituted.
Synthetic collateralized execution on USD-M prices models no funding, borrowing
or liquidations; it is not a perpetual live simulation.

TRAIN 2023-06-04→2024-07-01, VALIDATION 2024-07-01→2025-01-01,
TEST 2025-07-01→2026-09-26, UTC with exclusive end. All four original WF folds
and TRAIN/base Sharpe selection are unchanged. WF TEST evidence is for the adaptive
selection policy, not every fixed neighbor. No changes to existing classifier gates.

Annual diagnostic reruns are predeclared: 2023-06-04→2024-01-01;
2024-01-01→2025-01-01; 2025-01-01→2026-01-01;
2026-01-01→2026-09-26. 2023/2026 are partial. Capital resets at every segment,
and endpoints liquidate. Annual/main/WF windows overlap: never pool their trades or
treat them as independent replications. Annual periods do not enter ranking or gates.

BASE fee/slippage/full spread: 0.05/0.03/0.01%; ADVERSE: 0.10/0.06/0.02%.
`*_pct` is percentage units; fees on both sides, half-spread per fill. Both scenarios
are actual reruns, so costs can change equity, sizing and trade paths.

## Causal descriptive regimes

Only two variables, frozen before this new study is run:

- Direction: bearish when close<EMA200 and EMA200[t]-EMA200[t-5]<0; bullish when
  both signs are positive; mixed otherwise. Undefined EMA warmup is unavailable.
- Volatility: ATR14[t] / mean(ATR14[t-50:t-1]); high >=1.1, ordinary <1.1;
  invalid/undefined denominator is unavailable. This threshold is descriptive and
  coincides with a previously used ATR expansion level; no extra percentile fit.
- Combined: Cartesian product including unavailable, with explicit empty cells.

Features are computed separately for each execution period, using its same warmup
origin; gaps reset rolling/EMA state. Candle index is OPEN time. Each trade is tagged
at `signal_close-1h`, when its signal candle closed, using no next-open or future data.
These functions are report-only and are never imported by strategies or execution.

Every bucket retains run/configuration/backtest/period/scenario identity and shows
counts, PF, expectancy, net PnL and trade/PnL shares. No candidate/period pooling.
Fewer than **20 trades** is `INSUFFICIENT_SAMPLE`, including zero and three trades.
20 is a descriptive annotation, not statistical significance or a profitability gate.
PF without losses is undefined; net PnL share with non-positive total is undefined.
Positive-total shares can exceed100% when losing buckets offset gains.

EMA slope short entries already structurally favor bearish labels; ATR entry rules
favor high ATR labels. Apparent concentration alone cannot prove conditional edge.
This design has no regime opportunity/exposure matched control, confidence claim,
ADX grid, new filter or automatic economic decision. Compare hybrid vs pure Donchian
and ATR vs hybrid in matched windows/costs across the full neighboring regions.
Use negative periods to inspect failure regimes; do not rank or retune on TEST.

## Reporting and interpretation

The report audits completed ordinary runs, ledger/result/equity hashes and pinned
dataset bytes; requires equal execution/data/period/cost/risk/code assumptions across
families and the exact frozen study YAML in run provenance. Original/resolved plans,
strategy versions, parameter risks, code/Git/environment, source IDs/hashes and study
protocol are included in `sources.json` / published `metadata.json`.
`configs/research/eth_short_regime_challenge_v1.yaml` fixes configuration/profile and
report implementation hashes. Any migration needs a separately named protocol;
do not regenerate that lock to legitimize retrospective changes.

The four allowed descriptive labels are REJECTED, REGIME_DEPENDENT,
ROBUST_RESEARCH_SURVIVOR and INSUFFICIENT_SAMPLE. Only insufficient sample is
automatically annotated; economic classification is **pending human review**.
No new rigid profitability gates, strategy metadata promotion or paper approval.
Future regime restrictions belong to **NEXT HYPOTHESIS**, with a separate protocol
and fresh independent validation, not Python filters added after this study's TEST.

`summary.csv` retains every source cell. `strategy_comparison.csv` uses family
medians of all neighbors per window/cost. `walk_forward_summary.csv` reports positive,
negative/zero folds out of4, PF/expectancy range/median, missing PF, insufficient
folds and the actual TRAIN-selected configuration IDs. No fixed-candidate WF claim.
`parameter_robustness.csv` compares adjacent one-coordinate TRAIN/base neighbors.
Distribution includes wins/losses, payoff, net medians/percentiles and top1/5/10%.

`outlier_dependency.csv` deletes the best/top5%/top10% (ceil(N*pct/100)) net trade
PnLs descriptively and recomputes count/net PnL/PF/expectancy. This is not a rerun,
portfolio return, rebuilt drawdown or counterfactual path. Original results unchanged.

Local reports go to `reports/eth-short-regime/<unique-report-id>/`; heavyweight
results stay in `results/<experiment-id>/<run-id>/`. Publication uses an explicit
allowlist, default5MB per file, portable provenance and exclusive destination creation:
`research_results/trend_expansion/eth_short_regime/<unique-report-id>/`.
Re-publication and tampered/mixed/incomplete sources fail. No automatic commit/push.

## Local commands

From the repository root, CMD or PowerShell, without activating the venv:

```text
.venv\Scripts\python.exe scripts/lab.py eth-short-regime validate --full
.venv\Scripts\python.exe scripts/lab.py eth-short-regime run
.venv\Scripts\python.exe scripts/lab.py eth-short-regime compare
.venv\Scripts\python.exe scripts/lab.py eth-short-regime publish latest
```

`run` executes all three new experiment IDs; ordinary `run <experiment-id>` remains
available. `compare` is an alias of `report`, uses the latest completed run of each
new experiment, rejects an incomplete latest run, and creates all comparisons without
backtesting. Explicit `--runs` accepts three concrete run IDs in ATR, hybrid, control
order. `publish latest` validates that report and emits the compact directory path.
Neither compare nor publish selects candidates or starts simulations.

Upload the nine requested CSV/Markdown files from that publication, plus
`sources.json` and `metadata.json` when provenance is needed. Never upload datasets,
equity, ledgers or hundreds of trade artifacts for a first review.

## Verification scope

FAST/FULL source validation and 66 targeted tests passed (causal/synthetic
report/publication, existing Trend Expansion and frozen RMM regressions);
Ruff checks/format passed for405 Python files. No historical challenge executed by
Codex, so no new economic
results, rejected/surviving classification, or independence claim exists yet.
