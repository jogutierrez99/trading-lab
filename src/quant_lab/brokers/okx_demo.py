"""OKX EEA demo GET-only REST. Fixed host, no redirects, no mutation transport.

API reference: https://my.okx.com/docs-v5/en/ (checked 2026-09-28).
"""

import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from quant_lab.brokers.base import ReadOnlyBroker
from quant_lab.brokers.instruments import Instrument

REST_URL = "https://eea.okx.com"
WS_URL = "wss://wseeapap.okx.com:8443/ws/v5/business"
USER_AGENT = "QuantTradingLab/0.1 signal-only"
PUBLIC = {
    "/api/v5/public/time",
    "/api/v5/public/instruments",
    "/api/v5/market/candles",
    "/api/v5/market/history-candles",
    "/api/v5/market/ticker",
}
PRIVATE = {
    "/api/v5/account/balance",
    "/api/v5/account/positions",
    "/api/v5/trade/orders-pending",
    "/api/v5/trade/order",
    "/api/v5/trade/fills",
}


def safety_environment():
    for key, default in (("TRADING_ENABLED", "false"), ("ALLOW_LIVE_TRADING", "false")):
        if os.getenv(key, default).lower() != "false":
            raise ValueError(f"{key} must be false in SIGNAL_ONLY")
    if (
        os.getenv("ENVIRONMENT", "demo") != "demo"
        or os.getenv("OKX_DEMO", "true").lower() != "true"
    ):
        raise ValueError("Only OKX demo environment is permitted")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("OKX redirect refused")


def transport(path, headers):
    request = Request(
        REST_URL + path,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json", **headers},
        method="GET",
    )
    with build_opener(NoRedirect).open(request, timeout=15) as response:
        return json.load(response)


class OKXDemoBroker(ReadOnlyBroker):
    def __init__(self, request=transport):
        safety_environment()
        self._request = request

    def get(self, endpoint, params=None):
        safety_environment()
        if endpoint not in PUBLIC | PRIVATE:
            raise ValueError("Endpoint is not in the read-only allowlist")
        path = endpoint + ("?" + urlencode(params) if params else "")
        headers = {"Content-Type": "application/json", "x-simulated-trading": "1"}
        if endpoint in PRIVATE:
            names = ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
            if not all(os.getenv(n) for n in names):
                raise ValueError("Missing demo credentials: " + ", ".join(names))
            timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            signature = base64.b64encode(
                hmac.new(
                    os.environ[names[1]].encode(),
                    (timestamp + "GET" + path).encode(),
                    hashlib.sha256,
                ).digest()
            ).decode()
            headers.update(
                {
                    "OK-ACCESS-KEY": os.environ[names[0]],
                    "OK-ACCESS-SIGN": signature,
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": os.environ[names[2]],
                }
            )
        try:
            result = self._request(path, headers)
        except HTTPError as exc:
            raise RuntimeError(f"OKX read-only HTTP status {exc.code}") from None
        except OSError as exc:
            # URLError, socket failures and timeouts must reach the runner's
            # bounded continuity recovery, without exposing transport details.
            raise ConnectionError(
                f"OKX read-only transport failed ({type(exc).__name__})"
            ) from None
        except Exception as exc:
            # Do not expose headers, account response bodies or credentials through exceptions.
            raise RuntimeError(f"OKX read-only transport failed ({type(exc).__name__})") from None
        if result.get("code") != "0" or not isinstance(result.get("data"), list):
            raise RuntimeError("OKX rejected read-only request")
        return result["data"]

    def server_time(self):
        return int(self.get("/api/v5/public/time")[0]["ts"])

    def get_instruments(self):
        return self.get("/api/v5/public/instruments", {"instType": "FUTURES"})

    def get_instrument(self, instrument_id):
        rows = self.get(
            "/api/v5/public/instruments", {"instType": "FUTURES", "instId": instrument_id}
        )
        if len(rows) != 1 or rows[0]["instId"] != instrument_id:
            raise ValueError("Instrument absent or ambiguous")
        return Instrument.parse(rows[0])

    def get_balance(self):
        return self.get("/api/v5/account/balance")

    def get_positions(self):
        return self.get("/api/v5/account/positions")

    def get_open_orders(self):
        return self.get("/api/v5/trade/orders-pending", {"instType": "FUTURES"})

    def get_order(self, instrument_id, order_id):
        return self.get("/api/v5/trade/order", {"instId": instrument_id, "ordId": order_id})

    def get_fills(self):
        return self.get("/api/v5/trade/fills", {"instType": "FUTURES"})
