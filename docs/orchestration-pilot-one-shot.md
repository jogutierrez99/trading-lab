# Fase 5.4B — Autorización local de preparación

El receptor de GitHub conserva su recorrido de ingesta y revisión manual.
`scripts/authorize_github_pilot.py` es un punto de entrada del operador,
separado del receptor. Valida el checkpoint sellado y la misma ficha de
`HypothesisManifest 1.0` que usa el diagnóstico de 5.4A. El comando
`approve` requiere entrada y salida conectadas a una terminal interactiva.
Muestra el ámbito y exige escribir una frase con la tarea y el commit.
El recibo toma el usuario y el SID del token del proceso Windows mediante
`whoami.exe /user` localizado en el directorio del sistema que devuelve Windows,
y fecha UTC local; la CLI no admite `approved_by`
como argumento. GitHub acredita la identidad del autor del Issue y el
cuerpo recibido. Etiquetas y comentarios carecen de efecto autorizador.

Esta identificación confía en la sesión Windows, el código y los
permisos de los archivos locales. El SID identifica la cuenta del
proceso, no a la persona ante el teclado. No hay firma criptográfica,
MFA adicional ni protección frente a software con control de la cuenta,
del proceso o con acceso de escritura directo a SQLite. Proteger las
ACL, la instalación y la terminal es parte del límite de confianza.

## Recibo, reserva y recuperación

`PreparationAuthorization` amplía el vínculo consultivo
`ReviewAuthorization` con el hash del cuerpo, commit, SID, ruta
del ledger, máximo de un intento, tiempos del plan, 0 EUR de API y
prohibición de backtests. La aprobación queda en la cola SQLite
existente como recibo canónico con SHA-256. La tabla se crea al registrar
la primera aprobación explícita. La consulta, el receptor y las
migraciones ordinarias mantienen el esquema actual.

- `APPROVED` permite reservar la preparación vinculada. `REVOKED`
  cierra una aprobación sin consumirla y permite registrar otra.
- `RESERVED` vincula el único intento. El recibo y la reserva cambian
  en la misma transacción. Este estado sin un preparador activo exige
  revisión del intento antes de cualquier actuación.
- `CONSUMED` indica que se sellaron los controles de preparación.
  `UNKNOWN` indica una preparación interrumpida o incompleta.
- `CLOSED` archiva el intento original mediante conciliación explícita.
  Se conserva el intento y el límite queda agotado.

Las transiciones se registran en la bitácora existente. El preparador
toma el cerrojo de implementación y abre una transacción de escritura
en la cola. Vuelve a comprobar el SID, los hashes, el commit, el estado
de la tarea y candidata, la ausencia de intentos y de trabajo activo o
incierto, el protocolo y los límites. Hace un GET de GitHub para
comprobar Issue abierto, autor, etiqueta y hash del cuerpo. Un fallo
de red o una divergencia bloquean la reserva. Como GitHub es externo,
su respuesta es una observación puntual.

La ruta del ledger se deriva del archivo de configuración versionado
en el commit aprobado y se abre en solo lectura. El argumento de aprobación
debe coincidir con esa ruta. La preparación recupera la ruta del recibo
y vuelve a validarla contra el commit. Se comprueba el presupuesto y se
mantiene una transacción de lectura con journal de rollback hasta
confirmar la reserva en SQLite. Un ledger con WAL, sin evidencia de
apertura mensual, con saldo agotado o con reservas inciertas bloquea.
No se debita ni se reserva presupuesto API. La exclusión de tareas
pesadas usa la SQLite de coordinación; bases independientes conservan
sus propios cerrojos.

Para el Issue #3, el coordinador exige la tarea original y coteja la
ficha y el plan con los archivos Git del commit aprobado. Incluso una
llamada directa a `Coordinator.prepare` usa el transporte de GitHub del
coordinador y el ledger fijado. El perfil debe declarar `enabled: false`
en el worktree para que el intento llegue a `CONSUMED`.

