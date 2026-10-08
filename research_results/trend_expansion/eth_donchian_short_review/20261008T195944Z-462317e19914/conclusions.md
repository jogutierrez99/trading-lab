# ETH Donchian + ATR SHORT: frozen evidence review

This supplement reviews existing results, not new backtests or an independent
holdout. All six candidates are descriptively **REGIME_DEPENDENT**; statistical
decision **PROSPECTIVE_VALIDATION_REQUIRED**. No paper candidate is promoted.
The existing repository classifiers and old artifacts remain unchanged.

## Source scope and integrity

Historical report `20261008T184034Z-7804ae2eafb6`:72 completed cells, ATR run
`20261008T183830Z-e0ff782ccb9f`, hybrid run `20261008T183843Z-788bbf8b61dc`.
Historical reference commit439beec62bb8f3b41b227619a595597c350dd2b0.
Recent publication `20261007T203824Z-364120f09438`, ATR run
`20261007T203617Z-52e2dc923989`, hybrid `20261007T203647Z-194d4424b93c`;
reference commit856c8a712dc5545e131ed00ed094369f88b862d1.
Sources retain original plans/resolved parameters/costs, code hashes, environment,
run/backtest identities and record hashes. Dirty checkout provenance must not be
equated with a clean commit; missing prior exposure remains unknown.

Review checks hashes of both reports and source runs, historical frozen dependencies,
all72 historical plus24 recent TEST ledger/results/equity records. Each saved trade
is checked for effective SHORT, next-open timing, SL/2R TP, fee/slippage/spread on
both fills, net PnL, cost-aware1% stop budget and fee-inclusive25% entry capital cap.
This is saved-accounting verification, not replay of every OHLC protective fill.
Non-TEST recent metrics/diagnostics are reused from the hash-checked publication;
their individual ledgers are outside this bounded re-audit. Test fixtures verify
protective ordering, causality and prefix invariance separately.

The generic source template execution.direction=long is overridden by SHORT_ONLY
in lab_runner; saved effective metrics/trades are short. Synthetic collateralized
execution uses genuine Binance USD-M price candles, but does not model actual
perpetual funding, leverage/margin, liquidations or venue contract fills. A single
surviving asset cannot establish cross-market robustness or eliminate survivorship
bias. Stop-first intrabar ordering is conservative, exact intrabar time unknown;
gap stops fill at open and can exceed the initial stop budget.

Frozen parameters: EMA200/slope5, ATR14/reference50(mean), stop2ATR/RR2,
exit risk (exit_length10 inactive). Hybrid candidate00..02 expansion1.1,
Donchian30/40/50;03..05 expansion1.25, Donchian30/40/50. ATR candidates retain their
original expansion/impulse grid. Full twelve resolved lists appear in sources.json.
Capital resets10000 per scored annual segment. BASE fee/slippage/fullspread
0.05/0.03/0.01%, ADVERSE0.10/0.06/0.02%. All values are percentage units.

2020 starts2020-02-11T16Z after1000 warmup hours, ends2021-01-01T00Z;
2021/2022 are whole calendar years, each with its1000-hour prehistory. Ends UTC
exclusive; no annual-return sum or fictitious continuous2020–2022 curve.
FULL validation audits frozen price bytes, fingerprint, OHLC and continuous windows.

## Temporal and cost comparison

Six-configuration median net returns (%), independent annual accounts:

| Period | ATR BASE | ATR ADVERSE | Hybrid BASE | Hybrid ADVERSE |
|---|---:|---:|---:|---:|
|2020 partial|-4.14|-5.10|-1.07|-2.23|
|2021|-0.51|-1.38|5.35|0.60|
|2022|5.20|2.21|14.51|12.04|
|TEST2025-07-01→2026-09-26|5.01|2.52|4.24|3.09|

2022 is a coherent positive region, not an isolated optimum: all six positive
under both cost scenarios.2021 ADVERSE retains only3/6 economically positive
configurations, while2020 ADVERSE retains only02. Recent TRAIN is negative for
all six hybrid variants (BASE approximately-8.18..-6.80%); recent TEST is positive
for all six, with only46..68 trades per scenario. This inconsistency prevents a
persistent-edge claim. Sharpe, expectancy, DD, win rate, mean gain/loss and payoff
are copied per configuration/year/cost in summary.csv, not hidden by the medians.

## Candidate interpretation

| Candidate | Expansion / channel | Interpretation |
|---|---|---|
|00|1.1 /30|2020 BASE small gain lost to costs;2021 ADVERSE loss;2022 and recent TEST positive|
|01|1.1 /40|2020 gain lost to costs;2021 ADVERSE positive;2022 and recent TEST positive|
|02|1.1 /50|Only2020 ADVERSE positive, very small;2021 ADVERSE negative; later positive|
|03|1.25 /30|2020 loss;2021/2022 and recent TEST positive under both costs|
|04|1.25 /40|2020 loss; identical2021/2022 metrics to neighbor03/05 respectively are correlated evidence|
|05|1.25 /50|2020 loss;2021 ADVERSE approximately flat negative;2022/recent TEST positive|

