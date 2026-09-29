# Trend RSI Pullback V1 — protocolo de implementación

Familia `trend_rsi_pullback_v1`, versión 1.0.0, estado research. Hipótesis: un pullback
RSI contra una tendencia SMA puede ofrecer una entrada con riesgo ATR. La referencia
del vídeo es una formulación fija, no evidencia de edge. No se ejecutan automáticamente
los grids ni se declara rentabilidad, robustez o elegibilidad paper.

## Arquitectura inspeccionada y reutilizada

1. `StrategyRegistry.discover` encuentra las subclases locales de `BaseStrategy` sin
   listas de estrategias nuevas ni excepciones de discovery. Parámetros Pydantic
   StrictModel, desconocidos/tipos/rangos inválidos rechazados.
2. `Experiment.grid` expande listas cartesianas y `lab_runner.prepare` resuelve/valida
   cada combinación. No se introduce otro optimizador ni otra infraestructura de grid.
3. `lab_data` fija instrumentos, resolución, manifiesto, fingerprint y SHA256. El
   adaptador explícito `mtf_quarters` lee el formato real `data.parquet` del repositorio,
   sin convertir, copiar, descargar ni reemplazar datasets. FAST revisa manifiestos;
   FULL añade hashes, contenido OHLCV y continuidad de cada periodo/warmup.
4. `mtf_features.complete_bars` agrega horas solo con cuatro cuartos reales;
   `closed_features` cambia su índice a disponibilidad al cierre y hace forward-fill
   hacia los cierres 15m. No hay backfill. No se mezcla con adapters legacy_mtf.
5. StudyBackend v1 usa las mismas reglas de ejecución y RiskConfig. La ampliación 15m
   afecta a duración/auditoría del segmento, no a fills, comisiones, protección ni sizing.
   `study_data.HOURS` permanece intacto para no ampliar matrices/downloads históricos.
6. `modes` se traduce a long/short/combined, una posición colateralizada simultánea,
   sin piramidación/reversión en la misma apertura. Señales de cierre se ejecutan como
   pronto en la siguiente apertura; la marca temporal del cierre coincide con esa
   apertura, pero nunca se usa el precio de cierre como fill de entrada.
7. Capital y sizing heredan app/risk, igual que otros experimentos ordinarios. El único
   enlace opt-in `lab_risk_parameters` traduce atr_length → atr_period,
   atr_multiplier → atr_multiplier y reward_risk → risk_reward por combinación.
   Ninguna estrategia anterior declara este enlace. `resolved.json` guarda los riesgos
   resueltos y cada backtest nuevo conserva `resolved_risk`.
8. CostModel modela comisión en ambos lados, spread/2 y slippage adverso. El modelo
   synthetic NO calcula funding, liquidación por mark o préstamo. Los precios fuente
   son USD-M perpetuos: se declaran como precios para ejecución sintética, no spot ni
   réplica de una cuenta de futuros. El adaptador rechaza llamarlos ejecución spot.
9. Stops/targets se calculan desde el precio de entrada con costes, usando ATR conocido
   en la vela anterior. Reutiliza size_entry y protective_fill, incluida prioridad
   stop-first cuando una misma vela toca SL y TP. No introduce trailing ni time-stop.
10. Warmup se incorpora con `window`, sin entradas durante ese tramo. Los experimentos
    piden 1004 cuartos: 251 horas nominales, suficientes para 250 horas completas aunque
    un tramo empiece desalineado respecto de 1h. La estrategia declara su mínimo y
    oculta señales mientras no haya contexto/indicadores válidos. Los gaps reinician
    indicadores y contexto; ejecución FULL exige continuidad sin exclusiones implícitas.
11. Lab tiene TRAIN / VALIDATION / TEST. TEST es el holdout FINAL; no se añade una cuarta
    partición artificial ni se cambian las divisiones de runners especializados.
12. Ranking/selección permanecen en TRAIN/base; walk-forward selecciona TRAIN y reporta
    solo TEST del ganador. Estos cuatro experimentos usan los cuatro folds de Batch 003.
13. `failure_reasons` y sus thresholds no cambian. Aquí existen PASS/FAIL, no NEAR_PASS,
    RESEARCH_PASS ni PAPER_TRADING_CANDIDATE. Esas etiquetas son de otros protocolos.
14. `ExperimentStore`, métricas y reporting existentes producen plan, resolved, hashes,
    entorno, ledger, trades, equity, métricas, leaderboard, summary.md y ai_summary.md.
    `lab.py compare` lee solo artefactos compactos de runs COMPLETE y escribe un informe
    nuevo en reports/lab-comparison, sin alterar resultados ni simular backtests.

## Reglas exactas

