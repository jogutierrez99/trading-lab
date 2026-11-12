# Paso 4.2 — implementación manual mediante Codex CLI

Implementado sobre el coordinador4.1, verificado con ejecutable **simulado** y un
piloto con Codex real. El bloqueo de permisos está resuelto. La tercera entrega falló
inicialmente por formato; tras autorización del usuario el 2026-11-04 se corrigió solo
formato con AST idéntico y se repitieron nueve tests, lint y formato: SUCCEEDED y recibo
verificado. Sin cuarta llamada al modelo ni ampliación del límite de tres intentos.
Ver [diagnóstico, corrección y evidencia](orchestration-step-4.2-diagnosis.md).
NEW_STRATEGY prepara scaffolds con el generador local y sella sus hashes; el modelo
completa esos archivos. El adaptador restaura explícitamente el backend Windows del
sandbox al ignorar la configuración de usuario. Sin backtests, investigador, auditor,
scheduling, Telegram, OKX, push ni merge.

## Requisitos y ejecución manual

Desde la raíz del checkout, Python>=3.12 y Git:

    .\.venv\Scripts\Activate.ps1
    python -m pip install -e ".[dev]"
    git --version
    codex --version
    codex exec --help
    codex login status
    python scripts/orchestrator.py doctor
    python scripts/orchestrator.py --help

doctor comprueba ejecutable, versión, capacidades y autenticación local sin iniciar
el modelo. No almacena la salida de autenticación. Si falta login, ejecutar codex
login manualmente, sin copiar credenciales al chat/SQLite. --codex-executable admite
una ruta nativa; rechaza wrappers .cmd/.bat/.ps1. No hay fallback automático API.

