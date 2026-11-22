# Diseñador Cuantitativo V1 — implementación simulada, 5.9B.2

Implementación local pendiente de revisión. Identidad `quant_strategy_designer_v1`,
instrucciones `TLAgents.designer/1.0`. Base: `0a713557ae19ee549a39bfbc46aa6472ee2bbd2e`,
con el Investigador integrado por PR #10. No hay proveedor real, implementación de
estrategias, permisos operativos, registro de candidatas, backtests ni flujos activos.

## Arquitectura y uso

Extensión aditiva del paquete existente, sin dependencias adicionales ni otra orquestación:

| Módulo nuevo | Responsabilidad |
|---|---|
| `designer_models.py` | StrategySpecification 1.0, Formula, RiskConstraints, CostScenario y parser JSON estricto |
| `designer_capabilities.py` | Inventario del host contrastado con fuentes inspeccionadas y evidencia sintética separada de disponibilidad |
| `designer_host.py` | Revisión local de una candidata recuperable del recibo del Investigador; no concede ejecución |
| `designer_context.py` | Únicamente CatalogReader.for_profile("designer"), selección, páginas y checkpoints |
| `designer_provider.py` | FakeDesignerProvider sin red, claves, herramientas ni fallback |
| `designer_semantics.py` | Subconjunto declarativo verificable, contradicciones y mapeo científico |
| `designer.py` | Componente invocable, una simulación, recibo y diagnóstico |

Se reutilizan Contract, ResearchRequest/ResearchHypothesis, ContextLimits, ResearchError,
canonical/identity, ReceiptBook y el lector actual. No cambian los seis módulos del
Investigador, HypothesisManifest, su fingerprint, la ingesta, el esquema o las acreditaciones.
Los perfiles del lector siguen sin autenticar usuarios ni autorizar ejecución.

Interfaz local, con objetos preparados exclusivamente por el host de pruebas:

```python
from trading_lab_agents.designer import QuantStrategyDesigner, designer_operation_id
from trading_lab_agents.designer_context import DesignerContext
from trading_lab_agents.designer_host import DesignReviewHost
from trading_lab_agents.designer_provider import FakeDesignerProvider

# Todas estas entradas provienen del fixture sintético, no del catálogo real.
host = DesignReviewHost()
review_id = host.review(
    request_bytes, hypothesis_bytes, candidate_id,
    researcher_receipts=shared_memory_book, capabilities=host_capabilities,
)
designer = QuantStrategyDesigner(
    DesignerContext(temporary_catalogue, fixture_root=temporary_root),
    FakeDesignerProvider(proposal_bytes), shared_memory_book, host, host_capabilities,
)
result = designer.run(
    request_bytes, hypothesis_bytes, candidate_id, review_reference=review_id,
)
receipt = shared_memory_book.export(designer_operation_id(request_id, candidate_id))
```

`tests/designer/conftest.py` construye el ejemplo completo: Researcher simulado →
ResearchHypothesis → revisión sintética del host → Designer → especificación y recibo.
No crea ImplementationRequest ni envía nada al coordinador operativo o a Codex.

## Contratos, bytes y errores

Se implementa el [contrato normativo](agent-contracts-v1.md) sin modificarlo:
StrategySpecification contiene schema_version, contract_kind, request_id,
research_hypothesis_id, status, manifest, capital_policy, formulas, risk_constraints,
cost_scenarios, capability_reference_ids, implementation_operation, missing_fields,
review_requirements y notes. Los dos ejemplos normativos siguen validándose.

`extra=forbid`, tipos estrictos, porcentajes finitos, versiones e IDs exactos.
Se rechazan claves duplicadas, NaN/Infinity, desbordamiento numérico, profundidad
superior a 24 y entrada/salida superior a 64 KiB. El manifiesto embebido se valida
en **modo JSON**, conservando fechas ISO y timestamps UTC del contrato original.
Los booleanos declarativos no admiten 0/1 como sustitutos. Fórmulas ≤20;
costes ≤2; textos del suplemento ≤4000 caracteres; listas de diagnóstico ≤20.

