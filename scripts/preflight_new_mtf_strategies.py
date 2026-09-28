"""Run tests/static checks only; publish an immutable source-bound receipt."""

from pathlib import Path

from quant_lab.new_mtf_preflight import preflight

if __name__ == "__main__":
    raise SystemExit(0 if preflight(Path(__file__).resolve().parents[1]) else 1)