Each candidate remains REGIME_DEPENDENT and requires prospective validation.
No strongest year or TEST ranking nominates a winner. Parameter edges are adjacent
in exactly one coordinate; REGION_ESTABLE means both ends positive expectancy/PF>1
for that single period/cost, never persistent validation. Sign-changing edges are
locally isolated outcomes; whole-region contradictions indicate sensitivity.
Small/undefined cells receive INSUFFICIENT_EVIDENCE. Adaptive WF winners are excluded
from fixed-region evidence and cannot supply missing neighbor cells.

## Outliers and regimes

Existing deletion diagnostics only remove saved net PnL: no reconstituted equity,
return or DD.2022 BASE median net PnL remains+677.56 after top5% removal and+51.38
after top10%; ADVERSE+463.84 after top5% but-137.09 after top10%. Recent TEST median
BASE/ADVERSE turns negative after top5% (-213.45/-310.76); removing only best
trade remains positive(+230.29/+121.53).2021 ADVERSE turns negative even without
best trade. Dependence on a right tail is plausible for trend following, but costs
and sample size leave considerable uncertainty; no automatic outlier rejection.

The unchanged causal entry regime tags place all historical and recent TEST hybrid
trade instances in bearish/high volatility. Bullish, mixed and ordinary-volatility
buckets have zero entries, hence conditional expectancy/PF is unavailable. This is
structural entry concentration, not a demonstrated market regime advantage, and
not justification for a new filter. Calendar bull years can contain local bearish
signals; annual labels and entry-time regimes answer different questions. Duplicate
trades across candidates/costs/dimensions are not independent observations.

## Independence and prospective decision criteria

The candidates were frozen after recent TEST had influenced research. Historical
2020–2022 supplies additional falsification but prior project exposure is unknown.
TRAIN/validation/TEST/year diagnostics and WF overlaps appear explicitly in
historical_evidence.csv. No overlapping cells or duplicated cost scenarios are pooled.
Local ETH1h manifests end no later than2026-09-26; they supply no newer scored period.
Manifest inventory is metadata discovery; only the pinned lab dataset receives FULL
integrity validation. Forward cache/ticker snapshots are not an independent validated
historical dataset. No data were downloaded or unobserved outcomes inspected.

Preregistration `eth_donchian_short_prospective_v1.yaml` freezes a future lower
signal-close boundary2026-10-09T00:00Z after the recorded freeze time. If implementation
starts later, actual prospective start is the FIRST eligible confirmed signal close
after successful adapter acceptance/session start; freeze that actual timestamp
before collection. Never backfill missed days into prospective evidence. Warmup may
use older candles only as context. Collection continues at least180 calendar days
and100 unique closed trades PER candidate in each cost scenario. These are minimum
coverage/precision safeguards, not proof of independence or power; never sum the six
variants or BASE/ADVERSE counts. If insufficient: INSUFFICIENT_EVIDENCE, keep collecting
without changing rules. Predeclare one assessment at the first month end at which
both minima hold for every candidate. Interim economic peeking cannot select rules.

Economic screen on NEW evidence: expectancy>0 and PF>1 in BOTH BASE and ADVERSE for
at least4/6 candidates and at least4/7 adjacent edges whose BOTH endpoints satisfy
that screen. A majority region and connected neighbors discourage an isolated peak;
not every year must pass. DD<=15% for screened candidates at the frozen1% entry
risk, a prospective loss-tolerance ceiling (15 risk units), not a historical fitted
optimum. A breach pauses collection decisions and requires incident review; it cannot
be erased by session restart, risk reduction or refreezing the same observations.

Statistical assessment additionally requires a predeclared7-day calendar-block
bootstrap of daily marked net equity changes (10000 replicates, seed271828), with
simultaneous one-sided mean-return intervals across12 candidate/cost series using
Bonferroni alpha0.05/12. Preserve synchronized blocks/cross-candidate dependence,
zero-trade days and positions spanning days. A lower bound>0 for at least the same
four economic-screen candidates under both costs is necessary. Trade expectancy
is an economic measure; daily return intervals must not be mislabeled expectancy
intervals. Block length, test multiplicity and sample uncertainty remain limitations;
manual review required. This future analysis is specified, not implemented or run.
Insufficient blocks, unexplained missing data or critical fill/accounting errors
invalidate a positive claim. Costs exceeding the frozen scenarios require a NEW
protocol, not retrospective threshold relaxation.

Descriptive labels REJECTED, REGIME_DEPENDENT,
HISTORICAL_FALSIFICATION_SURVIVOR, INSUFFICIENT_EVIDENCE and
PROSPECTIVE_VALIDATION_REQUIRED do not replace repository gates. No statistical
screen approves operations; no operational acceptance establishes profitability.
All positive research decisions remain manual and grant no paper/live eligibility.

Continue research: yes. Independent persistent edge established: no. Donchian forward
adapter accepted: no. Portfolio diversification measured: no. See forward_readiness.md
and portfolio_compatibility.md for the required separate work.
