"""The preflight never relies on pytest's shared OS temp directory."""

import sys
from pathlib import Path

import pytest

from quant_lab.forward.preflight import create_check_directory, run_check, technical_commands


def test_pytest_uses_unique_project_temp_without_touching_prior_runs(tmp_path):
    old = create_check_directory(tmp_path)
    sentinel = old / "preserve.txt"
    sentinel.write_text("previous run", encoding="utf-8")
    current = create_check_directory(tmp_path)
    assert current != old
    (tmp_path / "conftest.py").write_text(
        "import pytest\n"
        "original = pytest.TempPathFactory.getbasetemp\n"
        "def checked(self):\n"
        "    assert self._given_basetemp is not None, 'Shared OS temp is unavailable'\n"
        "    return original(self)\n"
        "pytest.TempPathFactory.getbasetemp = checked\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "test_temp.py"
    fixture.write_text(
        "def test_temp(tmp_path):\n    (tmp_path / 'ok').write_text('ok')\n", encoding="utf-8"
    )
    command = technical_commands()[0] + [str(fixture)]
    temporary = Path(command[command.index("--basetemp") + 1])
    assert not temporary.exists()
    assert not temporary.is_relative_to(tmp_path)
    log = current / "pytest.log"
    run_check(command, tmp_path, log)
    assert "1 passed" in log.read_text(encoding="utf-8")
    assert sentinel.read_text(encoding="utf-8") == "previous run"
    assert temporary.is_dir()


def test_failed_check_keeps_complete_log_and_stops(tmp_path):
    log = tmp_path / "failure.log"
    with pytest.raises(SystemExit, match="Full output"):
        run_check(
            [sys.executable, "-c", "print('diagnostic details'); raise SystemExit(3)"],
            tmp_path,
            log,
        )
    assert "diagnostic details" in log.read_text(encoding="utf-8")


def test_connectivity_full_warmup_uses_configured_count(monkeypatch):
    from quant_lab.forward import preflight
    from quant_lab.forward.runner import DEFAULT_CONFIG

    counts = []

    class Broker:
        def server_time(self):
            return 0

        def get_instrument(self, instrument):
            from decimal import Decimal

            from quant_lab.brokers.instruments import Instrument

            return Instrument(instrument, "ETH", *(Decimal("1") for _ in range(5)))

    class Feed:
        def __init__(self, *args):
            pass

        def history(self, instrument, timeframe, count, *, since=None):
            counts.append(count)
            return []

    monkeypatch.setattr(preflight, "OKXDemoBroker", Broker)
    monkeypatch.setattr(preflight, "OKXMarketData", Feed)
    assert preflight.connectivity(DEFAULT_CONFIG, public_only=True)["warmup"] == "NOT_CHECKED"
    assert counts == [2] * 6
    counts.clear()
    result = preflight.connectivity(DEFAULT_CONFIG, public_only=True, full_warmup=True)
    assert result["warmup"] == "REQUIRED_FEEDS_VERIFIED"
    assert counts == [800] * 6


def test_history_monitoring_fallback_does_not_certify_warmup():
    from quant_lab.forward.config import load_config
    from quant_lab.forward.feeds import history, instrument_lookup
    from quant_lab.forward.runner import DEFAULT_CONFIG
    from quant_lab.market_data.okx import DataGap

    config, _, _ = load_config(DEFAULT_CONFIG)

    class Feed:
        def history(self, inst, tf, count, *, since=None):
            if count > 2:
                raise DataGap("unconfirmed historical candle")
            return ["recent confirmed only"]

    bars, warning = history(config, Feed(), config.instruments["ETH"], "4h")
    assert bars == ["recent confirmed only"]
    assert warning["warmup_verified"] is False
    for tf in ("1h", "15m"):
        with pytest.raises(DataGap):
            history(config, Feed(), config.instruments["ETH"], tf)

    class Broker:
        def get_instrument(self, instrument):
            if instrument == config.instruments["BTC"]:
                raise ValueError("BTC metadata unavailable")
            return "ETH verified"

    instruments, warnings = instrument_lookup(config, Broker())
    assert instruments == {config.instruments["ETH"]: "ETH verified"}
    assert len(warnings) == 1
