# Fase 5.3 · Recepción periódica de GitHub

El Programador de tareas invoca una pasada del consumidor local. El consumidor
lee los Issues abiertos con `strategy-intake` de `jogutierrez99/trading-lab`,
valida cada ficha y usa la cola SQLite existente. Cada propuesta y su
checkpoint se confirman en una transacción bajo el bloqueo por cola. La
tarea queda en `MANUAL_REVIEW / PREPARE_ONLY / QUEUED`. La pasada termina
al completar la recepción. La acción de Windows solo invoca `poll`.

## Comandos locales

Ejecuta desde la raíz en PowerShell con el entorno virtual instalado.
`--env-file` lee únicamente la asignación `TRADING_LAB_GITHUB_TOKEN` y
mantiene el token en memoria para la API de GitHub. El token necesita
acceso al repositorio con permiso de lectura de Issues. Las dos primeras
órdenes consultan GitHub sin tocar la cola. `scan` muestra números de
Issues. Usa `--issue N` en `scan` o `poll --live-read` para limitar una
prueba supervisada a un Issue.
[API de Issues](https://docs.github.com/en/rest/issues/issues#list-repository-issues)
· [Permisos para consultar la etiqueta](https://docs.github.com/en/rest/issues/labels#get-a-label)

```powershell
$py = '.\.venv\Scripts\python.exe'
$cli = 'scripts/github_strategy_intake.py'
$root = Join-Path $env:LOCALAPPDATA 'TradingLab\GitHubIntake53'
$db = Join-Path $root 'queue.sqlite3'
$logs = Join-Path $root 'logs'

& $py -B $cli --env-file .env doctor
& $py -B $cli --env-file .env scan
& $py -B $cli --db $db --env-file .env --log-dir $logs poll --author-id 64194024 --live-read
& $py -B $cli --db $db list
& $py -B $cli --db $db show --issue 2
Get-ChildItem -LiteralPath $logs -Filter '*.json' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 10
```

Usa una sola ruta de cola para las pasadas recurrentes. La deduplicación y el
límite de tres altas por fecha de investigación se aplican dentro de esa
SQLite. Antes de la primera pasada amplia, revisa los Issues abiertos que
ya se procesaron en bases de prueba. En una cola nueva se consideran
propuestas nuevas. El ledger canónico y las SQLite de ensayos anteriores
quedan fuera de la acción.

## Revisión y recuperación

Cada pasada crea un JSON con fecha UTC, estado, números de Issue, motivo
cuando corresponde, hash y tarea. `list` consulta checkpoints y `show`
recupera el registro de un Issue. Verifica que la ruta del log pertenezca
a la cuenta operadora. Se acumula un archivo por pasada.

Un autor fuera de la lista, una etiqueta ausente, un cuerpo inválido,
una identidad editada, un ID de hipótesis en conflicto o el límite diario
impiden el alta. Las fichas se conservan como datos y los comentarios no
participan en la ingesta. Una coincidencia de identidad o de huella
recupera la tarea existente.

`WAITING_LOCK` indica otra pasada en curso. `WAITING_GITHUB` indica una
lectura fallida, una respuesta parcial o una espera solicitada por
GitHub. Los fallos transitorios elegibles tienen un reintento inmediato
por petición. Si GitHub indica un límite y proporciona un plazo, la cola
guarda el momento de reintento en un archivo junto a la base. Durante
ese plazo, `poll` devuelve espera sin consultar GitHub. Usa ese plazo
también para cualquier diagnóstico manual. Una pasada reúne todas las
páginas antes de registrar. Si las páginas se solapan, una falla o hay
más de cinco páginas de treinta elementos, se conserva la cola.
Revisa los Issues abiertos si el límite de páginas impide continuar.
[Límites de la API de GitHub](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#exceeding-the-rate-limit)

Tras una interrupción vuelve a ejecutar `poll` con la misma SQLite. Las
transacciones confirmadas vuelven con `replayed: true` y la transacción
incompleta se revierte. Si la interrupción fue antes de escribir el log,
el checkpoint sigue siendo la fuente de estado.

## Programación de Windows

El generador entrega XML deshabilitado, con inicio en la cuenta actual,
privilegios limitados, `IgnoreNew` y un límite de tres minutos por pasada.
El intervalo predeterminado es 15 minutos y admite de 5 a 60. La cuenta
requiere una sesión iniciada, el ordenador encendido, acceso de red a
GitHub y acceso local al checkout, al entorno Python, a `.env` y a su
directorio bajo `LOCALAPPDATA`.

```powershell
$name = 'Trading Lab GitHub Intake 5.3'
$xml = & .\scripts\new_github_intake_task.ps1 -IntervalMinutes 15
# Opcional, tras revisar el XML. El registro crea la tarea deshabilitada.
Register-ScheduledTask -TaskName $name -Xml ($xml -join [Environment]::NewLine)
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
```

Solo tras autorización para activar la recepción periódica, usa
`Enable-ScheduledTask -TaskName $name`. Para detener futuras pasadas,
usa `Disable-ScheduledTask -TaskName $name`. Validar la primera pasada
bajo la cuenta operadora forma parte de la activación. La fase 5.4
requerirá una autorización distinta para preparar propuestas o ejecutar
Codex, más la revisión del protocolo y los controles del ledger cuando
correspondan. Los backtests y actividades operativas tienen su propia
autorización.
[Esquema del Programador de tareas de Windows](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema)

## Evidencia del Issue #2

El Issue publicado el 13 de noviembre a las 09:06:31 Europe/Madrid llegó
con autor `64194024`, etiqueta `strategy-intake` y origen
`chatgpt-daily-0900`. La ficha `btc_eth_long_only_multihorizon_tsmom_4h_v1`
cumple JSON 1.0, cita la URL SSRN en sus referencias y declara datos
`UNVERIFIED` y holdout `UNKNOWN`. La ingesta del 15 de noviembre fue
`ACCEPTED`. Repetir la lectura del mismo número devolvió
`replayed: true` y la misma tarea
`task_41e6afff474b4dedb69bdcf802471dd1`.
SHA-256 de propuesta
`ee29dcb81691c0eb95f4fe268e3eb3227c2fa993f9d159371967ff3e17d5f2fb`.
La SQLite aislada contiene una tarea y cero intentos, ejecuciones y avisos.
[Issue #2](https://github.com/jogutierrez99/trading-lab/issues/2)
