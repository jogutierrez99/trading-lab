"""Offline Donchian acceptance; real sessions/network never used as fixtures."""

import json
from decimal import Decimal

import pandas as pd
import pytest
import yaml
from test_trend_volatility_breakout_v1 import candles

from quant_lab.brokers.instruments import Instrument
from quant_lab.forward.donchian import DonchianEngine, DonchianStore, inspect
from quant_lab.forward.donchian_config import (
    DEFAULT,
    IDS,
    execution,
    frozen_context,
    load,
    resolved,
)
from quant_lab.forward.donchian_runner import PublicBroker, main
from quant_lab.forward.store import Store
from quant_lab.market_data.okx import Bar, DataGap
from quant_lab.notifications.donchian_watcher import poll
from quant_lab.risk import size_entry


@pytest.fixture(scope="module")
def context():
    return frozen_context()


@pytest.fixture
def env(tmp_path, context):
    inst = Instrument(
        "ETH-USD_UM_XPERP-310328",
        "ETH",
        Decimal(".001"),
        Decimal("1"),
        Decimal("1"),
        Decimal(".01"),
        Decimal("10"),
        "USD",
    )
    scope = resolved(load()[0], inst, {}, context)
    store = DonchianStore(tmp_path / "eth", scope, dict(code_sha256="fixture"))
    frame = candles(short=True, n=1001)
    frame.index = pd.date_range("2026-10-09", periods=1001, freq="h", tz="UTC")
    bars = [Bar(inst.instrument_id, "1h", t, **r.to_dict()) for t, r in frame.iterrows()]
    engine = DonchianEngine(
        store,
        context[1],
        context[2],
        execution(inst, context[3]),
        inst.instrument_id,
        "2026-10-09T00:00Z",
        bars[999].close_time,
    )
    engine.bootstrap(bars[:1000], bars[999].close_time)
    yield engine, bars, tmp_path, scope
    store.close()


def signal(engine, bars):
    engine.closed(bars[-1], bars[-1].close_time + pd.Timedelta(seconds=1))
    assert set(engine.state["pending"]) == set(IDS)
    return bars[-1].close_time


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "live"),
        ("mode", "demo_execution"),
        ("direction", "LONG_ONLY"),
        ("symbol", "BTCUSDT"),
        ("trading_enabled", True),
        ("send_orders", True),
        ("allow_live_trading", True),
        ("warmup_bars", 50),
        ("candidates", IDS[:5]),
        ("parameters", {"breakout_length": 999}),
        ("output", "../../results/forward/rmm_btc_4h"),
    ],
)
def test_unsafe_config_rejected(field, value, tmp_path):
    raw = yaml.safe_load(DEFAULT.read_text()) | {field: value}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError):
        load(path)


