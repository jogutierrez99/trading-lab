# ETH SHORT historical falsification V1

Study ID `eth_short_historical_falsification_v1`. Two frozen hypotheses only:
`atr_volatility_breakout` and `donchian_atr_breakout`, ETHUSDT1h SHORT_ONLY.
No pure Donchian candidate, ranking, optimization, signal/exit/risk/cost change,
new indicator/regime filter, forward/OKX/paper/Telegram modification.

> This historical challenge is a falsification study of frozen hypotheses. It does
> not constitute paper or live trading approval and does not establish future
> profitability.

## Source and hypothesis freeze

Read all eleven compact artifacts from
`research_results/trend_expansion/eth_short_regime/20261007T203824Z-364120f09438/`:
eight CSV, conclusions, metadata and sources. Published artifact hashes verified.
Their original conclusions are unchanged and still mark economic classifications
pending human review. The user's nomination motivates this challenge; it does not
retroactively assign an economic verdict to that publication.

Descriptive prior TEST medians match the supplied motivation: ATR BASE return5.0056%,
PF1.1841 / ADVERSE2.5175%, PF1.0947; hybrid BASE4.2438%, PF1.1904 /
ADVERSE3.0913%, PF1.1403. This is already-observed reference evidence, not new evidence.
Its adaptive WF evidence is not assigned to each fixed candidate. No historical
heavy trade/equity re-audit of the previous runs was performed during implementation.

The new configs copy the **complete actual resolved parameter lists** from sources,
not approximate prompt values and not the best TEST configuration. Existing enabled
strategy profiles, capital, execution, market, costs and sizing remain the same.
Validation compares prepared candidates/template/app/market/cost/execution to that
specific published source. New protocol hashes freeze configs, prior artifacts and
existing signal/features/report dependencies; runs record the new protocol YAML
hash in provenance. Changed sources/definitions fail instead of being accepted.

| Parameter | ATR | Donchian+ATR |
|---|---|---|
| expansion threshold | 1.1,1.25 | 1.1,1.25 |
| impulse multiplier | 0.75,1,1.25 | absent |
| Donchian length | absent | 30,40,50 |
| EMA / slope | 200 / 5 | 200 / 5 |
| trend filter | ema_slope | inherited frozen EMA/slope rule |
| fast_length | 50; inactive with ema_slope | absent |
| ATR length / reference | 14 / 50, mean | 14 / 50, arithmetic mean |
| stop / RR | 2ATR / 2 | 2ATR / 2 |
| exit method / exit_length | risk / 10 (inactive) | risk / 10 (inactive) |

Both version1.0.0, risk_per_trade1%, max_position25%, max_exposure100%, stop-risk
sizing, stop and target enabled, no trailing/time stop. Initial cash10000. Quantity
step/min_quantity0.000001, min_notional10, liquidate_at_end true. Profile marketBTC
is the stored template default; the explicit challenge market overrides it to ETH,
as in the original run. No BTC backtest is executed.

BASE fee/slippage/full spread0.05/0.03/0.01%; ADVERSE0.10/0.06/0.02%.
Percentage units, fees on both sides, half-spread each fill. ADVERSE is an actual
rerun and can change trades/sizing; never a retrospective flat PnL subtraction.

## Historical periods fixed before execution

Local bundle:
`data/lab_1h_prices/ETHUSDT/1006e4cb8296ab8d1574317f2927c7feb975bbd25a5f195a8c7d97a17d7b70e4/`.
Manifest declares59040 continuous rows, 2020-01-01→2026-09-26, no missing bars.
Fingerprint `1006e4cb8296ab8d1574317f2927c7feb975bbd25a5f195a8c7d97a17d7b70e4`;
Parquet SHA256 `45d54f213f24b4282a4a5ac972431aafb8d303456e4c202b548ec0e9196fb8ec`.
FULL verifies bytes/fingerprint/OHLCV and each window/warmup; FAST verifies manifests.
No downloads, substitutions or invented data.

All timestamps UTC; ends exclusive, covering December31 completely:

| Challenge | Scored start | Exclusive end |
|---|---|---|
| 2020 partial | 2020-02-11 16:00 | 2021-01-01 00:00 |
| 2021 | 2021-01-01 00:00 | 2022-01-01 00:00 |
| 2022 | 2022-01-01 00:00 | 2023-01-01 00:00 |

Original requested start2020-01-01 00:00 plus exactly1000 hourly warmup bars gives
2020-02-11 16:00, the minimum permitted start. The first1000 hours are context only;
2021/2022 each use the previous1000 existing hours. Dates are not chosen from outcomes.
Each scored annual account resets cash and forces liquidation at the endpoint;
warmup does not open positions. Gaps in any scored/warmup interval fail validation.

Two strict profiles under `configs/challenges/`, each six explicit candidates,
three named HISTORICAL_CHALLENGE segments and two scenarios =36 backtests per family,
**72 total**, for local user execution. Reuses `lab_challenge.prepare_challenge` /
`run_challenge`, `lab_runner.evaluate`, StudyBackend and ExperimentStore unchanged.
No fake TRAIN/VALIDATION/TEST, Cartesian optimization, leaderboard or WF winner.

