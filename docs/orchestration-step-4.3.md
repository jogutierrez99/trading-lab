# Paso 4.3 — ejecutor determinista manual (2026-11-04)

**Estado actual tras autorización posterior:** el piloto corregido1.0.1 completó el
circuito con identidad/recibo manuales nuevos y3 backtests sintéticos COMPLETE.
[Cierre técnico y conservación del3/3](pilot-native-index-repair-applied.md).
El diagnóstico inicial y las ejecuciones anteriores se conservan en esta guía.

Implementado y probado con el runner real en datos sintéticos. **El piloto de4.2 está
bloqueado por incompatibilidad de su estrategia con el DataFrame nativo**. No se ha
reparado esa estrategia, sustituido el motor ni declarado completado ese backtest.
La ejecución positiva descrita al final usa una candidata fixture compatible,
identificada expresamente como prueba de software, no el piloto real de Codex.

## Arquitectura y contratos

`scripts/orchestrator.py` conserva4.1/4.2 y añade prepare-execution,
validate-execution, run-execution, execution y reconcile-execution. Python determinista:
no doctor/login/modelo, descarga, scheduler, optimización, Telegram, OKX o publicación.

`ExecutionPlan1.0` es la entrada revisada del operador. Fija YAML original y SHA256,
protocolo exacto `StudyBackend v1 / lab_experiment_v1`, scope, autorización explícita
de todos los periodos declarados, nota de revisión, permiso para habilitar únicamente
la copia, datasets/fingerprints/hashes/procedencia y límites obligatorios.
Rechaza campos desconocidos, comandos arbitrarios y versiones no admitidas.

`ExecutionRequest1.0` generado fija execution/task/candidate/implementation IDs,
recibo IMPLEMENTED_VERIFIED y hash, request4.2/hash, commit base, archivos finales,
operator_format_repair, configuración/cambios de adaptación, inputs y runtime
archivados/hash, workspace, resultados y plan completo. Request y controles se sellan
en SQLite. La identidad final usa los bytes posteriores al formato, sin atribuir esa
corrección al ModelDelivery original.

Se comprueban los hashes del recibo y evidencia4.2, identidad, checks originales,
request/controls, archivos reales frente al baseline, y, si existe reparación, archivos
antes/después y AST. La implementación debe seguir SUCCEEDED/IMPLEMENTATION_READY y
detenida. Los cambios posteriores bloquean preparación/validación/ejecución.

El workspace de ejecución es un archivo del commit base **sin puntero .git**, con la
entrega verificada superpuesta. Se contrasta con el baseline4.2 salvo el puntero Git.
No comparte metadatos Git ni escribe en el worktree de implementación. Se archivan
también el bridge y módulos del coordinador necesarios para ejecutar el worker.
Python `-I -B` importa quant_lab desde la copia congelada; no usa el motor editable
del checkout principal por accidente. No hay motor alternativo.
El provenance nativo puede registrar Git revision/status como null por tratarse de
un snapshot sin .git: se conserva ese desconocido, y el request/recibo de ejecución
aporta el commit base y los hashes efectivos. No se inventa un commit de resultados.

## Configuración, datos y validación

Se reutilizan `lab_schema.Experiment`, `config.load_yaml/UniqueKeyLoader`,
`lab_runner.prepare(full=False/True)`, auditores de bundles, `lab_runner.window`,
registro y contrato nativo de señales. `run` delega en `lab_runner.run(output=...)`,
StudyBackend, ExperimentStore y reporting originales, sin cambiar sus bytes/reglas.

La copia contiene `execution-config/{experiment,app,strategy,risk}.yaml`. Solo se
reubican referencias, se fija dataset_id y se habilita el perfil de esa copia cuando
el operador lo autoriza. `adaptations.json` y los YAML/hash registran la diferencia;
los originales, incluido el perfil deshabilitado del piloto, permanecen intactos.
App/risk/perfil proceden del árbol4.2 verificado. Para NEW_EXPERIMENT se exige el YAML
entregado; para NEW_STRATEGY el operador aporta un experimento con ID/perfil correctos.

Cada dataset requiere ruta absoluta, dataset_id, SHA256 de manifest y candles.parquet,
tipo SYNTHETIC/LOCAL_HISTORICAL, nota de procedencia y archivos de evidencia fijados
por SHA256. Se leen en su ubicación original, no se copian al snapshot ni a Git.
Se verifica disponibilidad, identidad, integridad, OHLCV, cobertura y warmup con los
validadores existentes. La procedencia declarada sigue siendo responsabilidad de la
revisión humana: hashes prueban identidad/integridad, no autenticidad externa por sí solos.
La fixture conserva fórmula, código generador archivado y declaración de ausencia de
observaciones de mercado. No se disfrazan datos sintéticos como historial Binance.

