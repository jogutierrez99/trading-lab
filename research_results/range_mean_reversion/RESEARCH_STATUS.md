# Range Mean Reversion — RESEARCH ONLY

Fecha: 2026-10-04. Estrategia 1.0.0 implementada; investigación histórica pendiente.

`range_mean_reversion_v1_btc_eth_15m`: PREPARED_NOT_EXECUTED.
Una configuración predeclarada, BTC/ETH 15m, contexto 1h cerrado,
LONG_ONLY/SHORT_ONLY/LONG_SHORT y BASE/ADVERSE. Sin selección ni tuning.

Rango previo causal, excursión fallida y target midpoint congelado; stop externo
con buffer ATR y salida por pérdida del régimen. Se ha verificado la ejecución
con casos sintéticos pequeños, no resultados económicos reales.
Precios USD-M y ejecución synthetic sin funding ni liquidaciones.

[Protocolo y comandos](../../docs/intraday-strategies-v1.md).
Los resultados futuros se publican mediante lab.py publish, con run IDs y hashes;
datasets, equity, trades y ledger permanecen locales. Sin promoción paper/forward
ni commit/push automático.
