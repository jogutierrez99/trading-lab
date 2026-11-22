# Validador Cuantitativo V1 — implementación 5.9B.3

Implementación local pendiente de revisión independiente. Base verificada:
`91c9840f08f25ced200e39c159ab0cbcf168fa61`, integración del PR #11.
Componente `quant_auditor_v1`, instrucciones `TLAgents.validator/1.0`.
No hay proveedor real, integración operativa, publicación ni certificación científica
de un LLM. El [diseño](agent-03-quant-validator.md), los
[contratos](agent-contracts-v1.md) y la [política de permisos](agent-permissions-v1.md)
siguen vigentes. Las fases 5.9B.4, 5.9C, 7.0 y 8.0 permanecen fuera de esta entrega.

## Arquitectura e interfaces

Se extiende `trading_lab_agents` sin cambiar motores, estrategias, orquestación,
ingesta, esquema SQLite, comparador ni contratos científicos históricos.

| Módulo | Responsabilidad |
|---|---|
| `validator_models.py` | ValidationAssessment 1.0 y petición acotada del host |
| `validator_evidence.py` | Bytes capturados, hashes y correspondencia con el catálogo |
| `validator_context.py` | Consultas por perfil auditor y coherencia de checkpoint |
| `validator_policy.py` | Observaciones admisibles, limitaciones y testigos estructurados |
| `validator_provider.py` | FakeValidatorProvider reproducible y errores simulados |
| `validator.py` | Admisión, llamada simulada única, validación y recibo |

Se reutilizan `ModelReview` y `AuditVerdict` de `audit_contracts.py`, el parser
JSON estricto, canonicalización e identidades existentes y `ReceiptBook`.
El test arquitectónico global del Investigador permite ahora también el módulo
**pasivo** `audit_contracts`; continúa prohibiendo imports operativos o de red.
No se cambia código ni comportamiento de ejecución del Investigador o Diseñador.

`QuantValidator.run(request_bytes, *, sources=tuple[PreparedAudit, ...])` devuelve
datos JSON serializables: `status`, `error_code`, `assessment` y `receipt`.
Solo admite instancias explícitas de ValidatorContext, FakeValidatorProvider y
ReceiptBook. No existe registro de proveedores, autodetección ni fallback real.

```python
from trading_lab_agents.receipts import ReceiptBook
from trading_lab_agents.validator import QuantValidator
from trading_lab_agents.validator_context import ValidatorContext
from trading_lab_agents.validator_evidence import AuditDocument, PreparedAudit
from trading_lab_agents.validator_provider import FakeValidatorProvider

# El host de prueba ya posee estos bytes y sus hashes. No son locators para el modelo.
source = PreparedAudit(
    verdict_bytes,
    expected_sha256=verdict_sha256,
    documents=tuple(AuditDocument(key, raw) for key, raw in captured_documents.items()),
    case_bindings=case_to_native_backtest_id,
    manifest_identity_verified=True,  # Relación validada por el host, no por el proveedor.
    history_scope="HypothesisManifest.novelty/1.0",
)
book = ReceiptBook()
provider = FakeValidatorProvider()
validator = QuantValidator(
    ValidatorContext(temporary_catalogue_path, fixture_root=temporary_root),
    provider,
    book,
)
result = validator.run(request_json_bytes, sources=(source,))
```

El ejemplo requiere fixtures preparados; no inicializa ni localiza bases reales.
El embedding Python y los hashes esperados suministrados por el host son una frontera
de confianza. No hay autenticación criptográfica del operador ni aislamiento frente
a un host que modifique deliberadamente los objetos Python.

## Contratos y estados

`ValidationAssessment` respeta namespace TLAgents y los campos normativos de 1.0:
schema_version, contract_kind, request_id, agent_role, status, source_run_ids,
model_review, recommendation, limitations, does_not_override_source y notes.
Namespace figura en el envoltorio; no se añade un campo inesperado al contrato.
Admite CONSULTATIVE y NEEDS_REVIEW; recomendaciones NO_DECISION,
REQUEST_MORE_EVIDENCE, CONTINUE_RESEARCH y DO_NOT_ADVANCE. `agent_role` admite
validator/coordinator_advisory en el modelo normativo; este ejecutor solo acepta
validator y no implementa el asesor del Coordinador.

