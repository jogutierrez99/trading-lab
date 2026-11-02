# ETH Donchian + ATR SHORT 1h: observación aislada

Implementación2026-10-08, HEAD de partida
`fbcbed2a33210ffbcf99ef01e3de5ed5873f2a5b`, checkout inicialmente limpio y HEAD igual
al tracking local origin/main. No fetch ni certificación del estado remoto actual.
El último commit contiene la revisión y el preregistro; no contenía código Donchian
forward. Se conservan sus archivos/hash/criterios, incluidas las conclusiones históricas
que documentaban la arquitectura pendiente en ese momento.

## Diagnóstico y aislamiento

| Componente | Implementación | Impacto RMM |
|---|---|---|
| Estrategia | Clase Donchian1.0.0 existente, seis parámetros de publicación congelada | Ninguno |
| Runner | `run_donchian_forward.py`, polling público independiente | Runner RMM intacto |
| Datos | OKXDemoBroker GET público, OKXMarketData/history, parse_bar/CandleBook existentes | Sin edición compartida |
| PnL | Engine propio; size_entry/CostModel/protective_fill existentes | Sin edición financiera compartida |
| SQLite/locks | Subclase Store; WAL/FULL y lock existentes en raíz propia | Journals/locks distintos |
| Alertas | Watcher fuera del forward; transporte/cursor/helpers reutilizados | Watcher/secretos RMM intactos |
| Configuración RMM | Ningún cambio | No requiere reinicio |

Todos los Python/YAML añadidos son DONCHIAN_ONLY. README, ARCHITECTURE y PROJECT_STATE
son documentación SHARED_BACKWARD_COMPATIBLE, sin efectos en procesos. No hay archivos
SHARED_RESTART_REQUIRED ni POTENTIALLY_BREAKING modificados. El paquete no se reinstaló,
no se arrancó un runner real ni se detuvieron procesos. El sondeo CIM no identificó
una instancia coincidente; esto **no demuestra** que RMM esté detenido. Se trata la
sesión del usuario como activa; su estado efectivo no está certificado.

RMM puede continuar por aislamiento de rutas y locks probado con procesos temporales.
**Reinicio RMM: NO NECESARIO para esta integración.** No hay actualización automática
del Python ya cargado. Nunca usar su sesión real como fixture ni lanzar otra instancia
RMM. Su procedimiento operativo existente permanece en forward-rmm-btc-4h.md.

## Configuración y modelo económico

YAML propio `configs/forward/okx_demo_eth_donchian_short_1h.yaml`, no compatible con
ForwardConfig legacy: signal_only, trading_enabled/send_orders/allow_live_trading=false.
Rechaza LIVE/DEMO con órdenes, LONG, BTC, riesgo/parámetros/costes nuevos, variantes
omitidas y output compartido/alias. CLI solo acepta `--mode signal-only`.

Se deriva el listado resuelto de seis variantes del sources.json publicado y
verificado por hashes del preregistro, no del texto del prompt.00/01/02: canal30/40/50,
expansión1.10;03/04/05: canal30/40/50, expansión1.25. EMA200/slope5, ATR14/referencia50,
stop2ATR, RR2, exit risk, versión1.0.0. Doce cuentas virtuales independientes10000:
seis candidatos × BASE/ADVERSE. Sin selección, capital conjunto ni reset diario.

Solo velas confirmadas1h, UTC, OHLCV válido y continuo; al menos1000 de warmup.
Todo el contexto confirmado se mantiene para conservar la semilla causal EMA.
Las velas abiertas nunca llegan a señales/protecciones. Solo su OPEN se captura como
referencia cuando hay volumen positivo y se observa dentro de90s del límite horario.
Se registra la latencia: entrada nominal en next-open es un modelo hipotético, no
una operación ejecutada. Confirmación tardía/apertura perdida => MISSED_ENTRY,
sin sustitución por ticker, mark, index ni backfill. Señales duplicadas no reentran.

SL=entrada modelada+2ATR causal; TP=entrada-2*(SL-entrada). Cost-aware size_entry:
riesgo1% del equity de entrada, posición25% con fee de entrada, exposición100%.
BASE fee/slippage/fullspread0.05/0.03/0.01%; ADVERSE0.10/0.06/0.02%. Medio spread por
fill; SHORT entra con precio desfavorable menor y sale con mayor. Fees en ambos lados.
Nominal no representa leverage ni margen real. Las cuentas pueden divergir por costes.

Se adapta exclusivamente el lattice de cantidad al ctVal*lotSz observado (debe ser
múltiplo del step lab1e-6); mínimo max(lab mínimo,ctVal*minSz), notional mínimo lab10.
No se inventa un mínimo de nominal exchange no publicado. TickSz se registra: niveles
protectores hipotéticos no son órdenes limit redondeadas. Esta adaptación explícita
puede cambiar cantidades respecto del histórico; no se presenta paridad absoluta
entre venues. Riesgo, señales y porcentajes congelados permanecen iguales.

