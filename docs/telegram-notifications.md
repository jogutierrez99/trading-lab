# Telegram notifications

Observador independiente del forward actual OKX DEMO / SIGNAL_ONLY. Lee el journal
existente; no importa ForwardEngine, Runner, Store ni brokers, no cambia señales/riesgo
y no ejecuta operaciones. El runner puede seguir en su terminal mientras este proceso
arranca, se detiene o pierde conexión con Telegram. No requiere reiniciar el forward.

## Preparación y ejecución en Windows

Usar el entorno Python del proyecto con su instalación editable existente. No añade
dependencias: el cliente HTTP usa urllib de la biblioteca estándar. Crear el bot y
obtener su chat ID por los procedimientos de Telegram; iniciar conversación con el bot
o añadirlo al chat destino con permiso para publicar.

Configurar las variables en el **`.env` de la raíz del proyecto** con los valores propios:

```dotenv
TELEGRAM_BOT_TOKEN=<token del bot>
TELEGRAM_CHAT_ID=<chat id>
TELEGRAM_NOTIFICATIONS_ENABLED=true
TELEGRAM_POLL_SECONDS=2
```

También pueden exportarse en la terminal; las variables exportadas tienen prioridad
sobre `.env`, incluso si están vacías. Después ejecutar:

```powershell
python scripts/notification_watcher.py
```

Los valores anteriores son placeholders. No introducir credenciales en scripts ni
Git. `.env.example` contiene nombres vacíos; `.env` y `.env.*` están ignorados. El
watcher carga automáticamente solo las cuatro variables Telegram, al arrancar y nunca
al importar. Acepta UTF-8 (con o sin BOM), valores de una línea, comillas, comentarios
y prefijo `export`. No ejecuta comandos ni expande `${VARIABLES}`. No carga claves OKX
ni modifica variables de trading. El forward conserva su comportamiento anterior.
Los cambios de `.env` requieren reiniciar solo el watcher. Sin activar
`TELEGRAM_NOTIFICATIONS_ENABLED=true`, termina sin enviar ni consumir eventos. Si se
activa sin credenciales válidas, termina con un error de configuración sin mostrarlas.

Previsualización sin credenciales, HTTP, locks del watcher ni escrituras de estado:

```powershell
python scripts/notification_watcher.py --dry-run --replay-last 3 --once
```

Sin activar el venv, sustituir `python` por `.\.venv\Scripts\python.exe`. Desde otro
directorio, invocar el script por su ruta absoluta. El DB predeterminado y los paths
relativos de `--db` se resuelven contra la raíz del proyecto, no contra el cwd.

| Opción | Comportamiento |
|---|---|
| `--db PATH` | Predeterminado `results/forward/forward.sqlite` |
| `--state-dir PATH` | Guarda el estado fuera del directorio del journal; copia un estado previo validado si el destino no existe |
| `--poll-seconds 2` | Sobrescribe el entorno; intervalo finito de 0.1 a 3600 segundos |
| `--once` | Procesa hasta el máximo rowid observado al inicio de la lectura y termina |
| `--dry-run` | Imprime, usa cursor solo en memoria e ignora el estado real |
| `--replay-last N` | Últimas N **filas del journal**, incluidos eventos ignorados; máximo 10000 |
| `--include-rejected` | Añade SIGNAL_REJECTED, desactivado por defecto |
| `--startup-message` | Un aviso de arranque por proceso, tras la primera lectura correcta |

Sin replay y sin estado previo, guarda MAX(rowid) y notifica únicamente filas nuevas.
Un reinicio retoma el cursor guardado, incluyendo los eventos acumulados mientras el
watcher estaba apagado. Replay real solo se permite si no existe estado; con estado,
usar dry-run para inspeccionar sin reenviar alertas. No borrar estado para un reinicio
normal. Ctrl+C cierra lecturas y libera su lock; cada resultado ya tiene estado durable.

## Journal y semántica

SQLite se abre con URI `mode=ro`, `uri=True` y `PRAGMA query_only=ON`. No hay migraciones
ni cambios de journal mode. Consulta incremental `events.rowid > cursor`, ordenada y
limitada a 200 filas, con lecturas por clave de `sessions`. La transacción de lectura
termina **antes** del HTTP/backoff: no retiene snapshots WAL durante los envíos. No se
borra, mueve ni modifica manualmente ningún DB/WAL/SHM ni se abre `.runner.lock`.