Se reutiliza el ModelReview original con `verdict=NO_DECISION` y
`demo_authorized=false`. `does_not_override_source` exige booleano true. La nueva
frontera rechaza también autorizaciones numéricas como 0, sin modificar el modelo
histórico Literal[False]. Se rechazan extras, versiones incorrectas, tipos
incompatibles, IDs no válidos, claves JSON duplicadas, números no finitos,
desbordamientos, entradas demasiado grandes y anidamiento superior a 24 niveles.

`ValidationRequest` es una entrada local del host, no una tarea operativa nueva:
schema_version=1.0, contract_kind=ValidationRequest, request_id, source_run_ids,
audits con run_id/audit_id/verdict_sha256 y expected_checkpoint (SHA-256 o null).
Exige identidades distintas y una única ancla por run; no admite `latest`.
Un expediente sin métricas produce NEEDS_REVIEW, no métricas artificiales.

Estados del envoltorio de simulación:

| Estado | Significado |
|---|---|
| COMPLETE | Salida consultiva validada; no cambia el veredicto primario |
| BLOCKED | Contrato, referencias, fuente o límites rechazados; assessment=null |
| CONFLICT | Mismo identificador con bytes/admisión diferentes |
| UNKNOWN | Timeout, excepción inesperada o interrupción sin resultado recuperable |

COMPLETE no implica aprobación económica; también puede contener un assessment
NEEDS_REVIEW. No se modifica ninguna máquina de estados existente.

## Evidencia primaria y confianza

PreparedAudit conserva exactamente los bytes del AuditVerdict previo y exige su hash
esperado. Los documentos capturados deben cubrir exactamente sus referencias, con
hashes coincidentes. `case_bindings` enlaza explícitamente IDs del catálogo con los
backtest_id nativos. No abre archivos ni sigue rutas recibidas del proveedor.

La proyección admite el formato existente `observations.native_results`,
`metadata`, `result.metrics`, `result.trades` y referencias `result:<backtest_id>`.
Comprueba identidad run/experimento, recibo de ejecución, protocolo, holdout, conjunto
de casos, resultado capturado, denominador de trades, métricas y condiciones
asset/timeframe/dirección/periodo/escenario/costes/parámetros. Contrasta UTC y fechas.
No recalcula retornos, equity, drawdown, PF ni significación. Engine, versión y
dataset proceden del catálogo y sus referencias: esto no certifica de nuevo un runner
o dataset. Otros formatos necesitan un adaptador de host revisado; no se reconstruyen
ni reparan evidencias incompletas para admitirlas.

### Correcciones M01 y M02

El historial científico se proyecta con esquemas privados estrictos compatibles
con Novelty y EvaluationPlan: known_searches, known_variants, prior_work,
periodos, holdout_risk, criterios y planes declarados. Se distinguen ABSENT,
NULL y PRESENT y se conservan los campos realmente presentes: desconocido no
se convierte en cero. Cada proyección cita el ID y SHA-256 de su AuditVerdict.
No se reescribe el manifiesto ni se inventa multiplicidad o independencia OOS.

La respuesta debe conservar una advertencia estructurada por fuente con el historial
y sus limitaciones; omitirla o alterar los contadores provoca rechazo. Un periodo
de resultado fuera del plan declarado se conserva como conflicto y exige
NEEDS_REVIEW; no modifica el veredicto primario. Periodos declarados solapados,
tipos inválidos y contradicciones de holdout bloquean antes del proveedor.
El historial tiene un límite adicional de 16 KiB y su advertencia debe caber en
los 4.000 caracteres del contrato existente. No se truncan campos esenciales.

El adaptador nativo del protocolo de AuditRequest existente establece que
experiment.configuration_sha256 identifica los bytes de native:resolved.json.
Con ese protocolo, un pin capturado y comprobado que no coincide produce
AUDIT_CONFIGURATION_PIN_MISMATCH antes del proveedor. El recibo conserva hashes
de origen/catálogo, dominio, IDs, SHA del veredicto y checkpoint; los bytes originales
siguen en el libro privado. También se contrasta la observación resolved_configuration
con el JSON capturado. No se presupone esa equivalencia para protocolos distintos:
quedan UNVERIFIED_DOMAIN_BINDING con advertencia obligatoria.

La proyección distingue hashes de manifiesto, archivo Parquet, configuración
resuelta, fingerprint de parámetros y fingerprint del registro run. El fingerprint
del registro experimento no está disponible en este perfil y permanece null.
El dataset_sha256 genérico del catálogo no se equipara automáticamente al hash
de un manifiesto o Parquet, aunque coincidan sus dígitos: el vínculo queda
UNVERIFIED_NO_DOMAIN_BINDING. Un pin de configuración ausente conserva null y
UNVERIFIED_MISSING_SOURCE_PIN. Ninguno de estos estados crea acreditaciones.