Si hay una interrupción, consulta `show` y conserva los artefactos
del intento. `close` revoca una aprobación pendiente o cierra el
intento ya reservado con `--confirm-stopped`. Antes de confirmar,
comprueba que también terminaron el preparador y los posibles hijos de
Git o del scaffolder; si la identidad de un hijo registrado es incierta,
el cierre se bloquea. No relances la preparación.

## Orden futura para la revisión del operador

Estos comandos requieren un encargo posterior. Ejecutar el script desde
un checkout con este mecanismo revisado. `$repoBase` es un checkout
separado fijado al SHA del piloto, porque el commit del mecanismo puede
ser posterior. Los caminos de SQLite y del ledger corresponden a la
configuración original. Revisar `$request` y sus hashes antes de
introducir la confirmación interactiva.

```powershell
$py = '.\.venv\Scripts\python.exe'
$db = Join-Path $env:LOCALAPPDATA 'TradingLab\GitHubIntake53\queue.sqlite3'
$plan = (Resolve-Path examples/orchestration/phase-5-4b/implementation-plan.draft.json).Path
$secrets = (Resolve-Path .env).Path
$evidence = 'C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85\phase-5-4b-issue-3-reception'
$request = Get-Content -Raw (Join-Path $evidence 'authorization-request.pending.json') | ConvertFrom-Json
$record = Get-Content -Raw (Join-Path $evidence 'issue-3-reception.json') | ConvertFrom-Json
$repoBase = Read-Host 'Ruta del checkout en el commit base aprobado'
if ((git -C $repoBase rev-parse HEAD) -ne $request.base_commit) { throw 'El checkout no coincide con el commit base' }
$ledger = (git -C $repoBase show "$($request.base_commit):examples/orchestration/flow1_billing_worker.json" | ConvertFrom-Json).ledger
& $py -B scripts/authorize_github_pilot.py --db $db approve --repo $repoBase --ledger $ledger --plan $plan --env-file $secrets --issue $request.issue_number --issue-id $request.issue_id --task-id $request.task_id --proposal-sha256 $request.proposal_sha256 --body-sha256 $record.checkpoint.body_sha256 --plan-sha256 $request.plan_sha256 --base-commit $request.base_commit
```

Cuando exista la aprobación, sustituir `$id` por su ID real y elegir
una carpeta local corta de artefactos fuera del checkout. `show`
lee el recibo sin migrar la base. `prepare` actúa una sola vez
después de la revisión explícita del operador.

```powershell
$id = Read-Host 'Identificador de la autorización'
$artifacts = Join-Path $env:LOCALAPPDATA 'TL54B\attempts'
& $py -B scripts/authorize_github_pilot.py --db $db show --authorization-id $id
# Ejecutar solo cuando corresponda a la preparación autorizada.
& $py -B scripts/authorize_github_pilot.py --db $db prepare --authorization-id $id --repo $repoBase --plan $plan --env-file $secrets --artifacts $artifacts
& $py -B scripts/authorize_github_pilot.py --db $db show --authorization-id $id
# Solo tras verificar que todos los procesos se detuvieron.
# & $py -B scripts/authorize_github_pilot.py --db $db close --authorization-id $id --confirm-stopped --reason 'Motivo comprobado por el operador'
```

## Lanzamiento independiente

El recibo `PREPARE_ONLY` nunca habilita `run`, verificación de
resultados de modelo o reparación de formato del intento protegido.
Un disparador de SQLite impide guardar `RUNNING`, `SUCCEEDED` o habilitar
un reintento aunque un runtime anterior intente hacerlo.
En un encargo posterior debe diseñarse el permiso `LAUNCH_CODEX`
vinculado al intento y al hash de sus controles ya sellados, con
confirmación independiente del operador, revalidación del estado y
presupuesto, sandbox `workspace-write` y el mismo límite de un
intento. Este cambio no emite ni consume ese permiso.
