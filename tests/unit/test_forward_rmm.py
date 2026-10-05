"""RMM forward parity, causal boundaries and durable fake-demo execution."""

from dataclasses import asdict
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from quant_lab.brokers.instruments import Instrument
from quant_lab.brokers.okx_execution import OKXDemoExecution, demo_transport
from quant_lab.forward.config import RMM_NAMES, load_config
from quant_lab.forward.demo_execution import DemoCoordinator
from quant_lab.forward.engine import ForwardEngine
from quant_lab.forward.rmm_operations import DEFAULT, verify
from quant_lab.forward.shadow_reconstruct import reconstruct
from quant_lab.forward.store import Store
from quant_lab.market_data.okx import Bar, parse_bar


def setup(tmp_path, config_path=DEFAULT):
    config, settings, _ = load_config(config_path)
    instruments = {}
    for asset in config.instruments:
        i = Instrument(
            instrument_id=f"{asset}-USD_UM_XPERP-310328",
            base=asset,
            settlement_currency="USD",
            contract_size=Decimal(".001"),
            lot_size=Decimal("1"),
            min_size=Decimal("1"),
            tick_size=Decimal(".01"),
            max_leverage=Decimal("10"),
        )
        instruments[i.instrument_id] = i
    config = config.model_copy(
        update={
            "instruments": {
                a: next(i for i in instruments if i.startswith(a)) for a in config.instruments
            }
        }
    )
    resolved = dict(
        forward=config.model_dump(mode="json"),
        inherited=settings.model_dump(mode="json"),
        instruments={k: asdict(v) for k, v in instruments.items()},
    )
    store = Store(tmp_path, resolved, {"code_sha256": "fixture"})
    engine = ForwardEngine(config, settings, instruments, store)
    return engine, store


def bars(engine, n=1002, falling=False):
    x = np.arange(n)
    prices = 100 + (-0.04 if falling else 0.04) * x + np.sin(x / 5)
    dates = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    return [
        Bar(engine.eth or engine.config.instruments["BTC"], "4h", t, p, p + 1, p - 1, p, 1.0)
        for t, p in zip(dates, prices, strict=True)
    ]


@pytest.mark.parametrize("falling", [False, True])
def test_signal_parity_sizing_restart_long_only_and_shadow(tmp_path, falling):
    engine, store = setup(tmp_path / "forward")
    data = bars(engine, falling=falling)
    engine.bootstrap(data[:1000])
    last = data[1000]
    engine.ingest(last, lambda i, t: (last.close, t))
    intents = store.rows("order_intents")
    names = {r["strategy"] for r in intents}
    assert names == {RMM_NAMES[0]} if falling else names == set(RMM_NAMES[:2])
    frame = engine.book.frame(engine.eth, "4h")
    strategy = engine.rmm.adapters["ETH"]
    actual = strategy.generate_signals(frame)
    row, signals = engine.rmm.decision("ETH", last.close_time)
    assert signals["long"] == actual.long_entries[-1]
    assert signals["short"] == actual.short_entries[-1]
    rv = frame.close.pct_change().rolling(180).std(ddof=1).iloc[-1] * np.sqrt(2190)
    assert row.realized_volatility == pytest.approx(rv)
    for intent in intents:
        assert intent["stop_price"] is None and intent["risk_budget"] is None
        signal = next(s for s in store.rows("signals") if s["signal_id"] == intent["id"])
        assert signal["calculated_exposure_pct"] == pytest.approx(min(25, max(5, 10 / rv)))
        assert intent["target_notional"] <= 2500
        assert float(intent["contracts"]) * 0.001 == pytest.approx(intent["target_quantity"])
        assert intent["side"] == ("sell" if falling else "buy")
    restored = ForwardEngine(engine.config, engine.inherited, engine.instruments, store)
    restored.ingest(last, lambda *_: pytest.fail("Duplicate requested quote"))
    assert store.rows("order_intents") == intents
    assert len(store.rows("signals")) == len(intents)
    store.report("stopped")
    out = reconstruct(store.path, tmp_path / "derived")
    assert len(pd.read_csv(out / "shadow_positions_reconstructed.csv")) == len(intents)
    assert not store.rows("orders")
    store.close()


