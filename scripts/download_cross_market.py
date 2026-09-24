"""Download immutable, resumable spot archives. No strategy execution."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from quant_lab.study_data import download_all

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01T00:00:00Z")
    parser.add_argument("--end", default=datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z"))
    args = parser.parse_args()
    paths = download_all(Path("data/cross_market_timeframe_study_001"), args.start, args.end)
    print(json.dumps(paths, indent=2))
