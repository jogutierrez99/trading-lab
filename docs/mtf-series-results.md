# Resultados de la serie MTF 01–04

Estado: 7.200 backtests finalizados (912 + 912 + 5.376). Sin supervivientes para
MTF04. Integridad de las ejecuciones verificada: código congelado sin cambios
y 51.579 archivos protegidos anteriores intactos.

## Verificación previa

318 tests aprobados; Ruff, formato y dependencias sin errores. Código congelado:
`1a2fede7cec9fd00ba2f1fb4b2d8043ba5c8d3458d4de26a5089b9dfab377bcc`.
Las comprobaciones inicial y final confirmaron 51.579 archivos protegidos
anteriores intactos. Los ledgers y hashes de trades/equity verifican las 7.200
ejecuciones completadas, sin fallos.

Los resultados corresponden a cuentas independientes de 10.000 USDT sobre
BTCUSDT y ETHUSDT USD-M, con financiación histórica y costes BASE heredados.
La historia ya fue observada: estas particiones son diagnósticas, no OOS nuevo.

## Histórico original: V1 y V2

MTF01: 912 ejecuciones completadas y verificadas. Siete de ocho combinaciones
obtienen retorno FULL BASE positivo; ninguna cumple todos los criterios heredados.

MTF02: 912 ejecuciones completadas y verificadas. Ocho de ocho combinaciones
obtienen retorno FULL BASE positivo; ninguna cumple todos los criterios heredados.

El filtro 4h reduce drawdown, número de operaciones y costes en las ocho parejas.
Mejora expectancy en siete, pero retorno en solo tres. Menor actividad y drawdown
no equivalen por sí solos a un sistema más estable: hay fallos temporales, folds
insuficientemente positivos o pocas operaciones en holdout.

| asset | family | architecture | return_pct | max_drawdown_pct | expectancy | closed_trades | total_costs | classification |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | trend_pullback | V1 | 14.18 | 16.01 | 2.61 | 543 | 2914.53 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;COST_SENSITIVE |
| BTCUSDT | bollinger | V1 | 6.04 | 22.57 | 0.64 | 940 | 4892.38 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;COST_SENSITIVE;FAILED_TEMPORAL_VALIDATION |
| BTCUSDT | donchian | V1 | -3.92 | 26.37 | -0.51 | 775 | 3957.37 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;FAILED_AFTER_COSTS;FAILED_TEMPORAL_VALIDATION |
| BTCUSDT | ema_adx | V1 | 6.43 | 11.04 | 2.25 | 285 | 1522.65 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;COST_SENSITIVE;FAILED_TEMPORAL_VALIDATION |
| ETHUSDT | trend_pullback | V1 | 50.53 | 24.06 | 9.41 | 537 | 3659.09 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED |
| ETHUSDT | bollinger | V1 | 32.15 | 26.94 | 3.50 | 919 | 5827.37 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;COST_SENSITIVE;FAILED_TEMPORAL_VALIDATION |
| ETHUSDT | donchian | V1 | 37.45 | 24.24 | 4.97 | 754 | 5154.74 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;COST_SENSITIVE;FAILED_TEMPORAL_VALIDATION |
| ETHUSDT | ema_adx | V1 | 62.38 | 8.72 | 23.99 | 260 | 2024.00 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;FAILED_TEMPORAL_VALIDATION |
| BTCUSDT | trend_pullback | V2 | 8.79 | 11.35 | 2.42 | 363 | 2046.99 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;COST_SENSITIVE;FAILED_TEMPORAL_VALIDATION |
| BTCUSDT | bollinger | V2 | 8.12 | 18.84 | 1.48 | 550 | 2956.70 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;COST_SENSITIVE;FAILED_TEMPORAL_VALIDATION |
| BTCUSDT | donchian | V2 | 10.87 | 15.56 | 2.87 | 379 | 2228.22 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;COST_SENSITIVE;FAILED_TEMPORAL_VALIDATION |
| BTCUSDT | ema_adx | V2 | 9.26 | 10.58 | 5.26 | 176 | 1038.65 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;INSUFFICIENT_DATA;FAILED_TEMPORAL_VALIDATION |
| ETHUSDT | trend_pullback | V2 | 45.76 | 15.91 | 13.46 | 340 | 2560.57 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED |
| ETHUSDT | bollinger | V2 | 19.79 | 21.61 | 3.61 | 549 | 3329.15 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;COST_SENSITIVE;FAILED_TEMPORAL_VALIDATION |
| ETHUSDT | donchian | V2 | 31.79 | 13.45 | 8.83 | 360 | 2550.84 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;FAILED_TEMPORAL_VALIDATION |
| ETHUSDT | ema_adx | V2 | 42.40 | 6.21 | 27.18 | 156 | 1280.86 | DIAGNOSTIC_ONLY;MARGIN_MODEL_ASSUMED;INSUFFICIENT_DATA |

## Cohorte común autorizada