El AuditVerdict debe conservar NO_DECISION, integridad A=INTEGRITY_OK y estado
COMPLETED_WITH_LIMITATIONS. BLOCKED_EVIDENCE, fallo de integridad o estado no
completo bloquean antes de consultar el catálogo o invocar el proveedor. La mera
presencia de blockers económicos no impide una consulta: la auditoría existente los
conserva también en una ejecución técnica correcta.

HASH_VERIFIED acredita integridad de bytes, no SOURCE_AUDITED. Este último solo
se recupera de los estados efectivos/eventos existentes del catálogo y representa
la auditoría declarada en una fuente sellada validada. Ni el hash de PreparedAudit
ni una opinión del proveedor crean acreditaciones. Fuentes sin acreditación
suficiente conservan UNVERIFIED y obligan NEEDS_REVIEW. No se modifica AuditVerdict,
su hash, ResearchDecision ni los datos del catálogo.

### Corrección M01 multifuente: identidad congelada y ámbito

La proyección conserva candidate_id e hypothesis_manifest_sha256 exactos, dominio
HYPOTHESIS_MANIFEST_JSON_SHA256, ID/SHA del AuditVerdict y campo de origen.
Este hash identifica el JSON completo conservado por la auditoría, no el
fingerprint científico de HypothesisManifest (que no incluye novelty), un hash
de configuración, dataset o parámetros. No se inventan hashes ausentes.

La relación procede del AuditVerdict 1.0 capturado y verificado por el host, con
integridad A y estado admitidos. manifest_identity_verified es una restricción
del host, nunca un campo de salida del proveedor. Su valor false conserva el hash
declarado como UNVERIFIED e impide agruparlo. El valor true consume la relación
del productor actual, no verifica por sí mismo otro archivo de manifiesto ni crea
una acreditación SOURCE_AUDITED. El host debe deshabilitarlo si no puede acreditar
esa relación. La autoridad del host y de los hashes esperados sigue siendo necesaria.

Solo se comparan known_searches y known_variants explícitos, enteros y no nulos
de fuentes con el mismo candidato, mismo hash completo acreditado y ámbito
HypothesisManifest.novelty/1.0 reconocido. El host puede indicar otro history_scope
o null; una declaración search_history_scope incompatible de la fuente también
invalida la comparabilidad de esos contadores. No se interpreta texto libre como
una definición equivalente ni se comparan otras métricas sin contrato de ámbito.

La conciliación se ejecuta antes del proveedor y del comparador de resultados:

| Caso | Tratamiento |
|---|---|
| Mismo grupo, enteros explícitos diferentes | BLOCKED / SCIENTIFIC_HISTORY_CONFLICT, cero llamadas |
| Mismo grupo, enteros explícitos iguales | AGREEMENT del campo; no certificación científica/económica |
| Un valor conocido y otros null/ausentes | PARTIAL_KNOWLEDGE, valores intactos y NEEDS_REVIEW |
| Todos desconocidos | UNKNOWN; nunca cero ni acuerdo inventado |
| Un único testigo válido | SINGLE_SOURCE; no corroboración multifuente |
| Manifiestos y candidatos diferentes | Grupos separados; no conflicto por tener recuentos distintos |
| Un candidato con manifiestos distintos, o un manifiesto con candidatos distintos | Revisión de procedencia; sin fusionar ni elegir valores |
| Identidad no acreditada o ámbito no verificado | No se agrupa; incertidumbre explícita y revisión si es material |

No se suman recuentos, no se escoge el mayor y no se selecciona una fuente preferida.
Los diagnósticos de contradicción incluyen checkpoint, manifiesto, ámbito, referencias
afectadas, campos y testigos explícitos/nulos/ausentes. El candidato se representa
mediante una referencia opaca en el error para evitar exponer identificadores privados.
Los bytes y metadatos originales permanecen en el ReceiptBook privado, sin cambios.

El contexto y la evaluación conservan la conciliación y las advertencias individuales.
Omitir la advertencia de identidad o convertir una revisión requerida en CONSULTATIVE
se rechaza por el host. No se modifica AuditVerdict, ModelReview, el comparador ni sus
estados. La captura usa el perfil auditor y las consultas ya existentes.

