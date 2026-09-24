"""Execute frozen reused-history Batch 004 offline."""

import argparse
from pathlib import Path

from quant_lab.batch_004 import run_batch004

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/profiles/batch_004/batch.yaml")
    )
    args = parser.parse_args()
    print(run_batch004(args.config, Path(__file__).resolve().parents[1]).resolve())
