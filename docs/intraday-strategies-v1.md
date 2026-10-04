# Dos hipótesis intradía independientes — RESEARCH ONLY

Protocolo inicial congelado: `volatility_breakout_intraday_v1` y
`range_mean_reversion_v1`, versión 1.0.0, metadata research. Una configuración por
familia; sin tuning, selección económica ni combinación automática de regímenes.
Sin conexión a forward/OKX, Telegram, paper ni órdenes. Resultados económicos pendientes.

## Archivos de esta implementación

Creado:

- `src/quant_lab/strategies/volatility_breakout_intraday_v1.py`
  y `range_mean_reversion_v1.py`.
- `src/quant_lab/intraday_features.py`, `intraday_metrics.py`, `price_level_execution.py`.
- Dos YAML homónimos en `configs/strategies/` y los dos experimentos indicados abajo.
- `tests/unit/test_volatility_breakout_intraday_v1.py`, `test_range_mean_reversion_v1.py`,
  `test_intraday_contracts.py` y `tests/integration/test_intraday_lab.py`.
- Este protocolo y `research_results/{volatility_breakout_intraday,range_mean_reversion}/RESEARCH_STATUS.md`.

Modificado:

- `strategies/base.py`, `study_backend.py`, `lab_runner.py`, `lab_schema.py`, `lab_data.py`:
  contrato opt-in, diagnóstico y preparación compatible con challenges congelados.
- `lab_resume.py`, `lab_reporting.py`, `lab_publish.py`, `lab_comparison.py`, `lab_robustness.py`:
  conteo/reutilización, aislamiento de diagnósticos, compactos y agrupación por activo.
- Tests de catálogo/config y `test_lab_resume.py`: la excepción histórica sigue intacta;
  el nuevo hash del runner se rechaza para reanudar runs hechos con código anterior.
- `README.md`, `COMMANDS.md`, `docs/PROJECT_STATE.md`, `docs/ARCHITECTURE.md`,
  `docs/lab-workflow.md` y `research_results/README.md`.

Las modificaciones de código listadas sin prefijo viven bajo `src/quant_lab/`.

## Componentes y adaptación explícita

Se reutilizan BaseStrategy/discovery/scaffolding, EMA/ATR, ADX/Bollinger,
complete_bars/closed_features, lab.py, ExperimentStore, sizing, CostModel,
protective_fill, métricas y publicación allowlist. Señales al cierre 15m;
entrada en el próximo open con costes y caps existentes.

Lab ordinario usa **precios perpetuos USD-M con ejecución synthetic colateralizada**,
sin funding, mark, liquidaciones ni margen perpetuo real. Los runners perpetuos
dedicados no son un backend lab 15m genérico. Esta adaptación queda explícita en
YAML/resolved/resultados; no es una simulación completa de contratos perpetuos.

El adaptador estructural anterior solo admite spot LONG sin target. Para respetar
RANGE se añade un contrato opt-in de niveles absolutos y una rama acotada en
StudyBackend: niveles conocidos al cierre, sizing a next-open efectivo con distancia
al stop, rechazo si open/precio efectivo queda fuera del bracket. Stop/target quedan
congelados al entrar; no siguen el rango rolling. Se mantienen stop-first, gaps,
comisiones, riesgo y caps. Las estrategias anteriores usan su camino sin niveles.

## Volatility breakout

Hipótesis: `compression → breakout → volatility expansion → continuation`.

- 1h bullish: close>EMA100 y EMA100[t]>EMA100[t-3]; bearish simétrico.
- Compresión 15m: Bollinger20/ancho2/std ddof=0. bandwidth[t-1] <=0.75×
  mediana(bandwidth[t-61..t-2]), excluyendo señal y observación comparada.
- Canal high/low de 20 barras anteriores mediante shift(1). LONG cierra
  estrictamente sobre el high; SHORT bajo el low, con régimen permitido.
- ATR14 / media de 20 ATR anteriores >=1.10, referencia shift(1).
- Cuerpo (close-open)/ATR >=0.50 LONG, <=-0.50 SHORT.
- Stop a ATR14×2 del precio efectivo de entrada; target fijo 2R, sin trailing.
- Sin reentrada especial: una nueva entrada exige una señal completa nueva.

## Range mean reversion

