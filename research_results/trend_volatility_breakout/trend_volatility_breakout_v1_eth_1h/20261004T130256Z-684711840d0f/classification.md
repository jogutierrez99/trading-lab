# Research classification: trend_volatility_breakout_v1_eth_1h

Run: 20261004T130256Z-684711840d0f

Retrospective diagnostic; recorded dataset/warmup provenance checked, no new dataset/equity/trade audit. No proof of independent unobserved holdout. PAPER_TRADING_CANDIDATE is a protocol label, never order/forward authorization.

Legacy PASS is only the old filter result; it is not a research or paper gate.
Research gate reads TRAIN/VALIDATION only. TEST never ranks candidates.
fixed_candidate_robustness requires all prescribed WF TESTs for that same candidate.
walk_forward_selection reports adaptive winners separately; their evidence is not pooled into each candidate.
OOS trades count BASE disjoint WF TESTs + TEST, and VALIDATION only if nonoverlapping.
Medians across independently reset folds are descriptive, not compounded returns.

## Mutually exclusive highest classification

```json
{
  "FAIL": 0,
  "VALID": 431,
  "RESEARCH_PASS": 1,
  "OOS_PASS": 0,
  "ROBUST_PASS": 0,
  "PAPER_TRADING_CANDIDATE": 0
}
```

Per-candidate gates, per-fold technical validity, return/expectancy flags and failure reasons: classification.json.
Historical results do not establish future profitability.
