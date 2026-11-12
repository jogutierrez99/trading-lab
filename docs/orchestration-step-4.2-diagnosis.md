# Diagnóstico de la integración real 4.2 — evidencia inicial 2026-11-03 y cierre 2026-11-04

**Integración real aceptada tras reparación manual de formato.** El tercer intento
terminó originalmente FAILED por Ruff format, con nueve tests y lint correctos.
El usuario autorizó resolverlo el 2026-11-04: se corrigió exclusivamente formato,
con AST idéntico, y el coordinador repitió los tres checks y generó un recibo verificado.
Estado actual SUCCEEDED; ninguna cuarta llamada al modelo. Las secciones originales
siguientes describen el diagnóstico y el fallo conservado; el cierre figura al final.

## Evidencia y causa demostrada

Base común: 131ffaa101f7d04d81dcb47936142802ebba0a4b.
Candidata: cand_0b7f6f1e8580418887519e1f67c6ae10.
Tarea: task_7c894d7e4dca4f24a164632a703d5d5d.
La ficha permanece fijada por SHA256
903e06de1049e7557c0681300b335e9b3038b692b1e4f8668121cbaf810d5ae9.

| Intento | Configuración relevante | Evidencia real | Resultado |
|---|---|---|---|
| 1, attempt_ee967d986ab94a7199ce5fddede29230 | ignore-user-config, workspace-write, never | Lectura rechazada antes de ejecutarse; entrega BLOCKED sin archivos | BLOCKED original, después reconciliado manualmente como fallo confirmado |
| 2, attempt_4d04e0db523a4130b77ab3262e0eaff8 | Perfil :workspace explícito, generador previo, instrucción de shell del sistema | Mismo rechazo; el runtime sigue mostrando su pwsh privado | BLOCKED, después fallo confirmado manual |
| 3, attempt_cb2c94564a6f464f95faaeee58bae9a5 | Además windows.sandbox="elevated" explícito | La lectura antes rechazada se ejecuta correctamente mediante el mismo pwsh; entrega IMPLEMENTED con tres archivos | FAILED por formato, sin bloqueo de permisos |

Motivo literal inicial del modelo:

> The environment permits filesystem reads only and disallows approval escalation,
> so the three authorized new files cannot be created.

Segundo bloqueo literal del mismo recibo:

> Automatic policy review rejected the read command for the required project
> documentation and selected skill; those prerequisites could not be inspected.

Ese texto era una declaración del modelo, no prueba suficiente de los permisos del
filesystem. El stderr sí demuestra el rechazo de ejecución: la lectura de AGENTS,
README, documentación y skill mediante pwsh.exe acaba en "rejected: blocked by policy".
No aparece un error de lectura de AGENTS como causa de ese rechazo.

El adaptador arrancaba exec con --ignore-user-config. Su ayuda local dice que omite
config.toml y mantiene la autenticación local. Al inspeccionar únicamente campos de
permisos se comprobó que el equipo tenía windows.sandbox="elevated" en esa configuración,
pero el adaptador lo descartaba y no lo reponía. Las pruebas nativas que sí funcionaban
cargaban esa selección. Reponerla explícitamente en el tercer intento hizo que las
lecturas antes rechazadas se completaran, sin cambiar ficha, base, reglas del repo,
red, aprobación never ni rutas de escritura. Esta es la diferencia decisiva observada.

