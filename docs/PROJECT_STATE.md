# Estado actual del Trading Lab

Fecha de inspección: **2026-09-28**. Memoria operativa compacta, no historial de runs.
Fuentes: código/configuración presentes, catálogo CLI y manifiestos/resúmenes locales
seleccionados. La lectura de un recibo histórico no equivale a repetir su auditoría.
Datos y resultados están ignorados por Git y pueden faltar en otro checkout.

## Motor y configuración

Extensión 2026-10-04: `classify` aplica perfil versionado y gates separados de PASS
legacy, sin rerun; `compare`/`report` enlazan suplementos vigentes. `publish` y
`publish-comparison` generan un cuaderno Git compacto con límite por archivo, sin
subir resultados pesados ni ejecutar Git. Challenge ETH Single-TF: tres candidatos
congelados, 24 backtests previstos, historia anterior con warmup explícito; no ejecutado
por el agente. Las decisiones humanas de familia se mantienen separadas de gates
automáticos. [Contrato](research-evidence.md), [cuaderno](../research_results/README.md).

| Ámbito | Estado confirmado |
|---|---|
| Paquete | `quant-trading-lab` 0.1.0, Python >=3.12 |
| CLI ordinaria | `scripts/lab.py`, `StudyBackend v1`, ejecución serial offline |
| Recuperación lab | `run ID --resume [RUN_ID]`, auditoría `--check`; continuación nueva con referencias a artefactos verificados, sin cambiar estrategia/protocolo |
| Motor histórico | `backtest.py` referencia v3 y adaptadores especializados conservados |
| Mercado lab | Spot LONG_ONLY; cortos/combined sintéticos colateralizados, sin funding/préstamo |
| Capital base | `configs/app.yaml`: 10000; el experimento puede sobrescribirlo |
| Costes app | Comisión 0.05%, slippage 0.03%, spread completo 0.01%; cada fill usa medio spread |
| Riesgo base | 1% por trade, posición máxima 25%, exposición máxima 100%, ATR14 ×2, target 2R |
| Sizing | stop_risk, fixed_notional, volatility_target; este último solo 1h en lab |
| Apalancamiento lab | Sin apalancamiento, exposición máxima permitida 100% |
| Perpetuos dedicados | USD-M isolated 1x; funding histórico, mark y liquidación modelados |
| Supuestos perpetuos | `FuturesAssumptions`: mantenimiento 0.5%, fee de liquidación 0.5%; no reproduce tiers históricos/ADL |
| Seed app | 42; registrar también seeds específicos cuando un estudio usa Monte Carlo |

Estos son defaults, no constantes de todos los estudios. Perfiles, costes ZERO/BASE/ADVERSE
y sizing especializados están congelados en cada protocolo. Por ejemplo cross-market
usa slippage BASE 0.02%, distinto del 0.03% de app. Leer `resolved.json`/plan del run.

Recuperación lab implementada el 2026-09-30: validada con fixtures de interrupción,
corrupción y equivalencia con un run fresco; mantiene TRAIN/WF, filtros y ejecución.
No se completaron grids históricos durante la implementación. El uso de `--resume`
exige verificar los artefactos fuente y conservar sus carpetas (referencias sin copia).

## Datos encontrados

Coberturas en UTC, fin exclusivo. No implican continuidad donde se indican huecos.

| Familia local | Activos / resolución | Cobertura y límite |
|---|---|---|
| `data/history/77a552…` | BTC/USDT spot 1h | Estudio 2022-01-01 → 2023-02-01, 200 barras de warmup |
| `data/history/232203…` | BTC/USDT spot 1h | Estudio 2022-01-02 → 2023-03-01, 768 barras de warmup; ejemplo lab usa subconjuntos |
| `data/history/5810d6…` | BTC/USDT spot 1h | Estudio 2023-05-03 → 2026-01-01, 768 barras de warmup |
| `data/cross_market_timeframe_study_001/` | BTCUSDT, ETHUSDT spot; 1h/4h/1d | 2018-01-01 → 2026-09-22; varias revisiones 1h, huecos 1h/4h, diarios VALID según manifests |
| `data/batch_006_perpetual/` | BTCUSDT, ETHUSDT; klines 1h/4h/1d, mark 1h, eventos funding | Cohorte de protocolo 2020-01-01 → 2026-09-26; revisar identidad exacta del plan |
| `data/mtf_15m/` | BTCUSDT, ETHUSDT; contrato y mark 15m | 2020-01-01 → 2026-09-26; contrato VALID, mark con huecos; cohorte matched excluye 18 días |
| `data/archives/`, `data/csv/`, `data/gap-audits/` | Fuentes y auditorías | No confundir archivos fuente o solicitudes rechazadas con bundles aptos |

