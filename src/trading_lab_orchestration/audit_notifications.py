"""Coordinator-owned manual Telegram outbox; no forward watcher dependencies.

One sendMessage attempt per explicit send command. Remote acceptance is not reading.
Transport ambiguity is UNKNOWN and never automatically retried.
"""

import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener
from uuid import uuid4

from quant_lab.notifications.telegram import NoRedirect

from .audit import Auditor
from .contracts import digest
from .processes import coordinator_lock
from .store import utc_now


def recipient():
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    verified = os.getenv("TRADING_LAB_TELEGRAM_VERIFIED_PRIVATE_CHAT_ID", "").strip()
    if not re.fullmatch(r"[1-9][0-9]{0,19}", chat) or chat != verified:
        return None
    return digest("telegram-private:" + chat)


@dataclass(frozen=True)
class Outcome:
    status: str
    code: str
    message_id: int | None = None
    retry_after: float | None = None


class TelegramTransport:
    """No credentials/URLs/response bodies/exceptions escape this class."""

    def __init__(self, opener=None):
        self.opener = opener or build_opener(NoRedirect())

    def _call(self, method, payload, token):
        request = Request(
            "https://api.telegram.org/bot" + token + "/" + method,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                return json.loads(response.read(65536))
        except HTTPError as exc:
            try:
                return json.loads(exc.read(65536))
            finally:
                exc.close()

    def send(self, text):
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token) or recipient() is None:
            return Outcome("RETRYABLE", "MISSING_VERIFIED_TELEGRAM_CONFIGURATION")
        chat = os.environ["TELEGRAM_CHAT_ID"].strip()
        try:
            preflight = self._call("getChat", {"chat_id": chat}, token)
            result = preflight.get("result", {})
            if (
                preflight.get("ok") is not True
                or result.get("type") != "private"
                or str(result.get("id")) != chat
            ):
                return Outcome("FAILED", "DESTINATION_NOT_VERIFIED_PRIVATE_CHAT")
        except Exception:
            # No sendMessage was attempted. Retrying an explicit send remains safe.
            return Outcome("RETRYABLE", "PRIVATE_CHAT_PREFLIGHT_FAILED")
        try:
            payload = self._call(
                "sendMessage",
                {"chat_id": chat, "text": text, "link_preview_options": {"is_disabled": True}},
                token,
            )
            if not isinstance(payload, dict):
                return Outcome("UNKNOWN", "MALFORMED_SEND_RESPONSE")
            if payload.get("ok") is True:
                result = payload.get("result", {})
                identifier = result.get("message_id")
                if type(identifier) is int and str(result.get("chat", {}).get("id")) == chat:
                    return Outcome("ACCEPTED", "TELEGRAM_SERVICE_ACCEPTED", identifier)
                return Outcome("UNKNOWN", "ACCEPTANCE_WITHOUT_MATCHING_RECEIPT")
            code = payload.get("error_code")
            if payload.get("ok") is False and code == 429:
                delay = payload.get("parameters", {}).get("retry_after", 60)
                if type(delay) not in (int, float) or not math.isfinite(delay) or delay < 0:
                    delay = 86400
                return Outcome("RETRYABLE", "TELEGRAM_RATE_LIMIT", retry_after=float(delay))
            if payload.get("ok") is False and type(code) is int and 400 <= code < 500:
                return Outcome("FAILED", "TELEGRAM_PERMANENT_REJECTION")
            return Outcome("UNKNOWN", "SERVER_OR_INVALID_SEND_RESPONSE")
        except Exception:
            return Outcome("UNKNOWN", "TRANSMISSION_OUTCOME_UNKNOWN")


