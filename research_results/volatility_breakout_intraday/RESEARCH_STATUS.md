# Volatility Breakout Intraday — RESEARCH ONLY

Fecha: 2026-10-04. Estrategia 1.0.0 implementada; investigación histórica pendiente.

`volatility_breakout_intraday_v1_btc_eth_15m`: PREPARED_NOT_EXECUTED.
Una configuración predeclarada, BTC/ETH 15m, contexto 1h cerrado,
LONG_ONLY/SHORT_ONLY/LONG_SHORT y BASE/ADVERSE. Sin selección ni tuning.

Se han comprobado contratos y ejecución sintética pequeña; no se ha ejecutado
el experimento histórico real. Datos USD-M fijados, ejecución synthetic sin funding
ni liquidaciones. Los tests no acreditan edge ni elegibilidad paper/forward.

[Protocolo y comandos](../../docs/intraday-strategies-v1.md).
Los resultados futuros se publican mediante lab.py publish, con run IDs y hashes;
datasets, equity, trades y ledger permanecen locales. Sin commit/push automático.
