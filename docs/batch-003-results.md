# Batch 003: resultados y limitaciones

Run: `20260922T053734Z-6915f72a213b`. Completado: 130 backtests, sin modificar los
1.067 archivos protegidos de lotes anteriores. Código/configuraciones permanecen
idénticos a los hashes congelados antes de ejecutar. 175 tests, Ruff, formato y
pip check pasan. Sin órdenes reales.

Todas las cifras son **REUSED_HISTORY_DIAGNOSTIC**: el histórico hasta diciembre
de 2025 ya había sido observado. No hay validación independiente ni estrategia ROBUST.

| Estrategia | Variante train | Train % | Validation % | Test % | Final % | Final adverso % | WF % | Folds positivos |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| EMA pullback | EMA50 | 6,52 | 4,83 | -2,32 | -2,41 | -6,47 | 2,39 | 3/4 |
| MTF momentum | 72h | 5,66 | -1,21 | -1,75 | -1,01 | -2,33 | -2,94 | 1/4 |
| ATR breakout | K=1,5 | 5,73 | -4,30 | -2,00 | -2,12 | -3,05 | -6,22 | 0/4 |
| Trend strength | ROC7/60d | 8,65 | 3,07 | -0,08 | 0,30 | -0,63 | 2,99 | 2/4 |

Once variantes superan train. ATR K=2 no alcanza 40 operaciones y no es elegible.
Las cuatro selecciones se congelaron antes de validation y se mantuvieron en WF.
Ninguna es positiva en test ni en final adverso. EMA pullback queda FAILED_OOS;
las otras tres INSUFFICIENT_DATA por tener respectivamente15,16 y17 trades finales.
Esta etiqueta no oculta sus pérdidas, que figuran en la tabla y en todas las métricas.

Trend strength merece, como máximo, investigación adicional en Batch004: retorno
final pequeño, solo17 trades, test negativo y pérdida con costes adversos. No hay
base para promover ninguna estrategia a operativa. EMA pullback también tiene WF
positivo, pero pierde en test/final y se deteriora mucho con costes adversos.
ATR breakout pierde en todos los folds y MTF solo gana en uno; ambas hipótesis
tienen poco respaldo en este diagnóstico.

Monte Carlo usa10.000 permutaciones de PnL monetario fijo por caso elegible. Retorno
final constante por construcción; la información útil es el DD entre trades y las
rachas, no un pronóstico. Se guardan semillas y percentiles5/25/50/75/95. Los análisis
de régimen describen ejes de tendencia/volatilidad solapados y no seleccionan reglas.

## Acceso y reproducción

- [Protocolo y adaptaciones](batch-003-protocol.md).
- [Informe completo](../results/batch_003/20260922T053734Z-6915f72a213b/batch_003_summary.md),
  con las11 respuestas, benchmarks y referencias Batch001/002 en periodos idénticos.
- [Métricas](../results/batch_003/20260922T053734Z-6915f72a213b/metrics.csv).
- [Verificación](../results/batch_003/20260922T053734Z-6915f72a213b/verification.json).
- [Gráfico general](../results/batch_003/20260922T053734Z-6915f72a213b/charts/overview.png).

Los resultados locales están ignorados por Git, junto con datasets; no se han
sobrescrito resultados ni realizado commits. El manifiesto de artefactos permite
comprobar hashes de informes, ledger, trades, equities y gráficos.
