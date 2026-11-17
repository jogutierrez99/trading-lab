# Fase 5.4B — Autorización independiente de lanzamiento

El permiso `LAUNCH_CODEX` se registra por separado de `PREPARE_ONLY`.
La aprobación exige una terminal Windows interactiva y muestra la
identidad de la cuenta del proceso, el SID, el alcance y los hashes. El
operador escribe `LANZAR <attempt_id> <controls_sha256>`. La sesión local
identifica la cuenta y aporta una confirmación explícita sin firma
criptográfica de consentimiento. El receptor de Issues carece de acceso
a esta operación.

## Vínculo y reserva

El recibo se deriva de la preparación consumida y del intento persistido.
Incluye repositorio, Issue, tarea, intento, recibo de preparación y su hash,
cuerpo y propuesta, plan, base Git, solicitud, controles y ledger. Fija una
invocación inicial, hasta 600 s, 0 EUR de API, sandbox `workspace-write` y
prohibición de reparación automática, backtests y OKX. La salida estructurada
del modelo se valida con el contrato existente.

Antes de reservar se validan el Issue vivo, el checkpoint, el operador,
el saldo del ledger fijado en el commit base, los procesos y el estado de
los trabajos. También se comprueban la rama, el commit del worktree, los
archivos y hashes de `prepared-files.json`, el perfil deshabilitado y los
comandos de cierre derivados del plan. El adaptador fija MXC en Windows,
`workspace-write`, red de shell desactivada y aprobaciones `never`. La
comprobación local exige sesión Codex de ChatGPT. El consumo de esa sesión
queda fuera del gasto de la API de Trading Lab.

`APPROVED` permanece sin consumir hasta que, bajo el cerrojo de
implementación, la misma transacción marca el permiso `RESERVED` y el
intento `RUNNING`. El primer recibo instala los disparadores en esa SQLite
sin tocar bases con recepción ordinaria. El disparador preserva la
protección para intentos sin su permiso reservado, bloquea reintentos y
exige la misma solicitud y controles. Otro disparador bloquea la reserva
de backtest del piloto. Las rutas genéricas `run`, circuitos y reparación
siguen bloqueadas para el piloto.

La reserva exige su evento de auditoría en la misma transacción.
El esquema protege los recibos y sellos contra actualizaciones y
reemplazos accidentales, incluso con los disparadores recursivos
desactivados. La SQLite y sus permisos de escritura siguen siendo
parte del límite de confianza.

Un desenlace conocido agota el permiso como `CONSUMED`. Una interrupción
registra `UNKNOWN`; un cierre abrupto puede dejar `RESERVED / RUNNING`.
Ambos estados requieren comprobar identidad y parada del proceso antes
de cerrar el expediente. `close-launch` permite revocar una aprobación
pendiente o cerrar un intento incierto con confirmación de parada. El
cierre conserva los archivos y el límite agotado. El coordinador registra
la identidad del proceso y conserva los logs. Las comprobaciones
independientes, el perfil explícitamente deshabilitado y una entrega
coherente con el diff son requisitos para `IMPLEMENTED_VERIFIED`.

## Verificación independiente del código entregado

La auditoría reprodujo una escritura externa mediante el ejecutor local.
Ahora el intento protegido delega pytest, recopilación, importaciones,
Ruff y `SYNTHETIC_OHLCV_UTC_V1` al verificador Linux de Docker Desktop.
El host comprueba hashes, alcance, diff sin extensiones y perfil YAML
deshabilitado. El verificador recibe por stdin un archivo con la copia
del código de laboratorio del commit base, los tres archivos exactos
de la entrega y el verificador nativo del coordinador. La copia de la
solicitud sustituye únicamente el directorio por `/work`.
Se rechazan enlaces y puntos de reanálisis en las entradas de la entrega.
Quedan fuera los `conftest.py` del worktree, datos, metadatos Git,
credenciales, expedientes y bases operativas.

Cada comprobación usa un contenedor efímero sin red, montajes del host
ni socket Docker, con raíz de solo lectura, usuario sin privilegios,
capacidades retiradas y espacio temporal acotado de 32 MiB. Los límites
son una CPU, 768 MiB sin swap, 64 procesos y el tiempo restante del plan.
El supervisor limita también el volumen de los registros y confirma la
eliminación por el nombre único persistido antes del arranque. Los
procesos descendientes conservan el aislamiento del contenedor. Ante
interrupción o limpieza sin confirmar, la conciliación comprueba la
ausencia del contenedor antes de cerrar el expediente. El permiso sigue
agotado.

El permiso sella la imagen local por ID, el cliente Docker y la
configuración y código del verificador. El sondeo se repite antes de
reservar el lanzamiento y prueba restricciones de archivo, red, sockets
VM-host y procesos
hijos y dependencias. Una configuración ausente, distinta o que falle
el sondeo bloquea el lanzamiento antes de reservarlo. Si una comprobación
obligatoria falla después, se conserva su evidencia y se impide
`IMPLEMENTED_VERIFIED`. Las rutas para expedientes ordinarios mantienen
su comportamiento histórico. El aislamiento de esta fase cubre la
verificación independiente del intento protegido. MXC sigue regiendo la
sesión del modelo.

La imagen revisada y el motor Linux forman parte del límite de confianza.
El aislamiento contiene el código y sus hijos. Un test entregado por el
modelo sigue siendo evidencia de alcance limitado sobre la corrección
de la estrategia. La aceptación del entorno requiere el sondeo y la
prueba separada con la estrategia ficticia SMA.

