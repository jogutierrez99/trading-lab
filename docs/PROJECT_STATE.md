# Estado actual del Trading Lab

Extensión 2026-10-07: [ETH SHORT regime challenge V1](eth-short-regime-challenge-v1.md).
Tres experimentos ETHUSDT1h SHORT_ONLY reutilizan grids/señales/riesgo de Trend
Expansion; ATR/híbrida como hipótesis y Donchian control. 354 backtests previstos,
cuatro WF originales y años diagnósticos predeclarados. Reporting con etiquetas
causales dirección/ATR, muestra mínima descriptiva20 y dependencia de outliers;
CLI validate/run/compare/publish y compactos auditados inmutables. Protocolo YAML
fijado por hashes y registrado en provenance. Post-selección exploratoria del TEST;
sin holdout independiente, clasificación económica automática ni aprobación paper.
Verificación FAST/FULL,66 tests dirigidos aprobados y Ruff/check/format correctos;
ningún challenge histórico
ejecutado por Codex. Resultados económicos y revisión humana pendientes.

Extensión 2026-10-06: [Trend / Expansion V1](trend-expansion-v1.md), implementación
de Donchian1h e impulsoATR long/short y adapter Donchian+ATR que hereda entradas
congeladas de trend_volatility_breakout_v1, con salidaDonchian opt-in. Benchmark
ema_pullback sin cambios, soloLONG y salidaEMA original. Cuatro YAML ordinarios,
BTC/ETH1h, BASE/ADVERSE, 1/6/3/6 configuraciones,1448 backtests locales previstos.
Comparación mantiene activos separados; informes por regionesTRAIN/base y distribución
de trades auditan ledger/result/equity y publican allowlist compacta única. Fase2
congela nominación humana, cuatro salidas, sin ejecutar ni escoger supervivientes.
FAST/FULL reales válidos; suite completa1030 tests y Ruff/check/format correctos,
freeze RMM FAST conservado. Sin backtests históricos; historial reutilizado exploratorio,
sin holdout independiente ni incorporación a forward/OKX. Verificación sintética
y regresiones documentadas en el protocolo, no evidencia económica nueva.

Extensión 2026-10-04: [RMM 4h OKX DEMO](forward-rmm-4h.md), cuatro alternativas
independientes congeladas200/180/180/10, warmup1000. Reutiliza forward, SQLite,
recovery, shadow y watcher; una MAIN seleccionada puede enviar market demo tras
SIGNAL_ONLY>=4h y recibo verificado. D siempre SHADOW_CANDIDATE. PnL observado
separado del modelado; net demo excluye funding desconocido. Discovery público EEA
ETH/BTC X-Perp linear USD verificado; cuenta privada/WS prolongado/Telegram/órdenes
demo pendientes de fases locales. Legacy sigue SIGNAL_ONLY y live bloqueado.
Verificación:953 tests suite completa,138 regresiones forward,14 RMM específicos;
Ruff check/format pasan. Sin ejecución del forward ni órdenes/notificaciones reales.

Diagnóstico operativo 2026-10-05: la cuenta demo verificada por el usuario no implica
warmup válido. GET público ETH X-Perp devuelve902 velas4h/3611 horas, insuficientes
para1000 velas4h; arranque RMM bloqueado por historial. `verify_forward_rmm.py warmup`
comprueba ambos activos sin crear sesión. Se conserva el protocolo congelado y
se informa del bloqueo sin reducir warmup ni mezclar fuentes.
Preflight público dirigido: BTC sí aporta1000 velas4h continuas; ETH bloquea la
prueba conjunta.67 tests forward dirigidos y Ruff de archivos afectados pasan.

Variante operativa [BTC-only](forward-rmm-btc-4h.md): YAML separado
`okx_demo_rmm_btc_4h.yaml`, alternativas C MAIN/D shadow, warmup1000 congelado.
Discovery/gate se limitan a los activos configurados; recibo y journal propios.
La prueba conjunta conserva sus dos activos obligatorios. Implementación y tests
sintéticos; cuenta BTC, observación prolongada y ejecución demo pendientes del usuario.

Watcher: `--state-dir` permite cursor local fuera de OneDrive con migración validada,
sin borrar origen ni perder pending; lock sigue vinculado al DB. Replace Windows
reintenta bloqueos transitorios de forma acotada.64 tests notifier pasan. Cambia
el hash global: runner ya abierto continúa; futuros recibos RMM exigen el código vigente.

Preflight RMM `account` y entradas demo requieren `totalEq` finito positivo mediante
GET; el ledger modelado no aporta fondos al exchange. No bloquea salidas reduceOnly
ni demuestra margen suficiente. Diagnóstico de envío incierto conserva SUBMITTING
y consulta orden/ocupación/fills/permisos sin mutar journal ni reenviar.35 tests RMM
sintéticos pasan; no se enviaron órdenes durante esta verificación.

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
| Sizing | stop_risk, fixed_notional, volatility_target; horario legacy, opt-in 4h/1d para Risk Managed Momentum V1 |
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

