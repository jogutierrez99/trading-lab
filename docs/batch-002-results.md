# Batch 002: resultados ejecutados el 22 de septiembre de 2026

Run: `20260922T045248Z-daad23091510`.
Artefactos: `results/batch_002/20260922T045248Z-daad23091510/`.
Diseño y adaptaciones previas: [batch-002-design.md](batch-002-design.md).

Se implementaron y ejecutaron las cuatro estrategias, con tres variantes cada una.
148 backtests completados, ninguno fallido o pendiente. Cada ejecución representa
una cuenta independiente de 10.000 USDT, BTC/USDT spot 1h, solo largos, sin
apalancamiento. No son una cartera conjunta.

## Datos y separación temporal

Se validaron dos tramos independientes a partir de los CSV originales auditados:

- Principal: 03/05/2023–31/12/2025, más 768 horas previas de calentamiento.
  Dataset `5810d644e2ff492d1a4f0ed9c5327561418be3c20f920c9520d28920f46bf54b`.
  Son 24.144 filas totales, 23.376 puntuables.
- Diagnóstico anterior: 02/01/2022–28/02/2023, más 768 horas de calentamiento.
  Dataset `2322037acf66bdb51b4af3bc76c278d0dce85d2bc5bf2d0e8cd97e86d6eac04b`.
  Son 10.920 filas totales, 10.152 puntuables. Se solapa con historia ya observada
  en Batch 001: no se interpreta como una validación independiente.

No se rellenó ninguna vela, ni se mantuvieron posiciones entre tramos. Marzo de
2023 sigue excluido por su discontinuidad. No se afirma disponer de 2020–2026.

Train principal hasta el 30/06/2024; validation julio–diciembre de 2024; test
enero–junio de 2025; holdout final julio–diciembre de 2025. Cada partición comienza
sin posiciones y liquida al final, con costes. La selección quedó guardada antes
de validation/test. El holdout se abrió en el experimento 101, después de los
100 experimentos de train, validation, test y walk-forward, sin cambiar selección.

## Candidatos seleccionados y holdout final

Costes base por orden: comisión 0,05%, slippage 0,02%, media horquilla 0,005%.
Se aplican dentro de los fills. Son supuestos de investigación, no tarifas
históricas verificadas.

| Estrategia / variante congelada | Train neto | Validation neto | Test neto | Holdout final neto | DD final | Trades finales |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Momentum vol, 30 días | +11,06% | +5,68% | -5,34% | -2,56% | 5,09% | 60 |
| Donchian 40 / ADX 20 | +4,59% | +0,03% | -2,01% | -2,35% | 4,11% | 38 |
| Squeeze percentil 15 | +7,65% | +0,25% | -0,78% | -3,15% | 4,82% | 48 |
| Regime meanrev, RSI 30 | -4,37% | -1,31% | +0,31% | -0,43% | 0,73% | 3 |

Ninguna variante de regime meanrev cumplió elegibilidad en train; se conservó
la base como diagnóstico. Las otras tres se seleccionaron únicamente en train
con las reglas predefinidas de Sharpe, riesgo y número de operaciones.

| Estrategia | Holdout sin costes | Holdout con costes base | Holdout adverso | Sharpe final | Sortino final |
| --- | ---: | ---: | ---: | ---: | ---: |
| Momentum vol | -0,35% | -2,56% | -6,42% | -1,07 | -1,47 |
| Donchian/ADX | -1,03% | -2,35% | -5,50% | -1,63 | -2,23 |
| Squeeze | -1,51% | -3,15% | -6,58% | -2,50 | -3,20 |
| Regime meanrev | -0,33% | -0,43% | -0,59% | -1,58 | -1,68 |

Adverso: comisión 0,10%, slippage 0,10%, spread completo 0,02% por orden.
Las operaciones pueden cambiar entre escenarios por los efectos de los costes
sobre entrada, stop y capital. No es una resta posterior del mismo conjunto de trades.