DRAFT y NEEDS_REVIEW admiten manifest/risk_constraints nulos y listas vacías.
NEEDS_REVIEW exige diagnóstico; no se fabrica un manifiesto para representar un error.
SPECIFICATION_PREPARED exige completitud estructural y superar los gates del host.

La respuesta es JSON serializable: namespace/version/mode, status, error_code,
specification y receipt. COMPLETE significa que se procesó una propuesta: hay que
consultar también specification.status, que puede ser DRAFT o NEEDS_REVIEW.
Una propuesta preparada que falla el gate semántico se conserva con NEEDS_REVIEW,
su código y sin fingerprint de admisión del manifiesto. Un JSON inválido queda
BLOCKED. Timeout o error incierto queda UNKNOWN. No hay reparación ni reenvío.

Ejemplos de códigos: HOST_REVIEW_REQUIRED, HOST_REVIEW_IDENTITY_MISMATCH,
HANDOFF_NOT_REVIEWABLE, HANDOFF_FINGERPRINT_MISMATCH, HANDOFF_CHECKPOINT_CHANGED,
SPEC_IDENTITY_MISMATCH, DATASET_PENDING, RUNNER_UNSUPPORTED, MARKET_UNSUPPORTED,
SEMANTICS_UNVERIFIABLE, LIMITATION_DROPPED, HOLDOUT_RECLASSIFIED, CONFLICT,
CONTEXT_PAGE_LIMIT, CONTEXT_QUERY_LIMIT y CONTEXT_LIMIT_EXCEEDED.
Son diagnósticos técnicos; no decisiones económicas ni permisos.

## Transferencia y revisión del host

DesignReviewHost exige ResearchRequest PREPARED y ResearchHypothesis
HYPOTHESIS_PROPOSED. Contrasta bytes originales de solicitud/respuesta, request_id,
candidata, mercado, estado COMPLETE, fingerprints de hipótesis/candidata y versión
de agente identificable en el recibo simulado recuperable. NO_HYPOTHESIS y
NEEDS_REVIEW no se convierten en una revisión aprobada.

La referencia debe existir en el registro acotado del host y coincidir con los
hashes de entrada y capacidades. `specification_reviewed=true`, un booleano o un
JSON del proveedor no pueden crearla. Este registro es memoria local de simulación,
no autenticación criptográfica del operador ni autorización de implementar/ejecutar.
El host Python es parte confiable del modelo de amenazas; no se intenta aislar
código Python malicioso con los permisos del operador.

Se conservan warning_provenance, sus testigos, referencias, checkpoint y limitaciones
del Investigador. El manifiesto preparado debe mantener todas las limitaciones de
la candidata, su hipótesis, justificación, fuentes y falsación. Las advertencias de
antecedentes relacionados no se convierten en acreditaciones del nuevo diseño.
Un checkpoint cambiado bloquea la transferencia incluso si no hay referencias:
la ausencia de antecedentes también depende de la instantánea revisada. No se
relanza automáticamente el Investigador; una revisión nueva debe identificarse
mediante una transferencia explícita ligada a la instantánea correspondiente.
La integración durable/general corresponde a 5.9B.4, fuera de esta entrega.

## Catálogo y privacidad

Solo se usan métodos permitidos por designer: list_strategies, get_strategy,
list_versions, search_experiments y find_existing_research. La captura actual utiliza
list_strategies, search_experiments y list_versions; no necesita consultar decisiones,
runs, casos, SQL o Store. La información económica pertinente ya validada por el
Investigador llega en una proyección del host ligada al recibo, con procedencia.

