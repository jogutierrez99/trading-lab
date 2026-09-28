# OPTIONAL_15M_FILL — causal deadline-market protocol 1

Implementation scope: execution experiment, not new strategy versions. The user
explicitly selected the causal alternative after resolving a contradiction in
the initial request: one cannot observe 60 future minutes and then restore an
unfilled historical entry price/time. **Fallback is an actual market entry at
the decision time, possibly worse than baseline. Trade count is not guaranteed.**
No retrospective baseline substitution, minimum-of-next-hour search, new signal
generation, strategy filter, parameter search, downloads or live routing.

## Six frozen configurations and sources

All LONG_ONLY, on the same matched perpetual cohort:

| Asset | Family | Architecture | Baseline source |
|---|---|---|---|
| ETHUSDT | ema_adx | V2 | MTF03 matched LONG_ONLY |
| ETHUSDT | roc_momentum | V2 | New MTF phase A |
| ETHUSDT | supertrend_pullback | V2 | New MTF phase A |
| ETHUSDT | keltner_breakout | V2 | New MTF phase A |
| BTCUSDT | supertrend_pullback | V2 | New MTF phase A |
| ETHUSDT | trend_pullback | V1 | MTF03 matched LONG_ONLY |

Exact source paths, manifest SHA256 and matrix live in
`configs/profiles/optional_15m_fill.yaml`. Profiles are appropriate for dedicated
perpetual/MTF runners; the ordinary `configs/experiments` schema is not compatible.
Original strategies, parameters, higher-timeframe availability, data and risk
settings are unchanged. V1 never receives a new 4h regime.

## Causal opportunity and mapping

Run the original strategy/engine as a shadow baseline. Only its accepted entry
events are eligible for the policy. Although the historical baseline is computed
first, the policy receives a strict whitelist: entry/signal time, entry price,
ATR14, original stop distance and frozen structure/retest levels. No exit time,
future PnL, terminal equity or future trade outcome enters the decision API.
An entry event becomes available exactly at its original executable open T.
Baseline eligibility at T depends on the original strategy, prior position,
past fills and current open, all known at T. Entries not accepted by that causal
shadow baseline cannot be invented when the experimental account becomes flat.

The original `baseline_trade_id` is deterministic within asset/family/architecture,
window, scenario and original entry timestamp. `signal_id` is stable across windows
and scenarios, which are additional required pairing keys. Every baseline entry
gets a row in `trade_pairs.csv`, including entries the experimental engine cannot
execute. Only one accepted experimental fill is allowed per baseline trade ID.
Both baseline and experimental trades are linked in `trades.csv`.

## Fixed policy rules

Window is exactly four subsequent 15m closes: T+15, T+30, T+45, T+60 minutes.
Features indexed at T describe only the quarter that **closed** at T. A trigger
enters at the next executable open, with inherited adverse spread/slippage.
Only the first qualifying chronological fill is accepted; later prices cannot
revise the decision. The executable open must also remain above the frozen
structure level; a gap below it cannot masquerade as an optimized entry.
A proposed optimized LONG fill must strictly improve the baseline **after**
the current scenario's spread/slippage. Equality is not an
optimized fill. Commissions still affect sizing and account PnL normally.

The following frozen rules only decide whether to optimize before fallback:

| Family | Single fixed optimization rule |
|---|---|
| EMA_ADX V2 | A post-signal quarter touches EMA20 15m and closes bullish; its close remains above the frozen original hourly EMA50. No new ADX/EMA regime evaluation. |
| TREND_PULLBACK V1 | Same micro-pullback fill test, using its own frozen hourly EMA50; no 4h context added. |
| SUPERTREND_PULLBACK V2 | A post-signal quarter touches EMA20 15m, then a later quarter closes above the prior quarter high and its own open. Both optimization observations must preserve the original frozen hourly ST line. |
| KELTNER_BREAKOUT V2 | A post-signal quarter retests the frozen original hourly upper Keltner channel and closes back above it, while above the original middle channel. |
| ROC_MOMENTUM V2 | Three post-signal quarters consolidate with high-low range <=2 ATR14 15m available at the third close; the fourth closes above their high and its own open, above the frozen original breakout level. Thus this formulation can optimize at +60 minutes. |

