"""Execute only after the recorded preflight matches the current source hash."""

import argparse
from pathlib import Path

from quant_lab.cross_market_study import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    run(Path(__file__).resolve().parents[1], args.resume)
