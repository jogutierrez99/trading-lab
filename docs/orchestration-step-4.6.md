# Paso4.6: preparación de una prueba integrada nueva

Actualización posterior: [corrección de rutas y repetición real autorizada](orchestration-step-4.6-path-recovery.md),
NOTICE_PREPARED con presupuesto3/3, sin envío. La historia de preparación y del bloqueo
original se conserva debajo; no confundirla con el resultado posterior.

Estado inicial2026-11-04: implementado y verificado con ejecutable Codex **simulado**.
Preflight local real correcto, sin invocar Codex. Arranque real posterior autorizado
expresamente por el usuario desde esta sesión: bloqueado antes del modelo por rutas
largas Git/Windows. **4.6 no cerrado**; ver evidencia al final.
El cierre4.5 reconstruyó un piloto histórico con reparaciones manuales; no equivale
a esta nueva prueba. No se envía Telegram ni se llama a un auditor IA.

## Conexión añadida

Antes existían comandos separados: register, prepare/run, prepare-execution,
validate-execution/run-execution, audit y notification-preview. verify-pilot4.5
es una consulta histórica, no un ejecutor. Ahora circuit-run enlaza los componentes
existentes, sin otro motor ni cambios a protocolos financieros:

registro → Codex → tests/lint/formato/compatibilidad nativa → fixture sintética →
reserva/validación/runner Python → cobertura → auditoría determinista → outbox/preview.

CircuitRequest1.0 incorpora HypothesisManifest e ImplementationPlan vigentes.
SQLite de orquestación migra aditivamente v5→v6: solo tabla circuits de identidad,
enlaces, intención de etapa y checkpoints; almacenamiento experimental sin cambios.
ReadOnlyStore conserva consultas v5/v6 sin migración. No se crean componentes futuros.
El checkout principal no recibe estrategia ni YAML nuevos: Codex trabaja en worktrees;
el runner utiliza copias aisladas y resultados propios. El YAML entregado debe seguir
disabled; el executor registra la adaptación identificada a su copia de ejecución.

## Nueva ficha técnica y comprobaciones

examples/orchestration/circuit46.json define circuit46_pulse_001 / technical_circuit_pulse_001,
target integration_candle_pulse_v1, versión1.0.0, parámetros vacíos y LONG_ONLY spot.
No clona el piloto manual_engulfing_breakout_v1 ni reinicia sus3/3 intentos.
No hay una estrategia operativa añadida: la plantilla de tests es exclusivamente
una implementación de referencia para el ejecutable simulado.

Contrato nativo: OHLCV con DatetimeIndex UTC,1h, sin columna timestamp; primeras20
observaciones sin señales. Entrada: vela alcista tras vela anterior no alcista y
diferencia de índice de una hora; salida: vela bajista. Short siempre falso.
Sin parámetros ajustables, hipótesis económica ni selección por rentabilidad.
La ficha contiene las reglas completas; Codex debe entregar módulo/YAML/tests y
recibo, con metadata created_at explícitamente UTC, no una fecha sin timezone.

La verificación nativa existente incorpora, solo para este contrato técnico,
un oráculo independiente de señales: warmup, índice, doji, gaps, entradas/salidas,
short falso, causalidad por prefijos e inmutabilidad de OHLCV. Un test generado que
repita una implementación errónea no basta para superar este control. No se añade
timestamp al dataframe ni se cambia el motor para compensar errores.

Dos datasets locales generados determinísticamente,164 velas cada uno (20 de
warmup+144), enero2000: BTC con pulsos y ETH doji como control sin operaciones.
El runner ordinario ejecuta TRAIN/VALIDATION/TEST **sintéticos**,48h por segmento,
seis casos en total. Estas etiquetas son divisiones de datos fabricados; no se leen
TEST ni holdouts históricos reservados. Cada caso BTC debe cerrar operaciones y
cada caso ETH debe tener cero. Los fills, salidas, costes y etiquetas son los nativos
del laboratorio; no se exige beneficio, PASS, PF ni Sharpe. Fuente del generador,
datasets, procedencia y configuración quedan fijados con hashes.

## Presupuesto, estados y recuperación

Límites congelados y visibles en doctor:

| Recurso | Límite |
|---|---|
| Implementación |1 intento inicial + hasta2 reparaciones técnicas, máximo3|
| Cada intento / comando de check |300s /45s|
| Validación / ejecución Python |60s /120s|
| Backtests / velas / datos |6 /328 /2000000 bytes|
| Invocación del conector |1500s; se comprueba entre etapas|
| Auditoría / Telegram |DETERMINISTIC_ONLY /PREVIEW_ONLY|

No es un límite monetario de Codex: coste/tokens, CPU y RAM no tienen aquí caps
efectivos. La contabilidad del auditor API no se utiliza porque no se hacen llamadas.
Solo FAILED/TIMED_OUT con retry_allowed del adaptador y proceso detenido permite
reparación. Autenticación, sandbox/permisos, alcance y BLOCKED no se reintentan para
forzar acceso. Cada intento conserva sus archivos, errores y recibos; el nuevo
worktree recibe el diagnóstico técnico por el mecanismo de reparación existente.
No hay repair-format, edición manual ni cambio de reglas para mejorar resultados.
Si la incompatibilidad se descubre después de aceptar la entrega o falla el runner,
se bloquea: no se reparan estrategias ni se repiten backtests automáticamente.

