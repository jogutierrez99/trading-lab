import base64
import io
import json
import os
import tarfile
import time
from hashlib import sha256
from types import SimpleNamespace

import pytest

from trading_lab_orchestration import verification_container as isolation
from trading_lab_orchestration.github_intake import parse_proposal
from trading_lab_orchestration.implementation import load_plan
from trading_lab_orchestration.implementation_contracts import ImplementationRequest
from trading_lab_orchestration.processes import run_process
from trading_lab_orchestration.workspaces import write_json


@pytest.fixture
def verifier():
    instance = object.__new__(isolation.VerificationContainer)
    instance.fingerprint = "1" * 64
    instance.image = "sha256:" + "2" * 64
    instance.guest = "trusted"
    return instance


@pytest.mark.parametrize("clean", [True, False])
def test_pinned_container_without_mounts_and_cleanup_after_interruption(
    verifier, tmp_path, monkeypatch, clean
):
    calls = []

    def cli(arguments, *args):
        calls.append(arguments)
        if arguments[0] == "run":
            raise KeyboardInterrupt
        return {"timed_out": False, "exit_code": 0 if clean else 1, "output_truncated": False}

    monkeypatch.setattr(verifier, "_cli", cli)
    with pytest.raises(KeyboardInterrupt if clean else isolation.IsolationUncertain):
        verifier._execute(["-m", "pytest"], "", tmp_path, "fixture", 10)
    launch, cleanup = calls
    container = launch[launch.index("--name") + 1]
    assert cleanup == ["rm", "--force", container]
    assert {"--network=none", "--pull=never", "--read-only", "--cap-drop=ALL"} <= set(launch)
    assert not {"--mount", "--volume", "--privileged", "-v", "--pid=host"} & set(launch)
    assert any(flag.startswith("--pids-limit=") for flag in launch)
    assert any(flag.startswith("--memory=") for flag in launch)
    assert json.loads((tmp_path / "fixture-container.json").read_bytes())["container"] == container


def test_missing_pin_rejects_verification(monkeypatch):
    monkeypatch.setenv(isolation.IMAGE_VARIABLE, "python:latest")
    with pytest.raises(isolation.IsolationUnavailable, match="reviewed local image ID"):
        isolation.VerificationContainer()


def test_docker_executable_prefers_per_user_installation(tmp_path, monkeypatch):
    environment = {"LOCALAPPDATA": str(tmp_path / "user"), "ProgramFiles": str(tmp_path / "system")}
    monkeypatch.setattr(isolation, "os", SimpleNamespace(name="nt", environ=environment))
    system = tmp_path / "system/Docker/Docker/resources/bin/docker.exe"
    user = tmp_path / "user/Programs/DockerDesktop/resources/bin/docker.exe"
    for path in (system, user):
        path.parent.mkdir(parents=True)
    with pytest.raises(isolation.IsolationUnavailable):
        isolation._docker_executable()
    system.touch()
    assert isolation._docker_executable() == system
    user.touch()
    assert isolation._docker_executable() == user


def test_rejects_link_in_archive_input(tmp_path, monkeypatch):
    path = tmp_path / "link"
    path.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(type(path), "is_symlink", lambda self: self == path)
    with pytest.raises(isolation.IsolationUnavailable, match="reparse-point"):
        isolation._regular_bytes(tmp_path, "link")


def test_supervisor_bounds_stdout_and_stderr(tmp_path):
    import sys

    command = [
        sys.executable,
        "-I",
        "-c",
        "import os; os.write(1,b'a'*9000); os.write(2,b'b'*9000)",
    ]
    out, err = tmp_path / "out", tmp_path / "err"
    result = run_process(command, tmp_path, 10, out, err, output_limit=1024)
    assert result["exit_code"] == 0 and result["output_truncated"]
    assert out.read_bytes() == b"a" * 1024 and err.read_bytes() == b"b" * 1024


STRATEGY = """import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.strategies.base import BaseStrategy


class Parameters(StrictModel):
    pass


class VerificationFixture(BaseStrategy[Parameters]):
    name = "sma_isolation_fixture"
    lab_modes = ("LONG_ONLY",)
    parameter_model = Parameters

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        return 240

    def prepare_features(self, candles):
        assert isinstance(candles.index, pd.DatetimeIndex)
        assert str(candles.index.tz) == "UTC"
        assert "timestamp" not in candles
        close = candles["close"]
        return candles.assign(
            fast=close.rolling(50).mean(),
            slow=close.rolling(200).mean(),
        )

    def generate_long_entries(self, features):
        premium = features["fast"] - features["slow"]
        return (premium.gt(0) & premium.shift().le(0)).tolist()

    def generate_long_exits(self, features):
        premium = features["fast"] - features["slow"]
        return (premium.lt(0) & premium.shift().ge(0)).tolist()

    def generate_short_entries(self, features):
        return [False] * len(features)

    def generate_short_exits(self, features):
        return [False] * len(features)
"""