class Outbox:
    def __init__(self, store):
        self.store = store
        self.lock = store.path.with_suffix(".notification.lock")

    def get(self, identifier):
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM audit_outbox WHERE notification_id=?", (identifier,)
            ).fetchone()
        if not row:
            raise ValueError("Unknown notification")
        return dict(row)

    def preview(self, audit_id):
        audit = Auditor(self.store).inspect(audit_id)
        if audit["status"] == "PREPARED":
            raise ValueError("Persist verdict and report before enqueueing a notification")
        verdict = audit["verdict"]
        results = verdict["observations"].get("native_results", [])
        metrics = results[0]["result"]["metrics"] if results else {}
        count = sum(r["result"]["metrics"]["closed_trades"] for r in results) if results else None
        message = (
            "Trading Lab — aviso TÉCNICO 4.4\n"
            f"Estrategia: {metrics.get('strategy', 'UNKNOWN')}; "
            f"{metrics.get('symbol', 'UNKNOWN')}; "
            f"versión {metrics.get('strategy_version', 'UNKNOWN')}\n"
            f"Run: {verdict['run_id']}\n"
            f"Sintético: {verdict['observations'].get('synthetic', 'UNKNOWN')}\n"
            f"Auditoría: {audit_id}; {verdict['audit_status']}\n"
            f"Dictamen económico: {verdict['auditor_verdict']}. "
            "Sin validación económica ni elegibilidad demo/paper.\n"
            f"Operaciones cerradas por casos (no cartera agregada): {count}; "
            "evidencia insuficiente para concluir rentabilidad.\n"
            f"Informe local (portátil): {Path(audit['root']) / 'audit_report.md'}\n"
            f"SHA256 informe: {audit['report_sha256']}\n"
            "Sin botones, órdenes ni solicitud de activación."
        )
        if comparison := verdict["observations"].get("paired_comparison"):
            from .rmm_audit_summary import delta_overview

            branches = comparison["branches"]
            message = "\n".join(
                [
                    "Trading Lab — Flujo 1 · RMM 4H + momentum 28 días",
                    f"Auditoría {audit_id} · "
                    f"{verdict['audit_status']} · {verdict['auditor_verdict']}",
                    f"RMM congelado: {branches['baseline']['run_id']}",
                    f"Variante: {branches['variant']['run_id']}",
                    "24 casos BASE completos · 12 pares · Δ Sharpe neto variante menos baseline",
                    *delta_overview(comparison),
                    "Pendientes: TEST, ADVERSE y controles SMA28 y aleatorio.",
                    f"Informe local: {Path(audit['root']) / 'audit_report.md'}",
                ]
            )
        if len(message) > 4096:
            raise ValueError("Notification exceeds Telegram text limit")
        with self.store.transaction() as conn:
            old = conn.execute(
                "SELECT notification_id FROM audit_outbox WHERE audit_id=?", (audit_id,)
            ).fetchone()
            if old:
                identifier = old["notification_id"]
            else:
                identifier = "notice_" + uuid4().hex
                conn.execute(
                    (
                        "INSERT INTO audit_outbox(notification_id,audit_id,event,mess"
                        "age,message_sha256,status,created_at_utc,updated_at_utc) VAL"
                        "UES(?,?,'AUDIT_TECHNICAL_NOTICE',?,?,'DRAFT',?,?)"
                    ),
                    (identifier, audit_id, message, digest(message), utc_now(), utc_now()),
                )
        return self.get(identifier) | {
            "dry_run": True,
            "verified_recipient_configured": recipient() is not None,
            "real_send_performed": False,
        }

    def send(self, identifier, *, retry=False, transport=None):
        row = self.get(identifier)
        # Missing config is a local blocker, not a send attempt or binding to a
        # guessed destination. A draft can be bound exactly once at reservation.
        destination = recipient()
        if destination is None:
            return row | {
                "blocked": (
                    "Configure matching positive TELEGRAM_CHAT_ID and "
                    "TRADING_LAB_TELEGRAM_VERIFIED_PRIVATE_CHAT_ID for the user's "
                    "verified private chat"
                )
            }
        if transport is None and not os.getenv("TELEGRAM_BOT_TOKEN"):
            return row | {
                "blocked": "Configure TELEGRAM_BOT_TOKEN locally; do not paste it into chat"
            }
        try:
            with coordinator_lock(self.lock):
                return self._send(identifier, destination, retry, transport or TelegramTransport())
        except ValueError as exc:
            if "owns the OS lock" in str(exc):
                return self.get(identifier) | {"busy": True}
            raise

    def _send(self, identifier, destination, retry, transport):
        with self.store.transaction() as conn:
            row = dict(
                conn.execute(
                    "SELECT * FROM audit_outbox WHERE notification_id=?", (identifier,)
                ).fetchone()
            )
            if row["status"] not in ({"DRAFT", "RETRYABLE"} if retry else {"DRAFT"}):
                return row
            if row["attempts"] >= 3:
                raise ValueError("Manual notification attempt limit exhausted")
            if row["retry_after_utc"] and row["retry_after_utc"] > time.time():
                return row | {"blocked": "Respect Telegram cooldown before explicit retry"}
            if row["recipient_sha256"] and row["recipient_sha256"] != destination:
                raise ValueError("Recipient differs from immutable outbox binding")
            audit = Auditor(self.store).inspect(row["audit_id"])
            if audit["status"] == "PREPARED" or digest(row["message"]) != row["message_sha256"]:
                raise ValueError("Notification evidence changed")
            # Serialize even different audits; no burst or background retries.
            last = conn.execute(
                "SELECT MAX(retry_after_utc) FROM audit_outbox WHERE status IN "
                "('ACCEPTED','SENDING','RETRYABLE')"
            ).fetchone()[0]
            if last and last > time.time():
                return row | {"blocked": "Global notification cooldown"}
            conn.execute(
                (
                    "UPDATE audit_outbox SET status='SENDING',recipient_sha256=?, "
                    "attempts=attempts+1,updated_at_utc=?,retry_after_utc=? WHERE "
                    "notification_id=?"
                ),
                (destination, utc_now(), time.time() + 1, identifier),
            )
        try:
            result = transport.send(row["message"])
        except Exception:
            result = Outcome("UNKNOWN", "TRANSMISSION_OUTCOME_UNKNOWN")
        if result.status not in {"ACCEPTED", "FAILED", "UNKNOWN", "RETRYABLE"}:
            result = Outcome("UNKNOWN", "INVALID_TRANSPORT_OUTCOME")
        with self.store.transaction() as conn:
            conn.execute(
                (
                    "UPDATE audit_outbox SET status=?,message_id=?,outcome=?,retr"
                    "y_after_utc=?,updated_at_utc=? WHERE notification_id=? AND s"
                    "tatus='SENDING'"
                ),
                (
                    result.status,
                    result.message_id,
                    result.code,
                    time.time() + max(result.retry_after or 0, 1),
                    utc_now(),
                    identifier,
                ),
            )
        return self.get(identifier)

    def reconcile(self, identifier, *, outcome, reason, message_id=None, confirm_stopped=False):
        if (
            not confirm_stopped
            or not reason.strip()
            or outcome not in {"accepted", "not-sent", "uncertain"}
        ):
            raise ValueError(
                "Explicit stopped confirmation, reconciliation outcome and evidence reason required"
            )
        if outcome == "accepted" and (type(message_id) is not int or message_id <= 0):
            raise ValueError("Verified service message_id required for accepted reconciliation")
        with coordinator_lock(self.lock), self.store.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM audit_outbox WHERE notification_id=?", (identifier,)
            ).fetchone()
            if not row or row["status"] not in {"UNKNOWN", "SENDING"}:
                raise ValueError("Only uncertain/stopped delivery can be reconciled")
            conn.execute(
                (
                    "UPDATE audit_outbox SET "
                    "status=?,message_id=?,outcome=?,updated_at_utc=? WHERE "
                    "notification_id=?"
                ),
                (
                    {"accepted": "ACCEPTED", "not-sent": "RETRYABLE", "uncertain": "UNKNOWN"}[
                        outcome
                    ],
                    message_id if outcome == "accepted" else None,
                    "MANUAL: " + reason,
                    utc_now(),
                    identifier,
                ),
            )
        return self.get(identifier)
