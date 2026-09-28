"""Disconnected-feed incidents: durable evidence, restart and fail-closed decisions."""

from dataclasses import replace

import pandas as pd
import pytest
from test_forward_runner import fixture_bars, setup

from quant_lab.forward.engine import ForwardEngine
from quant_lab.forward.recovery import audit, detect, recover_incidents
from quant_lab.forward.store import Store
from quant_lab.market_data.okx import DataGap
from quant_lab.mtf_features import STEPS


class Feed:
    def __init__(self, engine, hours, quarters, now):
        self.engine, self.hours, self.quarters, self.clock = engine, hours, quarters, now
        self.missing = set()
        self.duplicate = False
        self.conflict = False
        self.reverse = False
        self.partial_error = False
        self.calls = []

    def now(self):
        return self.clock

    def history(self, inst, tf, count, *, since=None):
        self.calls.append((inst, tf, since))
        if not self.engine.config.required_feed(inst, tf):
            raise DataGap("optional monitoring unavailable")
        source = self.hours if tf == "1h" else self.quarters
        rows = [
            b
            for b in source
            if b.close_time <= self.clock
            and b.key not in self.missing
            and (since is None or b.timestamp >= since)
        ]
        if since is None:
            rows = rows[-count:]
        if self.duplicate and rows:
            rows.append(replace(rows[-1], volume=999) if self.conflict else rows[-1])
        if self.reverse:
            rows.reverse()
        if self.partial_error and self.missing:
            raise DataGap("partial REST response", bars=rows)
        return rows

    def quote(self, *_):
        pytest.fail("Recovery/blocked signal must never obtain an entry quote")


def prepared(tmp_path):
    engine, store = setup(tmp_path)
    hours, quarters = fixture_bars(engine)
    engine.bootstrap(hours[:250] + quarters[:1000])
    feed = Feed(engine, hours, quarters, hours[250].timestamp)
    return engine, store, feed


def test_disconnect_without_lost_candle_and_idempotency(tmp_path):
    engine, store, feed = prepared(tmp_path)
    detect(engine, "ConnectionError", now=feed.now())
    detect(engine, "ConnectionError", now=feed.now())
    before = store.rows("bars")
    assert recover_incidents(engine, feed)
    first = store.rows("events")
    assert recover_incidents(engine, feed)
    assert store.rows("events") == first
    assert store.rows("bars") == before
    (gap,) = store.gaps()
    assert gap["resolved"] and gap["continuity_verified"]
    assert gap["recovered_bars"] == 0
    assert gap["resolution"] == "REST_CONTINUITY_VERIFIED"
    assert gap["resolved_at"]
    for kind in ("DATA_GAP", "RECONNECTED", "DATA_GAP_RESOLVED"):
        assert sum(e["kind"] == kind for e in first) == 1
    store.report("stopped")
    text = (store.path / "ai_summary.md").read_text(encoding="utf-8")
    assert '"data_gaps_unresolved": 0' in text
    assert text.endswith("## Readiness\n\nNEEDS_REVIEW\n")
    store.close()


def test_one_lost_candle_is_persisted_audited_and_not_traded(tmp_path):
    engine, store, feed = prepared(tmp_path)
    detect(engine, "ConnectionError", now=feed.now())
    feed.clock += STEPS["15m"]
    assert recover_incidents(engine, feed)
    (gap,) = store.gaps()
    assert gap["recovered_bars"] == 1
    assert len(store.rows("bars")) == 1251
    assert all(a["continuity_ok"] for a in gap["audits"])
    assert not store.rows("signals") and not store.rows("order_intents")
    for bar in feed.quarters[1001:1100]:
        engine.ingest(bar, lambda inst, t, b=bar: (b.close, t + pd.Timedelta(seconds=1)))
    assert store.rows("signals") and store.rows("order_intents")
    store.close()


def test_incomplete_recovery_blocks_signals_and_readiness_then_resolves(tmp_path):
    engine, store, feed = prepared(tmp_path)
    detect(engine, "ConnectionError", now=feed.now())
    feed.clock += 2 * STEPS["15m"]
    missed = feed.quarters[1000]
    feed.missing.add(missed.key)
    feed.partial_error = True
    assert not recover_incidents(engine, feed)
    engine.ingest(feed.quarters[1001], feed.quote)
    (gap,) = store.gaps()
    assert not gap["resolved"] and gap["resolution"] == "RECOVERY_INCOMPLETE"
    assert any(m["timestamp"] == missed.timestamp.isoformat() for m in gap["missing_timestamps"])
    assert any(e["kind"] == "SIGNAL_BLOCKED_DATA_GAP" for e in store.rows("events"))
    assert len(store.rows("recovery_bars")) == 1  # real later candle, not a made-up fill
    assert not store.rows("signals")
    store.report("running")
    assert "BLOCK_DEMO_EXECUTION" in (store.path / "summary.md").read_text(encoding="utf-8")
    feed.missing.clear()
    assert recover_incidents(engine, feed)
    assert store.gaps()[0]["recovered_bars"] == 2
    store.report("stopped")
    assert "BLOCK_DEMO_EXECUTION" not in (store.path / "summary.md").read_text(encoding="utf-8")
    store.close()


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_recovery_is_deduplicated_or_fails_explicitly(tmp_path, conflict):
    engine, store, feed = prepared(tmp_path)
    detect(engine, "ConnectionError", now=feed.now())
    feed.clock += STEPS["15m"]
    feed.duplicate, feed.conflict = True, conflict
    assert recover_incidents(engine, feed) is not conflict
    (gap,) = store.gaps()
    if conflict:
        assert any(a.get("error") == "conflicting_duplicate" for a in gap["audits"])
    else:
        assert len(store.rows("bars")) == 1251
        assert gap["recovered_bars"] == 1
    store.close()


