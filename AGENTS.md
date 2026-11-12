# Project instructions

Before modifying research or relevant code, read in order:

1. [README.md](README.md)
2. [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
4. [docs/WORKFLOW.md](docs/WORKFLOW.md)
5. [docs/RESEARCH_RULES.md](docs/RESEARCH_RULES.md)

Then read the affected runner's frozen protocol. Current code/configuration defines
available commands; historical phase notes describe their original scope. Do not expand
a documentation task into strategy, parameter, engine, dataset or result changes.

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
Dedicated later runners implement audited perpetual/funding, MTF and execution refinement.
See their design/results documents; the paragraphs above describe earlier phase boundaries.
The ordinary lab CLI uses spot/synthetic OHLCV execution; dedicated runners retain their
specialized assumptions. No live trading is available.
Follow the user's requested phase boundaries and test before advancing.

## AI EXECUTION POLICY

Codex MAY inspect repositories, implement code/configs/strategies, add tests, run unit
tests and targeted synthetic smoke tests, run Ruff/format checks and fast verification.

Codex MUST NOT by default run full research batches, large parameter sweeps, thousands
of backtests, long MTF/cross-market/refinement studies, wait for long simulations, or
analyze thousands of generated artifacts. Long research workloads are executed locally
by the user. Do not interpret a routine "implement" or "continue" as permission to run
those workloads. A specific user instruction may override this default.

Finish strategy/experiment implementation with the exact local command, for example:
`python scripts/lab.py run trend_btc_1h_001`. Use targeted tests for orchestration changes;
do not require the full suite for every ordinary YAML validation. `validate` is fast;
`validate --full` checks dataset integrity without running backtests. `run` performs
full data checks before execution. See docs/lab-workflow.md.

## Architecture and principles

- `config.py`: strict YAML parsing, shared defaults, resolved research configuration.
- `strategies/base.py`: causal features and long/short decisions, no execution.
- `strategies/registry.py`: trusted module discovery, no hardcoded strategy list.
- `scaffolding.py`: exclusive creation of module/YAML/test triplets.
- Implemented layers: providers, validation/cache, reusable features, risk, execution,
  experiments and reporting. Keep these separate; dashboard remains deferred.
- Favor deterministic rules, explicit configuration, type hints, focused modules and
  meaningful errors. No LLM dependency in the core. Avoid heavy unused dependencies.

## Adding and modifying strategies

Install with `python -m pip install -e ".[dev]"`, then run
`python scripts/create_strategy.py new_strategy`. Implement its `Parameters` schema,
feature preparation and four signal methods. Add causal and long/short behavioral tests.
Enable its YAML only when implemented. Existing family YAMLs must not be overwritten;
liquidity_sweep and breakout_retest still reserve unimplemented families. Inspect the
current registry before scaffolding or implementing a reserved family.

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

The ordinary CLI is scripts/lab.py; Phase 1's no-backtest limitation is historical.
Preserve independent long, short and combined results where supported, costs on both
sides, risk sizing and capped exposure. Spot is long-only; synthetic shorts do not
model funding. Specialized perpetual/MTF runners retain their own assumptions. Keep
parameter selection confined to training data. Walk-forward summaries use test results
only; Monte Carlo analysis records seeds and assumptions. Never imply historical profits
prove future profitability. Separate backtest, out-of-sample and future paper results.

## Data safety and no look-ahead requirement

Use public historical endpoints without private trading credentials. Providers
must validate UTC timestamps, sorting, duplicates, missing candles and OHLC consistency.
Cache valid data deterministically and retain dataset fingerprints. Never silently replace
historical experiment artifacts. Existing storage uses SQLite plus immutable JSON/Parquet,
unique experiment IDs, resolved config, costs, dataset identity, code revision and environment.

Signals are decisions at close; earliest market entry is next open. Every feature at T
must depend only on observations available at T. No centered rolling windows or backfilled
future data. Swing confirmation is timestamped when confirmed. Higher-timeframe values
become available only when that candle closes. Explicitly document intrabar ambiguity,
gap fills and conservative stop/target ordering. Add prefix-invariance tests per strategy
and preserve dedicated multi-timeframe and execution regressions.

## No live trading

Do not implement or enable live order routing or withdrawals. Future paper, monitoring
and alert interfaces must remain separate from strategy decisions and historical runs.
Never create a CME gap detector from Binance candles: require genuine CME futures data
and its calendar/availability semantics through an independent future provider.

## Configuration and quality

`*_pct` always means percentage units: 0.05 = 0.05% = 5 bps. Never mix with fractions.
Experiment paths resolve relative to the experiment YAML; app references resolve relative
to app.yaml. Explicit strategy risk overrides global risk; experiment capital/costs can
override app defaults. Do not confuse dedicated profile schemas with lab experiments.
Parameter models must reject unknown values. No hidden network activity on import.
Structured operational logging belongs with data/experiment workflows as implemented;
never log secrets. Keep `.env`, secrets and local data/results ignored.
Document phase changes, verification evidence and remaining phases. Do not proceed on
broken foundations or add empty pretend implementations of future functionality.

## Strategy / experiment boundary

A strategy defines reusable causal features and signal rules. Asset, timeframe, period,
capital, mode, costs, parameter grids and filters belong in experimental configuration
where supported. Do not clone or change strategy Python just to test another value.
Use configs/experiments for the ordinary strict lab schema, configs/profiles for
dedicated protocols. Check catalogue capabilities; do not bypass unsupported modes,
hourly volatility sizing or legacy_mtf/legacy_batch_006 adapter guards.

## Research evidence and immutable results

Compact publication is allowed only through the lab allowlist into research_results/;
keep results/, reports/, datasets, equity and ledgers local. Never commit/push automatically.
For ordinary classification and frozen historical challenges, read docs/research-evidence.md.
Legacy PASS remains separate; retrospective labels do not establish unobserved holdout
independence. Do not assign adaptive WF winners' combined evidence to each fixed candidate.

Preserve run/backtest IDs, original and resolved config, dataset fingerprints and file
hashes, code hash, Git revision/status, strategy version, timestamps, environment and
seeds when applicable. Record missing provenance as unknown rather than inventing it.
Keep Batch 001 and other frozen configurations/results unchanged. New hypotheses get
new experiment IDs; analyses of old runs get separate uniquely named reports.

Never optimize on final holdout or use its outcome to reselect parameters while calling
it independent validation. Lab has train/validation/test, with test as final holdout;
dedicated runners may additionally have final_holdout. WF selection uses TRAIN only.
Respect each classifier exactly: generic PASS is a filter result, RESEARCH_PASS is a
research gate, and NEAR_PASS grants no V4/paper/live eligibility. Never automatically
mark strategy metadata promising/validated from a backtest or alter thresholds to pass.

## Skills del repositorio

These project-local skills use name/description YAML frontmatter in SKILL.md. No prior
skill system existed here. They live under skills/ and are routed by this contract;
do not assume a client automatically discovers that folder or that global skills were
installed. When the request matches, read the corresponding file (or invoke by path):

- New reusable signal logic: [create-strategy](skills/create-strategy/SKILL.md).
- New market/mode/parameter/period configuration: [create-experiment](skills/create-experiment/SKILL.md).
- An already executed run: [analyze-results](skills/analyze-results/SKILL.md).
- A stricter candidate validation protocol: [validate-strategy](skills/validate-strategy/SKILL.md).

Use one agent workflow for implementation. Steps 4.1–4.2 permit a separate deterministic
Python coordinator for manual HypothesisManifest validation, candidate/task registration,
deduplication, state history and queries in its own SQLite, plus manually activated
Codex CLI implementation in isolated branches/worktrees, with bounded attempts,
quick checks, receipts and explicit reconciliation. Integration tests use a simulated
executable; do not invoke real Codex nested during development. This exception does not
authorize researcher agents, scheduling or OKX integration.
Step 4.3 additionally permits a deterministic, manually invoked backtest executor using
existing validated lab runners, isolated execution copies/results, pinned local datasets,
bounded volume/time, one reserved heavy job and explicit uncertain-run reconciliation.
No model stays active during execution. Technical acceptance uses synthetic data or TRAIN;
never consume reserved TEST/holdouts merely to verify orchestration. No automatic sweeps,
downloads, strategy repairs, economic promotion or demo authorization are implied.
An explicitly authorized manual compatibility repair uses its own identity/provenance
and reviewed scope. Never reset model attempt budgets or rewrite historical receipts.
Step 4.4 permits bounded read-only audits of existing runs, immutable new dossiers and
a coordinator-owned manual Telegram outbox. Preview is the default; real send requires
an explicit operator command and a configured verified private recipient. During this
implementation use simulated Telegram only. Do not change forward watchers or run new
backtests for audit acceptance. An optional independent auditor adapter requires an
explicit configured provider, strict evidence/output contracts and reconciled global
API accounting capped at 20 EUR/month. Unknown spend blocks new calls; no implicit
provider, automatic permission retry, economic promotion or demo authorization.
Step 4.5 integrated historical verification must use read-only/query-only snapshots:
no initialization/migration, state mutation, new jobs, models, backtests or network.
Export only new reports outside inspected evidence. Never simulate incidents on the
real pilot, reset budgets or equate reconstruction with a new unattended end-to-end run.
Step 4.6 permits a manually started deterministic connector between existing stages:
one distinct technical card, one initial Codex attempt and at most two permitted
technical repairs, verified native deliveries, bounded deterministic synthetic runner,
DETERMINISTIC_ONLY audit and Telegram preview only. Never nest real Codex during
development; use simulated executables. The operator starts the real trial later.
Preserve the previous pilot's 3/3 budget. Stop uncertain stages for reconciliation;
never automatically relaunch uncertain executions or deliveries. No manual edits during
the trial, model-auditor APIs, real Telegram send or daily scheduling are authorized.
All existing research, immutable-results, workload and trading protections remain in force.
Post-4.6 OpenAI audit supplements require the explicit audit-openai command, a
verified deterministic source, a separate dossier and the canonical global API
ledger. Development tests simulate the provider. A manual real acceptance requires
a current reviewed cost bound and reconciled spend. Keep the circuit deterministic.
Skills do not authorize long computations beyond the AI EXECUTION POLICY.
Flujo 1 also permits explicit, on-demand research intake from an operator-supplied
batch. Use one bounded structured API request through the canonical global ledger,
retain source and outcome, validate with HypothesisManifest, and stop at manual
review or the coordinator queue. Simulate the provider in development.
Phase 5.1 permits read-only GitHub Issue intake from an explicit author
allowlist and local preparation through the existing coordinator after
operator review and the global budget gate. The bridge never dispatches
Codex or changes GitHub. Use fixtures during development. Publication,
scheduling, model dispatch and trading remain outside this activation.

## Maintaining operational memory

When a change significantly affects architecture, available strategies, backend,
datasets, workflow, experiment types, supported modes or MTF, evaluate and update
docs/PROJECT_STATE.md if needed. Keep it compact; ordinary runs belong in results,
manifests and Git history, not an ever-growing state log. State the scope of verification
and distinguish implementation, historical evidence and newly verified results.

## Trend Volatility Breakout V1

Para esta familia leer [el protocolo congelado](docs/trend-volatility-breakout.md).
Single timeframe 1h, ETH inicial y BTC preparado, mismo grid de 144; no ampliar
parámetros ni utilizar challenge RSI para selección. Preparación offline explícita
de precios USD-M con hashes fijados; funding not modelled. Conservar política de
gaps y clasificación existente, incluidos límites WF de cada configuración fija.
No ejecutar automáticamente grids ni incorporar esta hipótesis a forward/OKX.
