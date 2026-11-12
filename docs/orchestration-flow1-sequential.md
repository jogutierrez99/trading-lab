# Ensayo secuencial del Flujo 1 en Windows

Preparación para una ejecución posterior por el operador. La verificación usa
proveedores simulados, Git real, la SQLite del ensayo y el runner real sobre
dos series artificiales. Hay una sola estrategia, `integration_candle_pulse_v1`,
con un caso con operaciones y un control sin operaciones. La ejecución tiene
seis casos técnicos, 328 velas, un máximo de 120 segundos y validación previa.

El investigador usa el perfil reducido `gpt-4o-mini-2024-07-18`, con techo de
128.000 tokens de entrada, 1.200 de salida y **0,04 €** de reserva. El auditor
usa `gpt-6.1-sol`, con techo de 1.050.000 de entrada, 1.200 de salida y **18,08 €**
de reserva. Son máximos conservadores de la configuración vigente, revisada
hasta el 12 de noviembre de 2026 UTC. Cada fase exige su diagnóstico y el ledger
de 20 €/mes. La implementación usa el CLI de Codex ya configurado, con máximo
de un intento y dos reparaciones técnicas admitidas, 300 segundos por intento
y 45 por comprobación. Codex CLI no reserva euros en el ledger de la API.

## Arranque real posterior

### Aceptación desatendida de una sola estrategia

Desde la raíz del repositorio, carga `OPENAI_ADMIN_KEY` en el entorno de
PowerShell y configura `$ledger`, `$organization` y `$project` según el
bloque inferior. Verifica que el proyecto sea el que factura ambas llamadas.
Usa una ruta de expediente que todavía no exista y un identificador único
para el lote sintético. Esta orden pasa el mismo `--billing-scope` a ambos
proveedores, verifica las reservas de 4 y 1808 céntimos y enlaza
`READY_FOR_AUDITOR_PREFLIGHT` con el diagnóstico del auditor.

```powershell
$acceptance = Join-Path $env:LOCALAPPDATA 'TLF1UA07'
$runArgs = @('--root', $acceptance, '--ledger', $ledger, '--organization', $organization,
             '--project', $project, '--acceptance-id', '20261107-v1',
             '--interval-seconds', 30, '--max-wait-seconds', 300)
& $py -B scripts/run_flow1_acceptance.py @runArgs
```

Consulta cada 30 segundos durante un máximo de 300 segundos de espera
por cargo. Los GET individuales están acotados por el adaptador. La falta
de publicación y el timeout de un GET permiten volver a consultar dentro
del plazo. La atribución ambigua, el acceso
denegado y las demás causas explícitas detienen el ensayo con su evidencia.
Consulta `acceptance.jsonl` para ver los diagnósticos y tiempos UTC. Si se
detuvo esperando facturación, repite la misma orden con `--resume`. Ese
modo usa el expediente existente y entra directamente en la conciliación.
Una implementación bloqueada o interrumpida se inspecciona mediante la
recuperación explícita del coordinador. La aceptación exige ambos asientos
conciliados y conserva un único aviso DRAFT con cero intentos de envío.

El arranque real del 7 de noviembre llegó a la auditoría IA con una llamada
por proveedor. La instantánea del investigador acreditó 0,00027855 USD.
El auditor respondió, pero los seis pares posteriores seguían iguales a su
referencia. Un GET del séptimo ciclo agotó el timeout antes del plazo y la
versión ejecutada se detuvo en `AWAITING_MODEL_AUDIT`. El tratamiento del
timeout se ajustó y se verificó offline. El expediente `TLF1UA07` se puede
retomar con `--resume`. La reanudación autorizada terminó el 7 de noviembre
a las 05:14:05 UTC con `NOTICE_PREPARED`. El auditor se concilió por
diferencia de instantáneas con 0,004158 USD, contabilizado en 0,01 EUR,
y liberó 18,07 EUR. El saldo global quedó en 19,90 EUR. La consulta repetida
devolvió `ALREADY_SETTLED` y el mismo aviso
`notice_268d85c3d7394ecab999979a7654b586` en DRAFT con cero intentos.
El expediente contiene una tarea, un intento, una ejecución, una auditoría
determinista y un aviso. Conserva una llamada del investigador y otra del
auditor. El cierre requirió reanudar después del timeout del primer arranque.
Entre la reserva del auditor y la conciliación pasaron 5 h 16 min. La
mayor parte de ese intervalo transcurrió con el proceso detenido. Las
consultas solo acotan cuándo se observó el cargo. Se desconoce la hora en
que OpenAI lo publicó.

