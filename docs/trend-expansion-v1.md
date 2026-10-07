# Trend / Expansion V1

Estado: IMPLEMENTED / NOT_EXECUTED. Research only. Los perfiles públicos de copy
trading son fuente externa de hipótesis, no evidencia de edge ni instrucciones para
replicar traders. Protocolo declarado antes de consultar resultados de este estudio.
No se cambian familias, candidatos, grids ni resultados históricos congelados.

## Integración y reutilización

Cuatro experimentos ordinarios `lab_schema.Experiment`, con StudyBackend, riesgo,
costes, data preflight, registry, almacenamiento serial, resume y ranking existentes.
No hay motor, base de datos, dashboard ni selección por IA nuevos. Los YAML viven
planos en `configs/experiments/`: discovery usa `glob("*.yaml")`, no subdirectorios.
El prefijo `trend_expansion_entry_` identifica la fase sin cambiar el catálogo.

Inspección previa: `ema_pullback` es benchmark reutilizable 1h LONG_ONLY; se conserva
su Python/version y pullback_period=20, sin optimizar. `mtf_trend_pullback` necesita
legacy_mtf y no se fuerza a pasar por el adapter OHLCV. `atr_breakout` es LONG_ONLY,
con gate quantile720 y salida EMA; no es equivalente al estudio simétrico de ratio ATR.
`donchian_trend_v1` es 4h/ADX/trailing y no se traduce silenciosamente a 1h.
`trend_volatility_breakout_v1` 1.0.1 ya implementa el híbrido deseado: la nueva clase
`donchian_atr_breakout` hereda sus features y entradas exactas y añade únicamente
salidas Donchian opt-in para la fase 2. Su nueva identidad evita modificar V1 congelada;
una regresión compara features/señales contra V1. Sus YAML/grids anteriores de 144
configuraciones quedan intactos. Pure Donchian y ATR son reglas nuevas distintas.

## Reglas exactas al cierre

- **Pullback**: EMA50>EMA200, close>EMA200, toque de EMA20 en la vela anterior,
  recuperación close>EMA20 y RSI14>50. Salida original close<EMA50; solo LONG.
- **Donchian**: close>máximo high de las N barras anteriores (LONG), o close<mínimo
  low anterior (SHORT), con EMA200 y slope5 de signo compatible. Sin gate de expansión.
- **ATR**: `(close[t]-close[t-1])/ATR[t-1]` > k LONG o < -k SHORT, más
  `ATR[t]/mean(ATR[t-50:t-1]) >= threshold`, con el mismo régimen EMA200/slope5.
  No hay canal estructural en su entrada: permite distinguir impulso vs estructura.
- **Donchian+ATR**: entrada heredada de V1, Donchian anterior AND expansión, con
  exactamente los mismos EMA200/slope5/ATR14/canales que Donchian puro.

Pure Donchian y ATR permiten `trend_filter=ema_slope|price_ema|dual_ema|off`.
ATR permite referencia mean o median, siempre desplazada una barra; no se barren
estas alternativas en V1. Híbrido mantiene régimen/ref mean50 de la implementación
congelada. Un análisis con otros filtros requiere otro experimento predeclarado.

ATR es la media aritmética del true range existente, no Wilder. Comparaciones de
ruptura/régimen estrictas, threshold ATR inclusivo. Señales pueden repetirse mientras
exista ruptura; el motor limita ocupación a una posición, sin piramidación.

## Grid pequeño y comparable

| Familia / ID | Valores variables | Configuraciones | Backtests previstos |
|---|---|---:|---:|
| `trend_expansion_entry_pullback_v1` | EMA20 fija | 1 | 44 |
| `trend_expansion_entry_atr_v1` | impulse k 0.75/1.0/1.25 × expansión 1.1/1.25 | 6 | 552 |
| `trend_expansion_entry_donchian_v1` | canal 30/40/50 | 3 | 300 |
| `trend_expansion_entry_donchian_atr_v1` | canal 30/40/50 × expansión 1.1/1.25 | 6 | 552 |

