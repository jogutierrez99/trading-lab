"""Durable data incidents and explicit continuity audits, independent of signal rules."""

from math import isclose
from uuid import uuid4

import pandas as pd

from quant_lab.forward.feeds import history
from quant_lab.forward.store import identity
from quant_lab.market_data.okx import BARS, Bar, DataGap
from quant_lab.mtf_features import STEPS


def as_bar(row):
    return Bar(**(row | {"timestamp": pd.Timestamp(row["timestamp"])}))


def audit(instrument, timeframe, stamps, start, end):
    """Inclusive candle-open bounds; never infer a missing leading/trailing boundary."""
    step = STEPS[timeframe]
    stamps = [pd.Timestamp(t) for t in stamps]
    expected = pd.date_range(start, end, freq=step)
    present = [t for t in stamps if start <= t <= end]
    missing = expected.difference(pd.DatetimeIndex(present))
    duplicates = len(present) - len(set(present))
    out_of_order = any(a > b for a, b in zip(present, present[1:], strict=False))
    aligned = all(t.value % step.value == 0 for t in present)
    return {
        "instrument": instrument,
        "timeframe": timeframe,
        "expected_start": start.isoformat(),
        "expected_end": end.isoformat(),
        "expected_interval": str(step),
        "bars_expected": len(expected),
        "bars_present": len(set(present)),
        "missing_timestamps": [t.isoformat() for t in missing],
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "continuity_ok": bool(
            len(expected) and not len(missing) and not duplicates and not out_of_order and aligned
        ),
    }


def detect(engine, reason, *, now=None, first_new=None):
    """One open shared-feed incident; retries reuse its identity and original anchors."""
    pending = engine.store.gaps(unresolved=True)
    if pending:
        return pending
    windows = []
    for instrument in engine.config.instruments.values():
        for tf in BARS:
            if not engine.config.required_feed(instrument, tf):
                continue
            rows = engine.book.bars.get((instrument, tf), {})
            start = max(rows) if rows else None
            end = now.floor(STEPS[tf]) - STEPS[tf] if now is not None else start
            if first_new and (first_new.instrument_id, first_new.timeframe) == (instrument, tf):
                end = max(end, first_new.timestamp) if end is not None else first_new.timestamp
            windows.append(
                {
                    "instrument": instrument,
                    "timeframe": tf,
                    "expected_start": start.isoformat() if start is not None else None,
                    "expected_end": end.isoformat() if end is not None else None,
                }
            )
    with engine.store.db:
        key = uuid4().hex
        engine.store.event(
            "DATA_GAP",
            key,
            {
                "reason": reason,
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "resolved": False,
                "continuity_verified": False,
                "windows": windows,
            },
        )
        engine.store.event(
            "SIGNAL_BLOCKED_DATA_GAP",
            key,
            {
                "reason": "feed_paused",
                "incident": key,
            },
        )
    return engine.store.gaps(unresolved=True)


