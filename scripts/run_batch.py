"""Run the preregistered Batch 001A against an explicit validated offline bundle."""

import argparse
from pathlib import Path

from quant_lab.batch import run_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/profiles/batch_001/batch.yaml")
    )
    args = parser.parse_args()
    result = run_batch(args.config, Path(__file__).resolve().parents[1])
    print(f"Results: {result.resolve()}")


if __name__ == "__main__":
    main()