Al cerrar cada vela: gap stop a OPEN; target gap al target; stop primero si SL/TP
coinciden intrabar. Exit intrabar time=null; se conserva exit_bar_open. PnL de precios
bruto, PnL de fills, fees/slippage/spread/neto separados. Equity usa marcado de cierre;
PnL neto no realizado es estimación de salida con costes. DD>15% pausa nuevas entradas
sin reset de capital ni liquidación artificial; posiciones existentes siguen observadas.

## Puente de instrumento y preflight

Discovery público de FUTURES/xperp/linear/live ETH, ctValCcy=ETH, ctMult=1,
settlement USD o USDC, metadata positiva y vencimiento>180 días; AUTO selecciona
el mayor vencimiento determinísticamente. Se guardan instrumento exacto, tipo,
vencimiento, multiplicador, divisas, tick/lot/minSize. No rollover silencioso.
`quoteCcy` aplica a SPOT/MARGIN en la API OKX y puede estar vacío en FUTURES:
se conserva literalmente; la moneda de settlement se valida mediante `settleCcy`.
El discovery público comprobó ETH-USD_UM_XPERP-310328 con `quoteCcy=""` y
`settleCcy="USD"`. Se corrigió el filtro Donchian que descartaba esa metadata válida,
sin modificar el parser compartido ni los requisitos de contrato, riesgo o warmup.
Estos X-Perps pueden tener vencimiento: no llamarlos perpetuos indefinidos.

