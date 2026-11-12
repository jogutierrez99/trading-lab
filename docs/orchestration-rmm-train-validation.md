# RMM 4H · comparación BASE de TRAIN y VALIDATION

Este recorrido manual continúa el expediente existente del filtro de entradas de
28 días. Conserva la ficha y su hash. El coordinador reconoce la etiqueta exacta
`StudyBackend / lab.py` de la ficha sellada como `StudyBackend v1 / lab_experiment_v1`.
La revisión explícita y el estado de cola siguen siendo obligatorios.

El plan local `comparison-train-validation.json` liga la tarea y candidata a
`risk_managed_momentum_v1_btc_eth_4h`, versión de estrategia 1.0.0, commit y
hashes de configuración, código, aplicación y riesgo. La variante usa
exclusivamente su entrega `IMPLEMENTED_VERIFIED`. Se genera el YAML de las dos
ramas desde la misma configuración. Solo se habilita la copia de ejecución de
la variante. Los dos runs nativos tienen IDs y ledgers independientes.
La copia aislada conserva el commit base y registra por separado los hashes de
los tres archivos del runner local que habilitan la selección de tramos. Ambas
ramas usan esa misma copia del runner y el motor del commit congelado.

El plan tiene 24 casos BASE. Cada rama usa BTCUSDT y ETHUSDT a 4 h, tres
modos, una configuración y dos ventanas con las mismas 1.000 barras de
precarga, sizing, costes y supuestos de ejecución. TRAIN cubre
`2023-06-04T00:00:00Z` a `2024-07-01T00:00:00Z`. VALIDATION termina el
`2025-01-01T00:00:00Z`, con finales exclusivos. El runner conserva su
comportamiento ordinario cuando se omite la selección explícita.

El coordinador contrasta los hashes de los Parquet fuente completos y extrae
los intervalos permitidos con un filtro por timestamp. La lectura de bytes
para la integridad puede abarcar el archivo completo. El proceso del runner
solo recibe copias auditadas que terminan antes de TEST. El preflight contrasta
la configuración de ambas ramas y compara sus señales contra el baseline y el
filtro causal de referencia. Comprueba el signo, los 29 cierres diarios UTC
completos y consecutivos, el límite temporal estricto y la paridad de salidas.

`comparison.json` presenta métricas emparejadas y delta de Sharpe, conserva
métricas indefinidas como nulas y queda sellado por el recibo de ejecución.
Quedan pendientes TEST, costes ADVERSE y los controles SMA28 y aleatorio. La
comparación de BASE por sí sola no resuelve la falsación completa. La auditoría
ordinaria puede recibir la ejecución de la variante por su recibo nativo. El
informe emparejado de ambas ramas es un artefacto aparte.

## PowerShell

Ejecutar cada bloque por separado después de revisar su entrada. Los bloques
de preparación, implementación y ejecución cambian el estado del expediente.

```powershell
Set-Location 'C:\Users\joshu\OneDrive\Escritorio\WEBS\Back_testing\trading-lab'
$py = '.\.venv\Scripts\python.exe'
$folder = 'C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85\rmm-4h-intake-d12ed4380140'
$db = Join-Path $folder 'queue.sqlite3'
$task = 'task_ee9ba7da2262492f990ea59d77d94cb5'
$plan = Join-Path $folder 'comparison-train-validation.json'
$scope = Get-Content -Raw -Encoding utf8 $plan | ConvertFrom-Json
$scope | ConvertTo-Json -Depth 12
& $py -B scripts/orchestrator.py --db $db show $task
if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar la tarea' }
if ((git rev-parse HEAD) -ne $scope.comparison.baseline_commit) { throw 'HEAD difiere del baseline fijado' }
& $py -B scripts/orchestrator.py doctor
if ($LASTEXITCODE -ne 0) { throw 'Diagnóstico Codex bloqueado' }
```

Tras revisar la ficha y aceptar su alcance, crear el plan de implementación y
preparar el intento. Los artefactos se guardan en una ruta local corta.