| Variante | Tendencia | LONG | SHORT |
|---|---|---|---|
| V1 | close y SMA de 15m | close > SMA y RSI15m < oversold | close < SMA y RSI15m > overbought |
| V2 | último close y SMA de 1h completamente cerrado | close1h > SMA1h y RSI15m < oversold | close1h < SMA1h y RSI15m > overbought |
| V3 | V2 y slope SMA de 5 horas completas | V2 y SMA[t] > SMA[t-5] | V2 y SMA[t] < SMA[t-5] |

Comparaciones estrictas; igualdad no activa señal. Exits de señal siempre false:
SL, TP y liquidación de fin de periodo pertenecen al backend. RSI reutiliza Wilder
existente; ATR reutiliza la media aritmética de true range existente, no se sustituye
por otro ATR. SL = entry ∓ ATR15m × multiplier; TP = entry ± distancia × reward_risk.

Parámetros reutilizables en una sola clase; variante controlada por YAML. No existen
clones por activo, dirección o valores del grid. `sma_slope_lookback` está fijado a 5.

## Grid y referencia

- sma_length: 150, 185, 200.
- rsi_length: 14, 20, 25.
- rsi_oversold: 25, 30, 35; overbought derivado: 75, 70, 65 respectivamente.
- atr_length: 14, 20.
- atr_multiplier: 1.5, 2.0, 2.5.
- reward_risk: 1.25, 1.5, 2.0.

486 combinaciones por grid; el espejo no es otra dimensión. Una configuración explícita
no espejo se rechaza. Video Reference = V1 / SMA185 / RSI25 / 30-70 / ATR14 ×2 / RR1.5.

| Experimento | Parámetros únicos | × activos × modos | Backtests previstos |
|---|---:|---:|---:|
| trend_rsi_pullback_video_reference | 1 | 6 | 132 |
| trend_rsi_pullback_v1_single_tf | 486 | 2916 | 40872 |
| trend_rsi_pullback_v1_mtf | 486 | 2916 | 40872 |
| trend_rsi_pullback_v1_mtf_slope | 486 | 2916 | 40872 |

Backtests = 2 activos × 3 modos × 2 costes × [parámetros × (3 periodos principales
+ 4 TRAIN de walk-forward) + 4 TEST de walk-forward del ganador].
Para cada fold se elige por TRAIN/base; su TEST ejecuta solo esa configuración en ambos costes.
Cada grid es una carga larga para ejecución local, no una comprobación rápida.

## Datasets y periodos fijados

Sin descargas; fuentes `data/mtf_15m/{BTCUSDT,ETHUSDT}/klines`, 15m:

- BTC: `0a6032afe6c1e90ece9fe7f09ad8e7630860343b8433ca7f0d720102b54ffa97`.
- ETH: `9d4bcb5a0627a70513522de8d967c52697af68220dba52ce626a9915730e35c8`.

Cobertura de los manifiestos: 2020-01-01 → 2026-09-26 UTC, fin exclusivo, VALID sin
huecos declarados. La validación FULL comprueba bytes/fingerprint, sin fiarse solo del
manifiesto. 1h se agrega causalmente de esos mismos precios 15m; no se usan velas mark
ni se mezcla un OHLCV de otro proveedor.

Protocolo largo corregido: UTC, todos los finales exclusivos. TEST es el final holdout
del backend ordinario; no existe un cuarto periodo principal ni un campo final_holdout.

| Periodo | Inicio | Fin exclusivo |
|---|---|---|
| TRAIN | 2023-06-04 | 2024-07-01 |
| VALIDATION | 2024-07-01 | 2025-01-01 |
| TEST / final holdout | 2025-07-01 | 2026-09-26 |

Folds copiados exactamente de `configs/profiles/batch_003/batch.yaml`:

| Fold | TRAIN | TEST |
|---|---|---|
| 1 | 2023-07-01 → 2024-07-01 | 2024-07-01 → 2024-10-01 |
| 2 | 2023-10-01 → 2024-10-01 | 2024-10-01 → 2025-01-01 |
| 3 | 2024-01-01 → 2025-01-01 | 2025-01-01 → 2025-04-01 |
| 4 | 2024-04-01 → 2025-04-01 | 2025-04-01 → 2025-07-01 |

Cada TRAIN termina antes o en el inicio de su TEST; los TEST de los folds son disjuntos
y terminan en el inicio del holdout principal. No se utilizan datos desde 2026-09-26.
Los periodos cortos de 2022 fueron la configuración inicial incorrectamente heredada
de trend_btc_1h_001. Sus runs y comparaciones ya existentes se conservan con sus snapshots;
no representan este protocolo largo. Se mantienen los IDs de los cuatro experimentos
por petición explícita; cada nueva ejecución crea otro run con su configuración congelada.
La descripción YAML histórica se conserva porque la corrección solo modifica validation.
Datos previamente usados en investigación no se presentan como holdout nunca observado.