CircuitRunner persiste intenciones antes de arrancar procesos y enlaza IDs exactos;
recibos por etapa y resultado final inmutables, con SHA256. Repetir circuit-run
con la misma ficha consulta el circuito sin nuevas llamadas. No se puede cambiar
ficha, backend, base o procedencia simulada para reiniciar el presupuesto. Solo un
conector activo mediante lock; se conservan las reservas transaccionales del executor
y el límite global de un trabajo pesado. Codex termina antes del backtest Python.

Estados: PREPARED/RUNNING, NOTICE_PREPARED, BLOCKED o UNCERTAIN. El resultado separa
success_on_initial_attempt y success_after_repair. BLOCKED demuestra control, no
éxito completo. Un UNKNOWN/SENDING de outbox se muestra como UNCERTAIN sin enviar
ni reconciliar automáticamente. DRAFT exige cero envíos en esta prueba.

Una interrupción se inspecciona con circuit-show. --resume es una orden explícita,
no un retry ciego: un resultado ya SUCCEEDED puede recuperarse sin ejecutar otra vez.
Un modelo/ejecución inciertos requieren primero los comandos reconcile o
reconcile-execution existentes y revisión de procesos/recibos. Una auditoría parcial
requiere audit-reconcile. No repetir envíos inciertos. No editar archivos ni recibos
para desbloquear esta prueba: si necesita reparación manual, conservarla como bloqueada
y revisar el encargo por separado. No crear otro ID para eludir su presupuesto.

## Inicio posterior por el operador

Ejecutar en **PowerShell externo**, después de revisar estos cambios. No se ha
lanzado Codex real de forma anidada durante el desarrollo. Usar las mismas variables
y ficha para todos los comandos. Los datos/resultados quedan fuera de OneDrive.

```powershell
$repo = 'C:\Users\joshu\OneDrive\Escritorio\WEBS\Back_testing\trading-lab'
$db = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3'
$out = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL46'
$codex = 'C:\Users\joshu\AppData\Local\OpenAI\Codex\bin\b6c7fc9497179c98\codex.exe'

# Diagnóstico previo offline: no modelo, login, red ni migración SQLite.
python -B "$repo\scripts\orchestrator.py" --db $db circuit-doctor "$repo\examples\orchestration\circuit46.json" --repo $repo --artifacts $out --codex-executable $codex

# Única orden inicial del recorrido real (no ejecutada en esta entrega).
python -B "$repo\scripts\orchestrator.py" --db $db circuit-run "$repo\examples\orchestration\circuit46.json" --repo $repo --artifacts $out --codex-executable $codex

# Consulta sin modelo ni envío.
python -B "$repo\scripts\orchestrator.py" --db $db circuit-show circuit46_pulse_001
```

Doctor comprobó localmente base131ffaa101f7d04d81dcb47936142802ebba0a4b,
rutas libres, ejecutable resuelto y ausencia de trabajo activo/incierto. No comprobó
autenticación ni éxito futuro del sandbox; son requisitos de la ejecución posterior.
El adaptador mantiene workspace-write y aprobaciones never, sin acceso irrestricto
ni herramientas de red para la tarea. La CLI autenticada accede a su proveedor para
implementar; la prohibición de APIs de modelos aplica al auditor, que sigue determinista.
La ruta versionada del binario puede cambiar tras una actualización: volver a resolverla
antes de iniciar, sin cambiarla a mitad de un circuito. Telegram no necesita credenciales
para preparar preview. No ejecutar notification-send como parte de esta aceptación.

Solo tras inspección/reconciliación apropiada, si procede:

```powershell
python -B "$repo\scripts\orchestrator.py" --db $db circuit-run "$repo\examples\orchestration\circuit46.json" --repo $repo --artifacts $out --codex-executable $codex --resume
```

## Pruebas de preparación

Pruebas dirigidas con SQLite y Git temporales y Codex simulado, pero validadores,
runner sintético, auditor y outbox reales. No mocks del motor ni llamadas a servicios.
Cobertura: éxito al primer intento; reparación permitida y éxito segundo intento;
agotamiento3/3; incompatibilidad timestamp; permisos sin retry; interrupción después
de backtest finalizado y recuperación sin duplicarlo; intención modelo incierta sin
segundo arranque; doctor sin efectos; outbox incierta sin envío; expediente previo
con tres intentos conservado. Contratos rechazan ampliación de presupuesto, envío,
MODEL_ASSISTED y volumen extra; migración aditiva conserva registros previos.

```powershell
$tmp = 'C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85'
python -m pytest tests/unit/test_circuit_contracts.py tests/unit/test_pilot_verification.py tests/unit/test_audit_orchestration.py tests/unit/test_orchestration.py tests/unit/test_execution_contracts.py -q -p no:cacheprovider --basetemp "$tmp/u46b"
python -m pytest tests/integration/test_circuit_orchestration.py -q -p no:cacheprovider --basetemp "$tmp/c46e"
python -m pytest tests/integration/test_codex_orchestration.py::test_repair_limit_frozen_plan_and_prior_artifacts -q -p no:cacheprovider --basetemp "$tmp/b46"
python -m ruff check .
python -m ruff format --check .
python -m pip check
git diff --check
```