Las filas de sesiones/streams nuevos continúan en el mismo cursor global. Antes de
formatear como SIGNAL_ONLY se verifica la configuración persistida de la sesión:
OKX, demo, signal_only y ambos flags de trading false. Una sesión desconocida o
incompatible queda como `unsupported_session` y no se anuncia con semántica falsa.

Eventos soportados: SIGNAL_GENERATED, ORDER_INTENT_CREATED, TIMING_WINDOW_STARTED,
TIMING_FILL_SELECTED, TIMING_FALLBACK, TIMING_NOT_EXECUTED, DATA_GAP,
**DATA_GAP_RESOLVED**, **DATA_GAP_RECOVERY_FAILED**, RECONNECTED, MONITORING_WARNING,
ERROR y, opcionalmente, SIGNAL_REJECTED. Los nombres de recovery son los del código
actual; no emite DATA_GAP_DETECTED/DATA_GAP_RECOVERED ficticios. HEARTBEAT,
ORDER_SKIPPED_SIGNAL_ONLY y eventos no seleccionados solo avanzan el cursor.

La resolución modifica el DATA_GAP original y añade DATA_GAP_RESOLVED; el watcher
notifica esa nueva fila. No vuelve a escanear mutaciones de filas antiguas. Los intents
y selecciones 15m se presentan explícitamente como hipotéticos, sin órdenes ni fills
del exchange. Solo se muestran campos permitidos, con longitud limitada, fechas UTC
cuando existen y sin dumps. Se ocultan URLs, asignaciones de credenciales, patrones de
token y secretos presentes en el entorno; no es un escáner universal de secretos
arbitrarios introducidos manualmente en texto libre.

## Persistencia, fallos y duplicación

Estado separado: `results/forward/forward_telegram_watcher_state.json`; lock propio:
`forward_telegram_watcher.lock`. Para otro DB se utiliza su stem. El lock de sistema
operativo evita dos watchers reales simultáneos sobre esa ruta y se libera al salir
incluso si el proceso muere. Su archivo puede permanecer; no es un lock del runner.
El estado se escribe a temporal en el mismo directorio, flush/fsync y replace atómico.
Contiene path, cursor, identidad stream/evento del cursor, envío pendiente y hasta
100 fallos recientes (rowid, estado e intentos). No guarda token, chat ID ni mensajes.

En Windows, `PermissionError` con winerror5/32/33 durante replace reintenta cinco
veces con esperas0.2/0.4/0.8/1.6s. Si persiste, conserva el estado anterior y termina
sin enviar un evento cuyo pending no pudo persistirse. Los permisos, antivirus o
sincronización pueden bloquear la sustitución; no inferir una causa específica solo
del código5. En OneDrive, usar desde CMD un directorio de estado local:

```bat
.venv\Scripts\python.exe scripts/notification_watcher.py --db results/forward/rmm_btc_4h/forward.sqlite --state-dir "%LOCALAPPDATA%\TradingLab\watchers" --startup-message
```

El nombre del estado local incluye un hash de la ruta absoluta del DB para evitar
mezclar journals. Mantener `--state-dir` en todos los reinicios posteriores. Si el
destino no existe, se valida y copia el estado original, conservando cursor, anchor,
failures y pending; el original no se borra. Si ya existe destino, se usa su cursor
vigente. Un origen/destino corrupto falla para revisión, sin reset. El lock del
watcher sigue junto al DB, por lo que la opción no permite otro watcher simultáneo.
Dry-run no crea ni copia estado. No mover SQLite/WAL/SHM ni borrar estados para
resolver el incidente. Pruebas dirigidas64 passed; Ruff de archivos afectados pasa.

La modificación del watcher cambia el hash global de código. No interrumpe un runner
ya abierto; antes de reiniciar RMM demo se requiere una nueva fase SIGNAL_ONLY y
recibo del código vigente según su gate. Con posiciones/órdenes demo existentes,
revisar cuenta y recuperación antes de cualquier reinicio; no liquidar automáticamente
ni reutilizar un recibo anterior cambiando sus hashes.

- Éxito confirmado: persiste el cursor y no reenvía esa fila en un reinicio normal.
- Antes del HTTP persiste `pending`, conservando el cursor completado anterior.
  Si el proceso se interrumpe, el siguiente arranque registra `interrupted_unknown`
  y no vuelve a enviar esa fila. Prioriza evitar duplicados por reinicio: puede perder
  un aviso si murió entre guardar pending y entregar a Telegram.
