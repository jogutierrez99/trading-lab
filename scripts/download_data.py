"""Download and validate a public historical request, or verify its local cache."""

import argparse
import json
import logging
from pathlib import Path

from quant_lab.binance_history import download_history
from quant_lab.config import load_yaml
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import find_bundle, save_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/history"))
    parser.add_argument("--archive-dir", type=Path, default=Path("data/archives"))
    parser.add_argument(
        "--csv-dir", type=Path, help="Also retain original CSVs and an import manifest"
    )
    parser.add_argument("--refresh", action="store_true", help="Fetch again; retain old revisions")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        request = load_yaml(args.config, HistoryRequest)
        path = None if args.refresh or args.csv_dir else find_bundle(args.cache_dir, request)
        if path is None:
            frame, sources = download_history(
                request, archive_dir=args.archive_dir, csv_dir=args.csv_dir
            )
            path = save_bundle(args.cache_dir, frame, request, sources)
        print(json.dumps({"event": "dataset_ready", "path": str(path.resolve())}))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, json.dumps({"event": "download_failed", "error": str(exc)}) + "\n")


if __name__ == "__main__":
    main()
