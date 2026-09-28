"""Preflight isolates pytest temporaries/cache, including nested pytest processes."""

import os
import subprocess
import sys
from pathlib import Path

from quant_lab.new_mtf_preflight import isolated_test_environment


def test_isolation_is_unique_preserves_environment_and_avoids_shared_cache(monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "--strict-markers")
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", "unusable-shared-root")
    first, second = isolated_test_environment(), isolated_test_environment()
    assert first["PYTEST_DEBUG_TEMPROOT"] != second["PYTEST_DEBUG_TEMPROOT"]
    assert Path(first["PYTEST_DEBUG_TEMPROOT"]).is_dir()
    assert first["PYTEST_ADDOPTS"] == "--strict-markers -p no:cacheprovider"
    assert os.environ["PYTEST_DEBUG_TEMPROOT"] == "unusable-shared-root"
    # Use only fresh owned paths: no existing shared directory is deleted or chmodded.
    root = Path(first["PYTEST_DEBUG_TEMPROOT"])
    test = root / "test_isolated.py"
    test.write_text(
        "def test_temp(tmp_path):\n"
        "    (tmp_path / 'probe').write_text('ok')\n"
        "    assert (tmp_path / 'probe').read_text() == 'ok'\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(test)],
        cwd=root,
        env=first,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / ".pytest_cache").exists()