El resultado científico del diagnóstico es estable ante reordenación de fuentes.
La identidad de una operación sigue incluyendo sus bytes y las declaraciones del
host: misma solicitud idéntica recupera su resultado; cambiar orden/contenido bajo el
mismo request_id produce CONFLICT, sin una nueva llamada. No hay recuperación durable.
Los límites de contexto, respuesta y advertencias siguen vigentes; una captura densa
puede bloquearse en lugar de descartar evidencia o ampliar límites.

## Contexto acotado y lectura coherente

Solo se utiliza `CatalogReader.for_profile("auditor")` mediante get_run_details,
get_evidence_summary y compare_results. No se usan SQL, Store, herramientas de escritura,
LocalEvidenceReferences ni perfiles ajenos en el componente. Se heredan mode=ro,
query_only y las protecciones de apertura de la API; no se inicializa ni migra SQLite.

Cada método compuesto del lector conserva su propia instantánea. Como varias
llamadas no comparten automáticamente transacción, el adaptador exige que todas
devuelvan el mismo checkpoint. Un cambio descarta la captura completa y permite
hasta tres capturas **de lectura antes de llamar al proveedor**; el contador de
consultas es acumulativo. Si expected_checkpoint no es null, cualquier discrepancia
se bloquea sin nueva invocación del Investigador ni revisión implícita.
Si es null, la primera consulta fija el checkpoint de esa captura.

| Límite V1 | Valor |
|---|---|
| Runs por solicitud / casos totales / referencias | 4 / 40 / 50 |
| Limitaciones obligatorias y findings de ModelReview | 20 / 20 |
| Entrada y contexto total al proveedor | 64 KiB cada uno |
| Respuesta JSON | 32 KiB |
| AuditVerdict / cada documento / total de fuentes | 64 KiB / 64 KiB / 256 KiB |
| Consultas | ContextLimits existente, 80 por defecto |

Se recuperan IDs exactos; no se pagina un inventario de estrategias o decisiones.
Los métodos compuestos conservan sus propios límites de API. Los límites page_size
y max_pages compartidos no amplían esos métodos ni habilitan recorridos ocultos.
Una captura densa se bloquea: no se truncan silenciosamente fuentes o advertencias.
La selección de hasta 20 observaciones del proveedor simulado no se presenta como
un inventario exhaustivo de hallazgos; todas las limitaciones obligatorias se exigen.
No se acredita optimización del SQL interno ni consistencia tras cerrar la captura.

## Interpretación consultiva verificable

En esta V1 simulada, `ModelReview.findings` contiene observaciones declarativas JSON
canónicas del conjunto permitido por el host. No se admite prosa libre que afirme
métricas, causalidad, significación o rentabilidad sin un testigo verificable.
Esto conserva el contrato Text existente sin introducir un filtro de palabras.
El proveedor elige observaciones y una recomendación consultiva; el host contrasta
el contenido exacto y sus referencias. El texto de las incertidumbres/limitaciones
debe conservar todas las obligaciones, con procedencia en las referencias del contexto.

Se mantienen explícitamente NO_DECISION, CONSUMED, RESET_PER_SEGMENT y la separación
BASE/ADVERSE, incluso cuando los escenarios se distribuyen entre varios runs:
la advertencia consolida sus referencias sin declarar equivalencia entre ellos.
No se concatenan capitales ni se cuentan escenarios como observaciones
independientes. La regla descriptiva de menos de 30 trades solo genera una advertencia;
no constituye un test de significación. PF/Sharpe nulos siguen nulos; p_value ausente
figura null con disponibilidad ABSENT y significación UNKNOWN, sin inferir intervalos.
NOT_COMPARABLE nunca permite un ganador; los otros estados tampoco implican
suficiencia estadística. Se reutiliza exactamente el comparador existente.

Es una política conservadora para simulación, no un verificador general de veracidad
semántica de un modelo real. Una futura interpretación en lenguaje libre necesita
otra revisión, validación y autorización; no queda habilitada por esta entrega.

## Privacidad, inyección y recibos

El proveedor recibe IDs opacos, hashes, métricas permitidas, estados efectivos,
comparación y limitaciones. No recibe paths locales, documentos CSV completos,
veredictos/recibos íntegros, conexiones, SQL ni objetos del host. La proyección
usa listas blancas y el saneamiento existente; contenido sensible detectado bloquea
la salida en vez de resolver referencias privadas. No es un sistema DLP universal:
el host debe revisar las fuentes y no introducir secretos en texto público.

