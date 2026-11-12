# Paso4.5: verificación integrada y cierre del piloto técnico

2026-11-04. **Cierre técnico del recorrido histórico verificado**, mediante la
implementación1.0.1 y las evidencias existentes. No es una nueva ejecución completa
ni automatización desatendida. No se inicia el paso5 ni se autoriza demo.

## Recorrido real comprobado

La consulta deriva hypothesis_id/candidate_id de SQLite, no de nombres supuestos.
No selecciona latest. Reutiliza los verificadores4.2–4.4 y fuentes congeladas:

| Etapa | Identidad real | Estado histórico / comprobación | Intervención y límites |
|---|---|---|---|
| Ficha/candidata | manual_engulfing_implementation_001 / cand_0b7f6f1e8580418887519e1f67c6ae10 | Manifest/fingerprint/submissions/events verificados | Ficha manual; no evidencia económica |
| Tarea/intentos | task_7c894d7e4dca4f24a164632a703d5d5d | SUCCEEDED; tres solicitudes congeladas vinculadas;3/3 consumido | Dos fallos anteriores conservados; presupuesto no reiniciado |
| Implementación | repair_9dd2e6ba361d4de5baf13db554ed81fd | IMPLEMENTED_VERIFIED; hashes finales/linaje comprobados | Reparación manual de formato AST idéntico y reparación semántica manual con identidad nueva |
| Ejecución | execution_0e7131ba2d0344aeb6918648fda75af0 / 20261104T005019Z-7428e718b634 | SUCCEEDED / COMPLETE,3 casos,0 trades por caso,3 rechazos nativos | Configuración/dataset/protocolo sintéticos; ninguna ejecución nueva |
| Auditoría | audit_bbac0e00b8e449d78599c5c2150430d5 | DETERMINISTIC_ONLY / COMPLETED_WITH_LIMITATIONS / NO_DECISION | Informe y observaciones congelados, referencias/hashes y gates contrastados |
| Telegram | notice_f1cedfa29db34e7dbf35bec3ba09c4dc | ACCEPTED,1 intento,message_id136 | Recibo local fijado por hash; sin nueva consulta/envío Telegram |

Estrategia manual_engulfing_breakout_v1 **1.0.1**, UTC/1h/warmup100 según entrega y
configuración verificadas. Experimento orchestration_technical_smoke, StudyBackend v1 /
lab_experiment_v1. Dataset generado, no historia Binance. PF/Sharpe null y etiquetas
nativas conservadas. El holdout original sigue CONSUMED; los periodos sintéticos
train/validation/test no acreditan independencia ni consumen nuevo TEST histórico.

## Código y decisiones

Nuevos archivos:

- src/trading_lab_orchestration/readonly.py: adapta las consultas existentes de Store
  a mode=ro/query_only y un único snapshot. No llama al constructor inicializador,
  no crea carpetas/SQLite, no migra y rechaza transacciones de escritura.
- pilot_contracts.py: solicitud/resultado1.0 estrictos, IDs explícitos, referencia
  Telegram con hash/ID esperado, límites de lectura, resultados por etapa y separación
  entre reconstrucción, nueva ejecución, IA, economía y autorización.
- pilot.py: verificación integrada, resumen Markdown y exportación nueva opcional.
  Reutiliza audit_evidence.review, resolvers originales y Auditor.inspect; no ejecuta
  run/validate/reconcile, doctor, modelos ni transportes. Comprueba relaciones de ficha,
  solicitudes3/3, implementación original/reparaciones, ejecución y todos los hechos
  de la auditoría frente a evidencia primaria. Contrasta outbox, texto/hash y recibo.
- examples/orchestration/pilot_verification.json: IDs/pins reales de este portátil.
  Es una solicitud local verificable, no una fixture portable ni otro experimento.
- tests/unit/test_pilot_verification.py:24 casos aislados nuevos.
- Esta guía. Informes y comprobantes se conservan localmente fuera del repositorio.

Cambios: cli.py añade **verify-pilot**; store.py reutiliza un snapshot ya abierto en
show (evita BEGIN anidado). El comportamiento ordinario sigue abriendo su snapshot
cuando no existe uno. README, AGENTS, PROJECT_STATE, ARCHITECTURE y WORKFLOW documentan
la consulta y el alcance. Sin tablas nuevas: SQLite permanece **v5**; ninguna migración.
No se creó otro coordinador, ledger ni estado operativo. El estado de verificación
solo describe el resultado de la consulta; un fallo nunca cambia el expediente.

La implementación inicial detectó BEGIN anidado al reutilizar show; se corrigió y se
añadió una regresión explícita de consultas repetidas dentro del mismo snapshot.
El diagnóstico de desarrollo quedó separado; no se reescribió evidencia histórica.

## Comandos exactos

Desde la raíz del repositorio, con la instalación editable existente:

```powershell
$db = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3'

# Resumen legible; sin credenciales, red, migración o cambios de estado.
python -B scripts/orchestrator.py --db $db verify-pilot examples/orchestration/pilot_verification.json --format text

# Resultado JSON versionado.
python -B scripts/orchestrator.py --db $db verify-pilot examples/orchestration/pilot_verification.json --format json

# Exportación explícita: carpeta nueva por consulta, nunca dentro de fuentes congeladas.
$out = 'C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85\step45'
python -B scripts/orchestrator.py --db $db verify-pilot examples/orchestration/pilot_verification.json --output $out
```

