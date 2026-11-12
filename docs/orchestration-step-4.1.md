# Coordinador local — paso 4.1

Este documento conserva el alcance y la evidencia de4.1. El
[paso4.2](orchestration-step-4.2.md) amplía el mismo coordinador y migra SQLite a v2;
los contratos/comandos manuales de ingesta siguen disponibles.

Implementado el 2026-11-03: ingesta **manual**, validación de ficha, deduplicación,
registro y consulta. No es el pipeline multiagente completo. No llama a modelos,
Codex, Telegram, OKX, runners ni procesos programados. No importa `quant_lab`.

## Ejecutar en el portátil

Desde la raíz del checkout, con Python >=3.12:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# Base activa local, fuera de OneDrive; también es el default Windows.
$env:TRADING_LAB_ORCHESTRATOR_DB = Join-Path $env:LOCALAPPDATA 'TradingLab\orchestration\orchestrator.sqlite3'
python scripts/orchestrator.py --help
python scripts/orchestrator.py validate examples/orchestration/manual_valid.json
python scripts/orchestrator.py validate examples/orchestration/manual_incomplete.json
# El segundo termina con código 2 y detalles de campos ausentes; no escribe SQLite.

python scripts/orchestrator.py register examples/orchestration/manual_valid.json
python scripts/orchestrator.py register examples/orchestration/manual_valid.json
python scripts/orchestrator.py list
python scripts/orchestrator.py show manual_example_001
```

Primera alta: `created=true`, `duplicate=false`, `candidate_id=cand_<uuid>`,
`task_id=task_<uuid>`, `status=HYPOTHESIS_READY`. La repetición conserva ambos IDs,
devuelve `created=false`, `duplicate=true` y registra un evento de reenvío.
Cerrar la terminal y volver a consultar conserva el expediente. Cada invocación es
un proceso nuevo. `show` acepta candidate ID, task ID o cualquier hypothesis ID
registrado, incluidos los IDs alternativos deduplicados. `list` incluye estado de
candidata y tarea. `show` devuelve ficha original, hashes, envíos y eventos ordenados.
Las salidas son JSON; éxito=0, error=2. Un duplicado es éxito idempotente, no un error.

Ejemplo de bloqueo manual y consulta del historial:

```powershell
$candidate = (python scripts/orchestrator.py show manual_example_001 | ConvertFrom-Json).candidate_id
python scripts/orchestrator.py transition $candidate --from HYPOTHESIS_READY --to BLOCKED --reason 'Falta verificar el dataset'
python scripts/orchestrator.py show $candidate
python scripts/orchestrator.py transition $candidate --from BLOCKED --to HYPOTHESIS_READY --reason 'Aclaracion registrada; pendiente de revision humana'
```

No se requiere `init`: register/list/show/transition inicializan una base vacía
automáticamente. `validate` no crea ni abre la base. Se crean directorios padre.
No se modifica `.env`. Para persistir la ubicación en futuras terminales:

```powershell
[Environment]::SetEnvironmentVariable('TRADING_LAB_ORCHESTRATOR_DB', (Join-Path $env:LOCALAPPDATA 'TradingLab\orchestration\orchestrator.sqlite3'), 'User')
```

Precedencia: `--db RUTA` > `TRADING_LAB_ORCHESTRATOR_DB` > default local.
La opción global `--db` va **antes** del subcomando. Las rutas relativas se resuelven
contra el directorio actual. En Linux/macOS el default es
`${XDG_STATE_HOME:-~/.local/state}/TradingLab/orchestration/orchestrator.sqlite3`.
Si PowerShell no permite activar, sustituir `python` por `.\.venv\Scripts\python.exe`.

Una ruta explícita puede estar sincronizada; la CLI no detecta todos los proveedores
de sincronización. Elegir un disco local estable, nunca el SQLite de experimentos
ni un journal forward. El marcador SQLite rechaza otras aplicaciones/versiones.
SQLite y acompañantes `.sqlite3-*` están ignorados por Git. Backup manual: con todas
las invocaciones cerradas, copiar el fichero a otra ubicación y verificar la copia
con `--db RUTA_COPIA list` / `show`. No se ha implementado un servicio de backups.

## Contrato único

La ficha manual es `HypothesisManifest` v`1.0`, en
`src/trading_lab_orchestration/contracts.py`. No existe un segundo schema de ficha.
No se encontró una ficha previa adjunta aparte del ZIP ni una implementación anterior
en el árbol inspeccionado. El ejemplo conceptual `candidates[]` del Investigador es
un sobre de propuestas, no un segundo contrato aceptado por esta CLI.

Objetos estrictos Pydantic: rechazan campos desconocidos, coerción de bool/números,
versión no soportada, texto vacío, JSON con claves repetidas y valores no finitos.
Fechas ISO UTC explícitas, periodos con fin exclusivo ordenados y sin solapamientos;
costes `*_pct` en porcentajes, nunca fracciones. Campos obligatorios del maestro:
identidad/versión/fecha, hipótesis/fundamento/fuentes, datos, señales, parámetros,
ejecución, evaluación, novedad, limitaciones y cómputo esperado.

Los modos no soportados requieren entradas/salidas `null` y declaración explícita.
Spot requiere SHORT_ONLY no soportado y funding NOT_APPLICABLE; synthetic exige
NOT_MODELLED; perpetual exige REQUIRED. Entrada NEXT_OPEN y disponibilidad
CANDLE_CLOSE. Grids acotados al límite declarado, sin ejecutarlos. Una hipótesis
sin parámetros utiliza `parameters: {}` y combinación única. El plan incluye
holdout consumido/desconocido/declarado no observado, walk-forward, falsación,
métrica primaria y diagnóstico de robustez. Conteos desconocidos son `null`.

El resultado acredita **estructura y coherencia básica**, no causalidad, suficiencia
de las reglas, calidad de bibliografía, integridad de datos, compatibilidad efectiva
con un runner ni validez económica. Las reglas/stop/sizing/funding/gaps se describen;
no se evalúan como código. `source_refs.reference`, `dataset_refs` y `runner_protocol`
son referencias descriptivas: no se resuelven, abren ni ejecutan. Las declaraciones
MANUAL/MANUALLY_VERIFIED/UNOBSERVED_DECLARED no son verificaciones del coordinador.
Datos pendientes pueden registrarse para revisión; ninguna entrada autoriza actuar.

## Estados implementados

El estado de entrada del manifiesto solo puede ser `PROPOSED`. Una alta válida
registra los eventos de candidatura `null → IDEA_RECEIVED → HYPOTHESIS_READY`
y crea una tarea `MANUAL_REVIEW`, `PREPARE_ONLY`, `QUEUED`. Ambos pasos de admisión
son una sola transacción: no hay candidatas parcialmente registradas.
HYPOTHESIS_READY significa contrato admitido para revisión. No significa
GATE_RESEARCH_APPROVED, READY_FOR_IMPLEMENTATION ni aprobación de desarrollo.

| Estado candidatura | Destinos permitidos por CLI | Estado tarea asociado |
|---|---|---|
| HYPOTHESIS_READY | BLOCKED, CANCELLED, ARCHIVED | QUEUED |
| BLOCKED | HYPOTHESIS_READY, CANCELLED, ARCHIVED | BLOCKED |
| CANCELLED | ARCHIVED | CANCELLED |
| ARCHIVED | Ninguno | CANCELLED |

El estado de tarea mostrado en la última columna corresponde al estado de candidatura
de esa fila. ARCHIVED archiva el expediente y cancela el trabajo pendiente, sin borrar
historia. `--from` exige el estado actual; una petición obsoleta falla sin cambios.
Motivo obligatorio. La transición cambia candidatura/tarea/eventos atómicamente;
si el estado de tarea no cambia, no se inventa un evento de cambio.
Actor local `manual_cli`, sin autenticación multiusuario. No hay un worker ni una
operación de aprobación. El resto de estados del maestro queda solo diseñado.

Entradas inválidas devuelven errores de validación y no se admiten ni crean tareas.
BLOCKED se reserva para expedientes ya admitidos; no se fabrica un manifiesto parcial.
Los estados no sustituyen PASS, RESEARCH_PASS, NEAR_PASS ni metadata de estrategias.

## SQLite, deduplicación y atomicidad

Solo cuatro tablas, todas usadas:

- `candidates`: identidad canónica, ficha JSON normalizada, SHA256 completo,
  fingerprint científico, estado y timestamps UTC.
- `tasks`: una revisión manual por candidata, clave idempotente
  `<candidate_id>:manual_review:v1`, tipo/modo/estado y timestamps.
- `submissions`: hypothesis ID único como clave de reintento, snapshot y SHA256 de
  cada envío distinto, asociado a la candidata canónica. Permite preservar un ID
  alternativo y su metadata sin crear otro trabajo.
- `events`: historial append-only de admisión, cambios y reenvíos; entidad, estados,
  actor, motivo, UTC y payload JSON con SHA256. Los reintentos idénticos generan
  eventos adicionales, no tareas adicionales.

FK, UNIQUE y CHECK en SQLite; transacciones `BEGIN IMMEDIATE`, timeout de bloqueo
15 segundos y synchronous FULL. Inicialización transaccional con `application_id=TLO1`
y `user_version=1`; una base ajena o versión futura se rechaza sin migrarla. Esta
entrega implementa la migración inicial 0→1, no migraciones futuras especulativas.
No cambia journal mode a WAL; usa el journal de rollback ordinario de una base nueva.
Las lecturas de expediente utilizan una única instantánea transaccional.

Snapshot canónico: claves JSON ordenadas, UTF-8 y separadores estables. Mismo
hypothesis ID + mismo snapshot devuelve los IDs existentes. Mismo ID + contenido
distinto es conflicto, incluso si solo cambia metadata; usar ID nuevo para una revisión.
Un ID nuevo con fingerprint existente se guarda como envío de la misma candidata.
El snapshot de la candidata nunca se sobrescribe ni un reenvío reactiva una tarea
cancelada/bloqueada. Los snapshots y eventos tienen triggers contra actualizaciones;
esto no sustituye permisos de filesystem ni firma criptográfica frente al dueño del DB.

El fingerprint incluye `schema_version`, `market_hypothesis`, `data_requirements`,
`signal_spec`, `parameter_space`, `execution_assumptions`, `evaluation_plan` completos.
Excluye ID, fecha, título, researcher_version, rationale, fuentes, novelty,
limitations, expected_compute_class, requires_new_strategy_code y status.
Por tanto, cambiar costes/datos/periodos/reglas crea una variante; cambiar título
no duplica trabajo. Mantiene orden de listas y texto exacto tras quitar espacios
exteriores. No detecta paráfrasis, equivalencias matemáticas ni coincidencias con
experimentos históricos: requiere revisión humana y futura búsqueda explícita.

## Contraste del ZIP y decisiones

Inspección inicial: rama `main`, HEAD
`131ffaa101f7d04d81dcb47936142802ebba0a4b`, árbol limpio.
ZIP de Downloads SHA256:
`5c86f1a4e3f3555d26307d1180f9be9cd22653da5ba12e3975d5706c7ad53045`.
Se leyeron los cuatro documentos como especificación de diseño, no como órdenes
para desplegar agentes o detener esta entrega en una propuesta documental.
La petición actual autoriza expresamente el añadido y el ajuste mínimo de AGENTS.

| Documento del ZIP | Contraste y decisión |
|---|---|
| trading_lab_arquitectura_multiagente_maestra_v1.md | Referencia de contrato/estados; aplicar solo admisión manual. No crear las 12 tablas conceptuales, envelopes, aprobaciones, budgets o workers sin uso. El maestro deja ubicación/nombres por decidir. |
| trading_lab_investigador_cuantitativo_v1.md | Su ejemplo incompleto es ilustrativo; no aceptarlo como ficha lista. Formalizar HypothesisManifest del maestro, con PROPOSED como declaración y estado de candidatura independiente. VectorBT no es dependencia actual: prevalece StudyBackend v1 y sus adaptadores reales. |
| trading_lab_agente_02_desarrollador_cuantitativo_v1.md | Rol lógico futuro; no conectar Codex ni generar ImplementationRequest. Revisión manual QUEUED no equivale a desarrollo autorizado. Las cuatro skills existentes permanecen intactas. |
| trading_lab_agente_03_auditor_cuantitativo_v1.md | No crear auditor, veredictos ni evidencia ficticia. Conservar distinción entre clasificación nativa, estado operativo y permiso humano. |

La prohibición general de AGENTS se sustituye por excepción acotada para este paso;
se conserva un agente de implementación y todas las protecciones previas. No se
aplica la propuesta de precedencia del anexo como nueva política normativa.
No se crean perfiles de agentes ni skills vacías. El paquete separado
`src/trading_lab_orchestration` usa el packaging setuptools existente y Pydantic
ya instalado, sin dependencias nuevas ni modificaciones en `src/quant_lab`.
La CLI `scripts/orchestrator.py` no modifica el entrypoint lab congelado.

Inventario de fronteras comprobado contra README/arquitectura/código: CLI ordinaria
`scripts/lab.py`, ExperimentStore SQLite/JSON/Parquet, runners especializados,
`forward/` RMM/Donchian, `brokers/`, `market_data/` y `notifications/` permanecen
fuera del cambio. No se inspeccionaron credenciales, procesos vivos ni journals
activos; no se certifica su estado operativo mediante esta verificación.

## Verificación y siguientes entregas

Comandos de comprobación técnica:

```powershell
python -m pytest tests/unit/test_orchestration.py tests/unit/test_lab.py tests/unit/test_strategy.py tests/unit/test_config.py tests/integration/test_scaffolding.py tests/regression/test_causality_contract.py tests/regression/test_batch_strategies.py tests/regression/test_execution.py -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
git diff --check
git status --short
```

Las pruebas nuevas cubren entradas válidas/incompletas, campos extra, tipos,
versiones, UTC, reglas long/short/funding, costes, periodos/grid, JSON ambiguo,
hashes, conflictos, variantes, inicialización concurrente, envíos simultáneos,
persistencia entre procesos, reenvío bloqueado, restricciones de estado e
inyección de fallos durante inserts/transiciones para verificar rollback.
Se comprueba rechazo de DB ajena y versión futura sin reutilizar ledgers reales.
Resultado final: **133 passed en 35.09 s**, incluidos **30 tests nuevos** de
orquestación. Ruff global correcto, formato global correcto,
`pip check` sin dependencias rotas y `git diff --check` correcto. La CLI real
`validate examples/orchestration/manual_valid.json` terminó con código 0.
No se ejecutó la suite completa ni backtests históricos; las regresiones existentes
usan fixtures/simulaciones sintéticas pequeñas.

El primer intento de los tests nuevos tuvo 12 errores de fixture por no poder crear
temporales/cache en las rutas del sandbox (18 tests sin temporales sí pasaron).
Se repitió sin cacheprovider y con `--basetemp` dentro de una raíz permitida:
30/30 correctos, después el grupo final133/133. No se cambió código para ocultar
esos errores de entorno. Ruta de temporales de la ejecución final:
`C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/pytest-orchestration-02`.

Pendiente, solo diseñado: investigación automática, búsqueda semántica/histórica,
aprobaciones autenticadas, capacidades/perfiles, presupuesto API medido, adaptadores
de modelos/Codex/Git/Telegram, scheduling, ejecutor, auditor y backups automáticos.
No se impone cuota diaria o presupuesto ficticio a esta ingesta manual sin llamadas
ni tareas ejecutables. Esos controles deberán implementarse antes de habilitar
servicios o cómputo. Forward/OKX sigue siendo un proceso separado y fuera del alcance.

Archivos añadidos: paquete `src/trading_lab_orchestration/` (init, contracts, store,
cli), `scripts/orchestrator.py`, `tests/unit/test_orchestration.py`, los dos JSON de
`examples/orchestration/` y esta guía. Modificados: AGENTS, .gitignore, README,
PROJECT_STATE, ARCHITECTURE y WORKFLOW para registrar la capacidad y sus límites.
Sin commit, push ni merge; sin cambios a estrategias, resultados, datos o forward.

## Verificación adicional: procesos simultáneos y rollback (2026-11-03)

Se añaden cuatro regresiones a `tests/unit/test_orchestration.py`. No se detectaron
fallos en el coordinador y no fue necesario cambiar código de producción.

Dos intérpretes Python distintos esperan una barrera de entrada estándar; el padre
libera ambos para registrar la misma ficha por la CLI. Se comprueba tanto base nueva
(incluye la inicialización concurrente) como base previamente inicializada. Ambos
procesos terminan con código0, sin stderr ni errores de bloqueo. Una respuesta indica
`created=true` y la otra `duplicate=true`; coinciden candidate_id y task_id.
En ambos casos quedan exactamente **1 candidata, 1 tarea, 4 eventos, 1 envío**.
`integrity_check=ok` y `foreign_key_check` vacío.

Recibo de la prueba dirigida sobre base nueva: PIDs22024/14744,
candidate_id=`cand_11063caa9569488fb6d01f7f330aa6d9`,
task_id=`task_cb623f8a05834de481ef0c5aa2782f2a`.
Sobre base inicializada: PIDs28612/28284, ambas salidas0 y mismos conteos.

Para rollback se instala un trigger **solo en la base temporal** que aborta la
inserción del segundo evento. El propio trigger exige comprobar que ya existen
candidata, tarea, envío y primer evento de esa transacción, evitando una prueba que
falle antes de las escrituras. La CLI devuelve código2 con JSON gestionado:
`{"error":"IntegrityError","message":"injected after partial writes"}`, sin stderr.

| Caso | Después del fallo: candidatas/tareas/eventos/envíos | Después del reintento |
|---|---|---|
| Base vacía | 0 / 0 / 0 / 0 | 1 / 1 / 3 / 1 |
| Base con expediente previo | 1 / 1 / 3 / 1 | 2 / 2 / 6 / 2 |

Las filas anteriores al intento se comparan íntegramente tras el fallo y permanecen
idénticas. Eliminado el trigger de prueba, el reintento desde otro proceso termina
con código0 y `created=true`. Ambas bases pasan integridad y claves foráneas.
Se verifica una excepción SQL dentro de la transacción, no un corte eléctrico.

Reproducir estas cuatro pruebas con temporales nuevos:

```powershell
python -m pytest tests/unit/test_orchestration.py -k 'two_processes or partial_writes' -q -s
```

Resultado dirigido: **4 passed, 30 deselected en 4.22 s**. Grupo de verificación
documentado arriba, incluida toda orquestación: **137 passed en 30.83 s**
(34 tests de orquestación). Ruff global/check y formato global correctos,
`pip check` sin dependencias rotas, `git diff --check` correcto e inventario de
archivos modificados revisado. No se ejecutó la suite completa.

Para evitar los límites de temporales del sandbox se usó `-p no:cacheprovider` y
`--basetemp` bajo
`C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/`:
`pytest-process-acceptance-01` para las cuatro pruebas y
`pytest-process-acceptance-02` para el grupo137. Las SQLite se crearon únicamente
en esos temporales, nunca en bases experimentales o sesiones existentes.

Esta verificación añade solo tests y esta evidencia documental al trabajo4.1 ya
presente. Sin servicios, backtests históricos, scheduling ni avance al paso4.2.
