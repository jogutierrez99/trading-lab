# Paso4.6: rutas largas y repetición real autorizada

Actualización posterior: el [endurecimiento de identidad de procesos](orchestration-process-identity.md)
resuelve en código y pruebas el control PID-only señalado abajo. No repite esta
ejecución real ni modifica sus recibos; sus registros históricos no reciben atributos inventados.

2026-11-04. Resultado real: **NOTICE_PREPARED**, código0, tras recuperación de
infraestructura explícitamente autorizada y una reparación técnica automática.
No es éxito al primer intento ni demuestra que el arranque original fuese desatendido.
Después de la corrección y de la orden --resume no hubo ediciones manuales de estrategia.

## Corrección y recuperación

workspaces.git aplica `-c core.longpaths=true` por comando, junto a los controles
existentes de hooks/fsmonitor. No cambia configuración global/local ni permisos.
La regresión crea un worktree Git real con archivos de más de260 caracteres,
preserva su contenido y comprueba que core.longpaths local sigue false.

El intento1 falló antes de request.json y de lanzar modelo. No se elimina ni se
simula una entrega: se conserva el recibo original de preparación BLOCKED y el
informe step46-real-blocked.json. La orden existente reconcile --outcome failed
--confirm-stopped registra autorización/motivo y eventos, y permite consumir el
siguiente turno. No reinicia ningún contador ni duplica candidata/tarea.

Para ese caso concreto, Coordinator._prior_plan recupera el plan del CircuitRequest
ya sellado: verifica hash SQL/archivo, base, repo, ficha y recibo PREPARE original
con Filename too long, request ausente y child_pid nulo. Requiere FAILED y retry_allowed
tras reconciliación explícita. El camino normal conserva la validación de request.json.
CircuitRunner admite --resume de un bloqueo reconciliado reparable, sin ejecución
previa y con presupuesto restante. Un BLOCKED sin reconciliar sigue sin reintento.
No se toca el sandbox ni se habilitan reintentos automáticos de permisos.

Archivos de código cambiados: workspaces.py, implementation.py y circuit.py en
src/trading_lab_orchestration. Tests: tests/unit/test_worktree_paths.py y
tests/integration/test_circuit_orchestration.py. README, PROJECT_STATE y guía4.6
actualizan la evidencia; motor, configuraciones operativas y forward sin cambios.

## Cadena real

| Turno | Identidad | Resultado |
|---|---|---|
|1|attempt_cdb14421f9404a6394e9c5e01af8458c|Preparación Git bloqueada por longitud; sin modelo. Reconciliado FAILED con evidencia original intacta|
|2|attempt_b3714709ff8a4ed88239d07831290482|Modelo entregó;12 tests pasan; Ruff E501 en una línea de test. FAILED técnico|
|3|attempt_7aa5b8c7cb114020b695d486ced856fb|Reparación automática,12 tests/lint/formato y contrato nativo correctos; IMPLEMENTED_VERIFIED/SUCCEEDED|

Presupuesto **3/3**, dos turnos de reparación contabilizados: recuperación de
infraestructura y reparación técnica. Dos invocaciones reales del modelo. No hay
cuarto turno autorizado. El piloto engulfing anterior conserva su propio3/3.

- Circuito: circuit46_pulse_001.
- Candidata: cand_0f12f5bc5e8d47f3803f20ed592bf39e.
- Tarea: task_ffbc83f6803643858b093c335a8efbdd.
- Implementación final: attempt_7aa5b8c7cb114020b695d486ced856fb.
- Ejecución: execution_2d8298c1b93446baa47cabe986e5cef8, SUCCEEDED.
- Run:20261104T215604Z-5c15f4a2e853.
- Auditoría: audit_8bbfef6620204c32ba9d2f5dc1b0cc36,
  DETERMINISTIC_ONLY / COMPLETED_WITH_LIMITATIONS / NO_DECISION.
- Aviso: notice_50927e886a2545cdba0923bb37900c04, DRAFT,0 intentos, sin message_id.