FULL no ejecuta señales. El piloto demostró que eso no basta para detectar una
incompatibilidad del DataFrame:4.3 añade una prueba explícita de generate_signals
sobre warmup+dos velas del prefijo TRAIN, usando window/config/registro nativos.
No ejecuta fills ni backtest ni selecciona parámetros. Es una comprobación de interfaz,
no una prueba completa de causalidad ni validación económica. run repite el preflight.

Se admiten únicamente OHLCV spot/synthetic y bundles ordinarios, una configuración
fija de parámetros, hasta dos datasets. Sin grids/selección automática. Adapters
perpetual, MTF/quarter y runners dedicados se bloquean; no se esquivan sus guards.

El runner ordinario ejecuta **TRAIN, validation y TEST**. No existe TRAIN_ONLY en este
adaptador: se rechaza ese scope, sin renombrar periodos ni alterar el protocolo. La
prueba usa SYNTHETIC_TECHNICAL; los tres nombres nativos contienen solo datos generados.
DECLARED_RESEARCH_PERIODS exige autorización explícita para todos los periodos del YAML;
no es permiso para consumir un holdout reservado durante una comprobación técnica.
El [ensayo RMM posterior](orchestration-rmm-train-validation.md) incorpora un scope
específico para dos ramas BASE con TRAIN y VALIDATION. Mantiene el comportamiento
ordinario descrito aquí para el resto de planes.

## Límites y reserva

Límites obligatorios: max_wall_seconds (1..3600), validation_timeout_seconds (1..300),
max_backtests (1..100), max_candles (1..1000000), max_dataset_bytes (1..1000000000).
Antes de cargar datos se limita volumen de bytes y filas Parquet; el contador FAST
nativo limita el número de backtests antes de FULL/señales. El límite de duración
abarca el worker de run, incluyendo su preflight y reporting; validación tiene su
timeout separado. Los números no constituyen caps CPU/RAM/disco de sistema operativo.

SQLite de orquestación migra v2→v3 transaccionalmente, añadiendo únicamente executions,
su FK a tarea/implementación, enlace retry_of y UNIQUE parcial global para
PREPARED/RUNNING/UNKNOWN. BEGIN IMMEDIATE y el mismo lock OS de4.2 coordinan ambas
capas;4.2 no lanza un modelo mientras hay ejecución reservada/incierta. Se mantiene
un solo trabajo pesado activo en **esa SQLite**: usar una única base operativa.

La reserva y su evento son atómicos; un error de evento revierte la inserción.
No hay reintentos automáticos ni reinicio de filas terminales. La misma intención
ya registrada se rechaza; una repetición de fallo confirmado requiere --retry-of,
manteniendo implementación/recibo/plan exactos y creando otro ID/directorio.
No se permite relanzar nada mientras exista UNKNOWN, incluso con otro plan.

Estados de ejecución: PREPARED → RUNNING → SUCCEEDED / FAILED / TIMED_OUT;
preflight inválido → BLOCKED; interrupción/resultado no contrastable → UNKNOWN.
execution detecta dueño desaparecido sin inferir éxito/fallo. reconcile-execution
exige confirmación de procesos detenidos y motivo; verify solo lee evidencia y repite
contrastes, **no** el backtest. Sin process-result/outcome suficiente conserva UNKNOWN.
failed/cancel registra decisión manual. Se puede cancelar una reserva PREPARED.

Windows conserva Job Object kill-on-close, timeout y terminación de descendientes;
POSIX conserva grupos y sus límites documentados en4.2. Los workers ejecutan código
local revisado; no se añade un sandbox filesystem/red para código Python hostil.
No se presenta este ejecutor como aislamiento por archivo ni como control del sistema
frente a plugins no confiables. El sandbox de Codex4.2 no se modifica ni se usa en4.3.

## Recibo y significado de estados

BacktestExecutionReceipt1.0 registra IDs, request/implementación/commit/archivos finales,
reparación, comando real permitido, tiempos/retorno/timeout, resultado nativo, run_id,
artefactos y SHA256. Contrasta número esperado, outcome COMPLETE, ledger completed y
hashes de result.json antes de SUCCEEDED. Errores/timeout conservan un recibo de fallo
cuando hay evidencia confirmada; una interrupción queda pendiente de reconciliación.