def test_exit_no_same_boundary_reversal_and_gap_blocks(tmp_path):
    engine, store = setup(tmp_path)
    data = bars(engine)
    engine.bootstrap(data[:1000])
    engine.ingest(data[1000], lambda i, t: (data[1000].close, t))
    b = data[1001]
    b = Bar(b.instrument_id, "4h", b.timestamp, 50.0, 51.0, 49.0, 50.0, 1.0)
    engine.ingest(b, lambda i, t: (50.0, t))
    assert all(r["reason"] == "RMM_EXIT" for r in store.rows("order_intents")[-2:])
    assert all(engine.positions[n] is None for n in RMM_NAMES[:2])
    assert all(p["status"] == "CLOSED" for p in engine.shadow.positions.values())
    store.report("stopped")
    with store.db:
        store.event("DATA_GAP", "gap", {"resolved": False})
    engine.ingest(
        Bar(engine.eth, "4h", b.timestamp + pd.Timedelta(hours=4), 50, 51, 49, 50, 1),
        lambda *_: pytest.fail("Gap requested quote"),
    )
    assert len(store.rows("order_intents")) == 4
    store.close()


def test_open_4h_and_frozen_configuration():
    raw = ["0", "100", "101", "99", "100", "1", "1", "100", "0"]
    assert parse_bar("ETH", "4h", raw, pd.Timestamp("1970-01-01T04:00Z")) is None
    raw[-1] = "1"
    with pytest.raises(ValueError, match="unclosed"):
        parse_bar("ETH", "4h", raw, pd.Timestamp("1970-01-01T03:59Z"))
    config, _, _ = load_config(DEFAULT)
    with pytest.raises(ValueError):
        type(config).model_validate(config.model_dump() | {"demo_strategy": RMM_NAMES[3]})
    with pytest.raises(ValueError):
        type(config).model_validate(
            config.model_dump() | {"parameters": {"momentum_lookback": 210}}
        )


def test_demo_safety_headers_and_no_live(monkeypatch):
    for name in ("KEY", "SECRET", "PASSPHRASE"):
        monkeypatch.setenv("OKX_DEMO_API_" + name, "fake")
    sent = []

    def request(method, path, headers, body):
        sent.append((method, path, headers, body))
        return {"code": "0", "data": [{"sCode": "0"}]}

    payload = dict(
        instId="ETH-test",
        tdMode="isolated",
        posSide="net",
        side="buy",
        ordType="market",
        sz="1",
        clOrdId="rmm123",
        reduceOnly=False,
    )
    with pytest.raises(ValueError):
        OKXDemoExecution(request=request).submit(payload)
    OKXDemoExecution(armed=True, request=request).submit(payload)
    assert sent[0][2]["x-simulated-trading"] == "1"
    assert "expTime" in sent[0][2]
    with pytest.raises(ValueError):
        demo_transport("POST", "/api/v5/trade/order", {}, "")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "true")
    with pytest.raises(ValueError):
        OKXDemoExecution(armed=True, request=request)