Los prefijos anteriores son ayudas de lectura; nunca resolver datos por prefijo ambiguo.
El YAML y los manifests conservan hashes completos. Lab verifica SHA256 de Parquet,
fingerprint, mercado, cobertura y continuidad incluyendo warmup. No hay dataset spot
continuo válido para la solicitud original 2022–2025: los bundles separados y el estudio
con huecos no la convierten en válida. `configs/markets.yaml` incluye 5m como configuración,
no prueba una descarga 5m ni soporte de ese timeframe en lab.

## Estrategias implementadas

Catálogo real: **29**, todas versión **1.0.0**, estado de metadata **research**.
`L` = LONG_ONLY; `L/S/LS` = LONG_ONLY, SHORT_ONLY, LONG_SHORT. Son capacidades declaradas
del adaptador, no resultados de validación económica ni garantía de YAML habilitado.
Los protocolos dedicados pueden evaluar otros timeframes mediante traducciones explícitas.

| Strategy | Version | Modes | Timeframes lab | Adaptador / status |
|---|---|---|---|---|
| atr_breakout | 1.0.0 | L | 1h | ohlcv / research |
| bb_squeeze | 1.0.0 | L | 1h | ohlcv / research |
| bollinger_regime_reversal | 1.0.0 | L/S/LS | 1h | legacy_batch_006 / research |
| channel_break_retest | 1.0.0 | L | 1h | ohlcv / research |
| donchian_adx | 1.0.0 | L | 1h | ohlcv / research |
| dual_momentum | 1.0.0 | L | 1h | ohlcv / research |
| ema_pullback | 1.0.0 | L | 1h | ohlcv / research |
| low_vol_pullback | 1.0.0 | L | 1h | ohlcv / research |
| mean_reversion | 1.0.0 | L/S/LS | 1h, 4h, 1d | ohlcv / research |
| mtf_bollinger | 1.0.0 | L/S/LS | 1h | legacy_mtf / research |
| mtf_donchian | 1.0.0 | L/S/LS | 1h | legacy_mtf / research |
| mtf_ema_adx | 1.0.0 | L/S/LS | 1h | legacy_mtf / research |
| mtf_keltner_breakout | 1.0.0 | L | 1h, 15m | legacy_mtf / research |
| mtf_momentum | 1.0.0 | L | 1h | ohlcv / research |
| mtf_roc_momentum | 1.0.0 | L | 1h, 15m | legacy_mtf / research |
| mtf_supertrend_pullback | 1.0.0 | L | 1h, 15m | legacy_mtf / research |
| mtf_trend_pullback | 1.0.0 | L/S/LS | 1h | legacy_mtf / research |
| mtf_volatility_expansion | 1.0.0 | L | 1h, 15m | legacy_mtf / research |
| regime_meanrev | 1.0.0 | L | 1h | ohlcv / research |
| regime_trend | 1.0.0 | L | 1h | ohlcv / research |
| rsi_momentum_reset | 1.0.0 | L | 1h | ohlcv / research |
| time_series_momentum | 1.0.0 | L/S/LS | 1h | ohlcv / research |
| trend_acceleration | 1.0.0 | L | 1h | ohlcv / research |
| trend_following | 1.0.0 | L/S/LS | 1h, 4h, 1d | ohlcv / research |
| trend_rsi_pullback_v1 | 1.0.0 | L/S/LS | 15m | ohlcv, V1/V2/V3 causales / research |
| trend_strength | 1.0.0 | L | 1h | ohlcv / research |
| vol_contraction_expansion | 1.0.0 | L | 1h | ohlcv / research |
| vol_expansion_trend | 1.0.0 | L | 1h | ohlcv / research |
| vol_momentum | 1.0.0 | L | 1h | ohlcv / research |

`liquidity_sweep` y `breakout_retest` siguen como YAML reservados sin implementación.
Los perfiles originales deshabilitados no se habilitan automáticamente; el ejemplo
ordinario utiliza `configs/profiles/lab_trend.yaml` explícitamente habilitado.

## Investigación y MTF