### Consulta persistente de facturación

Desde la raíz del repositorio, ejecuta una pasada manual con la configuración
revisada del expediente `TLF1UA07`.

```powershell
& .\.venv\Scripts\python.exe -B scripts/poll_flow1_billing.py --config examples/orchestration/flow1_billing_worker.json
```

La orden inspecciona los directorios incluidos en `dossiers`. Usa la SQLite,
el expediente del investigador y el recibo del auditor de cada directorio.
Consulta `flow1-billing-cycle` una vez por expediente pendiente y por pasada.
Guarda la próxima consulta antes de acceder a facturación. La siguiente
invocación retoma el expediente desde el checkpoint y usa la organización,
el proyecto y el día UTC de la reserva original. Un bloqueo de Windows por
ledger excluye otras instancias del trabajador.

El ejemplo permite 120 segundos por pasada, con un mínimo de cinco minutos
entre consultas del mismo expediente pendiente y una antigüedad máxima de
48 horas. El timeout de consulta, la indisponibilidad temporal y la evidencia
aún incompleta conservan la espera. Una reserva incierta, evidencia ambigua
o una reserva demasiado antigua requieren revisión. El motivo queda en
`REVIEW_REQUIRED` dentro de `state_directory`. Tras resolverlo, archiva
el JSON de ese expediente fuera de ese directorio antes de volver a consultar.
Los checkpoints de la aceptación y las reservas están en sus expedientes
y en el ledger. El JSON del trabajador guarda únicamente el estado del sondeo.

Al conciliar al investigador, el trabajador pasa el diagnóstico del auditor.
La configuración entregada devuelve `AUDITOR_AUTHORIZATION_REQUIRED` si
el diagnóstico es apto y aún hace falta una nueva llamada. Una futura
configuración con `allow_model_audit: true` requiere revisar ese permiso,
el perfil, el ámbito y el límite de la reserva. Para un auditor que ya tiene
recibo, el trabajador usa el ciclo de facturación para preparar el borrador
cuando se confirme el cargo.

El trabajador toma `OPENAI_ADMIN_KEY` del entorno o lee exclusivamente esa
entrada en `secrets_env_file`. La cuenta de Windows necesita acceso de lectura
al archivo local y de escritura al directorio de estado y al ledger. El XML
usa la cuenta operadora con privilegios limitados y requiere que tenga una
sesión iniciada. La ejecución con la sesión cerrada requiere validar otra
identidad de ejecución y el acceso a esos archivos.

El XML `examples/orchestration/flow1_billing_task.xml` contiene la acción,
el intervalo de cinco minutos, la política `IgnoreNew` y el estado
deshabilitado. Después de revisar las rutas y la cuenta, puedes registrarlo
deshabilitado con estos comandos.

```powershell
$xml = Get-Content -LiteralPath 'examples/orchestration/flow1_billing_task.xml' -Encoding UTF8 -Raw
Register-ScheduledTask -TaskName 'Trading Lab Flow 1 Billing' -Xml $xml
Get-ScheduledTask -TaskName 'Trading Lab Flow 1 Billing' | Select-Object TaskName, State
```

Antes de activar una programación, comprueba una pasada manual con un
expediente autorizado y valida el acceso bajo la cuenta elegida. Revisa si
la periodicidad y la antigüedad máxima encajan con la operación prevista.