Feed de precios de trades del contrato OKX EEA demo, no Binance USD-M USDT. La
[documentación oficial](https://app.okx.com/docs-v5/en) define timestamp como apertura,
confirm0/1 como vela abierta/cerrada y volCcy como cantidad base en derivados.
El cambio de venue/divisa/basis se registra y limita comparaciones. Sin conversión
USD/USDC a USDT implícita; capital virtual denominado en settlement observado.
Sin funding, liquidaciones ni simulación fiel de margen/apalancamiento.

**Arranque gated: requiere un recibo preflight público vigente generado localmente.**
La entrega inicial quedó SIGNAL_ONLY_BLOCKED hasta aceptar el feed. La comprobación
pública posterior, tras corregir `quoteCcy`, aceptó ETH-USD_UM_XPERP-310328 y1000
velas1h confirmadas, continuas y actuales (último cierre2026-10-08T21:00Z).
Se ejecutó en memoria sin crear recibo ni sesión; no sustituye el preflight del usuario.
Los tests siguen offline y no contactan el broker.
`preflight` hace solo GET público y guarda un recibo único en reports/forward;
`run` exige ese recibo vigente<=30min, mismo YAML, código/dependencias y metadata,
y vuelve a validar el warmup antes de crear cuentas. Rechazo conserva el bloqueo.
Un preflight correcto más la QA offline permite la observación técnica; nunca aprueba
una ventaja estadística, paper o envío de órdenes. El broker acotado rechaza cualquier
endpoint privado y no dispone de método de envío; no requiere claves OKX privadas.

## Persistencia, recuperación y protocolo

Raíz exclusiva results/forward/eth_donchian_short_1h/: forward.sqlite, .runner.lock,
carpetas de sesiones, errores, checkpoints e identidades por stream/candidato/coste.
Eventos financieros y checkpoint se confirman en una misma transacción WAL/FULL.
Corrupción o cuentas faltantes se rechazan, nunca se recapitalizan automáticamente.

Ctrl+C preserva operaciones abiertas; no las liquida. `--resume SESSION_ID` recupera
el mismo stream de cuentas mediante **un nuevo segmento de proceso enlazado**;
no sobrescribe la sesión original ni reinicia su equity/fecha efectiva. Código,
dependencias, YAML o instrumento incompatibles bloquean restauración: no migrar
posiciones ni borrar el journal para eludirlo. Sin --resume se rechaza capital ya
persistido. El lock OS impide dos writers Donchian, incluso entre procesos.

DATA_GAP desconecta entradas, invalida pendientes y conserva posiciones. Recovery
debe cubrir exactamente checkpoint→última hora confirmada sin huecos/revisiones.
REST puede reconstruir un fill hipotético justificado por OHLC confirmado, con
coverage=REST_RECONSTRUCTED/evidence_eligible=false y tiempo intrabar desconocido.
No se reevalúan entradas antiguas. Hasta continuidad comprobada, no se reanuda.
review_required permanece registrado: esos intervalos no prueban evidencia limpia.
Reinicio sin horas faltantes conserva la cobertura original. Retries con backoff
2..60s; fallo crítico registra ERROR y detiene conservando el último checkpoint.

Fecha nominal2026-10-09T00Z y primer cierre efectivo tras inicio aceptado se registran
por separado. Warmup no ejecuta señales. Se mantienen criterios originales180 días,
100 operaciones únicas por candidato/coste,4/6 variantes,4/7 vecinos, DD15%, bootstrap
7 días/10000 réplicas/seed y multiplicidad. No se ejecutó análisis estadístico ni se
convirtió un reinicio/gap en periodo independiente. Readiness técnica y ventaja
económica siguen separadas.

## Telegram y consultas

`donchian_notification_watcher.py` es opcional, separado del runner y del watcher RMM.
Reutiliza transporte sanitizado/retries Telegram, lector SQLite read-only y helpers
de cursor/lock atómico. Propios donchian_telegram_state.json y donchian_telegram.lock.
No modifica secretos: lee solo cuatro variables Telegram existentes al arrancar;
la carga no ocurre al importar. Primer arranque from-now; dry-run imprime sin HTTP
ni cursor. Señales e intents individuales persisten; alertas agrupadas evitan seis
mensajes por el mismo cierre y mantienen las doce contabilidades. Entradas, salidas,
gaps/resumes, DD, parada/recovery llevan siempre:
SIGNAL_ONLY — HYPOTHETICAL — NO EXCHANGE ORDER.
Como el watcher RMM, omite HEARTBEAT en Telegram y avanza su cursor sin enviarlo.
Los heartbeats siguen guardándose en el journal local. Para aplicar un cambio del
watcher, detener solo ese proceso con Ctrl+C y volver a ejecutar
`scripts/donchian_notification_watcher.py`; no reiniciar el runner ni RMM.

Una entrega interrumpida se marca unknown y no se reenvía automáticamente; no promete
exactly-once en Telegram. El watcher conserva cursor y se niega ante truncado/reemplazo.
`status` consulta un snapshot de lectura del stream y últimos25 eventos; sesión enlazada
no significa solo los trades del último proceso. No utilizar shadow_pnl.py legacy para
este schema: el comando Donchian status muestra shadow, equity, costes y gaps propios.

## Comandos Windows / PowerShell

No detener ni reiniciar RMM para estos pasos. Revisar procesos es solo lectura:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*run_forward.py*' } | Select-Object ProcessId,Name,CreationDate
.venv\Scripts\python.exe scripts/run_donchian_forward.py validate
.venv\Scripts\python.exe -m pytest tests/unit/test_donchian_forward.py tests/unit/test_forward_rmm.py tests/unit/test_forward_shadow.py tests/integration/test_forward_runner.py tests/integration/test_forward_recovery.py -q
# En una terminal nueva Donchian; no cambia el entorno del RMM ya activo
$env:TRADING_ENABLED = 'false'
$env:ALLOW_LIVE_TRADING = 'false'
$env:ENVIRONMENT = 'demo'
$env:OKX_DEMO = 'true'
.venv\Scripts\python.exe scripts/run_donchian_forward.py preflight
$receipt = Get-ChildItem reports/forward/donchian_preflight/*.json | Sort-Object LastWriteTimeUtc | Select-Object -Last 1
.venv\Scripts\python.exe scripts/run_donchian_forward.py run --mode signal-only --preflight $receipt.FullName
```

El runner imprime session_id y carpeta exacta. Otra terminal puede observar ambos
procesos y leer el journal propio. Mantener el watcher RMM existente; no duplicarlo.

```powershell
$sessionId = Read-Host 'session_id Donchian impreso por el runner'
.venv\Scripts\python.exe scripts/run_donchian_forward.py sessions
.venv\Scripts\python.exe scripts/run_donchian_forward.py status --session $sessionId
.venv\Scripts\python.exe scripts/donchian_notification_watcher.py --dry-run --once
# Opcional: iniciar el watcher Donchian real, sin cambiar el de RMM
.venv\Scripts\python.exe scripts/donchian_notification_watcher.py
```

Parada: Ctrl+C en la terminal **Donchian**; el watcher propio puede detenerse con
Ctrl+C por separado. Esperar al fin del proceso y comprobar status. No taskkill /F.
Reanudación, mismo stream/capital, nuevo segmento enlazado:

```powershell
.venv\Scripts\python.exe scripts/run_donchian_forward.py preflight
$receipt = Get-ChildItem reports/forward/donchian_preflight/*.json | Sort-Object LastWriteTimeUtc | Select-Object -Last 1
.venv\Scripts\python.exe scripts/run_donchian_forward.py run --preflight $receipt.FullName --resume $sessionId
```

Si el lock sigue ocupado, no borrar el lock/journal: identificar la instancia.
Si código/config/metadata cambiaron, preservar posición y resolver la incompatibilidad;
no crear otra cuenta con10000 y llamarla continuación. No hay un procedimiento de
reinicio RMM necesario como parte de esta integración.

## QA

Tests offline: seis variantes, SHORT y flags estrictos, costes/sizing/protecciones,
duplicados, aperturas perdidas, DD, restart/restauración/corrupción, llamadas de red
falsas sin órdenes, metadata/recibos y proceso RMM temporal concurrente. Regresión
existente de señales/causalidad/RMM/shadow/recovery/Telegram; ningún módulo compartido
financiero cambia frente a HEAD. Aceptación pública, sesión prolongada y entrega real
Telegram quedan para ejecución local. No tests con la sesión activa del usuario.
