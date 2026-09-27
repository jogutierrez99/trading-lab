# Resultado del refinamiento de ejecución V2.1 / V4.1

**Completado:** 1.344 backtests, 335 tests aprobados, 672 reproducciones exactas
contra MTF03 y 80.707 archivos protegidos anteriores intactos. Código sin cambios
durante el experimento. No se inició paper ni live trading.

## Conclusión

Ninguna de las cuatro configuraciones recibe `PAPER_TRADING_CANDIDATE` bajo las
reglas operativas conservadoras fijadas antes del backtest. Las tres V2.1 no
aportan mejora en BASE o ADVERSE. Bollinger V4.1 reduce actividad, costes y
drawdown, pero deteriora expectancy, retorno y consistencia temporal.

Esto no es una búsqueda de parámetros: se ejecutaron las ocho configuraciones
pedidas, con los mismos indicadores, tres escenarios de costes, funding,
particiones, 22 folds y 29 segmentos de MTF03. Capital independiente de 10.000
USDT; misma cohorte de 58.296 horas por activo y las mismas 18 exclusiones.
Las configuraciones fueron seleccionadas tras observar la historia MTF: la
confirmación es diagnóstica, no una muestra OOS nueva.

## Comparación principal

Retorno neto BASE del periodo completo, no anualizado. Costes incluyen comisiones,
slippage, spread y coste neto de financiación. Las cuentas no se suman como cartera.

| Activo | Familia | Versión | Retorno % | DD % | PF | Expectancy USDT | Trades | Costes USDT |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | donchian | V2 | 4.92 | 15.47 | 1.05 | 1.50 | 329 | 1708.26 |
| BTCUSDT | donchian | V2.1 | 4.92 | 15.47 | 1.05 | 1.50 | 329 | 1708.26 |
| BTCUSDT | ema_adx | V2 | 6.15 | 10.58 | 1.14 | 4.13 | 149 | 807.65 |
| BTCUSDT | ema_adx | V2.1 | 6.15 | 10.58 | 1.14 | 4.13 | 149 | 807.65 |
| ETHUSDT | ema_adx | V2 | 19.51 | 6.21 | 1.44 | 15.24 | 128 | 829.13 |
| ETHUSDT | ema_adx | V2.1 | 19.51 | 6.21 | 1.44 | 15.24 | 128 | 829.13 |
| BTCUSDT | bollinger | V4 | 13.87 | 17.88 | 1.10 | 2.72 | 509 | 2668.68 |
| BTCUSDT | bollinger | V4.1 | -4.88 | 8.32 | 0.72 | -8.42 | 58 | 298.24 |

## 1. BTC Donchian V2.1

Sin cambio frente a V2 en BASE: retorno +4,92%, drawdown 15,47%, expectancy
1,50 USDT, 329 operaciones y costes 1.708,26 USDT. No reduce churn ejecutado ni
costes. El holdout mantiene +2,80% con 40 operaciones, suficiente según el mínimo
existente; sin embargo, TEST sigue fallando, solo 6/22 folds son positivos y el
retorno FULL ADVERSE es −19,06%.

**Decisión: ARCHIVE_NO_PAPER.** Tiene muestra de holdout suficiente, pero no
estabilidad ni resistencia a costes suficientes. No hay mejora de ejecución BASE
que justifique continuar esta variante como experimento de paper.

## 2. BTC EMA_ADX V2.1

Sin cambio frente a V2 en BASE: retorno +6,15%, drawdown 10,58%, expectancy
4,13 USDT, 149 operaciones y costes 807,65 USDT. Holdout +0,47% con 22 operaciones,
por debajo de las 30 exigidas. Solo 10/22 folds positivos, TEST negativo y FULL
ADVERSE −1,33%.

**Decisión: ARCHIVE_NO_PAPER.** No se demuestra ahorro de churn/costes ni mejora
de robustez; además persiste `INSUFFICIENT_DATA`.

## 3. ETH EMA_ADX V2.1

Resultados idénticos a V2 en todos los escenarios y ventanas evaluados: FULL BASE
+19,51%, drawdown 6,21%, expectancy 15,24 USDT, 128 operaciones y costes 829,13
USDT. FULL ADVERSE permanece positivo (+8,92%), 11/22 folds positivos y holdout
+3,14%, con expectancy 19,60 USDT y PF 1,65.

**Decisión: ARCHIVE_NO_PAPER por muestra insuficiente.** El holdout solo tiene
16 operaciones. Es el único motivo que impide la etiqueta operativa bajo las
reglas congeladas de esta fase; no se debe confundir con una estrategia que falla
todos los controles. Se conserva `INSUFFICIENT_DATA` y no se reduce el mínimo.
V2.1 tampoco aporta una mejora observable sobre V2.

## 4. BTC Bollinger V4.1

Pasa de 509 a 58 operaciones (−88,61%) y de 2.668,68 a 298,24 USDT de costes
(−88,82%). El drawdown baja de 17,88% a 8,32%. Es una reducción de exposición y
actividad, pero no una mejora de calidad:

