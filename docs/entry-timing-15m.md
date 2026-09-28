# Entry timing 15m: frozen protocol 1

This is an execution experiment, not three new strategies. Only ETHUSDT
Supertrend Pullback V2, ROC Momentum V2 and ROC Momentum V1 are admitted.
The original hourly strategy registry supplies opportunities without any change.
V2 uses its original last fully closed 4h regime; V1 has no 4h regime.
No optimization, downloads, paper trading or live orders are implemented.

## Frozen timing definitions

Each original long signal creates a frozen Opportunity. Its UTC close time is
also the original next-open baseline entry time. Its close price, ATR14 hourly,
structure level, direction and original regime/setup state never change.
Mutable execution status lives in a separate audit record. One signal produces
at most one trade. IDs are shared across variants; pairing additionally requires
the same window and cost scenario. Actual baseline fills alone define price
improvement: 100 * (baseline fill - timing fill) / baseline fill.
Unmatched opportunities are retained and never assigned fictitious fills.

* Expiry: exactly four subsequent closed 15m bars. A trigger on the fourth close
  can enter at its next open (60 minutes). Otherwise EXPIRED at that boundary.
* Extension: absolute distance of latest closed price OR current executable open
  from original close must be <= 1.5 original ATR. This guard is applied even
  without a trigger. Reported fill distance includes inherited slippage/spread.
* Supertrend: first a **post-signal** quarter touches EMA20 or bullish Supertrend
  (ATR10 Wilder, multiplier 3). A **later** closed quarter must close above the
  previous quarter high and above its own open. A touch and recovery in the same
  candle cannot enter. Original hourly bullish ST structure must remain valid;
  the last quarter close must stay above the frozen hourly ST line.
* ROC: previous **three post-signal** quarter candles must have total high-low
  range <= 2 times ATR14 15m available at the third close. The fourth closed
  candle must close above that three-bar high and its own open. Thus this single
  formulation can enter only at +60min. No pre-signal consolidation substitutes
  for waiting. Original hourly ROC20 > 0 and ROC5 > ROC20 must still hold; quarter
  close must remain above the original frozen 20-hour breakout level.
* Any applicable original 4h regime invalidation cancels the opportunity.
  Monitoring newer fully closed hourly structure does not mutate the snapshot
  or create a new opportunity. No future bar is used.
* Signals arriving with a position already open are recorded as INVALIDATED.
  An older pending signal has priority at shared hour boundaries. If it enters,
  the new signal is INVALIDATED. Engine sizing rejection cancels the attempted
  signal; it is never retried. No extra cooldown is introduced.
* Missing quarters inside a matched segment are an explicit data error; actual
  existing excluded segments reset indicators and policies. Pending signals
  become INVALIDATED at gaps/window ends. No signals from preceding windows
  carry into the new window. Warmup uses earlier causal observations in the same
  continuous segment, exactly as baseline.

Transitions: CREATED -> WAITING -> ENTERED -> CONSUMED; or EXPIRED / INVALIDATED.
Both entry transitions are recorded; CONSUMED means the opportunity cannot be
reused, not that its position has already closed.

## Inherited execution and temporal protocol

The existing perpetual engine and clock adapter remain untouched. Capital 10000
USDT independently per case/window/cost, 0.5% planned risk, 25% entry exposure,
2 * original hourly ATR14 stop and 72 elapsed hours maximum holding. Costs,
lot filters, margin assumptions and actual funding timestamps are inherited.
ZERO disables costs **and funding** as in the historical reference; BASE and
ADVERSE retain actual funding. No exit signal changes are introduced.

Baseline executes on original hourly bars; timing uses 15m contract and mark
bars, with the same protective-order model and conservative ordering. Quarter
resolution may change exit ordering/stop time as well as entry price. The
experiment must not attribute every PnL difference solely to entry timing.