Hipótesis: `validated range → failed breakout/breakdown → reversion to midpoint`.

- 1h RANGE: ADX14<20 y abs(100×(EMA100[t]-EMA100[t-3])/EMA100[t])<0.10%.
- Rango high/low de 32 barras anteriores, shift(1); midpoint=(high+low)/2.
- Posición=(close-low)/(high-low); denominadores cero no generan entradas.
- Calidad: anchura/ATR14>=3. No garantiza cubrir costes; BASE/ADVERSE lo contrastan.
- LONG: low actual<range_low, cierre>range_low y posición<0.20.
- SHORT: high actual>range_high, cierre<range_high y posición>0.80.
- Stop LONG=range_low−ATR14×0.50; SHORT=range_high+ATR14×0.50.
- Target de ambos: midpoint de la señal, congelado al entrar.
- Pérdida del régimen inhibe entradas y sale en next-open. Protecciones de apertura
  tienen prioridad. Cierres fuera del rango no generan entradas.
- Rechazo de la misma vela observado al cierre: OHLC no reconstruye todos sus
  movimientos. No se atribuye trigger/fill anterior; stop-first conserva ambigüedad.

## Parámetros exactos de V1

Cada YAML contiene singleton por parámetro. Bollinger20/2 define la métrica, sin
otro grid. Comunes: ema_period100, ema_slope_lookback3, atr_period14.

| Breakout | Valor |
|---|---|
| compression_window / compression_ratio | 60 / 0.75 |
| breakout_lookback | 20 |
| atr_reference_window / atr_expansion_factor | 20 / 1.10 |
| momentum_threshold | 0.50 ATR |
| stop_atr_multiplier / reward_risk | 2.0 / 2.0 |

| Range | Valor |
|---|---|
| adx_period / adx_threshold | 14 / 20.0 |
| max_ema_slope_pct | 0.10% por 3 horas |
| range_lookback | 32 |
| lower_zone / upper_zone | 0.20 / 0.80 |
| minimum_range_atr / stop_atr_buffer | 3.0 / 0.50 |

## Datos, causalidad y warmup

Fuente local `data/mtf_15m/<asset>/klines`: BTC/ETH 236160 barras por activo,
2020-01-01→2026-09-26 UTC fin exclusivo, sin gaps según manifiestos. FULL verifica
SHA, fingerprint, cobertura y OHLCV. Sin descarga, conversión ni velas inventadas.

- BTC: `0a6032afe6c1e90ece9fe7f09ad8e7630860343b8433ca7f0d720102b54ffa97`.
- ETH: `9d4bcb5a0627a70513522de8d967c52697af68220dba52ce626a9915730e35c8`.

1h deriva de cuatro quarters completos, se etiqueta al cierre y alinea al cierre
15m mediante closed_features. Horas parciales no son disponibles. Features se
reinician tras gaps; lab rechaza gaps en periodo y warmup. Las señales warmup
no abren posiciones puntuables.

Warmup dinámico: 4×max(5×EMA, EMA+slope, 5×ADX cuando aplica)+4 quarters para
primera hora parcial; máximo con ventanas 15m. Defaults **2004 barras**, EMA100
requiere 500 horas completas y features válidas. Fórmulas de indicadores intactas.

## Experimentos y temporalidad

YAML: `configs/experiments/volatility_breakout_intraday_v1_btc_eth_15m.yaml` y
`configs/experiments/range_mean_reversion_v1_btc_eth_15m.yaml`.

Ambos: BTC/ETH, tres modos separados, capital10000, riesgo1%, posición máxima25%,
exposición máxima100%, lot/min_quantity0.000001 y min_notional10. BASE app
fee/slippage/spread=0.05/0.03/0.01%; ADVERSE=0.10/0.06/0.02%.

| Periodo UTC, fin exclusivo | Intervalo |
|---|---|
| TRAIN | 2020-02-01→2023-01-01 |
| VALIDATION | 2023-01-01→2025-01-01 |
| TEST | 2025-01-01→2026-09-26 |
| diagnostic_2020 | 2020-02-01→2021-01-01 |
| diagnostic_2021..2025 | años naturales completos |
| diagnostic_2026 | 2026-01-01→2026-09-26 |

