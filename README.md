# Quant Trading Lab

A modular quantitative research laboratory for reproducible strategy experiments.
The initial target is BTC/USDT using public Binance OHLCV data. No private exchange
credentials are required. Historical profitability is not evidence of future returns.

## Local experiment workflow

New ordinary experiments run from YAML without Codex:
`python scripts/lab.py strategies`, `experiments`, `validate latest-experiment`,
`run latest-experiment`, `report latest`, and `status`.
See [PowerShell workflow and examples](docs/lab-workflow.md) and the
[architecture/reuse audit](docs/lab-architecture-audit.md).
Each run freezes configuration/data identities and produces `leaderboard.csv` and
`ai_summary.md`. Existing batch/MTF/perpetual runners and results remain intact.
Codex implements and tests; the user launches long research locally.

**Original Batch 001/002 scope (preserved below).** The reference engine
supports costs, risk sizing, fixed notional, optional targets, causal ATR trailing and
time stops. Donchian trend, Bollinger/RSI mean reversion and hourly momentum are available
in a dedicated profile. The batch records all trials, temporal holdouts, walk-forward
windows and benchmarks. See [Batch 001 implementation](docs/batch-001-implementation.md).
Batch 002 adds volatility-scaled momentum, Donchian/ADX, Bollinger squeeze and regime
mean reversion, with a final holdout and rolling 12-month/3-month walk-forward.
See its [frozen design](docs/batch-002-design.md) and
[executed results](docs/batch-002-results.md).
The full 2022–2025 request still has a source gap. Batch 002 uses independently validated
pre-gap and post-gap bundles; it never bridges the discontinuity. No dashboard,
live trading or withdrawals are implemented. Independent perpetual research with
historical funding is described under Batch 006 below.

An alternative **January 2022–January 2023 inclusive** dataset has passed data and
indicator checks (9,504 study hours plus 200 warmup hours). See its
[test record](docs/data-test-2022-jan2023.md), including the resolved Windows cache access issue.

Current independent extensions: [cross-market study](docs/cross-market-timeframe-study-001.md)
and [Batch 006 perpetual Bollinger long/short](docs/batch-006-design.md). Earlier
phase limitations below describe their original scope, not the independent runners.

## Setup

Run the new lot offline with `python scripts/run_batch_002.py --config
configs/profiles/batch_002/batch.yaml`. Each run has its own ledger and results under
`results/batch_002/`; Batch 001 configurations and artifacts remain unchanged.

Use Python 3.12 or newer. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

On macOS/Linux activate with `source .venv/bin/activate`. No `.env` file is needed.
The editable install is required for scripts to import the `src` package.

## Architecture

```text
src/quant_lab/
  config.py                     validated YAML models and composition
  scaffolding.py                safe source/config/test generation
  strategies/
    base.py                     strategy and close-time signal contracts
    registry.py                 explicit instance-scoped module discovery
configs/
  app.yaml                      capital, percentage costs, seed and file references
  markets.yaml                  BTC/USDT: 5m, 15m, 1h, 4h, 1d
  risk.yaml                     unleveraged risk defaults
  strategies/*.yaml             four disabled family reservations
scripts/create_strategy.py
tests/{unit,integration,regression}/
docs/phase-1.md
```

Future layers: public providers → validated candles/cache → reusable causal features
→ strategy signals → risk → replaceable backtest backend → experiment store → reports.
Strategy modules must not import exchange clients or execute orders. Future paper
broker and alert adapters will consume the same decisions through separate execution
interfaces. Empty implementation directories are deferred until their phase.

## Configuration

The BTC spot proposal has a separate historical request, preserving existing app schemas:

```powershell
python scripts/download_data.py --config configs/profiles/btc_spot_1h/history.yaml
```

This command downloads completed monthly archives, verifies SHA256 checksums, retains
originals under `data/archives`, and validates candles. Only complete, valid requests
produce a bundle under `data/history/<dataset_id>/`. Existing bundles are verified and
reused offline. `--refresh` downloads again and retains different revisions. Missing
candles cause a nonzero exit and an immutable quality report, never fabricated candles.
See [Phase 2](docs/phase-2.md) for supported inputs and the actual historical audit.

Original CSVs can also be retained with `--csv-dir data/csv/binance_spot_BTCUSDT_1h`.
This option downloads sources even if a validated Parquet bundle already exists and
prints a `csv_manifest` path. Reimport them offline with `scripts/import_csv.py`:
checksums and full monthly candle validation run before publishing or reusing a bundle.
See [CSV import and real validation results](docs/csv-import.md). The full 2022–2025
CSV history remains rejected for its missing March 2023 hour.

```python
from quant_lab.config import load_research_config

research = load_research_config("configs/app.yaml")
print(research.model_dump(mode="json"))
```