- Timeout/conexión/HTTP 5xx: hasta tres intentos, timeout de 10 s por petición y
  backoff 1/2 s. 429 respeta `retry_after`; si excede 30 s, no bloquea el consumidor:
  registra rate_limited y omite envíos durante ese cooldown. Tras agotar intentos,
  persiste fallo, avanza y sigue. No hay reenvío automático ni dead-letter con payload.
- **No existe garantía de entrega exactamente una vez**: una respuesta perdida puede
  provocar duplicado en un retry HTTP aunque Telegram ya recibiese el mensaje. No hay
  transacción conjunta entre sendMessage y el estado local. Una caída también puede
  perder el aviso según la política pending anterior. El journal conserva la evidencia.
- DB inexistente/bloqueada o esquema todavía no disponible: reintenta en el siguiente
  poll; `--once` devuelve 1 en vez de esperar indefinidamente. Un fallo persistente del
  esquema requiere revisar compatibilidad. Sin escrituras en el journal.
  Una base ausente muestra INFO indicando arrancar el runner para la ruta elegida;
  el watcher no crea la base. Bloqueos, acceso SQLite y otros errores de lectura
  tienen diagnósticos separados con código numérico, sin texto de excepción.
  Solo informa cuando cambia el problema y al recuperar la lectura, sin repetir
  el aviso cada dos segundos. El startup Telegram espera la primera lectura correcta.
- Estado corrupto, identidad del cursor cambiada o fallo de disco/lock: termina con
  código 2 para revisión, sin asumir cursor cero ni reenviar histórico. No restablecer
  el estado automáticamente si se sustituye/trunca un DB. No afecta al runner.

El startup opcional se intenta una vez por proceso (con retries HTTP acotados), no en
cada retry SQLite. No participa en el cursor de eventos. No afirma conectividad OKX.
El cliente rechaza redirects y solo hace POST a sendMessage, sin parse_mode ni previews.
Referencia: [Telegram Bot API: sendMessage](https://core.telegram.org/bots/api#sendmessage)
y [retry_after](https://core.telegram.org/bots/api#responseparameters).

## Verificación local

```powershell
python -m pytest tests/unit/test_notifications.py tests/integration/test_notification_watcher.py tests/unit/test_forward.py tests/integration/test_forward_runner.py tests/integration/test_forward_recovery.py -q
python -m ruff check .
python -m ruff format --check .
```

Los tests usan journals temporales, el Store real con fixtures y HTTP simulado. Cubren
formatos, privacidad, cursor, replay, reinicio, interrupción, atomicidad, WAL/escrituras
concurrentes, locks reales y simulados, timeouts/429/5xx, variables ausentes, CLI desde
otro cwd y ausencia de imports hacia Telegram en forward/brokers/strategies.
No requiere el DB operativo, Telegram real ni sesiones forward nuevas.

Verificación 2026-09-28: **50 tests del notifier aprobados** en 4.73 s y **39 regresiones
forward aprobadas** en la ejecución dirigida anterior (85 casos antes de añadir cuatro
pruebas adicionales del notifier). `pip check` y `git diff --check` correctos. Ruff
check/format globales detectan únicamente el archivo local preexistente no versionado
`scripts/test_telegram.py`; se conserva sin modificar ni ejecutar. Excluyendo ese
archivo, ambos checks pasan (293 archivos Python). Smoke CLI `--help` correcto.
No se ejecutó la suite histórica completa ni research. Flags `trading_enabled` y
`allow_live_trading` siguen false; ninguna modificación en forward, brokers, estrategias
o configs. Revisión de patrones de credenciales en archivos versionados y nuevos sin
coincidencias; `.env` continúa ignorado. La entrega a un chat real sigue sin verificar.

Archivos creados: `src/quant_lab/notifications/{__init__,telegram,formatter,forward_watcher}.py`,
`scripts/notification_watcher.py`, `tests/unit/test_notifications.py`,
`tests/integration/test_notification_watcher.py` y este documento.
Modificados: `.env.example`, README, docs/ARCHITECTURE.md y docs/PROJECT_STATE.md.
No se añadieron dependencias ni se cambió `.gitignore` (ya cubría los secretos/estado).

Actualización `.env`: 54 tests del notifier aprobados, incluidos carga desde la raíz
con otro cwd, prioridad del shell, aislamiento de variables de trading y errores sin
exposición de valores. Los tests usan `.env` temporales; no cargan credenciales locales.

Añadir Python cambia el hash general de provenance en un **futuro** arranque del
runner conforme a sus reglas actuales; no cambia el proceso ya arrancado ni migra su
estado. El watcher no requiere ni realiza ese reinicio, ni renueva recibos de preflight.
