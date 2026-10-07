# ETH SHORT regime challenge: compact publication

Implementation only; economic results and human classification pending local execution.
See [frozen protocol](../../../docs/eth-short-regime-challenge-v1.md).

This study is exploratory regime analysis based on hypotheses generated after observing
previous TEST results. It is not an independent holdout and does not constitute
paper-trading approval.

`lab.py eth-short-regime compare` audits three ETH SHORT ordinary lab runs;
`lab.py eth-short-regime publish latest` creates an immutable uniquely named directory.
Allowlist: summary.csv, strategy_comparison.csv, regime_comparison.csv,
walk_forward_summary.csv, base_adverse_comparison.csv, parameter_robustness.csv,
trade_distribution.csv, outlier_dependency.csv, conclusions.md, sources.json,
plus publication metadata.json. Max5MB per file by default.

Datasets, equity, ledgers and original heavy artifacts remain local. No automatic
profitability labels, parameter reselection, forward/OKX integration or paper approval.