class FakeDemo:
    def __init__(self):
        self.submissions = []
        self.unknown = False
        self.position = "0"
        self.state = "filled"
        self.funded = True

    def entry_balance_ready(self):
        if not self.funded:
            raise ValueError("Demo trading equity is not positive")
        return Decimal("10000")

    def account_ready(self, i):
        pass

    def get_positions(self):
        return (
            []
            if self.position == "0"
            else [
                {"instId": "ETH-USD_UM_XPERP-310328", "pos": self.position, "mgnMode": "isolated"}
            ]
        )

    def get_open_orders(self):
        return []

    def submit(self, payload):
        self.submissions.append(payload)
        self.position = "0" if payload["reduceOnly"] else payload["sz"]
        if self.unknown:
            raise TimeoutError("unknown")
        return [{"sCode": "0", "ordId": "1"}]

    def by_client(self, i, client):
        if self.unknown:
            return []
        return [
            {
                "state": self.state,
                "ordId": str(len(self.submissions)),
                "avgPx": "140",
                "uTime": str(int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)),
            }
        ]

    def get(self, endpoint, params):
        if endpoint == "/api/v5/trade/orders-pending":
            return []
        return [
            {"fillSz": self.submissions[-1]["sz"], "tradeId": "1", "fee": "-.1", "feeCcy": "USD"}
        ]


def demo_intent(engine, store):
    data = bars(engine)
    engine.bootstrap(data[:1000])
    engine.ingest(data[1000], lambda i, t: (140.0, t))
    # Synthetic history is old; only the injected execution clock sees it as timely.
    return data[1000].close_time


@pytest.mark.parametrize("equity", ["0", "-1", "NaN", "Infinity", "", None, "10000"])
def test_demo_entry_balance_guard_reads_exchange_equity(monkeypatch, equity):
    for name in ("KEY", "SECRET", "PASSPHRASE"):
        monkeypatch.setenv("OKX_DEMO_API_" + name, "fake")
    sent = []

    def request(method, path, headers, body):
        sent.append((method, path))
        return {"code": "0", "data": [{"totalEq": equity}]}

    broker = OKXDemoExecution(request=request)
    if equity == "10000":
        assert broker.entry_balance_ready() == Decimal("10000")
    else:
        with pytest.raises(ValueError, match="Demo trading equity"):
            broker.entry_balance_ready()
    assert sent == [("GET", "/api/v5/account/balance")]


def test_unfunded_demo_entry_creates_no_submission_or_durable_order(tmp_path, monkeypatch):
    engine, store = setup(tmp_path)
    now = demo_intent(engine, store)
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: now))
    fake = FakeDemo()
    fake.funded = False
    coordinator = DemoCoordinator(store, fake, RMM_NAMES[0], engine.instruments, engine.inherited)
    with pytest.raises(ValueError, match="equity is not positive"):
        coordinator.drain()
    assert not fake.submissions
    assert not store.rows("orders")
    assert store.rows("order_intents")
    store.close()


@pytest.mark.parametrize("unknown", [False, True])
def test_demo_durable_submission_no_duplicate_or_timeout_retry(tmp_path, monkeypatch, unknown):
    engine, store = setup(tmp_path)
    now = demo_intent(engine, store)
    fake = FakeDemo()
    fake.unknown = unknown
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: now))
    coordinator = DemoCoordinator(store, fake, RMM_NAMES[0], engine.instruments, engine.inherited)
    if unknown:
        with pytest.raises(TimeoutError):
            coordinator.drain()
        with pytest.raises(RuntimeError, match="Unknown"):
            coordinator.drain()
    else:
        coordinator.drain()
        coordinator.drain()
        assert (store.restore() or {})["demo_position"]["quantity"] > 0
        assert len(store.rows("fills")) == 1
    assert len(fake.submissions) == 1
    assert len(store.rows("orders")) == 1
    store.close()


def test_activation_gate_rejects_short_stage(tmp_path):
    engine, store = setup(tmp_path)
    store.report("stopped")
    with pytest.raises(ValueError, match=">=4h"):
        verify(store.path, engine.config, {"code_sha256": "fixture"})
    store.close()


def test_partial_fill_pauses_then_reconciles_without_resubmit(tmp_path, monkeypatch):
    engine, store = setup(tmp_path)
    now = demo_intent(engine, store)
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: now))
    fake = FakeDemo()
    fake.state = "partially_filled"
    coordinator = DemoCoordinator(store, fake, RMM_NAMES[0], engine.instruments, engine.inherited)
    coordinator.drain()
    coordinator.drain()
    assert len(fake.submissions) == 1
    assert store.rows("fills")
    assert not store.restore().get("demo_position")
    assert store.restore()["demo_pending_order"]["status"] == "PARTIALLY_FILLED"
    store.report("running")
    fake.state = "filled"
    coordinator.drain()
    assert store.restore()["demo_position"]
    assert len(fake.submissions) == 1
    store.close()


