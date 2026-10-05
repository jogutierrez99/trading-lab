# RMM 4h — protocolo operativo OKX DEMO

Implementación 2026-10-04. Prueba operativa de unos siete días, con detención manual.
No cambia estrategia, parámetros ni evidencia histórica; siete días no demuestran
rentabilidad estadística. El protocolo [legacy SIGNAL_ONLY](forward-signal-only.md)
permanece disponible con `configs/forward/okx_demo.yaml`.

## Infraestructura y alternativas

Reutiliza `scripts/run_forward.py`, ForwardEngine, REST/WS, CandleBook, SQLite,
checkpoints, recovery DATA_GAP, ShadowTracker, informes, `shadow_pnl.py` y watcher.
`forward/rmm.py` es una política del motor existente que llama a la estrategia
original. DemoCoordinator es un adaptador de ejecución separado de las señales.

| Prioridad | Nombre | Modo | Etiqueta |
|---|---|---|---|
| A / 1 | rmm_eth_long_short_4h | LONG_SHORT | MAIN |
| B / 2 | rmm_eth_long_only_4h | LONG_ONLY | MAIN |
| C / 3 | rmm_btc_long_short_4h | LONG_SHORT | MAIN |
| D | rmm_btc_long_only_4h_shadow | LONG_ONLY | SHADOW_CANDIDATE |

Cuatro ledgers virtuales independientes, capital inicial10,000 cada uno, señales,
posiciones y PnL separados. No se suma exposición. Una cuenta demo compartida ejecuta
solo `demo_strategy`, inicialmente A; B/C son alternativas MAIN elegibles, D nunca
envía órdenes. Cambiar selección requiere cuenta demo sin posiciones/órdenes ajenas,
nueva configuración y nueva fase SIGNAL_ONLY/verificación. No hay subcuentas ficticias.

## Parámetros y causalidad

Congelados: EMA200, momentum180, volatilidad180, target10%. Warmup **1000 velas4h**
porque la clase original exige cinco periodos EMA. No se añade stop, target,
trailing ni timeout. Momentum=`close[T]/close[T-180]-1`, filtro EMA original y
salida por momentum contra la posición. LONG_ONLY nunca entra SHORT. Se cierra
primero y la nueva entrada opuesta exige otra decisión4h, sin reversal en el mismo open.

UTC; timestamp=apertura, cierre=apertura+4h. Solo `confirm=1` y cierre<=reloj OKX.
Histórico4h nativo preferido; si falla continuidad, agregación causal de cuatro
velas1h confirmadas completas. Sin interpolación. Si se usa fallback, WS1h se
convierte en dependencia obligatoria y solo emite4h al cerrar las cuatro horas.
Con fuente nativa WS4h es obligatorio,1h/15m auxiliares.
Retraso>90s exige recuperación, sin entradas retrospectivas. Referencia=midpoint
bid/ask válido posterior al cierre, antigüedad<=30s, ventana de decisión<=90s.
Market demo tras cierre confirmado difiere del fill OHLCV siguiente open del backtest:
precio ejecutable y latencia se registran, no se afirma paridad de fills.

## Sizing y costes

`RV = std(simple_returns,180,ddof=1)*sqrt(2190)`.
`fraction = clip((10/100)/RV,5/100,25/100)`. RV inválida/cero no genera entrada.
Se usa el mismo `size_entry`, con fracción al entrar, sin rebalanceo ni leverage extra.
Shadow BASE: fee0.05%, slippage0.03%, spread completo0.01% (medio por fill).
Cantidad redondeada abajo a `lotSz*ctVal`; mínimo `minSz*ctVal`; contratos=base/ctVal.
Lab usa step1e-6/min notional10, OKX filtros actuales/minSz: adaptación documentada.
TickSz se registra; market no fija ni redondea precio limit. No se aumenta tamaño
para superar mínimos. Demo usa ledger separado y fees observadas, nunca fees BASE
para atribuir PnL real; net/equity se etiquetan **excluding_funding**.

## Instrumentos

Discovery público verificado por API EEA demo durante implementación:

| ID | Tipo | Liquidación | ctVal | lotSz | minSz | tickSz |
|---|---|---|---|---|---|---|
| ETH-USD_UM_XPERP-310328 | FUTURES/xperp/linear | USD |0.001 ETH|1|1|0.01|
| BTC-USD_UM_XPERP-310328 | FUTURES/xperp/linear | USD |1 BTC|0.0001|0.0001|0.1|

