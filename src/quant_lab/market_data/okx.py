"""REST bootstrap/recovery and demo business WebSocket candle updates."""

import json
import time
from dataclasses import asdict, dataclass
from math import isclose, isfinite

import pandas as pd

from quant_lab.brokers.okx_demo import USER_AGENT, WS_URL
from quant_lab.mtf_features import STEPS

BARS = {"15m": "15m", "1h": "1H", "4h": "4H"}


@dataclass(frozen=True)
class Bar:
    instrument_id: str
    timeframe: str
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def close_time(self):
        return self.timestamp + STEPS[self.timeframe]

    @property
    def key(self):
        return f"{self.instrument_id}|{self.timeframe}|{self.timestamp.isoformat()}"

    def row(self):
        return asdict(self)


def parse_bar(instrument, timeframe, raw, now):
    if timeframe not in BARS or len(raw) != 9:
        raise ValueError("Invalid candle message")
    if raw[8] != "1":
        return None
    stamp = pd.Timestamp(int(raw[0]), unit="ms", tz="UTC")
    if stamp.value % STEPS[timeframe].value or stamp + STEPS[timeframe] > now:
        raise ValueError("Causal violation: unclosed or misaligned confirmed candle")
    # volCcy (index 6) is base quantity for derivatives; index 5 is contracts.
    o, h, low, c, volume = [float(raw[i]) for i in (1, 2, 3, 4, 6)]
    if (
        not all(isfinite(v) for v in (o, h, low, c, volume))
        or min(o, h, low, c) <= 0
        or volume < 0
        or low > min(o, c)
        or h < max(o, c)
        or low > h
    ):
        raise ValueError("Invalid OHLCV")
    return Bar(instrument, timeframe, stamp, o, h, low, c, volume)


class DataGap(ValueError):
    def __init__(self, message, *, bars=()):
        super().__init__(message)
        self.bars = list(bars)


@dataclass(frozen=True)
class FeedIssue:
    instrument_id: str
    timeframe: str
    reason: str


class CandleBook:
    def __init__(self):
        self.bars = {}

    def add(self, bar):
        rows = self.bars.setdefault((bar.instrument_id, bar.timeframe), {})
        if bar.timestamp in rows:
            previous = rows[bar.timestamp]
            if not all(
                isclose(getattr(previous, field), getattr(bar, field), rel_tol=1e-10, abs_tol=1e-10)
                for field in ("open", "high", "low", "close", "volume")
            ):
                raise ValueError("Conflicting closed candle revision")
            return False
        if rows and bar.timestamp != max(rows) + STEPS[bar.timeframe]:
            raise DataGap(f"Non-contiguous {bar.instrument_id} {bar.timeframe}")
        rows[bar.timestamp] = bar
        return True

    def frame(self, instrument, timeframe):
        rows = self.bars.get((instrument, timeframe), {})
        if not rows:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"],
                index=pd.DatetimeIndex([], tz="UTC"),
            )
        return (
            pd.DataFrame([r.row() for r in rows.values()])
            .set_index("timestamp")[["open", "high", "low", "close", "volume"]]
            .sort_index()
        )


