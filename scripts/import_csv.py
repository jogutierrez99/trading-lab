"""Validate original Binance CSVs offline and publish only complete historical bundles."""

import argparse
import json
from pathlib import Path

from quant_lab.config import load_yaml
from quant_lab.csv_history import load_csv_history
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import save_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--csv-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/history"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/csv-import"))
    args = parser.parse_args()
    try:
        request = load_yaml(args.config, HistoryRequest)
        frame, sources, report = load_csv_history(
            request, args.manifest, args.csv_dir, args.report_dir
        )
        path = save_bundle(args.cache_dir, frame, request, sources)
        print(
            json.dumps(
                {
                    "event": "dataset_ready",
                    "path": str(path.resolve()),
                    "quality_report": str(report.resolve()),
                    "rows": len(frame),
                }
            )
        )
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, json.dumps({"event": "csv_import_failed", "error": str(exc)}) + "\n")


if __name__ == "__main__":
    main()