Clasificación: las primeras tres son **FAILED_OOS**. Regime meanrev es
**INSUFFICIENT_DATA**, con bandera adicional de pérdida OOS: tres operaciones
no permiten una conclusión sólida. No hay ganadora ni estrategia ROBUST.

## Qué ocurrió con el escalado por volatilidad

En las 72 entradas del test y las 60 del holdout de momentum seleccionado,
`clip(0,20 / volatilidad, 0,05, 0,25)` fue siempre 0,25. También ocurrió en las
386 entradas de la baseline de 14 días durante todo el tramo principal.
La regla está implementada, pero **no redujo exposición en esas entradas**.
No atribuir estos resultados a una mejora causada por el escalado.

El 25% limita el tamaño al entrar, incluyendo la comisión; no hay rebalanceos
posteriores. La exposición porcentual puede variar con el precio. Esta versión
también cambia el retraso del momentum y añade EMA respecto de Batch 001, y se
evalúa en otro periodo: no es una comparación aislada de una única modificación.

## Walk-forward y diagnósticos descriptivos

Cuatro folds, cada uno con 12 meses móviles de train y 3 meses de test. Tests
de julio de 2024 a junio de 2025. Composición de retornos test exclusivamente:

| Estrategia | Retorno compuesto de tests walk-forward |
| --- | ---: |
| Momentum vol | +0,96% |
| Donchian/ADX | -5,18% |
| Squeeze | -2,00% |
| Regime meanrev | -1,01% |

Cada fold reinicia capital; esta composición es descriptiva. Sus tests se solapan
con validation/test estáticos y no representan otra muestra independiente.

Baselines, periodo principal completo, **sin interpretación fuera de muestra**:
momentum 14 días +8,59%; Donchian 20/ADX 20 -2,94%; squeeze percentil 20 +0,70%;
regime meanrev RSI 30 -5,74%. Son variantes base, que pueden diferir de las seleccionadas.

Diagnóstico del tramo anterior: momentum -4,42%; Donchian +3,04%; squeeze -1,40%;
regime meanrev -1,37%. No se suman estos retornos a los del tramo principal.

Buy-and-hold, costes base, mismo calendario ejecutable: holdout -4,62% al 25%
y -18,49% al 100%; tramo principal completo +51,76% y +207,03%, respectivamente.
Exposición y objetivos de riesgo distintos: no sustituye la evaluación de cada estrategia.

## Evidencia y archivos

- 154 tests superados antes de ejecutar: ADX con valores manuales, causalidad,
  percentiles anteriores, señales, sizing en siguiente open, trailing de cierres,
  validación de folds, CLI y aislamiento de datos. Lint/formato y dependencias correctos.
- Verificados los hashes de los 148 resultados, conciliación del PnL frente a
  equity final, timestamps de entrada, ausencia de posiciones abiertas y PnL por régimen.
- Las selecciones permanecieron iguales en validation, test y holdout. Código
  ejecutado coincide con los hashes congelados antes del primer backtest.
- 512 archivos protegidos de Batch 001 —módulos anteriores, configuraciones y
  resultados— conservan exactamente sus hashes. No se sobreescribieron.
- `plan.json`, `provenance.json`, `selection_train.json`, `holdout_unlocked.json`,
  `ledger.sqlite`, `metrics.csv`, `walk_forward.json`, `classifications.json` y
  `verification.json` registran el experimento. Cada ID tiene resultado JSON,
  operaciones, métricas por régimen y equity Parquet.
- `charts/` contiene 17 PNG: curvas comparativas y paneles por estrategia de
  equity, drawdown, retornos mensuales, Sharpe móvil, trades y exposición.

El análisis de rentabilidad queda cerrado para esta configuración. Cualquier
nueva hipótesis debe abrir otro lote y reconocer que estos holdouts ya se observaron.