El inventario general contiene IDs/nombres/familias declaradas/conteos de versiones;
se marca DISCOVERY_ONLY_NOT_EQUIVALENCE. Los experimentos exigen coincidencia exacta
de mercado, activo y timeframe; las referencias incompatibles o contradictorias
bloquean. Se seleccionan versiones pertinentes. La API actual enumera versiones por
estrategia, por lo que resolver un version_id sin propietario puede requerir recorrer
estrategias: esa limitación se conserva bajo límites, sin SQL alternativo.

Todas las páginas de la captura deben compartir checkpoint. Hay hasta dos recapturas
completas adicionales de lectura antes del proveedor si cambia; presupuestos acumulados,
nunca recaptura para repetir una invocación ya iniciada. Por defecto: páginas de 20
(máximo 50), ocho páginas por operación (máximo 20), 80 consultas totales (máximo 128),
64 KiB de contexto. No hay truncamiento silencioso; los límites bloquean.

El proveedor recibe únicamente bytes JSON, tools=[], IDs y hashes. No recibe objetos
Python, conexiones, rutas de SQLite, referencias locales, credenciales o herramientas.
Se aplica la proyección conservadora de privacidad; el campo `reference` del manifiesto
solo admite fuentes con IDs ya contrastados, nunca apertura de locators.
La minimización/redacción por patrones no prueba ausencia de secretos semánticos en
texto libre: el host debe revisar las fuentes antes de futuras integraciones reales.

fixture_root exige ubicación explícita y prohíbe ascensos; no es una sandbox contra
un host malicioso. Se heredan mode=ro/query_only y guardas nativas del catálogo,
sin debilitarlas ni cambiar ACL. No existe ruta predeterminada al catálogo real.

## Capacidades verificadas y subconjunto matemático

DesignCapabilities inspecciona únicamente bytes de nueve fuentes fijas: config,
execution_config, features, risk, backtest, study_backend, study_data, lab_runner y
docs/lab-workflow.md. Las huellas se contrastan con la revisión inspeccionada,
normalizando CRLF a LF. No importa ni ejecuta el motor y no invoca Git o comandos.
Un cambio de esas fuentes exige nueva revisión del inventario; no se acepta una
capacidad afirmada por el proveedor. No se amplía el inventario de forma automática.

Protocolo sintético versionado `ohlcv_design_subset_v1`:

- StudyBackend v1, spot LONG_ONLY y synthetic con una dirección por diseño; timeframes
  1h/4h/1d, velas cerradas y entrada NEXT_OPEN. Sin piramidación ni reversión al mismo open.
- Stops ATR y objetivos riesgo/recompensa; sin trailing, niveles estructurales, HTF
  o sizing por volatilidad en este subconjunto. El motor tiene otras capacidades;
  esta entrega no las acredita para un diseño automáticamente.
- ATR = **media aritmética** de TR, con cierre anterior obligatorio y primer TR NaN,
  conforme a features.atr; no se sustituye por Wilder. El stop usa ATR sin shift
  al cierre de señal; distancia y objetivo se fijan respecto al precio de entrada.
- Sizing preparado stop_risk, límites de exposición, pérdida de stop y capital
  con costes incluidos, redondeo ROUND_FLOOR y filtros sintéticos explícitos. No
  se presentan esos filtros como reglas actuales de Binance u otro venue.
  El backend también ofrece fixed_notional/volatility_target, pero no se acreditan
  aquí: requieren otro mapeo de riesgo revisado. En particular, fixed_notional no
  aplica el presupuesto risk_per_trade_pct y no debe presentarse como si lo hiciera.
- Fees en ambos lados; precio adverso por slippage + spread/2. Fee <100% y ajuste
  adverso combinado <100%, como CostModel. ADVERSE no reduce componentes BASE.
- Gaps temporales rechazados; para gaps de precio y ambigüedad intrabar se conserva
  adverse open gap → stop antes de target. Liquidación al final y capital reiniciado.
- Spot NOT_APPLICABLE, synthetic NOT_MODELLED. Perpetual queda UNSUPPORTED en este
  inventario: requiere otro adaptador/datos de funding verificados, aunque exista
  infraestructura especializada en el repositorio. No se modifica el motor.