@pytest.mark.parametrize("reason", ["stop", "target", "stop_gap"])
def test_economics_twelve_accounts_protective_fills_and_no_duplicates(env, reason):
    e, bars, root, _ = env
    stamp = signal(e, bars)
    price = bars[-1].close
    e.opening(stamp, price, stamp + pd.Timedelta(seconds=2), volume=1)
    positions = {k: a["position"].copy() for k, a in e.state["accounts"].items()}
    for key, p in positions.items():
        name, scenario = key.split("|")
        s, r = e.candidates[name]
        distance = float(s.prepare_features(e.book.frame(e.instrument, "1h")).atr.iloc[-1]) * 2
        expected = size_entry(10000, price, distance, -1, r, e.execution, e.costs[scenario])
        assert p["quantity"] == expected.quantity and p["price"] == expected.price
        assert p["price"] - p["target"] == pytest.approx(2 * (p["stop"] - p["price"]))
        assert p["expected_stop_loss"] <= 100
        assert p["quantity"] * p["price"] * (1 + e.costs[scenario].fee) <= 2500
    assert positions[IDS[0] + "|base"]["quantity"] != positions[IDS[0] + "|adverse"]["quantity"]
    e.opening(stamp, price, stamp + pd.Timedelta(seconds=3), volume=1)
    assert len([v for v in e.store.rows("events") if v["kind"] == "SHADOW_ENTRY"]) == 12
    high = max(p["stop"] for p in positions.values()) + 1
    low = min(p["target"] for p in positions.values()) - 1
    opening = high + 2 if reason == "stop_gap" else price
    bar = Bar(
        e.instrument,
        "1h",
        stamp,
        opening,
        opening + 0.1 if reason == "stop_gap" else high if reason == "stop" else price + 0.1,
        opening - 0.1 if reason == "stop_gap" else low,
        opening,
        10,
    )
    e.closed(bar, bar.close_time)
    exits = [v for v in e.store.rows("events") if v["kind"] == "SHADOW_EXIT"]
    assert len(exits) == 12 and all(v["reason"] == reason for v in exits)
    for v in exits:
        key = v["candidate"] + "|" + v["scenario"]
        assert v["price_pnl_gross"] - v["slippage"] - v["spread"] - v["entry_fee"] - v[
            "exit_fee"
        ] == pytest.approx(v["net_pnl"])
        assert e.state["accounts"][key]["balance"] == pytest.approx(10000 + v["net_pnl"])
        assert (v["exit_time"] is not None) == (reason == "stop_gap")
        if reason == "stop":
            assert -v["net_pnl"] == pytest.approx(positions[key]["expected_stop_loss"])
    e.closed(bar, bar.close_time)
    assert len([v for v in e.store.rows("events") if v["kind"] == "SHADOW_EXIT"]) == 12
    assert (
        inspect(root / "eth/forward.sqlite", e.store.session)["state"]["effective_start"]
        == stamp.isoformat()
    )


@pytest.mark.parametrize("reason", ["late", "gap", "missing"])
def test_missed_open_no_retroactive_trade(env, reason):
    e, bars, _, _ = env
    stamp = signal(e, bars)
    price = bars[-1].close
    if reason == "late":
        e.opening(stamp, price, stamp + pd.Timedelta(seconds=91), volume=1)
    elif reason == "gap":
        e.gap("missing", stamp)
    else:
        e.closed(
            Bar(e.instrument, "1h", stamp, price, price + 0.1, price - 0.1, price, 1),
            stamp + pd.Timedelta(hours=1),
        )
    assert not any(a["position"] for a in e.state["accounts"].values())
    assert len([v for v in e.store.rows("events") if v["kind"] == "MISSED_ENTRY"]) == 6


def test_resume_open_accounts_and_gap_recovery(env, context):
    e, bars, root, scope = env
    stamp = signal(e, bars)
    price = bars[-1].close
    e.opening(stamp, price, stamp + pd.Timedelta(seconds=1), volume=1)
    accounts = json.loads(json.dumps(e.state, default=str))["accounts"]
    e.store.close()
    e.store.close = lambda: None
    store = DonchianStore(root / "eth", scope, dict(code_sha256="fixture"))
    try:
        restored = DonchianEngine(
            store,
            context[1],
            context[2],
            e.execution,
            e.instrument,
            e.nominal,
            stamp + pd.Timedelta(seconds=2),
        )
        restored.recover([bars[-1]], stamp + pd.Timedelta(seconds=2))
        assert restored.state["accounts"] == accounts
        bar = Bar(e.instrument, "1h", stamp, price, price + 0.1, price - 0.1, price, 1)
        restored.recover([bars[-1], bar], bar.close_time)
        assert restored.state["review_required"] and not restored.state["gap"]
        assert all(
            a["position"]["coverage"] == "REST_RECONSTRUCTED"
            for a in restored.state["accounts"].values()
        )
    finally:
        store.close()