Total 1448 ejecuciones, 16 configuraciones de parámetros antes de mercado/modo/periodo.
El coste computacional procede de los controles temporales/direccionales, no de cientos
de combinaciones arbitrarias. EMA200, slope5, ATR14, referencia 50, stop2ATR y RR2
permanecen fijos para aislar entradas; vecinos 30/40/50 y 0.75/1/1.25 estudian regiones.
No se añaden timeframes, activos, filtros ni una búsqueda de exits a este grid.

## Riesgo, mercados y costes

BTCUSDT/ETHUSDT 1h, capital 10000 por cuenta/periodo. Stop-risk 1%, posición máxima 25%,
exposición máxima 100%, sin apalancamiento. Stop inicial ATR14 × 2 desde el fill efectivo,
target 2R, sin trailing/time stop en fase 1. Filtros quantity_step/min_quantity 0.000001,
min_notional 10, supuestos fijos existentes. Cada familia tiene perfil propio; no se
modifican app/risk globales. Perfil benchmark nuevo usa estos brackets, conservando
la salida EMA original. Comparabilidad de entradas con el benchmark es aproximada:
RSI/salida por señal/solo LONG son confusores explícitos, no un ablation puro.

BASE fee/slippage/spread completo 0.05/0.03/0.01%; ADVERSE 0.10/0.06/0.02%.
Valores fijados explícitamente a los perfiles ordinarios existentes. Comisión en ambas
puntas; medio spread más slippage adverso en cada fill. Cada stress se simula de nuevo,
porque cambia sizing/trades. Todos operan synthetic sobre precios USD-M, incluso LONG
para mantener comparabilidad; sin funding, préstamo o liquidación de perpetuos.
SHORT_ONLY y LONG_SHORT solo en las tres familias compatibles; benchmark solo LONG_ONLY.
No existe benchmark SHORT ficticio ni guard legacy desactivado.

## Datos y causalidad

Reutiliza los bundles `data/lab_1h_prices` fijados por dataset_id en los experimentos
anteriores, ver [preparación offline](trend-volatility-breakout.md). Sin descargas,
interpolación, cambio de fuente ni ejecución automática de backtests.

- BTC: 874c185c21abeeda4bf17c026a44a55a19bf91ead2ac2b4466b1f37d4a97c00b.
- ETH: 1006e4cb8296ab8d1574317f2927c7feb975bbd25a5f195a8c7d97a17d7b70e4.

Warmup 1000 barras por activo. EMA/ATR/canales/referencia reinician ante gaps en las
nuevas familias; lab exige periodos continuos incluyendo warmup. Benchmark se ejecuta
solo sobre esas ventanas continuas, sin modificar su tratamiento legacy de features.
Falta/corrupción del bundle bloquea validate/run; no se reemplaza silenciosamente.

Canal y referencia ATR excluyen la vela de señal con shift(1). EMA/ATR actual usan la
vela recién cerrada. ATR de stop viene de la vela de señal; no se calcula en el fill
con el high/low posterior. available_at=index+1h. Decisiones al cierre, entrada y
salida por señal como pronto al siguiente open, sin órdenes originadas en warmup.
Tests: prefix-invariance, mutación de futuro, long/short, ventanas exactas, gaps,
paridad del híbrido y ejecución con señales reales. Stops/targets/trailing permanecen
en motor: stop-first en ambigüedad OHLC, gaps al open, trailing de cierre efectivo
en la siguiente barra. Nunca se supone un orden intrabar conocido.

## Periodos y límites de evidencia

Mismos periodos UTC fin exclusivo del protocolo largo, sin elegir fechas favorables:
TRAIN 2023-06-04→2024-07-01, VALIDATION→2025-01-01,
TEST 2025-07-01→2026-09-26. WF:

| Fold | TRAIN | TEST |
|---|---|---|
| 0 |2023-07-01→2024-07-01|2024-07-01→2024-10-01|
| 1 |2023-10-01→2024-10-01|2024-10-01→2025-01-01|
| 2 |2024-01-01→2025-01-01|2025-01-01→2025-04-01|
| 3 |2024-04-01→2025-04-01|2025-04-01→2025-07-01|