Paths in `app.yaml` resolve relative to that file. YAML parsing rejects duplicate keys,
unknown fields, invalid types and unsafe tags. Missing referenced files fail explicitly.
Strategy risk fields override `risk.yaml`; omitted fields inherit the shared values.
The standalone `load_yaml(..., StrategyConfig)` uses schema defaults, so use
`load_research_config` to compose a research run. Parameters remain dictionaries until
the selected strategy validates them with its own Pydantic schema. Disabled reserved
families have no parameter schema yet, and therefore cannot be run.

All `*_pct` fields use **percentages**: `0.05` means 0.05%, or 5 basis points, or 0.0005
as a decimal fraction. Conversion belongs at the future execution boundary. Configuration
validation constrains exposure to 100%; sizing/cost simulation is implemented in the
reference backend. The market list describes configured research markets, not a download already
performed. The schema accepts additional fixed timeframes; provider support is validated
by future provider adapters.

## Strategy system

```powershell
python scripts/create_strategy.py cme_gap_reversion
```

Creates `src/quant_lab/strategies/cme_gap_reversion.py`,
`configs/strategies/cme_gap_reversion.yaml` and `tests/unit/test_cme_gap_reversion.py`.
Alternatively use `quant-create-strategy cme_gap_reversion --root PATH_TO_CHECKOUT`.
Existing files are never overwritten. The generated YAML is disabled and rules raise
`NotImplementedError` until implemented. This command creates no CME detector: genuine
CME futures data, session calendars and availability timestamps would be required.

Implement a constrained `Parameters` model, causal `prepare_features`, and four entry/exit
methods. Return one Python boolean per input row in input order (convert pandas series
with `.tolist()`). Include prefix-invariance and long/short rule tests, bump the version
when behavior changes, then enable the YAML. Never modify the engine for ordinary new
strategies. Reserved family YAML files intentionally block scaffolding over their names;
implement those modules directly during Phases 4–7 while preserving their configs.

```python
from quant_lab.strategies.registry import StrategyRegistry

registry = StrategyRegistry().discover()
print(registry.names())  # mean_reversion, time_series_momentum, trend_following
# strategy = registry.create(enabled_strategy_config)
```

Discovery imports trusted local modules; it is not a sandbox for third-party code. There
is no global mutable registry. Duplicate names fail; repeated discovery is idempotent.
V1 loads one implementation per name and requires an exact config/implementation version
match. Reproducing older implementations requires their source revision and environment.

## Execution and validation methodology

The paragraphs below preserve the original roadmap and Phase 1 limitations.
For implemented execution semantics and validation, see
[Batch 001](docs/batch-001-implementation.md).

Planned execution uses signals at candle close and entries at the next candle open.
Features must only use data available by their row's close. Swing confirmation must be
delayed until knowable; higher-timeframe features must align on their availability time.
The future backend must define gap fills, fees on both legs, spread/slippage, and conservative
stop-first treatment when both stop and target touch within a candle. Phase 1 defines
contracts; it does not implement or validate those future execution semantics.

The test-only strategy and production SMA/ATR features demonstrate prefix invariance:
adding future observations must not change past outputs. Resampling, breakout, retest
and fill bias tests will accompany their implementations.

Future experiments will preserve separate long, short and combined results, full resolved
configuration, unique ID, dataset fingerprint, strategy version, Git revision, timestamps
and dependency information. SQLite metadata plus immutable JSON/Parquet artifacts is the
planned storage design. `data/`, `experiments/` and `reports/` are ignored local outputs.
No experiment persistence or historical performance results exist in Phase 1.

Parameter grids will record every trial. Selection must use training data only; holdouts
remain unseen. Walk-forward will aggregate test windows only. Monte Carlo trade-sequence
analysis must expose its sampling assumptions and seed. No single “best strategy” label
will be based only on return.

## First backtest and dashboard (planned)

The offline single-run CLI now works with an enabled profile and explicit validated
dataset. Batch 001A is executable:

```powershell
python -m pip install -e ".[dev,reports]"
python scripts/run_batch.py --config configs/profiles/batch_001/batch.yaml
python scripts/plot_batch.py results/batch_001/<run_id>
```

Results are ignored local artifacts; each run has a unique directory. No data download
occurs during a backtest. The older illustrative commands below remain unavailable
in that exact syntax, and the dashboard is still planned.

These commands are the intended interface, **not available yet**:

```text
python scripts/run_backtest.py --strategies all --symbol BTC/USDT --timeframe 1h
python scripts/run_validation.py --strategy liquidity_sweep --mode walk-forward
streamlit run dashboard/app.py
```

The dashboard will compare stored configurations, equity, drawdown, trades, periodic
returns and long/short metrics. It will distinguish backtest and out-of-sample research.

## Roadmap and limitations

1. **Complete:** configuration, strategy interface/registry, generator, tests, documentation.
2. **Implemented, historical quality gate blocked:** public monthly Binance spot history
   (1h), UTC validation, immutable Parquet bundles, SMA and arithmetic ATR.
