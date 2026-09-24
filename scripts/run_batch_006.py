"""Run the frozen independent perpetual Bollinger experiment."""

from pathlib import Path

from quant_lab.batch_006 import run

if __name__ == "__main__":
    run(Path(__file__).resolve().parents[1])