0 = VERIFIED_HISTORICAL_TECHNICAL_PILOT;2 = evidencia ausente, contradictoria,
incompatible o entrada inválida. El formato JSON es predeterminado. Sin --output,
la consulta solo imprime; -B evita caches bytecode. No carga.env ni necesita tokens.
Un fallo de exportación conserva el resultado JSON versionado con export_error y
código2; no reabre ni cambia los estados verificados.

La exportación genera pilot_verification.json, pilot_report.md y hashes.json en una
carpeta exclusiva verification_UUID, no un nuevo audit_id ni registros operativos.
Rechaza destinos en repo/SQLite/fuentes/datasets/resultados inspeccionados, incluso
si la consulta queda bloqueada. Si faltan controles de rutas para exportar con seguridad,
usar stdout sin --output. No sobrescribe informes. Un UUID/timestamp nuevo identifica
una nueva **consulta/informe**, no una repetición del circuito.

## Informe integrado generado

Verificación final: **verification_fa0b936f3e714b229eecc5a73c6b94b6**.
Resultado VERIFIED_HISTORICAL_TECHNICAL_PILOT; cinco etapas VERIFIED;
**2219 referencias** comprobadas. Se verificaron dos consultas simultáneas reales
con el mismo resultado, sin cambios de registros o bytes de SQLite.
Motor src/quant_lab y configs permanecieron idénticos. Ningún recibo anterior se alteró.

Directorio:
`C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85\step45\verification_fa0b936f3e714b229eecc5a73c6b94b6`.

- pilot_report.md SHA256:
  `d74a591e9d1a93176141d106e1346923b5af5f605cd26f3a4c234548f3ee577e`.
- pilot_verification.json SHA256:
  `7f79ebccacb6bfa0624698694c0243bca088e924892f9a2bc8bd584ffd080dab`.
- Comprobante separado de lecturas concurrentes, hashes DB antes/después y conteos:
  step45/verification_fa0b936f3e714b229eecc5a73c6b94b6-checks.json.

El JSON aporta referencias/hashes, ficha y candidata derivadas, protocolo/configuración/
datasets, métricas/etiquetas nativas, intervenciones y acciones pendientes. El Markdown
incluye la tabla por etapa. Fuentes4.4 y recibo Telegram siguen congelados y con sus hashes.

## Pruebas y controles de esta entrega

**121 casos distintos aprobados**, sin sumar repeticiones:
24 nuevos4.5 +44 auditoría4.4 +34 ingesta4.1 +18 contratos4.3 +1 regresión de presupuesto4.2.
No se ejecutó la suite completa ni tests del motor que generen nuevos backtests.

```powershell
$tmp = 'C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85'
python -m pytest tests/unit/test_pilot_verification.py tests/unit/test_audit_orchestration.py tests/unit/test_orchestration.py tests/unit/test_execution_contracts.py -q -p no:cacheprovider --basetemp "$tmp/p45g"
python -m pytest tests/integration/test_codex_orchestration.py::test_repair_limit_frozen_plan_and_prior_artifacts -q -p no:cacheprovider --basetemp "$tmp/b45"
python -m ruff check .
python -m ruff format --check .
python -m pip check
git diff --check
```

Primer grupo:120 aprobados. Regresión existente de presupuesto:1 aprobado,12.88s,
CLI **simulada**, tres llamadas simuladas y cuarta preparación bloqueada; no Codex real.
Las pruebas nuevas reutilizan la fixture4.4 con recibos artificiales y simulan solo
sus sellos heredados. No sustituyen la integración real, comprobada sin mocks arriba.

Cobertura: repetición sin efectos; dos consultas exitosas simultáneas; dos procesos
CLI sobre fixture incompleta (ambos BLOCKED sin modificarla); KeyboardInterrupt y
repetición; alteración/ausencia/otra implementación; fuente sin hash; schema anterior
sin migración; snapshots compartidos; escritura prohibida; salida JSON/texto y export
separado sin sobrescritura. UNKNOWN de ejecución no se relanza; UNKNOWN/SENDING de
Telegram bloquea y exige reconciliación. Se reutilizan además las regresiones4.4 de
reconciliación/idempotencia/budget. Incidentes **solo en temporales**, nunca sobre
el expediente real. Las consultas reales concurrentes fueron lecturas normales.

## Dictamen y límites

A. **Cubierto:** reconstrucción integrada del recorrido histórico real, íntegro y trazable.
B. **Cubierto con simulación:** recuperación/interrupción/idempotencia en temporales.
C. **No realizado:** una nueva ejecución completa ficha→Telegram en esta entrega.
D. **Pendiente separado:** auditor IA real; perfil/adaptador simulado no acredita despliegue.
E. **No acreditadas:** validación económica, robustez y autorización demo.

No hay bloqueos de integridad pendientes para cerrar este piloto técnico.
La muestra sintética de cero operaciones y el holdout histórico consumido son límites
científicos conocidos, no motivos para inventar rentabilidad o rechazar económicamente
la estrategia. Las reparaciones manuales impiden declarar automatización desatendida.
No se valida prospectiva ni operativamente una estrategia por completar este recorrido.

Sin nuevas llamadas Codex/APIs de modelos/Telegram, backtests, descargas, TEST reservado,
optimizaciones, órdenes, OKX, forward, activación de perfiles, servicios/scheduling,
commit, push o merge. Presupuesto3/3 intacto. Cierre técnico4.5 únicamente; paso5
no iniciado ni autorizado. Investigación diaria y patrones6/7 siguen fuera de alcance.