Fuentes e instrucciones incrustadas son datos. No existe eval/exec, despacho de
herramientas, comandos, proveedores reales, lectura .env o clientes OpenAI. La
inyección puede aparecer como texto de una incertidumbre citada, nunca como permiso.
Las observaciones, autorizaciones y recomendaciones están separadas en código.

ReceiptBook conserva bytes privados de solicitud y fuentes, instrucciones/versiones,
hashes, contexto, respuesta y diagnóstico. Su exportación privada no se entrega al
proveedor; contiene evidencia sensible y pertenece al host. La clave de operación
prefijada `validator:` evita colisiones con las operaciones de los otros componentes.
Igual identidad y mismos bytes recuperan el resultado sin consultar de nuevo ni
invocar al proveedor. Misma identidad con bytes distintos produce CONFLICT.
El bloqueo del libro serializa solicitudes concurrentes. UNKNOWN se conserva y no
se reenvía automáticamente; una interrupción se reconcilia solo en memoria.
No hay recuperación durable, cola ni almacenamiento adicional. Un libro nuevo no
recupera resultados de procesos anteriores. Los errores públicos contienen códigos
fijos, no tracebacks o rutas privadas.

### Corrección L01: observaciones de invocación

El contexto preparado no cuenta como llamada. El host guarda una observación privada
en ReceiptBook y estados de preparación/intención/recepción; FakeValidatorProvider
marca su entrada efectiva mediante un ContextVar aislado por ejecución. La interfaz
respond(bytes) y el contador global calls del simulador conservan su compatibilidad.
No se modifica ReceiptBook ni se añade contabilidad financiera.

El recibo incluye invocation_observation: context_prepared, intent_recorded,
observed_calls, response_received, response_captured y outcome. Una interrupción
acreditada antes de la intención registra cero. Si existe intención sin constancia
de recepción, observed_calls y simulated_invocations son null: la frontera es incierta.
Una recepción observada conserva uno aunque falte resultado. La respuesta capturada
se distingue de la admisión final; una operación interrumpida sigue UNKNOWN incluso
si ya se conservaron bytes, y no se reenvía. Un contexto sin traza verificable tampoco
se convierte automáticamente en una llamada. Son observaciones en memoria, no
recuperación durable ni una reserva del ledger global.

## Aceptación V01–V12

| Grupo | Comprobación |
|---|---|
| V01 | COMPLETE técnico + pocos trades + NO_DECISION, sin promoción |
| V02 | Hash íntegro sin acreditación suficiente permanece UNVERIFIED |
| V03 | SOURCE_AUDITED y holdout consumido conservan sus limitaciones |
| V04 | Periodos, costes, motores y capital incompatibles: motivos, sin ganador |
| V05 | Capital independiente y escenarios alternativos, sin agregación |
| V06 | Métricas nulas/ausentes y muestra desconocida, sin derivados inventados |
| V07 | Referencias externas al paquete y métricas no soportadas rechazadas |
| V08 | demo_authorized=true y cambios de verdict/control rechazados |
| V09 | BLOCKED_EVIDENCE: cero consultas y cero llamadas al proveedor |
| V10 | Hash y bytes del AuditVerdict primario preservados |
| V11 | Inyección en CSV/informes: sin herramientas ni cambios de gates |
| V12 | Timeout/error/interrupción: resultado incierto o bloqueado, sin reenvío |

Se añaden contratos estrictos, límites, privacidad, ocho lectores compartiendo libro,
captura invalidada por escritor sintético, idempotencia, conflictos y transferencia
desde el Auditor determinista existente. El último ensayo reutiliza el fixture
4.4: su sello de implementación 4.3 es simulado; las comprobaciones nativas de
identidad, hashes, metadatos y denominadores se ejecutan sin cambios. No es un
histórico real, backtest nuevo ni una nueva auditoría económica.

Las comprobaciones de inventario y hashes se toman después de preparar cada fixture
y tras la consulta. La única ingesta concurrente intencionada pertenece a un fixture
temporal y se distingue de escrituras del componente, que no existen.

