"""Run the frozen Batch 002 on two independently validated spot bundles, offline."""

import argparse
from pathlib import Path

from quant_lab.batch_002 import run_batch002

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/profiles/batch_002/batch.yaml")
    )
    args = parser.parse_args()
    print(run_batch002(args.config, Path(__file__).resolve().parents[1]).resolve())
