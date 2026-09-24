import os
import shutil
import subprocess
import sys

import pytest

from quant_lab.scaffolding import create_strategy


@pytest.fixture
def checkout(tmp_path, repo_root):
    shutil.copytree(repo_root / "src", tmp_path / "src")
    shutil.copytree(repo_root / "scripts", tmp_path / "scripts")
    return tmp_path


def test_cli_generation_discovery_and_generated_test(checkout):
    env = os.environ | {"PYTHONPATH": str(checkout / "src")}
    command = [sys.executable, "scripts/create_strategy.py", "cme_gap_reversion"]
    run = subprocess.run(command, cwd=checkout, env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    test = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/test_cme_gap_reversion.py", "-q"],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
    )
    assert test.returncode == 0, test.stdout + test.stderr
    before = (checkout / "src/quant_lab/strategies/cme_gap_reversion.py").read_bytes()
    again = subprocess.run(command, cwd=checkout, env=env, capture_output=True, text=True)
    assert again.returncode == 2
    assert "Refusing to overwrite" in again.stderr
    assert (checkout / "src/quant_lab/strategies/cme_gap_reversion.py").read_bytes() == before


@pytest.mark.parametrize("name", ["../evil", "Upper", "class", "base", "registry", "nul", "com1"])
def test_rejects_bad_names(checkout, name):
    with pytest.raises(ValueError):
        create_strategy(name, checkout)


def test_preflight_conflict_does_not_create_partial_files(checkout):
    path = checkout / "configs/strategies/example.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("existing")
    with pytest.raises(FileExistsError):
        create_strategy("example", checkout)
    assert not (checkout / "src/quant_lab/strategies/example.py").exists()
    assert path.read_text() == "existing"
