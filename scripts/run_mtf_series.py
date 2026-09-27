"""Execute the frozen MTF01-04 protocol after its bound preflight."""

from pathlib import Path

from quant_lab.mtf_series import run

if __name__ == "__main__":
    run(Path(__file__).resolve().parents[1])