El 11 de noviembre se ejecutaron dos pasadas manuales sobre TLF1UA07.
Ambas recuperaron el mismo DRAFT con `ALREADY_SETTLED` y 0 EUR liberados.
Las huellas de las dos SQLite, el diario de aceptación y el recibo del
auditor coincidieron antes y después. Windows aceptó el XML como definición
deshabilitada sin registrarlo.

### Comandos de las etapas individuales

Desde PowerShell en la raíz del repositorio. La ruta de ensayo es independiente
del ledger y del checkout. El ledger global debe existir y estar conciliado.

```powershell
$py = '.\.venv\Scripts\python.exe'
$cli = 'scripts/orchestrator.py'
$ledger = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3'
$env:TRADING_LAB_GLOBAL_API_DB = $ledger
$root = Join-Path $env:LOCALAPPDATA 'TLF1SeqTrial'
$db = Join-Path $root 'state\trial.sqlite3'
$research = Join-Path $root 'research'
$artifacts = Join-Path $root 'circuit'
$modelDossier = Join-Path $root 'model-audit'
$request = Join-Path $root 'circuit-request.json'
$batch = 'examples/orchestration/research_batch_flow1_sequential.json'
$id = 'flow1_seq_v1'
$batchSha = 'f7938e03cf96044bec53c8f7141ca5735c8fb0c96bd36e7e950c8c2462be2b55'
$researchDossier = Join-Path $research $batchSha
$organization = 'org-ID_VERIFICADO'
$project = 'proj_ID_VERIFICADO'
```

Ejecutar primero los diagnósticos. La ficha 4.6 se usa aquí únicamente para
comprobar el mismo objetivo técnico y la resolución del CLI. El preflight
es local y no verifica autenticación de Codex.

```powershell
if (Test-Path $root) { throw 'El ensayo ya tiene expediente. Consulta su estado.' }
& $py -B $cli --db $db circuit-doctor examples/orchestration/circuit46.json --repo . --artifacts $artifacts
if ($LASTEXITCODE -ne 0) { throw 'Preflight Windows bloqueado.' }
$raw = & $py -B $cli research-doctor $batch --budget-db $ledger --profile reduced
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$check = $raw | ConvertFrom-Json
if ($check.status -ne 'READY' -or $check.batch_sha256 -ne $batchSha -or
    $check.pricing.model -ne 'gpt-4o-mini-2024-07-18' -or $check.pricing.maximum_cents -ne 4 -or
    $check.pricing.input_token_ceiling -ne 128000 -or $check.pricing.output_token_limit -ne 1200) {
    throw 'El lote o el perfil del investigador cambió.'
}
```

Arranque de pago, reservado para el ensayo real. Si hay `NEEDS_REVIEW` se
detiene con el expediente del investigador. Si quedó `QUEUED`, se vincula la
misma tarea al circuito y se comprueba la ruta exacta antes de implementar.

```powershell
$raw = & $py -B $cli --db $db research-intake $batch --budget-db $ledger --profile reduced --artifacts $research --confirm-maximum-cents 4 --billing-scope $organization $project
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$intake = $raw | ConvertFrom-Json
$intake
if ($intake.status -ne 'REGISTERED' -or $intake.queue_status -ne 'QUEUED') { throw 'El investigador requiere revisión.' }
$raw = & $py -B $cli --db $db flow1-bind --budget-db $ledger --research-dossier $researchDossier
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
if (Test-Path $request) { throw 'Conserva la solicitud ya guardada.' }
$raw | Set-Content -LiteralPath $request -Encoding utf8
& $py -B $cli --db $db circuit-doctor $request --repo . --artifacts $artifacts
if ($LASTEXITCODE -ne 0) { throw 'Preflight de la tarea vinculada bloqueado.' }
& $py -B $cli --db $db circuit-run $request --repo . --artifacts $artifacts
```

## Consulta, conciliación y reanudación

Si se interrumpe la sesión, vuelve a cargar el bloque de variables. Consulta
el estado sin repetir el arranque. `AWAITING_MODEL_AUDIT` implica ejecución y
auditoría determinista guardadas. El auditor IA y el aviso siguen pendientes.
Los bloqueos de implementación o ejecución se consultan y reconcilian con los
comandos existentes del circuito, según su estado.

