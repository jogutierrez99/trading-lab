# Reparación manual del piloto aplicada y ejecutada — 2026-11-04

El usuario autorizó ejecutar la propuesta previamente revisada («ejecutalo tu y
sacame resumen»). Se registró una reparación técnica manual1.0.1, con identidad
nueva, y se completó el circuito4.3 con datos sintéticos. **Compatibilidad técnica
verificada; no validación económica ni autorización demo.**

## Resultado real

| Identificador | Valor |
|---|---|
| Tarea conservada | task_7c894d7e4dca4f24a164632a703d5d5d |
| Implementación origen conservada | attempt_cb2c94564a6f464f95faaeee58bae9a5 |
| Nueva implementación manual | repair_9dd2e6ba361d4de5baf13db554ed81fd |
| Ejecución nueva | execution_0e7131ba2d0344aeb6918648fda75af0 |
| run_id nativo | 20261104T005019Z-7428e718b634 |
| Estado implementación y ejecución | SUCCEEDED |
| Resultado del runner | COMPLETE,3 backtests,0 fallidos |
| Retorno del coordinador | 0 |

La corrección sustituye candles.timestamp.diff() por
candles.index.to_series().diff(), conservando comparación1h, warmup100 y todas las
reglas. Módulo y perfil pasan a1.0.1. El perfil entregado sigue deshabilitado; se
habilita únicamente una copia identificada para backtesting. No se modificó el
motor ni se añadió columna timestamp.

La reparación ejecutó las12 regresiones propuestas (incluido un recorrido nativo
con una entrada comprobada en la apertura siguiente), lint, formato y probe nativo.
Después se generó un plan sintético nuevo, se reservó la ejecución, se aprobó FULL
y la interfaz, se ejecutó el runner real y se consultó el resultado en otro proceso.

Límites de esta ejecución:3 backtests,244 velas,120s para run,60s para validación,
1000000 bytes de datos/procedencia. No grids ni selección de parámetros.
Los tres periodos nativos usan solo velas generadas; no se consumió ningún holdout
histórico. La muestra final del helper no produjo operaciones: filtros nativos
rechazan los3 resultados por closed_trades:min=1 y registran0 supervivientes.
Se conservan esas etiquetas. COMPLETE no equivale a PASS económico.

## Registro y presupuesto

SQLite migra transaccionalmente v3→v4, con respaldo previo. Se añade manual_repairs
y executions.manual_repair_id con FK/trigger que exige misma tarea, origen y reparación
SUCCEEDED. Los intentos de modelo conservan CHECK(number BETWEEN1 AND3), todas sus
filas/IDs/estados y los contadores originales: **3/3 usados,0 llamadas de modelo nuevas**.
No se creó otra tarea/candidata ni se usó repair-format.

La ruta apply-technical-repair admite exclusivamente esta operación y los SHA256 de
origen/patch/resultado revisados. Un único registro por origen/operación; no sirve para
reparaciones arbitrarias, relanzar modelos o resetear presupuestos. Exige autor y
autorización explícitos. Comparte lock/reserva con implementación y ejecución;
UNKNOWN mantiene el slot hasta reconciliación manual. No hay reintento automático.

El autor registrado es el asistente Codex de este chat, bajo autorización del usuario.
El recibo es ManualImplementationReceipt con estado IMPLEMENTED_VERIFIED, sin un
ModelDelivery nuevo atribuido falsamente a Codex CLI. Conserva la referencia/hash del
recibo origen, el formato heredado y la enmienda técnica1.0.0→1.0.1. La ficha inmutable
no se reescribe. El descriptor del checker conserva el ordinal del intento origen
como procedencia; no es un cuarto intento de modelo ni reinicia su contador.

Los requests4.3 identifican la nueva implementación, su recibo y origen manual; la FK
attempt_id conserva el padre histórico y manual_repair_id selecciona explícitamente
la nueva entrega. El resolver verifica la reparación y sus archivos antes de cada
ejecución. Los FAILED/BLOCKED anteriores no se redirigieron ni reactivaron.

## Evidencia y conservación