def test_demo_exit_reduce_only_observed_fees_and_separate_ledger(tmp_path, monkeypatch):
    from quant_lab.forward.store import encode
    from quant_lab.notifications.formatter import format_event
    from quant_lab.notifications.forward_watcher import signal_only

    engine, store = setup(tmp_path)
    now = demo_intent(engine, store)
    clock = [now]
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: clock[0]))
    fake = FakeDemo()
    coordinator = DemoCoordinator(store, fake, RMM_NAMES[0], engine.instruments, engine.inherited)
    coordinator.drain()
    clock[0] += pd.Timedelta(hours=4)
    fake.funded = False  # Entry guard must never prevent a reduceOnly exit.
    engine.ingest(Bar(engine.eth, "4h", now, 50, 51, 49, 50, 1), lambda i, t: (50.0, t))
    coordinator.drain()
    assert len(fake.submissions) == 2 and fake.submissions[-1]["reduceOnly"] is True
    state = store.restore()
    assert state["demo_position"] is None
    assert state["demo_trades"][0]["net_pnl_excluding_funding"] == pytest.approx(-0.2)
    assert state["demo_equity_excluding_funding"] == pytest.approx(9999.8)
    assert engine.equity[RMM_NAMES[0]] != state["demo_equity_excluding_funding"]
    store.report("stopped")
    assert (store.path / "demo_expected_vs_observed.csv").exists()
    assert "OKX DEMO FILLED" in (store.path / "demo_pnl.md").read_text()
    event = next(e for e in store.rows("events") if e["kind"] == "DEMO_ORDER_FILLED")
    message = format_event(event, store.session)
    assert "Mode: OKX DEMO / DEMO_EXECUTION" in message and "Observed fee: -.1 USD" in message
    metadata = {
        "config": {
            "forward": dict(
                data_protocol="rmm_4h",
                mode="demo_execution",
                trading_enabled=True,
                environment="demo",
                broker="okx",
                allow_live_trading=False,
            )
        }
    }
    with store.db:
        store.db.execute("INSERT INTO sessions VALUES (?,?)", ("observer-demo", encode(metadata)))
    assert signal_only(store.db, "observer-demo") is True
    metadata["config"]["forward"]["allow_live_trading"] = True
    with store.db:
        store.db.execute(
            "UPDATE sessions SET data=? WHERE id=?", (encode(metadata), "observer-demo")
        )
    assert signal_only(store.db, "observer-demo") is False
    store.close()


def test_btc_fourth_is_shadow_and_independent(tmp_path):
    engine, store = setup(tmp_path)
    data = [
        Bar(
            engine.config.instruments["BTC"],
            b.timeframe,
            b.timestamp,
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
        )
        for b in bars(engine)
    ]
    engine.bootstrap(data[:1000])
    engine.ingest(data[1000], lambda i, t: (data[1000].close, t))
    signals = store.rows("signals")
    assert {s["strategy"] for s in signals} == set(RMM_NAMES[2:])
    assert next(s for s in signals if s["strategy"] == RMM_NAMES[3])["role"] == "SHADOW_CANDIDATE"
    assert len(engine.shadow.positions) == 2
    assert len({s["signal_id"] for s in signals}) == 2
    store.close()