Ayuda local inspeccionada: codex-cli0.166.0-alpha.5.1. Se comprobaron exec/stdin,
JSONL, output-schema, output-last-message, sandbox workspace-write, ignore-user-config,
ephemeral, no-daemon y -a never global. Hubo avisos de permisos sobre aliases/temp
del entorno Codex; no se sortearon con acceso irrestricto. La verificación inicial
de ayuda no certificaba cuenta/sandbox; el piloto posterior está en el diagnóstico.
Referencias:
[modo no interactivo](https://learn.chatgpt.com/docs/non-interactive-mode) y
[opciones CLI](https://learn.chatgpt.com/docs/cli/reference); prevalece ayuda local
al elegir argumentos, no flags de versiones históricas.

Revisar el diff y los ejemplos antes de la prueba real. Los worktrees parten de HEAD,
no de modificaciones locales. Para incluir esta entrega en la base, revisarla y
hacer commit **manualmente**. No hay commit/stash/reset/push/merge automáticos.
El checkout del usuario puede estar sucio: se conserva, sin copiar sus modificaciones.

Revisar examples/orchestration/implementation_manual.json e implementation_plan.json:
regla pequeña spot1h LONG_ONLY, sin datos reales, experimento ni backtests; plan con
target nuevo, revisión explícita, wall limit900s y60s por check. Es un ejemplo de
implementación, no evidencia económica ni estrategia implementada en este desarrollo.

    $state = Join-Path $env:LOCALAPPDATA 'TradingLab\orchestration'
    $env:TRADING_LAB_ORCHESTRATOR_DB = Join-Path $state 'orchestrator.sqlite3'
    $artifacts = Join-Path $state 'implementation-attempts'
    python scripts/orchestrator.py validate examples/orchestration/implementation_manual.json
    $registration = python scripts/orchestrator.py register examples/orchestration/implementation_manual.json | ConvertFrom-Json
    $task = $registration.task_id
    $prepared = python scripts/orchestrator.py prepare $task --repo . --plan examples/orchestration/implementation_plan.json --artifacts $artifacts | ConvertFrom-Json
    $attempt = $prepared.attempt_id
    python scripts/orchestrator.py attempt $attempt
    Get-Content (Join-Path $prepared.root 'request.json')
    Get-Content (Join-Path $prepared.root 'prompt.txt')

Comprobar $LASTEXITCODE después de cada comando. prepare debe devolver PREPARED y0.
Revisar IDs, commit, rama/workspace, ficha/hash, paths, pruebas y límites. Si hay
BLOCKED/código2, inspeccionar error y conservar evidencia. **Después de revisar**:

    python scripts/orchestrator.py run $attempt
    python scripts/orchestrator.py attempt $attempt
    python scripts/orchestrator.py show $task
    git worktree list

Alternativa manual de una orden, tras revisar previamente ficha y plan:

    python scripts/orchestrator.py process $task --repo . --plan examples/orchestration/implementation_plan.json --artifacts $artifacts

No ejecutar ambas alternativas para la misma tarea. process=prepare+run; no reanuda
intentos ni programa nada. Este run no es lab.py run y no lanza estudios históricos.
Éxito0; error/bloqueo2. attempt/show devuelven0 si la consulta es válida, incluso
cuando el estado consultado sea fallido.

## Contratos, scopes y decisiones

Mismo HypothesisManifest1.0/snapshot/hash de4.1. Se añaden ImplementationPlan1.0
(operador: operación/target/revisión/límites), ImplementationRequest1.0
(IDs/intento/ficha/hash/base/rama/workspace/plan/paths/checks/skill/antecedente),
ModelDelivery1.0 (salida no confiable: identidad/procedencia/archivos+SHA/resumen/
bloqueos/advertencias/comandos inertes) e ImplementationReceipt1.0 generado por el
coordinador tras contrastar archivos y checks reales. Entradas y entrega del modelo
usan Pydantic estricto, sin campos extra.

NEW_STRATEGY debe coincidir con requires_new_strategy_code=true; NEW_EXPERIMENT con
false. Gate rechaza placeholders esenciales, perpetual/runners dedicados y timeframes
fuera de1h/4h/1d; exige StudyBackend v1 y revisión manual de completitud. No demuestra
semánticamente que cualquier prosa sea suficiente ni valida datasets. Un experimento
requiere ficha inequívoca sobre estrategia/versión/perfil/datos; si falta, BLOCKED.

Paths derivados del plan: NEW_STRATEGY solo módulo/perfil/test nuevos del target;
NEW_EXPERIMENT solo YAML y test unitario nuevos. Sin rutas/comandos arbitrarios del
modelo. Nombres existentes en base o checkout original se rechazan, incluidas
reservas. Encargo reutiliza skills/create-strategy/SKILL.md o create-experiment/SKILL.md;
no duplica skills ni instala perfiles de agentes. Otros protocolos siguen intactos.
AGENTS amplía solo la excepción de orquestación a esta implementación manual.
El límite de dos reparaciones de la petición actual sustituye el reintento único
propuesto por el maestro del ZIP; no cambia contratos financieros.

El modelo declara tests_run=NOT_RUN_BY_MODEL. El coordinador ejecuta pytest del test
nuevo y Ruff/check+format de Python nuevos, guardando stdout/stderr/retorno/duración.
Las entregas nuevas pasan además el probe nativo sintético compartido con4.3 antes
del recibo; runtime, resultado y proceso quedan archivados. No habilita YAML en disco
ni ejecuta backtests. [Contrato y reparación pendiente](pilot-native-index-repair.md).
No confía en un PASS redactado. ID/hash contradictorio, archivo faltante, check fallido
o modificación fuera de scope impide SUCCEEDED. ModelDelivery y resultado0 no bastan.
El recibo independiente incluye archivos/SHA, checks, consumo CLI o null, EUR null,
result_commit null y hashes de fuentes/artefactos. No acredita rentabilidad.

## SQLite, reserva y recuperación

Misma base, migración transaccional user_version1→2. Preserva IDs/manifiestos/envíos/
eventos, amplía CHECK de candidates/tasks y añade solo attempts. FK OFF únicamente
en esa conexión de migración, BEGIN IMMEDIATE y foreign_key_check antes del commit;
un fallo revierte. Rechaza DB ajenas/versiones futuras; no abre ExperimentStore/forward.
La tarea MANUAL_REVIEW pasa a IMPLEMENTATION con el mismo ID/clave histórica.

Attempts conserva IDs, número1..3, estado/timestamps UTC, repo/base/rama/rutas,
PID/error/elegibilidad de reparación. Estados y eventos cambian atómicamente.
UNIQUE parcial permite un único PREPARED/RUNNING/UNKNOWN en esa SQLite; lock OS
complementario durante preparación/ejecución/reconciliación. Usar una sola base:
bases independientes no comparten el límite global.

| Fase | Candidata | Tarea | Intento |
|---|---|---|---|
| Revisión/preparación | GATE_RESEARCH_APPROVED → DEVELOPMENT_QUEUED | QUEUED | PREPARED |
| Codex/checks | IMPLEMENTING | RUNNING | RUNNING |
| Entrega contrastada | IMPLEMENTATION_READY | SUCCEEDED | SUCCEEDED |
| Fallo técnico | FAILED | FAILED/TIMED_OUT | FAILED/TIMED_OUT |
| Spec/auth/permisos/scope | BLOCKED | BLOCKED | BLOCKED |
| Resultado incierto | BLOCKED | BLOCKED | UNKNOWN |

GATE registra revisión manual para implementar, no etiqueta económica ni permiso de
backtest. Transiciones4.1 no saltan intentos activos. attempt detecta RUNNING sin
propietario del lock y marca UNKNOWN; no infiere fallo/éxito ni relanza. UNKNOWN
mantiene ocupado el slot. Se conservan artefactos de todos los intentos.

Windows: hijo suspendido, asignación a Job Object kill-on-close y reanudación;
timeout/cierre/caída del padre mata árbol. Si no puede asociar al Job, falla de forma
conservadora. POSIX: grupos terminados al salir/timeout; SIGKILL del coordinador puede
dejar hijos, que hay que inspeccionar/detener. Tras comprobar proceso/descendientes y
artefactos, elegir una acción manual:

    python scripts/orchestrator.py attempt $attempt
    python scripts/orchestrator.py reconcile $attempt --outcome verify --confirm-stopped --reason 'Proceso y descendientes detenidos; revisar entrega existente'
    # O para fallo confirmado:
    python scripts/orchestrator.py reconcile $attempt --outcome failed --confirm-stopped --reason 'Fallo confirmado tras inspeccion'
    # O para cancelar:
    python scripts/orchestrator.py reconcile $attempt --outcome cancel --confirm-stopped --reason 'Cancelacion manual'

No ejecutar las tres acciones sucesivamente. Rechaza terminales y PID existente.
La comprobación de PID es conservadora ante reutilización y no demuestra ausencia
de todos los descendientes; confirm-stopped es declaración explícita del operador.
verify utiliza process-result/entrega existentes y checks sin invocar al modelo;
si falta evidencia confirmada conserva UNKNOWN.

### Reparación manual exclusiva de formato

Si el último intento es FAILED **solo** por el tercer check de Ruff format, los otros
dos checks pasaron, el modelo terminó correctamente y no hay otro trabajo activo:

    python scripts/orchestrator.py --db RUTA_SQLITE repair-format ATTEMPT_ID --confirm-stopped --reason 'Autorizo corregir únicamente formato y repetir controles'

Es una acción manual adicional, sin llamada al modelo ni intento nuevo. Rechaza cambios
desde la entrega original, PID vivo, otro fallo o reparación previa. Antes de modificar,
archiva estado, autorización y archivos; ejecuta Ruff por stdin y exige AST idéntico.
Se permite únicamente el formato de los Python autorizados. El YAML queda intacto.
Repite todos los checks y registra la transición mediante UNKNOWN a SUCCEEDED/FAILED.
Nunca altera ModelDelivery ni los logs originales: el recibo incorpora
operator_format_repair con hashes antes/después y procedencia explícita. Los hashes de
files corresponden a los bytes corregidos; model_delivery conserva los hashes del modelo.
Si se interrumpe, UNKNOWN exige inspección manual; no hay reanudación automática.
El límite de tres llamadas al modelo sigue vigente. No modifica lógica ni elimina gates.

No hay reintentos automáticos. Para fallo técnico confirmado:

    python scripts/orchestrator.py prepare $task --repo . --plan examples/orchestration/implementation_plan.json --artifacts $artifacts --repair

Revisar nuevo request y usar su nuevo attempt_id. Máximo inicial+dos reparaciones,
misma ficha/plan/base, rama/worktree/evidencia distintos, diagnósticos previos referenciados.
No se ajustan reglas/umbrales para mejorar resultados. Auth/ejecutable ausente antes
del lanzamiento deja BLOCKED, child_pid=null: tras corregir, run explícito reutiliza
ese preparado sin crear otro intento. Tras lanzamiento no se permite run directo.

Raíz de intento: request/prompt/schema/baseline, probe CLI, JSONL/stderr, resultado de
proceso y verification_UUID con cambios/diff, copias de archivos nuevos, checks,
receipt o failure y hashes. Snapshot complementa diff Git (omite untracked).
Sin limpieza automática de worktrees ni sobrescritura de evidencia previa.

## Controles efectivos y límites pendientes

Efectivos: argv sin shell, scopes del operador, base/branch/worktree exclusivos,
comprobación HEAD/branch/hash, scope incluso con exit!=0, SQLite+lock OS, timeout,
terminación de árboles y logs exclusivos. Git desactiva hooks/fsmonitor. No se
ejecutan comandos sugeridos ni lab run/download. Variables de secretos se retiran
por nombre; no se copian .env/datos/resultados locales al worktree.

CLI: workspace-write, network_access=false, -a never, ignore-user-config, ephemeral,
no-daemon; sin add-dir ni acceso irrestricto. Auth local de CLI. Wall limit reparte
tiempo entre Codex/checks y hay timeout individual; probes15s y Git30s independientes.

**No es aislamiento por archivo**: workspace-write permite todo el worktree; el
allowlist interno se comprueba después. Fidelidad a reglas, prohibición de backtests/
herramientas y no lectura de secretos dependen también de instrucciones y controles
CLI. Un worktree comparte metadatos Git/cuenta. Checks externos ejecutan Python
generado con timeout/Job, **sin sandbox filesystem/red propio**. No es contención
frente a código hostil: primera prueba real pequeña, confiable y supervisada.
El diff no detecta escrituras externas ni cambios transitorios revertidos.

CPU/RAM/disco/tokens/coste no tienen caps duros. Usage si existe o null; EUR null.
La integración real se comprobó en el piloto descrito; sigue pendiente el control financiero.
El presupuesto20EUR del diseño no se presenta como garantizado.

## Verificación y cierre

Ejecutable simulado en otro intérprete con probes/argv y Git/SQLite/procesos/checks
reales. Cubre éxito, recibos inválidos/contradictorios, fallo/timeout/hijos, ausencia
de ejecutable/auth, reserva concurrente/límite global, interrupción/reconciliación,
reparaciones/tampering/scope, preservación local y migración. Conserva tests4.1.

    python -m pytest tests/unit/test_orchestration.py tests/integration/test_codex_orchestration.py -q
    python -m pytest tests/unit/test_orchestration.py tests/integration/test_codex_orchestration.py tests/unit/test_lab.py tests/unit/test_strategy.py tests/unit/test_config.py tests/integration/test_scaffolding.py tests/regression/test_causality_contract.py tests/regression/test_batch_strategies.py tests/regression/test_execution.py -q
    python -m ruff check .
    python -m ruff format --check .
    python -m pip check
    git diff --check
    git status --short

Para cerrar **integración real**, devolver versión/doctor sin datos de cuenta,
prepare/run/attempt/show, request/hash, ModelDelivery, process-result y stderr depurado,
receipt/checks, diff+archivos/SHA, hashes, usage o null y revisión manual del scope.
Conservar task/candidate/attempt/base/branch exactos. Confirmar original checkout
intacto, sin backtests/órdenes ni procesos huérfanos. Exit0 del modelo no cierra4.2:
se exige SUCCEEDED con evidencia coherente. Nada habilita4.3, forward o publicación.

## Evidencia de ejecución de esta entrega

Grupo dirigido completo del comando anterior: **160 passed en83.95s**, incluidos
los34 tests4.1 y23 tests de integración4.2. Tras ajustar timestamps de UNKNOWN,
revalidación de plan, reconciliación y lectura conservadora de usage, se repitieron
los23 tests de integración sobre el código final: **23 passed en48.59s**.
No son183 tests distintos. No se ejecutó la suite completa ni investigación histórica.

Checks finales: Ruff global correcto, formato global correcto, pip check sin
dependencias rotas, git diff --check correcto. Se inspeccionaron diff e inventario
de archivos nuevos; no hay cambios al motor, estrategias o sesiones existentes.
La CLI --help y validación de implementation_manual.json terminaron con código0.
Hash canónico del ejemplo:
903e06de1049e7557c0681300b335e9b3038b692b1e4f8668121cbaf810d5ae9.

Los tests usan bases/repositorios/worktrees temporales. En este sandbox se añadió
-p no:cacheprovider y --basetemp bajo
C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/:
pytest42-final-04 para el grupo160 y pytest42-integration-final-05 para la repetición23.
No se migró la SQLite operativa del usuario durante estas pruebas.

El primer pase del simulador tuvo4 fallos/12 correctos: su test generado no cumplía
Ruff format, y los casos que esperaban éxito quedaron correctamente rechazados.
Se corrigió el fixture, conservando el gate; siguientes16 y luego55 tests pasaron.
La revisión adicional detectó y corrigió la clasificación de un BLOCKED sin archivos,
la posible carrera entre consulta y finalización y timestamps inciertos. Todo ello
está cubierto por la batería final; no se rebajaron los controles para conseguir éxito.

Archivos añadidos en4.2 dentro de src/trading_lab_orchestration:
implementation.py, implementation_contracts.py, codex_adapter.py, workspaces.py,
processes.py y migration.py. Modificados store.py y cli.py del mismo paquete.
Añadidos tests/integration/test_codex_orchestration.py, los dos ejemplos
implementation_manual.json/implementation_plan.json y esta guía.
Documentación/política: AGENTS, README, PROJECT_STATE, ARCHITECTURE, WORKFLOW y enlace
desde la guía4.1. Los cambios4.1 previos siguen sin commit en el checkout, preservados.
Sin commits, push, merge ni publicación. Ese grupo inicial usó únicamente el simulador;
el piloto real posterior y su cierre están en el diagnóstico enlazado arriba.