```powershell
$raw = & $py -B $cli --db $db circuit-show $id
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$state = $raw | ConvertFrom-Json
$state | Select-Object status,task_id,attempt_id,execution_id,audit_id,notification_id,error
$intake = Get-Content -LiteralPath (Join-Path $researchDossier 'result.json') -Raw | ConvertFrom-Json
& $py -B $cli --db $db show $intake.task_id
```

Para expedientes con captura previa, ejecuta el ciclo programático descrito
abajo con `$intake.call_id`. Si el expediente es anterior a esa captura,
exporta Usage y Costs para el día UTC de `intake.call_id`. Si ese día hay
otros cargos conciliados, conserva como referencia sus dos exportaciones
anteriores y añade ambos argumentos `--prior-*` indicados abajo. Para el 6 de
noviembre de 2026, la pareja `(4)` ya conciliada sirve de referencia si se
mantiene el mismo ámbito. Usa `--exclusive-billing-scope` cuando los informes
cubran exclusivamente las llamadas de Lab que se están comparando.

```powershell
$usage = 'C:\RUTA\completions_usage_actualizado.csv'
$costs = 'C:\RUTA\cost_actualizado.csv'
$evidence = @($intake.call_id, '--usage-csv', $usage, '--costs-csv', $costs, '--exclusive-billing-scope')
# Si hay otros asientos conciliados del mismo día y ámbito, añade las rutas anteriores:
# $evidence += @('--prior-usage-csv', 'C:\RUTA\usage_anterior.csv', '--prior-costs-csv', 'C:\RUTA\cost_anterior.csv')
$raw = & $py -B $cli --db $ledger api-budget-billing-doctor @evidence
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$billing = $raw | ConvertFrom-Json
if ($billing.status -eq 'READY') {
    & $py -B $cli --db $ledger api-budget-billing-reconcile @evidence
    if ($LASTEXITCODE -ne 0) { throw 'No se acreditó la conciliación.' }
} elseif ($billing.status -ne 'ALREADY_SETTLED') {
    throw 'El investigador sigue pendiente.'
}
```

Si la facturación falta, conserva el expediente y repite solo el ciclo
programático o el diagnóstico histórico, según corresponda. Una vez
conciliada, reanuda desde la auditoría
determinista guardada. Si ya existe el recibo del auditor IA, pasa a validar
ese recibo y recuperar el borrador. Si la reserva del auditor existe pero
falta su recibo, el diagnóstico impedirá otro intento de pago.

```powershell
$raw = & $py -B $cli --db $db circuit-show $id
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$state = $raw | ConvertFrom-Json
if ($state.status -notin @('AWAITING_MODEL_AUDIT', 'NOTICE_PREPARED')) { throw 'El ensayo no llegó al auditor.' }
$auditId = $state.audit_id
$receipt = Join-Path $modelDossier 'review_receipt.json'
if (!(Test-Path $receipt)) {
    $raw = & $py -B $cli --db $ledger audit-openai-doctor $auditId --source-db $db --model gpt-6.1-sol
    if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
    $check = $raw | ConvertFrom-Json
    if ($check.status -ne 'READY' -or $check.pricing.maximum_cents -ne 1808 -or
        $check.pricing.input_token_ceiling -ne 1050000 -or $check.pricing.output_token_limit -ne 1200) {
        throw 'El perfil del auditor cambió.'
    }
    & $py -B $cli --db $ledger audit-openai $auditId --source-db $db --model gpt-6.1-sol --artifacts $modelDossier --confirm-maximum-cents 1808 --billing-scope $organization $project
    if ($LASTEXITCODE -ne 0) { throw 'Auditor IA incompleto. Consulta su recibo y ledger.' }
}
$review = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
& $py -B $cli --db $db flow1-billing-cycle $review.call_id --project-id $project --budget-db $ledger --research-dossier $researchDossier --model-dossier $modelDossier
```

