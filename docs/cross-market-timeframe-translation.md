# Frozen timeframe translations

Adapter v1. No parameter search. Original configs and signal predicates preserved.
All risk ATR periods remain bars; ATR multiples/percentages unchanged.
One-bar lags/crossings refer to consecutive candles, not one elapsed hour.
Quantile720 is interpreted as a30-day empirical distribution; probabilities unchanged.
This is an explicit temporal interpretation, not a claim of identical signals.
Features reset after excluded days; no position crosses a gap or partition.

| Strategy | Translation |
|---|---|
| trend_following | Donchian20 and EMA200: intentional bars. ATR14: bars; trailing3 ATR unchanged. |
| time_series_momentum | ROC14d:336/84/14 bars. Original extra one-bar lag retained. |
| mean_reversion | Bollinger20/std2 and RSI14: intentional bars. RSI thresholds30/70 unchanged. |
| vol_momentum | ROC30d and volatility30d:720/180/30; EMA200: bars. Annualization sqrt(8760/2190/365). |
| donchian_adx | Donchian40, EMA200 and ADX14: intentional bars. ADX threshold20 unchanged. |
| bb_squeeze | BB20/std2 and EMA200: bars. Prior quantile30d and recent squeeze24h:720/180/30 and24/6/1. |
| regime_meanrev | BB20/std2, EMA200, RSI14 and ADX14: bars. RSI30, ADX20, distance5% unchanged. |
| ema_pullback | EMA50/200, pullbackEMA50, RSI14: bars. Previous-bar touch retained; time stop120h:120/30/5. |
| mtf_momentum | Fixed completed4h EMA50/200 and ROC30d; entry channel72h. Only1h supported: higher-frame hypothesis otherwise changes. |
| atr_breakout | EMA50/200 and ATR14: bars. Quantile30d:720/180/30. Prior-bar ATR/close and K1.5 unchanged. |
| trend_strength | EMA50/200: bars. ROC7d/60d, slope24h and channel48h:168/42/7,1440/360/60,24/6/1,48/12/2. |
| regime_trend | EMA50/200, ADX14, ATR14: bars. ROC30d, quantile30d, channel48h. Threshold18 unchanged. |
| dual_momentum | EMA200: bars. ROC7d/30d:168/42/7 and720/180/30. Raw ROC comparison unchanged. |
| vol_expansion_trend | EMA50/200 and ATR14: bars. ROC7d, quantile30d, ATR-ratio mean24h and channel24h. |
| low_vol_pullback | EMA20/50/200, RSI14, ATR14: bars; previous-bar touch. Quantiles30d. Time stop120h:120/30/5. |
| channel_break_retest | EMA50/200, ATR14: bars. Channel24h:24/6/1. Explicit retest24 CANDLES retained. Time stop168h:168/42/7. |
| trend_acceleration | EMA50/200: bars. Slope12h, slope72h, acceleration lag24h and channel24h. Time stop240h. Daily12h unrepresentable: skipped. |
| rsi_momentum_reset | EMA50/200, RSI14, ATR14: bars. ROC30d; reset expiry48h:48/12/2. Crossings remain consecutive candles. |
| vol_contraction_expansion | EMA50/200 and ATR14: bars. ROC7d, prior quantiles30d, channel24h. Explicit count>=6 of previous24 CANDLES retained. |

Versions1.0.0. 108 evaluable combinations;6 skips: MTF4h/1d and acceleration1d, both assets.
Warmup uses preceding candles within the same continuous segment. Initial segment starts cold; incomplete indicators cannot emit entries.
Holdout follows train/validation/test for ALL combinations. Full/annual diagnostics follow unlock. No selection stage exists.