def test_verification_receipt_checks_operational_stage_and_tampering(tmp_path):
    import json

    from quant_lab.forward.rmm_operations import check_receipt
    from quant_lab.forward.store import encode

    engine, store = setup(tmp_path)
    with store.db:
        for asset in ("ETH", "BTC"):
            store.event("RMM_CANDLE_EVALUATED", asset, {"symbol": asset, "recovering": False})
        store.event("HEARTBEAT", "heartbeat", {})
        store.event(
            "ORDER_INTENT_CREATED",
            "entry",
            dict(
                strategy=RMM_NAMES[0],
                reason="RMM_ENTRY",
                target_quantity=1.0,
                target_notional=100.0,
                estimated_entry_price=100.0,
                stop_price=None,
                contracts="1000",
            ),
        )
    store.metadata["start"] = str(pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=5))
    store.report("stopped")
    code = {"code_sha256": "fixture"}
    with pytest.raises(ValueError, match="Telegram"):
        verify(store.path, engine.config, code)
    receipt = verify(store.path, engine.config, code, telegram_verified=True)
    path = tmp_path / "receipt.json"
    path.write_text(encode(receipt), encoding="utf-8")
    check_receipt(path, engine.config, code, engine.config.instruments)
    receipt["event_sha256"] = "tampered"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        check_receipt(path, engine.config, code, engine.config.instruments)
    store.close()


def test_rmm_quote_rejects_crossed_book_and_uses_midpoint(monkeypatch):
    from quant_lab.market_data.okx import OKXMarketData, QuoteUnavailable

    now = pd.Timestamp("2026-10-04T12:00Z")

    class Quotes:
        bid = "99"

        def server_time(self):
            return int(now.timestamp() * 1000)

        def get(self, *args):
            return [{"ts": str(self.server_time()), "askPx": "101", "bidPx": self.bid}]

    broker = Quotes()
    feed = OKXMarketData(broker, ["ETH"])
    feed.rmm_reference = True
    assert feed.quote("ETH", now)[0] == 100
    broker.bid = "102"
    monkeypatch.setattr("quant_lab.market_data.okx.time.sleep", lambda t: None)
    with pytest.raises(QuoteUnavailable):
        feed.quote("ETH", now)


def test_resampled_history_and_live_group_are_closed_and_contiguous(monkeypatch):
    from quant_lab.market_data.okx import DataGap, OKXMarketData

    now = pd.Timestamp("2026-10-04T12:00Z")
    feed = OKXMarketData(None, ["ETH"])
    feed.required_feeds = {("ETH", "4h")}
    hours = [
        Bar("ETH", "1h", now - pd.Timedelta(hours=12 - i), 100 + i, 102 + i, 99 + i, 101 + i, 1)
        for i in range(12)
    ]

    def history(i, tf, count, since=None):
        if tf == "4h":
            raise DataGap("native gap")
        return hours

    monkeypatch.setattr(feed, "history", history)
    monkeypatch.setattr(feed, "now", lambda: now)
    resampled = feed.rmm_history("ETH", 2)
    assert len(resampled) == 2 and resampled[-1].close_time == now
    assert feed.required_feeds == {("ETH", "1h")}
    for i in range(4):
        b = Bar("ETH", "1h", now + pd.Timedelta(hours=i), 112 + i, 114 + i, 111 + i, 113 + i, 1)
        result = feed.rmm_live_bars(b)
        assert len([r for r in result if r.timeframe == "4h"]) == (1 if i == 3 else 0)
    combined = result[0]
    assert combined.timestamp == now and combined.close_time == now + pd.Timedelta(hours=4)
    assert combined.open == 112 and combined.close == 116
    assert not any(r.timeframe == "4h" for r in feed.rmm_live_bars(b))


def test_insufficient_rmm_history_reports_both_sources_without_relaxing_warmup(monkeypatch):
    from quant_lab.market_data.okx import DataGap, OKXMarketData

    feed = OKXMarketData(None, ["ETH"])
    calls = []

    def insufficient(instrument, timeframe, count, since=None):
        calls.append((timeframe, count))
        raise DataGap(f"Insufficient warmup: required={count}, available=12")

    monkeypatch.setattr(feed, "history", insufficient)
    with pytest.raises(DataGap, match="native 4h:.*required=1000.*hourly fallback:.*required=4004"):
        feed.rmm_history("ETH", 1000)
    assert calls == [("4h", 1000), ("1h", 4004)]
    assert feed.rmm_sources == {} and feed.rmm_hours.bars == {}