Raíz canónica local (fuera de OneDrive):
C:/Users/joshu/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/TL43/m589a0a/.

- orchestrator-before-manual-repair.sqlite3: respaldo de la base v3.
- before.json y acceptance.json: snapshots/comparaciones y comandos por etapa.
- repairs/repair_9dd2e6ba361d4de5baf13db554ed81fd/: controles, autorización/autor,
  patch, baseline/final-tree, regresiones, runtime archivado, native-evidence y recibo.
- executions/execution_0e7131ba2d0344aeb6918648fda75af0/: request, copias/runtime,
  validación, resultado de proceso, artefactos nativos y recibo de ejecución.

SHA256 del recibo manual:
e0b9b641241ed653c5a1dddcd4c509ab8b70b838ffcae3ef3cbbeb86495b626c.
SHA256 del recibo de ejecución:
62ef4217dadb793df108fa7e772b0ecd8ce876c9e5dba2ef9671c9d5f408147d.

Resumen verificable:
C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/pilot-repair-applied-acceptance.json.

Se contrastaron filas previas de candidates/tasks/attempts/submissions/events y
executions (columnas históricas): conservadas. Worktree y todos los artefactos del
intento origen idénticos por hash; datos sintéticos sin cambios; recibos/artefactos
finales contrastados. integrity_check=ok, sin FK inválidas. Checkout principal sin
cambios durante la aceptación respecto al baseline posterior a los cambios autorizados
del coordinador. Todos los PID registrados detenidos,0 trabajos activos. Sin modelos,
datos reservados, descargas, Telegram, OKX, programación, push ni merge. No se avanzó4.4.

## Pruebas y cambios de código

91 casos distintos del repositorio aprobados en grupos, sin suite completa:

- Ingesta4.1, implementación4.2 y contratos4.3:83 aprobados,244.12s.
- Vía manual:4 aprobados,116.39s; posteriormente happy-path y recuperación UNKNOWN,
  2 aprobados,74.86s (un caso nuevo, una repetición). Total5 casos distintos.
- Última comprobación de identidad/FK incorrecta dentro del happy-path:1 aprobado,
  45.57s (repetición, no caso nuevo).
- Ejecutor4.3 afectado (éxito, reserva y reconciliación):3 aprobados,72.18s.

Las regresiones rechazan autorización vacía, patch alterado y archivos modificados;
comprueban atomicidad ante fallo de evento, evidencia nueva sin alterar origen,
FK de ejecución exclusiva, conservación de3 intentos/1 tarea, duplicados y retención
del slot en UNKNOWN. Ruff global, formato, pip check y git diff --check correctos.

Cambios: manual_repair.py, migración/store v4, resolver y procedencia en contratos y
ejecutor/smoke, callbacks/guards compartidos en implementation.py y comandos CLI.
Fixtures históricas están en tests/fixtures/manual_pilot_legacy; son test data, no
otra estrategia operativa. Se preservan motor/configs operativas y cambios previos
sin commit. La propuesta y sus pruebas anteriores permanecen como evidencia histórica.

## Consultas seguras, sin relanzar

Desde la raíz del proyecto:

```powershell
$db = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3'
python scripts/orchestrator.py --db $db technical-repair repair_9dd2e6ba361d4de5baf13db554ed81fd
python scripts/orchestrator.py --db $db execution execution_0e7131ba2d0344aeb6918648fda75af0
python scripts/orchestrator.py --db $db show task_7c894d7e4dca4f24a164632a703d5d5d
```

La orden apply-technical-repair ya se ejecutó una vez y rechaza su duplicación. No
repetir el apply ni tocar contadores. Para inspeccionar opciones:

```powershell
python scripts/orchestrator.py apply-technical-repair --help
python -m pytest tests/integration/test_manual_repair.py -q
```

En este entorno Windows se usaron temporales explícitos cortos (mr1..mr6) bajo la
carpeta de visualizaciones y -p no:cacheprovider. Si una reparación futura distinta
fuera necesaria, requiere otra revisión/autorización y diseño acotado: esta vía no
permite sustituir patches o crear reparaciones automáticas para mejorar resultados.