La aceptación exige la misma candidata y tarea de `QUEUED`, una ejecución
`SUCCEEDED` con los seis casos sintéticos, auditoría determinista
`COMPLETED_WITH_LIMITATIONS`, ambos asientos `SETTLED`, un único recibo del
auditor IA `COMPLETED` ligado a la ejecución y `NOTICE_PREPARED` con un solo
aviso `DRAFT`, cero intentos de entrega y `message_id` vacío. La repetición del
ciclo devuelve el mismo aviso sin volver a conciliar.

## Recuperación del intento bloqueado el 6 de noviembre

El expediente real `flow1_seq_v1` adoptó la tarea
`task_746fd03fc0f64e749eb5af8dec39ee05`. En el intento
`attempt_99b374401e7547f3a6c4a8d6ccebf030`, el lanzador eligió el `pwsh.exe`
del runtime privado. Ese binario funciona por sí solo. El proceso directo
de Codex heredaba `CODEX_WINDOWS_REGISTERED_CORE=1`, que solicita un
lanzador que exige identidad de paquete de la app en el proceso de Codex.
La prueba local con `codex sandbox` reprodujo el mismo error. Al omitir
solo esa variable para la CLI hija, el mismo binario y worktree devolvieron
`TLF1_SHELL_OK`, código 0, bajo `elevated`, `:workspace`, red deshabilitada
y aprobaciones `never`. El adaptador aplica esa omisión a sus comprobaciones
y a su arranque supervisado.
[Código de la versión instalada](https://github.com/openai/codex/blob/rust-v0.166.0-alpha.6/codex-rs/windows-sandbox-rs/src/app_package.rs) ·
[Sandbox de Windows](https://learn.chatgpt.com/docs/windows/windows-sandbox)

La llamada del investigador `call_fc42254bf6be400e8430fd9dcfc9fc69` quedó
`SETTLED` con los CSV `(6)` frente a `(4)`. El cargo acreditado fue
0,00027840 USD, contabilizado como 0,01 €, y se liberaron 0,03 €. El intento
de implementación sigue `BLOCKED` con `retry_allowed=0` y su hijo consta como
`EXITED`. El recibo original se conserva. El backtest y el auditor siguen
pendientes de la implementación.

Cuando se autorice reanudar la implementación, carga las variables del
bloque de arranque y usa los comandos siguientes. `reconcile --outcome failed`
registra el cierre confirmado y el motivo en el historial. `circuit-run --resume`
usa la solicitud ya guardada, conserva la tarea y consume el intento 2 del
presupuesto original de 3. Si el estado ya es `FAILED` con `retry_allowed=1`,
omite la reconciliación y conserva el evento que ya la autorizó.

```powershell
$attempt = 'attempt_99b374401e7547f3a6c4a8d6ccebf030'
$raw = & $py -B $cli --db $db attempt $attempt
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$a = $raw | ConvertFrom-Json
if ($a.task_id -ne 'task_746fd03fc0f64e749eb5af8dec39ee05' -or $a.process_state -ne 'EXITED') {
    throw 'La identidad del intento o el estado del hijo no coincide.'
}
if ($a.status -eq 'BLOCKED' -and !$a.retry_allowed) {
    $raw = & $py -B $cli --db $db reconcile $attempt --outcome failed --confirm-stopped --reason 'Arranque registrado rechazado; hijo EXITED. La prueba local TLF1_SHELL_OK verificó el mismo sandbox con el entorno CLI corregido. Se conserva el recibo original.'
    $closed = $raw | ConvertFrom-Json
    if ($closed.attempt_id -ne $attempt -or $closed.status -ne 'FAILED' -or !$closed.retry_allowed) {
        throw ($raw -join "`n")
    }
} elseif ($a.status -ne 'FAILED' -or !$a.retry_allowed) {
    throw 'Consulta el expediente antes de seguir.'
}
& $py -B $cli --db $db circuit-run $request --repo . --artifacts $artifacts --resume
```

Cuando el circuito llegue a `AWAITING_MODEL_AUDIT`, usa el bloque de
reanudación del auditor con el mismo expediente. El investigador ya está
conciliado.

## Un ciclo de facturación bajo demanda

`flow1-billing-cycle` hace una consulta programática por invocación para el
asiento del investigador o del auditor que pertenece al expediente indicado.
Usa el ledger global, los mismos recibos y el proyecto explícito. Requiere
`OPENAI_ADMIN_KEY` en el entorno del proceso que lo ejecuta. Para uso manual
en Windows, cárgala en la sesión local de PowerShell. Para una tarea futura,
inyéctala desde el almacén de secretos de la cuenta que lance el proceso.
La variable requiere una clave Admin de la organización con acceso de lectura
a `GET /v1/organization/usage/completions` y `GET /v1/organization/costs`.
El adaptador no lee `.env` para esta variable y el coordinador la excluye
del entorno de sus procesos hijos.
[Autenticación Admin](https://developers.openai.com/api/reference/cli)

En un ensayo nuevo, pasa `--billing-scope $organization $project` tanto a
`research-intake` como a `audit-openai`. Antes de reservar y enviar, el
coordinador consulta el día UTC del proyecto con filtros fijos, comprueba
que Usage y las partidas de Costs cubran los recibos ya conciliados y
archiva las respuestas con hora UTC, ámbito, consultas y SHA-256. Si falla
esa captura, el comando de pago se detiene. Usa el mismo proyecto dedicado
para las dos llamadas y una clave de modelo con acceso a ese proyecto.
Los archivos quedan en el directorio `<nombre-del-ledger>-billing-snapshots`
junto a la SQLite. El ledger vincula la instantánea previa por ruta y hash.

Después de cargar las variables de esta guía y comprobar el proyecto facturado:

```powershell
$pending = $intake.call_id  # Después de ejecutar el auditor, usa $review.call_id.
& $py -B $cli --db $db flow1-billing-cycle $pending --project-id $project --budget-db $ledger --research-dossier $researchDossier --model-dossier $modelDossier
```

El ciclo deja `WAITING_BILLING` cuando la evidencia falta o es insuficiente.
`billing.reason_code` distingue `ADMIN_KEY_MISSING`, `ADMIN_ACCESS_DENIED`,
`COST_NOT_AVAILABLE`, `USAGE_INCOMPLETE_OR_DIFFERENT_SCOPE` y
`ATTRIBUTION_UNCERTAIN`. `BASELINE_MISSING` requiere la vía histórica con CSV
o un justificante individual. Usage incompleto por sí solo no distingue un retraso
de un ámbito diferente. Un estado de espera devuelve código 0 con el resultado
estructurado. Una entrada inválida o un expediente incoherente devuelve error.

Con el investigador conciliado, `READY_FOR_AUDITOR_PREFLIGHT` es el punto
de entrega a la siguiente etapa. El ciclo no invoca al modelo. Si ya existe
un asiento del auditor, devuelve `AUDITOR_ALREADY_RESERVED` y el siguiente
ciclo debe usar ese asiento. Si otro gasto bloquea el saldo global, devuelve
`WAITING_GLOBAL_LEDGER`. Si el auditor ya tiene recibo válido y se concilia,
el ciclo termina la preparación del `DRAFT` pendiente o recupera el existente.
Un asiento `ALREADY_SETTLED` evita volver a consultar Usage y Costs. El ciclo
reutiliza la ejecución y la auditoría determinista, incluso tras reiniciar.

El ciclo exige una única incorporación en Usage y cantidades e importes de
entrada y salida coherentes en ambos Costs. Cualquier partida inesperada,
ajuste, cambio de tarifa o ámbito, o cantidad pendiente conserva la reserva.
La conciliación usa la diferencia facturada, con la conversión y el redondeo
existentes. El cargo histórico de 0,00414 USD se acreditó manualmente con CSV
previos y el desglose posterior. Su regresión reconstruye las partidas previas
en una SQLite aislada a partir de los datos archivados. La prueba integrada
simula investigador y auditor en el mismo día UTC. Queda pendiente un ensayo
desatendido con dos instantáneas programáticas reales y el mismo ámbito.