Nuevo YAML utiliza AUTO, no IDs fijos. Discovery admite metadata lineal actual,
ctMult1 y vencimiento>8 días, selecciona determinísticamente el mayor vencimiento.
SWAP no está soportado por el adaptador EEA actual: se usa X-Perp compatible.
Acceso privado aún debe validarse en la cuenta demo. USD/USDC no se convierten a USDT
ficticiamente; capital numérico10,000 denominado en liquidación observada. Esto limita
la comparación con Binance USD-M USDT.

## Seguridad y activación

YAML `environment=demo`, `mode=signal_only`, `trading_enabled=false`,
`allow_live_trading=false`. Únicamente CLI `--mode demo-execution` con recibo válido
arma la capacidad demo. Legacy sigue SIGNAL_ONLY. LIVE no está disponible.
Claves dedicadas exportadas en terminal: `OKX_DEMO_API_KEY`, `OKX_DEMO_API_SECRET`,
`OKX_DEMO_API_PASSPHRASE`; no reutiliza `OKX_API_*` ni carga claves OKX de `.env`.
Watcher carga solo sus variables Telegram de `.env`.

EEA **comparte REST `https://eea.okx.com`** entre producción/demo. La separación
exige `x-simulated-trading:1` y claves demo; no dos hosts REST diferentes.
WS `wss://wseeapap.okx.com:8443/ws/v5/business`; host fijo, sin redirecciones.
Allowlist: GET lectura y único POST market isolated/net, reduceOnly al salir,
expTime corto. No leverage mutation, retiros, live ni cancelación automática.
Configurar manualmente net_mode/isolated1x, comprobados mediante GET antes de operar.
No exportar TRADING_ENABLED=true: el guard global permanece false; solo el contexto
runtime armado mediante CLI/recibo cambia trading_enabled para órdenes demo.
[Documentación oficial OKX EEA](https://my.okx.com/docs-v5/en/).

Gate: validate → SIGNAL_ONLY>=4h → detener → verify → demo-execution.
Verify exige metadata igual al journal, mismo código/config/instrumentos, nuevas
evaluaciones confirmadas de ambos activos, heartbeat, una intención ENTRY válida de
la MAIN seleccionada que compruebe cotización/sizing, y ninguna incidencia
DATA_GAP/ERROR/QUOTE_UNAVAILABLE/recovery review. `--telegram-verified` es confirmación
humana de recepción real, no una prueba automática. El recibo se verifica al arrancar.

## Gaps y reinicios

Gap pausa nuevas decisiones, resync reconstruye histórico y audita continuidad antes
de reanudar. No ejecuta señales perdidas. Si existe posición y se perdió una frontera
de decisión, demo se detiene para revisión; no inventa salida ni PnL. Estado con gap
se etiqueta como observación incompleta.
IDs independientes incluyen alternativa/versión/instrumento/cierre/acción.
clOrdId alfanumérico<=32 deriva de stream+intent. SQLite FULL/WAL confirma SUBMITTING
antes de POST. Timeout nunca reenvía POST; consulta clOrdId al reiniciar y bloquea
si resultado desconocido. Fills únicos por ordId/tradeId se persisten antes de aplicar
posición. Pendientes/parciales bloquean nuevas submissions y se concilian en heartbeat.
Rechazo/cancelación, fee currency desconocida o cuenta divergente requieren revisión.
Posiciones/órdenes ajenas bloquean cuenta; no borrar SQLite para solucionar incidentes.
Cambio de código/config/instrumentos cambia stream, sin migración automática.
SIGNAL_ONLY y DEMO_EXECUTION tienen streams distintos: fase2 comienza con ledgers
shadow nuevos y no envía las intenciones antiguas de fase1.
Ctrl+C guarda/cierra runner, **no liquida posiciones demo**.

## Informes y Telegram

Shadow: posiciones/trades/summary, reconstrucción read-only de eventos RMM sin stops.
Demo: orders/fills/trades/PnL/expected_vs_observed CSV y Markdown. Se conservan expected
entry/quantity/side, signal/submission timestamps, fill, fees/currency, contracts,
reject code/status, latency, slippage, desviación sizing y estado tras fill.
Funding desconocido no se asume cero. Fee de moneda no equivalente impide net fiable
y nuevo sizing. MFE/MAE demo omite vela parcial de entrada: cotas de barras completas.
DD realizado no es drawdown intrabar; mark PnL/saldo privado está en broker snapshots.
Por sesión: session.json, summary.md, ai_summary.md, métricas operativas y CSVs existentes.
Todo en `results/forward/rmm_4h/`, sin publicar en research_results.
Watcher read-only admite ambos modos demo. Señales/intents shadow se separan de alertas
DEMO ORDER SUBMITTED/FILLED/REJECTED/POSITION CLOSED, DATA_GAP/ERROR/RECONNECTED.
Fallo Telegram no detiene el runner. No se enviaron mensajes ni órdenes en implementación.

## Comandos locales

Desde `C:\Users\joshu\OneDrive\Escritorio\WEBS\Back_testing\trading-lab`, con
Python del proyecto activo y dependencias `.[dev,forward]` instaladas. Claves demo
en variables de entorno del runner, Telegram en `.env`. No incluir secretos en informes.

### 1. Verificar configuración

```powershell
python scripts/verify_forward_rmm.py validate
```

### 2. Probar conexión OKX DEMO

```powershell
python scripts/verify_forward_rmm.py connect
python scripts/verify_forward_rmm.py account
```

Connect público; account verifica autenticación demo/net/isolated1x/acceso mediante GET.

### 3. Verificar instrumentos

```powershell
python scripts/verify_forward_rmm.py instruments
```

### 4. Ejecutar tests relevantes

Antes de iniciar la observación, comprobar el warmup real de ambos activos:

```powershell
python scripts/verify_forward_rmm.py warmup
```

Consulta únicamente datos públicos demo, sin crear sesiones ni recibos. Sale con
código1 si alguna fuente requerida no está lista. `account` verifica la cuenta,
pero no certifica la disponibilidad del historial. Comprobación pública 2026-10-05:
ETH ofrece902 velas4h confirmadas y3611 velas1h desde mayo, insuficientes para
1000 velas4h (fallback pide4004 horas). El endpoint alternativo de velas tampoco
ofrece el tramo anterior. Esta prueba operativa está bloqueada por datos;
BTC sí supera la comprobación con1000 velas4h continuas, pero ambos activos son
obligatorios para esta prueba conjunta.
no reducir warmup, mezclar Binance/spot/live ni borrar el journal para arrancar.
Repetir `warmup` para comprobar disponibilidad futura, sin asumir una fecha de solución.

```powershell
python -m pytest tests/unit/test_forward_rmm.py tests/unit/test_forward.py tests/unit/test_forward_shadow.py tests/integration/test_forward_runner.py tests/integration/test_forward_recovery.py tests/integration/test_forward_quotes.py tests/integration/test_notification_watcher.py -q
```

Si los tests muestran `PermissionError: [WinError 5]` sobre AppData/Local/Temp o
`.pytest_cache`, repetir desde CMD con el Python del proyecto, sin cacheprovider,
y una base temporal nueva por ejecución directamente bajo TEMP:

```bat
.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/unit/test_forward_rmm.py tests/unit/test_forward.py tests/unit/test_forward_shadow.py tests/integration/test_forward_runner.py tests/integration/test_forward_recovery.py tests/integration/test_forward_quotes.py tests/integration/test_notification_watcher.py -q --basetemp="%TEMP%\trading-lab-tests-%RANDOM%-%RANDOM%"
```

`%TEMP%` y `%RANDOM%` son sintaxis CMD. La carpeta nueva la crea la cuenta que ejecuta
el comando, sin reutilizar `.pytest_cache` ni `pytest-of-joshu`. Carpetas creadas
por CodexSandboxOffline con ACL protegida pueden no admitir acceso desde la cuenta
normal; comprobado por lectura de ACL, sin cambiar permisos ni propietarios.
Pytest vacía su basetemp si ya existe: usar siempre una ruta nueva y exclusiva de tests,
sin apuntar a sesiones, resultados ni datos. No requiere cambiar permisos de AppData.

### 5. Arrancar notification watcher

Otra terminal:

```powershell
python scripts/notification_watcher.py --db results/forward/rmm_4h/forward.sqlite --startup-message
```

`python scripts/notification_watcher.py --startup-message` sigue correcto para la
base anterior; RMM necesita --db. Puede arrancarse antes y esperar a que exista base.

### 6. Iniciar SIGNAL_ONLY

```powershell
python scripts/run_forward.py --config configs/forward/okx_demo_rmm_4h.yaml --mode signal-only
```

### 7. Comprobar sesión SIGNAL_ONLY

Otra terminal PowerShell:

```powershell
$rmmSession = (Get-ChildItem results/forward/rmm_4h -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'session.json') } | Sort-Object Name -Descending | Select-Object -First 1).FullName
$rmmSession
python scripts/shadow_pnl.py "$rmmSession"
Get-Content (Join-Path $rmmSession 'ai_summary.md')
Get-Content (Join-Path $rmmSession 'summary.md')
```

### 8. Detener SIGNAL_ONLY

Ctrl+C después>=4h, nuevas evaluaciones de ambos activos y una intención ENTRY de
la MAIN seleccionada. Si no hay señal elegible, prolongar la observación. session.json debe indicar
stopped. Conservar esta ruta para verify; no sustituirla por la nueva sesión demo.

### 9. Iniciar OKX DEMO PAPER

Después de revisar informes y recibir Telegram, misma terminal verify/demo:

```powershell
python scripts/verify_forward_rmm.py verify --session "$rmmSession" --telegram-verified
python scripts/run_forward.py --config configs/forward/okx_demo_rmm_4h.yaml --mode demo-execution --verification reports/forward/rmm_verification.json
```

Si verify falla, resolver incidencia y repetir una fase limpia. No omitir gate.

### 10. Monitoring

Watcher continúa; si se detuvo repetir paso5 en otra terminal.

```powershell
$rmmDemoSession = (Get-ChildItem results/forward/rmm_4h -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'session.json') } | Sort-Object Name -Descending | Select-Object -First 1).FullName
python scripts/shadow_pnl.py "$rmmDemoSession"
Get-Content (Join-Path $rmmDemoSession 'demo_pnl.md')
Get-Content (Join-Path $rmmDemoSession 'errors.log')
Get-Content (Join-Path $rmmDemoSession 'ai_summary.md')
Import-Csv (Join-Path $rmmDemoSession 'demo_orders.csv')
Import-Csv (Join-Path $rmmDemoSession 'demo_fills.csv')
```

### 11. Reinicio seguro

Ctrl+C, conservar base/config/recibo/claves y repetir:

```powershell
python scripts/run_forward.py --config configs/forward/okx_demo_rmm_4h.yaml --mode demo-execution --verification reports/forward/rmm_verification.json
```

Se crea sesión nueva del mismo stream y concilia antes de enviar. Incidentes requieren
revisión de journal/cuenta, no borrar datos ni reenviar órdenes. Sin apagado automático.

## Qué enviar tras una semana

De sesiones relevantes: ai_summary.md, summary.md, session.json, signals.csv,
order_intents.csv, shadow_positions.csv, shadow_trades.csv, shadow_pnl_summary.md,
rmm_shadow_metrics.csv,
demo_orders.csv, demo_fills.csv, demo_trades.csv, demo_expected_vs_observed.csv,
demo_pnl.md. Añadir salida reconstruida de shadow_pnl.py y provenance.json.
Si hubo incidentes: errors.log, data_gaps.csv, continuity_audits.csv,
recovery_events.csv, monitoring bars/warnings. No enviar .env, claves ni toda carpeta.

## Alcance de verificación

Evidencia: `python -m pytest -q` **953 passed**; regresión forward **138 passed**;
RMM específico final **14 passed**. `python -m ruff check .` y
`python -m ruff format --check .` pasan; `git diff --check` sin errores.
774 warnings de deprecación pandas/Matplotlib en reporting Batch006, sin fallos.
Validación YAML, consulta pública de hora e instrumentos pasan. CLI --help verificado
para runner, verifier, watcher y shadow_pnl; previsualización watcher sin base retorna
aviso esperado y no envía mensajes. Telegram probado con fakes/formatter/guard demo.

Tests sintéticos/fakes y consulta pública de instrumentos. Cuenta privada,
WS prolongado, Telegram real y órdenes demo se verifican localmente durante las dos
fases. No se ejecutaron batches históricos ni el bot de siete días.