- Retorno: +13,87% → −4,88%.
- Expectancy: +2,72 → −8,42 USDT por operación.
- Profit factor: 1,10 → 0,72.
- Folds positivos: 9/22 → 5/22; dos folds quedan sin retorno.
- En los 29 segmentos BASE, el retorno mejora en 11, empeora en 16 y empata en 2.
- Holdout: −1,11% → −0,87%, pero las operaciones bajan de 62 a 6 y la expectancy
  empeora de −1,79 a −14,57 USDT. El menor quebranto agregado no demuestra mejor timing.
- Incluso ZERO pierde −2,28%; ADVERSE pierde −8,12%. El problema no se explica
  únicamente por costes.

Las 1.502 señales horarias generan 58 entradas, 1.009 expiraciones y 435
invalidaciones; se registran 174 bloqueos por extensión. La edad media de las
entradas es 0,797 horas (47,8 minutos), mediana 45 minutos; distancia media de
fill 0,299 ATR. Estos datos describen las señales ejecutadas, no prueban ventaja
frente a esperar otro tiempo. No se ajustó la ventana tras observarlos.

**Decisión: ARCHIVE_NO_PAPER.** Ahorra costes, pero no mantiene expectancy,
estabilidad ni muestra suficiente. Además V4.1 cambia el origen a una oportunidad
1h congelada: la comparación no aísla únicamente la calidad del timing 15m.

## Qué hicieron realmente los controles V2.1

En FULL BASE no se activó el bloqueo por cooldown o extensión para estas tres
configuraciones. Los 662, 259 y 297 bloqueos etiquetados como duplicados corresponden
a señales recibidas con posición abierta. El motor original ya las ignoraba:
**no son operaciones adicionales eliminadas por el refinamiento**.

Sí hay una diferencia en ZERO para BTC Donchian y BTC EMA_ADX: un bloqueo de
cooldown aparece en FULL, HOLDOUT y las ventanas solapadas que contienen el mismo
evento. No son cuatro eventos distintos. FULL ZERO baja de 24,39% a 24,12% y de
14,32% a 14,00%, respectivamente. BASE/ADVERSE no cambian. La menor diferencia
ZERO−BASE no es ahorro de costes ejecutados: procede de cambiar una operación
sin costes. ETH EMA_ADX no cambia en ninguna de las 168 ventanas/escenarios de
su pareja. Los 29 segmentos BASE quedan idénticos en las tres parejas V2/V2.1.

## Nota de trazabilidad en límites de segmento

El contador observacional de señales del baseline ETH EMA_ADX FULL BASE es 426,
frente a 425 objetos de ejecución V2.1. La diferencia es el cierre de
2023-11-10 00:00 UTC, justo al terminar el segmento 25: no existe una siguiente
apertura ejecutable dentro de ese segmento. El baseline cuenta ese cierre bruto;
la política de ejecución no crea una oportunidad al otro lado del hueco. No hubo
trade, ahorro de costes ni cambio de regla principal por esa diferencia. Al comparar
contadores hay que distinguir señales brutas al cierre y oportunidades ejecutables.

## Criterios y riesgos pendientes

La etiqueta operativa se evaluó aparte de las clasificaciones históricas. Se
exigieron expectancy/PF/Sharpe positivos según el protocolo, ADVERSE positivo,
validación temporal, al menos 30 operaciones FULL y HOLDOUT y ausencia de deterioro
frente al baseline en las medidas predeclaradas. Se adoptó antes del experimento
una tolerancia conservadora de cero deterioro, salvo precisión numérica. En esta
fase la baja muestra no se admite como candidata. No se relajaron criterios tras
ver resultados ni se sustituyó `PROMISING_BUT_UNCONFIRMED`.

Continúan abiertos el sesgo de selección sobre historia observada, el modelo de
margen histórico asumido, spread fijo sin cotizaciones observadas, la ambigüedad
intrabar y las muestras pequeñas indicadas. `MARGIN_MODEL_ASSUMED` se mantiene.
Archivar aquí significa no promover estas variantes a paper con la evidencia
actual; no elimina estrategias, datos ni artefactos.

## Evidencia y archivos

- [Protocolo previo](execution-refinement-design.md).
- [Informe completo del batch](../results/batch_execution_refinement/20260927T095107Z-e9c66424fbd6/summary.md).
- [Deltas por pareja](../results/batch_execution_refinement/20260927T095107Z-e9c66424fbd6/paired_deltas.csv).
- [Holdout](../results/batch_execution_refinement/20260927T095107Z-e9c66424fbd6/holdout.csv).
- [Clasificación operativa](../results/batch_execution_refinement/20260927T095107Z-e9c66424fbd6/paper_trading_candidates.md).
- [Verificación final](../results/batch_execution_refinement/20260927T095107Z-e9c66424fbd6/final_verification.json).

El batch también conserva config, results, metrics, trades, signals,
signal_lifecycle, segment_metrics, costs y equity en CSV; ledger SQLite;
JSON/Parquet por ejecución; código congelado y manifiesto de integridad.
`equity.csv` ocupa aproximadamente 1,15 GB: las curvas por ejecución también están
separadas en Parquet para consultarlas sin cargar todo el CSV.

El experimento termina aquí. No se lanzó paper trading y no se modificaron
parámetros para corregir a posteriori los resultados negativos.
