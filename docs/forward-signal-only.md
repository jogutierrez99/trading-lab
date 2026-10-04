# Forward OKX EU — SIGNAL_ONLY, protocolo de datos ETH V1

Infraestructura separada de los runners históricos. Solo ETH Trend Pullback V1
LONG_ONLY, versión 1.0.0, con dos alternativas independientes: baseline y la política
existente OPTIONAL_15M_FILL. BTC se observa como market data; no activa otra estrategia.
No se han cambiado estrategias, políticas, motores, datasets ni resultados históricos.

## Seguridad y conexión

Todos los métodos de mutación (`place_order`, `cancel_order`, `close_position`) lanzan
`TradingDisabled`. No existe transporte POST ni implementación funcional demo/live.
Cambiar `TRADING_ENABLED` a true **bloquea** esta versión; no habilita operaciones.
Configuración y entorno exigen demo, OKX_DEMO=true, TRADING_ENABLED=false y
ALLOW_LIVE_TRADING=false. No hay transfers, withdrawals ni endpoints arbitrarios.
Los redirects HTTP se rechazan. Imports no conectan ni leen archivos `.env`.

REST fijo `https://eea.okx.com`, siempre con `x-simulated-trading: 1`.
WebSocket fijo `wss://wseeapap.okx.com:8443/ws/v5/business`, canales candle15m,
candle1H y candle4H. Referencia oficial consultada el 2026-09-28:
[OKX EU API](https://my.okx.com/docs-v5/en/). REST comparte host con producción;
el aislamiento procede de la cabecera demo, claves demo y allowlist GET de lectura.

Instrumentos fijados: BTC-USD_UM_XPERP-310328 y ETH-USD_UM_XPERP-310328.
El lookup verifica FUTURES, xperp, linear, state=live y ctValCcy=activo base.
Acepta settlement USD/USDC y conserva exactamente la moneda devuelta por OKX en
`settlement_currency`. La consulta pública de 2026-09-28 devuelve **USD** para ambos
instrumentos, distinto de USDC indicado inicialmente; no se asume equivalencia.
ctVal, lotSz, minSz, tickSz y lever se obtienen de OKX, no de tamaños hardcodeados.
Decimal convierte base/notional a contratos, redondeando lotes hacia abajo, rechazando
mínimos y valores inválidos. El stop long se redondea al tick hacia arriba para no
aumentar el presupuesto calculado. Objetivo máximo 1x; lever=10 no significa usar 10x.

Credenciales opcionales para el runner público, obligatorias para el connectivity
check privado: exportar OKX_API_KEY, OKX_API_SECRET y OKX_API_PASSPHRASE de **demo**.
Firmas GET HMAC-SHA256/base64 incluyen timestamp, método y ruta con query.
Con credenciales, startup reconciliation lee balance, positions, open orders y fills;
sin ellas registra PUBLIC_ONLY y estado privado desconocido. No mezcla posiciones
del exchange con los dos estados hipotéticos. Cuenta real/demo no se modifica.
No se imprimen secretos, firmas ni cuerpos privados; los snapshots privados se guardan
localmente en results, ya ignorado por Git. No compartirlos sin revisar su contenido.

## Datos, causalidad y diferencias de ejecución

Bootstrap REST paginado, 800 velas confirmadas por instrumento/timeframe por defecto;
ETH 1h y ETH 15m son los únicos feeds obligatorios del protocolo
`eth_v1_required_1h_15m`, aprobado para las dos variantes actuales. Sin suficientes
velas, continuidad o última vela completa en ellos, se aborta. BTC (todos sus timeframes)
y ETH 4h son monitorización: también se audita su historial, pero un fallo produce
MONITORING_WARNING, no habilita ese historial como validado ni bloquea ETH V1.
Se intenta obtener dos velas recientes confirmadas solo para observar el feed;
si tampoco están disponibles, sigue como monitorización no disponible. No se rellena
ningún hueco. El libro de datos usado por las estrategias contiene solo ETH 1h/15m;
las observaciones auxiliares y sus discontinuidades se almacenan separadamente.
Esta separación también aplica a metadatos BTC, recuperación REST, mensajes inválidos
o rechazos de suscripción identificados de canales opcionales y heartbeat.
Una caída del WebSocket compartido sí requiere recuperar los feeds obligatorios.
Valida alineación
UTC, OHLCV, valores finitos y confirm=1; volumen usa volCcy (base), no contratos.
No genera señales desde warmup ni velas incompletas. La señal horaria se evalúa cuando
se recibe el último cuarto cerrado de la hora; se agrega esa hora completa si el canal
nativo aún no llegó. Revisiones contradictorias de velas cerradas son errores.
El canal 4h está preparado como datos, pero V1 no recibe un filtro 4h nuevo.

StrategyAdapter usa exactamente la clase original. La prueba de paridad compara sus
decisiones incrementales con `mtf_execution.prepare` sobre el mismo dataset fijo,
incluyendo entradas positivas y prefix-invariance. Esto prueba paridad de **señales**,
no igualdad económica entre Binance y OKX, ni equivalencia de fills/cuentas.

La estimación de entrada usa ask observado por REST después del cierre, hasta 90 s
después de la frontera, con antigüedad máxima de cotización de 30 s. Conserva los
costes BASE históricos como supuestos explícitos. No llama a ese precio un fill real
ni inventa la apertura exacta que habría existido cuando llegó la señal.
OPTIONAL_15M_FILL recibe esa estimación baseline y cada cuarto posterior cerrado.
Se reutilizan BaselineEntry, OptionalFillPolicy y quarter_features sin copiarlos ni
alterarlos. Primer candidato válido más barato después de costes; fallback a mercado
en +60 min aunque resulte peor. Persiste candidatos, fallback y motivos de no ejecución.

Riesgo/costes se cargan desde `configs/profiles/mtf_series.yaml`, congelado:
capital teórico 10000 por alternativa, riesgo 0.5%, exposición/posición máxima 25%,
ATR14 ×2, sin target/trailing y límite de 72 horas. Usa `risk.size_entry` existente.
Una posición hipotética por alternativa; la baseline limita qué oportunidades recibe
optional fill. Stops baseline observados con barras 1h y optional con 15m, stop-first
y precio conservador en gaps. Las salidas solo actualizan ocupación y saldo **shadow**.
Las alternativas NO se suman en una cartera con capital compartido.

No se modelan funding, liquidaciones por mark ni tiers de margen OKX en este forward;
el saldo shadow no replica una cuenta perpetua. Las reglas originales de señales y
timing son las mismas, pero elegibilidad y precios dependen de estas observaciones
forward. OKX X-Perps es evidencia nueva; no equivale a Binance USD-M/USDT.

## Persistencia y recuperación

SQLite `results/forward/forward.sqlite`: sessions, bars, signals, order_intents, orders,
fills, positions, broker_snapshots, events, recovery_bars y checkpoints. orders/fills permanecen vacías.
IDs deterministas; cada actualización confirma barras, eventos y checkpoint en una
transacción. WAL + synchronous FULL. Lock del sistema operativo impide dos runners
sobre el mismo output y se libera incluso al morir el proceso.

La identidad del stream incluye configuración resuelta, metadatos de ETH y
hash del código. Reiniciar sin cambiar esos elementos restaura estado y deduplica;
cambiarlos inicia evidencia independiente para señales/estado shadow. Los incidentes
de datos pendientes se buscan también en streams anteriores con la misma configuración
resuelta y metadatos ETH, aunque cambie el hash de código. No se migra estado de trading
entre versiones. No borrar la SQLite para reiniciar.
Una pérdida temporal de metadatos BTC no reinicia el estado de las estrategias.
Una interrupción entre eventos y checkpoint revierte la transacción completa.

Heartbeat cada 30 s: conexiones, últimas velas, última señal y estado. Timeout, cierre
WebSocket o feed desactualizado provoca DATA_GAP, pausa decisiones, recuperación REST
y reconexión con backoff acotado. Si REST no recupera continuidad, reintenta hasta el
límite configurado y termina con error conservando el incidente pendiente.
Nunca rellena velas ni salta huecos. Las barras recuperadas actualizan contexto y shadow
pero no crean intents tardíos. Si se perdieron cuartos, cancela pendientes con motivo;
un reinicio sin velas perdidas conserva el pendiente. DATA_GAP/RECONNECTED mantienen
la auditoría. Un gap recuperado deja de bloquear readiness solo tras auditoría explícita.

El incidente conserva los últimos opens persistidos y, cuando existe, el primer open
nuevo observado. La auditoría llega hasta la última vela cerrada según la hora del
servidor, por instrumento/timeframe: expected_start/end/interval, bars_expected/present,
missing_timestamps, duplicates, out_of_order y continuity_ok. Las respuestas REST
parciales confirmadas quedan en recovery_bars; solo pasan al contexto de señales cuando
el conjunto requerido es continuo. Nunca se fabrican velas ni se aceptan velas abiertas.
Solapamientos idénticos se deduplican y se contabilizan; revisiones contradictorias y
respuestas desordenadas mantienen el bloqueo. Las auditorías BTC/4h son no bloqueantes,
conforme a las dependencias V1; un aviso opcional no certifica su historial.

Al resolver se actualiza el DATA_GAP original con resolved=true, resolved_at,
resolution=REST_CONTINUITY_VERIFIED, recovered_bars y continuity_verified=true.
Si faltan datos conserva resolved=false, resolution=RECOVERY_INCOMPLETE y timestamps
faltantes. SIGNAL_BLOCKED_DATA_GAP deja constancia de la pausa y de evaluaciones
bloqueadas; las barras de recuperación no generan entradas retrospectivas. Reintentos
reutilizan el incidente y no duplican barras, resoluciones ni RECONNECTED. Cero barras
recuperadas es válido cuando cayó la conexión pero no faltó ninguna vela cerrada.

Startup audita primero incidentes anteriores. Para incidentes antiguos sin límites
temporales audita todo su historial persistido y el intervalo hasta el presente; nunca
deduce continuidad solo de la última vela. La resolución actualiza SQLite y el informe
de la sesión nueva, conservando los archivos de las sesiones anteriores.

Cada arranque crea `results/forward/<session_id>/` con session.json, bars.csv,
signals.csv, order_intents.csv, timing_events.csv, positions_snapshot.csv,
broker_state.csv, monitoring_bars.csv, monitoring_warnings.csv, data_gaps.csv,
continuity_audits.csv, recovery_events.csv, errors.log, summary.md
y ai_summary.md. CSV/Markdown son vistas
regenerables del journal de esa sesión; SQLite conserva también sesiones anteriores.
session.json incluye configuración, instrumentos, hashes, Git/runtime y timestamps.
Informes deterministas, sin IA externa ni declaraciones de rentabilidad.

Data health incluye data_gaps_total, data_gaps_resolved, data_gaps_unresolved,
recovered_bars y reconnections del conjunto de incidentes compatibles entre sesiones;
los contadores ordinarios de eventos siguen correspondiendo a la sesión actual.
Readiness: BLOCK_DEMO_EXECUTION ante fallo/gap obligatorio **no resuelto**;
NEEDS_REVIEW sin evidencia suficiente.
SIGNAL_PIPELINE_OK exige intents válidos, instrumentos verificados, sesión sin errores
ni gaps pendientes y recibo preflight con tests de paridad aprobados para el mismo code hash.
No autoriza ejecución demo. Sin señales no se certifica un pipeline de intents vacío.

Para comprobar una resolución, abrir el ai_summary.md de la sesión nueva y buscar en
Data health `"data_gaps_unresolved": 0` y el número esperado en `data_gaps_resolved`.
En el detalle del incidente deben aparecer `"resolved": true`,
`"resolution": "REST_CONTINUITY_VERIFIED"` y `"continuity_verified": true`.
El detalle por feed está también en continuity_audits.csv. Un `recovered_bars: 0`
no es error. Readiness puede seguir en NEEDS_REVIEW o bloqueado por otro fallo;
resolver datos no fuerza SIGNAL_PIPELINE_OK ni habilita ejecución.

## Comandos locales

Desde la raíz, con Python del entorno virtual activado:

```powershell
python -m pip install -e ".[dev,forward]"
python scripts/preflight_forward.py --technical-only
python scripts/test_okx_demo_connection.py
python scripts/preflight_forward.py
python scripts/run_forward.py --mode signal-only --config configs/forward/okx_demo.yaml
```

Sin claves, usar `--public-only` en connectivity/preflight. Preflight ejecuta pytest,
Ruff check/format, pip check y, salvo technical-only, consultas de conectividad REST
e instrumentos y valida las 800 velas de warmup por feed (o el count configurado).
Solo ETH 1h/15m bloquean el arranque; el resultado separa required_feeds y
monitoring_warnings y devuelve warmup=REQUIRED_FEEDS_VERIFIED cuando los obligatorios pasan.
El connectivity check rápido solo prueba dos velas y devuelve warmup=NOT_CHECKED.
Para auditar el warmup sin repetir tests:
`python scripts/test_okx_demo_connection.py --public-only --full-warmup`.
No ejecuta batches históricos. Recibos en reports/forward/preflight.
El test privado consulta también fills, sin enviar/cancelar órdenes. `.env.example`
documenta nombres; exportar variables en el shell, no introducir valores reales en Git.
Para invocar sin activar venv, sustituir `python` por `.\.venv\Scripts\python.exe`.

El preflight usa una carpeta temporal exclusiva por ejecución:
`<TEMP>/quant-forward-<id>/pytest`, evitando la carpeta compartida
`Temp/pytest-of-<usuario>` de Windows. No borra ni cambia sus permisos. Los checkouts
temporales quedan fuera del repositorio para que sus pytest anidados no hereden el
pyproject de este laboratorio. Desactiva el cache de pytest en los checks y sus hijos;
Ruff usa un cache exclusivo. Los logs completos quedan en
`reports/forward/preflight/checks/<id>/`, incluso si falla; el mensaje final muestra
la ruta para adjuntarlos. Se conservan los directorios de checks anteriores.
El Python utilizado se imprime al inicio y es el mismo que
invoca el comando (Python global o venv); no cambia automáticamente de intérprete.

Ctrl+C detiene el loop y cierra SQLite generando resúmenes. El checkpoint sobrevive.
`--max-updates 6` permite limitar una sesión manual por número de actualizaciones
confirmadas; puede esperar hasta el siguiente cierre. El agente no deja ningún runner
indefinido en marcha. No existe argumento demo-execution ni live.

## Inventario y verificación

Nuevos: `src/quant_lab/brokers/{base,instruments,okx_demo,signal_only}.py`,
`src/quant_lab/market_data/okx.py`, `src/quant_lab/forward/{config,strategy,engine,store,
runner,preflight}.py`, sus __init__.py, los tres scripts anteriores,
configs/forward/okx_demo.yaml, tests/unit/test_forward.py,
tests/integration/test_forward_runner.py y este protocolo.
Actualizados: .env.example, pyproject.toml (extra forward), README,
docs/ARCHITECTURE.md y docs/PROJECT_STATE.md. .gitignore ya protegía .env y results.
Se conservan los cambios locales anteriores.

Pruebas nuevas: firma/read-only, interfaz, lot/tick/min size, timeframe cerrado,
paridad histórica e incremental, política optional y restauración, paginación/gaps,
WebSocket desconexión/reconexión, transacciones/idempotencia, riesgo y pipeline sin
llamadas a place_order/cancel_order/close_position. Fixtures sintéticos acotados.

Verificación final 2026-09-28: `preflight_forward.py --technical-only` completado,
**529 tests passed** en 136.98 s; Ruff check y format correctos (281 archivos),
pip check sin dependencias rotas. 774 avisos de deprecación Matplotlib proceden
del reporting histórico. Recibo:
`reports/forward/preflight/20260928T143648Z-dee341f2d320.json`.
También se ejecutaron pruebas dirigidas de forward/optional fill y smoke de los
tres CLI con `--help`. No se ejecutaron batches históricos ni sesiones forward
indefinidas. Connectivity pública GET a OKX EU intentada: **HTTP 403** desde este
entorno. No se verificaron instrumentos remotos, WebSocket real ni cuenta privada;
su funcionamiento se cubrió con fixtures/mocks, pendiente de preflight local.

Antes de DEMO_EXECUTION: resolver conectividad desde el equipo del usuario, completar
preflight privado, revisar suficientes sesiones SIGNAL_ONLY, auditar el modelo shadow
y añadir un protocolo separado de órdenes demo con reconciliación, clOrdId idempotente,
fills parciales, rechazos, stop protection y límites de cuenta. Habilitar una variable
no implementa ni autoriza esa fase. No se añade capacidad live.

Corrección de permisos Windows (2026-09-28): el preflight actualizado se verificó
con el Python 3.13 global del usuario. **531 tests passed** en 162.35 s, Ruff
check/format correctos (282 archivos) y pip check sin problemas. Incluye dos tests
adicionales sobre temporales independientes y conservación del log tras un fallo.
Recibo: `reports/forward/preflight/20260928T145835Z-45742c5b49ab.json`.

Corrección HTTP posterior: Cloudflare devolvía 403/1010 para el User-Agent por defecto
de urllib. El cliente ahora se identifica explícitamente como
`QuantTradingLab/0.1 signal-only`, conserva el host EU, cabecera demo y transporte GET.
Check público completo aprobado: hora, ambos instrumentos y velas 15m/1h/4h,
`market_data=REST_OK`, cero mutaciones. No se probaron credenciales privadas ni WS real.
Los recibos técnicos previos tienen otro code hash; repetir preflight tras este cambio.

Auditoría de warmup anterior a la separación de feeds (2026-09-28): de los seis feeds de 800 velas, ETH 4h
contiene un hueco en la apertura 2026-07-02T04:00:00Z. OKX devuelve confirm=0 para
esa vela antigua tanto en history-candles como en candles y en páginas solapadas.
También hay componentes no confirmados en las resoluciones inferiores del intervalo;
no se puede reconstruir una vela completa con esos datos verificados. Los otros cinco
feeds pasaron continuidad en la consulta. El protocolo inicial bloqueaba el runner.
El protocolo ETH V1 actual conserva ese aviso como no bloqueante, porque 4h no es
una entrada de las estrategias habilitadas. No se redujo el warmup ETH 1h/15m,
no se aceptó confirm=0 ni se rellenaron huecos.
El preflight completo detecta y registra la limitación antes del arranque;
DataGap incluye instrumento, timeframe, UTC faltante y confirm=0 cuando corresponde.

Las futuras variantes V2 que consuman 4h no están autorizadas por este contrato.
Requerirán una declaración explícita de dependencias y warmup 4h obligatorio.
No se modificó Python de estrategias, parámetros, riesgo ni OptionalFillPolicy.

Verificación del protocolo separado (2026-09-28): **540 tests passed** en 143.70 s
con Python 3.13 local; Ruff check/format (283 archivos) y pip check correctos.
Ruff emitió un aviso no bloqueante de escritura de cache; ambos checks salieron con 0.
Preflight público completo: REST_OK y REQUIRED_FEEDS_VERIFIED para ETH 15m/1h,
con el hueco ETH 4h explícito en monitoring_warnings. Recibo:
`reports/forward/preflight/20260928T152926Z-dda60ae2efd8.json`.
Las pruebas dirigidas comparan señales, intents y posiciones con/sin huecos auxiliares,
persistencia del estado al perder metadatos BTC, recuperación y aislamiento de errores WS.
WebSocket demo real comprobado hasta primera actualización y cerrado inmediatamente,
sin runner continuo, órdenes ni cuenta privada.


Corrección de recovery (2026-09-28): el bug anterior registraba RECONNECTED sin
actualizar DATA_GAP y readiness bloqueaba por cualquier ocurrencia, incluso recuperada.
Nuevo módulo `forward/recovery.py`, staging durable y resolución del incidente original.
Archivos modificados en esta corrección: forward/runner.py, forward/engine.py,
forward/store.py, market_data/okx.py, tests/integration/test_forward_runner.py,
docs/forward-signal-only.md y docs/PROJECT_STATE.md. Archivos creados:
forward/recovery.py y tests/integration/test_forward_recovery.py.

Pruebas dirigidas: **43 passed** en 33.67 s. Incluyen 14 casos nuevos parametrizados:
caída sin vela perdida, recuperación de una vela y reanudación de señales, REST parcial
con bloqueo, duplicados exactos/conflictivos, reinicio con/sin cambio de código,
incidente antiguo ConnectionError + RECONNECTED, idempotencia, límites de auditoría
15m/1h/4h, desorden, persistencia del staging entre versiones y error independiente
que conserva readiness bloqueado. Se conserva la regresión de paridad de estrategias,
riesgo, política opcional y ausencia de órdenes. Pruebas con fixtures; no se provocó una
desconexión real ni se inició un runner continuo. Los artefactos operativos existentes
no se han marcado resueltos manualmente; su resolución requiere el siguiente arranque
y una auditoría correcta con REST.

Preflight técnico de esta corrección con Python 3.13 local: **554 passed** en
154.66 s; Ruff check/format correctos (285 archivos) y pip check sin dependencias rotas.
Recibo: `reports/forward/preflight/20260928T185408Z-327ead927c70.json`.
Este recibo es technical_only: no certifica una nueva consulta de conectividad pública
ni la recuperación real de la sesión observada. Para comprobar conectividad y warmup:
`python scripts/preflight_forward.py --public-only`.
Después: `python scripts/run_forward.py --mode signal-only --config configs/forward/okx_demo.yaml`.
Si hay un runner anterior abierto, detenerlo con Ctrl+C antes de iniciar la versión nueva.
DEMO_EXECUTION continúa BLOCKED_NOT_IMPLEMENTED; no se inició ningún runner operativo
ni se enviaron órdenes durante esta corrección.


## Cotización temporalmente no disponible (2026-09-29)

El error anterior `Invalid or pre-signal quote` abortaba el proceso con ValueError
sin conservar el detalle temporal ni la señal dentro de la transacción fallida.
Ahora quote realiza como máximo tres consultas GET con pausas de 250 ms. Si el
último ticker parece posterior al reloj estimado, actualiza la hora del servidor
antes de decidir; nunca cambia el timestamp del ticker ni relaja la comparación.
Se mantienen las ventanas de 30 s de antigüedad y 90 s desde el cierre. Se comprueban
tras cada respuesta, incluso si una petición tarda demasiado.

Si sigue sin haber ask válido, QuoteUnavailable conserva motivo, decision_close,
quote_timestamp, checked_at e intentos. El motor guarda QUOTE_UNAVAILABLE, la vela,
la señal si existe y SIGNAL_REJECTED. Las oportunidades opcionales pendientes se
cancelan explícitamente con TIMING_NOT_EXECUTED/quote_unavailable usando finalize
existente: no se inventa un fill ni se arrastra una observación perdida. El proceso
continúa con las próximas velas y persiste checkpoint para no repetir la decisión.
Errores de transporte siguen su manejo de desconexión; otros ValueError no se ocultan.
No cambia la estrategia, sizing, parámetros ni la implementación de OptionalFillPolicy.

quote_events.csv y el contador QUOTE_UNAVAILABLE en Data health permiten revisar
estas omisiones; la sesión queda como máximo NEEDS_REVIEW. No se clasifica un fallo
de ticker como DATA_GAP de velas. No se reescribe la sesión que ya terminó con error.

Verificación: 51 pruebas forward dirigidas aprobadas en 48.34 s, incluidas 12 nuevas
sobre cotizaciones; Ruff check/format de los archivos afectados correctos. No se
ejecutó preflight completo ni runner operativo. Ruff global detectó I001 en
scripts/test_telegram.py (imports), fuera de esta corrección. No se consultó OKX
para reproducir la cotización perdida; el error antiguo no guardaba sus timestamps.

## Contabilidad shadow detallada

El observador [Shadow PnL](forward-shadow-pnl.md) añade posiciones, costes desglosados,
MFE/MAE con límites causales, cierres y comparación de alternativas por signal_id.
Se persiste en checkpoint y no cambia señales, sizing ni la ocupación legacy.
Reconstrucción no destructiva, incluso mientras sigue el runner antiguo:
`python scripts/shadow_pnl.py <SESSION_ID>`. No modifica lab.py ni los experimentos RSI.