| Línea | Capacidad / evidencia actual |
|---|---|
| Lab YAML | Un experimento versionado: `trend_btc_1h_001`, BTC 1h LONG_ONLY, Donchian 20/40; train feb–mar 2022, validation abril, test mayo, BASE/ADVERSE; 12 backtests |
| Batch 001–005 | 19 estrategias/configuraciones congeladas, selección temporal y diagnósticos; conservar código/perfiles/artifacts de cada protocolo |
| Cross-market | BTC/ETH, 1h/4h/1d, traducciones explícitas, stress, Monte Carlo y diagnósticos; evidencia exploratoria |
| Batch 006 | Bollinger long/short perpetuo y funding; resultados documentados sin candidatos prometedores bajo su protocolo |
| Serie MTF | V1 baseline 1h, V2 filtro 4h cerrado, V3 alineación 4h/1h/15m, V4 recuperación; cohortes original y matched; MTF04 sin supervivientes según informe |
| Refinamiento | V2.1/V4.1, oportunidades de un solo uso/cooldown/extensión; informe sin candidatos operativos paper |
| Nuevas MTF | Cuatro familias V1/V2/V4 LONG_ONLY. A evalúa 16 configuraciones; B solo si RESEARCH_PASS; NEAR_PASS es watchlist |
| Timing 15m | Experimento de ejecución sobre tres configuraciones ETH fijadas: Supertrend V2, ROC V2/V1. No son estrategias nuevas |
| Optional fill 15m | Seis parejas congeladas, optimización causal y fallback al precio de mercado tras hasta 60 min; puede empeorar fill o perder trades por sizing/ocupación. [Protocolo](optional-15m-fill.md), runners/preflight dedicados; implementación, sin batch histórico ejecutado por el agente |

Excepción al nombre MTF: `mtf_momentum` es OHLCV 1h con régimen 4h derivado causalmente,
y puede usar lab. Las otras familias `legacy_mtf` necesitan sus runners. Valores HTF solo
están disponibles cuando cierra la vela completa. Timing 15m consume oportunidades 1h;
no convierte retrospectivamente un trigger anterior en entrada. Detalles de restricciones
V1–V4 y reinicios por huecos en [serie MTF](mtf-series-design.md),
[nuevas MTF](new-mtf-strategies.md) y [timing](entry-timing-15m.md).

Evidencia local seleccionada, leída sin repetir estudios:

- `results/trend_btc_1h_001/20260927T162220Z-9f3ca92a5354/outcome.json` registra COMPLETE, 12 backtests.
- `results/new_mtf_strategies/20260927T183211Z-caef33c4aef0/verification.json` registra B omitida,
  cero configuraciones; el resumen indica que ninguna V1/V2 obtuvo RESEARCH_PASS.
- `results/entry_timing_15m/20260928T064408Z-16de9b156291/verification.json` registra completed,
  1008 ejecuciones y 504 baselines reproducidos. Su `ai_summary.md` clasifica las tres
  variantes TIMING_WORSE / ARCHIVE_TIMING_VARIANT. No se han reauditado sus operaciones aquí.

## Trend RSI Pullback (2026-09-29)

Nueva familia `trend_rsi_pullback_v1`: SMA/RSI, ATR y RR mediante RiskConfig existente,
V1 15m, V2 tendencia 1h cerrada y V3 slope 5h. Lab admite explícitamente 15m con
formato local mtf_quarters, hash fijado y auditoría quarter existente. Cortos synthetic,
sin funding/liquidaciones, aunque los precios fuente sean USD-M. Legacy guards intactos.
Cuatro experimentos: referencia de una configuración y tres grids de 486; BTC/ETH,
tres modos, 1004 barras warmup. Filtros/costes conservados de trend_btc_1h_001;
protocolo temporal corregido: TRAIN 2023-06-04→2024-07-01, VALIDATION hasta 2025-01-01,
cuatro folds de Batch 003 y TEST/final holdout 2025-07-01→2026-09-26 (fin exclusivo).
Previsión: 132 backtests de referencia y 40872 por grid; resultados anteriores conservados.
Corrección temporal verificada con FULL en los cuatro YAML y 56 tests dirigidos;
ningún backtest histórico ejecutado para esta corrección.
WF admite evaluar una referencia única predeclarada con ranking TRAIN indefinido,
con aviso y sin alterar null/filtros. Grids múltiples siguen fallando sin elegibles.
`lab.py compare` genera comparación inmutable de resultados existentes por periodo,
coste y modo, con ejemplos ordenados solo por TRAIN. No promoción de research/paper.
[Protocolo y comandos](trend-rsi-pullback.md). Catálogo deshabilitado y perfil propio
habilitado; sin cambios a estrategias previas, configuración global ni forward.
Verificación: 653 tests completos aprobados (33 nuevos), Ruff/format de 300 archivos
y pip check correctos. Grids históricos no ejecutados; solo fixtures sintéticos.

## Límites y continuación