En el equipo del piloto se detectó Windows 11 Home 25H2, build
26200.9974, con virtualización de firmware y SLAT expuestas por Windows.
Windows Sandbox carece de soporte en Home. El sondeo anterior de MXC
mostró una denegación al crear alias en `.codex/tmp/arg0-windows`, seguida
de un código 1 del auxiliar de configuración. Es una observación de la
sesión administrada. La causa de esa denegación fuera de esa sesión queda
por verificar.

Tras instalar WSL 3.0.5 sin distribución adicional y reiniciar, la
consulta fuera del sandbox confirmó WSL2 como versión predeterminada.
Docker Desktop 4.99.0 se instaló por usuario con backend WSL2. El
motor Linux 29.9.3 respondió con cgroup v2 y la distribución interna
`docker-desktop` en versión 2.

La aceptación real del 17 de noviembre de 2026 usó la imagen local
`sha256:539a1a6c2f1669b6c36612417f9cf70fe28e822095433d8a1453e706396b5f2e`
y obtuvo el hash de verificación
`6c4d7f92d9011c0f3e6ea1a1ebc5ae2016df54d461d788016dd3dc8ce8a84759`.
La base oficial de Python quedó fijada a
`sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`.
El sondeo bloqueó las operaciones externas en el padre y el hijo y
verificó la integridad del testigo del host. Pasaron pytest, Ruff y
la interfaz nativa sintética SMA con causalidad, warmup de 240 velas
y 242 filas UTC. La evidencia queda en `phase-5-4b-real-b1227133`
fuera del repositorio.

### Aceptación del entorno

En Windows con Docker Desktop y motor Linux local, tras aprobar por
separado la preparación del entorno, use una carpeta temporal vacía
como contexto de construcción. Revise el contenido de la imagen y
conserve el ID producido. La construcción obtiene dependencias y se
realiza antes de verificar código generado. El verificador prohíbe
descargas de imágenes durante la evaluación.

```powershell
$docker = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
if (-not (Test-Path -LiteralPath $docker)) {
    $docker = Join-Path $env:ProgramFiles 'Docker/Docker/resources/bin/docker.exe'
}
$engine = 'npipe:////./pipe/dockerDesktopLinuxEngine'
$ctx = Join-Path ([IO.Path]::GetTempPath()) ('tl-pilot-image-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $ctx | Out-Null
& $docker --host $engine build --iidfile (Join-Path $ctx 'image-id.txt') --file scripts/pilot-verification.Dockerfile $ctx
if ($LASTEXITCODE -ne 0) { throw 'No se pudo construir el verificador' }
$env:TRADING_LAB_VERIFICATION_IMAGE = (Get-Content (Join-Path $ctx 'image-id.txt') -Raw).Trim()
$env:TRADING_LAB_REAL_ISOLATION_TEST = '1'
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$evidence = Join-Path $env:LOCALAPPDATA ('TL54B-Sandbox-' + [guid]::NewGuid())
& .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp $evidence tests/unit/test_pilot_verification_container.py -k real_linux
```

La prueba usa archivos sintéticos fuera del expediente y espera pruebas
SMA correctas, warmup 240, causalidad y contrato OHLCV UTC, además del
bloqueo de escritura externa, enlaces, archivo testigo, TCP y DNS tanto
en el padre como en un hijo. La CLI del piloto requiere mantener el
mismo ID de imagen en la sesión.
La carpeta de evidencia conserva `isolation-probe.json`,
`acceptance-checks.json` y las salidas de las comprobaciones.

Los cerrojos coordinan una SQLite compartida; otras bases conservan sus
propios cerrojos.

## Auditoría y consolidación

Desde el checkout de desarrollo, revisar `git status --short` y
`git diff`, incluidos los dos archivos nuevos del mecanismo y sus pruebas.
Ejecutar el grupo dirigido de autorización, ingesta y facturación en SQLite
temporales, Ruff e inspeccionar los hashes del intento real en solo lectura.
La incorporación al checkout principal y la publicación deben autorizarse
por separado. Consolidar únicamente el diff revisado sobre el commit B;
conservar el commit A que ya figura en el intento preparado.

## Comandos futuros en PowerShell

Estos comandos requieren un encargo posterior. Ejecutarlos desde un
checkout verificado del mecanismo de lanzamiento publicado. El primero
registra únicamente la aprobación, después de la confirmación personal.

```powershell
$py = '.\.venv\Scripts\python.exe'
$db = Join-Path $env:LOCALAPPDATA 'TradingLab\GitHubIntake53\queue.sqlite3'
$attempt = 'attempt_8baf5dad9eb44b7eb5005bad86c89809'
& $py -B scripts/authorize_github_pilot.py --db $db approve-launch --attempt-id $attempt --env-file .env
```

Tras recibir una autorización real, inspeccionar el recibo. El lanzamiento
es otra acción y usa el identificador del permiso B.

```powershell
$id = Read-Host 'Authorization ID de LAUNCH_CODEX'
& $py -B scripts/authorize_github_pilot.py --db $db show-launch --authorization-id $id
# Solo en el encargo que autorice el lanzamiento real.
# & $py -B scripts/authorize_github_pilot.py --db $db launch --authorization-id $id --env-file .env
# Solo tras verificar parada e identidad de todos los procesos.
# & $py -B scripts/authorize_github_pilot.py --db $db close-launch --authorization-id $id --confirm-stopped --reason 'Motivo verificado'
```