No strategy/regime/momentum recalculation can cancel the pending order. Losing
compatibility merely prevents an optimized fill: fallback still attempts entry.
At T+60, first test the valid optimized fill; otherwise submit a market fallback
at that open, even if its price is worse or the original structure is lost.
The old expiry/invalidation-to-no-trade policy is not reused.

At a predeclared window/continuous-segment end, shorten the deadline to its last
executable open and label `segment_or_window_boundary`. These boundaries come
from the frozen study calendar/cohort, never from future price extrema. If a
gap appears unexpectedly, label the non-execution; never fill a missing bar.

Pending signals are ordered oldest first. A position already open prevents a
new fill under the inherited one-position engine; waiting continues until the
deadline, then `position_capacity_at_deadline` explains the missing trade. An
engine sizing rejection can be retried at later opens through the deadline;
afterward `engine_risk_rejection` and actual rejection reasons are recorded.
No size/exposure override or simultaneous position is introduced to fabricate
100% retention. Every failure remains visible; none is a strategy rejection.

## Inherited execution and comparisons

10000 USDT independent capital per case/window/scenario, stop-risk 0.5%, maximum
entry exposure 25%, ATR14 hourly *2 initial stop distance, no target, maximum
holding 72 elapsed hours. The frozen signal ATR determines stop distance; account
equity, quantity, stop price and exposure are recomputed by the unchanged engine
at actual fill time. Funding, fees, spread, slippage, lot filters, mark and isolated
1x margin assumptions are inherited. ZERO disables costs and funding as before.

Baseline retains hourly execution. Experimental execution uses contract/mark
15m bars, so stops/liquidations and funding participation can change independently
of entry price. Do not interpret all PnL differences as entry improvement.

Same FULL, train/validation/test/final_holdout, 22 WF test folds, 29 segments,
18 excluded days, matched fingerprints and three costs ZERO/BASE/ADVERSE:
**56 windows * 6 cases * 3 costs * 2 variants = 2016 executions** when all pairs pass.
All 1008 baseline executions precede experimental executions. Each pair must
reproduce all of its 168 baseline windows/scenarios before its variant is allowed.
Metrics, every trade, rejections, funding events and equity/exposure/side series
are compared to the selected immutable historical result; rtol=1e-9, atol=1e-8.
Any mismatch records `BASELINE_REPRODUCTION_FAILED`, aborts that pair and prevents
its optimization. Other pairs can continue. Such runs exit with code 1 and
`completed_with_failed_pairs`, not a clean success. Execution invariant errors
also abort the affected pair and produce FILL_WORSE with an explicit reason.
Each child ledger unlocks holdout only after its pre-holdout matrix is complete.

## Metrics and fixed classification

Keep all requested strategic and temporal metrics and both actual fill prices.
Signed improvement for LONG = baseline_price - experimental_price; percent =
100 * difference / baseline_price; ATR improvement = difference / original ATR.
Wait measures actual entry delay, not the time at which a historical entry is
retrospectively selected. Means/medians include optimized **and fallback** fills;
unexecuted entries are missing observations, never zero-price/zero-wait samples.

`number_of_worse_fills` includes ALL worse fills, including fallback losses.
`number_of_worse_optimized_fills` must be zero (equality also violates strict
optimization); `number_of_worse_fallback_fills` explicitly records the cost of
the causal alternative selected by the user. A worse fallback is not a causal
error. It prevents FILL_IMPROVED under the original no-worse-fill criterion, but
does not alone force FILL_WORSE; aggregate deterioration rules still apply.

