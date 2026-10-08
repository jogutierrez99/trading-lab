"""Forward contracts and causality on fixed synthetic candles; never network."""

import base64
import hashlib
import hmac
from decimal import Decimal
from urllib.error import HTTPError, URLError

import numpy as np
import pandas as pd
import pytest

from quant_lab.brokers.base import TradingDisabled
from quant_lab.brokers.instruments import Instrument
from quant_lab.brokers.okx_demo import OKXDemoBroker
from quant_lab.execution_policies.optional_15m_fill import BaselineEntry, OptionalFillPolicy
from quant_lab.forward.config import load_config
from quant_lab.forward.runner import DEFAULT_CONFIG
from quant_lab.forward.store import Store
from quant_lab.forward.strategy import IncrementalTiming, StrategyAdapter
from quant_lab.market_data.okx import CandleBook, DataGap, OKXMarketData, parse_bar
from quant_lab.mtf_execution import prepare


def instrument(asset="ETH", settlement="USDC"):
    return Instrument.parse(
        {
            "instId": f"{asset}-USD_UM_XPERP-310328",
            "instType": "FUTURES",
            "ruleType": "xperp",
            "ctType": "linear",
            "settleCcy": settlement,
            "state": "live",
            "ctValCcy": asset,
            "ctVal": "0.001" if asset == "ETH" else "1",
            "lotSz": "1" if asset == "ETH" else "0.0001",
            "minSz": "1" if asset == "ETH" else "0.0001",
            "tickSz": "0.01" if asset == "ETH" else "0.1",
            "lever": "10",
        }
    )


def test_transport_identifies_client_and_preserves_demo_header(monkeypatch):
    from io import BytesIO

    from quant_lab.brokers import okx_demo

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://eea.okx.com/api/v5/public/time"
            assert request.get_method() == "GET"
            headers = {key.lower(): value for key, value in request.header_items()}
            assert headers["user-agent"] == okx_demo.USER_AGENT
            assert headers["accept"] == "application/json"
            assert headers["x-simulated-trading"] == "1"
            return BytesIO(b'{"code":"0","data":[]}')

    monkeypatch.setattr(okx_demo, "build_opener", lambda handler: Opener())
    assert okx_demo.transport("/api/v5/public/time", {"x-simulated-trading": "1"})["code"] == "0"


def candles(n=290):
    rng = np.random.default_rng(24)
    close = 100 + np.arange(n) * 0.1 + np.sin(np.arange(n) / 3) * 2
    opening = close + rng.normal(0, 0.4, n)
    return pd.DataFrame(
        {
            "open": opening,
            "high": np.maximum(opening, close) + 0.1,
            "low": np.minimum(opening, close) - 2,
            "close": close,
            "volume": 100.0,
        },
        index=pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC"),
    )


@pytest.mark.parametrize(
    "error",
    [URLError("private details"), TimeoutError("private details"), OSError("private details")],
)
def test_readonly_transport_failure_is_recoverable_and_sanitized(error):
    def request(*_):
        raise error

    with pytest.raises(ConnectionError, match="OKX read-only transport failed") as caught:
        OKXDemoBroker(request=request).server_time()
    assert "private details" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("private url", 403, "private details", {}, None),
        ValueError("private details"),
        RuntimeError("OKX redirect refused"),
    ],
)
def test_readonly_non_connection_failure_remains_fatal(error):
    def request(*_):
        raise error

    with pytest.raises(RuntimeError) as caught:
        OKXDemoBroker(request=request).server_time()
    assert not isinstance(caught.value, ConnectionError)
    assert "private" not in str(caught.value)