Las fórmulas son datos JSON tipados dentro de Formula.expression. Operadores:
PRICE, SMA, ROLLING_MAX, ROLLING_MIN, ATR_SMA. Declaran input, window (entero o
parámetro congelado), shift≥0, centered=false, fill=NONE, timeframe y closed=true.
PROTOCOL fija ecuaciones, intervalos inclusivos/exclusivos y tratamiento NaN.
Las señales son predicados GT/LT/GE/LE sobre OHLC o fórmulas declaradas. No hay
eval/exec, funciones arbitrarias o descarga de expresiones.

Warmup/NaN/gaps, ATR, target, sizing y selección usan subestructuras tipadas.
Las ventanas y shifts deben concordar con Formula; warmup cubre lookback y shift
(más cierre anterior para ATR) y la cobertura del fixture incluye el warmup anterior
a TRAIN. Expresiones complejas/textuales desconocidas quedan NEEDS_REVIEW. Esto
verifica **declaraciones**, no la causalidad del código futuro: prefix-invariance,
equivalencia de indicadores y fills siguen pendientes de implementación autorizada.

El dataset tiene identidad/hash/cobertura sintética emitidos por el host. Los bytes
de fixture prueban captura e identidad, no validación OHLCV ni cobertura del mercado
real. Bytes ausentes mantienen PENDING y hash nulo. No se abren datos de producción.

## Selección, holdout y reutilización

TRAIN/VALIDATION/TEST UTC, cronológicos y disjuntos por HypothesisManifest. El subconjunto
requiere parámetros singleton congelados, selección TRAIN y protocolo fijado.
No se admiten búsquedas sin resolver o selección TEST como especificaciones preparadas.
Un periodo TEST coincidente con descubrimiento o un dataset de antecedente CONSUMED
no puede declararse UNOBSERVED_DECLARED. CONSUMED no puede ser holdout_independent.
Un dataset diferente no hereda automáticamente el holdout del antecedente, cuyas
limitaciones y procedencia se mantienen. UNOBSERVED_DECLARED sigue siendo declaración.

La multiplicidad de descubrimiento se contrasta con la solicitud validada del host.
Si discovery.searches_count es conocido, novelty.known_searches no puede ser null
ni menor: el gate devuelve DISCOVERY_MULTIPLICITY_LOST y NEEDS_REVIEW, sin corregir
silenciosamente los bytes de la propuesta. Un total mayor conserva el mínimo conocido,
pero sigue siendo una declaración, no una auditoría del número real de búsquedas.
Si el contador de entrada es desconocido, V1 exige null; no hay otra fuente estructurada
del host que acredite un contador alternativo. Un valor numérico no acreditado devuelve
DISCOVERY_MULTIPLICITY_UNVERIFIED. Esto no cambia HypothesisManifest ni su fingerprint
vigente: novelty se conserva en el manifiesto y en la identidad completa de la especificación.
Preservar el contador no convierte el periodo de descubrimiento en validación OOS.

NEW_EXPERIMENT exige requires_new_strategy_code=false y testigo de reutilización
revisado por el host: version_id, hashes de código/configuración y plantilla exacta
de señales. Las identidades deben coincidir con el catálogo; la plantilla no se
deduce de nombres parecidos. El esquema de parámetros debe ser comprobable: en V1,
objeto cerrado con enteros acotados explícitos, sin keywords no interpretadas.
Esquemas más complejos requieren revisión. Una variante compatible de parámetro
no exige otro Python. NEW_STRATEGY requiere requires_new_strategy_code=true.
No se implementa ni registra ninguna estrategia en esta fase.

## Mapeo TLAgents.semantic/1.0 e identidades

Primero se conservan los bytes originales y se validan contradicciones. Después:

| Información | Campo existente dentro del fingerprint original |
|---|---|
| Fórmulas/unidades/window/shift/warmup/gaps | signal_spec.feature_definitions, con reglas de señales contrastadas |
| Capital/riesgo/sizing | execution_assumptions.sizing |
| BASE | execution_assumptions numérico, con comprobación exacta |
| Escenarios completos y protocolo/dataset | evaluation_plan.robustness_plan |
| Periodos/selección/parámetros | evaluation_plan y parameter_space originales |

Cada campo Text mapeado es JSON canonical con semantic_version="TLAgents.semantic/1.0",
declared (contenido original) y scientific_data. Se preserva la declaración original;
una contradicción bloquea en vez de sobrescribirla. Un envelope recibido del proveedor
se rechaza; no se remapean manifiestos históricos o resultados previamente sellados.
La especificación mapeada se valida de nuevo y mantiene el límite de salida.

El recibo conserva fingerprint original del manifiesto, fingerprint del manifiesto
mapeado usando **su método original**, fingerprint completo de StrategySpecification,
contexto/propuesta y hashes. Cambiar capital, riesgo, sizing, fórmulas, parámetros,
stop/target o ADVERSE cambia la identidad científica, o se bloquea si hay contradicción.
No se depende de notas externas al fingerprint para reconocer trabajo nuevo.
Los hashes no demuestran rentabilidad, causalidad real o elegibilidad demo.

## Proveedor, recibos e idempotencia

Se acepta únicamente la clase exacta FakeDesignerProvider; no un callback arbitrario,
subclase o cliente real. Escenarios: propuesta en bytes, incompleta, truncada, timeout,
error, interrupción y respuesta maliciosa. Cuenta invocaciones bajo lock.

ReceiptBook se reutiliza sin cambios. La clave `designer.<hash(request_id,candidate_id)>`
separa la operación de la clave del Investigador. Admission liga bytes/revisión,
capacidades, instrucciones y límites; un cambio contradice la identidad existente.
La sección crítica cubre la captura y la única invocación. Un resultado recuperable
se devuelve sin proveedor ni nueva lectura. UNKNOWN o interrupción no se reintentan.
Las exportaciones son copias separadas y conservan propuesta/contexto originales.
No se escriben recibos automáticamente ni se abre una base nueva.

La idempotencia existe **solo en el libro compartido en memoria**. Otro proceso u
otro libro no puede recuperar esa reserva/resultado. No hay recuperación durable;
su integración futura deberá pasar por el coordinador existente y otra autorización.

## Pruebas y aceptación

Escrituras únicamente durante preparación de SQLite sintéticas desechables.
Tras prepararlas, cada fixture compara inventario de directorio y hashes antes/después,
y exige ausencia de nuevos journals/WAL/SHM. La transferencia también es sintética.

| Grupo | Evidencia ejecutable en tests/designer |
|---|---|
| D01 | Contrato completo, fórmulas, dependencias, ventanas/shifts y fechas JSON |
| D02 | Centered/backfill/futuro/HTF sin confirmar, tipos de flags y expresiones desconocidas |
| D03 | Unidades, rangos, coherencia riesgo/sizing, costes BASE/ADVERSE y límites del backend |
| D04 | Spot/synthetic válidos, spot short rechazado, perpetual bloqueado por inventario |
| D05 | Reglas/NaN/warmup/gaps/stop/target/sizing faltantes y cobertura warmup |
| D06 | Holdout consumido aplicable, descubrimiento en TEST, selección TEST y advertencias |
| D07 | Fuente/capacidad/runner/dataset desconocidos o pendientes sin hash inventado |
| D08 | Reutilización con testigo y esquema, cambios de parámetros, lógica o identidad incompatibles |
| D09 | Campos extra/auto-revisión, referencia alterada, privacidad, proveedor ajeno y ausencia de herramientas |
| D10 | Repetición/concurrencia inicial, timeout/error/interrupción y resultados desacoplados |
| D11 | Identidades distintas ante cambios científicos y rechazo de envelopes/contradicciones |
| D12 | Manifest/riesgo nulos en borradores y rechazo de incompletos presentados como preparados |

