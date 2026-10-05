"""Allowlisted, bounded plain text; journal payloads are never dumped wholesale."""

import os
import re
from datetime import UTC, datetime

TITLES = {
    "DEMO_ORDER_SUBMITTED": "DEMO ORDER SUBMITTED",
    "DEMO_ORDER_FILLED": "DEMO ORDER FILLED",
    "DEMO_ORDER_REJECTED": "DEMO ORDER REJECTED",
    "DEMO_POSITION_CLOSED": "DEMO POSITION CLOSED",
    "DEMO_EXECUTION_BLOCKED": "DEMO EXECUTION BLOCKED",
    "SIGNAL_GENERATED": "🚨 SIGNAL GENERATED",
    "ORDER_INTENT_CREATED": "🧮 HYPOTHETICAL ORDER INTENT",
    "TIMING_WINDOW_STARTED": "⏳ OPTIONAL 15M WINDOW STARTED",
    "TIMING_FILL_SELECTED": "🎯 OPTIONAL 15M ENTRY SELECTED",
    "TIMING_FALLBACK": "⏱ OPTIONAL 15M THEORETICAL FALLBACK",
    "TIMING_NOT_EXECUTED": "⏹ OPTIONAL 15M NOT EXECUTED",
    "DATA_GAP": "⚠️ DATA GAP",
    "DATA_GAP_RESOLVED": "🟢 DATA GAP RESOLVED",
    "DATA_GAP_RECOVERY_FAILED": "⚠️ DATA GAP RECOVERY FAILED",
    "RECONNECTED": "🟢 RECONNECTED",
    "MONITORING_WARNING": "⚠️ MONITORING WARNING",
    "ERROR": "🔴 FORWARD ERROR",
    "SIGNAL_REJECTED": "SIGNAL REJECTED",
}


def safe_text(value: object) -> str:
    """Redact configured credentials, credential assignments and URLs before truncating."""
    text = str(value)
    for name, secret in os.environ.items():
        if secret and any(
            part in name.upper()
            for part in ("TOKEN", "SECRET", "PASSWORD", "PASSPHRASE", "API_KEY", "CHAT_ID")
        ):
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"https?://\S+", "[URL REDACTED]", text, flags=re.I)
    text = re.sub(r"\b\d{5,}:[A-Za-z0-9_-]{20,}\b", "[TOKEN REDACTED]", text)
    text = re.sub(
        r"(?i)\b(?:[\w-]*(?:token|secret|password|passphrase|api[_-]?key|authorization))"
        r"[\"']?\s*[:=]\s*[^,;\n]+",
        "[CREDENTIAL REDACTED]",
        text,
    )
    return " ".join(text.split())[:240]


def stamp(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        pass
    return "unknown (missing/invalid UTC timestamp)"


def format_event(data: dict, session: str, *, include_rejected: bool = False) -> str | None:
    kind = data.get("kind")
    if not isinstance(kind, str) or kind not in TITLES:
        return None
    if kind == "SIGNAL_REJECTED" and not include_rejected:
        return None
    actual = kind.startswith("DEMO_")
    demo_context = actual or data.get("runtime_mode") == "demo_execution"
    lines = [
        TITLES[kind],
        "",
        "Mode: OKX DEMO / " + ("DEMO_EXECUTION" if demo_context else "SIGNAL_ONLY"),
    ]
    if actual:
        for fee in data.get("fees_observed", []):
            lines.append(
                "Observed fee: " + safe_text(fee.get("fee")) + " " + safe_text(fee.get("currency"))
            )
        lines.append("Execution: OKX DEMO exchange state; see journal for reconciliation")
    elif demo_context and kind in {"SIGNAL_GENERATED", "ORDER_INTENT_CREATED"}:
        lines.append("Execution: HYPOTHETICAL / SHADOW — see separate demo order events")
    elif demo_context:
        lines.append("Execution: OKX DEMO operational event")
    elif kind == "ORDER_INTENT_CREATED":
        lines.append("Execution: SIGNAL ONLY — NOT sent to OKX")
    elif kind.startswith("TIMING_"):
        lines.append("Execution: SIGNAL ONLY — theoretical selection; no exchange order sent")
    else:
        lines.append("Execution: SIGNAL ONLY — no exchange order sent")

    def field(label: str, *keys: str, timestamp: bool = False) -> None:
        value = next((data[k] for k in keys if data.get(k) is not None), None)
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"{label}: {stamp(value) if timestamp else safe_text(value)}")

    field("Strategy", "strategy")
    field("Instrument", "instrument", "instrument_id")
    field("Timeframe", "timeframe")
    field("Side", "side")
    for key in (
        "ema",
        "momentum",
        "realized_volatility",
        "calculated_exposure_pct",
        "quantity",
        "client_id",
        "status",
        "symbol",
        "mode",
        "reference_price",
        "target_volatility_pct",
        "target_notional",
        "contracts",
        "fill_price",
        "reject_code",
        "latency_ms",
        "actual_quantity",
        "position_after_fill",
    ):
        field(key, key)
    if actual:
        exchange = data.get("exchange", {})
        for label, key in (
            ("Order ID", "ordId"),
            ("Filled contracts", "accFillSz"),
            ("Fee", "fee"),
            ("Fee currency", "feeCcy"),
            ("Position state", "state"),
        ):
            if exchange.get(key) is not None:
                lines.append(f"{label}: {safe_text(exchange[key])}")
    field("Timestamp (UTC)", "timestamp", "resolved_at", "quote_observed_at", timestamp=True)
    if kind == "SIGNAL_GENERATED":
        signal = safe_text(data.get("signal_id", data.get("key", "unknown")))[:16]
        lines.append(f"Signal ID: {signal}")
    elif kind == "ORDER_INTENT_CREATED":
        for label, key in (
            ("Reference price", "reference_price"),
            ("Estimated entry", "estimated_entry_price"),
            ("Target notional", "target_notional"),
            ("Quantity", "target_quantity"),
            ("Contracts", "contracts"),
            ("Stop", "stop_price"),
            ("Policy", "execution_policy"),
        ):
            field(label, key)
    elif kind.startswith("TIMING_"):
        for label, key in (
            ("Baseline entry", "baseline_entry"),
            ("Baseline entry price", "baseline_entry_price"),
            ("Theoretical entry price", "experimental_entry_price"),
            ("Wait minutes", "wait_minutes"),
            ("Fallback", "fallback_used"),
        ):
            field(label, key)
        field("Deadline (UTC)", "deadline", timestamp=True)
        field("Theoretical entry time (UTC)", "experimental_entry_time", timestamp=True)
    for label, key in (
        ("Reason", "reason"),
        ("Non-execution reason", "non_execution_reason"),
        ("Resolved", "resolved"),
        ("Resolution", "resolution"),
        ("Continuity", "continuity"),
        ("Recovered bars", "recovered_bars"),
        ("Incident", "incident"),
        ("Exception type", "exception_type"),
        ("Message", "message"),
    ):
        field(label, key)
    lines.append(f"Session: {safe_text(session)}")
    # Also bounds UTF-16 length well below Telegram's 4096 limit, including emoji.
    return "\n".join(lines)[:1900]