```powershell
$artifactRoot = Join-Path $env:LOCALAPPDATA 'TLRMM'
New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
$implPlan = Join-Path $artifactRoot 'implementation-plan-reviewed.json'
@{
  schema_version = '1.0'
  operation = 'NEW_STRATEGY'
  target = 'rmm_4h_momentum_28d_filter_v1'
  specification_reviewed = $true
  review_note = 'Implementar solo el filtro de entradas sellado como subclase del RMM congelado. Reutilizar salidas, sizing y parámetros. Copiar el perfil RMM de 4h con solo nombre y enabled=false distintos. Probar DatetimeIndex UTC, frontera de medianoche estricta, gaps, recuperación, ambos signos, warmup y causalidad por prefijos. Sin backtests.'
  max_wall_seconds = 900
  check_timeout_seconds = 60
} | ConvertTo-Json | Set-Content -Encoding utf8 $implPlan
$raw = & $py -B scripts/orchestrator.py --db $db prepare $task --repo . --plan $implPlan --artifacts (Join-Path $artifactRoot 'i')
if ($LASTEXITCODE -ne 0) { throw 'Preparación bloqueada' }
$attempt = $raw | ConvertFrom-Json
if ($attempt.status -ne 'PREPARED') { throw 'Se esperaba PREPARED' }
Get-Content (Join-Path $attempt.root 'request.json')
Get-Content (Join-Path $attempt.root 'prompt.txt')
```

Lanzar Codex solo tras revisar esos artefactos. El comando vuelve con el estado
de implementación y el enlace al recibo verificado.

```powershell
$raw = & $py -B scripts/orchestrator.py --db $db run $attempt.attempt_id
if ($LASTEXITCODE -ne 0) { throw 'Implementación no verificada, revisar el intento' }
$implementation = $raw | ConvertFrom-Json
if ($implementation.status -ne 'SUCCEEDED') { throw 'Se esperaba SUCCEEDED' }
```

Si el lanzador de Windows falla con `registered Core launch requires an installed
app`, inspeccionar el intento antes de reconciliar. En este equipo, la prueba sin
modelo con MXC pudo leer y escribir dentro del worktree y rechazó una escritura
fuera. Después de confirmar que el proceso anterior terminó y preparar una
reparación con el mismo plan, seleccionar MXC explícitamente en `run` con
`--windows-sandbox mxc` y la ruta verificada en `--codex-executable`.
La opción conserva `workspace-write`, el perfil `:workspace`, la red
deshabilitada para comandos y la política de aprobación `never`.

Preparar, validar y ejecutar la comparación después de la revisión del recibo.

```powershell
$raw = & $py -B scripts/orchestrator.py --db $db prepare-execution $implementation.attempt_id --plan $plan --artifacts (Join-Path $artifactRoot 'e')
if ($LASTEXITCODE -ne 0) { throw 'Reserva de la comparación bloqueada' }
$execution = $raw | ConvertFrom-Json
$raw = & $py -B scripts/orchestrator.py --db $db validate-execution $execution.execution_id
if ($LASTEXITCODE -ne 0) { throw 'Validación bloqueada' }
$validation = $raw | ConvertFrom-Json
if ($validation.report.total_backtests -ne 24 -or ($validation.report.periods -join ',') -ne 'train,validation') { throw 'Alcance inesperado' }
& $py -B scripts/orchestrator.py --db $db run-execution $execution.execution_id
if ($LASTEXITCODE -ne 0) { throw 'Consultar estado y recibo antes de reintentar' }
& $py -B scripts/orchestrator.py --db $db execution $execution.execution_id
Get-Content -Raw -Encoding utf8 (Join-Path $execution.root 'comparison.json')
```

Un estado `UNKNOWN` exige reconciliación con el recibo y la identidad del
proceso antes de continuar. La preparación inicial se comprobó en una copia
temporal de la tarea original y con datos sintéticos.

## Verificación

La copia de la SQLite y un checkout temporal recreado desde HEAD permitieron
llegar a `PREPARED` con los IDs y el hash originales. El literal desconocido
se rechazó. Las regresiones sintéticas comprobaron 24 casos, ausencia de TEST,
rechazo de evidencias cruzadas y bloqueo ante riesgo divergente.

Pasaron 130 pruebas del grupo de integración y contratos, 134 pruebas del
grupo unitario del lab, contratos, ingesta y auditoría, y la repetición final
de las dos pruebas dirigidas RMM. Los grupos comparten algunas pruebas.
Ruff y la comprobación de formato pasaron.

La ejecución histórica autorizada `execution_1de92025fc2a4a159ee1dc46c579370c`
terminó `SUCCEEDED` tras el segundo intento, con 12 casos nativos completos
por rama y `comparison.json` sellado por el recibo. El lanzamiento inicial
quedó registrado como fallo de arranque de PowerShell. El recorrido terminó
en el informe emparejado.
