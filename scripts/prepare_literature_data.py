"""Prepare explicit immutable local snapshots; no downloads or backtests."""

import argparse
import json
from pathlib import Path

from quant_lab.literature_data import prepare

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(prepare(args.root.resolve()), indent=2))