def recover_incidents(engine, feed):
    store = engine.store
    gaps = store.gaps(unresolved=True)
    if not gaps:
        return True
    try:
        now = feed.now()
    except (OSError, RuntimeError, ValueError):
        with store.db:
            for gap in gaps:
                store.update_gap(gap, resolution="RECOVERY_INCOMPLETE", continuity_verified=False)
                store.event(
                    "DATA_GAP_RECOVERY_FAILED",
                    identity(gap["event_id"], "clock"),
                    {
                        "incident": gap["event_id"],
                        "reason": "server_clock_unavailable",
                    },
                )
        return False
    sources = {g["source_stream"] for g in gaps} | {store.stream}
    original = [as_bar(r) for source in sources for r in store.source_bars(source)]
    staged = [as_bar(r) for source in sources for r in store.source_bars(source, "recovery_bars")]
    plans = {}
    for gap in gaps:
        windows = gap.get("windows") or [
            {"instrument": inst, "timeframe": tf}
            for inst in engine.config.instruments.values()
            for tf in BARS
            if engine.config.required_feed(inst, tf)
        ]
        plans[gap["event_id"]] = []
        for window in windows:
            inst, tf = window["instrument"], window["timeframe"]
            stamps = [b.timestamp for b in original if (b.instrument_id, b.timeframe) == (inst, tf)]
            end = now.floor(STEPS[tf]) - STEPS[tf]
            if window.get("expected_end"):
                end = max(end, pd.Timestamp(window["expected_end"]))
            # Legacy incidents have no anchors: audit the entire persisted history,
            # rather than treating their last bar alone as evidence of continuity.
            start = (
                pd.Timestamp(window["expected_start"])
                if window.get("expected_start")
                else (min(stamps) if stamps else end - (engine.config.warmup_bars - 1) * STEPS[tf])
            )
            plans[gap["event_id"]].append((inst, tf, start, end))
    with store.db:
        for gap in gaps:
            store.event(
                "DATA_GAP_RECOVERY_STARTED",
                gap["event_id"],
                {
                    "incident": gap["event_id"],
                    "source_session": gap["source_session"],
                },
            )
    fetched, failures = [], {}
    for inst in engine.config.instruments.values():
        for tf in BARS:
            bounds = [w for plan in plans.values() for w in plan if w[:2] == (inst, tf)]
            if not bounds:
                continue
            since = min(w[2] for w in bounds)
            try:
                bars = feed.history(inst, tf, engine.config.warmup_bars, since=since)
                chunks = [bars]
                if not engine.book.bars.get((inst, tf)):
                    warmup = feed.history(inst, tf, engine.config.warmup_bars)
                    chunks.append(warmup)
                    bars = warmup + bars
            except DataGap as exc:
                bars = exc.bars
                chunks = [bars]
                # A persisted copy can cover a missing REST overlap, but the audit
                # must still cover every requested boundary using confirmed data.
            except (OSError, RuntimeError, ValueError) as exc:
                bars = []
                chunks = []
                failures[(inst, tf)] = type(exc).__name__
            # REST legitimately overlaps persisted candles. Duplicate exact values
            # are deduplicated explicitly below; revisions and unordered responses fail.
            # Each REST call is chronological; the warmup overlap is checked separately
            # through the immutable per-candle identity, not concatenation order.
            if any(
                a.timestamp > b.timestamp
                for chunk in chunks
                for a, b in zip(chunk, chunk[1:], strict=False)
            ):
                failures[(inst, tf)] = "out_of_order"
            for bar in bars:
                if (bar.instrument_id, bar.timeframe) != (inst, tf) or bar.close_time > now:
                    failures[(inst, tf)] = "invalid_or_unclosed_candle"
                    continue
                fetched.append(bar)
    merged, deduplicated = {}, {}
    for bar in original + staged + fetched:
        previous = merged.get(bar.key)
        pair = (bar.instrument_id, bar.timeframe)
        if previous and not all(
            isclose(getattr(previous, field), getattr(bar, field), rel_tol=1e-10, abs_tol=1e-10)
            for field in ("open", "high", "low", "close", "volume")
        ):
            failures[(bar.instrument_id, bar.timeframe)] = "conflicting_duplicate"
        elif previous:
            deduplicated[pair] = deduplicated.get(pair, 0) + 1
        else:
            merged[bar.key] = bar
    # Persist real REST data separately until the complete context is certified.
    # A failed audit must not leave a discontinuous CandleBook/checkpoint.
    original_keys = {b.key for b in original + staged}
    with store.db:
        for bar in fetched:
            if (bar.instrument_id, bar.timeframe) in failures:
                continue
            if bar.key not in original_keys and store.put("recovery_bars", bar.key, bar.row()):
                store.event(
                    "DATA_GAP_BAR_RECOVERED",
                    bar.key,
                    {
                        "incident": gaps[0]["event_id"],
                        **bar.row(),
                    },
                )
    persisted = original + staged + [as_bar(r) for r in store.rows("recovery_bars")]
    unique = {b.key: b for b in persisted}
    audits = {}
    for gap in gaps:
        result = []
        for inst, tf, start, end in plans[gap["event_id"]]:
            stamps = sorted(
                b.timestamp for b in unique.values() if (b.instrument_id, b.timeframe) == (inst, tf)
            )
            row = audit(inst, tf, stamps, start, end)
            row["duplicates_deduplicated"] = deduplicated.get((inst, tf), 0)
            if (inst, tf) in failures:
                row.update(
                    continuity_ok=False,
                    error=failures[(inst, tf)],
                    out_of_order=failures[(inst, tf)] == "out_of_order",
                    duplicates=int(failures[(inst, tf)] == "conflicting_duplicate"),
                )
            result.append(row)
        audits[gap["event_id"]] = result
    success = all(a["continuity_ok"] for rows in audits.values() for a in rows)
    if success:
        collected = []
        for bar in unique.values():
            rows = engine.book.bars.get((bar.instrument_id, bar.timeframe), {})
            if engine.config.required_feed(bar.instrument_id, bar.timeframe) and (
                not rows or bar.timestamp >= max(rows)
            ):
                collected.append(bar)
        if not store.restore():
            engine.bootstrap(collected)
        else:
            known = engine.book.bars.get((engine.eth, "15m"), {})
            if any(b.timeframe == "15m" and b.timestamp not in known for b in collected):
                engine.invalidate_timing("disconnect_or_restart_no_retroactive_entry")
            for bar in sorted(collected, key=lambda b: (b.close_time, b.timeframe != "15m")):
                engine.ingest(bar, feed.quote, recovering=True)
        # Monitoring remains nonblocking and cannot certify required strategy inputs.
        for inst in engine.config.instruments.values():
            for tf in BARS:
                if not engine.config.required_feed(inst, tf):
                    latest = engine.monitor_latest.get(f"{inst}|{tf}")
                    since = pd.Timestamp(latest["timestamp"]) if latest else None
                    bars, warning = history(engine.config, feed, inst, tf, since=since)
                    if warning:
                        with store.db:
                            engine.monitoring_warning(inst, tf, warning["reason"])
                    for bar in bars:
                        engine.ingest(bar, feed.quote, recovering=True)
                    end = now.floor(STEPS[tf]) - STEPS[tf]
                    start = (
                        since
                        if since is not None
                        else (min(b.timestamp for b in bars) if bars else end)
                    )
                    stamps = [b.timestamp for b in bars]
                    if since is not None and since not in stamps:
                        stamps.insert(0, since)
                    monitoring_audit = audit(inst, tf, stamps, start, end)
                    if warning:
                        monitoring_audit.update(continuity_ok=False, error=warning["reason"])
                    with store.db:
                        store.event(
                            "MONITORING_CONTINUITY_AUDIT",
                            identity(gaps[0]["event_id"], inst, tf, end),
                            monitoring_audit | {"blocks_signals": False},
                        )
    with store.db:
        recovered = [
            r
            for source in sources
            for r in store.source_bars(source, "events")
            if r["kind"] == "DATA_GAP_BAR_RECOVERED"
        ]
        for gap in gaps:
            rows = audits[gap["event_id"]]
            fields = {
                "resolved": success,
                "continuity_verified": success,
                "audits": rows,
                "resolution": "REST_CONTINUITY_VERIFIED" if success else "RECOVERY_INCOMPLETE",
                "missing_timestamps": [
                    {"instrument": a["instrument"], "timeframe": a["timeframe"], "timestamp": t}
                    for a in rows
                    for t in a["missing_timestamps"]
                ],
                "recovered_bars": sum(r["incident"] == gap["event_id"] for r in recovered),
            }
            if success:
                fields.update(resolved_at=pd.Timestamp.now(tz="UTC").isoformat(), reconnected=True)
            store.update_gap(gap, **fields)
            kind = "DATA_GAP_RESOLVED" if success else "DATA_GAP_RECOVERY_FAILED"
            key = gap["event_id"] if success else identity(gap["event_id"], fields)
            store.event(kind, key, {"incident": gap["event_id"], **fields})
            if success and not store.gap_reconnected(gap):
                store.event(
                    "RECONNECTED",
                    gap["event_id"],
                    {
                        "incident": gap["event_id"],
                        "continuity": "REST_verified",
                    },
                )
    return success
