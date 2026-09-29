"""Bounded quote retry and durable nonexecution without stopping the forward loop."""

import pandas as pd
import pytest
from test_forward_runner import fixture_bars, setup

from quant_lab.forward.engine import ForwardEngine
from quant_lab.market_data.okx import OKXMarketData, QuoteUnavailable


def ticker(stamp, price="100"):
    return {"ts": str(stamp.value // 1000000), "askPx": price}


def feed_with(monkeypatch, rows, clocks):
    calls = []

    class Broker:
        def get(self, *_):
            calls.append(True)
            return rows.pop(0) if len(rows) > 1 else rows[0]

    feed = OKXMarketData(Broker(), ["ETH"])
    monkeypatch.setattr(feed, "now", lambda: clocks.pop(0) if len(clocks) > 1 else clocks[0])
    monkeypatch.setattr("quant_lab.market_data.okx.time.sleep", lambda _: None)
    return feed, calls


def test_pre_signal_then_valid_quote(monkeypatch):
    t = pd.Timestamp("2026-01-01", tz="UTC")
    feed, calls = feed_with(monkeypatch, [[ticker(t - pd.Timedelta(seconds=1))], [ticker(t)]], [t])
    assert feed.quote("ETH", t) == (100, t)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "offset,price,reason",
    [
        (-1, "100", "pre_signal_quote"),
        (10, "100", "future_quote"),
        (0, "0", "invalid_ask"),
        (0, "nan", "invalid_ask"),
        (0, "", "malformed_quote"),
    ],
)
def test_bad_quotes_exhaust_bounded_retries(monkeypatch, offset, price, reason):
    t = pd.Timestamp("2026-01-01", tz="UTC")
    feed, calls = feed_with(monkeypatch, [[ticker(t + pd.Timedelta(seconds=offset), price)]], [t])
    with pytest.raises(QuoteUnavailable) as error:
        feed.quote("ETH", t)
    assert error.value.details["reason"] == reason
    assert error.value.details["attempts"] == len(calls) == 3


def test_future_quote_requires_clock_refresh(monkeypatch):
    t = pd.Timestamp("2026-01-01", tz="UTC")
    observed = t + pd.Timedelta(seconds=1)
    feed, calls = feed_with(monkeypatch, [[ticker(observed)]], [t, observed])
    assert feed.quote("ETH", t) == (100, observed)
    assert len(calls) == 1


def test_retry_cannot_cross_decision_deadline(monkeypatch):
    t = pd.Timestamp("2026-01-01", tz="UTC")
    feed, calls = feed_with(
        monkeypatch,
        [[ticker(t)], [ticker(t + pd.Timedelta(seconds=91))]],
        [t + pd.Timedelta(seconds=89), t + pd.Timedelta(seconds=91)],
    )
    with pytest.raises(QuoteUnavailable, match="outside_decision_window"):
        feed.quote("ETH", t)
    assert len(calls) == 2


@pytest.mark.parametrize("empty", [[], [{}]])
def test_empty_or_malformed_response_is_unavailable(monkeypatch, empty):
    t = pd.Timestamp("2026-01-01", tz="UTC")
    feed, calls = feed_with(monkeypatch, [empty], [t])
    with pytest.raises(QuoteUnavailable, match="malformed_quote"):
        feed.quote("ETH", t)
    assert len(calls) == 3


def test_unavailable_quote_preserves_signal_and_bar_then_continues(tmp_path):
    engine, store = setup(tmp_path)
    hours, quarters = fixture_bars(engine)
    engine.bootstrap(hours[:250] + quarters[:1000])

    def unavailable(inst, boundary):
        raise QuoteUnavailable(
            {
                "reason": "pre_signal_quote",
                "instrument": inst,
                "decision_close": boundary,
                "attempts": 3,
            }
        )

    failed_bar = None
    for bar in quarters[1000:1100]:
        engine.ingest(bar, unavailable)
        if store.rows("signals"):
            failed_bar = bar
            break
    assert failed_bar is not None
    assert not store.rows("order_intents")
    assert any(e["kind"] == "QUOTE_UNAVAILABLE" for e in store.rows("events"))
    before = store.rows("signals")
    engine = ForwardEngine(engine.config, engine.inherited, engine.instruments, store)
    engine.ingest(failed_bar, lambda *_: pytest.fail("Duplicate decision must not request quote"))
    assert store.rows("signals") == before
    for bar in quarters:
        if failed_bar.timestamp < bar.timestamp < quarters[1150].timestamp:
            engine.ingest(bar, lambda inst, t, b=bar: (b.close, t + pd.Timedelta(seconds=1)))
    assert store.rows("order_intents")
    store.report("stopped")
    assert (store.path / "quote_events.csv").exists()
    assert (store.path / "ai_summary.md").read_text(encoding="utf-8").endswith("NEEDS_REVIEW\n")
    store.close()


def test_pending_timing_is_explicitly_cancelled_without_quote(tmp_path):
    engine, store = setup(tmp_path)
    hours, quarters = fixture_bars(engine)
    engine.bootstrap(hours[:250] + quarters[:1000])
    for _index, bar in enumerate(quarters[1000:], 1000):
        engine.ingest(bar, lambda inst, t, b=bar: (b.close, t + pd.Timedelta(seconds=1)))
        if engine.timing.policy.pending:
            break
    assert engine.timing.policy.pending
    intents = store.rows("order_intents")

    def unavailable(*_):
        raise QuoteUnavailable({"reason": "stale_quote"})

    engine.ingest(quarters[_index + 1], unavailable)
    assert not engine.timing.policy.pending
    assert store.rows("order_intents") == intents
    assert any(
        e["kind"] == "TIMING_NOT_EXECUTED" and e["reason"] == "quote_unavailable"
        for e in store.rows("events")
    )
    store.close()