Keep original train/validation/test/final_holdout, FULL, 22 walk-forward test
folds and 29 continuous segments. Same matched data, funding and 18 exclusions.
56 windows * 3 scenarios * 3 cases * 2 variants = **1008 executions**.
All 504 baselines run and reproduce before any of the 504 timing executions.
Each variant has its own ledger and pre-holdout completion unlock. No strategy
is selected or rejected using RESEARCH_PASS. Prior holdout observations informed
the user's selection, so holdout is diagnostic, not pristine new evidence.

## Reproduction, provenance and failure handling

Config: `configs/profiles/entry_timing_15m.yaml`. This is a dedicated research
profile; `configs/experiments/` is reserved for the ordinary lab's strict schema.
The source phase A and SHA256 of its artifact manifest are explicitly pinned.
All previous manifest files are checked read-only. Original strategy, indicator,
execution, risk and configuration hashes must match the source snapshot.
Data identities, funding audits, exclusions and scheduled windows must match.

Every baseline compares metrics, trades, rejections, funding events and full
equity/exposure/side series with the corresponding historical execution.
Float tolerance rtol=1e-9, atol=1e-8; IDs/order/timestamps/counts must match.
Parquet serialization bytes are not used for numerical equivalence.
Any mismatch aborts explicitly before timing. Failed runs retain their ledger,
artifacts and failure.json; they are never overwritten or resumed silently.
Source snapshots, code/runtime fingerprints, per-child integrity verification
and a final recursively hashed artifact manifest are retained.

## Fixed classification, defined before results

No score. WORSE takes precedence, then all nine IMPROVED conditions; otherwise
MIXED. Full BASE expectancy must improve, PF must not decrease, drawdown must
not increase, total costs must not increase, and >=50 trades are required.
Return must be >= baseline - 0.10 * abs(baseline): 20% implies a floor of 18%.
Holdout BASE expectancy cannot decrease; full ADVERSE return can decrease by
at most 5 percentage points; positive BASE folds can decrease by at most 2.

WORSE: positive expectancy becomes <=0, PF<1, full BASE return<=0, <30 trades,
positive folds drop >4, or any following material deterioration:

* Extremely low execution rate: <10%, without both improved expectancy and
  nondecreasing PF.
* Material holdout deterioration: return falls >5 percentage points OR
  expectancy falls >20% of the absolute baseline expectancy.
* Material full ADVERSE deterioration: return falls >10 percentage points.

These numeric interpretations resolve terms left open in the request and are
frozen in code/plan before any timing results. Undefined metrics never qualify
as improved evidence; known worse conditions still apply. Trade retention <30%
is flagged explicitly. Ratios are fractions; return/cost parameters ending in
`_pct` remain percentage units. Only CONTINUE_RESEARCH, NEED_MORE_DATA or
ARCHIVE_TIMING_VARIANT are emitted. Overlapping windows are not independent
observations and their profits/trades must not be pooled.

## Local commands and outputs

From the repository root, using the same Python/environment for both commands:

```powershell
python scripts/preflight_entry_timing_15m.py
python scripts/run_entry_timing_15m.py
```

Preflight runs pytest, Ruff lint/format, pip check; then verifies data/artifacts
and reproduces three FULL/BASE historical cases. This is **three replays only**,
not the full research batch. Any change to code/config/tests or dependencies
requires a new preflight. `--config PATH` is supported by both scripts.
`--technical-only` runs just software checks and cannot authorize the runner.

Receipts: `reports/entry_timing_15m/preflight/<timestamp-id>.json`.
Results: `results/entry_timing_15m/<run_id>/` with config.json, plan.json,
results.csv, metrics.csv, paired_comparison.csv, trades.csv, signals.csv,
signal_lifecycle.csv, segment_metrics.csv, fold_metrics.csv, holdout.csv,
cost_sensitivity.csv, timing_metrics.csv, timing_classification.csv,
baseline_reproduction.json, summary.md, ai_summary.md, verification.json,
artifact_manifest.json, source_snapshot/ and independent baseline/timing stores.
The AI summary is generated solely by local rules/templates, without model calls.

Implementation validation uses synthetic unit/integration tests and technical
checks. Historical experiment execution is left to the user.
