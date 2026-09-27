# Refinamiento de ejecución: protocolo previo

Ocho configuraciones LONG_ONLY: BTC Donchian V2/V2.1, BTC EMA_ADX V2/V2.1,
ETH EMA_ADX V2/V2.1 y BTC Bollinger V4/V4.1. Sin grid ni cambios de indicadores.
Se conserva exactamente la cohorte MTF03, sus 18 exclusiones, 29 segmentos,
particiones y 22 folds TEST; tres escenarios de costes existentes. Son 1.344
ejecuciones independientes de 10.000 USDT. No hay nueva muestra OOS.

## Reutilización y cambio técnico necesario

Se reutilizan señales/features MTF, loaders, validación, risk sizing, funding,
costes, margen y contabilidad. Las estrategias V2/V4 y sus configuraciones no
se editan. El motor recibe un callback opcional de ejecución y los adaptadores
transmiten el callback: sin él conserva su comportamiento. Este cambio es
necesario porque cooldown y consumo dependen de fills reales, no solo de señales.
Cada una de las 672 ejecuciones baseline debe reproducir exactamente los hashes
de trades y equity de MTF03; cualquier divergencia aborta el experimento.
Los snapshots históricos de código y los resultados anteriores se preservan.

## Decisiones congeladas antes de resultados

- V2.1: cada cierre 1h válido V2 es una oportunidad distinta, con ID determinista.
  La entrada solo se intenta en la apertura siguiente. No se reinterpretan varias
  señales consecutivas como un único episodio de tendencia. El motor anterior ya
  impedía piramidación y entradas simultáneas: no se presupone un fallo histórico.
- Cooldown: una hora desde el instante conocido de salida. Si la salida intrabar
  es ambigua, se considera conocida al cierre de esa vela. Se admite entrar al
  cumplir la hora; se impide reentrada en la propia vela de salida.
- Extensión: distancia absoluta apertura de ejecución menos cierre de origen,
  dividida por ATR14 1h congelado, <=1,5. No se mira high/low/close de la vela
  actual. La distancia de fill registrada incluye slippage/spread modelados.
- Spread dinámico: interfaz que exige cotizaciones observadas y umbral explícito;
  deshabilitada porque este dataset solo tiene spread fijo. Sin valores inventados.
- V4.1: oportunidad 1h definida por la señal Bollinger V2 existente, incluido su
  régimen 4h. El disparador 15m es la recuperación de media Bollinger de V4,
  con toque posterior al origen congelado y ruptura del máximo anterior.
  No genera oportunidades nuevas. Como también cambia el origen de señal frente
  a V4, esta pareja no demuestra aisladamente la superioridad del timing 15m.
- Vigencia V4.1: cuatro cierres posteriores de 15m, incluyendo el cuarto a +1h.
  Se cancela si régimen o setup 1h dejan de ser válidos, por extensión, o al vencer.
  A igualdad de timestamp se prioriza la oportunidad más antigua si puede entrar;
  la nueva se registra y cancela por conflicto de prioridad. No se acumula una cola.
- Solo un fill por signal_id. El origen es un objeto inmutable; el estado de
  lifecycle va separado. El ATR congelado fija stop 2 ATR; salida a 72 horas,
  exposición/riesgo y financiación heredados. Sin salidas técnicas nuevas.
- Señales, posiciones y cooldown no cruzan gaps ni límites de ejecución. Features
  se reinician tras gaps físicos; las particiones pueden usar historia causal previa
  para indicadores, pero nunca señales anteriores al inicio de la cuenta.

## Clasificación operativa predeclarada

Las etiquetas históricas se calculan exactamente como antes. La etiqueta separada
PAPER_TRADING_CANDIDATE exige simultáneamente:

1. Expectancy BASE >0, PF >1, Sharpe >0 y retorno ADVERSE >0 en periodo completo.
2. VALIDATION, TEST y HOLDOUT positivos; al menos 50% de folds TEST positivos.
3. Al menos 30 trades FULL y 30 HOLDOUT, conservando INSUFFICIENT_DATA si no cumple.
4. Ningún deterioro frente al baseline en drawdown FULL, expectancy, PF, proporción
   de folds positivos, ni arrastre de costes (retorno ZERO menos BASE).
5. Ningún deterioro de retorno, expectancy o drawdown del HOLDOUT.
6. Pruebas técnicas, reproducibilidad y replay exacto del baseline aprobados.

Se interpreta «material» conservadoramente: tolerancia cero al deterioro, salvo
1e-9 numérico. Se fija antes del backtest, no tras ver resultados. En esta fase no
se admite baja muestra como candidata; no se reducen mínimos ni se sustituyen
clasificaciones históricas. Un incumplimiento produce ARCHIVE_NO_PAPER con motivos.
«Archive» es una conclusión de investigación: no borra archivos ni estrategias.

## Trazabilidad y pruebas

signal_id se deriva de activo/familia/versión/dirección/cierre UTC. Los mismos IDs
pueden aparecer en cuentas independientes; experiment_id define su ámbito.
signals.csv contiene estado final y signal_lifecycle.csv registra transiciones y
motivos. Bloqueos cuentan intentos, no señales únicas. Edad y retraso se expresan
en horas. trades.csv enlaza origin_signal_timestamp con el fill, además del timestamp
del disparador del motor. El baseline tiene instrumentación observacional sin guards.

Antes del batch: causalidad 4h/1h/15m, freeze, expiry, consumo, duplicados, cooldown,
extensión, gaps/warmup, funding/costes, replay determinista y hashes; suite completa,
Ruff, formato y dependencias. Después: ledger y hashes, matriz completa, código
congelado, resultados originales intactos. Informes incluyen todos los costes,
segmentos, folds y holdout, incluso negativos o con poca muestra.

```powershell
python scripts/preflight_execution_refinement.py
python scripts/run_execution_refinement.py
```

Se detiene después del informe. No se inicia paper ni live trading.