Capital 10000 por backtest, riesgo y límites de risk.yaml. BASE heredado de app.yaml:
fee 0.05%, slippage 0.03%, spread 0.01%. ADVERSE heredado del experimento ordinario:
fee 0.10%, slippage 0.06%, spread 0.02%. Mismos filtros: >=1 trade y DD<=25%.
No se han relajado umbrales ni modificado archivos globales de configuración.

## Métricas y comparación

`metrics.csv` conserva closed_trades, return_pct, max_drawdown_pct, sharpe, sortino,
win_rate_pct, profit_factor, expectancy, average_win/loss, fees_paid,
slippage_cost_closed_trades, spread_cost_closed_trades, average_close_exposure_pct,
long_trades y short_trades. Average trade corresponde a expectancy (media de PnL neto
por trade), sin una fórmula duplicada. No existe mediana por trade en el resumidor
actual. funding_pnl queda null y funding_note=not_modelled_synthetic, nunca cero ficticio.

`compare` produce comparison.csv/json y ambos resúmenes con recuentos de parámetros,
configuraciones por activos/modos, válidas, PASS/FAIL y medianas de retorno, DD, Sharpe
y expectancy por periodo, coste y dirección. Los ejemplos descriptivos se toman del
leaderboard ordenado por TRAIN, no por holdout. sources.json fija run IDs, rutas,
periodos, datasets, costes, filtros y hashes de artefactos. No infiere rentabilidad.

## Comandos Windows (raíz del repositorio)

```bat
python scripts/lab.py strategies
python scripts/lab.py experiments
python scripts/lab.py validate trend_rsi_pullback_video_reference --full
python scripts/lab.py validate trend_rsi_pullback_v1_single_tf --full
python scripts/lab.py validate trend_rsi_pullback_v1_mtf --full
python scripts/lab.py validate trend_rsi_pullback_v1_mtf_slope --full
```

Siguiente ejecución local autorizada inicialmente: solo la referencia del protocolo largo:

```bat
python scripts/lab.py run trend_rsi_pullback_video_reference
```

Los tres grids completos quedan pendientes de una decisión posterior.

Cada `run` crea automáticamente summary.md y ai_summary.md (sin llamadas a una IA).
`report` localiza los resúmenes, no recalcula operaciones:

```bat
python scripts/lab.py report trend_rsi_pullback_video_reference
python scripts/lab.py report trend_rsi_pullback_v1_single_tf
python scripts/lab.py report trend_rsi_pullback_v1_mtf
python scripts/lab.py report trend_rsi_pullback_v1_mtf_slope
python scripts/lab.py compare trend_rsi_pullback_video_reference trend_rsi_pullback_v1_single_tf trend_rsi_pullback_v1_mtf trend_rsi_pullback_v1_mtf_slope
```

No hay subcomando separado `ai-summary`. Compare exige los últimos runs completos de
los IDs pedidos; conserva sus resultados y crea una nueva carpeta para cada comparación.

## Archivos de la implementación

Creados:
- src/quant_lab/strategies/trend_rsi_pullback_v1.py: única familia, parámetros y señales.
- configs/strategies/trend_rsi_pullback_v1.yaml: catálogo deshabilitado por defecto.
- configs/profiles/lab_trend_rsi_pullback.yaml: perfil habilitado para estos experimentos.
- configs/experiments/trend_rsi_pullback_video_reference.yaml: referencia fija.
- configs/experiments/trend_rsi_pullback_v1_single_tf.yaml: grid V1.
- configs/experiments/trend_rsi_pullback_v1_mtf.yaml: grid V2.
- configs/experiments/trend_rsi_pullback_v1_mtf_slope.yaml: grid V3.
- src/quant_lab/lab_comparison.py: comparación de artefactos existentes.
- tests/unit/test_trend_rsi_pullback_v1.py: reglas/causalidad/parámetros/registry.
- tests/integration/test_trend_rsi_lab.py: datos, grids, fill ATR/RR, modos y CLI/reportes.
- docs/trend-rsi-pullback.md: este protocolo.

Modificados:
- strategies/base.py: contratos opt-in de warmup y parámetros de riesgo; defaults vacíos.
- lab_schema.py / lab_data.py: formato explícito de quarters fijado por hash y lectura validada.
- study_backend.py: duración 15m y auditoría quarter existente; bucle de fills intacto.
- lab_runner.py: validación de warmup, enlace a RiskConfig y conteo long/short.
- lab_cli.py: comando compare de lectura de resultados; comandos anteriores conservados.
- tests/unit/test_strategy.py y test_config.py: actualizar únicamente inventarios
  esperados (29 implementaciones, 31 YAML incluidos los dos reservados). Se conserva
  la aserción de todos los YAML de catálogo deshabilitados y el inventario previo.