Retention = executed baseline-linked trades / baseline trades. Warn below 98%.
Below 95% requires explicit non-execution explanations and is FILL_WORSE. Reasons
are required for **every** missing trade, not just below a threshold. Zero baseline
trades give undefined retention, never fictitious 100% retention.

Precedence: any WORSE condition, then all IMPROVED conditions, otherwise NEUTRAL.
No score or post-result adjustment. Ambiguous "material" terms are fixed now:

* Full BASE expectancy/PF material loss: >5% of absolute baseline value, allowing
  1e-8 numerical tolerance. Full BASE return material loss: >2 percentage points.
* Holdout clear deterioration: return loss >2 points OR expectancy loss >5% of
  absolute baseline expectancy (plus 1e-8 tolerance).
* Costs not materially worse: <= baseline + max(1 USDT, 1% absolute baseline costs).
* DD numerical tolerance: 1e-8 percentage points.
* IMPROVED also requires retention >=98%, zero worse fills including fallback,
  expectancy/PF/return >= baseline, DD within tolerance, holdout expectancy within
  the material tolerance, positive folds drop <=1, ADVERSE return loss <=2 points.
  At least a strictly positive mean fill improvement or return increase above
  1e-8 is required; an identical result with no measured benefit is NEUTRAL.
* WORSE also includes retention <95%, any invalid optimized replacement,
  positive folds drop >2, ADVERSE return loss >5 points, baseline reproduction
  failures or execution/causality invariant errors. Known failures remain failures
  even if other metrics are undefined. Undefined metrics cannot satisfy IMPROVED.

Only CONTINUE_FILL_RESEARCH, NO_MEANINGFUL_IMPROVEMENT and ARCHIVE_FILL_VARIANT
are emitted. Reused holdout is exploratory; overlapping windows are not independent.

## Local commands and artifacts

From the repository root, same Python/environment for both commands:

```powershell
python scripts/preflight_optional_15m_fill.py
python scripts/run_optional_15m_fill.py
```

Both accept `--config configs/profiles/optional_15m_fill.yaml`. Preflight runs
pytest -q, Ruff lint/format and pip check; validates strict config, pinned source
manifests, datasets, funding, 15m coverage/cohort, original code and all 1008
reference identities. **It does not run historical backtests.** The runner performs
the numerical historical reproductions locally. `--technical-only` skips dataset
verification and cannot authorize the runner. Source/runtime/config changes after
preflight invalidate its immutable receipt. No automatic dependency installation.

Targeted tests:

```powershell
python -m pytest -q tests/unit/test_optional_15m_fill.py tests/integration/test_optional_fill_runner.py
```

Receipts: `reports/optional_15m_fill/preflight/<timestamp-id>.json`.
Results: `results/optional_15m_fill/<run_id>/`, exclusively created:

config.json, plan.json, baseline_reproduction.csv, results.csv, metrics.csv,
paired_comparison.csv, trade_pairs.csv, fill_metrics.csv, trades.csv,
fold_metrics.csv, segment_metrics.csv, holdout.csv, cost_sensitivity.csv,
fill_classification.csv, summary.md, ai_summary.md, verification.json,
artifact_manifest.json, source_snapshot/ and per-pair baseline/optimized ledgers.
Reports are deterministic local templates, with no model/API calls. A failed
global run preserves failure.json and all partial evidence. No historical results
are rewritten; there is no implicit resume or deletion.

## Implementation inventory

New: `execution_policies/optional_15m_fill.py`, `optional_fill_execution.py`,
`optional_fill_protocol.py`, `optional_fill_runner.py`, `optional_fill_preflight.py`,
`optional_fill_reporting.py` under src/quant_lab; two scripts above; dedicated YAML,
this protocol, unit and integration tests. Existing PROJECT_STATE gains a capability
entry; engines, strategies, old runners/configs/datasets/results remain untouched.