def test_invalid_unclosed_revision_and_missing_bars(env):
    e, bars, _, _ = env
    with pytest.raises(ValueError):
        e.closed(bars[-1], bars[-1].timestamp)
    with pytest.raises(ValueError):
        e.closed(Bar("BTC", "1h", bars[-1].timestamp, 1, 1, 1, 1, 1), bars[-1].close_time)
    with pytest.raises(ValueError):
        e.opening(bars[-1].close_time, float("nan"), bars[-1].close_time, volume=1)
    with pytest.raises(ValueError):
        e.closed(Bar(e.instrument, "1h", bars[999].timestamp, 1, 1, 1, 1, 1), bars[-1].close_time)
    t = bars[-1].timestamp + pd.Timedelta(hours=2)
    with pytest.raises(DataGap):
        e.closed(Bar(e.instrument, "1h", t, 100, 100, 100, 100, 1), t + pd.Timedelta(hours=1))


def test_modes_rejected_before_network_or_order_capability():
    class Trap:
        def get(self, *args):
            raise AssertionError("Network forbidden")

        def send_order(self, *args):
            raise AssertionError("Orders forbidden")

    public = PublicBroker(Trap())
    with pytest.raises(ValueError):
        public.get("/api/v5/trade/order")
    assert not hasattr(public, "send_order")
    for mode in ("live", "demo-execution"):
        with pytest.raises(SystemExit):
            main(["run", "--mode", mode])


def test_rmm_mutable_state_and_locks_isolated(env):
    e, _, root, _ = env
    rmm = Store(
        root / "rmm",
        dict(forward=dict(data_protocol="rmm_4h", strategies=[])),
        dict(code_sha256="rmm"),
    )
    try:
        with rmm.db:
            rmm.checkpoint(dict(position="OPEN_RMM_UNTOUCHED"))
        with pytest.raises(OSError):
            DonchianStore(root / "eth", e.store.metadata["config"], dict(code_sha256="fixture"))
        e.gap("fixture", pd.Timestamp.now(tz="UTC"))
        assert rmm.restore() == dict(position="OPEN_RMM_UNTOUCHED")
        assert rmm.lock.name != e.store.lock.name
    finally:
        rmm.close()


def test_grouped_alerts_dry_run_never_send_or_modify_journal(env):
    e, bars, root, _ = env
    signal(e, bars)
    state = root / "cursor.json"
    output = []
    before = e.store.restore()
    poll(root / "eth/forward.sqlite", state, dry_run=True, replay=True, output=output.append)
    assert len(output) == 1 and all(n in output[0] for n in IDS)
    assert "NO EXCHANGE ORDER" in output[0] and not state.exists()
    assert e.store.restore() == before


def test_watcher_skips_heartbeats_advances_cursor_and_delivers_alerts(env):
    from types import SimpleNamespace

    e, _, root, _ = env
    state = root / "cursor.json"
    db = root / "eth/forward.sqlite"
    messages = []

    def send(message):
        messages.append(message)
        return SimpleNamespace(status="delivered")

    notifier = SimpleNamespace(send=send)
    poll(db, state, notifier)
    initial_cursor = json.loads(state.read_text())["cursor"]
    with e.store.db:
        e.store.event("HEARTBEAT", "quiet-heartbeat", dict(notify=True))
    before = e.store.rows("events")
    assert poll(db, state, notifier) == 1
    assert not messages
    assert json.loads(state.read_text())["cursor"] > initial_cursor
    assert e.store.rows("events") == before
    assert poll(db, state, notifier) == 0
    with e.store.db:
        e.store.event("DATA_GAP", "visible-gap", dict(notify=True, reason="fixture"))
    poll(db, state, notifier)
    assert len(messages) == 1 and "DATA_GAP" in messages[0]
    assert "NO EXCHANGE ORDER" in messages[0]
    assert json.loads(state.read_text())["last_delivery"] == "delivered"
    assert poll(db, state, notifier) == 0
    assert len(messages) == 1


def test_late_confirmed_signal_has_explicit_missed_entries(env):
    e, bars, _, _ = env
    e.closed(bars[-1], bars[-1].close_time + pd.Timedelta(seconds=91))
    assert not e.state["pending"] and e.state["effective_start"] is None
    assert len([v for v in e.store.rows("events") if v["kind"] == "MISSED_ENTRY"]) == 6