Se conserva cobertura homogénea con warmup, sin fabricar enero anterior.
Los diagnósticos anuales son segmentos independientes liquidados y reiniciados a
capital inicial; no una cartera encadenada. Se solapan con los periodos principales:
no sumar sus trades/PnL con los principales.

Campo opt-in `diagnostic_periods`: nombres diagnostic_, intervalos ordenados y
disjuntos entre sí, dentro de cobertura experimental. Reutiliza Segment/evaluate,
ledger y resume; no participa en ranking, gates research/OOS, robustez ni filtros
agregados. Sin WF ni selección de ganadores. Ranking por closed_trades es solo
orden descriptivo; top_n6 incluye todos los activos/modos de la configuración única.
120 backtests por familia: 2×3×2×(3+7), para ejecución local del usuario.
Historia ya observada: diagnóstico retrospectivo, no holdout virgen ni permiso paper.

## Métricas y publicación

Además de métricas existentes: gross price PnL antes de fricciones, gross return,
costes fees+spread+slippage, net return, cost/gross-profit ratio (denominador:
ganancias positivas antes de fricciones), average trade/winner/loser, exposición,
holding hours y concentración top5 de ganancias netas. Funding null/not_modelled.

Setup counts LONG/SHORT cuentan señales completas dentro del periodo. Porcentaje
operado=trades cerrados/señales permitidas del modo; ocupación, último cierre, caps
o rechazos pueden impedir entradas. RANGE añade midpoint_exit_pct y pérdidas por
salida de régimen. No se reconstruye MFE/MAE ni se identifica un failed breakout
posterior mediante proxies; razones detalladas quedan en result.json local.

publish exporta solo allowlist compacta: métricas principales/anuales, parámetros,
resúmenes, identidades y hashes, sin equity/ledger/datasets. Compare conserva activos
separados para estos experimentos. Analizar después costes, lados, activos, muestra,
concentración, degradación anual y stops/midpoints sin elegir parámetros ni ganador.
El efecto de quitar el filtro requiere una ablation nueva, no se deduce de estos runs.

## Comandos locales completos

Desde la raíz con Python del proyecto; el usuario ejecuta los runs:

```powershell
Set-Location 'C:\Users\joshu\OneDrive\Escritorio\WEBS\Back_testing\trading-lab'
$py = '.\.venv\Scripts\python.exe'
& $py scripts/lab.py validate volatility_breakout_intraday_v1_btc_eth_15m
& $py scripts/lab.py validate volatility_breakout_intraday_v1_btc_eth_15m --full
& $py scripts/lab.py validate range_mean_reversion_v1_btc_eth_15m
& $py scripts/lab.py validate range_mean_reversion_v1_btc_eth_15m --full
& $py scripts/lab.py run volatility_breakout_intraday_v1_btc_eth_15m
& $py scripts/lab.py report volatility_breakout_intraday_v1_btc_eth_15m
& $py scripts/lab.py run range_mean_reversion_v1_btc_eth_15m
& $py scripts/lab.py report range_mean_reversion_v1_btc_eth_15m
& $py scripts/lab.py compare volatility_breakout_intraday_v1_btc_eth_15m range_mean_reversion_v1_btc_eth_15m
& $py scripts/lab.py publish volatility_breakout_intraday_v1_btc_eth_15m
& $py scripts/lab.py publish range_mean_reversion_v1_btc_eth_15m
& $py scripts/lab.py publish-comparison latest
```

No requiere classify/robust para esta falsación inicial. Conservar run IDs y entregar
a ChatGPT compactos de ambas familias/comparación: metrics_compact.csv,
summary/ai_summary.md, metadata.json, comparison.csv y sources.json. Sin subir results/.

## Evidencia de verificación técnica

2026-10-04: suite completa **863 passed**, incluidos **57 tests nuevos**;
774 avisos de deprecación de Matplotlib/pandas en reporting histórico, sin fallos.
Ruff check, format --check, pip check y diff --check correctos.
Ambos experimentos FAST y FULL **VALID**, 120 backtests previstos cada uno;
validar no ejecuta backtests. Pruebas de integración usan ventanas sintéticas pequeñas
y almacenamiento temporal para fills, costes, modos, resume, compare y publish.
No se ha ejecutado investigación histórica real ni inferido resultados económicos.