elevated es el backend con usuarios restringidos de Windows, no un modo sin sandbox:
[documentación oficial](https://learn.chatgpt.com/docs/windows/windows-sandbox).
No se modificó config.toml, requirements, reglas, ACL manuales ni archivos de autenticación.
No se expusieron credenciales. No se eliminó la conexión IPC ni se retiraron variables
de seguridad: la comparación de contexto con/sin identidad heredada no acreditó esa causa.

## Configuración solicitada y permisos comprobados

CLI local: codex-cli 0.166.0-alpha.5.1. Cada intento conserva los argv exactos en
process-result.json. Invocación final, con las rutas concretas del intento:

    codex.exe --no-daemon -a never exec --ignore-user-config --sandbox workspace-write
      -c default_permissions=":workspace"
      -c sandbox_workspace_write.network_access=false
      -c windows.sandbox="elevated"
      --ephemeral --json --color never --cd WORKSPACE
      --output-schema ATTEMPT/delivery.schema.json
      --output-last-message ATTEMPT/delivery.json -

cwd es exactamente WORKSPACE, no el checkout principal. La entrada llega por stdin;
no se construyen comandos de shell a partir de la hipótesis. No hay --add-dir,
ignore-rules, danger-full-access ni bypass de aprobaciones.

WORKSPACE del intento final:
C:/Users/joshu/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/TL42/964b59/a/attempt_cb2c94564a6f464f95faaeee58bae9a5/workspace.

Raíz local del circuito:
C:/Users/joshu/AppData/Local/TL42/964b59/.
Windows resuelve esa ruta al LocalCache de la aplicación; la ruta canónica exacta
consta en cada request y fila attempts. Los worktrees son:
a/attempt_ID/workspace y las ramas codex/attempt_ID.
Los JSONL, stderr, requests, controles, recibos y diagnósticos se guardan en la raíz
de cada intento, fuera de OneDrive. El CLI controlador escribe esos artefactos;
no se concedió al modelo escritura sobre el padre ni sobre la base SQLite.

Tres rutas de entrega, sin ampliación:

- src/quant_lab/strategies/manual_engulfing_breakout_v1.py
- configs/strategies/manual_engulfing_breakout_v1.yaml
- tests/unit/test_manual_engulfing_breakout_v1.py

Lecturas necesarias: documentación, skill, BaseStrategy/registry/config y ejemplos
existentes dentro del worktree. El puntero .git es de lectura; no se concedió
escritura al Git compartido. La lectura inicial no necesitaba mutar metadatos Git.
Preparar un worktree sí requiere que el controlador cree rama/metadatos: eso se
autorizó para el controlador, sin otorgarlo al modelo.

Pruebas deterministas con codex sandbox -P :workspace, sin modelo ni red:

| Comprobación | Resultado observado |
|---|---|
| PowerShell del sistema lee AGENTS del worktree | Sí |
| Puede crear y retirar un marcador propio en el worktree | Sí |
| Puede escribir el marcador en el checkout principal | No, UnauthorizedAccessException |
| Puede leer el puntero .git del worktree | Sí |
| Python privado instalado para el usuario arranca en ese sandbox | No, CreateProcessAsUserW error5 |

Los marcadores se retiraron; no se modificaron archivos existentes. Se confirmó
también la protección del checkout con el worktree del intento2.
Añadir lectura de la carpeta y archivos exactos de Python no resolvió su arranque;
esas concesiones diagnósticas no se incorporaron al adaptador.
Los ensayos con cmd.exe y cwd Windows dieron errores de sintaxis/setup y no se
utilizan para atribuir la causa al filesystem ni al worktree.

La ruta de shell solicitada como precaución no fue el arreglo decisivo: el runtime
mostró su pwsh.exe privado tanto antes como después de la corrección efectiva.
La traza no identifica una regla individual responsable del rechazo original.
La comparación de los intentos2 y3 sí acredita la omisión del backend al ignorar
la configuración de usuario.

## Corrección aplicada y regresiones

codex_adapter.py selecciona :workspace explícitamente y, solo en Windows, repone
windows.sandbox="elevated" al ignorar config.toml. Mantiene restricciones administradas,
aprobaciones never y red desactivada; no tiene fallback a unelevated ni acceso total.
Una máquina que exija otro backend no debe saltarse su política.

implementation.py ejecuta el generador existente del commit base como preparación
determinista de NEW_STRATEGY. Es código del repositorio congelado, no un comando
propuesto por el modelo. Solo crea el triplete exclusivo previsto, con timeout y Job.
Esto evita depender del Python privado dentro del sandbox del modelo y cumple el
paso de scaffolding de create-strategy. No implementa señales ni ejecuta tests.

Se conservan baseline del commit y hashes de los tres scaffolds en prepared-files.json.
Ese archivo queda sellado en controls_sha256; antes del lanzamiento se exige igualdad
exacta con el estado preparado. Cambios posteriores, incluso en una ruta permitida,
bloquean el lanzamiento. Un BLOCKED del modelo sin archivos sigue siendo BLOCKED
aunque existan scaffolds creados por el controlador; no se toma el scaffold por entrega.
Las solicitudes antiguas sin ese artefacto mantienen su validación anterior.

Regresiones añadidas: sellado del scaffold, detección de cambios posteriores,
manipulación de prepared-files, selección del perfil, backend Windows explícito,
aprobación never y ausencia de flags de bypass/add-dir.
No se modificaron HypothesisManifest, motor, riesgo, estrategias existentes,
datos, resultados históricos o sesiones forward.

Los checks externos siguen siendo procesos del controlador con timeout/Job,
sin sandbox filesystem propio: se conserva ese límite documentado de4.2.
No se presenta todo el sistema como contención frente a código hostil.

## Resultado de la repetición final

El último request tiene SHA256
d7ef6836e9297652a4cad3d3fdec8046dc0369a80a93472a89218a1b1803b1e2.
Codex real terminó con código0 y ModelDelivery IMPLEMENTED; hashes, IDs, base,
rama y conjunto de archivos coinciden con los bytes reales y el alcance autorizado.

Checks independientes del controlador:

- pytest: nueve tests sintéticos aprobados, 22.09s; reglas/fronteras, gaps, warmup,
  modos no soportados, registro y prefix-invariance.
- Ruff check: correcto.
- Ruff format --check: código1; solo el módulo necesita redistribuir una expresión
  encadenada .fillna(False).tolist(). No es un fallo de reglas o rendimiento económico.

El controlador devolvió código2 y FAILED, sin recibo IMPLEMENTED_VERIFIED.
Los artefactos originales de los tres intentos permanecen conservados; la
reconciliación de los fallos confirmados se añadió al historial, sin sobrescribir
los ModelDelivery originales BLOCKED ni sus logs.
No se ejecutó un cuarto intento ni se amplió el límite de tres.

Se comprobó por hashes que el checkout principal no cambió durante la ejecución
(respecto a la instantánea posterior a las correcciones autorizadas del adaptador).
Todos los PID registrados de Codex, generador y checks están terminados.
No hubo backtests históricos, Telegram, OKX, órdenes, push ni merge.
El YAML nuevo está deshabilitado y sigue únicamente en el worktree.

Se dejó una propuesta de formato separada, sin aplicarla al intento ni cambiar su estado:
C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/tl42-format-only-proposal/format-only.patch.
Ruff acepta la propuesta y su AST es idéntico al original. Para incorporarla y
registrar una entrega aprobada hace falta una reparación adicional autorizada:
el presupuesto acordado de tres intentos está agotado. No se relaja el gate de formato.

## Verificación técnica del repositorio

Se ejecutaron los grupos documentados de4.2 con temporales nuevos y sin cacheprovider:

- 23 tests de integración existentes: aprobados, 245.22s.
- Dos regresiones nuevas: aprobadas, 9.73s.
- Grupo de ingesta/core/scaffolding/causalidad/ejecución:137 aprobados, 113.48s.
- Tras añadir el backend explícito se repitieron tres casos afectados: aprobados,
  19.43s. Son repeticiones, no tests distintos adicionales.

Total de tests distintos del repositorio:162 aprobados; además los nueve de la
entrega real. No se ejecutó la suite completa. Ruff global, formato global del
checkout principal, pip check y git diff --check correctos. El formato fallido es
el del módulo nuevo del worktree, no el del adaptador del checkout principal.

Evidencia local adicional, fuera del repo:
tl42-effective-fs-probe.json, tl42-python-exact-read-probe.json,
tl42-diagnosis-repeat-result.json y tl42-final-diagnosis-result.json, bajo la raíz
de visualizaciones de esta conversación. El último incluye checks, PID, hashes,
ModelDelivery consistente, estados y consumo CLI informado; EUR queda null.

## Cierre autorizado — 2026-11-04

La petición del usuario «si sabes donde esta el error solucionalo» autoriza la reparación
manual adicional. Se añadió repair-format al coordinador y CLI, sin aumentar el límite
de llamadas al modelo, migrar SQLite ni reabrir la ejecución de Codex. Solo admite el
último FAILED por el check de formato, con pytest/lint previos correctos, proceso modelo
correcto, procesos detenidos y ningún intento activo. Rechaza cambios posteriores y
contrasta los archivos con la entrega y las copias de la verificación original.

Archiva estado, autorización y archivos en format_repair_UUID; Ruff genera propuestas
por stdin, se compara el AST y solo entonces se escribe el formato. Repite todos los
checks y crea verification_UUID nuevo. El recibo conserva model_delivery original y
añade operator_format_repair con procedencia y hashes antes/después. No se retocó
el recibo del modelo para atribuirle la corrección del operador.

Ejecución real: repair-format del intento attempt_cb2c94564a6f464f95faaeee58bae9a5
devuelve0; intento y tarea SUCCEEDED, candidata IMPLEMENTATION_READY. Nueve tests,
Ruff check y Ruff format --check aprobados. Recibo nuevo:
verification_5e638f2b6d5e4a0082d2bdd96cf5256f/receipt.json.
Solo cambia el formato del módulo; test y YAML conservan sus hashes. SHA256 final
del módulo:8f61601832fbf010eaea294bb905d02d5c2718a5ebac4c4c3dfb2537db1249e1.

Todos los artefactos preexistentes siguen idénticos por hash; el checkout principal
no cambió durante esta reparación. Todos los PID registrados están terminados.
Permanecen exactamente tres intentos, sin nuevas llamadas al modelo. Las cuatro
regresiones nuevas pasan: reparación exitosa sin relanzar, rechazo de fallo de tests,
rechazo de manipulación posterior y rechazo de cambio de AST.

Verificación adicional de cierre: las cuatro regresiones pasaron en99.78s. El pase
completo de ingesta/orquestación terminó con62 aprobados y1 fallo en514.22s: el check
pytest sintético del caso preflight/missing alcanzó15.057s, timed_out=true, sin salida
ni error de aserción. El coordinador rechazó correctamente ese timeout. Se amplió
únicamente el margen del fixture (check15→30s, wall30→60s) para el arranque de Python
en Windows; los planes operativos y la regresión de timeout wall=1s no se modificaron.
No se presenta ese pase como63 aprobados. La repetición dirigida de recuperación
(auth/missing) y timeout terminó con3 aprobados en65.92s, incluido el caso fallido.
Así, los63 casos distintos de ingesta/orquestación han pasado en grupos, sin repetir
innecesariamente el pase completo. Ruff global, formato global (447 archivos), pip check
y git diff --check correctos. No se ejecutó la suite completa del repositorio.

Comandos de pruebas del cierre (temporales bajo la carpeta de visualizaciones,
cacheprovider desactivado):

    python -m pytest tests/integration/test_codex_orchestration.py -k manual_format_repair -q -p no:cacheprovider
    python -m pytest tests/unit/test_orchestration.py tests/integration/test_codex_orchestration.py -q -p no:cacheprovider
    python -m pytest tests/integration/test_codex_orchestration.py -k 'preflight_recoverable or timeout_kills' -q -p no:cacheprovider

Evidencia completa del cierre:
C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/tl42-authorized-format-result.json.
Incluye recibo, checks, hashes, estados y PID. El fallo anterior y la propuesta separada
permanecen como evidencia histórica, no como estado actual.

No hay validación económica, aprobación paper ni autorización de4.3. El piloto se cerró
con intervención manual de formato; no demuestra un flujo desatendido sin reparaciones.

Nota posterior2026-11-04: el usuario autorizó implementar4.3. Su integración con el
runner descubrió una incompatibilidad de interfaz no cubierta por los nueve tests4.2:
la estrategia espera columna timestamp y el runner usa DatetimeIndex. El recibo4.2
se conserva; no certificaba compatibilidad total ni rentabilidad. El backtest fallido
y la validación previa que ahora lo bloquea están en [paso4.3](orchestration-step-4.3.md).