def test_warmup_preflight_checks_both_assets_and_fails_without_creating_session(
    monkeypatch, capsys
):
    from quant_lab.forward import rmm_operations
    from quant_lab.market_data.okx import DataGap, OKXMarketData

    monkeypatch.setattr(rmm_operations, "OKXDemoBroker", lambda: object())
    monkeypatch.setattr(
        rmm_operations, "instrument_lookup", lambda *args: ({"ETH": None, "BTC": None}, [])
    )
    checked = []

    def unavailable(self, instrument, count):
        checked.append((instrument, count))
        raise DataGap(f"{instrument}: insufficient history")

    monkeypatch.setattr(OKXMarketData, "rmm_history", unavailable)
    with pytest.raises(SystemExit) as exc:
        rmm_operations.main(["warmup"])
    assert exc.value.code == 1
    assert checked == [("ETH", 1000), ("BTC", 1000)]
    assert "no session, receipt or orders created" in capsys.readouterr().err


BTC_CONFIG = DEFAULT.with_name("okx_demo_rmm_btc_4h.yaml")


@pytest.mark.parametrize(
    "code,expected",
    [("51603", "51603"), ("50110", "50110"), ("private-token", "unknown"), (None, "unknown")],
)
def test_demo_api_diagnostics_expose_numeric_code_only(monkeypatch, code, expected):
    from quant_lab.brokers.okx_execution import DemoAPIError

    for name in ("KEY", "SECRET", "PASSPHRASE"):
        monkeypatch.setenv("OKX_DEMO_API_" + name, "fake")
    broker = OKXDemoExecution(
        request=lambda *_: {"code": code, "msg": "private-message", "data": []}
    )
    with pytest.raises(DemoAPIError) as exc:
        broker.by_client("BTC-test", "rmmtest")
    assert exc.value.code == expected
    assert f"OKX code={expected}" in str(exc.value)
    assert "private" not in str(exc.value)


def test_order_not_found_checks_occupancy_without_clearing_durable_order(
    tmp_path, monkeypatch, capsys
):
    from quant_lab.brokers.okx_execution import DemoAPIError
    from quant_lab.forward import rmm_operations

    engine, store = setup(tmp_path, BTC_CONFIG)
    with store.db:
        store.put(
            "orders",
            "missing-client",
            dict(
                client_id="missing-client",
                instrument_id=engine.config.instruments["BTC"],
                status="SUBMITTING",
                submitted_at="2026-10-05T08:00:01Z",
            ),
        )
    store.report("failed")
    session = store.path
    store.close()
    before = (session.parent / "forward.sqlite").read_bytes()
    queried = []

    class Broker:
        def __init__(self, *, armed):
            assert armed is False

        def by_client(self, *args):
            raise DemoAPIError("GET", "51603")

        def get(self, endpoint, params=None):
            queried.append(endpoint)
            if endpoint == "/api/v5/trade/fills":
                assert params["begin"] == "1791187141000"
                assert params["limit"] == "100"
            if endpoint == "/api/v5/account/config":
                return [dict(perm="read_only", acctLv="2", posMode="net_mode", uid="private-uid")]
            return []

    monkeypatch.setattr("quant_lab.brokers.okx_execution.OKXDemoExecution", Broker)
    with pytest.raises(SystemExit) as exc:
        rmm_operations.main(["order", "--config", str(BTC_CONFIG), "--session", str(session)])
    assert exc.value.code == 1
    assert queried == [
        "/api/v5/account/positions",
        "/api/v5/trade/orders-pending",
        "/api/v5/trade/fills",
        "/api/v5/account/config",
    ]
    assert (session.parent / "forward.sqlite").read_bytes() == before
    output = capsys.readouterr()
    assert "Current positions: []" in output.out and "Pending orders: []" in output.out
    assert '"perm": "read_only"' in output.out and "private-uid" not in output.out
    assert "submission remains uncertain" in output.err


