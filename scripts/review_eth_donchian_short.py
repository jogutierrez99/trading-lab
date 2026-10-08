"""Read-only evidence review; no market connection or backtest execution."""

from quant_lab.eth_donchian_review import main

if __name__ == "__main__":
    raise SystemExit(main())
