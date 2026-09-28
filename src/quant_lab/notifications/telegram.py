"""Small stdlib Telegram client. Never logs URLs, response bodies or exceptions."""

import json
import math
import os
import re
import time
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Delivery:
    status: str
    attempts: int


def enabled() -> bool:
    value = os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").lower().strip()
    if value not in {"true", "false"}:
        raise ValueError("TELEGRAM_NOTIFICATIONS_ENABLED must be true or false")
    return value == "true"


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, *, opener=None, sleep=time.sleep):
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token) or not chat_id.strip():
            raise ValueError(
                "Set valid TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables"
            )
        self._token, self._chat_id = token, chat_id
        self._opener = opener if opener is not None else build_opener(NoRedirect())
        self._sleep = sleep
        self._cooldown_until = 0.0

    @classmethod
    def from_environment(cls):
        return cls(os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", ""))

    def send(self, text: str) -> Delivery:
        if time.monotonic() < self._cooldown_until:
            return Delivery("rate_limited", 0)
        request = Request(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            data=json.dumps(
                {
                    "chat_id": self._chat_id,
                    "text": text,
                    "link_preview_options": {"is_disabled": True},
                }
            ).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "QuantTradingLab/0.1"},
            method="POST",
        )
        for attempt in range(1, 4):
            delay = float(2 ** (attempt - 1))
            try:
                try:
                    with self._opener.open(request, timeout=10) as response:
                        status = response.status
                        payload = json.loads(response.read(65536))
                except HTTPError as exc:
                    status = exc.code
                    try:
                        payload = json.loads(exc.read(65536))
                    except (ValueError, OSError):
                        payload = {}
                    finally:
                        exc.close()
                if not isinstance(payload, dict):
                    return Delivery("invalid_response", attempt)
                if status == 200 and payload.get("ok") is True:
                    return Delivery("sent", attempt)
                code = payload.get("error_code", status)
                if code == 429:
                    params = payload.get("parameters", {})
                    retry = params.get("retry_after", 1) if isinstance(params, dict) else 1
                    delay = max(delay, float(retry))
                    if not math.isfinite(delay) or delay > 30:
                        # Respect long server cooldown without blocking the journal consumer.
                        cooldown = delay if math.isfinite(delay) else 60
                        self._cooldown_until = time.monotonic() + cooldown
                        return Delivery("rate_limited", attempt)
                    outcome = "rate_limited"
                elif isinstance(code, int) and 500 <= code <= 599:
                    outcome = "server_error"
                else:
                    return Delivery("rejected", attempt)
            except (TimeoutError, ConnectionError, URLError, OSError, HTTPException):
                # Delivery may have succeeded remotely: retrying can duplicate a message.
                outcome = "transport_unknown"
            except (ValueError, TypeError):
                return Delivery("invalid_response", attempt)
            if attempt < 3:
                self._sleep(delay)
            elif outcome == "rate_limited":
                self._cooldown_until = time.monotonic() + delay
        return Delivery(outcome, 3)
