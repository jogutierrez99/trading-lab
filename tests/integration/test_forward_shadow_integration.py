"""Shadow integration uses existing forward fixtures; no network or historical research."""

import copy
import json
from dataclasses import asdict

import pandas as pd
from test_forward_runner import fixture_bars, setup

from quant_lab.forward.engine import ForwardEngine
from quant_lab.forward.shadow_reconstruct import reconstruct


def test_shadow_restart_replay_and_reconstruction(tmp_path):
    engine, store = setup(tmp_path / "forward")
    # Complete metadata for read-only reconstruction, as in production runner.
    store.metadata["config"].update(
        inherited=engine.inherited.model_dump(mode="json"),
        instruments={k: asdict(v) for k, v in engine.instruments.items()},
    )
    hours, quarters = fixture_bars(engine)
    engine.bootstrap(hours[:250] + quarters[:1000])

    def quote(inst, t):
        return 130, t

    for b in quarters[1000:1100]:
        engine.ingest(b, quote)
    assert engine.shadow.positions
    before = copy.deepcopy(engine.shadow.positions)
    engine = ForwardEngine(engine.config, engine.inherited, engine.instruments, store)
    assert engine.shadow.positions == before
    for b in quarters[1000:1100]:
        engine.ingest(b, quote)
    assert engine.shadow.positions == before
    store.report("running")
    original = {p.name: p.read_bytes() for p in store.path.iterdir() if p.is_file()}
    out = reconstruct(store.path, tmp_path / "derived")
    source = json.loads((out / "source_snapshot.json").read_text())
    assert source["source"] == "sqlite_readonly_snapshot"
    restored = pd.read_csv(out / "shadow_positions_reconstructed.csv")
    live = pd.read_csv(store.path / "shadow_positions.csv")
    columns = ["order_intent_id", "status", "bars_held", "mfe_pnl", "mae_pnl", "realized_pnl_net"]
    pd.testing.assert_frame_equal(live[columns], restored[columns])
    assert all((store.path / name).read_bytes() == content for name, content in original.items())
    assert not store.rows("orders") and not store.rows("fills")
    assert "HYPOTHETICAL / SHADOW RESULTS" in (store.path / "ai_summary.md").read_text()
    store.close()


def test_shadow_new_store_restart_and_unresolved_gap(tmp_path):
    from quant_lab.forward.store import Store
    from quant_lab.market_data.okx import Bar

    engine, store = setup(tmp_path / "restart")
    t = pd.Timestamp("2026-01-01", tz="UTC")
    with store.db:
        intent = engine.sized_intent("eth_trend_pullback_v1", "signal", t, 100, t, 2)
        engine.accept(intent, t, signal_id="signal")
        engine.save()
    before = copy.deepcopy(engine.shadow.positions)
    config, settings, instruments = engine.config, engine.inherited, engine.instruments
    store.close()
    store = Store(
        tmp_path / "restart", {"forward": config.model_dump(mode="json")}, {"code_sha256": "test"}
    )
    engine = ForwardEngine(config, settings, instruments, store)
    assert engine.shadow.positions == before
    # Repeated intent remains the same position even in a new session.
    p = engine.shadow.open(intent, instruments[engine.eth], store.session, "signal", t)
    assert p["shadow_position_id"] in before
    with store.db:
        store.event("DATA_GAP", "gap", {"reason": "fixture", "resolved": False})
    engine.ingest(Bar(engine.eth, "15m", t, 100, 101, 99, 100, 1), lambda *_: None)
    assert engine.shadow.positions == before
    assert not store.rows("orders") and not store.rows("fills")
    assert any(e["kind"] == "SIGNAL_BLOCKED_DATA_GAP" for e in store.rows("events"))
    store.metadata["config"].update(
        inherited=settings.model_dump(mode="json"),
        instruments={k: asdict(v) for k, v in instruments.items()},
    )
    store.report("running")
    out = reconstruct(store.path, tmp_path / "derived-restart")
    carried = pd.read_csv(out / "shadow_positions_reconstructed.csv")
    assert set(carried.shadow_position_id) == set(before)
    assert carried.order_intent_id.tolist() == [intent.id]
    assert carried.coverage.eq("DATA_GAP").all()
    store.close()


def test_shadow_csv_reconstruction_and_gap_limit(tmp_path):
    import shutil

    engine, store = setup(tmp_path / "forward")
    store.metadata["config"].update(
        inherited=engine.inherited.model_dump(mode="json"),
        instruments={k: asdict(v) for k, v in engine.instruments.items()},
    )
    t = pd.Timestamp("2026-01-01", tz="UTC")
    with store.db:
        intent = engine.sized_intent("eth_trend_pullback_v1", "signal", t, 100, t, 2)
        engine.accept(intent, t, signal_id="signal")
        store.event("DATA_GAP", "gap", {"reason": "fixture", "resolved": False})
        engine.save()
    store.report("running")
    state = pd.read_csv(store.path / "shadow_positions.csv")
    assert state.coverage.eq("DATA_GAP").all()
    assert all(p["coverage"] == "CONTINUOUS" for p in engine.shadow.positions.values())
    exported = tmp_path / "exports" / store.session
    shutil.copytree(store.path, exported)
    source_before = {p.name: p.read_bytes() for p in exported.iterdir() if p.is_file()}
    out = reconstruct(exported, tmp_path / "derived")
    restored = pd.read_csv(out / "shadow_positions_reconstructed.csv")
    assert restored.coverage.eq("DATA_GAP").all()
    assert restored.bars_held.eq(0).all()
    assert json.loads((out / "provenance.json").read_text())["warnings"]
    assert all((exported / name).read_bytes() == value for name, value in source_before.items())
    store.close()