No se reescriben outcome, ledger, summary ni etiquetas nativas. Las métricas y filtros
siguen en los artefactos del laboratorio. economic_assessment=NOT_ASSESSED y
demo_authorized=false son independientes del éxito técnico. Candidata y tarea4.2
mantienen sus estados de implementación; backtests se consultan en executions.
Los eventos anexan execution_id/status sin promover metadata ni clasificación científica.

## Comandos exactos en el portátil

Desde la raíz del repositorio, con Python instalado y `pip install -e ".[dev]"` hecho:

```powershell
$db = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3'
$impl = 'attempt_cb2c94564a6f464f95faaeee58bae9a5'
$local = Join-Path $env:LOCALAPPDATA ('TradingLab\orchestration\step43\' + [guid]::NewGuid().ToString('N'))

# Prepara únicamente datos sintéticos y el plan, sin backtest ni modelo.
python scripts/prepare_execution_smoke.py $impl --db $db --output (Join-Path $local 'inputs')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar la ficha técnica' }
$plan = Join-Path $local 'inputs\execution-plan.json'
Get-Content $plan

# Revisar plan, límites, scope y hashes antes de reservar.
$prepared = python scripts/orchestrator.py --db $db prepare-execution $impl --plan $plan --artifacts (Join-Path $local 'executions') | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $prepared.status -ne 'PREPARED') { throw 'Preparación bloqueada' }
$exec = $prepared.execution_id
python scripts/orchestrator.py --db $db validate-execution $exec
if ($LASTEXITCODE -ne 0) { throw 'Validación bloqueada: leer diagnóstico; no ejecutar' }

# Solo con una implementación compatible y validación FULL/interfaz aprobada:
python scripts/orchestrator.py --db $db run-execution $exec
python scripts/orchestrator.py --db $db execution $exec
python scripts/orchestrator.py --db $db show 'task_7c894d7e4dca4f24a164632a703d5d5d'
```

**Con el $impl actual, la secuencia se detiene en validate-execution por timestamp.**
No quitar ese guard ni ejecutar lab.py directamente para esquivarlo. Para otro
experimento compatible, aportar un ExecutionPlan1.0 con sus pines reales en --plan;
el helper sintético no es un generador de investigación histórica.
Usar AppData o disco local fuera de OneDrive; --db y --artifacts son explícitos.
El ejemplo usa la ruta canónica del piloto: los alias AppData pueden redirigirse
desde la aplicación empaquetada de Windows y no equivaler a otra terminal.

Consultas del diagnóstico ya guardado (no ejecutan backtests):

```powershell
python scripts/orchestrator.py --db $db execution execution_41c1fdbe9b9a41a292a46b67ec7168a0
python scripts/orchestrator.py --db $db execution execution_4dc719fb9102428fa1f5a357506f07fd
```

Recuperación manual, únicamente después de inspeccionar procesos y artefactos:

```powershell
python scripts/orchestrator.py --db $db reconcile-execution $exec --outcome verify --confirm-stopped --reason 'Proceso y descendientes detenidos; contrastar evidencia existente'
# Si se confirma fallo sin evidencia suficiente, elegir failed en lugar de verify.
# Tras ese fallo confirmado, --retry-of crea otro directorio; revisar de nuevo antes de run.
python scripts/orchestrator.py --db $db prepare-execution $impl --plan $plan --artifacts (Join-Path $local 'executions') --retry-of $exec
```

No ejecutar sucesivamente esas opciones como una receta automática.

## Verificación y evidencias

148 tests distintos aprobados en grupos; no suite completa:

- Conservación4.1/4.2 y validadores lab/config:110 aprobados,122.97s.
- Contrato4.3:18 aprobados,0.32s.
- Ejecutor inicial:16 aprobados,262.78s.
- Identidad con reparación de formato:1 aprobado,23.36s (caso nuevo).
- Atomicidad/cancelación y repetición de recuperación/fallo/timeout:5 aprobados,91.08s
  (dos casos nuevos; tres repeticiones).
- Tras el hallazgo del piloto, runtime archivado y contrato de índice:6 aprobados,
  118.44s (un caso nuevo; cinco repeticiones). Total4.3:20 integración+18 contrato.

Ruff global, formato global, pip check y git diff --check correctos. Primer
setup de test necesitó core.longpaths=true **solo en su repo temporal**; primer
contrato con tmp por defecto no pudo crear el temporal del sandbox. Se repitieron
con temporales explícitos permitidos. No se cambiaron asserts ni límites operativos.

```powershell
python -m pytest tests/unit/test_execution_contracts.py tests/integration/test_execution_orchestration.py -q
python -m pytest tests/unit/test_orchestration.py tests/integration/test_codex_orchestration.py tests/unit/test_lab.py tests/unit/test_config.py -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
git diff --check
```