Comandos PowerShell desde la raíz del checkout, con Python del entorno del proyecto:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m pytest tests/designer tests/researcher tests/catalog_api tests/unit/test_strategy_catalog.py -q -p no:cacheprovider -k 'not test_real_symlink_guard_if_available and not test_audit_preexisting_junction_is_blocked and not test_audit_directory_swap_cannot_redirect_sqlite_open and not test_audit_hardlink_database_alias_is_blocked'
python -B -m pytest tests/unit/test_orchestration.py -q -p no:cacheprovider -k 'invalid_contract or nested_rejections or periods_and_grid or json_duplicate_keys or fingerprint_key_order_and_metadata'
python -B -m ruff check src/trading_lab_agents tests/designer
python -B -m ruff format --check src/trading_lab_agents tests/designer
git diff --check
```

Aceptación correctiva ejecutada en Python 3.12: **408 aprobadas** (167 del Diseñador,
119 del Investigador y 122 del catálogo/API), cero fallidas y cero omitidas dentro
de la selección. Además, **19 pruebas** del contrato HypothesisManifest aprobadas
en una selección separada, con 15 pruebas ajenas a ese contrato deseleccionadas.
Son 427 pruebas distintas aprobadas; no se suman las repeticiones del desarrollo.
Se conservan las 154 pruebas originales del Diseñador y D01–D12. Las 13 nuevas en
test_review_corrections.py cubren reducción/borrado del contador, positivos de mínimo
conocido y desconocido, incertidumbre/OOS, checkpoint cambiado sin referencias,
instantáneas estables con/sin referencias y revisión nueva explícita. Antes de cambiar
los módulos, esos casos reprodujeron seis fallos esperados y siete positivos; después
pasaron los trece. Se conservan ambos resultados en el informe privado de correcciones.
Las cuatro pruebas nativas de enlaces están **deseleccionadas y pendientes**; no se
cuentan como aprobadas ni se fuerzan privilegios/ACL/Developer Mode. Se conserva el
riesgo de la API: LOW en Windows NTFS confiable, MEDIUM en POSIX con sustitución de
ascendentes por procesos no confiables. La prueba SMA preexistente está fuera de
esta selección y no se modifica para ocultarla.

Medición ejecutada del contexto aislado: 40 estrategias, 120 experimentos y 80 decisiones;
cuatro experimentos pertinentes y una versión, cinco consultas/páginas, 7495 bytes,
aproximadamente 51 ms en la aceptación correctiva.
Los paquetes completos observados midieron entre 7599 y 15020 bytes; se contaron
109 invocaciones falsas en la selección del Diseñador, incluyendo escenarios de fallo.
Bytes no son tokens. Se prueba
también bloqueo al agotar páginas. La selección no acredita optimización del SQL
interno ni asegura tiempo constante en catálogos más densos.
El informe local de aceptación conserva totales definitivos, XML de resultados,
mediciones, hashes/blobs e inventario y diff; no se añade evidencia privada al repo.

## Límites y continuación

Aceptación técnica simulada, no certificación científica por un LLM real. No se
demuestra veracidad semántica de texto libre, independencia estadística real,
fidelidad de código aún inexistente, facturación, rendimiento económico ni trading.
Los límites pueden bloquear investigaciones densas y reglas fuera del subconjunto.
La cobertura OHLCV de mercado, ejecución de protocolos especializados y reutilización
de esquemas complejos requieren trabajo posterior revisado; no se amplían por defecto.

Siguiente paso: revisión independiente de código, mapeo científico, tests y diff;
publicación solo con autorización posterior. No comenzar Validador 5.9B.3 ni conectar
agentes/flujos en esta entrega. Se conserva el [roadmap](../ROADMAP.md): terminar MVP
de ambos flujos hasta Telegram antes de biblioteca/RAG (7.0) y evolución del motor (8.0).
