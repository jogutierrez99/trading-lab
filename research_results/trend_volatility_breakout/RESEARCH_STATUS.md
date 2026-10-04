# Trend Volatility Breakout — estado de investigación

Fecha: 2026-10-04. Implementación técnica, sin grid histórico ejecutado por el agente.

| Hipótesis | Status | Razón |
|---|---|---|
| trend_volatility_breakout_v1_eth_1h | NEW_HYPOTHESIS | Nueva familia trend + breakout + volatility expansion después de que RSI pullback no demostrara suficiente robustez histórica. |
| trend_volatility_breakout_v1_btc_1h | PREPARED_NOT_EXECUTED | Misma lógica y grid congelado para futura comprobación de portabilidad. |

ETH 1h primero; BTC preparado. 144 configuraciones por mercado/modo. Sin selección
basada en el challenge RSI, sin ampliación del grid tras ver resultados. [Protocolo](../../docs/trend-volatility-breakout.md).
La implementación y los tests no constituyen evidencia económica ni promoción.
Clasificación global vigente; TEST OOS del protocolo específico sobre histórico
observado por el proyecto, sin independencia futura absoluta. No forward automático.

Si falla, descartar o formular otra hipótesis V2 explícita; si supera los gates,
contrastar BTC sin cambiar parámetros. Fases 4h/MTF/trailing/forward requieren
investigación y tareas posteriores. No están implementadas aquí.
