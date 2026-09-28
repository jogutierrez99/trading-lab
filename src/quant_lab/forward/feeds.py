"""Required strategy inputs versus nonblocking observation feeds."""


def instrument_lookup(config, broker):
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