La comparación V1–V4 excluye los mismos 18 días completos para ambos activos:
58.296 horas válidas por activo, frente a las 58.728 originales. Se conservan las
fechas de las particiones y los 22 folds; los huecos generan 29 segmentos continuos
frente a los 11 originales. Los resultados originales V1/V2 no se sustituyen.

V1→V2 mide el efecto del filtro 4h. V2→V3 cambia también setup, disparador y
resolución de ejecución; no permite atribuir todo el cambio a un filtro.
V3→V4 cambia alineación por recuperación tras retroceso/consolidación.

El retraso informado es la edad del toque previo en entradas ejecutadas; no
prueba que una entrada V4 sea la misma oportunidad V1 tomada más tarde.
Los retornos futuros de señales rechazadas son descriptivos, sin costes y con
solapamiento: no son beneficios ejecutables de una estrategia alternativa.


## V1–V4 sobre las mismas fechas

Retorno neto FULL BASE en porcentaje para todo el periodo, no anualizado.

| asset | family | V1 | V2 | V3 | V4 |
|---|---|---|---|---|---|
| BTCUSDT | bollinger | 0.51 | 4.69 | -0.13 | 13.87 |
| BTCUSDT | donchian | -7.21 | 4.92 | 1.39 | -2.02 |
| BTCUSDT | ema_adx | 1.91 | 6.15 | -1.19 | 0.19 |
| BTCUSDT | trend_pullback | 11.22 | 8.08 | 12.94 | 1.22 |
| ETHUSDT | bollinger | 31.64 | 21.28 | 14.43 | -6.65 |
| ETHUSDT | donchian | 34.54 | 15.96 | 13.89 | 7.20 |
| ETHUSDT | ema_adx | 47.87 | 19.51 | 6.43 | -0.00 |
| ETHUSDT | trend_pullback | 30.35 | 15.68 | 10.89 | 11.56 |

Número de parejas que mejoran cada medida, de un total de ocho. Son comparaciones
descriptivas, no pruebas de significación estadística.

| Cambio | Mayor retorno | Menor drawdown | Mayor expectancy | Menos trades | Menores costes |
|---|---|---|---|---|---|
| V1 → V2 | 3 | 8 | 6 | 8 | 8 |
| V2 → V3 | 1 | 2 | 1 | 2 | 2 |
| V3 → V4 | 3 | 4 | 2 | 5 | 5 |

V2 reduce actividad, coste y drawdown en todas las parejas; el retorno mejora
solo en tres. V3 aumenta actividad y costes en seis parejas, con mayor drawdown
en seis y mayor retorno solo en una. V4 ofrece resultados mixtos: el retroceso
no aporta una mejora consistente entre familias y activos. La reducción de
operaciones tampoco garantiza mayor expectancy.

Los reinicios tras huecos incluyen nuevos periodos de calentamiento de los
indicadores. El contador de rechazo 4h incluye régimen incompatible y régimen
todavía no disponible; no debe interpretarse entero como ruido eliminado.

## Elegibilidad y MTF04

Ninguna de las 32 configuraciones comparables obtiene
`PROMISING_BUT_UNCONFIRMED`. No se han relajado los criterios ni escogido otras
reglas tras observar resultados. SHORT_ONLY y LONG_SHORT están implementados
y probados con datos sintéticos, pero no se han ejecutado como nuevo experimento
histórico porque ninguna configuración LONG_ONLY reúne los requisitos.

- `FAILED_TEMPORAL_VALIDATION`: 28/32.
- `INSUFFICIENT_DATA`: 5/32.
- `COST_SENSITIVE`: 24/32.
- `FAILED_AFTER_COSTS`: 6/32.

Las etiquetas pueden solaparse. Un retorno positivo no implica supervivencia.

Ejemplo: EMA+ADX V2 en ETH tiene holdout positivo (3.14%), pero
solo 16 operaciones en él, por debajo de las 30 exigidas. EMA+ADX
V1 en ETH tiene el mayor retorno de la cohorte, pero su holdout es negativo.

## Artefactos y reproducción

- [Protocolo y comandos](mtf-series-design.md).
- [Comparación maestra](../results/mtf_series/20260926T231005Z-328815f654cb/master_table.csv).
- [Evolución y deltas](../results/mtf_series/20260926T231005Z-328815f654cb/summary.md).
- [MTF01 original](../results/batch_mtf_01_baseline/20260926T231006Z-ae31d32a2ab3/summary.md).
- [MTF02 original](../results/batch_mtf_02_regime/20260926T231432Z-ece9e3ef79fa/summary.md).
- [MTF03 comparable](../results/batch_mtf_03_architectures/20260926T231820Z-44cc4dedd4ab/summary.md).

Cada fase conserva configuración, métricas por segmento/costes/activo,
trades, equity, financiación, diagnósticos de señales y hashes de integridad.
La carpeta maestra conserva el código exacto y la exclusión explícita de MTF04.
Las fechas excluidas están en `plan.json → matched_audit → excluded_days`.