3. **Implemented:** reference backend, execution, risk, costs and descriptive metrics.
4. Liquidity sweep baseline and causal tests.
5. Breakout/retest baseline and causal tests.
6. **Implemented baseline:** Bollinger/RSI mean reversion and causal tests.
7. **Implemented baseline:** Donchian trend and causal tests; hourly momentum also added.
8. **Implemented serial batch:** SQLite ledger, immutable artifacts and bounded grids;
   parallel runs remain deferred.
9. **Implemented exploratory:** temporal holdouts and walk-forward; Monte Carlo deferred.
10. Streamlit dashboard and comparisons.

Docker reproducibility will accompany the executable research stack; local development
does not require Docker. Paper trading, real-time data and alerts are later extensions.
VectorBT integration is deferred to Phase 3; no compatibility claim or mandatory dependency
is made now. `FeatureFrame` and boolean signals keep strategy decisions backend-independent.
Runtime dependencies now include pandas, NumPy and PyArrow for candles, features and
Parquet, alongside Pydantic and PyYAML. Downloads use standard-library urllib.

See [AGENTS.md](AGENTS.md) for contributor rules and [Phase 1 notes](docs/phase-1.md)
for design decisions and verification scope.

## Cross-market timeframe study 001

The independent cross-market study adds audited BTC/USDT and ETH/USDT spot archives
for 1h, 4h and 1d, explicit temporal translations of the 19 frozen Batch 001–005
configurations, independent cost reruns, chronological splits, annual diagnostics,
entry excursions, correlations, overlap and Monte Carlo. Historical batch artifacts
and their engine remain unchanged. Earlier roadmap sections describe their original
phase scope; see the [current study protocol](docs/cross-market-timeframe-study-001.md)
and [timeframe translations](docs/cross-market-timeframe-translation.md) for this phase.

```powershell
python scripts/download_cross_market.py
python scripts/verify_cross_market_study.py
python scripts/run_cross_market_study.py
```

The runner requires successful checks bound to the exact source hash. Each study
writes a unique directory under `results/cross_market_timeframe_study_001/`, including
the complete comparison matrix, `summary.md`, `4h_analysis.md`, charts and a SQLite
ledger. Six unsupported combinations are explicit exclusions; no timeframe winner
is selected for investment. A dashboard and live trading are not implemented here.

## Batch 006: Bollinger long/short

Experimento independiente en futuros perpetuos, con funding histórico y supuestos
explícitos de margen aislado. Tres variantes, tres modos y comparación BTC/ETH
en 1h/4h/1d. Protocolo, limitaciones y comandos en
[docs/batch-006-design.md](docs/batch-006-design.md). Sin ejecución real de órdenes.

Ejecución completada: 7.952 backtests, 280 tests aprobados y ninguna configuración
clasificada como prometedora bajo los criterios congelados. Véanse los
[resultados del Batch 006](docs/batch-006-results.md).

## Serie MTF 01–04

Cuatro familias nuevas con baseline 1h, filtro 4h, alineación 4h/1h/15m y
recuperación tras retroceso. MTF01–02 conservan el dataset original; una cohorte
adicional compara V1–V4 excluyendo simétricamente los 18 días con discrepancias
de mark price. MTF04 aplica los criterios de supervivencia ya existentes.
Definiciones, adaptación de ejecución y limitaciones en el
[protocolo MTF](docs/mtf-series-design.md).

```powershell
python scripts/preflight_mtf_series.py
python scripts/run_mtf_series.py
```

El preflight queda ligado al código exacto. Cada ejecución crea artefactos nuevos
en `results/mtf_series/` y en las carpetas de cada fase, con comparación maestra,
operaciones, equity, costes, diagnósticos, hashes y ledger.

La ejecución MTF ha completado 7.200 backtests y 318 tests. Ninguna configuración
cumple todos los criterios heredados para MTF04; los modos direccionales están
implementados, pero esa fase queda excluida por falta de supervivientes.
Véase el [informe de resultados MTF](docs/mtf-series-results.md), con comparación
del histórico original y la cohorte común, y el estado de verificación final.

## Refinamiento de ejecución V2.1 / V4.1

Batch de confirmación de cuatro parejas concretas, LONG_ONLY, sobre la cohorte
MTF03 intacta. Añade señales congeladas, consumo único, cooldown y filtro de
extensión; V4.1 permite que 15m ejecute únicamente oportunidades originadas en 1h.
Los indicadores y costes mantienen sus valores anteriores. Los baselines se
reproducen comparando hashes exactos de trades/equity con MTF03.

```powershell
python scripts/preflight_execution_refinement.py
python scripts/run_execution_refinement.py
```

[Protocolo y criterios previos](docs/execution-refinement-design.md).
La etiqueta operativa de paper es independiente de las clasificaciones históricas;
este batch termina con el informe y no inicia paper trading.

Completado: 1.344 backtests, 335 tests y 672 reproducciones exactas del baseline.
V2.1 no mejora BASE/ADVERSE; Bollinger V4.1 reduce costes pero empeora expectancy.
Ninguna configuración cumple los criterios operativos para paper.
[Resultados y conclusiones por configuración](docs/execution-refinement-results.md).