En este entorno se usó -p no:cacheprovider y --basetemp en la carpeta de visualizaciones
de esta conversación (pytest43-*). Ningún test usa un holdout histórico reservado.

Ejecución positiva **real del runner**, dentro del test de integración, con candidata
fixture compatible, sin simular procesos/backtests:

- execution_41ee3fec331b4c9db071c055698df1a1;
- run_id20261103T235017Z-761b39197164;
- SUCCEEDED, outcome COMPLETE,3 backtests,0 fallidos;
- Native filters:3 rechazados por closed_trades:min=1,0 supervivientes;
-244 velas sintéticas,1 configuración, máximo3 backtests/120s/1000000 bytes;
- Recibo SHA256:ced9683136996e4d3360482d131a7e0a45aa27bd865195a629fa7aa4bc82fd9d.

Evidencia local: tl43-positive-technical-evidence.json, bajo
C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/.
Incluye ruta exacta del recibo. Es prueba de software; no prueba rentabilidad del
piloto, ni una implementación nueva atribuida a Codex.

### Piloto4.2: bloqueo concreto conservado

Se respaldó SQLite v2 antes de migrar a v3 en
C:/Users/joshu/AppData/Local/TL43/b75804/orchestrator-before-v3.sqlite3.
Se comprobó que candidates/tasks/attempts/submissions y el prefijo de eventos4.1/4.2
permanecen idénticos, integrity_check=ok, sin FK inválidas.

La primera orden manual alcanzó el runner con la entrega4.2 y reparación identificadas:

- ejecución execution_41c1fdbe9b9a41a292a46b67ec7168a0, estado FAILED;
- run_id20261103T234645Z-4f43ff68ecc2, outcome FAILED,0 backtests completados;
- error literal: `'DataFrame' object has no attribute 'timestamp'`;
- módulo del piloto prepare_features, línea33: usa candles.timestamp;
- el runner nativo entrega OHLCV con DatetimeIndex y sin esa columna;
- límites3 backtests/244 velas/120s, validación60s,1000000 bytes;
- recibo SHA256:75fb90ac4e651d435bc39b9ed5bdebf96af85852e2d976fe6381bcca50cc547d.

Se preservaron stderr, outcome/ledger/recibo y runtime anterior. Tras añadir el probe,
una nueva preparación y **solo validación manual**, sobre el mismo experimento/dataset,
registró execution_4dc719fb9102428fa1f5a357506f07fd en BLOCKED con el mismo motivo,
sin crear results ni lanzar otro backtest. El generador original se conservó por hash
al cambiar el adaptador; la revisión del nuevo plan lo declara.

Reporte: C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/tl43-pilot-diagnosis.json.
Datos y worktree4.2 intactos, reparación de formato incluida en la identidad, cero
procesos registrados vivos y cero trabajos pesados activos. No hay cambios al motor,
estrategias existentes, forward ni resultados previos. Sin modelos, descargas, TEST
histórico, Telegram, OKX, procesos programados, push ni merge.

## Qué falta para cerrar el circuito del piloto

Una implementación revisada compatible con el contrato nativo de velas, con sus tests
de integración y **nuevo recibo4.2/identidad**; no editar retrospectivamente la entrega
verificada ni atribuir una reparación lógica a repair-format. No se autorizó aquí una
reparación automática de estrategia. Después, nuevo plan revisado y ejecución técnica
pequeña con FULL/interfaz válidos, outcome COMPLETE, ledger/hashes/recibo contrastados,
sin consumo de holdout y con procesos terminados. No hay permiso para avanzar4.4,
investigación masiva o demo. El ejecutor está implementado; ese cierre del piloto
sigue explícitamente bloqueado.

Actualización posterior: [propuesta de reparación nativa](pilot-native-index-repair.md),
con diff mínimo, pruebas del runner real y auditoría del presupuesto3/3. Aún no es
una nueva entrega aceptada. El probe se comparte ahora con la verificación de futuras
implementaciones4.2, sin recalificar recibos históricos.

Archivos4.3: execution.py, execution_contracts.py, execution_inputs.py,
execution_worker.py, execution_smoke.py; scripts run_coordinated_backtest.py y
prepare_execution_smoke.py; dos archivos de tests nuevos. Modificados store/migration,
CLI y guards de implementation.py; test de migración4.2 espera la versión vigente.
AGENTS y documentación actualizados. Se preservan los cambios4.1/4.2 previos sin commit.