def test_transport_diagnostics_distinguish_get_and_post_without_exposing_secrets(monkeypatch):
    from urllib.error import HTTPError

    for name in ("KEY", "SECRET", "PASSPHRASE"):
        monkeypatch.setenv("OKX_DEMO_API_" + name, "fake")

    def failed(*args):
        raise HTTPError("secret-url", 403, "secret-message", {}, None)

    broker = OKXDemoExecution(request=failed)
    with pytest.raises(RuntimeError, match=r"GET unavailable \(HTTP status 403\)") as exc:
        broker.by_client("BTC-test", "rmmtest")
    assert "secret" not in str(exc.value)


def test_order_diagnostic_is_read_only_and_never_resubmits(tmp_path, monkeypatch, capsys):
    from quant_lab.forward import rmm_operations

    engine, store = setup(tmp_path, BTC_CONFIG)
    with store.db:
        store.put(
            "orders",
            "client-test",
            dict(
                client_id="client-test",
                instrument_id=engine.config.instruments["BTC"],
                status="SUBMITTING",
            ),
        )
    store.report("failed")
    session = store.path
    store.close()
    before = (session / "session.json").read_bytes()
    called = []

    class Broker:
        def __init__(self, *, armed):
            assert armed is False

        def by_client(self, instrument, client):
            called.append((instrument, client))
            return [
                dict(
                    instId=instrument,
                    clOrdId=client,
                    ordId="order-test",
                    state="filled",
                    accFillSz="0.01",
                )
            ]

    monkeypatch.setattr("quant_lab.brokers.okx_execution.OKXDemoExecution", Broker)
    rmm_operations.main(["order", "--config", str(BTC_CONFIG), "--session", str(session)])
    assert called == [(engine.config.instruments["BTC"], "client-test")]
    assert (session / "session.json").read_bytes() == before
    output = capsys.readouterr().out
    assert '"state": "filled"' in output and "journal unchanged" in output


def test_btc_only_config_preserves_frozen_scope_and_rejects_mismatches():
    config, _, output = load_config(BTC_CONFIG)
    assert config.instruments == {"BTC": "AUTO"}
    assert config.strategies == RMM_NAMES[2:]
    assert config.demo_strategy == RMM_NAMES[2]
    assert output.name == "rmm_btc_4h" and config.warmup_bars == 1000
    for change in (
        {"strategies": RMM_NAMES},
        {"demo_strategy": RMM_NAMES[0]},
        {"demo_strategy": RMM_NAMES[3]},
        {"warmup_bars": 902},
        {"instruments": {"ETH": "AUTO"}},
    ):
        with pytest.raises(ValueError):
            type(config).model_validate(config.model_dump() | change)


def test_btc_discovery_never_requires_eth():
    from quant_lab.forward.feeds import instrument_lookup

    config, _, _ = load_config(BTC_CONFIG)

    class Broker:
        def server_time(self):
            return 1000

        def get_instruments(self):
            return [
                dict(
                    instId="BTC-USD_UM_XPERP-310328",
                    ctType="linear",
                    instType="FUTURES",
                    ruleType="xperp",
                    ctVal="1",
                    ctValCcy="BTC",
                    settleCcy="USD",
                    lotSz="0.0001",
                    minSz="0.0001",
                    tickSz="0.1",
                    lever="10",
                    state="live",
                    expTime="1932451200000",
                    ctMult="1",
                )
            ]

    instruments, warnings = instrument_lookup(config, Broker())
    assert list(instruments) == ["BTC-USD_UM_XPERP-310328"] and warnings == []