Forward SIGNAL_ONLY: capas separadas brokers/market_data/forward, OKX EU demo GET-only,
BTC/ETH X-Perps (API actual settleCcy=USD, sin equiparar a USDC; señales solo ETH
Trend Pullback V1 baseline + OPTIONAL_15M_FILL).
REST/WS confirmado, sizing por metadatos, journal SQLite/checkpoint y reportes locales.
Sin órdenes demo/live; estado shadow no replica funding/liquidación. Paridad técnica
con fixtures, no evidencia económica forward. Ver [protocolo](forward-signal-only.md)
y sus comandos. Connectivity pública REST verificada tras identificar el cliente HTTP
con User-Agent propio (el predeterminado recibía 403/Cloudflare 1010). Instrumentos y
velas 15m/1h/4h disponibles; cuenta privada y WebSocket real aún sin verificar.
No quedó ningún runner en ejecución.
Protocolo forward autorizado `eth_v1_required_1h_15m`: ETH 1h/15m obligatorios,
BTC y ETH 4h solo monitorización, con avisos persistentes sin alterar señales/timing.
ETH 4h de 2026-07-02T04:00:00Z sigue confirm=0: el historial no se certifica ni se rellena;
ya no bloquea las dos variantes V1. Preflight verifica el warmup obligatorio y registra
los avisos opcionales. Connectivity rápido no valida warmup. V2/4h sigue sin habilitarse.
Preflight público más reciente: 540 tests con Python 3.13 local, Ruff check/format
(283 archivos), pip check y warmup ETH 1h/15m correctos; aviso no bloqueante ETH 4h.
Recibo `reports/forward/preflight/20260928T152926Z-dda60ae2efd8.json`.
WebSocket demo comprobado hasta primera actualización y cerrado; no sesión continua.

Recovery forward: incidentes DATA_GAP persistentes y auditoría explícita por feed antes
de resolverlos. REST parcial se conserva separado del contexto de señales; los gaps
pendientes bloquean decisiones y readiness. El reinicio recupera incidentes compatibles
incluso tras cambiar código, sin migrar posiciones entre versiones ni reescribir informes
antiguos. Un gap auditado/resuelto deja de bloquear; el resto de checks sigue vigente.
BTC/4h mantienen monitorización no bloqueante. Protocolo y verificación en
[forward-signal-only](forward-signal-only.md). Sin cambios a estrategias, riesgo o routing.
Verificación del recovery: 554 tests, Ruff (285 archivos) y pip check correctos.
Recibo técnico `reports/forward/preflight/20260928T185408Z-327ead927c70.json`;
la recuperación real de incidentes antiguos queda pendiente del siguiente arranque.

Cotizaciones forward: reintentos GET acotados, refresh de reloj ante timestamps
aparentemente futuros y rechazo explícito sin detener el runner cuando no hay precio
causal válido. QUOTE_UNAVAILABLE/quote_events.csv conservan diagnóstico; se cancelan
pendientes afectados sin inventar fills. Límites 30/90 s y estrategia conservados.

Alertas Telegram implementadas como proceso observacional independiente:
`scripts/notification_watcher.py`, events/sessions SQLite read-only, cursor externo
atómico, primer arranque from-now, replay/dry-run y retries HTTP acotados.
Carga las cuatro variables Telegram desde `.env` del proyecto al iniciar, con prioridad
del entorno de la terminal; no carga variables OKX/trading ni lee `.env` al importar. Ver
[operación y límites de entrega](telegram-notifications.md). Sin cambios a runner,
Store, señales, riesgo ni configuración de trading. Verificación con mocks y journals
temporales; entrega Telegram real pendiente, sin activar un watcher operativo.

Implementados: datos, indicadores, estrategias, backends, persistencia, CLI y protocolos
especializados. Research sigue siendo experimental: holdouts ya consultados no constituyen
nueva evidencia independiente. Legacy significa contrato histórico conservado, no eliminado.

Pendientes documentados: resolver la cobertura histórica original, familias reservadas,
dashboard e integración VectorBT; paper y otras interfaces de monitorización son futuras,
sin routing live. Monte Carlo existe en cross-market, no es una capacidad genérica de lab.
No hay una siguiente fase autorizada por el mero hecho de aparecer en esta lista.

Actualizar esta memoria al cambiar arquitectura, datos disponibles, estrategias, modos,
workflow o MTF; no por cada run. El historial permanece en Git, protocolos y artefactos.

## Observador Shadow PnL (2026-09-30)

Forward incorpora contabilidad observacional separada de la ocupación legacy: posiciones
persistentes, PnL/costes BASE, MFE/MAE, stops conservadores y límite 72h contado en barras
completas. No modifica decisiones/sizing ni ejecución histórica. Barras parciales o
huecos pueden limitar la evidencia; ver [semántica](forward-shadow-pnl.md).
`python scripts/shadow_pnl.py SESSION` reconstruye con snapshot de lectura en un informe
nuevo, sin tocar sesión o journal originales. SIGNAL_ONLY y bloqueo demo/live intactos.

Shadow: preflight técnico final 672 tests aprobados, Ruff/format y dependencias correctos;
17 pruebas nuevas, cuatro experimentos RSI FULL VALID. Reconstrucción read-only de la
sesión solicitada documentada en la guía; sin reiniciar el runner externo ni enviar órdenes.