Ranking Sharpe TRAIN/base exclusivamente; filtro legacy 1 trade/DD<=25% no acredita edge,
suficiencia económica ni paper. No se cambian clasificadores existentes. WF ejecuta
el ganadorTRAIN de cada fold; sus TEST son evidencia adaptativa, no resultados de todos
los candidatos fijos. No sumar ventanas solapadas, costes o modos ni presentar medianas
como una cartera. Lab calcula los grids en TEST: no usar esas columnas para elegir
entradas/supervivientes. Historial ya observado en el proyecto: toda esta línea es
REUSED_HISTORY_EXPLORATORY, sin holdout nuevo independiente.

## Comparación y outputs

`lab.py compare` se mantiene disponible; ahora siempre separa symbol/timeframe y no
mezcla BTC/ETH en sus medianas. Se corrige el nombre local que ocultaba el DataFrame.
`lab.py trend-expansion report` usa los cuatro últimos runs solicitados COMPLETE y
los fija por run ID. `--runs` admite cuatro IDs en orden pullback/ATR/Donchian/híbrido.
Compara planes vigentes exactos, periodos/datos/costes/ejecución/capital/riesgo y code
hash; incompatibilidades bloquean el informe. Audita ledger, metadata, result y equity
SHA256 con el verificador existente, incluidas referencias de resume. No simula.

Reporte único: `reports/trend-expansion/<UTC-id>/`. Publicación:
`lab.py trend-expansion publish latest` exporta allowlist a
`research_results/trend_expansion/<UTC-id>/`, con límite 5 MB por archivo, hashes y rutas
portables. No sobrescribe ni ejecuta Git; archivos pesados y audit detallado quedan
locales. Rechaza exportación incompleta, cambios de fuente o límites excedidos.

Outputs permitidos:

- `experiment_manifest.csv`: IDs/version/code hash/revisión y tamaño de grid.
- `summary.csv`: todas las celdas con parámetros, identidad, costes y métricas.
- `family_comparison.csv`: medianas por familia/activo/modo/periodo/coste, sin ganador.
- `long_short_comparison.csv`: cuentas independientes y contribuciones LONG/SHORT
  del combined; contribución PnL no equivale a Sharpe/DD independiente de cada lado.
- `base_adverse_comparison.csv`: parejas exactas y deltas, no una comisión restada.
- `parameter_robustness.csv`: pares adyacentes de un solo parámetro en TRAIN/base,
  con expectancy/PF/retorno/DD/trades de ambos; sin selección automática ni TEST.
- `trade_distribution.csv`: medianas winner/loser, payoff, percentiles1/5/50/95/99,
  mejor trade y PnL sin él, top1/5/10% de todos los trades ordenados por PnL neto.
- `conclusions.md`: estructura solicitada, limitaciones y review humana pendiente.
- `sources.json` y `metadata.json`: provenance, snapshots resueltos, datasets/hashes,
  periodos, costes, riesgo, código/revisión/Git status/entorno, selección y hashes.

Métricas originales: retorno neto/CAGR, expectancy/PF/win rate, average winner/loser,
DD/Sharpe/Sortino, exposición, fees/spread/slippage, total costs y coste medio/trade.
Undefined/null permanecen vacíos. No se crea nueva regla rígida de aprobación.
Distribución usa ceil(N×porcentaje); shares del PnL neto total solo si total>0 y pueden
exceder 100%. PnL sin mejor trade es suma descriptiva, sin rehacer sizing/equity/DD.
Correlación/portfolio se dejan para otra investigación. La convexidad depende también
de la salida: fixedRR podría truncar tendencias; fase 2 evalúa esa hipótesis.

## Fase 2 preparada, sin candidatos automáticos