**136 casos distintos aprobados**:127 unitarios (28.05s), ocho integraciones4.6
(153.91s) y una regresión4.2 de presupuesto/artefactos (9.41s). Ruff global, formato
485 archivos, pip check y git diff --check correctos. No se ejecuta suite completa.
Consulta real readonly posterior VERIFIED_HISTORICAL_TECHNICAL_PILOT, cinco etapas
VERIFIED y presupuesto3/3 intacto. Requirió lectura del worktree externo fuera del
sandbox de esta sesión; la restricción inicial no era corrupción de las evidencias.
El comprobante de preparación separado aporta hashes y preflight; no es un recibo
de ejecución real4.6.
Un fixture simulado inicial falló por metadata created_at sin timezone y consumió
correctamente sus tres intentos temporales; se corrigió la preparación de la fixture
entre pruebas. No fue una intervención durante un recorrido real.

## Evidencia necesaria para cerrar después

Revisar circuit-show y circuit-status_*.json: procedencia real, IDs coherentes,
intentos1–3 y diagnóstico de cada reparación, sin intervención manual. Examinar
requests, prompts, stdout/stderr, diff, archivos finales y recibos IMPLEMENTED_VERIFIED;
pruebas nativas y hashes sin cambios posteriores. Verificar fixture/procedencia,
copia de configuración, seis casos y cobertura de trades/cero trades, run_id y recibo
SUCCEEDED. Examinar auditoría COMPLETED_WITH_LIMITATIONS/NO_DECISION y aviso DRAFT,
cero intentos de envío, texto de preview. Comprobar checkout principal y ausencia de
procesos hijos, expediente anterior inalterado y presupuesto3/3 preservado.

Solo NOTICE_PREPARED con toda esa evidencia acredita el nuevo recorrido técnico
completo. Un bloqueo gestionado se documenta como tal. La evidencia sintética no
acredita rentabilidad, robustez, validación económica ni autorización demo.
Auditor IA real y decisión2/3 estrategias diarias pendientes; reservar presupuesto
para reparaciones según consumo/fallos/reintentos reales. No activar programación.
## Arranque real autorizado: bloqueo de preparación

Tras autorizar expresamente el usuario la excepción de llamada anidada desde esta
sesión, se ejecutó una única orden circuit-run el2026-11-04T21:31UTC. Se mantuvieron
sandbox, límite1+2, datos sintéticos, auditor determinista y Telegram preview.
No se modificó código durante el recorrido ni se aplicaron reparaciones manuales.

- Circuito: circuit46_pulse_001, tarea task_ffbc83f6803643858b093c335a8efbdd.
- Intento: attempt_cdb14421f9404a6394e9c5e01af8458c, número1, BLOCKED,
  retry_allowed=0. Cero reparaciones, modelo no iniciado, child_pid nulo.
- Etapas alcanzadas: REGISTER y PREPARE. Sin backtest, auditoría ni nuevo aviso/envío.
- Error literal relevante: `unable to create file research_results/cross_family/comparison/20261004T150626Z-4dc5ce45836d/train_ranked_examples.json: Filename too long`;
  también `fatal: cannot create directory at 'research_results/range_mean_reversion/range_mean_reversion_v1_btc_eth_15m/20261004T150205Z-7a46d39881da': Filename too long`.
- Causa demostrada: el checkout del worktree falla al combinar la raíz profunda de
  artefactos y rutas ya existentes del repositorio. No es evidencia de falta de
  permisos del sandbox ni de error de estrategia. core.longpaths no estaba configurado.
- Posible corrección a preparar/revisar por separado: Git `-c core.longpaths=true`
  por comando y/o una raíz de worktree más corta, con regresión y diagnóstico previo
  de longitud. No se ha aplicado ni probado esa solución, no se ha alterado el intento
  bloqueado y no se ha relanzado. Requiere resolver explícitamente su recuperación
  conservando identidad, presupuesto y recibos; no duplicar la tarea.

SQLite migró v5→v6; todas las filas preexistentes de sus11 tablas se conservaron
idénticas.333 archivos de motor/configs idénticos y estado del checkout principal
sin cambios al terminar el comando, antes de añadir esta nota documental.
Presupuesto anterior3/3 intacto. Git no dejó registrado un nuevo worktree exitoso;
se conserva la evidencia y la rama creada, sin limpieza destructiva.

Recibo: circuit-status_6814088fc12841e6a3a92e9395674891.json,
SHA256 `67931fa4b24eaeec132df68e7bb068468bc1f2d0f99b9487e68dc6987264d61a`,
en la raíz TL46/circuit46_pulse_001 documentada arriba.
Comprobación separada: `C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85\step46-real-blocked.json`.
El bloqueo gestionado acredita la parada, **no el éxito completo del circuito**.

