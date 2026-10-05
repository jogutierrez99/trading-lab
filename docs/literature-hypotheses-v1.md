# Literatura V1 — cuatro hipótesis independientes, RESEARCH ONLY

Fecha: 2026-10-04. Una configuración predeclarada por familia/timeframe, sin tuning,
portfolio, regime switcher ni promoción automática. Backtests históricos pendientes.
Implementación/validación técnica no acreditan rentabilidad ni independencia del TEST:
la historia de mercado ya fue observada por investigaciones previas.

## Fundamento bibliográfico y límites

- [Kaufman, Trading Systems and Methods, Wiley](https://onlinelibrary.wiley.com/doi/book/10.1002/9781119202561):
  marco de sistemas tendenciales, momentum y gestión del riesgo. Donchian V1 es una
  formulación propia, no réplica de Turtle ni afirmación de edge cripto.
- [Moskowitz, Ooi y Pedersen, Time Series Momentum, JFE 2012](https://fairmodel.econ.yale.edu/ec439/mosk.pdf):
  dirección por retorno propio y escalado de riesgo; evidencia en futuros tradicionales.
  El horizonte 30 días, EMA y caps de esta V1 son decisiones locales; no replica su
  horizonte ni transfiere sus resultados a BTC/ETH.
- [Moreira y Muir, Volatility-Managed Portfolios, 2017](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513):
  motivación para condicionar riesgo a volatilidad. Aquí inverse-volatility y tamaño
  fijado a entrada; no inverse-variance ni cartera reequilibrada continuamente.
- [Wilder, New Concepts in Technical Trading Systems, 1978](https://books.google.com/books?vid=ISBN0894590278):
  origen de RSI/ADX/ATR. EMA200, ADX25 y RSI55/45 son la hipótesis local de continuación,
  no evidencia publicada de rentabilidad de esta combinación.
- [Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888):
  mecánica económica de perpetuos/funding, no prueba de que los cuatro casos propuestos
  anticipen el precio. La señal condicional se falsará sin presuponer contrarian.
- [Binance, historial funding](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History):
  semántica del endpoint público utilizado previamente; esta tarea no descarga datos.

## Arquitectura reutilizada y adaptación

Se reutilizan discovery/scaffolding, StrictModel, BaseStrategy, EMA, ATR, Wilder RSI/ADX,
rolling, realized_volatility, complete_bars, continuous_blocks, StudyBackend, size_entry,
CostModel, ExperimentStore, lab.py, Segment, resume, métricas diarias UTC, excursiones
conservadoras y publicación allowlist. No cambios a estrategias ni perfiles congelados.

Nuevos: literature_features/data/metrics y lab_funding_adapter; cuatro módulos de estrategia,
cuatro perfiles, cinco experimentos, script de preparación offline y tests.
Cambios acotados en base, indicadores (annual_bars explícito, default horario intacto),
MTF (1d completo), schema/preparación/evaluate, reporting, compactos y compare.
Ruff formatea únicamente los cambios necesarios; sin nuevas dependencias.

Solo risk_managed_momentum_v1 opta por volatility sizing 4h/1d. Los guards horarios
de familias anteriores y legacy_mtf/legacy_batch_006 permanecen. El sizing es a entrada,
causal, coste-aware, 5–25% de exposición; no rebalancea una posición abierta al variar
volatilidad. Esto limita la conclusión sobre mejora por escalado: requiere un control
sin escalado en un experimento futuro, no se deduce por sí sola de V1.

Funding declara adapter perpetual_funding y PerpetualLabExecution, un schema local
especializado que no habilita perpetual en ExecutionConfig genérico. Se integra en
la orquestación/ledger/publicación existentes y llama a run_perpetual sin modificarlo.
Fills/margen/funding son los del motor horario existente. Spot/synthetic y adapters
legacy conservan sus guardas.

## Reglas y parámetros exactos

Señales a cierre y earliest fill próximo open. Una posición, sin pyramiding ni
reversal en la misma apertura; sin targets ni time stops en estas cuatro V1.

| Familia / timeframe | Parámetros iniciales |
|---|---|
| Donchian / 4h | ema_period200; adx_period14; adx_threshold25; donchian_lookback20; atr_period14; breakout_strength_min0.10; stop_atr_multiplier2; trailing_atr_multiplier2 |
| Momentum / 4h | ema_period200; momentum_lookback180; volatility_period180; target_volatility_pct10 |
| Momentum / 1d | ema_period200; momentum_lookback30; volatility_period30; target_volatility_pct10 |
| RSI / 4h | ema_period200; adx_period14; adx_threshold25; rsi_period14; long_threshold55; short_threshold45; atr_period14; stop_atr_multiplier2 |
| Funding / 1h | momentum_lookback168; funding_window90; lower_quantile0.05 (superior0.95); atr_period14; stop_atr_multiplier2 |

Donchian LONG: close>EMA, pendiente EMA de 3 barras >=0, ADX>25,
(close-prior_high20)/ATR>0.10. SHORT simétrico. Canal shift(1). Stop inicial 2ATR;
única salida activa: trailing 2ATR de extremos favorables de cierres, efectivo
en vela posterior. No target ni salida por EMA.

Momentum: close/close[N]-1; LONG si positivo y close>EMA200, SHORT si negativo y
close<EMA200. Sale por signo contrario o cero; perder solo EMA no sale. Sin stop ni
trailing; esto implica exposición a gaps. 180×4h=30 días; 30×1d=30 días. EMA200 sí
conserva significado en barras y distinta duración física. RV: desviación muestral de
retornos simples, sqrt(2190) 4h / sqrt(365) 1d; target10% anual / RV, clipped5–25%.
Volatilidad cero/no finita impide entradas.

RSI LONG: close>EMA200, ADX>25, RSI14>55. SHORT: close<EMA200, ADX>25, RSI14<45.
Sin techo RSI ni entrada contrarian. Stop inicial 2ATR; salida de momentum RSI<=50
LONG, RSI>=50 SHORT en next-open. Sin trailing ni target.

Funding: últimos90 eventos anteriores al actual para quantiles5/95%, excluye
observación comparada. Negativo extremo exige tasa<0 y <=q05; positivo tasa>0
y >=q95. Último evento conocido al cierre, antigüedad máxima8h, no backfill.
Un percentil descriptivo midrank usa solo esos90 eventos previos.
Momentum168h (7 días), un único contexto de precio:
negative_positive → LONG; negative_negative → SHORT;
positive_negative → SHORT; positive_positive → LONG de continuación.
Los cuatro casos quedan etiquetados; no cuatro variantes optimizadas.
Stop inicial 2ATR; salida por momentum contrario/cero; sin target/trailing.
Casos se mantienen activos mientras último evento sea extremo y fresco; una nueva
entrada exige señal válida y cuenta libre, no hay deduplicación especial por settlement.

## Datos offline fijados y causalidad

Precios fuente USD-M quarters completos BTC/ETH 2020-01-01→2026-09-26 exclusivo;
sin gaps, iguales valores en timestamps distintos conservados. Se agregan solo
4/16/96 quarters completos para 1h/4h/1d, UTC. Ninguna señal utiliza 15m en este batch.
Fuentes:
BTC 0a6032afe6c1e90ece9fe7f09ad8e7630860343b8433ca7f0d720102b54ffa97;
ETH 9d4bcb5a0627a70513522de8d967c52697af68220dba52ce626a9915730e35c8.

prepare_literature_data.py audita SHA/fingerprint, agrega y crea bundles nuevos
data/literature_v1/prices/<asset>/<tf>/<hash> con fuentes/hash resampling explícitos.
No descarga, relleno ni modificación de fuentes; no overwrite. YAML fija ID completo.
No se utilizan 4h/1d nativos con inconsistencias/gaps de anteriores cohortes.

EMA warmup conservador5×periodo:1000 barras para A/B/C. FUND728h conservadoras
incluyen historia percentiles; después de cortes precio/ATR/momentum reinician.
Causalidad probada por prefijos/vacío, futuros funding mutados, offsets de1ms,
canal sin vela actual, resampling parcial, gaps y volatilidad/anualización.

## Audit funding real y PnL

Fuente archivos públicos Binance USD-M retenidos:
data/batch_006_perpetual/<asset>/fundingRate/events/<id> y funding_rest/*.json.
Archivo mensual7305 eventos hasta2026-08-31 16:00:00.001UTC; con REST retenido
y deduplicado, **7380 eventos por activo**, 2020-01-01 00:00UTC→
2026-09-25 16:00:00.002UTC. Tasas reales, fracciones; interval8h,00/08/16UTC.
No missing settlements en cobertura; offset máximo0.047s. Conflictos se rechazan.
Timestamp de publicación independiente no existe en fuentes: disponibilidad asumida
al settlement observado, latencia desconocida. No usar tasas estimadas/previsiones.

Aux snapshots inmutables con hashes de funding, mark y fuentes:
BTC 544ea6f02c44faf7da884f218ad65288cde1208897095e16dc39a6bc873c6fc0;
ETH e040bf81eb66d02b74bcfbb51434bc96af4d815212b1e8b7a0b2a74a99a9e80f.
Mark1h falta216 BTC y72 ETH horas; cohorte BTC/ETH común2451 de2460 días.
Excluidos:2021-07-01,2021-07-24..27,2022-07-31,2022-10-02,2023-02-24,2026-06-29.
Se excluye día completo si falta mark/settlement en cualquiera de los activos.
Cohorte retrospectiva de calidad: no representa anticipar una interrupción en vivo.

Funding adapter liquida en fronteras, conserva cash entre segmentos y reinicia
features; muestra matched_hours/excluded_hours. Warmup no inicia operaciones.
Settlement exacto al open antes de acciones; offset<1s después de acciones y antes
de fills intrabar. Usa mark-open proxy para notional del evento; sin precisión tick.
Funding incluido en PnL: -side×quantity×mark×rate. Isolated1x, maintenance0.5%,
liquidationfee0.5%, sin tiers/ADL/insurance histórico. Stops y liquidaciones conservadoras.
Gross-fees-spread-slippage+funding-liquidationfee+bankruptcy_adjustment reconcilia net.
total_modeled_costs suma fricciones de trading; liquidation_fees va separado; funding
tiene signo ingreso/coste, nunca sumarlo dos veces. Los otros tres módulos usan
synthetic sobre USD-M, funding=null/not_modelled, sin liquidaciones.

## Experimentos y periodos

- configs/experiments/donchian_trend_v1_btc_eth_4h.yaml
- configs/experiments/risk_managed_momentum_v1_btc_eth_4h.yaml
- configs/experiments/risk_managed_momentum_v1_btc_eth_1d.yaml
- configs/experiments/rsi_momentum_regime_v1_btc_eth_4h.yaml
- configs/experiments/funding_conditional_momentum_v1_btc_eth_1h.yaml

BTC/ETH y LONG_ONLY/SHORT_ONLY/LONG_SHORT separados, capital10000. BASE app
fee/slippage/spread0.05/0.03/0.01%; ADVERSE0.10/0.06/0.02%, mismos eventos funding.
Riesgo1% stop-risk A/C/D, cap posición25%, cap exposición100%, sin apalancamiento.
B volatility-target5–25%. Filtros descriptivos: mínimo1 trade, DD<=25, PF/Sharpe
sin mínimo; ranking por número de trades TRAIN/base, top_n6 incluye todo. PASS legacy
no acredita edge. Sin WF, búsqueda ni selección por TEST.

| Experimento | TRAIN | VALIDATION | TEST exclusivo | Diagnósticos |
|---|---|---|---|---|
| A/B4h/C |2020-07-01→2023-01-01|2023→2025|2025→2026-09-26|2020 parcial;2021..2025;2026 parcial|
| B1d |2023→2024|2024→2025|2025→2026-09-26|2023..2025;2026 parcial|
| D1h |2020-02-01→2023-01-01|2023→2025|2025→2026-09-26|2020 parcial;2021..2025;2026 parcial|

Cada año es cuenta independiente liquidada, sin sumar con periodos principales;
no interviene en selección/gates. 120 backtests A/B4h/C/D,84 B1d, **564 totales**.
Los ejecuta el usuario. Fechas y motores distintos impiden ranking por retorno bruto.

## Resultados, métricas y clasificación posterior

metrics.csv local y metrics_compact.csv publicado incluyen CAGR/Sortino, retorno
gross/net, fees/slippage/spread, costs/gross-profit, PF/expectancy, muestra, exposición,
holdinghours, contribuciones LONG/SHORT, setups/aceptados y concentración top5.
entry_diagnostics.csv compacto: RSI/ADX, momentum/RV/entry scaling, breakoutstrength
o rawfunding/percentil/caso en entrada; PnL y MFE/MAE con cotas intrabar conservadoras,
usando infraestructura existente. No MFE/MAE exactos ni asumir fallo posterior de
breakout a partir de cualquier stop. Resultados por buckets descriptivos y casos
funding; parámetros exactos en exact_parameters.json, provenance/hash/IDs en metadata.

compare conserva activo/timeframe/modo/periodo/coste y medianas (un candidato por celda),
incluye trades, PF, Sharpe, DD, costs y funding; no ranking de rentabilidad.
Los resúmenes automáticos no contestan preguntas económicas antes de los runs.
Revisión posterior: REJECTED, INCONCLUSIVE o PROMISING_BUT_UNCONFIRMED según evidencia
y límites documentados en informe separado. No umbrales nuevos automáticos ni
PAPER_TRADING_CANDIDATE. No asignar promising/validated a metadata.

## Contexto frente a investigaciones previas

A comparte motor conceptual con trend_following/donchian_adx, Bollinger/Keltner/
Supertrend/MTF trend pullback; magnitudATR, ADX25, shorts y salida distinta no
demuestran independencia estadística. B comparte precio/momentum con time_series_momentum
horario: difiere horizonte30d, EMA, frecuencia y riesgo explícito.
C es fuerza persistente RSI, distinto de EMA/RSI pullback o reset; todavía pertenece
al complejo momentum/trend. La decisión humana RSI pullback actual es NOT_VALIDATED,
según research_results/trend_rsi_pullback/RESEARCH_STATUS.md; no se reauditaron sus trades.
Intradía breakout/range permanecen RESEARCH ONLY, con resultados pendientes según
sus status locales. D sí añade un dato de funding distinto del precio, pero probar
incrementalidad requiere control precio-only posterior. No recalcular familias antiguas
ni adjudicar fuente de edge nueva por nombres o literatura.

## Comandos exactos para ejecución local

```powershell
Set-Location 'C:\Users\joshu\OneDrive\Escritorio\WEBS\Back_testing\trading-lab'
$py = '.\.venv\Scripts\python.exe'
# Preparación offline explícita; ya realizada en este checkout, repetición verifica identidades.
& $py scripts/prepare_literature_data.py

# 1. Validate Donchian
& $py scripts/lab.py validate donchian_trend_v1_btc_eth_4h
& $py scripts/lab.py validate donchian_trend_v1_btc_eth_4h --full
# 2. Run Donchian
& $py scripts/lab.py run donchian_trend_v1_btc_eth_4h
& $py scripts/lab.py report donchian_trend_v1_btc_eth_4h
# 3. Validate Risk Managed Momentum
& $py scripts/lab.py validate risk_managed_momentum_v1_btc_eth_4h --full
& $py scripts/lab.py validate risk_managed_momentum_v1_btc_eth_1d --full
# 4. Run Risk Managed Momentum 4H
& $py scripts/lab.py run risk_managed_momentum_v1_btc_eth_4h
& $py scripts/lab.py report risk_managed_momentum_v1_btc_eth_4h
# 5. Run Risk Managed Momentum 1D
& $py scripts/lab.py run risk_managed_momentum_v1_btc_eth_1d
& $py scripts/lab.py report risk_managed_momentum_v1_btc_eth_1d
# 6. Validate RSI Momentum
& $py scripts/lab.py validate rsi_momentum_regime_v1_btc_eth_4h --full
# 7. Run RSI Momentum
& $py scripts/lab.py run rsi_momentum_regime_v1_btc_eth_4h
& $py scripts/lab.py report rsi_momentum_regime_v1_btc_eth_4h
# 8. Validate Funding Conditional
& $py scripts/lab.py validate funding_conditional_momentum_v1_btc_eth_1h --full
# 9. Run Funding Conditional
& $py scripts/lab.py run funding_conditional_momentum_v1_btc_eth_1h
& $py scripts/lab.py report funding_conditional_momentum_v1_btc_eth_1h
# 10. Compare — solo tras completar los cinco runs
& $py scripts/lab.py compare donchian_trend_v1_btc_eth_4h risk_managed_momentum_v1_btc_eth_4h risk_managed_momentum_v1_btc_eth_1d rsi_momentum_regime_v1_btc_eth_4h funding_conditional_momentum_v1_btc_eth_1h
# 11. Generate research_results
& $py scripts/lab.py publish donchian_trend_v1_btc_eth_4h
& $py scripts/lab.py publish risk_managed_momentum_v1_btc_eth_4h
& $py scripts/lab.py publish risk_managed_momentum_v1_btc_eth_1d
& $py scripts/lab.py publish rsi_momentum_regime_v1_btc_eth_4h
& $py scripts/lab.py publish funding_conditional_momentum_v1_btc_eth_1h
& $py scripts/lab.py publish-comparison latest
```

Conservar run/comparison IDs. latest es la comparación recién creada si no se
generan otras entre medias; después sustituir por comparison_id exacto.
Cada run escribe results/<experiment>/<run>/; informes comparativos
reports/lab-comparison/<comparison>/; publicaciones research_results/<family>/<experiment>/<run>/,
cross_family/comparison/<comparison>. Family elimina solo sufijo_v1.
Publicación limitada por archivo5MB, no equity/datasets/SQLite, sin Git automático.

Para análisis posterior entregar de cada uno: ai_summary.md, summary.md,
metrics_compact.csv, metadata.json, exact_parameters.json y entry_diagnostics.csv
(si omitido por límite, metadata registra omisión). Comparación: comparison.csv,
sources.json y summary.md. No subir directorios completos. Revisar especialmente
casos funding, costes, concentración, lados, años y límites de cohorte/warmup.

## Verificación e inventario de cambios

Suite completa: **928 passed**,65 nuevos,774 avisos de deprecación Matplotlib/pandas
procedentes de reporting histórico; sin fallos. Ruff/check y formato correctos,
pip check sin conflictos. Cinco experimentos FULL VALID; FAST se comprueba también
con las configuraciones reales en tests dirigidos. Sin backtests históricos reales.

Creados: cuatro estrategias y YAML homónimos; cinco experiments listados arriba;
src/quant_lab/literature_features.py, literature_data.py, literature_metrics.py,
lab_funding_adapter.py; scripts/prepare_literature_data.py; cuatro tests unitarios
homónimos, test_literature_contracts.py, integration/test_literature_lab.py; este
protocolo y cuatro RESEARCH_STATUS.md. Preparación genera datos solo locales/ignorados.

Modificados: strategies/base.py, indicators.py, intraday_metrics.py, mtf_features.py,
lab_schema.py, lab_runner.py, lab_reporting.py, lab_publish.py y lab_comparison.py
bajo src/quant_lab; tests de catálogo/config; README, PROJECT_STATE, ARCHITECTURE,
lab-workflow, COMMANDS, README del cuaderno y skill create-experiment.
Contratos opt-in y valores horarios default preservados; datasets, costes globales,
forward, motores perpetuos originales y estrategias/resultados previos intactos.