TESTS = """import numpy as np
import pandas as pd

from quant_lab.config import MarketConfig, RiskConfig, StrategyConfig
from quant_lab.strategies.sma_isolation_fixture import VerificationFixture


def test_native_warmup_and_future_prefix():
    config = StrategyConfig(
        name="sma_isolation_fixture",
        version="1.0.0",
        enabled=False,
        market=MarketConfig(symbol="BTC/USDT", timeframe="1h"),
        risk=RiskConfig(),
    )
    strategy = VerificationFixture(config)
    close = np.concatenate([np.linspace(100, 80, 240), np.linspace(80, 160, 100)])
    index = pd.date_range("2000-01-01", periods=len(close), freq="h", tz="UTC")
    candles = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0},
        index=index,
    )
    complete = strategy.generate_signals(candles)
    prefix = strategy.generate_signals(candles.iloc[:315])
    assert strategy.required_warmup({}, "1h") == 240
    assert not any(complete.long_entries[:199])
    assert any(complete.long_entries)
    assert complete.long_entries[:315] == prefix.long_entries
    assert complete.long_exits[:315] == prefix.long_exits
    assert not any(complete.short_entries)
"""


@pytest.fixture
def synthetic_delivery(tmp_path):
    root = isolation.ROOT / "examples/orchestration/phase-5-4b"
    source = parse_proposal((root / "issue-body.json").read_text(encoding="utf-8"))
    plan = load_plan(root / "implementation-plan.draft.json").model_copy(
        update={"target": "sma_isolation_fixture"}
    )
    request = ImplementationRequest(
        schema_version="1.0",
        mode="PREPARE_ONLY",
        attempt_id="fixture",
        attempt_number=1,
        task_id="fixture",
        candidate_id="fixture",
        hypothesis_manifest=source.manifest,
        hypothesis_sha256="0" * 64,
        base_commit="703829cf19f5b8321b78a2b51949a5db7aa7d380",
        branch="fixture",
        workspace=str(tmp_path),
        plan=plan,
        allowed_write_paths=plan.paths(),
        protected_paths=[],
        authorized_checks=plan.checks(),
        skill_paths=[],
        previous_attempt=None,
        max_api_eur=None,
        max_cpu_seconds=None,
        native_interface_check="SYNTHETIC_OHLCV_UTC_V1",
    )
    yaml = (
        "name: sma_isolation_fixture\nversion: 1.0.0\n"
        "enabled: false\nmarket: {symbol: BTC/USDT, timeframe: 1h}\nparameters: {}\n"
    )
    fixture = tmp_path / "files"
    actual = {}
    for path, contents in zip(plan.paths(), (STRATEGY, yaml, TESTS), strict=True):
        target = fixture / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents.encode())
        actual[path] = sha256(target.read_bytes()).hexdigest()
    return request, fixture, actual


def test_only_sealed_sources_reach_the_container(
    verifier, synthetic_delivery, tmp_path, monkeypatch
):
    request, fixture, actual = synthetic_delivery
    (fixture / ".env").write_text("FAKE_SENTINEL", encoding="utf-8")
    (fixture / "conftest.py").write_text("raise RuntimeError('fixture')", encoding="utf-8")
    commands = []
    report = {
        "status": "VALID",
        "scope": "SYNTHETIC_NATIVE_INTERFACE_ONLY",
        "strategy": request.plan.target,
        "timeframe": "1h",
        "timezone": "UTC",
        "timestamp_column": False,
        "profile_file_modified": False,
        "historical_data_read": False,
        "backtests_executed": 0,
        "economic_assessment": "NOT_ASSESSED",
    }

    def execute(command, payload, folder, name, timeout):
        with tarfile.open(fileobj=io.BytesIO(base64.b64decode(payload))) as archive:
            names = archive.getnames()
            assert "pyproject.toml" in names and set(actual) <= set(names)
            assert not any(item.endswith((".env", "conftest.py", ".sqlite3")) for item in names)
            assert json.load(archive.extractfile("request.json"))["workspace"] == "/work"
        commands.append(command)
        stdout = folder / f"{name}.stdout"
        stdout.write_text(json.dumps(report), encoding="utf-8")
        return {
            "timed_out": False,
            "exit_code": 0,
            "output_truncated": False,
            "stdout": str(stdout),
        }

    monkeypatch.setattr(verifier, "_execute", execute)
    checks, native = verifier.verify(request, fixture, actual, tmp_path, time.monotonic() + 30)
    assert len(checks) == 3 and native["report"] == report
    assert commands == [command[1:] for command in request.authorized_checks] + [
        ["-c", isolation.NATIVE]
    ]
    original = fixture / request.allowed_write_paths[0]
    original.write_text("Staged bytes changed", encoding="utf-8")
    with pytest.raises(isolation.IsolationUnavailable, match="contradicts the sealed delivery"):
        verifier.verify(request, fixture, actual, tmp_path, time.monotonic() + 30)


@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_REAL_ISOLATION_TEST") != "1",
    reason="Explicit acceptance against the installed Windows Linux verifier",
)
def test_real_linux_isolation_positive_and_negative(synthetic_delivery, tmp_path):
    request, fixture, actual = synthetic_delivery
    environment = isolation.VerificationContainer()
    probe = environment.preflight()
    write_json(tmp_path / "isolation-probe.json", probe)
    assert probe["probe"].count("external TCP: blocked") == 2
    assert probe["probe"].count("external write: blocked") == 2
    assert probe["probe"].count("VM-to-host socket: blocked") == 2
    checks, native = environment.verify(request, fixture, actual, tmp_path, time.monotonic() + 180)
    write_json(tmp_path / "acceptance-checks.json", {"checks": checks, "native": native})
    assert len(checks) == 3
    assert native["report"]["warmup_bars"] == 240
    assert native["report"]["backtests_executed"] == 0