def test_drawdown_breach_does_not_reset_cash_or_close_positions(env):
    e, bars, _, _ = env
    stamp = signal(e, bars)
    e.opening(stamp, bars[-1].close, stamp + pd.Timedelta(seconds=1), volume=1)
    for account in e.state["accounts"].values():
        account["peak"] = 20000
    bar = Bar(e.instrument, "1h", stamp, 95, 95.1, 94.9, 95, 1)
    e.closed(bar, bar.close_time)
    assert e.state["paused"]
    assert any(a["position"] for a in e.state["accounts"].values())
    assert len([v for v in e.store.rows("events") if v["kind"] == "DRAWDOWN_LIMIT_BREACH"]) == 1


def test_failed_recovery_does_not_clear_gap(env):
    e, bars, _, _ = env
    e.gap("fixture", bars[-1].close_time)
    with pytest.raises(DataGap):
        e.recover([bars[-1]], bars[-1].close_time)
    assert e.state["gap"]


def test_separate_process_rmm_lock_survives_donchian_restart(env):
    import subprocess
    import sys

    e, _, root, scope = env
    code = """
import sys
from pathlib import Path
from quant_lab.forward.store import Store
s=Store(Path(sys.argv[1]),dict(forward=dict(data_protocol='rmm_4h',strategies=[])),dict(code_sha256='rmm'))
with s.db: s.checkpoint(dict(position='RMM_OPEN'))
print('LOCKED',flush=True)
sys.stdin.readline()
assert s.restore()==dict(position='RMM_OPEN')
s.close()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(root / "rmm_process")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        assert child.poll() is None
        e.store.close()
        e.store.close = lambda: None
        restarted = DonchianStore(root / "eth", scope, dict(code_sha256="fixture"))
        try:
            assert restarted.restore() is not None and child.poll() is None
        finally:
            restarted.close()
        child.stdin.write("stop\n")
        child.stdin.flush()
        assert child.wait(timeout=10) == 0
    finally:
        if child.poll() is None:
            child.stdin.close()
            child.wait(timeout=10)


def test_runner_fake_network_stop_and_resume_no_orders(env, context, monkeypatch):
    from quant_lab.forward import donchian_runner as runner
    from quant_lab.forward.store import encode
    from quant_lab.lab_evidence import sha256

    e, bars, root, scope = env
    config = load()[0]
    calls = []
    resumed = False

    class FakeFeed:
        def __init__(self):
            self.broker = self
            self.count = 0

        def now(self):
            self.count += 1
            return (
                bars[-1].close_time + pd.Timedelta(seconds=2)
                if resumed or self.count >= 3
                else bars[999].close_time
            )

        def history(self, *args, **kwargs):
            return [bars[-1]]

        def get(self, endpoint, params=None):
            calls.append(endpoint)
            assert endpoint == "/api/v5/market/candles"
            stamp = bars[-1].close_time
            rows = [[str(stamp.value // 1000000), "95", "95.1", "94.9", "95", "1", "10", "1", "0"]]
            for b in (bars[-1], bars[999]):
                rows.append(
                    [
                        str(b.timestamp.value // 1000000),
                        *map(str, (b.open, b.high, b.low, b.close)),
                        "1",
                        "10",
                        "1",
                        "1",
                    ]
                )
            return rows

        def send_order(self, *args):
            raise AssertionError("Order transport called")

    monkeypatch.setattr(runner, "load", lambda p: (config, root / "runner", context))
    monkeypatch.setattr(runner, "code_identity", lambda: dict(code_sha256="fixture"))
    monkeypatch.setattr(
        runner,
        "public_preflight",
        lambda *args: (FakeFeed(), Instrument(**scope["instrument"]), bars[:1000], scope),
    )

    def stop(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner.time, "sleep", stop)
    proof = root / "proof.json"
    proof.write_text(
        encode(
            dict(
                status="PUBLIC_PREFLIGHT_OK",
                created_at=pd.Timestamp.now(tz="UTC"),
                config_sha256=sha256(DEFAULT),
                code_sha256="fixture",
                resolved=scope,
            )
        )
    )
    runner.run(DEFAULT, proof, broker=FakeFeed())
    first = inspect(root / "runner/forward.sqlite")["sessions"][-1]["session_id"]
    snapshot = inspect(root / "runner/forward.sqlite", first)
    assert all(a["position"] for a in snapshot["state"]["accounts"].values())
    resumed = True
    runner.run(DEFAULT, proof, resume=first, broker=FakeFeed())
    last = inspect(root / "runner/forward.sqlite")["sessions"][-1]["session_id"]
    restored = inspect(root / "runner/forward.sqlite", last)
    assert restored["state"]["accounts"] == snapshot["state"]["accounts"]
    assert set(calls) == {"/api/v5/market/candles"}


@pytest.mark.parametrize(
    "change,accepted",
    [
        ({}, True),
        ({"quoteCcy": ""}, True),
        ({"quoteCcy": "", "settleCcy": "USDC"}, True),
        ({"ctMult": "2"}, False),
        ({"quoteCcy": "USDT"}, False),
        ({"quoteCcy": None}, False),
        ({"quoteCcy": "", "settleCcy": "USDT"}, False),
        ({"quoteCcy": "", "ctValCcy": "USD"}, False),
        ({"expTime": "0"}, False),
        ({"ctType": "inverse"}, False),
    ],
)
def test_instrument_bridge_accepts_only_characterized_contract(change, accepted):
    from types import SimpleNamespace

    from quant_lab.forward.donchian_config import select_instrument

    row = dict(
        instId="ETH-USD_UM_XPERP-310328",
        instType="FUTURES",
        ruleType="xperp",
        ctType="linear",
        state="live",
        ctValCcy="ETH",
        ctMult="1",
        ctVal=".001",
        settleCcy="USD",
        quoteCcy="USD",
        lotSz="1",
        minSz="1",
        tickSz=".01",
        lever="10",
        expTime=str(pd.Timestamp("2031-03-28T00:00Z").value // 1000000),
    )
    broker = SimpleNamespace(get_instruments=lambda: [row | change])
    config = SimpleNamespace(instrument="AUTO")
    if not accepted:
        with pytest.raises(ValueError):
            select_instrument(config, broker, pd.Timestamp("2026-10-09T00:00Z"))
    else:
        inst, metadata = select_instrument(config, broker, pd.Timestamp("2026-10-09T00:00Z"))
        assert inst.contract_size == Decimal(".001")
        assert metadata["quoteCcy"] == (row | change)["quoteCcy"]
        assert inst.settlement_currency == (row | change)["settleCcy"]


@pytest.mark.parametrize(
    "change",
    [
        {"code_sha256": "wrong"},
        {"config_sha256": "wrong"},
        {"created_at": "2020-01-01T00:00:00Z"},
        {"status": "FAILED"},
        {"resolved": {}},
    ],
)
def test_receipt_changes_block_before_run(env, change):
    from quant_lab.forward.donchian_runner import check_receipt
    from quant_lab.forward.store import encode
    from quant_lab.lab_evidence import sha256

    _, _, root, scope = env
    proof = root / "receipt.json"
    raw = dict(
        status="PUBLIC_PREFLIGHT_OK",
        code_sha256="fixture",
        config_sha256=sha256(DEFAULT),
        created_at=pd.Timestamp.now(tz="UTC"),
        resolved=scope,
    )
    proof.write_text(encode(raw | change))
    with pytest.raises(ValueError):
        check_receipt(proof, DEFAULT, scope, dict(code_sha256="fixture"))


def test_checkpoint_missing_account_never_recapitalized(env, context):
    e, _, _, _ = env
    state = e.store.restore()
    del state["accounts"][IDS[0] + "|base"]
    with e.store.db:
        e.store.checkpoint(state)
    with pytest.raises(ValueError, match="never reset"):
        DonchianEngine(
            e.store, context[1], context[2], e.execution, e.instrument, e.nominal, e.started
        )
