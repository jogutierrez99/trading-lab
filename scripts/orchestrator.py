"""Run after pip install -e '.[dev]'."""

from trading_lab_orchestration.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