Catálogo real: **39**, estado de metadata **research**. Versión 1.0.0 salvo
trend_volatility_breakout_v1 1.0.1 (corrección de warmup).
`L` = LONG_ONLY; `L/S/LS` = LONG_ONLY, SHORT_ONLY, LONG_SHORT. Son capacidades declaradas
del adaptador, no resultados de validación económica ni garantía de YAML habilitado.
Los protocolos dedicados pueden evaluar otros timeframes mediante traducciones explícitas.

| Strategy | Version | Modes | Timeframes lab | Adaptador / status |
|---|---|---|---|---|
| atr_breakout | 1.0.0 | L | 1h | ohlcv / research |
| atr_volatility_breakout | 1.0.0 | L/S/LS | 1h | ohlcv / research |
| bb_squeeze | 1.0.0 | L | 1h | ohlcv / research |
| bollinger_regime_reversal | 1.0.0 | L/S/LS | 1h | legacy_batch_006 / research |
| channel_break_retest | 1.0.0 | L | 1h | ohlcv / research |
| donchian_adx | 1.0.0 | L | 1h | ohlcv / research |
| donchian_atr_breakout | 1.0.0 | L/S/LS | 1h | ohlcv / research, entradas heredadas V1 |
| donchian_trend_breakout | 1.0.0 | L/S/LS | 1h | ohlcv / research |
| donchian_trend_v1 | 1.0.0 | L/S/LS | 4h | ohlcv / research |
| dual_momentum | 1.0.0 | L | 1h | ohlcv / research |
| ema_pullback | 1.0.0 | L | 1h | ohlcv / research |
| funding_conditional_momentum_v1 | 1.0.0 | L/S/LS | 1h | perpetual_funding / research |
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
| range_mean_reversion_v1 | 1.0.0 | L/S/LS | 15m + contexto 1h | ohlcv, niveles absolutos opt-in / research |
| regime_trend | 1.0.0 | L | 1h | ohlcv / research |
| rsi_momentum_reset | 1.0.0 | L | 1h | ohlcv / research |
| risk_managed_momentum_v1 | 1.0.0 | L/S/LS | 4h, 1d | ohlcv, sizing volatilidad opt-in / research |
| rsi_momentum_regime_v1 | 1.0.0 | L/S/LS | 4h | ohlcv / research |
| time_series_momentum | 1.0.0 | L/S/LS | 1h | ohlcv / research |
| trend_acceleration | 1.0.0 | L | 1h | ohlcv / research |
| trend_following | 1.0.0 | L/S/LS | 1h, 4h, 1d | ohlcv / research |
| trend_rsi_pullback_v1 | 1.0.0 | L/S/LS | 15m | ohlcv, V1/V2/V3 causales / research |
| trend_volatility_breakout_v1 | 1.0.1 | L/S/LS | 1h | ohlcv / research |
| trend_strength | 1.0.0 | L | 1h | ohlcv / research |
| vol_contraction_expansion | 1.0.0 | L | 1h | ohlcv / research |
| vol_expansion_trend | 1.0.0 | L | 1h | ohlcv / research |
| vol_momentum | 1.0.0 | L | 1h | ohlcv / research |
| volatility_breakout_intraday_v1 | 1.0.0 | L/S/LS | 15m + contexto 1h | ohlcv / research |

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

## Trend Volatility Breakout (2026-10-04)

V1 1h: EMA/slope + canal de barras anteriores + ATR actual/media de los 50 ATR
anteriores. ATR/RR enlazados a RiskConfig; sin nuevo backend/sizing ni filtros extra.
ETH/BTC separados, mismo grid 144 y protocolo temporal largo vigente: TRAIN desde
2023-06-04, VALIDATION desde 2024-07-01, TEST 2025-07-01→2026-09-26, cuatro WF.
Warmup conservador dinámico 5×EMA: 500/1000 barras; máximo del grid 1000.
BASE app y ADVERSE ordinario conservados. `lab.py robust` completa solo WF TEST
propios BASE/ADVERSE faltantes de candidatos RESEARCH_PASS + OOS_PASS, con reutilización
verificada, suplementos inmutables y reclasificación; el WF adaptativo permanece separado.
`prepare_lab_1h_prices.py` verifica fuentes USD-M fijadas y conserva velas/identidad
en bundles lab locales; ejecución synthetic, funding not modelled. Sin cambio a
forward, OKX ni RSI. Hipótesis ETH NEW_HYPOTHESIS, BTC PREPARED_NOT_EXECUTED.
RSI Single-TF RESEARCH_COMPLETED / NOT_VALIDATED; challenge ETH
HISTORICAL_CHALLENGE_FAILED_ROBUSTNESS / NOT_VALIDATED según decisión del usuario;
historial preservado. [Reglas, límites de WF y comandos](trend-volatility-breakout.md).
Tests sintéticos y validación técnica no equivalen a resultados económicos; los
grids completos quedan para el usuario. TEST es OOS específico sobre historia ya
observada a nivel del proyecto, no evidencia independiente futura.
Verificación de la corrección: suite completa 806 passed; Ruff/format y dependencias
correctos; ETH/BTC FAST y FULL VALID. Sin grids históricos ni robustez real ejecutados.

