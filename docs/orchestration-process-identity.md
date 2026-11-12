# Identidad de procesos tras4.6

Corrección del control PID-only que confundió un modelo simulado ya terminado con
svchost.exe al reutilizar Windows su PID. Solo infraestructura de orquestación;
no cambia señales, motor, protocolos, clasificación económica ni presupuestos.

## Identidad y comprobación

process_identity.py distingue RUNNING, EXITED, REUSED, UNKNOWN y NOT_RECORDED.
Se conserva PID y tiempo de creación nativo. Windows usa GetProcessTimes/FILETIME:
entero de64 bits en unidades100ns desde1601UTC, serializado como cadena decimal
para no perder precisión por floats/JSON. No se convierte a hora local, ISO redondeado
ni segundos de pared;100ns es la unidad del dato, no una promesa de resolución del reloj.
PID, creación y estado se consultan sobre el mismo handle. El estado de salida usa
WaitForSingleObject, evitando confundir un exit code259 con STILL_ACTIVE.

Linux usa starttime de /proc/PID/stat en ticks nativos desde boot más boot_id.
No convierte ticks a datetime ni compara valores redondeados. El supervisor necesita
pidfd/procfs; en otros POSIX se bloquea antes de lanzar, sin fallback de señales por PID.
Implementación Linux incluida, no certificada en este portátil Windows.
No se usan nombres de proceso, argumentos, rutas ejecutables ni usuario como prueba
de identidad; no se leen credenciales ni se registran comandos de procesos ajenos.

Resultados:

| Observación | Interpretación |
|---|---|
| PID y nacimiento exactos, handle no señalado | RUNNING: no reconciliar como detenido |
| PID ausente o handle original señalado | EXITED: terminó; no demuestra éxito |
| PID presente, nacimiento distinto en el mismo reloj nativo | REUSED: el ocupante actual es ajeno; no actuar sobre él |
| Acceso denegado, fallo de consulta, reloj incompatible o identidad incompleta con PID existente | UNKNOWN: conservar incertidumbre y bloquear acciones dependientes |
| Sin PID ni identidad registrados | NOT_RECORDED: no prueba que un trabajo RUNNING/UNKNOWN nunca arrancase |

pending aplica esta política en implementación, ejecución, reparación manual y circuito:
inspección, verificación de entregas, preparación/reintento y reconciliación. Un trabajo
RUNNING/UNKNOWN sin PID sigue pendiente. Las consultas exponen process_state separado
del status histórico: no reescriben un estado o recibo congelado por una consulta actual.
No cambia automáticamente UNKNOWN a SUCCEEDED ni convierte PID obsoleto en permiso
para relanzar un modelo/backtest. Reconciliar sigue exigiendo orden explícita, proceso
original detenido y recibos/artefactos válidos. Sin evidencia de ejecución, sigue UNKNOWN.

## Propiedad de procesos y terminación

run_process obtiene la identidad del handle original de Popen y la persiste mediante
on_start **antes de reanudar el hijo Windows suspendido**. Cada fase supervisada
(modelo, checks, bridge nativo, validación y runner) actualiza conjuntamente PID e
identidad del trabajo; sus resultados JSON conservan también su propia identidad.
No se mezclan el PID de una fase y el nacimiento de otra.

En Windows, el hijo se asigna a un Job Object propio antes de ejecutar. Timeout,
interrupción y errores cierran ese objeto del kernel y sus descendientes; la limpieza
residual usa exclusivamente el handle original de Popen. No se reabre un PID para
matarlo, no hay taskkill ni enumeración/terminación por nombre. Cerrar un job propio
o terminar por el handle original no puede adoptar el ocupante nuevo de un PID.
Se confirma además la señalización del handle original antes de publicar el resultado.
Un fallo al capturar/persistir identidad no permite continuar; el llamador conserva
UNKNOWN y se limpia solamente la capacidad de proceso/job que creó el supervisor.

En Linux se conserva pidfd y no se recoge al líder hasta limpiar el grupo: su PID
retenido evita que el grupo numérico se reasigne entre comprobación y señal.
Solo se señala el grupo cuando coincide el nacimiento; el fallback del líder usa
pidfd, nunca un PID reabierto. No se ofrecen operaciones para terminar arbitrariamente
un proceso persistido después de reiniciar el coordinador. Si no se puede probar
identidad/terminación, hace falta inspección externa; no se habilita acceso irrestricto.

## Persistencia y registros antiguos

Migración aditiva SQLite v7: process_identity_json nullable en attempts, executions
y manual_repairs; sin tablas nuevas ni cambios al almacenamiento de experimentos.
La migración deja NULL en registros existentes y no modifica presupuestos ni recibos.
ReadOnlyStore admite v5/v6/v7 sin inicialización/migración. En esta entrega la base
real permanece v6; solo se migra cuando el operador use después un comando de escritura.

Un PID histórico sin tiempo de creación no se completa con el proceso actual, con
started_at_utc del coordinador ni con su nombre. Si el PID ya no existe, puede saberse
que el proceso original no sigue allí; si existe, identidad UNKNOWN aunque se llame
svchost.exe. Los recibos antiguos siguen siendo los originales y se evalúan según sus
contratos. Falta de atributos puede limitar una reconciliación, no justificar inventarlos.

## Verificación

