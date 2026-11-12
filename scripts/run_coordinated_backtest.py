"""Fixed deterministic bridge to the frozen lab; not a configurable shell command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_lab_orchestration.execution_worker import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
