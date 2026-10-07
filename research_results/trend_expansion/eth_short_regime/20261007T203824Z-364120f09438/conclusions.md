# ETH SHORT regime challenge V1

## Scope

ETHUSDT 1h SHORT_ONLY; two hypotheses and one control. Synthetic USD-M prices; no funding, borrowing or liquidations.

## Previous evidence

User-reported previous ETH SHORT TEST evidence; motivation only, not independently re-audited by this study.

## Methodological warning

This study is exploratory regime analysis based on hypotheses generated after observing previous TEST results. It is not an independent holdout and does not constitute paper-trading approval.

## Strategies

### ATR Volatility Breakout

Main hypothesis; impulse 0.75/1/1.25 ATR, expansion 1.1/1.25.

### Donchian + ATR

Main hypothesis; Donchian 30/40/50, expansion 1.1/1.25.

### Donchian control

Control only; Donchian 30/40/50. EMA200 slope filter and ATR14 x2 / RR2 unchanged for all families.

## Temporal Stability

Original TRAIN/VALIDATION/TEST unchanged. diagnostic_year_2023 through diagnostic_year_2026 are separate annual reruns, 2023/2026 partial. Capital resets; these overlap main/WF windows and must not be pooled. Annual evidence includes prior unselected history; it is exploratory.

## Walk Forward

Four original folds; selection uses TRAIN Sharpe/base only. Adaptive policy evidence, never assigned to each fixed candidate.

- atr adverse: positive 2/4, negative 2/4; median PF 1.082; median expectancy 4.185; insufficient folds 3.
- atr base: positive 4/4, negative 0/4; median PF 1.151; median expectancy 7.323; insufficient folds 3.
- donchian adverse: positive 3/4, negative 1/4; median PF 1.118; median expectancy 5.422; insufficient folds 1.
- donchian base: positive 3/4, negative 1/4; median PF 1.191; median expectancy 8.476; insufficient folds 1.
- donchian_atr adverse: positive 3/4, negative 1/4; median PF 1.34; median expectancy 14.24; insufficient folds 2.
- donchian_atr base: positive 3/4, negative 1/4; median PF 1.439; median expectancy 17.55; insufficient folds 2.

## BASE vs ADVERSE

Actual matched reruns; BASE fee/slippage/spread 0.05/0.03/0.01%, ADVERSE 0.10/0.06/0.02%. Fees both sides and half-spread each fill. Sizing/trades may change. Read base_adverse_comparison.csv.

## Regime Analysis

### Trend direction

Bearish: close below EMA200 AND EMA200[t]-EMA200[t-5]<0. Bullish: both opposite; otherwise mixed.

### Volatility

ATR14[t] divided by mean ATR14[t-50:t-1]; high >=1.1, ordinary <1.1. Undefined warmup is unavailable.

### Combined

Cross of trend and volatility; explicit empty buckets. Labels sampled at signal close with the same period warmup as execution, reset at gaps. No regime filters added. Every bucket has count, PF, expectancy, sample status and trade/net PnL shares. No pooled candidate evidence or return/DD from bucket PnL.

## Parameter robustness

All original neighbors retained; parameter_robustness.csv compares adjacent one-coordinate TRAIN/base pairs. No TEST ranking or parameter reselection; summary retains every fixed candidate main/annual cell.

## Trade distribution

Per-cell wins/losses/breakevens, win rate, payoff, mean/median winners and losers, net median and percentiles, top ceil(N*pct/100) at 1/5/10%. Net shares undefined for non-positive total, may exceed 100%. Read trade_distribution.csv.

## Outlier dependency

Complete and deletion of best/top5%/top10% net trades: count, net PnL, expectancy and PF. Descriptive deletion only; costs already netted, no execution rerun, return or DD. Read outlier_dependency.csv.

## Findings

Descriptive TEST family medians (all neighbors, no winner selection):

- atr adverse: 6 configurations; median return 2.518%; expectancy 3.994; PF 1.095; trades 64.
- atr base: 6 configurations; median return 5.006%; expectancy 7.486; PF 1.184; trades 64.
- donchian adverse: 3 configurations; median return -2.371%; expectancy -2.027; PF 0.9472; trades 110.
- donchian base: 3 configurations; median return 0.94%; expectancy 0.7966; PF 1.021; trades 111.
- donchian_atr adverse: 6 configurations; median return 3.091%; expectancy 5.934; PF 1.14; trades 56.5.
- donchian_atr base: 6 configurations; median return 4.244%; expectancy 7.846; PF 1.19; trades 57.5.

5600/6726 regime cells have insufficient samples. 914 deletion cells have non-positive remaining net PnL. These overlapping descriptive counts are not independent tests. Review hybrid vs control and ATR vs hybrid within the same period/scenario and neighboring regions; inspect negative periods without ranking TEST.

## Rejected hypotheses

PENDING HUMAN REVIEW. Labels: REJECTED, REGIME_DEPENDENT, ROBUST_RESEARCH_SURVIVOR, INSUFFICIENT_SAMPLE. Fewer than 20 trades marks insufficient descriptive sample, never a profitability gate. No automatic economic classification.

## Surviving hypotheses

PENDING HUMAN REVIEW. REGIME_DEPENDENT requires documented concentration with sufficient bucket samples; ROBUST_RESEARCH_SURVIVOR requires explicit joint review of periods, costs, neighbors and outliers. Neither grants paper/live eligibility. No new numeric approval gates.

## Limitations

Post-selection and multiple comparisons; reused TEST, dependent candidates/overlapping periods, limited samples, no confidence inference or portfolio. Shared EMA slope short entry rule can structurally concentrate trades in bearish labels, and ATR entry thresholds in high ATR labels: concentration alone is not proof of conditional edge. Conditional trade PnL lacks opportunity/exposure controls. Calendar boundaries force liquidation. OHLC ambiguity and conservative stop-first ordering unchanged. Undefined PF with no losses is missing, not infinity or failure. No independent holdout or future profits inferred.

## Next falsification experiment

NEXT HYPOTHESIS ONLY: after human review, predeclare any bearish/high-volatility restriction and a fresh independent temporal protocol before observing new results. Do not implement filters, retune on this TEST or incorporate into forward/OKX/paper.
