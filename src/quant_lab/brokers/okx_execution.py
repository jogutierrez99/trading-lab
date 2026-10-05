"""Explicit demo-only order capability. Legacy GET-only broker remains unchanged."""

import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from quant_lab.brokers.okx_demo import (
    PUBLIC,
    REST_URL,
    USER_AGENT,
    NoRedirect,
    OKXDemoBroker,
    safety_environment,
)

READ = {
    "/api/v5/account/config",
    "/api/v5/account/leverage-info",
    "/api/v5/account/instruments",
    "/api/v5/account/balance",
    "/api/v5/account/positions",
    "/api/v5/trade/orders-pending",
    "/api/v5/trade/order",
    "/api/v5/trade/fills",
}


class DemoAPIError(RuntimeError):
    """Numeric exchange diagnostic only; never expose private response messages."""

    def __init__(self, method, code):
        self.code = (
            code
            if isinstance(code, str) and code.isascii() and code.isdecimal() and len(code) <= 16
            else "unknown"
        )
        super().__init__(
            f"Demo API {method} rejected (OKX code={self.code}); reconcile order state"
        )


def demo_transport(method, path, headers, body):
    if REST_URL != "https://eea.okx.com" or headers.get("x-simulated-trading") != "1":
        raise ValueError("Demo transport invariant failed")
    request = Request(
        REST_URL + path,
        headers={"User-Agent": USER_AGENT, **headers},
        data=body.encode() if body else None,
        method=method,
    )
    with build_opener(NoRedirect).open(request, timeout=15) as response:
        return json.load(response)


class OKXDemoExecution(OKXDemoBroker):
    def __init__(self, *, armed=False, request=demo_transport):
        safety_environment()
        self.armed, self.request = armed, request

    def call(self, method, endpoint, params=None, payload=None):
        safety_environment()
        if method == "POST":
            if not self.armed or endpoint != "/api/v5/trade/order":
                raise ValueError("Only armed DEMO market orders are permitted")
            required = {
                "instId",
                "tdMode",
                "posSide",
                "side",
                "ordType",
                "sz",
                "clOrdId",
                "reduceOnly",
            }
            if (
                set(payload) != required
                or payload["ordType"] != "market"
                or payload["tdMode"] != "isolated"
                or payload["posSide"] != "net"
                or payload["side"] not in {"buy", "sell"}
                or not payload["clOrdId"].isalnum()
                or len(payload["clOrdId"]) > 32
                or not Decimal(payload["sz"]).is_finite()
                or Decimal(payload["sz"]) <= 0
                or type(payload["reduceOnly"]) is not bool
            ):
                raise ValueError("Invalid frozen demo market order")
        elif method != "GET" or endpoint not in PUBLIC | READ:
            raise ValueError("Endpoint/method forbidden")
        body = json.dumps(payload, separators=(",", ":")) if payload is not None else ""
        path = endpoint + ("?" + urlencode(params) if params else "")
        headers = {"Content-Type": "application/json", "x-simulated-trading": "1"}
        if method == "POST":
            headers["expTime"] = str(int(datetime.now(UTC).timestamp() * 1000) + 5000)
        if method == "POST" or endpoint in READ:
            names = ["OKX_DEMO_API_KEY", "OKX_DEMO_API_SECRET", "OKX_DEMO_API_PASSPHRASE"]
            if not all(os.getenv(n) for n in names):
                raise ValueError("Dedicated OKX_DEMO_API_* credentials required")
            stamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            signature = base64.b64encode(
                hmac.new(
                    os.environ[names[1]].encode(),
                    (stamp + method + path + body).encode(),
                    hashlib.sha256,
                ).digest()
            ).decode()
            headers.update(
                {
                    "OK-ACCESS-KEY": os.environ[names[0]],
                    "OK-ACCESS-SIGN": signature,
                    "OK-ACCESS-TIMESTAMP": stamp,
                    "OK-ACCESS-PASSPHRASE": os.environ[names[2]],
                }
            )
        try:
            response = self.request(method, path, headers, body)
        except Exception as exc:
            diagnostic = (
                f"HTTP status {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
            )
            operation = (
                "submission outcome unknown; reconcile by clOrdId"
                if method == "POST"
                else "GET unavailable"
            )
            raise RuntimeError(f"Demo transport {operation} ({diagnostic})") from None
        if response.get("code") != "0" or not isinstance(response.get("data"), list):
            raise DemoAPIError(method, response.get("code"))
        return response["data"]

    def get(self, endpoint, params=None):
        return self.call("GET", endpoint, params)

    def submit(self, payload):
        return self.call("POST", "/api/v5/trade/order", payload=payload)

    def by_client(self, instrument, client):
        return self.get("/api/v5/trade/order", {"instId": instrument, "clOrdId": client})

    def entry_balance_ready(self):
        """Minimum entry guard; positive equity does not prove sufficient margin."""
        balance = self.get_balance()
        try:
            if len(balance) != 1:
                raise ValueError
            equity = Decimal(balance[0]["totalEq"])
            if not equity.is_finite():
                raise ValueError
        except (KeyError, TypeError, InvalidOperation, ValueError):
            raise ValueError("Demo trading equity unavailable; new entries blocked") from None
        if equity <= 0:
            raise ValueError(
                "Demo trading equity is not positive; "
                "restore virtual demo assets before new entries"
            )
        return equity

    def account_ready(self, instrument):
        cfg = self.get("/api/v5/account/config")
        if len(cfg) != 1 or cfg[0].get("posMode") != "net_mode":
            raise ValueError("Demo account must use net_mode")
        leverage = self.get(
            "/api/v5/account/leverage-info", {"instId": instrument, "mgnMode": "isolated"}
        )
        if not leverage or any(Decimal(r["lever"]) != 1 for r in leverage):
            raise ValueError("Configure isolated 1x manually before starting; no leverage mutation")
        accessible = self.get("/api/v5/account/instruments", {"instType": "FUTURES"})
        if not any(r["instId"] == instrument and r.get("state") == "live" for r in accessible):
            raise ValueError("Instrument unavailable to this demo account")