Pruebas usan exclusivamente hijos Python temporales y probes simulados. No se
termina ni se modifica ningún proceso del sistema. Se cubren nacimiento exacto,
salida, diferencia de un solo tick, PID reutilizado, acceso denegado, identidad
incompleta/malformada, legado y migración. Otro hijo temporal ajeno sobrevive a la
limpieza del supervisado. Las integraciones comprueban que reconciliar REUSED usa
recibos existentes sin otra llamada al ejecutable simulado ni otro runner; si falta
el recibo, no establece éxito. RUNNING/UNKNOWN/incompleto no permiten reconciliación.

Primer pase unitario:15 aprobados,2 fallos. Uno observó el hijo como RUNNING justo
después de un timeout; se añadió confirmación explícita sobre el handle original.
El otro esperaba la forma de filas anterior a añadir la columna nullable; se corrigió
la expectativa de migración conservando los valores antiguos y comprobando NULL.
Repetición dirigida17/17; grupo unitario final **139/139** (53.82s), incluidas
regresiones de sqlite3.Row y persistencia antes de reanudar un hijo Windows.

Primer grupo completo de integración: **67 aprobados,4 fallos** (1022.35s).
Un defecto real de adaptación sqlite3.Row/dict en pending se corrigió, con regresión.
Dos expectativas antiguas permitían reconciliar RUNNING/UNKNOWN sin PID/identidad:
se adaptaron a conservar UNKNOWN, no se debilitó la política. Otro caso se detuvo
antes de la interrupción simulada al no poder acreditar que la implementación estaba
detenida; no se interpreta como backtest válido ni se relanza automáticamente.

Segunda ejecución completa por archivos: **69 aprobados,2 fallos**. Uno no llegó
al runner porque la identidad de la entrega temporal no pudo verificarse; la consulta
posterior fue EXITED, sin atribuir retrospectivamente una causa del SO no registrada.
El otro era una expectativa del mensaje de bloqueo: al conservar UNKNOWN, la reserva
global bloquea antes que la deduplicación de reparaciones. Se corrigió esa expectativa.
Los pases por archivo fueron35/35 implementación (330.49s),21/22 ejecución (510.68s),
4/5 reparación (187.62s) y9/9 circuito (314.49s).

Las fixtures Windows conservan ahora los handles originales de sus propios hijos
hasta terminar cada test: los casos de éxito no dependen de que Windows entregue
un PID liberado a un servicio protegido. No se falsean tiempos ni se reemplazan los
probes reales del camino satisfactorio. Reutilización/acceso denegado se simulan
explícitamente en sus casos negativos, que conservan UNKNOWN cuando corresponde.
Repetición final de **los cuatro archivos completos**: **71/71 aprobados**, sin
repetir únicamente casos seleccionados. Implementación35/35 (329.11s), ejecución22/22
(483.56s), reparación5/5 (187.06s), circuito9/9 (311.60s), bases temporales pidg0–pidg3.
Con las139 unitarias: **210 casos distintos aprobados**, sin sumar repeticiones.
Ruff global, formato491 archivos, pip check y git diff --check correctos.
No se ejecuta la suite completa del laboratorio. No se ocultan los fallos anteriores.

Migración adicional comprobada sobre una copia consistente de la base real:12 tablas
y97 filas mantienen todos sus valores previos; todos los atributos nuevos históricos
siguen NULL. La base original conserva bytes y versión6,140 JSON anteriores del
expediente4.6 y333 archivos motor/configs mantienen sus hashes; ambos presupuestos3/3.

```powershell
$tmp = 'C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85'
$run = [guid]::NewGuid().ToString('N').Substring(0, 8)
python -m pytest tests/unit/test_process_identity.py tests/unit/test_circuit_contracts.py tests/unit/test_pilot_verification.py tests/unit/test_audit_orchestration.py tests/unit/test_orchestration.py tests/unit/test_execution_contracts.py -q -p no:cacheprovider --basetemp "$tmp/$run-u"
foreach ($suite in 'codex_orchestration', 'execution_orchestration', 'manual_repair', 'circuit_orchestration') {
    python -m pytest "tests/integration/test_$suite.py" -q -p no:cacheprovider --basetemp "$tmp/$run-$($suite.Substring(0, 1))$($suite.Substring(1, 1))"
}
python -m ruff check .
python -m ruff format --check .
python -m pip check
git diff --check
```

No se ejecutan Codex real, backtests del piloto, Telegram, APIs de modelos, OKX,
scheduling, push o merge. Las integraciones reutilizan runners reales solo con
fixtures sintéticas en temporales independientes. No certifican economía ni demo.

Referencias de semántica nativa:
[Microsoft GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes),
[Python pidfd_open](https://docs.python.org/3.13/library/os.html#os.pidfd_open),
[Linux proc_pid_stat](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html).

Archivos: nuevo process_identity.py; integración en processes.py, implementation.py,
execution.py, execution_inputs.py, manual_repair.py, circuit.py, store.py y readonly.py.
Nuevo test_process_identity.py y process_test_support.py; actualización de las cuatro
integraciones afectadas y fixtures de migración test_circuit_contracts/test_audit_orchestration.
README, PROJECT_STATE, ARCHITECTURE, WORKFLOW y enlace desde el diagnóstico4.6 actualizados.
Comprobante local separado: `C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85\process-identity-verification.json`.
