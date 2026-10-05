"""Required strategy inputs versus nonblocking observation feeds."""


def instrument_lookup(config, broker):
    if config.data_protocol == "rmm_4h":
        from quant_lab.brokers.instruments import Instrument

        instruments = {}
        now = broker.server_time()
        available = broker.get_instruments()
        for asset in config.instruments:
            matches = []
            for row in available:
                if not row["instId"].startswith(asset + "-"):
                    continue
                try:
                    instrument = Instrument.parse(row)
                except (ValueError, KeyError):
                    continue
                if (
                    row.get("ctMult", "1") in {"", "1"}
                    and int(row.get("expTime") or 0) > now + 8 * 86400000
                ):
                    matches.append((int(row["expTime"]), instrument.instrument_id, instrument))
            if not matches:
                raise ValueError(f"No eligible {asset} linear EEA demo X-Perp")
            selected = max(matches)[2]
            instruments[selected.instrument_id] = selected
        return instruments, []
    instruments, warnings = {}, []
    for asset, instrument in config.instruments.items():
        try:
            instruments[instrument] = broker.get_instrument(instrument)
        except (ValueError, RuntimeError, OSError) as exc:
            if asset == "ETH":
                raise
            warnings.append(
                {
                    "instrument": instrument,
                    "timeframe": "metadata",
                    "reason": f"Instrument lookup failed ({type(exc).__name__})",
                }
            )
    return instruments, warnings


def history(config, feed, instrument, timeframe, *, since=None, full=True):
    """An optional failure remains visible; recent bars never certify its warmup."""
    required = config.required_feed(instrument, timeframe)
    if config.data_protocol == "rmm_4h" and timeframe == "4h":
        return feed.rmm_history(instrument, config.warmup_bars if full else 2, since=since), None
    try:
        bars = feed.history(instrument, timeframe, config.warmup_bars if full else 2, since=since)
        return bars, None
    except (ValueError, RuntimeError, OSError) as exc:
        if required:
            raise
        warning = {
            "instrument": instrument,
            "timeframe": timeframe,
            "reason": str(exc),
            "warmup_verified": False,
            "role": "monitoring",
            "blocks_signals": False,
        }
        try:
            bars = feed.history(instrument, timeframe, 2)
        except (ValueError, RuntimeError, OSError):
            bars = []
        return bars, warning
