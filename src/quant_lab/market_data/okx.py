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


class QuoteUnavailable(ValueError):
    """A decision has no usable quote; never substitute an old or invented price."""

    def __init__(self, details):
        super().__init__(details["reason"])
        self.details = details


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
        self.rmm_sources = {}
        self.rmm_hours = CandleBook()
        self.last_quotes = {}

    def now(self):
        elapsed = time.monotonic() - self._clock_at
        if self._clock is None or elapsed >= 30:
            self._clock = pd.Timestamp(self.broker.server_time(), unit="ms", tz="UTC")
            self._clock_at = time.monotonic()
            elapsed = 0.0
        return self._clock + pd.Timedelta(seconds=elapsed)

    def rmm_history(self, instrument, count, *, since=None):
        try:
            result = self.history(instrument, "4h", count, since=since)
            self.rmm_source(instrument, "native_4h")
            return result
        except DataGap as native_error:
            from quant_lab.mtf_features import complete_bars

            try:
                hours = self.history(instrument, "1h", count * 4 + 4, since=since)
            except DataGap as hourly_error:
                raise DataGap(
                    f"RMM history unavailable for {instrument}: native 4h: {native_error}; "
                    f"hourly fallback: {hourly_error}. "
                    "Forward cannot start until continuous confirmed OKX DEMO history is "
                    "available; preserve the frozen warmup and do not splice other markets.",
                    bars=hourly_error.bars,
                ) from None
            self.rmm_hours.bars[(instrument, "1h")] = {}
            for hour in hours:
                self.rmm_hours.add(hour)
            frame = pd.DataFrame([b.row() for b in hours]).set_index("timestamp")
            frame = complete_bars(frame[["open", "high", "low", "close", "volume"]], "1h", "4h")
            if since is None:
                frame = frame.tail(count)
            if len(frame) < (count if since is None else 1):
                raise DataGap("RMM 4h resampled warmup incomplete") from None
            expected = self.now().floor("4h") - STEPS["4h"]
            if frame.index[-1] != expected or any(
                frame.index.to_series().diff().dropna() != STEPS["4h"]
            ):
                raise DataGap("RMM resampled 4h continuity incomplete") from None
            self.rmm_source(instrument, "resampled_1h")
            return [Bar(instrument, "4h", t, **r.to_dict()) for t, r in frame.iterrows()]

    def rmm_source(self, instrument, source):
        self.rmm_sources[instrument] = source
        if self.required_feeds is not None:
            self.required_feeds.discard((instrument, "1h"))
            self.required_feeds.discard((instrument, "4h"))
            self.required_feeds.add((instrument, "1h" if source == "resampled_1h" else "4h"))

    def rmm_live_bars(self, bar):
        if self.rmm_sources.get(bar.instrument_id) != "resampled_1h":
            return [bar]
        if bar.timeframe == "4h":
            return []
        output = [bar]
        if (
            bar.timeframe == "1h"
            and self.rmm_hours.add(bar)
            and bar.close_time.value % STEPS["4h"].value == 0
        ):
            from quant_lab.mtf_features import complete_bars

            frame = self.rmm_hours.frame(bar.instrument_id, "1h").tail(4)
            combined = complete_bars(frame, "1h", "4h")
            if len(combined) != 1 or combined.index[0] != bar.close_time - STEPS["4h"]:
                raise DataGap("Incomplete causal live 1h -> 4h group")
            output.insert(
                0, Bar(bar.instrument_id, "4h", combined.index[0], **combined.iloc[0].to_dict())
            )
        return output

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
            raise DataGap(
                f"Insufficient warmup: {instrument} {timeframe}; "
                f"required={count}, available={len(result)}, "
                f"first_open={result[0].timestamp.isoformat()}, "
                f"last_open={result[-1].timestamp.isoformat()}",
                bars=result,
            )
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
        for attempt in range(1, 4):
            observed, price = None, None
            reason = "malformed_quote"
            rows = self.broker.get("/api/v5/market/ticker", {"instId": instrument})
            try:
                observed = pd.Timestamp(int(rows[0]["ts"]), unit="ms", tz="UTC")
                price = float(rows[0]["askPx"])
                if getattr(self, "rmm_reference", False):
                    bid = float(rows[0]["bidPx"])
                    if not isfinite(bid) or bid <= 0 or bid > price:
                        raise ValueError("Invalid bid/ask")
                    price = (price + bid) / 2
            except (IndexError, KeyError, TypeError, ValueError, OverflowError):
                price = None
            now = self.now()
            if observed is not None and observed > now:
                # Cached server time can lag another endpoint: refresh, never relax
                # the timestamp comparison or replace the quote's own timestamp.
                self._clock = None
                now = self.now()
            if price is not None and observed is not None:
                if not isfinite(price) or price <= 0:
                    reason = "invalid_ask"
                elif observed < boundary:
                    reason = "pre_signal_quote"
                elif observed > now:
                    reason = "future_quote"
                elif now - observed > pd.Timedelta(seconds=30):
                    reason = "stale_quote"
                else:
                    reason = None
            if now < boundary or now - boundary > pd.Timedelta(seconds=90):
                reason = "outside_decision_window"
            if reason is None:
                if getattr(self, "rmm_reference", False):
                    self.last_quotes[instrument] = dict(
                        bid=float(rows[0]["bidPx"]),
                        ask=float(rows[0]["askPx"]),
                        quote_observed_at=str(observed),
                        quoted_spread_bps=(float(rows[0]["askPx"]) - float(rows[0]["bidPx"]))
                        / price
                        * 10000,
                    )
                return price, observed
            details = {
                "reason": reason,
                "instrument": instrument,
                "decision_close": boundary,
                "quote_timestamp": observed,
                "checked_at": now,
                "attempts": attempt,
            }
            if reason == "outside_decision_window" or attempt == 3:
                raise QuoteUnavailable(details)
            time.sleep(0.25)

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
                        yield from self.rmm_live_bars(bar)
                # Also allow heartbeat/staleness checks during incomplete candle updates.
                yield None
