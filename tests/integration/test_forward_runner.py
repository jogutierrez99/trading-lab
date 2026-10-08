"""Synthetic end-to-end forward journal, risk, recovery and no-routing regressions."""

from dataclasses import asdict
from decimal import Decimal
from urllib.error import URLError

import numpy as np
import pandas as pd
import pytest

from quant_lab.brokers.base import ReadOnlyBroker
from quant_lab.brokers.instruments import Instrument
from quant_lab.forward.config import load_config
from quant_lab.forward.engine import BASELINE, OPTIONAL, ForwardEngine
from quant_lab.forward.runner import DEFAULT_CONFIG, recover
from quant_lab.forward.store import Store
from quant_lab.market_data.okx import Bar, DataGap


def setup(tmp_path):
    config, settings, _ = load_config(DEFAULT_CONFIG)
    config = config.model_copy(update={"warmup_bars": 250})
    instruments = {
        i: Instrument(
            i, asset, Decimal("0.001"), Decimal("1"), Decimal("1"), Decimal("0.01"), Decimal("10")
        )
        for asset, i in config.instruments.items()
    }
    store = Store(tmp_path, {"forward": config.model_dump(mode="json")}, {"code_sha256": "test"})
    return ForwardEngine(config, settings, instruments, store), store


def fixture_bars(engine, n=300):
    rng = np.random.default_rng(24)
    close = 100 + np.arange(n) * 0.1 + np.sin(np.arange(n) / 3) * 2
    opening = close + rng.normal(0, 0.4, n)
    times = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    hours, quarters = [], []
    for i, timestamp in enumerate(times):
        values = dict(
            open=float(opening[i]),
            high=float(max(opening[i], close[i]) + 0.1),
            low=float(min(opening[i], close[i]) - 2),
            close=float(close[i]),
            volume=100.0,
        )
        hours.append(Bar(engine.eth, "1h", timestamp, **values))
        for j in range(4):
            quarters.append(
                Bar(
                    engine.eth,
                    "15m",
                    timestamp + pd.Timedelta(minutes=15 * j),
                    **(values | {"volume": 25.0}),
                )
            )
    return hours, quarters


