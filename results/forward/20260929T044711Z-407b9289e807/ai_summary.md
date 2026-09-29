# Forward Test — AI Summary

## Session

{"config": {"forward": {"allow_live_trading": false, "broker": "okx", "data_protocol": "eth_v1_required_1h_15m", "environment": "demo", "heartbeat_seconds": 30, "inherited_profile": "../profiles/mtf_series.yaml", "instruments": {"BTC": "BTC-USD_UM_XPERP-310328", "ETH": "ETH-USD_UM_XPERP-310328"}, "max_reconnects": 8, "mode": "signal_only", "output": "../../results/forward", "strategies": ["eth_trend_pullback_v1", "eth_trend_pullback_v1_optional_15m_fill"], "trading_enabled": false, "warmup_bars": 800}, "inherited": {"capital": 10000.0, "costs": {"adverse": {"slippage_pct": 0.1, "spread_pct": 0.02, "trading_fee_pct": 0.1}, "base": {"slippage_pct": 0.02, "spread_pct": 0.01, "trading_fee_pct": 0.05}, "zero": {"slippage_pct": 0.0, "spread_pct": 0.0, "trading_fee_pct": 0.0}}, "risk": {"atr_multiplier": 2.0, "atr_period": 14, "max_exposure_pct": 25.0, "max_holding_bars": 72, "max_position_pct": 25.0, "min_position_pct": 5.0, "position_pct": 25.0, "risk_per_trade_pct": 0.5, "risk_reward": 2.0, "sizing_method": "stop_risk", "stop_enabled": true, "stop_method": "atr", "take_profit_enabled": false, "target_volatility_pct": 20.0, "trailing_atr_multiplier": null, "trailing_basis": "high_low", "volatility_period": 720}, "source_run": "results/batch_006_bollinger_long_short/20260926T103758Z-dd7672b4fa25"}, "instruments": {"BTC-USD_UM_XPERP-310328": {"base": "BTC", "contract_size": "1", "instrument_id": "BTC-USD_UM_XPERP-310328", "lot_size": "0.0001", "max_leverage": "10", "min_size": "0.0001", "settlement_currency": "USD", "tick_size": "0.1"}, "ETH-USD_UM_XPERP-310328": {"base": "ETH", "contract_size": "0.001", "instrument_id": "ETH-USD_UM_XPERP-310328", "lot_size": "1", "max_leverage": "10", "min_size": "1", "settlement_currency": "USD", "tick_size": "0.01"}}}, "end": null, "parity_receipt": "reports\\forward\\preflight\\20260929T044702Z-f292ae536143.json", "session_id": "20260929T044711Z-407b9289e807", "start": "2026-09-29T04:47:11.242168+00:00", "status": "running", "stream_id": "8a6b6aa8f9ec161d936129af0508f665f15af0fc6da772f4e9d0a4b50554d37e"}

## Data health

{"BROKER_SNAPSHOT": 1, "HEARTBEAT": 1831, "MARKET_BAR_CLOSED": 1685, "MONITORING_WARNING": 1, "MONITOR_BAR_CLOSED": 2495, "ORDER_INTENT_CREATED": 2, "ORDER_SKIPPED_SIGNAL_ONLY": 2, "POSITION_SIZE_CALCULATED": 2, "POSITION_SNAPSHOT": 2, "SIGNAL_GENERATED": 1, "STOP_CALCULATED": 2, "TIMING_FILL_SELECTED": 1, "TIMING_WINDOW_STARTED": 1, "data_gaps_resolved": 1, "data_gaps_total": 1, "data_gaps_unresolved": 0, "reconnections": 1, "recovered_bars": 3}

## Signals

{"eth_trend_pullback_v1": {"average_theoretical_entry": 2695.4937050000003, "hypothetical_orders": 1, "signals_generated": 1, "sizes": ["702"], "stops": [2627.65]}, "eth_trend_pullback_v1_optional_15m_fill": {"average_theoretical_entry": 2692.4729500000003, "hypothetical_orders": 1, "signals_generated": 1, "sizes": ["702"], "stops": [2624.63]}}

## Timing

{"TIMING_FILL_SELECTED": 1, "TIMING_WINDOW_STARTED": 1}

## Risk

{"accounts": "independent alternatives, not a combined portfolio", "average_notional": 1891.1762959050002, "entry_exposure_cap_pct": 25, "max_notional": 1892.2365809100002, "max_theoretical_entry_exposure_pct": 18.9223658091}

## Differences / warnings

OKX EU settlement currency is recorded from API instrument metadata (USD or USDC, never assumed equivalent). Binance USD-M USDT evidence is not equivalent. Quotes and shadow occupancy are estimates, not exchange fills. No funding, mark-price liquidation or account PnL replication is claimed. Recovery does not invent missed entries. Runtime parity/sizing evidence must be reviewed before SIGNAL_PIPELINE_OK. Demo routing is unavailable.

## Errors

[{"audits": [{"bars_expected": 814, "bars_present": 814, "continuity_ok": true, "duplicates": 0, "duplicates_deduplicated": 1612, "expected_end": "2026-09-28T18:45:00+00:00", "expected_interval": "0 days 00:15:00", "expected_start": "2026-09-20T07:30:00+00:00", "instrument": "ETH-USD_UM_XPERP-310328", "missing_timestamps": [], "out_of_order": false, "timeframe": "15m"}, {"bars_expected": 804, "bars_present": 804, "continuity_ok": true, "duplicates": 0, "duplicates_deduplicated": 1603, "expected_end": "2026-09-28T18:00:00+00:00", "expected_interval": "0 days 01:00:00", "expected_start": "2026-08-26T07:00:00+00:00", "instrument": "ETH-USD_UM_XPERP-310328", "missing_timestamps": [], "out_of_order": false, "timeframe": "1h"}], "continuity_verified": true, "event_id": "74f36ec13e201a6e18b57389207c231a1364da57943d01acd75f030083139ebc", "key": "62cdf6f812414fb3bf87b0bce9c54d62", "kind": "DATA_GAP", "missing_timestamps": [], "reason": "ConnectionError", "reconnected": true, "recovered_bars": 3, "resolution": "REST_CONTINUITY_VERIFIED", "resolved": true, "resolved_at": "2026-09-28T19:10:44.592141+00:00", "source_session": "20260928T153046Z-2ad54a3f6bb0", "source_stream": "20ca59c4bd8864b33cdc00b6be3debc69229baf0bf379c89b584254f6c836d28"}]

## Readiness

SIGNAL_PIPELINE_OK
