"""Run the eight frozen execution-refinement configurations."""

from pathlib import Path

from quant_lab.refinement_batch import run

if __name__ == "__main__":
    run(Path(__file__).resolve().parents[1])