def test_end_to_end_no_order_risk_restart_and_reports(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("SIGNAL_ONLY called a broker mutation")

    for method in ("place_order", "cancel_order", "close_position"):
        monkeypatch.setattr(ReadOnlyBroker, method, forbidden)
    engine, store = setup(tmp_path)
    hours, quarters = fixture_bars(engine)
    engine.bootstrap(hours[:250] + quarters[:1000])
    for bar in quarters[1000:1100]:
        engine.ingest(bar, lambda inst, t, b=bar: (b.close, t + pd.Timedelta(seconds=1)))
    assert store.rows("signals")
    intents = store.rows("order_intents")
    assert {r["strategy"] for r in intents} == {BASELINE, OPTIONAL}
    assert not store.rows("orders") and not store.rows("fills")
    for intent in intents:
        assert intent["target_notional"] <= 2500.0
        assert intent["risk_budget"] <= 50.0
        cost = engine.costs
        stop_fill = cost.price(intent["stop_price"], -1)
        loss = intent["target_quantity"] * (
            intent["estimated_entry_price"]
            - stop_fill
            + cost.fee * (intent["estimated_entry_price"] + stop_fill)
        )
        assert loss <= intent["risk_budget"] + 1e-8
    snapshots = engine.positions.copy()
    store.report("stopped")
    for name in (
        "summary.md",
        "ai_summary.md",
        "bars.csv",
        "signals.csv",
        "order_intents.csv",
        "positions_snapshot.csv",
        "broker_state.csv",
        "timing_events.csv",
    ):
        assert (store.path / name).exists()
    assert "NEEDS_REVIEW" in (store.path / "ai_summary.md").read_text(encoding="utf-8")
    store.close()
    engine, store = setup(tmp_path)
    assert engine.positions == snapshots
    for bar in quarters[1000:1100]:
        engine.ingest(bar, forbidden)
    assert len(store.rows("order_intents")) == len(intents)
    store.close()


def test_gap_blocks_then_rest_recovers_without_delayed_entries(tmp_path):
    engine, store = setup(tmp_path)
    hours, quarters = fixture_bars(engine)
    engine.bootstrap(hours[:250] + quarters[:1000])
    with pytest.raises(DataGap):
        engine.ingest(quarters[1001], lambda *_: pytest.fail("Quote requested across gap"))
    # Only ETH is needed in this isolated recovery fixture.
    engine.config = engine.config.model_copy(update={"instruments": {"ETH": engine.eth}})

    class Feed:
        def history(self, instrument, timeframe, count, since=None):
            source = (
                quarters[:1004] if timeframe == "15m" else hours[:251] if timeframe == "1h" else []
            )
            return [b for b in source if since is None or b.timestamp >= since]

        def quote(self, *args):
            pytest.fail("REST recovery must not fabricate a contemporaneous quote")

    recover(engine, Feed())
    assert len(engine.book.frame(engine.eth, "15m")) == 1004
    assert not store.rows("order_intents")
    store.close()


def test_broker_protocol_readonly_surface():
    from quant_lab.brokers.base import Broker
    from quant_lab.brokers.signal_only import SignalOnlyBroker

    for name in (
        "get_balance",
        "get_positions",
        "get_position",
        "get_open_orders",
        "place_order",
        "cancel_order",
        "get_order",
        "get_fills",
        "close_position",
        "get_instrument",
        "get_instruments",
        "reconcile",
    ):
        assert hasattr(Broker, name)
        assert hasattr(SignalOnlyBroker, name)


def test_sizing_uses_instrument_contract_metadata(tmp_path):
    engine, store = setup(tmp_path)
    time = pd.Timestamp("2026-01-01", tz="UTC")
    with store.db:
        intent = engine.sized_intent(BASELINE, "signal", time, 3000, time, 20)
    assert Decimal(intent.contracts) % Decimal("1") == 0
    assert intent.target_quantity == float(Decimal(intent.contracts) * Decimal("0.001"))
    assert asdict(intent)["execution_policy"] == "BASELINE"
    store.close()


@pytest.mark.parametrize("clock_failures", [0, 1, 2, 10])
def test_runner_reconnects_recovers_and_stops_after_bounded_update(
    tmp_path, monkeypatch, clock_failures
):
    pytest.importorskip("websockets")
    from quant_lab.forward import runner
    from quant_lab.mtf_features import STEPS

    config, inherited, _ = load_config(DEFAULT_CONFIG)
    config = config.model_copy(update={"warmup_bars": 250, "max_reconnects": 2})
    endpoint = pd.Timestamp("2026-02-01", tz="UTC")
    instruments = {
        i: Instrument(
            i, asset, Decimal("0.001"), Decimal("1"), Decimal("1"), Decimal("0.01"), Decimal("10")
        )
        for asset, i in config.instruments.items()
    }
    calls = []

    from quant_lab.brokers.okx_demo import OKXDemoBroker
    from quant_lab.market_data.okx import OKXMarketData

    remaining = clock_failures

    def request(path, headers):
        nonlocal remaining
        assert path == "/api/v5/public/time"
        calls.append(("clock",))
        if remaining:
            remaining -= 1
            raise URLError("sensitive transport details")
        return {"code": "0", "data": [{"ts": str(endpoint.value // 1000000)}]}

    class Broker:
        def get_instrument(self, instrument):
            return instruments[instrument]

    class Feed:
        def __init__(self, broker, instruments):
            self.round = 0
            self.clock = OKXMarketData(OKXDemoBroker(request=request), [])

        def history(self, instrument, timeframe, count, since=None):
            calls.append(("history", instrument, timeframe, since))
            stamps = pd.date_range(
                end=endpoint - STEPS[timeframe], periods=count, freq=STEPS[timeframe]
            )
            return [
                Bar(instrument, timeframe, t, 100, 101, 99, 100, 10)
                for t in stamps
                if since is None or t >= since
            ]

        def now(self):
            if self.round == 1 and clock_failures:
                return self.clock.now()
            return endpoint + pd.Timedelta(minutes=15 if self.round >= 2 else 0)

        def quote(self, *args):
            pytest.fail("Flat fixture must not create a signal")

        def updates(self):
            self.round += 1
            calls.append(("connect", self.round))
            if self.round == 1:
                self.now()  # Real clock refresh/broker path from the reported traceback.
                raise ConnectionError("synthetic disconnect")
            yield Bar(config.instruments["ETH"], "15m", endpoint, 100, 101, 99, 100, 10)

    for key in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(runner, "load_config", lambda _: (config, inherited, tmp_path))
    monkeypatch.setattr(runner, "OKXDemoBroker", Broker)
    monkeypatch.setattr(runner, "OKXMarketData", Feed)
    monkeypatch.setattr(runner, "provenance", lambda _: {"code_sha256": "bounded-test"})
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    if clock_failures > config.max_reconnects:
        with pytest.raises(RuntimeError, match="Reconnect limit reached"):
            runner.run(DEFAULT_CONFIG, max_updates=1)
        assert ("connect", 2) not in calls
        metadata = list(tmp_path.glob("*/session.json"))
        import json

        assert json.loads(metadata[0].read_text(encoding="utf-8"))["status"] == "failed"
        assert "sensitive" not in list(tmp_path.glob("*/errors.log"))[0].read_text(encoding="utf-8")
        return
    runner.run(DEFAULT_CONFIG, max_updates=1)
    assert ("connect", 2) in calls
    assert sum(c[0] == "history" for c in calls) == 12
    summaries = list(tmp_path.glob("*/summary.md"))
    assert len(summaries) == 1
    report = summaries[0].read_text(encoding="utf-8")
    assert "RECONNECTED" in report and "BLOCK_DEMO_EXECUTION" not in report
    assert '"data_gaps_resolved": 1' in report


def test_monitoring_gaps_do_not_change_signals_intents_or_positions(tmp_path):
    reference, rs = setup(tmp_path / "reference")
    observed, os = setup(tmp_path / "observed")
    hours, quarters = fixture_bars(reference)
    for engine in (reference, observed):
        engine.bootstrap(hours[:250] + quarters[:1000])
    for i, bar in enumerate(quarters[1000:1100]):
        if i % 32 == 0:
            monitor = Bar(
                observed.config.instruments["BTC"],
                "4h",
                bar.timestamp.floor("4h"),
                9999,
                10000,
                1,
                2,
                9999,
            )
            observed.ingest(monitor, lambda *_: pytest.fail("Monitoring requested quote"))
        for engine in (reference, observed):
            engine.ingest(bar, lambda inst, t, b=bar: (b.close, t + pd.Timedelta(seconds=1)))
    assert rs.rows("signals") == os.rows("signals")
    assert rs.rows("order_intents") == os.rows("order_intents")
    assert reference.positions == observed.positions
    assert reference.equity == observed.equity
    assert observed.book.bars.keys() == reference.book.bars.keys()
    assert any(e["kind"] == "MONITORING_WARNING" for e in os.rows("events"))
    assert not any(e["kind"] == "DATA_GAP" for e in os.rows("events"))
    latest = observed.monitor_latest.copy()
    rs.close()
    os.close()
    restored, store = setup(tmp_path / "observed")
    assert restored.monitor_latest == latest
    store.close()


def test_bootstrap_optional_failure_is_visible_but_required_gap_blocks(tmp_path):
    engine, store = setup(tmp_path)
    hours, quarters = fixture_bars(engine)

    class Feed:
        required_gap = False

        def history(self, inst, tf, count, *, since=None):
            if engine.config.required_feed(inst, tf):
                if self.required_gap:
                    raise DataGap("ETH required gap")
                return hours[:250] if tf == "1h" else quarters[:1000]
            raise DataGap("monitoring history unavailable")

    feed = Feed()
    recover(engine, feed, initial=True)
    assert len(engine.book.frame(engine.eth, "1h")) == 250
    assert len([e for e in store.rows("events") if e["kind"] == "MONITORING_WARNING"]) == 4
    feed.required_gap = True
    with pytest.raises(DataGap, match="ETH required"):
        recover(engine, feed)
    store.close()