- README, docs/ARCHITECTURE.md, docs/PROJECT_STATE.md, docs/WORKFLOW.md,
  docs/lab-workflow.md y skills/create-experiment/SKILL.md: capacidades y límites nuevos.

Los cambios previos de forward, cotizaciones y Telegram se preservan; no pertenecen a
esta implementación. No se ha añadido integración de esta familia al forward ni órdenes.


## Verificación de la implementación inicial — 2026-09-29

Evidencia histórica anterior a la corrección temporal; sus recuentos corresponden al protocolo corto.

- 33 tests nuevos: 27 unitarios y 6 de integración parametrizados.
- Grupo relevante: 146 passed en 17.76 s.
- Suite completa con Python 3.13 local: 653 passed en 177.65 s.
- Ruff check y format globales correctos (300 archivos); pip check sin problemas.
- Los cuatro comandos reales lab.py validate ID --full devolvieron VALID.
- Grids: 1 / 486 / 486 / 486; backtests previstos 36 / 17496 / 17496 / 17496.
- lab.py strategies carga 29 implementaciones; CLI compare/report probado con fixtures.
- git diff --check correcto. app.yaml, risk.yaml, risk.py, metrics.py, lab_reporting.py,
  study_data.py, mtf_features.py, registry.py y estrategias previas sin cambios de esta tarea.
- Evidencia de validación local: reports/trend-rsi-implementation/20260929T162400Z-efceeced/validation.json.
- No se ejecutaron grids históricos, descargas, forward ni órdenes. Tests de integración
  ejecutaron solo simulaciones pequeñas sobre fixtures. No hay resultado económico nuevo.


## Verificación de la corrección temporal — 2026-09-29

- Cambiados exclusivamente train/validation/test/walk_forward en los cuatro YAML;
  cost_stress y todos los campos exteriores a validation conservados frente a Git HEAD.
- Los cuatro comandos `python scripts/lab.py validate <ID> --full` anteriores: VALID.
  BTC/ETH tienen cobertura continua de todos los periodos y sus 1004 barras warmup,
  hasta 2026-09-26 exclusivo; no DATA_GAP. Sin modificar datasets.
- Recuentos reales de prepare/CLI: referencia 132; V1, V2 y V3 40872 cada uno.
- `python -m pytest tests/unit/test_trend_rsi_pullback_v1.py tests/integration/test_trend_rsi_lab.py tests/unit/test_lab.py -q --basetemp=reports/temporal-protocol-pytest`:
  56 passed. Pruebas de fechas exactas, causalidad, folds de Batch 003, grid y supuestos
  preservados; las simulaciones son fixtures pequeños.
- `python scripts/lab.py strategies`: correcto, catálogo existente conservado.
- Ruff check/format globales y git diff --check correctos.
- Sin cambios en estrategia, schema, runner, StudyBackend, sizing, filtros ni costes;
  trend_btc_1h_001 y Batch 003 intactos. No ejecutados backtests históricos de referencia
  ni grids completos para esta corrección. Siguiente comando local: solo video_reference.


## Referencia fija con Sharpe TRAIN indefinido

El run 20260929T181029Z-abd68c372a9b se conserva FAILED (8/132): BTC LONG_ONLY
no operó en el primer TRAIN WF y su Sharpe fue null. FULL certifica datos, no actividad.
El runner ahora distingue una referencia de un solo candidato de un grid: la referencia
predeclarada se evalúa en todos los TEST de folds sin selección por ranking. Un aviso
explica el Sharpe indefinido; métricas null, filtros y clasificación permanecen intactos.
Con varios candidatos, todos los rankings indefinidos siguen causando fallo explícito.
No se cambian parámetros usando TEST ni se fabrican operaciones o métricas. COMPLETE
solo significa ejecución terminada; cero operaciones sigue fallando minimum_trades: 1.
Esta excepción permite completar la evaluación, pero no aporta evidencia de eficacia
cuando no hay operaciones. Repetir crea otro run y preserva el fallido.

Regresión sintética: una referencia sin operaciones completa todos los modos/costes,
con Sharpe null y FAIL; un grid de dos candidatos sin ranking válido sigue fallando.
La prueba existente de invariancia frente al holdout permanece activa.

Verificación de la excepción: 58 tests aprobados (test_lab, test_trend_rsi_pullback_v1
y test_trend_rsi_lab), Ruff check/format globales correctos. Referencia FULL VALID,
132 backtests previstos. Solo fixtures sintéticos; ningún run histórico relanzado.