class OKXMarketData:
    def __init__(self, broker, instruments):
        self.broker, self.instruments = broker, instruments
        self._clock = None
        self._clock_at = 0.0
        self.required_feeds = None  # None means every subscribed channel is mandatory.

    def now(self):
        elapsed = time.monotonic() - self._clock_at
        if self._clock is None or elapsed >= 30:
            self._clock = pd.Timestamp(self.broker.server_time(), unit="ms", tz="UTC")
            self._clock_at = time.monotonic()
            elapsed = 0.0
        return self._clock + pd.Timedelta(seconds=elapsed)

    def history(self, instrument, timeframe, count, *, since=None):
        now = self.now()
        rows, after = {}, None
        unconfirmed = set()
        for _ in range(200):
            params = {"instId": instrument, "bar": BARS[timeframe], "limit": "100"}
            if after is not None:
                params["after"] = str(after)
            raw_rows = self.broker.get("/api/v5/market/history-candles", params)
            if not raw_rows:
                break
            for raw in raw_rows:
                bar = parse_bar(instrument, timeframe, raw, now)
                if bar is None:
                    unconfirmed.add(pd.Timestamp(int(raw[0]), unit="ms", tz="UTC"))
                if bar is not None:
                    if bar.timestamp in rows and rows[bar.timestamp] != bar:
                        raise ValueError("Conflicting REST candle")
                    rows[bar.timestamp] = bar
            oldest = min(int(r[0]) for r in raw_rows)
            if after is not None and oldest >= after:
                raise DataGap("REST pagination made no progress")
            after = oldest
            if (since is None and len(rows) >= count) or (
                since is not None and rows and min(rows) <= since
            ):
                break
            time.sleep(0.12)
        result = sorted(rows.values(), key=lambda b: b.timestamp)
        result = (
            [r for r in result if r.timestamp >= since] if since is not None else result[-count:]
        )
        expected_last = now.floor(STEPS[timeframe]) - STEPS[timeframe]
        if not result or result[-1].timestamp < expected_last:
            raise DataGap("REST latest closed candle unavailable", bars=result)
        if since is None and len(result) < count:
            raise DataGap("Insufficient warmup", bars=result)
        if since is not None and result[0].timestamp > since:
            raise DataGap("REST recovery did not cover missing history", bars=result)
        for previous, current in zip(result, result[1:], strict=False):
            if current.timestamp - previous.timestamp != STEPS[timeframe]:
                missing = previous.timestamp + STEPS[timeframe]
                reason = "OKX confirm=0" if missing in unconfirmed else "missing from OKX response"
                raise DataGap(
                    f"REST history has a gap: {instrument} {timeframe}; "
                    f"first missing open={missing.isoformat()}; "
                    f"next confirmed open={current.timestamp.isoformat()}; {reason}. "
                    "Refusing to generate signals without continuous confirmed warmup.",
                    bars=result,
                )
        return result

    def quote(self, instrument, boundary):
        row = self.broker.get("/api/v5/market/ticker", {"instId": instrument})[0]
        observed = pd.Timestamp(int(row["ts"]), unit="ms", tz="UTC")
        now = self.now()
        price = float(row["askPx"])
        if not isfinite(price) or price <= 0 or not boundary <= observed <= now:
            raise ValueError("Invalid or pre-signal quote")
        if now - observed > pd.Timedelta(seconds=30) or now - boundary > pd.Timedelta(seconds=90):
            raise ValueError("Stale quote or late decision; no retroactive entry")
        return price, observed

    def updates(self):
        from websockets.exceptions import ConnectionClosed

        try:
            yield from self._updates()
        except ConnectionClosed:
            raise ConnectionError("Demo WebSocket disconnected") from None

    def _updates(self):
        # Optional dependency imported only when explicitly starting the runner.
        from websockets.sync.client import connect

        channels = [
            {"channel": "candle" + bar, "instId": inst}
            for inst in self.instruments
            for bar in BARS.values()
        ]
        with connect(
            WS_URL, user_agent_header=USER_AGENT, open_timeout=15, close_timeout=5
        ) as socket:
            socket.send(json.dumps({"op": "subscribe", "args": channels}))
            while True:
                try:
                    message = socket.recv(timeout=20)
                except TimeoutError:
                    socket.send("ping")
                    message = socket.recv(timeout=10)
                if message == "pong":
                    yield None
                    continue
                payload = json.loads(message)
                if payload.get("event") == "error":
                    arg = payload.get("arg", {})
                    tf = next(
                        (
                            tf
                            for tf, label in BARS.items()
                            if "candle" + label == arg.get("channel")
                        ),
                        None,
                    )
                    if (
                        self.required_feeds is not None
                        and tf
                        and arg in channels
                        and (arg["instId"], tf) not in self.required_feeds
                    ):
                        yield FeedIssue(arg["instId"], tf, "Monitoring subscription rejected")
                        continue
                    raise RuntimeError("OKX WebSocket subscription rejected")
                if "data" not in payload:
                    continue
                arg = payload["arg"]
                if arg not in channels:
                    raise ValueError("Unexpected candle channel")
                timeframe = next(
                    tf for tf, label in BARS.items() if "candle" + label == arg["channel"]
                )
                now = self.now()
                for raw in sorted(payload["data"], key=lambda r: int(r[0])):
                    try:
                        bar = parse_bar(arg["instId"], timeframe, raw, now)
                    except ValueError:
                        if (
                            self.required_feeds is None
                            or (arg["instId"], timeframe) in self.required_feeds
                        ):
                            raise
                        yield FeedIssue(arg["instId"], timeframe, "Invalid monitoring candle")
                        continue
                    if bar:
                        yield bar
                # Also allow heartbeat/staleness checks during incomplete candle updates.
                yield None