@pytest.mark.parametrize("upgrade,legacy", [(False, False), (True, False), (True, True)])
def test_restart_recovers_prior_incident_even_after_code_upgrade(tmp_path, upgrade, legacy):
    engine, store, feed = prepared(tmp_path)
    if legacy:
        with store.db:
            store.event(
                "DATA_GAP", "old-connection-error", {"reason": "ConnectionError", "resolved": False}
            )
            store.event("RECONNECTED", "old-reconnected", {"continuity": "REST_verified"})
    else:
        detect(engine, "ConnectionError", now=feed.now())
    original_gap = store.gaps()[0]
    store.report("stopped")
    old_report = (store.path / "ai_summary.md").read_bytes()
    old_path = store.path
    config, inherited, instruments = engine.config, engine.inherited, engine.instruments
    store.close()
    store = Store(
        tmp_path,
        {"forward": config.model_dump(mode="json")},
        {"code_sha256": "upgraded" if upgrade else "test"},
    )
    engine = ForwardEngine(config, inherited, instruments, store)
    assert store.gaps(unresolved=True)[0]["event_id"] == original_gap["event_id"]
    feed.clock += STEPS["15m"]
    assert recover_incidents(engine, feed)
    assert not store.gaps(unresolved=True)
    assert store.gaps()[0]["source_session"] == original_gap["source_session"]
    assert old_path.joinpath("ai_summary.md").read_bytes() == old_report
    reconnects = [
        r
        for source in {original_gap["source_stream"], store.stream}
        for r in store.source_bars(source, "events")
        if r["kind"] == "RECONNECTED"
    ]
    assert len(reconnects) == 1
    assert not store.rows("signals") and not store.rows("order_intents")
    store.report("stopped")
    assert '"data_gaps_resolved": 1' in store.path.joinpath("ai_summary.md").read_text(
        encoding="utf-8"
    )
    store.close()


@pytest.mark.parametrize("tf", ["15m", "1h", "4h"])
def test_audit_explicit_bounds_duplicates_and_order(tf):
    start = pd.Timestamp("2026-01-01", tz="UTC")
    end = start + 2 * STEPS[tf]
    a = audit("ETH", tf, [start, end], start, end)
    assert not a["continuity_ok"] and a["bars_expected"] == 3
    assert a["missing_timestamps"] == [(start + STEPS[tf]).isoformat()]
    a = audit("BTC", tf, [end, start, start], start, end)
    assert a["duplicates"] == 1 and a["out_of_order"]


def test_out_of_order_rest_never_silently_certifies(tmp_path):
    engine, store, feed = prepared(tmp_path)
    detect(engine, "ConnectionError", now=feed.now())
    feed.clock += STEPS["15m"]
    feed.reverse = True
    assert not recover_incidents(engine, feed)
    assert any(a["out_of_order"] for a in store.gaps()[0]["audits"])
    store.close()


def test_resolved_gap_does_not_override_unrelated_error(tmp_path):
    engine, store, feed = prepared(tmp_path)
    detect(engine, "ConnectionError", now=feed.now())
    assert recover_incidents(engine, feed)
    with store.db:
        store.event("ERROR", "unrelated", {"message": "other required check failed"})
    store.report("stopped")
    text = (store.path / "ai_summary.md").read_text(encoding="utf-8")
    assert '"data_gaps_unresolved": 0' in text and text.endswith("BLOCK_DEMO_EXECUTION\n")
    store.close()


def test_partial_staging_survives_restart_with_code_upgrade(tmp_path):
    engine, store, feed = prepared(tmp_path)
    detect(engine, "ConnectionError", now=feed.now())
    feed.clock += 2 * STEPS["15m"]
    feed.missing.add(feed.quarters[1000].key)
    assert not recover_incidents(engine, feed)
    assert store.gaps()[0]["recovered_bars"] == 1
    config, inherited, instruments = engine.config, engine.inherited, engine.instruments
    store.close()
    store = Store(
        tmp_path, {"forward": config.model_dump(mode="json")}, {"code_sha256": "updated-again"}
    )
    engine = ForwardEngine(config, inherited, instruments, store)
    feed.missing.clear()
    assert recover_incidents(engine, feed)
    assert store.gaps()[0]["recovered_bars"] == 2
    store.close()
