# Lab CLI architecture audit (2026-09-27)

The local checkout is authoritative, including work after the public repository's
foundation commits. Inspected configuration, strategy discovery and scaffolding,
historical/cache validation, reference and study execution, persistence, metrics,
batch/cross-market/MTF/refinement entry points, representative strategies and tests.
No historical research was executed for this audit.

## Reuse decisions

| Existing component | Decision |
|---|---|
| `StrategyRegistry`, `BaseStrategy`, parameter models | Extend discovery metadata; keep signal contracts and versions |
| `config.py` | Reuse strict models, duplicate-key rejection, percentage units and shared defaults |
| `StudyBackend`, `Segment` | Invoke the existing duration-aware engine for ordinary OHLCV experiments; no new fills engine |
| `history_cache.read_bundle`, `study_data.audit/digest` | Verify existing local immutable bundle formats; never download implicitly |
| `features.atr`, `indicators.volatility_fractions` | Reuse causal risk inputs, limited to supported sizing |
| `metrics.summarize` | Reuse all descriptive metrics and their undefined-value conventions |
| `ExperimentStore`, `provenance` | Reuse unique run directories, SQLite lifecycle and content hashes |
| `create_strategy.py` / `scaffolding.py` | Keep the only strategy generator; add explicit metadata |
| `run_backtest.py`, `run_batch*` | Keep historical semantics and entry points; new ordinary runs use lab YAML |
| `run_cross_market_study.py` | Keep frozen temporal translations and matrix; generic bar-based strategies can use lab on 4h/1d |
| `run_mtf_series.py`, `run_execution_refinement.py` | Keep dedicated audited perpetual/mark/funding and policy adapters; do not silently emulate with spot |
| Existing reports/preflights | Keep for their frozen studies; new fast validation does not require full pytest |

No runner is deleted or formally deprecated. Legacy artifacts are neither moved nor
rewritten. The new orchestrator does not claim to replay frozen batches. Strategy
capabilities prevent unsupported temporal translations, directional modes, specialized
execution and volatility annualization from silently changing a hypothesis.

New code is limited to experiment schema/discovery, bundle resolution, orchestration,
compact deterministic reporting and CLI. Explicit dated experiment definitions govern
`latest-experiment`; run metadata governs `report latest`. Results are research, not
paper/live trading. Funding and specialized MTF remain available through legacy runners,
not through the ordinary spot/synthetic adapter. No external dependency is needed.
