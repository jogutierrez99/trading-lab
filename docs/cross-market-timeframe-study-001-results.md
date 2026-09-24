# Cross-market study 001: resultado verificado

Run: `results/cross_market_timeframe_study_001/20260922T214527Z-e7ef570a28ce`.

- 4536 ejecuciones completas; ninguna fallida.
- 114 combinaciones previstas: 108 evaluadas y 6 exclusiones temporales documentadas.
- BTC/USDT y ETH/USDT, spot long, 1h/4h/1d; 10000 USDT por cuenta independiente.
- Historico descargado desde 2018-01-01 hasta 2026-09-22 exclusivo; 3152 dias
  completos comunes tras excluir huecos y discrepancias, sin interpolacion.
- 238 tests aprobados, Ruff check/format y pip check correctos antes de congelar.
- Codigo sin cambios durante las ejecuciones; 4267 archivos anteriores protegidos intactos.
- Holdout desbloqueado tras las 972 ejecuciones TRAIN/VALIDATION/TEST.
- 77 combinaciones FULL/BASE admitieron 10000 permutaciones y 10000 bootstrap;
  31 quedaron excluidas de Monte Carlo por tener menos de 30 operaciones.
- 13 graficos generados; revisadas visualmente la comparacion BTC y la correlacion ETH4h.
- Las contribuciones de PnL por regimen concilian con el PnL de cada cuenta.
- `artifact_manifest.json` conserva hashes de los artefactos finales.

## Lectura descriptiva

4h mejora el retorno neto BASE de 24/36 pares comparables con 1h: 16/18 en BTC y
8/18 en ETH. Diferencia mediana: +6.52 puntos porcentuales en el periodo completo.
No es una mejora uniforme entre activos ni una seleccion de timeframe para operar.

| Activo, 4h | Positivas | Retorno neto mediano | Sharpe mediano | PF mediano |
|---|---:|---:|---:|---:|
| BTC | 17/18 | 21.16% | 0.81 | 1.84 |
| ETH | 16/18 | 17.68% | 0.55 | 1.55 |

Son medianas entre cuentas, no un rendimiento de cartera ni retornos anualizados.
Los costes reducen el retorno con mayor intensidad en 1h: drag mediano ZERO-BASE
14.44 puntos frente a 4.19 en 4h. La diferencia incorpora cambios en fills, tamanos
y operaciones, no solo comisiones de una lista fija de trades.

En 1d hay 23/34 combinaciones positivas, pero la mediana es de solo 15 operaciones.
Esto limita fuertemente la inferencia. Los reinicios de indicadores tras los dias
excluidos afectan especialmente a las ventanas largas diarias; ver cobertura anual.

47 combinaciones tienen al menos 60% de anos calendario completos positivos.
Ocho muestran MFE/MAE medio favorable con PnL negativo; esto motiva investigar
captura del recorrido y salidas, sin identificar causalmente que las salidas fallen.
Ningun par supera 80% de Jaccard de barras ocupadas; la correlacion diaria muestra
dependencias que ese criterio de solapamiento no captura.

Recomendacion experimental: B, investigar 4h con protocolo nuevo, y F, estudiar
salidas. No se implementa Batch006 ni una cartera. BTC contiene historia reutilizada;
ETH es validacion entre activos bajo adaptaciones temporales congeladas. Ninguna
estrategia recibe automaticamente la etiqueta ROBUST.

Ver `summary.md` para las 14 respuestas, `4h_analysis.md` para comparaciones por
estrategia y `timeframe_comparison.csv` para la matriz completa. Las limitaciones y
los comandos de reproduccion estan en [el protocolo](cross-market-timeframe-study-001.md).