Aceptación previa: 565 pruebas distintas. Tras corregir M01/M02/L01 se ejecutaron
606 pruebas distintas aprobadas, cero fallidas y cero omitidas por pytest:
las 565 anteriores más 41 nuevas en test_review_corrections.py. Se conservan las
125 originales del Validador, 167 del Diseñador, 119 del Investigador,
84 de la API, 38 del catálogo, 19 de HypothesisManifest y 13 de auditoría determinista.
Los cuatro ensayos nativos pendientes fueron **deseleccionados**, no aprobados;
otras 56 pruebas quedaron fuera de las selecciones dirigidas de contratos/auditoría.
V01–V12 están cubiertos. Ruff check, formato y comprobación del diff pasan.
Las tres reproducciones fallaron sobre la implementación anterior verificada y pasan
sobre la corregida. Los XML y snapshots de comparación quedan fuera del checkout;
no fue necesario revertir temporalmente código del árbol de trabajo.

Tras la segunda revisión se añadieron 26 regresiones permanentes multifuente en
test_multisource_consistency.py. Aceptación actual: **632 pruebas distintas aprobadas**,
las 606 anteriores sin modificaciones más las 26 nuevas. El caso 12/12 frente a 0/0
falló antes de corregirlo y ahora se bloquea antes del proveedor con diagnóstico.
La cobertura incluye identidades iguales/distintas/ausentes/no acreditadas, nulos,
procedencia incompatible, tres fuentes, reordenación, duplicados, límites, privacidad,
advertencias omitidas y ámbitos diferentes. No se suman repeticiones al total distinto.

Medición local de una ejecución, sin umbral de rendimiento ni equivalencia a tokens:
40 estrategias, 40 experimentos y 40 decisiones sintéticos; tres consultas,
18.495 bytes de contexto, 9.346 bytes de respuesta y 0,0399 s para captura más
validación. Ocho lectores con un libro compartido completaron en 0,0409 s con una
sola invocación simulada. Son observaciones del entorno de prueba, no benchmarks
generalizables ni optimización del motor o del SQL del catálogo. El test de límite
de 1 KiB bloquea sin invocar al proveedor; no se aumentan límites para admitirlo.

## Ejecución y límites de la verificación

Pruebas con Python 3.12, PYTHONPATH=src y PYTHONDONTWRITEBYTECODE=1. Sin pytest cache;
basetemp y XML JUnit se guardan fuera del checkout. Las pruebas de lectura NTFS
usan el proceso de usuario ordinario; no se cambian ACL ni privilegios de Windows.

```text
python -B -m pytest tests/validator -q -p no:cacheprovider
python -B -m pytest tests/designer tests/researcher tests/catalog_api tests/unit/test_strategy_catalog.py -q -p no:cacheprovider -k "not test_real_symlink_guard_if_available and not test_audit_preexisting_junction_is_blocked and not test_audit_directory_swap_cannot_redirect_sqlite_open and not test_audit_hardlink_database_alias_is_blocked"
python -B -m pytest tests/unit/test_orchestration.py -q -p no:cacheprovider -k "invalid_contract or nested_rejections or periods_and_grid or json_duplicate_keys or fingerprint_key_order_and_metadata"
python -B -m pytest tests/unit/test_audit_orchestration.py -q -p no:cacheprovider -k "complete_zero_trades or native_pass_is_preserved or contradictory_classification_counts or evidence_blockers_do_not_change_execution or dedup_persistence_and_immutable_artifacts or consumed_holdout_is_not_restored or contracts_reject_latest_revision or evidence_changed_during_review"
python -m ruff check src/trading_lab_agents tests/validator tests/researcher/test_context.py
python -m ruff format --check src/trading_lab_agents tests/validator tests/researcher/test_context.py
git diff --check
```

Las cuatro pruebas nativas de enlaces siguen pendientes, no aprobadas. El fallo SMA
preexistente queda fuera de esta selección; no se corrige ni se presenta como resuelto.
No se abre el catálogo real ni el ledger. Tampoco se afirma una nueva verificación
de su SHA, ACL o fuentes: se preservan por ausencia de acceso durante esta tarea.
El modelo de amenazas del lector se conserva: Windows NTFS confiable; riesgo
residual ante procesos no confiables que sustituyan ascendentes POSIX. No hay
garantías nuevas para otros entornos o fuentes no compatibles.

## Próxima revisión

Revisar código, pruebas, contrato, adaptador y el inventario local antes de autorizar
publicación. La fase 5.9B.4 y la integración general requieren otro encargo. El piloto
real exige presupuesto global conciliado (20 EUR/mes compartidos), precios/modelos
vigentes, reservas revisadas y autorización expresa. Esta implementación no toca
ledger, tarifas, credenciales, notificaciones, permisos ni estados operativos.