Runner Python después de terminar Codex:6/6 backtests válidos,328 velas sintéticas,
seis operaciones cerradas BTC en cada segmento TRAIN/validation/test; cero ETH en
cada segmento. Resumen nativo conservado:3 filter_rejected (closed_trades:min=1),
survivors1, configuraciones2. No se exige ni se atribuye rentabilidad a este resultado.
No se leyeron datos históricos reservados ni se activó el YAML operativo.

Preview preparado (no enviado):

> Trading Lab — aviso TÉCNICO4.4. integration_candle_pulse_v1, versión1.0.0.
> Run20261104T215604Z-5c15f4a2e853. Sintético:True.
> Auditoría COMPLETED_WITH_LIMITATIONS. Dictamen económico:NO_DECISION.
>18 operaciones cerradas por casos, no cartera agregada; evidencia insuficiente
>para concluir rentabilidad. Sin validación económica ni elegibilidad demo/paper.

El texto literal completo y su hash están en la outbox y el informe de verificación.
No se enviaron mensajes ni se llamaron APIs del auditor IA.

## Evidencia y conservación

Raíz: `C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL46\circuit46_pulse_001`.
Resultado: circuit-status_398519bc13c74e65b2ed8456a12315b7.json,
SHA256 `67d303c9217a9f81dfcf6da222ae70c3ff4d3cbecfd57c12ce1c73cb01670679`.
SHA256 informe auditor: `84e64e9e71a94144b7e835f782aeda6066bf163f7a0dd00b4c597f3a747554cc`.

Comprobante: `C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85\step46-real-recovered.json`,
SHA256 `de181981a654fc87cae26c31c62e85343622680f2707fcf518db27e2f1b55c89`.
Reverifica cadena final con auditor existente, hashes, diff limitado a los tres
archivos autorizados, seis casos y todos los recibos de etapa. Lectura no altera DB.
Todas las filas anteriores al primer arranque se conservan;333 archivos motor/configs
idénticos y HEAD principal131ffaa101f7d04d81dcb47936142802ebba0a4b intacto.
No push, merge, optimización, datos reservados, órdenes, OKX, forward ni scheduling.

## Pruebas y limitación detectada

18 casos distintos aprobados en grupos:9 (rutas Git+7 contratos+presupuesto4.2) y
9 integraciones de circuito, incluida recuperación de preparación con hashes originales.
Pase completo de integración:8 pasan y uno queda UNKNOWN; repetición aislada del
caso pasa (47.47s). No se oculta ese fallo inicial: el PID15592 del modelo simulado
había sido reutilizado por svchost.exe (creado21:51:12.624949UTC); el control conservador
por PID consideró la implementación todavía activa al finalizar el runner. No se
repite automáticamente el backtest incierto ni se falsea su recibo. El endurecimiento
de identidad de procesos sigue pendiente como asunto separado; esta corrección de
rutas no lo resuelve. No afectó a la repetición real, cuya evidencia sí se verificó.
La primera fixture de rutas exageraba también la raíz del worktree y alcanzó el
límite administrativo distinto `$GIT_DIR too big`; se ajustó la fixture para probar
el fallo real de rutas de archivos, con raíz corta y archivos largos.

Ruff global, formato487 archivos, pip check y git diff --check correctos. Sin suite
completa. No se suman las12 pruebas generadas por Codex a los18 casos del adaptador.
Comprobación final de procesos del circuito y último pase de tests: cero restantes.
La estrategia, YAML y test generados no existen en el checkout principal.
Éxito técnico tras recuperación documentada; no declarar éxito al primer intento,
rentabilidad, auditor IA desplegado ni autorización demo. La frecuencia2/3 diaria
y el presupuesto de reparaciones siguen pendientes; no se activa programación.

Consulta idempotente, sin otra llamada al modelo ni envío:

```powershell
python -B scripts/orchestrator.py --db 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3' circuit-show circuit46_pulse_001
```
