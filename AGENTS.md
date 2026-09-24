# Project instructions

## Purpose and current scope

Build a modular quantitative research laboratory, initially BTC/USDT on public Binance
data. This is not a single bot or a fixed list of four strategies. Phase 1 foundations
and Phase 2 data tooling are implemented; see README and docs/phase-2.md. The requested
2022–2025 history has an unresolved source gap; no full valid dataset for that range
or backtest exists. An alternative January 2022–January 2023 dataset passed data and
indicator checks; see docs/data-test-2022-jan2023.md for evidence and cache access limits.
Historical execution and Batch 001A now implement three spot strategies, serial experiment
storage and exploratory temporal validation; see docs/batch-001-implementation.md.
Batch 002 adds four long-only modules and independent validated pre/post-gap datasets,
entry-time volatility sizing, close-based trailing and a final holdout. See
docs/batch-002-design.md. Preserve Batch 001 strategies/configs/artifacts unchanged.
Funding, perpetuals, multi-leg portfolios, a dashboard and Monte Carlo remain unavailable.
Follow the user's requested phase boundaries and test before advancing.

## Architecture and principles

- `config.py`: strict YAML parsing, shared defaults, resolved research configuration.
- `strategies/base.py`: causal features and long/short decisions, no execution.
- `strategies/registry.py`: trusted module discovery, no hardcoded strategy list.
- `scaffolding.py`: exclusive creation of module/YAML/test triplets.
- Later layers: providers, validation/cache, reusable features, risk, execution,
  experiments, statistical validation, reporting and dashboard. Keep these separate.
- Favor deterministic rules, explicit configuration, type hints, focused modules and
  meaningful errors. No LLM dependency in the core. Avoid heavy unused dependencies.

## Adding and modifying strategies

Install with `python -m pip install -e ".[dev]"`, then run
`python scripts/create_strategy.py new_strategy`. Implement its `Parameters` schema,
feature preparation and four signal methods. Add causal and long/short behavioral tests.
Enable its YAML only when implemented. The four reserved family YAMLs already exist;
implement their modules directly in the corresponding phase instead of overwriting.

Do not modify the backtesting engine merely to add a strategy. Ordinary additions require
only a strategy file, configuration and tests. The registry discovers concrete local
subclasses. Never swallow import failures or duplicate names. Increment strategy versions
when behavior changes. Preserve old configurations/results and document migrations.
V1 registry supports one implementation per name; replay old versions from their Git revision.

## Tests and checks

Run `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`.
Unit tests cover config and contracts; integration tests exercise the real generator CLI
and discover/run generated tests in a temporary checkout. Regression tests establish the
prefix-invariance pattern. Add actual indicator and fill regressions with those modules.
Inspect `git diff` and untracked files. Do not commit credentials or generated datasets.

## Backtests and validation

No backtest or validation CLI is implemented in Phase 1. Planned commands are documented
in README, clearly marked unavailable. Future backtests must support independent long,
short and combined results, costs on both sides, risk sizing and capped exposure. Keep
parameter selection confined to training data. Walk-forward summaries use test results
only; Monte Carlo analysis records seeds and assumptions. Never imply historical profits
prove future profitability. Separate backtest, out-of-sample and future paper results.

## Data safety and no look-ahead requirement

Use public historical endpoints without private trading credentials. Future providers
must validate UTC timestamps, sorting, duplicates, missing candles and OHLC consistency.
Cache valid data deterministically and retain dataset fingerprints. Never silently replace
historical experiment artifacts. Planned storage is SQLite plus immutable JSON/Parquet,
unique experiment IDs, resolved config, costs, dataset identity, code revision and environment.

Signals are decisions at close; earliest market entry is next open. Every feature at T
must depend only on observations available at T. No centered rolling windows or backfilled
future data. Swing confirmation is timestamped when confirmed. Higher-timeframe values
become available only when that candle closes. Explicitly document intrabar ambiguity,
gap fills and conservative stop/target ordering. Add prefix-invariance tests per strategy
and dedicated multi-timeframe and execution tests when those capabilities arrive.

## No live trading

Do not implement or enable live order routing or withdrawals. Future paper, monitoring
and alert interfaces must remain separate from strategy decisions and historical runs.
Never create a CME gap detector from Binance candles: require genuine CME futures data
and its calendar/availability semantics through an independent future provider.

## Configuration and quality

`*_pct` always means percentage units: 0.05 = 0.05% = 5 bps. Never mix with fractions.
Config paths resolve relative to app.yaml; explicit strategy risk overrides global risk.
Parameter models must reject unknown values. No hidden network activity on import.
Structured operational logging belongs with data/experiment workflows as implemented;
never log secrets. Keep `.env`, secrets and local data/results ignored.
Document phase changes, verification evidence and remaining phases. Do not proceed on
broken foundations or add empty pretend implementations of future functionality.