`lab.py trend-expansion prepare-exits --help` documenta argumentos reales. Requiere
run ID de fase 1, configuration_id exacto, prefijo nuevo y justificación humana explícita
de suficiencia/evidencia. No escoge supervivientes, no calcula backtests y no retunea
entradas. Congela una cuenta activo/modo, parámetros y source hashes en un receipt
`configs/profiles/trend_expansion/<prefijo>_freeze.json`, y crea cuatro YAML singleton
planos nuevos y perfiles separados, sin sobrescribir. Solo las tres familias breakout;
benchmark conserva su salida congelada y no se usa como candidato de exit ablation.

| Sufijo generado | Arquitectura |
|---|---|
| `_fixed_rr` | control stop ATR + 2R |
| `_atr_trailing` | stop ATR + close trailing 2ATR + 2R |
| `_donchian_exit` | stop ATR + salida canal contrario 10 al cierre, sin TP |
| `_atr_trailing_no_tp` | stop ATR + close trailing 2ATR, sin TP |

B conserva TP para distinguirlo de D. D mantiene stop inicial hasta la primera
actualización trailing; no abre posiciones sin protección. Exits se comparan con
entradas idénticas; el experimento hereda periodos/costes y tres segmentos+WF singleton.
Hay 14 backtests previstos por exit/activo/modo. El receipt no acredita independencia:
si la decisión usa TEST observado sigue siendo exploratoria. No ejecutar fase 2 antes
de la revisión ni tomar TEST para cambiar parámetros manteniendo etiqueta independiente.
Los comandos `lab.py validate/run/report` aceptan los IDs concretos que devuelve
prepare-exits. Aún no existen candidatos, por lo que no se fabrican YAML de supervivientes.

## Comandos locales

Desde la raíz, con el entorno activado (o usar `.venv/Scripts/python.exe`):

```powershell
python scripts/prepare_lab_1h_prices.py BTCUSDT
python scripts/prepare_lab_1h_prices.py ETHUSDT
python scripts/lab.py trend-expansion validate
python scripts/lab.py trend-expansion validate --full
python scripts/lab.py run trend_expansion_entry_pullback_v1
python scripts/lab.py run trend_expansion_entry_atr_v1
python scripts/lab.py run trend_expansion_entry_donchian_v1
python scripts/lab.py run trend_expansion_entry_donchian_atr_v1
python scripts/lab.py compare trend_expansion_entry_pullback_v1 trend_expansion_entry_atr_v1 trend_expansion_entry_donchian_v1 trend_expansion_entry_donchian_atr_v1
python scripts/lab.py trend-expansion report
python scripts/lab.py trend-expansion publish latest
```

Los dos primeros comandos solo verifican/preparan fuentes offline existentes; no
backtests/descargas. Si se interrumpe un run usar resume/check según lab-workflow,
conservar fuentes y no cambiar código/configuración entre runs de esta comparación.
No classify/robust automático ni forward/OKX. Ningún resultado constituye promoción.

Estas pruebas constituyen investigación histórica y generación/falsación de hipótesis.
No demuestran rentabilidad futura ni constituyen por sí mismas aprobación para paper/live trading.

## Verificación técnica (2026-10-06)

- `python scripts/lab.py trend-expansion validate`: FAST VALID,1448 previstos,0 ejecutados.
- `python scripts/lab.py trend-expansion validate --full`: FULL VALID, mismos conteos;
  hashes/OHLCV/periodos/warmup verificados para ambos activos.
- `python scripts/lab.py falsification validate`: freeze RMM FAST VALID sin backtests.
- `python -m pytest -q -p no:cacheprovider`:1030 passed,317.50s;774 avisos legacy
  de deprecación Matplotlib/Pandas en reporting. Solo fixtures sintéticos pequeños.
- `python -m ruff check .`, `python -m ruff format --check .`: correctos,400 archivos.
- `python -m pip check`, `git diff --check`: correctos.

Se conservó el hash original de lab_cli.py; el dispatch adicional vive en el
entrypoint. Tests de configuración/registro actualizan únicamente las expectativas
por las tres nuevas implementaciones. No se ejecutaron grids históricos, fase2,
publicación de resultados reales, conexiones forward ni Git commit/push.
