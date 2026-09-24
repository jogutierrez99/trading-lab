# Phase 1 design record

## Initial repository inspection

The checkout contained only `.git`, with a clean index and no commits, source files or
ancestor AGENTS.md instructions. Python was absent from PATH; a bundled Python 3.12.14
runtime was available to create the local virtual environment.

## Decisions

- Python `src` layout with editable installation and setuptools packaging.
- Strict, frozen Pydantic v2 models and safe YAML with duplicate-key rejection. Nested
  arbitrary parameter mappings are copied into strategy instances and validated by each
  implementation. Frozen models are not a deep immutability guarantee for dict contents.
- Shared risk composition is explicit; strategy overrides preserve unspecified global
  values. Costs have one documented unit. Only research mode is accepted.
- Backend-neutral row-preserving feature protocol and four boolean signal vectors.
  No pandas/vectorbt dependency until actual market/engine work. Runtime validation checks
  lengths and bool types; implementations and later indexed-frame validation must protect
  row order and timestamps. This foundation cannot prove absence of future leakage itself.
- Registries are independent objects. Discovery is explicit and imports trusted package
  modules in sorted order. Duplicate names or invalid implementations fail atomically.
- Disabled configurations reserve the four requested strategy families. Their algorithms
  and detailed parameter/filter schemas belong to Phases 4–7, not this foundation.
- Scaffolds fail explicitly if executed before rules are implemented. Exclusive file
  creation and preflight checks prevent overwrites; cleanup removes only files created
  by a failed call. This is not a crash-recoverable multi-file transaction.
- Deferred unused dependencies, empty subsystems, Docker and Streamlit until runnable
  code makes their contracts testable. Future engine selection must evaluate then-current
  VectorBT/Python compatibility and document its execution semantics.

## Verification scope

Configuration tests cover all supplied YAMLs, repeated deterministic loads, relative path
resolution, inherited/overridden risk, duplicate keys, unsafe tags and invalid values.
Contract tests cover registry isolation, discovery, version checks, disabled/unknown
strategies, typed parameters, long/short outputs and malformed signal vectors.
Generator integration invokes the CLI in a temporary checkout, runs its generated pytest
test, confirms discovery and checks overwrite refusal. No fake CME data is produced.
The causal regression demonstrates prefix invariance using a test-only strategy.

Verification completed on Python 3.12.14:

- `python -m pytest -q`: 38 tests passed (including the generated-test subprocess).
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: all 15 Python files formatted.
- `python -m pip check`: no broken requirements.
- Installed-package imports, all seven YAML files, empty production registry and console
  entry-point help verified. The generator integration verifies a nonempty registry.
- Git whitespace checks and new-file diffs reviewed against the empty repository.
  No commit was created; generated runtime artifacts remain ignored.

Phase 2 remains unstarted. The next work is public Binance ingestion, data validation,
Parquet caching and reusable features. Phases 3–10 are listed in README.