def test_expired_okx_clock_blocks_until_successful_refresh(monkeypatch):
    from quant_lab.market_data import okx

    monotonic = [100.0]
    monkeypatch.setattr(okx.time, "monotonic", lambda: monotonic[0])
    stamp = pd.Timestamp("2026-01-01", tz="UTC")
    responses = [stamp, URLError("private details"), stamp + pd.Timedelta(seconds=40)]

    def request(*_):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return {"code": "0", "data": [{"ts": str(response.value // 1000000)}]}

    feed = OKXMarketData(OKXDemoBroker(request=request), [])
    assert feed.now() == stamp
    monotonic[0] += 31
    with pytest.raises(ConnectionError):
        feed.now()
    assert feed._clock == stamp and feed._clock_at == 100.0
    assert feed.now() == stamp + pd.Timedelta(seconds=40)


def test_contracts_round_down_and_never_use_max_leverage():
    eth, btc = instrument(), instrument("BTC")
    assert eth.convert(3000, target_notional=100)["contracts_rounded"] == "33"
    assert btc.convert(100000, target_quantity="0.123456")["contracts_rounded"] == "0.1234"
    assert eth.round_price("100.019") == Decimal("100.01")
    assert eth.round_price("100.011", upward=True) == Decimal("100.02")
    for kwargs in (
        {"target_notional": 1},
        {"target_notional": 100, "leverage": 10},
        {"target_quantity": float("nan")},
        {"target_notional": 100, "target_quantity": 1},
    ):
        with pytest.raises(ValueError):
            eth.convert(3000, **kwargs)


def test_instrument_rejects_wrong_currency_and_inactive():
    with pytest.raises(ValueError):
        Instrument.parse({"instId": "ETH-USDT", "instType": "SWAP"})


def test_instrument_preserves_observed_settlement_without_currency_equivalence():
    assert instrument(settlement="USD").settlement_currency == "USD"
    assert instrument(settlement="USDC").settlement_currency == "USDC"
    with pytest.raises(ValueError, match="settlement"):
        instrument(settlement="USDT")


def test_demo_auth_is_signed_get_only_and_no_mutations(monkeypatch):
    for name, value in (
        ("OKX_API_KEY", "fake-key"),
        ("OKX_API_SECRET", "fake-secret"),
        ("OKX_API_PASSPHRASE", "fake-pass"),
    ):
        monkeypatch.setenv(name, value)
    calls = []

    def request(path, headers):
        calls.append((path, headers))
        return {"code": "0", "data": []}

    broker = OKXDemoBroker(request)
    broker.get_order("ETH", "123")
    path, headers = calls[0]
    signature = base64.b64encode(
        hmac.new(
            b"fake-secret", (headers["OK-ACCESS-TIMESTAMP"] + "GET" + path).encode(), hashlib.sha256
        ).digest()
    ).decode()
    assert headers["OK-ACCESS-SIGN"] == signature
    assert headers["x-simulated-trading"] == "1"
    for method in (broker.place_order, broker.cancel_order, broker.close_position):
        with pytest.raises(TradingDisabled):
            method("ignored")
    with pytest.raises(ValueError):
        broker.get("/api/v5/asset/transfer")
    assert len(calls) == 1
    monkeypatch.setenv("TRADING_ENABLED", "true")
    with pytest.raises(ValueError):
        broker.get_balance()


def raw_bar(stamp, confirmed="1"):
    return [str(stamp.value // 1000000), "100", "102", "99", "101", "5000", "5", "505", confirmed]


def test_closed_candles_duplicates_gaps_and_future():
    stamp = pd.Timestamp("2026-01-01", tz="UTC")
    now = stamp + pd.Timedelta(hours=1)
    assert parse_bar("ETH", "1h", raw_bar(stamp, "0"), now) is None
    with pytest.raises(ValueError):
        parse_bar("ETH", "1h", raw_bar(stamp), stamp)
    book = CandleBook()
    bar = parse_bar("ETH", "1h", raw_bar(stamp), now)
    assert bar.volume == 5
    assert book.add(bar) and not book.add(bar)
    with pytest.raises(DataGap):
        book.add(
            parse_bar(
                "ETH", "1h", raw_bar(stamp + pd.Timedelta(hours=2)), now + pd.Timedelta(hours=2)
            )
        )


def test_signal_parity_original_historical_prepare_and_incremental():
    _, settings, _ = load_config(DEFAULT_CONFIG)
    adapter = StrategyAdapter(settings.risk)
    frame = candles()
    dataset = {"frames": {"1h": frame}, "mark": frame, "funding": pd.DataFrame(index=frame.index)}
    historical = prepare(dataset, adapter.strategy.config)[0][3]
    actual = []
    for i in range(200, len(frame)):
        boundary = frame.index[i] + pd.Timedelta(hours=1)
        signal, row = adapter.evaluate(frame.iloc[: i + 1], boundary)
        actual.append(signal)
        assert row.risk_atr == pytest.approx(
            adapter.strategy.prepare_features(frame).risk_atr.iloc[i]
        )
        # An appended unclosed hour cannot affect a decision.
        assert adapter.evaluate(frame.iloc[: i + 2], boundary)[0] == signal
    assert any(actual)
    assert actual == historical["le"].iloc[200:].tolist()


@pytest.mark.parametrize("price,expected", [(99.0, 1), (105.0, 4)])
def test_incremental_optional_policy_exact_parity_and_restore(price, expected):
    _, inherited, _ = load_config(DEFAULT_CONFIG)
    costs = inherited.costs["zero"]
    times = pd.date_range("2026-01-01", periods=6, freq="15min", tz="UTC")
    entry = BaselineEntry("base", "signal", times[0], times[0], 100, 2, 4, 90, 90)
    rows = pd.DataFrame(
        {"open": 98, "high": 101, "low": 97, "close": 100, "ema20": 99}, index=times
    )
    historical = OptionalFillPolicy(
        rows,
        [entry],
        times[0] - pd.Timedelta(minutes=15),
        times[-1] + pd.Timedelta(minutes=15),
        "trend_pullback",
        costs,
    )
    incremental = IncrementalTiming(costs)
    incremental.add(entry)
    for i, time in enumerate(times[: expected + 1]):
        a = historical.decision(time, price, False)
        b = incremental.decision(time, price, rows.loc[time].to_dict(), False)
        assert a == b
        if i == 0:
            import json

            restored = IncrementalTiming(costs)
            restored.restore(json.loads(json.dumps(incremental.snapshot(), default=str)))
            incremental = restored
        if a:
            historical.on_entry(time, price)
            incremental.policy.on_entry(time, price)
    assert historical.records == incremental.policy.records
    assert historical.records[0]["status"] == "ENTERED"


def test_rest_recovery_pagination_and_continuity():
    times = pd.date_range("2026-01-01", periods=5, freq="1h", tz="UTC")

    class Fake:
        def server_time(self):
            return int((times[-1] + pd.Timedelta(hours=1)).value // 1000000)

        def get(self, endpoint, params):
            return [raw_bar(t) for t in (times[:3] if "after" in params else times[3:])][::-1]

    data = OKXMarketData(Fake(), ["ETH"])
    assert len(data.history("ETH", "1h", 5, since=times[0])) == 5

    class Gap(Fake):
        def get(self, endpoint, params):
            return [raw_bar(t) for t in times if t != times[2]][::-1]

    with pytest.raises(DataGap):
        OKXMarketData(Gap(), ["ETH"]).history("ETH", "1h", 4)


def test_old_unconfirmed_candle_is_a_gap_with_actionable_details():
    times = pd.date_range("2026-07-02", periods=6, freq="4h", tz="UTC")

    class Broker:
        def server_time(self):
            return int((times[-1] + pd.Timedelta(hours=4)).value // 1000000)

        def get(self, endpoint, params):
            return [raw_bar(t, "0" if t == times[1] else "1") for t in reversed(times)]

    with pytest.raises(DataGap, match="ETH 4h.*2026-07-02T04:00:00.*confirm=0"):
        OKXMarketData(Broker(), ["ETH"]).history("ETH", "4h", 5)


def test_store_transactions_restart_and_dedup(tmp_path):
    store = Store(tmp_path, {}, {"code_sha256": "test"})
    with store.db:
        store.event("SIGNAL_GENERATED", "stable", {"signal": True})
        store.checkpoint({"pending": True})
    with pytest.raises(RuntimeError), store.db:
        store.event("SIGNAL_GENERATED", "rollback", {"signal": True})
        raise RuntimeError("crash before checkpoint")
    store.close()
    store = Store(tmp_path, {}, {"code_sha256": "test"})
    with store.db:
        store.event("SIGNAL_GENERATED", "stable", {"signal": True})
    assert len(store.rows("signals")) == 1
    assert store.restore() == {"pending": True}
    with pytest.raises(ValueError):
        store.event("SIGNAL_GENERATED", "stable", {"signal": False})
    store.close()


@pytest.mark.parametrize("timeframe", ["15m", "1h", "4h"])
def test_closed_availability_all_timeframes(timeframe):
    from quant_lab.mtf_features import STEPS

    stamp = pd.Timestamp("2026-01-01", tz="UTC")
    with pytest.raises(ValueError):
        parse_bar(
            "ETH", timeframe, raw_bar(stamp), stamp + STEPS[timeframe] - pd.Timedelta(seconds=1)
        )
    assert parse_bar("ETH", timeframe, raw_bar(stamp), stamp + STEPS[timeframe]) is not None

    class Broker:
        def server_time(self):
            return int((stamp + STEPS[timeframe]).value // 1000000)

        def get(self, endpoint, params):
            return [raw_bar(stamp)]

    # REST rounding must use fixed Timedelta, not pandas' ambiguous '15m' month alias.
    assert len(OKXMarketData(Broker(), ["ETH"]).history("ETH", timeframe, 1)) == 1


def test_websocket_demo_subscription_incomplete_filter_and_reconnect(monkeypatch):
    import json

    client = pytest.importorskip("websockets.sync.client")
    from websockets.exceptions import ConnectionClosedError

    from quant_lab.brokers.okx_demo import WS_URL

    stamp = pd.Timestamp("2026-01-01", tz="UTC")
    messages = [
        {"arg": {"channel": "candle15m", "instId": "ETH"}, "data": [raw_bar(stamp, "0")]},
        {"arg": {"channel": "candle15m", "instId": "ETH"}, "data": [raw_bar(stamp)]},
    ]
    sent, connections = [], []

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, data):
            sent.append(json.loads(data))

        def recv(self, timeout):
            if messages:
                return json.dumps(messages.pop(0))
            raise ConnectionClosedError(None, None)

    def connect(url, **kwargs):
        connections.append(url)
        return Socket()

    class Broker:
        def server_time(self):
            return int((stamp + pd.Timedelta(minutes=15)).value // 1000000)

    monkeypatch.setattr(client, "connect", connect)
    feed = OKXMarketData(Broker(), ["ETH"])
    stream = feed.updates()
    assert next(stream) is None
    assert next(stream).close_time == stamp + pd.Timedelta(minutes=15)
    assert next(stream) is None
    with pytest.raises(ConnectionError):
        next(stream)
    with pytest.raises(ConnectionError):
        next(feed.updates())
    assert connections == [WS_URL, WS_URL]
    assert len(sent[0]["args"]) == 3


def test_websocket_optional_bad_candle_is_warning_required_is_fatal(monkeypatch):
    import json

    client = pytest.importorskip("websockets.sync.client")
    from quant_lab.market_data.okx import FeedIssue

    stamp = pd.Timestamp("2026-01-01", tz="UTC")
    raw = raw_bar(stamp)
    raw[2] = "1"  # high below open: must never enter any candle book

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, _):
            pass

        def recv(self, **kwargs):
            return json.dumps({"arg": {"channel": "candle4H", "instId": "ETH"}, "data": [raw]})

    class Broker:
        def server_time(self):
            return int((stamp + pd.Timedelta(hours=4)).value // 1000000)

    monkeypatch.setattr(client, "connect", lambda *a, **kw: Socket())
    feed = OKXMarketData(Broker(), ["ETH"])
    feed.required_feeds = {("ETH", "1h"), ("ETH", "15m")}
    stream = feed.updates()
    assert isinstance(next(stream), FeedIssue)
    stream.close()
    feed.required_feeds.add(("ETH", "4h"))
    with pytest.raises(ValueError, match="OHLCV"):
        next(feed.updates())


def test_optional_instrument_metadata_does_not_reset_stream(tmp_path):
    config, _, _ = load_config(DEFAULT_CONFIG)
    resolved = {
        "forward": config.model_dump(mode="json"),
        "instruments": {
            config.instruments["ETH"]: {"ctVal": "0.001"},
            config.instruments["BTC"]: {"ctVal": "1"},
        },
    }
    store = Store(tmp_path, resolved, {"code_sha256": "test"})
    stream = store.stream
    with store.db:
        store.checkpoint({"must_survive": True})
    store.close()
    resolved["instruments"].pop(config.instruments["BTC"])
    store = Store(tmp_path, resolved, {"code_sha256": "test"})
    assert store.stream == stream
    assert store.restore() == {"must_survive": True}
    store.close()