Optional continuous aggregate omitted to keep this protocol as three natural annual
challenges. Annual results are not compounded/summed as continuous return/DD.
The conclusions include Aggregate2020-2022 explicitly as not executed. Recent2025-2026
is shown only from the pinned existing publication, with no rerun or pooled evidence.

Earlier history lies outside the principal recent selection window, but the hypotheses
were chosen after observing later results, and older history may have been observed
elsewhere in this laboratory. It is additional falsification, not independent future
holdout or proof of unobserved historical independence. Conceptual overlap is explicit.

## Descriptive reporting

Per configuration/year/scenario: return/CAGR, PF, expectancy, daily UTC Sharpe/Sortino,
DD, wins/losses, win rate, means/medians/payoff, closed trades, full modelled costs,
average close exposure and separate long/short PnL contributions. Short-only long
contribution is0; undefined metrics remain blank rather than fabricated zeros/infinity.

Whole-region scorecard: positive config count/percentage, PF>1/expectancy>0 percentages,
medians/IQR, worst/best return extrema and sample flags. Percentages always divide by
all six configurations; undefined PF/expectancy counts are explicit. Best/worst returns
are descriptive, never nominated winners. No arbitrary combined score.

`strategy_comparison.csv` matches ATR vs hybrid whole-region medians by year/scenario
and reports hybrid-minus-ATR differences. `year_comparison.csv` shows each full region.
`parameter_robustness.csv` compares adjacent one-coordinate neighbors in every
year/cost separately. No pooled candidate or portfolio interpretation.

BASE→ADVERSE pairs retain both backtest IDs and return/PF/expectancy/Sharpe deltas.
`edge_disappears_adverse` flags a BASE-positive return/PF>1/expectancy conjunction
lost under ADVERSE; missing metrics make it unknown. A descriptive flag, not a new gate.

Unchanged distribution and outlier methods: top ceil(N*pct/100)1/5/10% net PnL,
net shares unknown for non-positive total, descriptive best/top5/top10 removal with
remaining count/PnL/PF/expectancy. No resimulation or rebuilt return/DD. Low win rate,
small losses, right-tail winners and negative years do not automatically reject trend
systems; jointly review tail gains against losses and costs across neighbors/years.

Regime diagnostics reuse exactly `eth_short_regimes.py`, previous EMA200 price/slope5
and ATR14 divided by previous50 mean, high>=1.1, with the same unavailable buckets.
Features use each execution warmup and reset at gaps. Tag at signal_close-1h because
candle index is OPEN; decisions are causal at close, earliest fill next open.
No filter or new bucket. Existing entry rules structurally concentrate some regimes;
conditional PnL has no opportunity/exposure matched-control inference.

Final economic classification remains manual: REJECTED, REGIME_DEPENDENT,
HISTORICAL_FALSIFICATION_SURVIVOR, INSUFFICIENT_SAMPLE. Fewer than20 trades is a
descriptive annotation, not statistical significance. Review expectancy, PF, costs,
stability, count, neighbors, outliers and years together; not every year must profit.
No strategy metadata or forward/paper eligibility promotion.

## Storage and CLI

Heavy runs: `results/<challenge-id>/<unique-run-id>/`, immutable ledger/result/equity
with original/resolved configs, dataset/code/environment identity and backtest IDs.
Local audited reports: `reports/eth-short-history/<unique-report-id>/`.
Compact immutable publication:
`research_results/trend_expansion/eth_short_historical_falsification/<unique-report-id>/`.
Explicit allowlist, default5MB per file, portable sources and publication metadata.
Sources/ledger/equity/data/protocol hashes are checked; duplicate/tampered/incomplete/
mixed code or costs fail. No automatic commit/push, full ledgers or datasets exported.

From the repository root, CMD or PowerShell:

```text
.venv\Scripts\python.exe scripts/lab.py eth-short-history validate --full
.venv\Scripts\python.exe scripts/lab.py eth-short-history run eth_short_historical_falsification_v1_atr
.venv\Scripts\python.exe scripts/lab.py eth-short-history run eth_short_historical_falsification_v1_donchian_atr
.venv\Scripts\python.exe scripts/lab.py eth-short-history compare
.venv\Scripts\python.exe scripts/lab.py eth-short-history publish latest
```

The two run commands explicitly perform heavy history, after full preflight. Compare
uses the latest complete requested challenge runs, rejects a latest incomplete run,
and never simulates or selects winners. Optional `--runs` pins two real run IDs in
ATR/hybrid order. Publish validates that report and prints publication_directory.

Exact compact files: summary.csv, year_comparison.csv, strategy_comparison.csv,
base_adverse_comparison.csv, parameter_robustness.csv, trade_distribution.csv,
outlier_dependency.csv, regime_comparison.csv, falsification_scorecard.csv,
conclusions.md, sources.json, metadata.json. Upload these for economic review.

## Implementation verification

FAST/FULL valid for both profiles, including2020 warmup;50 targeted tests passed:
synthetic workflow, freeze/cost/denominator/adjacency, existing causal/runner and
frozen RMM regressions. Ruff/check and format passed for410 Python files; diff check
passed. The previous Regime Challenge FAST validation also remains valid.
No historical challenge executed by Codex. Historical economic verdicts remain
pending local runs and manual interpretation; no profitability inferred from tests.
