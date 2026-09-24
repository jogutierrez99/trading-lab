# Batch 001A: resultados reales del 21 de septiembre de 2026

Run: `20260921T204432Z-48a412b8930d`.
Artefactos locales: `results/batch_001/20260921T204432Z-48a412b8930d/`.
Dataset padre: `77a55251e86f4034b317dd312b3bad06bb95c36f6540c74c4b8121793425b6da`.
Solo BTC/USDT spot 1h, largos; 10.000 USDT independientes por ejecución.
Máximo al entrar del 25%; riesgo al stop del 0,5% para trend/meanrev.
Momentum usa notional del 25% y no lleva stop. Costes por orden: comisión0,05%,
slippage0,02% y media horquilla0,005%. No son tarifas históricas verificadas.

## Versiones base: periodo completo descriptivo

Febrero2022–enero2023 inclusive, tras calentamiento común. Este resultado no es
un test fuera de muestra y las tres cuentas no forman una cartera.

| Estrategia | Retorno neto | DD máximo | Trades | Sharpe diario anualizado |
| --- | ---: | ---: | ---: | ---: |
| Donchian/EMA/ATR | -2,84% | 6,27% | 103 | -0,54 |
| Bollinger/RSI | -7,84% | 8,71% | 114 | -1,71 |
| Momentum14 días en1h | -5,24% | 15,85% | 128 | -0,50 |

Buy-and-hold con el mismo calendario y costes: -9,94% al25% y -39,78% al100%.
La diferente exposición impide interpretar esa comparación como prueba de
rentabilidad absoluta o de superioridad ajustada al riesgo.

## Selección y periodos reservados

Las13 configuraciones principales perdieron dinero en train (febrero–agosto2022).
Ninguna cumplió el criterio predefinido de elegibilidad. Se conservaron las
versiones base como diagnósticos, antes de mirar validation/test.

| Estrategia | Validation sep–oct2022 | Test nov2022–ene2023 | Test adverso | Trades test |
| --- | ---: | ---: | ---: | ---: |
| Donchian | -0,09% | +1,34% | -1,28% | 30 |
| Reversión | -0,68% | -1,20% | -3,59% | 25 |
| Momentum | -3,77% | +5,16% | +3,32% | 26 |

Los costes adversos son comisión0,10%, slippage0,10%, spread completo0,02%.
Las órdenes/trades pueden cambiar con costes por sus efectos sobre fills,
stops y capital; no se calcula sensibilidad restando un importe al PnL original.

Etiquetas según reglas registradas: Donchian PROMISING_BUT_UNSTABLE (sin
elegibilidad en train y falla costes adversos); reversión INSUFFICIENT_DATA,
con flags FAILED_AFTER_COSTS y FAILED_OOS; momentum INSUFFICIENT_DATA por
menos de30 operaciones test. Ninguna se clasifica ROBUST ni ganadora.

Walk-forward, solo retornos de sus cuatro tests mensuales julio–octubre2022:
Donchian -2,74%, reversión -0,87%, momentum -2,03% compuestos. Son porcentajes
descriptivos sobre folds que reinician capital. Se solapan con train/validation
estáticos y no aportan una segunda muestra independiente.

CRYPTO_001: pendiente por falta de perpetual/funding y ejecución de dos patas.
El tramo posterior a marzo2023, ETH, timeframes4h/1d, momentum escalado por
volatilidad, ADX y Monte Carlo siguen fuera de esta ejecución.

## Verificación y artefactos

139 tests superados, Ruff lint/formato correctos y `pip check` sin problemas.
El ledger registra118 backtests completados y1 estrategia omitida por falta de
datos; ningún experimento fallido o pendiente. Se verificaron hashes de todos
los resultados, PnL de operaciones frente a equity final, ausencia de posiciones
abiertas y orden temporal señal/entrada. La caché original sigue intacta.

Plan, costes y código se congelaron antes del primer backtest. No había commit
Git utilizable: la procedencia incluye hashes de archivos. Tras el backtest solo
se mejoró el formato de fechas de los gráficos; el motor, estrategias, plan y
resultados no cambiaron. El render tiene su propio hash y versión de Matplotlib.

Archivos principales dentro del run: `batch_001_summary.md`, `metrics.csv`,
`classifications.json`, `walk_forward.json`, `ledger.sqlite` y resultados JSON/
equity Parquet por experiment_id. `charts_v2/overview.png` compara las baselines
y benchmarks; los otros seis PNG muestran equity, drawdown, retornos mensuales,
Sharpe móvil90 días, distribución de trades y exposición de cada estrategia.
Los tres gráficos de test tienen solo tres observaciones válidas de Sharpe móvil;
no constituyen una serie larga de estabilidad. `charts/` conserva el primer render.
