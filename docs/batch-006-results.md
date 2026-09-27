# Batch 006: resultados de Bollinger long/short

La estrategia está implementada y el experimento ha terminado. **Esta formulación
no muestra una ventaja consistente después de costes.** Ninguna configuración
alcanza la clasificación predefinida `PROMISING_BUT_UNCONFIRMED`.
No se han ajustado parámetros después de observar los resultados.

Run: `20260926T103758Z-dd7672b4fa25`.

Datos de futuros perpetuos BTCUSDT/ETHUSDT: 01/01/2020–25/09/2026 UTC,
58.728 velas horarias comunes por activo, 11 segmentos válidos y funding histórico.
Cada cuenta comienza con 10.000 USDT. Los retornos siguientes corresponden a todo
el periodo, no son rentabilidades anuales ni una cartera de las configuraciones.

## Resultado principal

| Modo | Positivas BASE | Retorno mediano | Sharpe mediano | PF mediano | Trades medianos |
|---|---:|---:|---:|---:|---:|
| LONG_ONLY | 4/18 | −0,23% | −0,43 | 0,65 | 31 |
| SHORT_ONLY | 2/18 | −0,87% | −0,66 | 0,59 | 42 |
| LONG_SHORT | 2/18 | −1,90% | −0,45 | 0,66 | 73 |

Estas medianas incluyen configuraciones sin operaciones. **12/54 no operan**;
un retorno cero en esos casos no demuestra una estrategia rentable.

| Timeframe | Positivas BASE | Retorno mediano | Trades medianos |
|---|---:|---:|---:|
| 1h | 0/18 | −17,55% | 220 |
| 4h | 6/18 | −0,79% | 37,5 |
| 1d | 2/18 | 0,00% | 0 |

En 1h, los retornos medianos son −10,38% en largos, −18,98% en cortos y
−27,92% combinados. En 1d la frecuencia es insuficiente para extraer conclusiones;
los dos casos positivos corresponden a la misma operación larga de BTC en A,
registrada en LONG_ONLY y LONG_SHORT.

La combinación mejora el retorno de LONG_ONLY en solo 2/18 comparaciones y el
de SHORT_ONLY en 4/18. En 3/18 cuentas combinadas una dirección gana y la otra
pierde. La contribución larga supera a la corta en 13/18 cuentas; esto no implica
que la contribución larga sea necesariamente positiva.

## Costes, funding y validación

- Configuraciones positivas: **14/54 en ZERO, 8/54 en BASE y 6/54 en ADVERSE**.
  Seis resultados positivos desaparecen al pasar de ZERO a BASE. ZERO también
  desactiva funding; el informe separa todos los componentes.
- Funding BASE: mediana de +0,26 USDT por cuenta; rango de −34,71 a +78,06 USDT.
  No compensa la debilidad general observada. Cero liquidaciones en FULL/BASE
  para las estrategias bajo el modelo de margen declarado.
- Holdout: 8/54 retornos positivos; solo 13/54 configuraciones alcanzan 30 trades
  en esa partición. 48/54 fallan la validación temporal definida y 41/54 tienen
  muestra insuficiente según los criterios congelados.
- Walk-forward: 22 ventanas, sin optimización. La media por configuración del
  porcentaje de ventanas TEST positivas es 16,92% en largos, 14,39% en cortos
  y 15,91% combinados. Las ventanas sin operaciones cuentan como no positivas.
- MFE/MAE mediano de las cuentas combinadas: 1,08 en largos y 0,97 en cortos.
  Expectancy mediana: −3,39 y −7,28 USDT por trade, respectivamente. Las excursiones
  son descriptivas y no incluyen costes ni funding.

BTC y ETH tienen cada uno 4/27 configuraciones positivas. Las medianas de PnL
por cuenta combinada son negativas en ambas direcciones dentro de BULL, BEAR
y SIDEWAYS; esta agregación descriptiva no prueba una regla de filtrado nueva.

## Variantes y continuación de la investigación

A tiene 4/18 resultados positivos y 42 trades medianos; B, 4/18 y 9,5 trades;
C, 0/18 y 51,5 trades. B genera hipótesis para estudiar eventos extremos, pero
su baja actividad impide interpretar su menor pérdida como superioridad.

El mayor retorno observado es ETH/4h/B/LONG_SHORT: +4,53%, con **solo 15 trades**
en todo el histórico y clasificación `INSUFFICIENT_DATA`. No se selecciona como
ganador. Todas las configuraciones positivas tienen esa limitación de muestra.
No hay una variante suficientemente respaldada para avanzar por sus resultados
actuales. Una hipótesis modificada necesitaría otro experimento predefinido;
este lote permanece íntegro, incluidos sus resultados negativos.

## Benchmarks BASE

| Activo | Benchmark | Retorno | Máximo drawdown |
|---|---|---:|---:|
| BTC | Buy & Hold 25% | +76,37% | 54,33% |
| BTC | Buy & Hold 100% | +245,65% | 88,06% |
| ETH | Buy & Hold 25% | +290,78% | 64,23% |
| ETH | Buy & Hold 100% | +573,70% | 89,31% |
| Ambos, por separado | CASH | 0,00% | 0,00% |

Son posiciones largas perpetuas con funding, cerradas y reiniciadas en las
fronteras de datos. El porcentaje fija la exposición inicial de cada segmento;
no es un rebalanceo continuo. Sus riesgos y exposiciones difieren de los de la
estrategia: un mayor retorno no basta para concluir superioridad.

## Evidencia y archivos

- **7.952 ejecuciones completadas**: 7.938 de estrategia y 14 benchmarks.
- **280 tests aprobados**, Ruff y `pip check` correctos antes del primer backtest.
- Código congelado sin cambios durante la ejecución; 19.490 archivos anteriores
  comprobados y conservados. Holdout desbloqueado tras 6.318 ejecuciones previas.
- Ledger, trades y equity verificados; manifest de 32.078 archivos, incluida
  una copia de los 220 archivos de código/configuración congelados.
- 32 gráficos generados; comparación de equity y de direcciones inspeccionadas.

La simulación usa tasas de funding históricas, pero precios de marca horarios
y supuestos de mantenimiento/liquidación. Todos los casos son `DIAGNOSTIC_ONLY`
y `MARGIN_MODEL_ASSUMED`; no son resultados paper ni evidencia futura.
El [protocolo](batch-006-design.md) explica también huecos, duración intrabar,
horizontes, filtros de cantidad y disponibilidad de datos.

Archivos principales del experimento:

- [Informe con las 20 respuestas y matriz completa](../results/batch_006_bollinger_long_short/20260926T103758Z-dd7672b4fa25/summary.md)
- [Comparación de direcciones](../results/batch_006_bollinger_long_short/20260926T103758Z-dd7672b4fa25/direction_comparison.csv)
- [Descomposición long/short](../results/batch_006_bollinger_long_short/20260926T103758Z-dd7672b4fa25/long_short_decomposition.csv)
- [Verificación](../results/batch_006_bollinger_long_short/20260926T103758Z-dd7672b4fa25/verification.json)
- [Gráfico BTC/4h/A, definido antes de ver resultados](../results/batch_006_bollinger_long_short/20260926T103758Z-dd7672b4fa25/charts/long_short_equity_comparison.png)