def test_btc_only_bootstrap_restart_and_verification_keep_safety_gates(tmp_path):
    engine, store = setup(tmp_path, BTC_CONFIG)
    try:
        data = bars(engine)
        engine.bootstrap(data[:1000])
        engine.ingest(data[1000], lambda i, t: (data[1000].close, t))
        assert set(engine.rmm.adapters) == {"BTC"}
        assert {r["strategy"] for r in store.rows("signals")} == set(RMM_NAMES[2:])
        assert not store.rows("orders") and not store.rows("fills")
        restored = ForwardEngine(engine.config, engine.inherited, engine.instruments, store)
        before = store.rows("order_intents")
        restored.ingest(data[1000], lambda *_: pytest.fail("Duplicate requested quote"))
        assert store.rows("order_intents") == before
        with store.db:
            store.event("HEARTBEAT", "btc-heartbeat", {})
        store.report("stopped")
        with pytest.raises(ValueError, match=">=4h"):
            verify(store.path, engine.config, {"code_sha256": "fixture"}, telegram_verified=True)
        store.metadata["start"] = str(pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=5))
        store.report("stopped")
        with pytest.raises(ValueError, match="Telegram"):
            verify(store.path, engine.config, {"code_sha256": "fixture"})
        receipt = verify(
            store.path, engine.config, {"code_sha256": "fixture"}, telegram_verified=True
        )
        assert set(receipt["instruments"]) == {"BTC"}
        joint, _, _ = load_config(DEFAULT)
        with pytest.raises(ValueError):
            verify(store.path, joint, {"code_sha256": "fixture"}, telegram_verified=True)
    finally:
        store.close()


def test_btc_only_runner_bootstraps_without_eth_and_persists_signal_only(tmp_path, monkeypatch):
    import json
    import sqlite3

    from quant_lab.forward import runner

    reference, reference_store = setup(tmp_path / "fixture", BTC_CONFIG)
    data = bars(reference)
    instruments = reference.instruments
    reference_store.close()
    config, _, _ = load_config(BTC_CONFIG)
    output = tmp_path / "btc-runner"
    config_path = tmp_path / "btc-config.yaml"
    config_path.write_text(
        json.dumps(config.model_dump() | {"output": str(output)}), encoding="utf-8"
    )
    monkeypatch.setattr(runner, "OKXDemoBroker", lambda: object())
    monkeypatch.setattr(runner, "instrument_lookup", lambda *_: (instruments, []))
    monkeypatch.setattr(runner, "provenance", lambda *_: {"code_sha256": "btc-runner-fixture"})

    class Feed:
        rmm_sources = {data[0].instrument_id: "native_4h"}

        def __init__(self, broker, requested):
            assert requested == [data[0].instrument_id]

        def history(self, instrument, timeframe, count, since=None):
            assert instrument.startswith("BTC-") and timeframe in {"1h", "15m"}
            return []

        def rmm_history(self, instrument, count, since=None):
            assert instrument.startswith("BTC-") and count == 1000
            return data[:1000]

        def now(self):
            return data[1000].close_time

        def quote(self, instrument, boundary):
            assert instrument.startswith("BTC-")
            return data[1000].close, boundary

        def updates(self):
            yield data[1000]

    monkeypatch.setattr(runner, "OKXMarketData", Feed)
    runner.run(config_path, max_updates=1)
    with sqlite3.connect(output / "forward.sqlite") as db:
        metadata = json.loads(db.execute("SELECT data FROM sessions").fetchone()[0])
        events = [json.loads(row[0]) for row in db.execute("SELECT data FROM events")]
    assert metadata["status"] == "stopped"
    assert set(metadata["config"]["forward"]["instruments"]) == {"BTC"}
    assert metadata["config"]["forward"]["trading_enabled"] is False
    assert any(e["kind"] == "ORDER_INTENT_CREATED" for e in events)
    assert not any(e["kind"] in {"ERROR", "DATA_GAP", "DEMO_ORDER_SUBMITTED"} for e in events)