## Hipótesis intradía independientes (2026-10-04)

Breakout compresión→ruptura→expansión y RANGE rechazo→midpoint: una configuración
por familia, BTC/ETH 15m, contexto 1h completo y warmup2004. Fuente USD-M 2020–2026
fijada; evaluación desde 2020-02-01 para disponer de warmup. Ejecución synthetic,
sin funding/liquidaciones. BASE/ADVERSE y tres modos separados; RESEARCH ONLY.
RANGE añade niveles absolutos opt-in sobre sizing/protecciones existentes.
diagnostic_periods reutiliza segmentos/ledger/resume para siete años independientes,
fuera de selección y gates. 120 backtests previstos por familia, ninguno histórico
ejecutado por el agente. [Protocolo, adaptaciones y comandos](intraday-strategies-v1.md).
Verificación: 863 tests aprobados (57 nuevos), Ruff/check y format correctos,
dependencias sin conflictos; ambos experimentos FAST/FULL VALID. Solo pruebas
sintéticas pequeñas de ejecución/reutilización/publicación; resultados económicos pendientes.

## Literatura V1 (2026-10-04)

Cuatro familias nuevas RESEARCH ONLY: Donchian4h, Risk Managed Momentum4h/1d,
RSI Momentum4h y Funding Conditional1h. Una configuración por timeframe; tres modos,
BTC/ETH y BASE/ADVERSE. 120 ejecuciones por experimento excepto diario84; total564,
ninguna histórica real ejecutada por el agente. [Protocolo](literature-hypotheses-v1.md).

Datos preparados offline bajo data/literature_v1/ desde USD-M15m auditado,
agregación completa1h/4h/1d, sin señal15m ni alterar fuentes. Warmup EMA1000 barras:
4h desde2020-07-01, diario desde2023-01-01; funding728h desde2020-02-01.
Funding público archivado+REST retenido:7380 eventos por activo,2020-01-01→
2026-09-25 16:00:00.002UTC,8h, sin settlements ausentes; offsetmáximo0.047s.
Mark tiene216/72 horas ausentes BTC/ETH; cohorte común2451 días, nueve excluidos.

PerpetualLabExecution y adapter perpetual_funding opt-in llaman al motor1x existente,
funding incluido en PnL, margen/liquidación asumidos; días completos matched,
liquidación/cash/reinicio de features entre gaps. Disponibilidad de funding asumida
al settlement; publicación independiente/latencia desconocidas. No es paper/live.
Los demás usan synthetic sin funding. Volatility sizing4h/1d exclusivo del nuevo
Momentum, anualización explícita2190/365 y exposición5–25% fijada a entrada,
sin rebalanceo continuo. Los guards legacy permanecen.

Verificación: **928 tests passed**,65 nuevos;774 avisos de deprecación de reporting
histórico. Ruff/check, formato, pip check correctos; cinco experimentos FULL VALID.
Tests sintéticos pequeños incluyen fills/funding/MFE-MAE, causalidad, resume,
compare y publicación. Resultados económicos y clasificación prudente pendientes;
ningún cambio a forward/OKX ni a configuraciones/resultados históricos.


## Risk Managed Momentum 4h: falsación congelada

[Protocolo y comandos](rmm-final-falsification-v1.md): cuatro candidatos A/B/C/D, seis folds fijos,
control fixed15%, vecinos ligados150/180/210, años y BASE/ADVERSE. Cuatro
experimentos ordinarios singleton;704 backtests para ejecución local del usuario.
POST-SELECTION FALSIFICATION / ROBUSTNESS CHALLENGE, sin nuevo holdout independiente.
`lab.py falsification validate [--full]` verifica freeze/datos; `falsification report
--runs RUN180 RUNFIXED RUN150 RUN210` audita fuentes y exporta compactos únicos,
sin simular ni aprobar demo. Strategy/engine/global risk/forward sin cambios.

Verificación:939 tests completos aprobados;11 dirigidos repetidos tras cierre del
lock de candidatos/criterios. Ruff/format/pip correctos; cuatro FAST/FULL VALID,
sin challenge histórico ejecutado. Clasificación final pendiente de resultados y
revisión humana. El lock en configs/research queda registrado en provenance de runs.
