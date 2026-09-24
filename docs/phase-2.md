# Phase 2: public history and causal features

Implemented: strict historical request, public monthly Binance spot provider (1h only),
UTC OHLCV validation, immutable Parquet cache and reusable SMA/arithmetic ATR.
No strategy signals, sizing, execution, performance metrics or phase 3 work added.

## Usage and contracts

```powershell
python -m pip install -e ".[dev]"
python scripts/download_data.py --config configs/profiles/btc_spot_1h/history.yaml
```

`history.yaml` is separate from `app.yaml`: old app configurations keep their meaning.
Dates must be timezone-aware UTC datetimes aligned to an hour; YAML timestamps must
be unquoted. End is exclusive. Warmup extends start by the requested number of hours.
Only completed months are supported; unavailable archives fail explicitly. Cache and
archive directory arguments resolve from the current working directory. Inputs do not
require account credentials or contact the network on import.

Original ZIP files are retained under SHA256 names in `data/archives`. They are source
material, not certified datasets. The provider checks the publisher's checksum, archive
layout, millisecond/microsecond timestamp units, hourly grid, duplicates, ordering,
finite positive prices, nonnegative volume and OHLC bounds. It validates whole source
months, including portions outside the requested range. HTTP requests have timeouts
and bounded retries for transient failures. Operational events are JSON lines.

Binance source close timestamps must be inside their hour. An early source close is
recorded explicitly in provenance and logged; it never makes a candle available early.
All features are available at `open_time + 1 hour`. The December 2021 archive contains
such a close at 2021-12-24 04:59:54.362 UTC. A read-only API check returned the same
early timestamp (with slightly different OHLCV), so the archive version is retained
and identified by checksum, not silently replaced with a revised API observation.

Monthly format and 2025 microsecond transition are documented by
[Binance public data](https://github.com/binance/binance-public-data#readme).

Only a valid complete request can be saved in `data/history/<dataset_id>/` with
`candles.parquet` and `manifest.json`. Dataset identity hashes resolved request, UTC
nanosecond opening timestamps and little-endian float64 OHLCV values in canonical
column order. Manifest records sources, row count, availability and file checksum.
Bundle publication uses a temporary sibling directory and rename. Existing bundles
are revalidated, never overwritten. A changed dataset gets a new ID. Multiple revisions
require explicit selection through `read_bundle`; no silent latest-version selection.
`--refresh` fetches sources again. Without it, a matching valid bundle is reused offline.

SMA uses a trailing arithmetic mean with a full window. ATR uses a trailing arithmetic
mean of true range, not Wilder smoothing. The first TR is NaN because no previous close
is known; ATR14 first appears on row 15. SMA200 first appears on row 200. No backfill,
centered window, signal generation or fill simulation occurs. `baseline_features`
returns a copy with `sma_50`, `sma_200`, `atr_14`, preserving input rows and timestamps.
Use it only on validated contiguous candles; it does not repair input gaps.

## Real request and quality gate

Requested: 2022-01-01 inclusive through 2026-01-01 exclusive, plus 200 warmup hours
starting 2021-12-23 16:00 UTC. Expected total: 35,264 rows (35,064 study + 200 warmup).

The March 2023 archive lacks **2023-03-24 13:00 UTC**. A direct public spot API request
for exactly that hour also returned `[]`. Therefore this is not repaired by substituting
an invented candle or a different market. The downloader audits remaining months,
retains originals and writes an immutable `quality-<sha256>.json` with all issues.
The command exits nonzero, and no complete validated Parquet bundle is published.

The real audit downloaded and checked all 49 monthly archives (December 2021 through
December 2025). Exactly one missing hour was found. Report:
`data/archives/quality-abbeb13a2be621f793ac08fcf8aa3da82cbf8159ee145279ab12aa68b105731e.json`.
Sources and quality reports are ignored local artifacts, not committed datasets.

Phase 3 must wait for an explicit gap-handling research policy or a verified corrected
source. Any future policy must model discontinuity and indicator warmup explicitly;
it must not turn absence of data into a false hour of trading.

## Verification

Tests cover schema rejection, archive checksums and both timestamp units, warmup across
the 2025 boundary, missing/duplicate/unsorted/misaligned candles, invalid OHLCV, immutable
cache reuse/revisions/corruption, offline CLI reuse, hand-calculated SMA/TR/ATR values
and prefix invariance at warmup boundaries. Existing phase 1 tests remain required.

Verification on Python 3.12.14: 70 tests passed; Ruff lint and format checks passed
(25 Python files); `pip check` passed. Real archive download/audit completed with the
expected quality rejection above. No backtest or performance result was produced.
