"""Corroborate the 13 identified BTCUSDT spot gaps against daily files and public API."""

import argparse
from pathlib import Path

from quant_lab.gap_audit import audit_hours

HOURS = [
    "2021-02-11T04:00:00Z",
    "2021-03-06T02:00:00Z",
    "2021-04-20T02:00:00Z",
    "2021-04-20T03:00:00Z",
    "2021-04-25T05:00:00Z",
    "2021-04-25T06:00:00Z",
    "2021-04-25T07:00:00Z",
    "2021-08-13T02:00:00Z",
    "2021-08-13T03:00:00Z",
    "2021-08-13T04:00:00Z",
    "2021-08-13T05:00:00Z",
    "2021-09-29T07:00:00Z",
    "2021-09-29T08:00:00Z",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/gap-audits"))
    args = parser.parse_args()
    print(audit_hours(HOURS, args.output).resolve())


if __name__ == "__main__":
    main()
