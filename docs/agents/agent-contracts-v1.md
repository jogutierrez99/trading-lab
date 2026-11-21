# Contratos de comunicación de agentes — V1

Especificación documental, sin modelos Python, esquemas instalados o migraciones.
Los ejemplos son datos artificiales y no expedientes, autorizaciones o ejecuciones.
Las instrucciones propuestas no convierten estos bloques en acciones.

## 1. Inventario y reglas comunes

| Necesidad | Contrato existente | Decisión |
|---|---|---|
| Recepción de ideas | research_intake.Batch 1.0; Idea y Selection sin versión propia | Reutilizar para selección de lotes; ResearchRequest general requiere un adaptador |
| Hipótesis admitida | HypothesisManifest 1.0 | No duplicarlo; el borrador de Investigación aún no es una ficha admitible |
| Diseño | Ningún contrato de Diseñador | Proponer StrategySpecification con manifest vigente, sin modificarlo |
| Encargo a Codex | ImplementationPlan/ImplementationRequest 1.0 | Reutilizar exactamente, generado por el host |
| Entrega | ModelDelivery 1.0 + recibo anfitrión de Coordinator | Proponer una proyección pública ImplementationEvidence, no otro recibo primario |
| Ejecución | ExecutionPlan/ExecutionRequest y recibos existentes | Proyección BacktestEvidenceReference; no nuevo formato de cálculo |
| Auditoría | AuditRequest/AuditVerdict y ModelReview 1.0 | Reutilizar; ValidationAssessment envuelve el suplemento sin alterar gates |
| Coordinación y notificación | CircuitRequest, checkpoints y audit_outbox | Proyecciones consultables; no otro motor de estados o transporte |

Los contratos propuestos usan namespace `TLAgents`, versión exacta `1.0` y
contract_kind fijo. Los existentes conservan nombres, versiones y campos reales.
No se reutiliza el número 1.0 para cambiar silenciosamente un contrato existente.
Una activación futura negociará explícitamente el nuevo namespace y perfil.

Las declaraciones MANUAL, MANUALLY_VERIFIED o UNOBSERVED_DECLARED admitidas por
HypothesisManifest conservan su significado declarativo. No son acreditaciones
del catálogo ni autorizaciones del coordinador. El host contrasta cualquier
afirmación de fuente, capacidad o aprobación contra evidencia independiente.

### Tipos y validación transversal

| Tipo | Definición propuesta |
|---|---|
| ID | `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`, sin identidad latest |
| CatalogID | Cadena de 1–160 caracteres, según identity/Identity de la API 5.9A; no imponerle el patrón de ID de orquestación |
| SHA | 64 caracteres hexadecimales minúsculos |
| Commit | 40 hexadecimales; referencia exacta, no nombre de rama como identidad congelada |
| UTC | ISO-8601 con zona UTC explícita; fin de periodo exclusivo y start < end |
| Texto | UTF-8 no vacío, hasta 4000 caracteres por campo salvo límite menor explícito |
| Lista | Hasta 20 entradas por defecto; null conserva desconocidos donde se admita |
| Porcentaje | Número finito en unidades porcentuales; 0.05 = 0.05 %. Respetar rango del protocolo |
| Resultado | Campo de datos, nunca autorización; ver estados de cada contrato |

En propuestas nuevas, extra=forbid en todos los objetos, sin claves repetidas,
NaN/Infinity o coerción de booleanos a números. Los campos indicados como opcionales
se representan con null en salidas estructuradas del modelo; no se completan por
inferencia. Las listas vacías solo se admiten cuando el contrato lo indica.
No se modifica la semántica exacta de los validadores de contratos existentes.

Límites nuevos propuestos: 64 KiB de entrada saneada y 32 KiB de JSON de salida,
sujetos además al perfil y al techo de tokens/coste. No truncar un contrato.
Las respuestas de la API del catálogo conservan sus propios límites y api_version 1.0.
ID identifica operaciones nuevas del coordinador; CatalogID conserva identidades
existentes de la memoria científica. No recortar, renombrar o normalizar un ID del
catálogo para ajustarlo a otro dominio. Si la proyección pública redacta una
identidad sensible, bloquear su uso como referencia resoluble y pedir revisión.

### Identidad, bytes y fingerprints

- evidence.sha256 se refiere a los bytes capturados, sin reserializar JSON.
- El fingerprint de HypothesisManifest es el método implementado en contracts.py:
  incluye schema_version, market_hypothesis, data_requirements, signal_spec,
  parameter_space, execution_assumptions y evaluation_plan. No es equivalencia semántica.
- Los nuevos payloads TLAgents usarían canonical/digest de ese módulo, con namespace
  y versión en la identidad. La clave de operación la fija el host y liga sus entradas.
- Los fingerprints del catálogo los calcula trading_lab_catalog.models; su
  canonicalización no es idéntica a la de orquestación para todo Unicode.
  No intercambiar fingerprints de ambos dominios ni recalcularlos con otra función.
- La huella no firma al productor. Un producer o actor dentro de JSON no autentica
  al emisor: el host verifica canal, ownership y scope fuera del payload del modelo.

### Componentes comunes nuevos

PublicEvidence: todos obligatorios salvo que el tipo incluya null:
`reference_id: ID`, `kind: Texto`, `sha256: SHA|null`,
`verification: UNVERIFIED|HASH_VERIFIED|SOURCE_AUDITED`, `limitations: Texto[]`.
Solo el host puede producir/validar sus estados efectivos desde evidencia disponible.
El modelo cita reference_id, nunca concede verification ni abre su contenido.

CatalogRef: `entity_type: strategy|version|experiment|run|case|artifact|decision`,
`entity_id: CatalogID`, `record_fingerprint: SHA|null`, `checkpoint: SHA|null`,
`effective_status: UNVERIFIED|HASH_VERIFIED|SOURCE_AUDITED|UNKNOWN`.
Un fingerprint ausente en la respuesta se conserva null. La clasificación efectiva
es la del contexto del host, no una acreditación autodeclarada del modelo.

Source refs son identificadores públicos del paquete. Un mapa privado separado
resuelve paths/URLs si la política lo permite. No incorporar ese mapa a prompts.

### Sobre del host propuesto

TLAgents.Envelope 1.0: `message_id: ID`, `request_id: ID`, `producer: ID`,
`consumer: ID`, `created_at_utc: UTC`, `contract_kind: Texto`,
`payload_reference_id: ID`, `payload_sha256: SHA`, `policy_version: Texto`,
`operation_key: SHA`, `mode: SIMULATED|READ_ONLY_PROPOSAL`,
`authorization_reference_id: ID|null`. Además `schema_version: "1.0"`.
El host lo genera; la respuesta LLM solo contiene el payload de su contrato.
Una referencia de autorización no permite ejecutar hasta comprobar la frontera
existente. No hay modo EXECUTE en este sobre de agentes.

Ejemplo de sobre del host, sin autoridad operativa. payload_sha256 identifica
la serialización canónica UTF-8 del ResearchRequest documental siguiente; no se
utiliza esta reserialización para sustituir los bytes originales de una respuesta LLM.

```json
{
  "schema_version": "1.0",
  "message_id": "synthetic_message_001",
  "request_id": "design_request_001",
  "producer": "coordinator_python",
  "consumer": "quant_researcher_v1",
  "created_at_utc": "2026-11-21T08:00:00Z",
  "contract_kind": "ResearchRequest",
  "payload_reference_id": "synthetic_request_payload_001",
  "payload_sha256": "74d378ea50432340f2ab65b62b3a93fe4814b1dfecb229d49653c1ca6fb89e98",
  "policy_version": "TLAgents.policy/1.0",
  "operation_key": "e02f29c441f37272aeaad35ed1aae2067d00178db721699f70858ebdc89f1e63",
  "mode": "SIMULATED",
  "authorization_reference_id": null
}
```

## ResearchRequest 1.0 propuesto

Productor: coordinador Python. Consumidor: Investigador a través del broker.
Versión/kind: `1.0` / `ResearchRequest`. Estado PREPARED o BLOCKED.

| Campo | Tipo y obligación |
|---|---|
| schema_version, contract_kind | Constantes, obligatorias |
| request_id | ID, obligatorio; identidad idempotente del host |
| flow | FLOW1 o FLOW2, obligatorio |
| objective | Texto, obligatorio |
| market | Objeto obligatorio: asset, market_type y timeframe Texto; requested_years entero 1–30 o null; coverage_start_utc/end UTC o null |
| source_refs | PublicEvidence[], obligatorio, al menos una para PREPARED |
| catalog_context | CatalogRef[], obligatorio; puede estar vacío si se declara ausencia |
| discovery | Objeto: statistics_reference_id ID|null, searches_count entero no negativo|null, period_start_utc/end UTC|null |
| max_hypotheses | Entero 1–3, obligatorio, piloto 1 |
| status | PREPARED o BLOCKED, obligatorio |
| limitations | Texto[], obligatorio, puede estar vacío |
| notes | Texto|null, opcional |

PREPARED exige coherencia de cobertura y fuentes; no significa permiso API.
FLOW2 exige estadísticas con procedencia antes de pedir conclusiones sobre patrones.
Errores: INPUT_INVALID, SOURCE_MISSING, COVERAGE_UNKNOWN, CAPABILITY_UNSUPPORTED.

```json
{
  "schema_version": "1.0",
  "contract_kind": "ResearchRequest",
  "request_id": "design_request_001",
  "flow": "FLOW1",
  "objective": "Formulate a falsifiable research hypothesis; no execution",
  "market": {
    "asset": "BTCUSDT",
    "market_type": "spot",
    "timeframe": "1h",
    "requested_years": null,
    "coverage_start_utc": null,
    "coverage_end_utc": null
  },
  "source_refs": [
    {
      "reference_id": "synthetic_source_01",
      "kind": "SYNTHETIC_DOCUMENTATION",
      "sha256": "c69dc9fa8b69341d2a67e72629faf631d296b2a5bc214b4be6c7d87e18bfdc24",
      "verification": "UNVERIFIED",
      "limitations": [
        "Artificial documentation bytes; not audited evidence"
      ]
    }
  ],
  "catalog_context": [
    {
      "entity_type": "strategy",
      "entity_id": "synthetic_strategy_01",
      "record_fingerprint": null,
      "checkpoint": "6c4b5fbe2e70caeef006b93f7f1da77937c00a4f7c99f989671665d1c8e10f72",
      "effective_status": "UNKNOWN"
    }
  ],
  "discovery": {
    "statistics_reference_id": null,
    "searches_count": null,
    "period_start_utc": null,
    "period_end_utc": null
  },
  "max_hypotheses": 1,
  "status": "PREPARED",
  "limitations": [
    "Dataset availability not verified"
  ],
  "notes": null
}
```

## ResearchHypothesis 1.0 propuesto

Productor: Investigador. Consumidores: host y Diseñador tras revisión.
Kind ResearchHypothesis. Estados HYPOTHESIS_PROPOSED, NO_HYPOTHESIS, NEEDS_REVIEW.

| Campo | Tipo y obligación |
|---|---|
| schema_version, contract_kind | Constantes obligatorias |
| request_id | ID de entrada, obligatorio |
| status | Estado de propuesta, obligatorio |
| candidates | HypothesisDraft[], obligatorio, 0–3 y no más que el límite de entrada |
| rejected_reasons | Texto[], obligatorio |
| missing_fields | Texto[], obligatorio |
| notes | Texto|null, opcional |

HypothesisDraft exige todos estos campos: hypothesis_id ID; asset, market_type,
timeframe, statement, justification Texto; source_ids, evidence_ids ID[];
observable_conditions, falsification, bias_risks, limitations Texto[];
catalog_refs CatalogRef[]; verification_status constante DECLARED.
En HYPOTHESIS_PROPOSED hay al menos una candidata con condiciones y falsación;
NO_HYPOTHESIS exige candidates=[]; NEEDS_REVIEW enumera faltantes y no habilita diseño.
El host contrasta referencias y estados contra el paquete y fija la identidad final.
Errores: INVENTED_REFERENCE, UNSUPPORTED_CLAIM, MISSING_FALSIFICATION, POLICY_BLOCKED.

No sustituye HypothesisManifest. Una propuesta no contiene necesariamente entradas,
salidas y protocolo completos; se mantiene fuera del Store de admisión hasta completarlos.

```json
{
  "schema_version": "1.0",
  "contract_kind": "ResearchHypothesis",
  "request_id": "design_request_001",
  "status": "HYPOTHESIS_PROPOSED",
  "candidates": [
    {
      "hypothesis_id": "design_hypothesis_001",
      "asset": "BTCUSDT",
      "market_type": "spot",
      "timeframe": "1h",
      "statement": "A causal breakout might persist after costs; exploratory proposal only",
      "justification": "Synthetic teaching example, not evidence of an edge",
      "source_ids": [
        "synthetic_source_01"
      ],
      "evidence_ids": [],
      "observable_conditions": [
        "Close exceeds a previously available rolling high"
      ],
      "falsification": [
        "Reject if the preregistered net expectancy diagnostic is nonpositive"
      ],
      "bias_risks": [
        "Multiple testing count unknown",
        "Previously observed history"
      ],
      "limitations": [
        "No verified dataset or economic result"
      ],
      "catalog_refs": [
        {
          "entity_type": "strategy",
          "entity_id": "synthetic_strategy_01",
          "record_fingerprint": null,
          "checkpoint": "6c4b5fbe2e70caeef006b93f7f1da77937c00a4f7c99f989671665d1c8e10f72",
          "effective_status": "UNKNOWN"
        }
      ],
      "verification_status": "DECLARED"
    }
  ],
  "rejected_reasons": [],
  "missing_fields": [],
  "notes": null
}
```

## StrategySpecification 1.0 propuesto

Productor: Diseñador. Consumidor: host, revisión humana y preparación de Codex.
Kind StrategySpecification. Estados DRAFT, NEEDS_REVIEW, SPECIFICATION_PREPARED.

| Campo | Tipo y obligación |
|---|---|
| schema_version, contract_kind | Constantes obligatorias |
| request_id, research_hypothesis_id | IDs obligatorios, lineage con la propuesta revisada |
| status | Estado de especificación, obligatorio |
| manifest | HypothesisManifest 1.0 completo y sin campos añadidos, o null únicamente en DRAFT/NEEDS_REVIEW; clave obligatoria |
| capital_policy | RESET_PER_SEGMENT, CONTINUOUS o UNKNOWN; obligatorio |
| formulas | Formula[], obligatorio; al menos una si hay indicador |
| risk_constraints | Objeto con risk_per_trade_pct, max_position_pct, max_exposure_pct finitos y max_open_positions entero ≥1, según runner; null solo en DRAFT/NEEDS_REVIEW |
| cost_scenarios | CostScenario[], obligatorio; BASE y ADVERSE cuando el protocolo los exija |
| capability_reference_ids | ID[] obligatorio; evidencias del host, no inventadas |
| implementation_operation | NEW_STRATEGY, NEW_EXPERIMENT o UNSUPPORTED |
| missing_fields, review_requirements | Texto[], obligatorios |
| notes | Texto|null, opcional |

Formula: name, expression, units, availability Texto; lookback_bars entero ≥0;
shift_bars entero ≥0; warmup_rule y gap_rule Texto. Una fórmula es especificación,
no código para eval. Las dependencias y el índice excluido/incluido deben ser explícitos.
CostScenario: name BASE|ADVERSE y trading_fee_pct/slippage_pct/spread_pct finitos,
no negativos. Funding se declara en el manifiesto y el protocolo especializado.

SPECIFICATION_PREPARED exige missing_fields vacío, capacidad y fuentes verificadas,
manifest y risk_constraints no nulos, capital distinto de UNKNOWN y
parámetros/protocolo congelados por el host. Las fórmulas y los escenarios de coste
requeridos por el protocolo deben estar completos.
Si faltan reglas esenciales, DRAFT/NEEDS_REVIEW puede conservar manifest=null,
risk_constraints=null y listas vacías de fórmulas o costes aún desconocidos;
missing_fields debe explicar cada ausencia. No construir una ficha ficticia para
poder devolver un error. Ese borrador no se valida como HypothesisManifest ni se
envía a registro, implementación o ejecución.
No se concede autorización por esa etiqueta. El ejemplo queda NEEDS_REVIEW porque
el dataset está pendiente, sin inventar su hash o cambiar el contrato vigente.
Errores: INCOMPLETE_SPEC, CAPABILITY_UNSUPPORTED, COST_UNITS_INVALID, HOLDOUT_CONFLICT.

### Mapeo científico sin perder identidad

HypothesisManifest no tiene campos estructurados separados para capital_policy,
todos los escenarios de coste o una lista de fórmulas. El fingerprint del Store
solo incluye sus campos implementados. Por ello no basta guardar el suplemento
en una nota externa: cambiar capital o ADVERSE podría deduplicarse incorrectamente.

Gate futuro obligatorio antes de SPECIFICATION_PREPARED/admisión:

| Dato complementario | Campo vigente donde debe quedar representado explícitamente |
|---|---|
| Fórmulas, unidades, shift/warmup/gaps | signal_spec.feature_definitions y las reglas de señal pertinentes |
| Restricciones de sizing/riesgo y política de capital | execution_assumptions.sizing |
| Escenarios BASE/ADVERSE y reglas de robustez | execution_assumptions para BASE; evaluation_plan.robustness_plan para los escenarios completos |
| Protocolo temporal y selección de parámetros | evaluation_plan y parameter_space |

Propuesta de serialización para especificaciones NUEVAS: el host incorpora una
sección etiquetada TLAgents.semantic/1.0 con JSON canonical de los objetos pertinentes
dentro de esos campos Text, preservando una explicación inequívoca y sin campos extra.
El diseño completo se revisa y se sella después de ese mapeo; conserva también los
bytes de la propuesta previa. No se normalizan o reescriben manifiestos históricos.
Las proyecciones y el manifiesto revisado deben concordar; una contradicción bloquea.
La huella completa de StrategySpecification y las refs se guardan en el recibo del
host, aunque ImplementationRequest mantenga su formato existente.

El verificador futuro tendrá que probar que una modificación relevante de capital,
fórmulas o costes cambia el fingerprint científico o se bloquea explícitamente.
Si no existe un mapeo fiel al contrato y al runner, detener la admisión y proponer
una extensión versionada en otra entrega. No fabricar equivalencia por texto parecido.
El ejemplo siguiente es anterior a ese gate y conserva NEEDS_REVIEW.

Ejemplo adicional de aclaración cuando todavía no es posible construir el
manifiesto. Es un payload TLAgents propuesto: deliberadamente no se entrega a
HypothesisManifest, al Store ni a Codex.

```json
{
  "schema_version": "1.0",
  "contract_kind": "StrategySpecification",
  "request_id": "design_request_001",
  "research_hypothesis_id": "design_hypothesis_001",
  "status": "NEEDS_REVIEW",
  "manifest": null,
  "capital_policy": "UNKNOWN",
  "formulas": [],
  "risk_constraints": null,
  "cost_scenarios": [],
  "capability_reference_ids": [],
  "implementation_operation": "UNSUPPORTED",
  "missing_fields": [
    "Entry and exit rules",
    "Risk, capital and cost assumptions"
  ],
  "review_requirements": [
    "Clarify essential rules before preparing an implementation request"
  ],
  "notes": null
}
```

Ejemplo con un manifiesto completo en estructura, pero todavía pendiente de
verificar dataset y capacidades; tampoco autoriza implementación o ejecución:

```json
{
  "schema_version": "1.0",
  "contract_kind": "StrategySpecification",
  "request_id": "design_request_001",
  "research_hypothesis_id": "design_hypothesis_001",
  "status": "NEEDS_REVIEW",
  "manifest": {
    "schema_version": "1.0",
    "hypothesis_id": "design_hypothesis_001",
    "created_at_utc": "2026-11-21T08:00:00Z",
    "researcher_version": "TLAgents.designer/1.0",
    "title": "Synthetic documentation specification; no executed study",
    "market_hypothesis": "Una ruptura del maximo previo de 20 barras podria persistir.",
    "rationale": "Ejemplo para comprobar ingesta; no es una propuesta aprobada.",
    "source_refs": [
      {
        "reference": "synthetic_source_01",
        "accessed_on": "2026-11-21",
        "verification": "UNVERIFIED"
      }
    ],
    "data_requirements": {
      "assets": [
        "BTC/USDT"
      ],
      "timeframe": "1h",
      "horizon": "2022-02-01 a 2022-06-01 UTC, fin exclusivo",
      "warmup_bars": 200,
      "gap_policy": "Rechazar cualquier gap en warmup o periodo evaluado; no rellenar.",
      "funding_policy": "NOT_APPLICABLE",
      "dataset_refs": [
        "PENDING: bundle spot BTC/USDT 1h; no se abre ni descarga en 4.1"
      ],
      "availability": "PENDING"
    },
    "signal_spec": {
      "long_entry": "Al cierre T, close[T] > max(high[T-20:T]); no incluir high[T].",
      "long_exit": "Al cierre T, close[T] < min(low[T-10:T]); no incluir low[T].",
      "short_entry": null,
      "short_exit": null,
      "unsupported_modes": [
        "SHORT_ONLY"
      ],
      "availability": "CANDLE_CLOSE",
      "feature_definitions": "Maximo/minimo rolling desplazados una barra; ATR14 Wilder causal; primeras 200 barras sin entradas. Ventanas en barras completas."
    },
    "parameter_space": {
      "parameters": {
        "entry_window": {
          "values": [
            20
          ],
          "rationale": "Referencia unica, sin seleccion."
        },
        "exit_window": {
          "values": [
            10
          ],
          "rationale": "Salida unica predeclarada."
        }
      },
      "combination_limit": 1,
      "limit_rationale": "Solo probar el contrato; ninguna simulacion en esta entrega."
    },
    "execution_assumptions": {
      "market_mode": "spot",
      "runner_protocol": "StudyBackend v1; compatibilidad pendiente de revision manual",
      "entry_timing": "NEXT_OPEN",
      "trading_fee_pct": 0.05,
      "slippage_pct": 0.03,
      "spread_pct": 0.01,
      "stop": "ATR14 Wilder x2 disponible al cierre de entrada, bracket fijado a next-open.",
      "target": "2R desde next-open; sin trailing ni time stop.",
      "sizing": "stop_risk 1% capital; max_position_pct 25, max_exposure_pct 100; sin piramidacion.",
      "intrabar_policy": "Stop-first si stop y target coinciden; gaps al precio adverso disponible. Costes en ambos lados."
    },
    "evaluation_plan": {
      "train": {
        "start": "2022-02-01T00:00:00Z",
        "end": "2022-04-01T00:00:00Z"
      },
      "validation": {
        "start": "2022-04-01T00:00:00Z",
        "end": "2022-05-01T00:00:00Z"
      },
      "test": {
        "start": "2022-05-01T00:00:00Z",
        "end": "2022-06-01T00:00:00Z"
      },
      "holdout_status": "CONSUMED",
      "holdout_risk": "Historia previamente observada a nivel de proyecto; no independiente.",
      "walk_forward": "No previsto en este ejemplo singleton; requeriria protocolo nuevo.",
      "primary_metric": "Expectancy neta TRAIN; sin seleccion de parametros.",
      "falsification": "Rechazar si expectancy neta validation <=0; TEST solo diagnostico retrospectivo.",
      "robustness_plan": "Futuro stress predeclarado con costes x2 y periodos anuales; no ejecutado."
    },
    "novelty": {
      "prior_work": "Solapa Donchian; ejemplo de contrato, no familia nueva.",
      "known_searches": null,
      "known_variants": null
    },
    "limitations": [
      "Datos y causalidad no auditados por la CLI.",
      "No es YAML experimental ni autoriza desarrollo o backtests."
    ],
    "expected_compute_class": "SMALL",
    "requires_new_strategy_code": false,
    "status": "PROPOSED"
  },
  "capital_policy": "RESET_PER_SEGMENT",
  "formulas": [
    {
      "name": "prior_high",
      "expression": "max(high[T-20:T]); exclude T",
      "units": "quote currency",
      "availability": "CANDLE_CLOSE",
      "lookback_bars": 20,
      "shift_bars": 1,
      "warmup_rule": "No entries during 200 context bars",
      "gap_rule": "Reject discontinuities"
    }
  ],
  "risk_constraints": {
    "risk_per_trade_pct": 1.0,
    "max_position_pct": 25.0,
    "max_exposure_pct": 100.0,
    "max_open_positions": 1
  },
  "cost_scenarios": [
    {
      "name": "BASE",
      "trading_fee_pct": 0.05,
      "slippage_pct": 0.03,
      "spread_pct": 0.01
    },
    {
      "name": "ADVERSE",
      "trading_fee_pct": 0.1,
      "slippage_pct": 0.06,
      "spread_pct": 0.02
    }
  ],
  "capability_reference_ids": [],
  "implementation_operation": "NEW_EXPERIMENT",
  "missing_fields": [
    "Verified dataset identity",
    "Reviewed runner capability reference"
  ],
  "review_requirements": [
    "Operator review before implementation; no execution approved"
  ],
  "notes": null
}
```

## ImplementationRequest 1.0 existente

Productor: Coordinator de implementación, después de la revisión externa.
Consumidor: CodexCLI controlado. No lo genera ni lo autoriza el Diseñador.
Fuente normativa: [implementation_contracts.py](../../src/trading_lab_orchestration/implementation_contracts.py).

Campos obligatorios reales: schema_version="1.0", mode="PREPARE_ONLY",
attempt_id, attempt_number entero, task_id, candidate_id, hypothesis_manifest
(HypothesisManifest), hypothesis_sha256 (SHA), base_commit, branch, workspace,
plan (ImplementationPlan), allowed_write_paths, protected_paths,
authorized_checks (listas argv), skill_paths, previous_attempt (Texto|null),
max_api_eur=null y max_cpu_seconds=null. native_interface_check es opcional y
solo admite null o SYNTHETIC_OHLCV_UTC_V1. La restricción de intentos 1–3 se aplica
en la reserva y su scope, no se inventa un nuevo presupuesto en el modelo.

ImplementationPlan exige schema_version, operation NEW_STRATEGY|NEW_EXPERIMENT,
target, specification_reviewed=true, review_note, max_wall_seconds 1–1800 y
check_timeout_seconds 1–120. Las rutas y los checks se derivan por su implementación.
El booleano procede del host revisado; no autentica una respuesta del LLM.
PREPARE_ONLY no significa que el adaptador jamás invoque Codex: el lanzamiento
requiere la operación autorizada existente y no habilita backtests ni trading.

Errores del host: IDENTITY_CONFLICT, SPEC_NOT_REVIEWED, PATH_SCOPE_VIOLATION,
ACTIVE_OR_UNKNOWN_ATTEMPT, AUTHORIZATION_REQUIRED. Son códigos de diseño del broker,
no se afirma que las excepciones actuales ya tengan esos códigos estructurados.
Las rutas siguientes son ficticias, de un encargo sintético; no existen en el host.

```json
{
  "schema_version": "1.0",
  "mode": "PREPARE_ONLY",
  "attempt_id": "synthetic_attempt_001",
  "attempt_number": 1,
  "task_id": "synthetic_task_001",
  "candidate_id": "synthetic_candidate_001",
  "hypothesis_manifest": {
    "schema_version": "1.0",
    "hypothesis_id": "design_hypothesis_001",
    "created_at_utc": "2026-11-21T08:00:00Z",
    "researcher_version": "TLAgents.designer/1.0",
    "title": "Synthetic documentation specification; no executed study",
    "market_hypothesis": "Una ruptura del maximo previo de 20 barras podria persistir.",
    "rationale": "Ejemplo para comprobar ingesta; no es una propuesta aprobada.",
    "source_refs": [
      {
        "reference": "synthetic_source_01",
        "accessed_on": "2026-11-21",
        "verification": "UNVERIFIED"
      }
    ],
    "data_requirements": {
      "assets": [
        "BTC/USDT"
      ],
      "timeframe": "1h",
      "horizon": "2022-02-01 a 2022-06-01 UTC, fin exclusivo",
      "warmup_bars": 200,
      "gap_policy": "Rechazar cualquier gap en warmup o periodo evaluado; no rellenar.",
      "funding_policy": "NOT_APPLICABLE",
      "dataset_refs": [
        "PENDING: bundle spot BTC/USDT 1h; no se abre ni descarga en 4.1"
      ],
      "availability": "PENDING"
    },
    "signal_spec": {
      "long_entry": "Al cierre T, close[T] > max(high[T-20:T]); no incluir high[T].",
      "long_exit": "Al cierre T, close[T] < min(low[T-10:T]); no incluir low[T].",
      "short_entry": null,
      "short_exit": null,
      "unsupported_modes": [
        "SHORT_ONLY"
      ],
      "availability": "CANDLE_CLOSE",
      "feature_definitions": "Maximo/minimo rolling desplazados una barra; ATR14 Wilder causal; primeras 200 barras sin entradas. Ventanas en barras completas."
    },
    "parameter_space": {
      "parameters": {
        "entry_window": {
          "values": [
            20
          ],
          "rationale": "Referencia unica, sin seleccion."
        },
        "exit_window": {
          "values": [
            10
          ],
          "rationale": "Salida unica predeclarada."
        }
      },
      "combination_limit": 1,
      "limit_rationale": "Solo probar el contrato; ninguna simulacion en esta entrega."
    },
    "execution_assumptions": {
      "market_mode": "spot",
      "runner_protocol": "StudyBackend v1; compatibilidad pendiente de revision manual",
      "entry_timing": "NEXT_OPEN",
      "trading_fee_pct": 0.05,
      "slippage_pct": 0.03,
      "spread_pct": 0.01,
      "stop": "ATR14 Wilder x2 disponible al cierre de entrada, bracket fijado a next-open.",
      "target": "2R desde next-open; sin trailing ni time stop.",
      "sizing": "stop_risk 1% capital; max_position_pct 25, max_exposure_pct 100; sin piramidacion.",
      "intrabar_policy": "Stop-first si stop y target coinciden; gaps al precio adverso disponible. Costes en ambos lados."
    },
    "evaluation_plan": {
      "train": {
        "start": "2022-02-01T00:00:00Z",
        "end": "2022-04-01T00:00:00Z"
      },
      "validation": {
        "start": "2022-04-01T00:00:00Z",
        "end": "2022-05-01T00:00:00Z"
      },
      "test": {
        "start": "2022-05-01T00:00:00Z",
        "end": "2022-06-01T00:00:00Z"
      },
      "holdout_status": "CONSUMED",
      "holdout_risk": "Historia previamente observada a nivel de proyecto; no independiente.",
      "walk_forward": "No previsto en este ejemplo singleton; requeriria protocolo nuevo.",
      "primary_metric": "Expectancy neta TRAIN; sin seleccion de parametros.",
      "falsification": "Rechazar si expectancy neta validation <=0; TEST solo diagnostico retrospectivo.",
      "robustness_plan": "Futuro stress predeclarado con costes x2 y periodos anuales; no ejecutado."
    },
    "novelty": {
      "prior_work": "Solapa Donchian; ejemplo de contrato, no familia nueva.",
      "known_searches": null,
      "known_variants": null
    },
    "limitations": [
      "Datos y causalidad no auditados por la CLI.",
      "No es YAML experimental ni autoriza desarrollo o backtests."
    ],
    "expected_compute_class": "SMALL",
    "requires_new_strategy_code": false,
    "status": "PROPOSED"
  },
  "hypothesis_sha256": "a0b51db4ca31f1b40bb21b59af931a4735727f73d2966d70776844c0e528235b",
  "base_commit": "077acd4bb1956c8e10302c45708c4bdc112be0df",
  "branch": "fixture/design-example",
  "workspace": "/synthetic/documentation-only/workspace",
  "plan": {
    "schema_version": "1.0",
    "operation": "NEW_EXPERIMENT",
    "target": "catalog_design_example_v1",
    "specification_reviewed": true,
    "review_note": "Fictional review for a documentation example; not an operator permission",
    "max_wall_seconds": 300,
    "check_timeout_seconds": 45
  },
  "allowed_write_paths": [
    "configs/experiments/catalog_design_example_v1.yaml",
    "tests/unit/test_catalog_design_example_v1.py"
  ],
  "protected_paths": [
    "src/quant_lab/study_backend.py",
    "src/trading_lab_orchestration",
    "data",
    "results"
  ],
  "authorized_checks": [
    [
      "python",
      "-m",
      "pytest",
      "tests/unit/test_catalog_design_example_v1.py",
      "-q",
      "-p",
      "no:cacheprovider"
    ],
    [
      "python",
      "-m",
      "ruff",
      "check",
      "--no-cache",
      "tests/unit/test_catalog_design_example_v1.py"
    ],
    [
      "python",
      "-m",
      "ruff",
      "format",
      "--check",
      "--no-cache",
      "tests/unit/test_catalog_design_example_v1.py"
    ]
  ],
  "skill_paths": [
    "skills/create-experiment/SKILL.md"
  ],
  "previous_attempt": null,
  "max_api_eur": null,
  "max_cpu_seconds": null,
  "native_interface_check": null
}
```

El ModelDelivery 1.0 de Codex conserva tests_run=NOT_RUN_BY_MODEL. Sus afirmaciones
no sustituyen el proceso de checks ni el recibo anfitrión validado.

## ImplementationEvidence 1.0 propuesto

Productor: host que proyecta el recibo existente. Consumidores: controlador y
paquetes de auditoría. No es otro recibo primario ni una entrega acreditada por Codex.

| Campo | Tipo y obligación |
|---|---|
| schema_version, contract_kind | Constantes 1.0 / ImplementationEvidence |
| candidate_id, task_id, attempt_id | IDs obligatorios |
| status | SUCCEEDED, FAILED, BLOCKED, TIMED_OUT o UNKNOWN |
| base_commit | Commit obligatorio |
| receipt | PublicEvidence obligatorio |
| final_files | Lista de {repository_path Texto relativo seguro, sha256 SHA}, obligatoria |
| check_evidence | PublicEvidence[], obligatorio, sin afirmar tests ausentes |
| limitations | Texto[], obligatorio |
| notes | Texto|null, opcional |

SUCCEEDED exige recibo verificado y alcance de archivos/checks concordante en el
host. Un raw ModelDelivery no basta. La versión original del recibo se conserva
en receipt.kind/referencia, no se le asigna silenciosamente otra estructura.
Errores: RECEIPT_MISSING, HASH_MISMATCH, UNVERIFIED_DELIVERY, CHECKS_INCOMPLETE.

```json
{
  "schema_version": "1.0",
  "contract_kind": "ImplementationEvidence",
  "candidate_id": "synthetic_candidate_001",
  "task_id": "synthetic_task_001",
  "attempt_id": "synthetic_attempt_001",
  "status": "UNKNOWN",
  "base_commit": "077acd4bb1956c8e10302c45708c4bdc112be0df",
  "receipt": {
    "reference_id": "synthetic_receipt_01",
    "kind": "SYNTHETIC_DOCUMENTATION",
    "sha256": "81474e18c1b27d61b9adbf57bcec2a030b80ca7cbc36d6d5ab074463aa6a3fb6",
    "verification": "UNVERIFIED",
    "limitations": [
      "No process or calculation executed"
    ]
  },
  "final_files": [],
  "check_evidence": [],
  "limitations": [
    "Fictional example; no implementation or checks executed"
  ],
  "notes": null
}
```

## BacktestEvidenceReference 1.0 propuesto

Productor: host tras resolver el verificador del protocolo. Consumidores:
auditoría/Validador. Ningún campo concede un nuevo permiso de ejecución.

| Campo | Tipo y obligación |
|---|---|
| schema_version, contract_kind | Constantes 1.0 / BacktestEvidenceReference |
| execution_id, run_id, experiment_id | IDs obligatorios |
| kind | SYNTHETIC, HISTORICAL o PROSPECTIVE, obligatorio |
| execution_status | PREPARED, RUNNING, SUCCEEDED, FAILED, TIMED_OUT, BLOCKED, UNKNOWN o CANCELLED |
| native_status | COMPLETE, INCOMPLETE, FAILED o UNKNOWN |
| sealing_status | SEALED, UNSEALED, UNKNOWN o NOT_APPLICABLE |
| engine, protocol | Texto, obligatorios |
| job_sha256 | SHA|null, obligatorio; no todos los runners tienen un job equivalente |
| receipt | PublicEvidence obligatorio |
| case_ids | CatalogID[] obligatorio; por escenario/segmento, no observaciones independientes |
| holdout | CONSUMED, UNOBSERVED o UNKNOWN |
| capital_policy | RESET_PER_SEGMENT, CONTINUOUS o UNKNOWN |
| limitations | Texto[], obligatorio |
| notes | Texto|null, opcional |

El traductor conserva además los estados nativos originales en el paquete del
host; la proyección nunca convierte SUCCEEDED o una salida Docker en COMPLETE.
No adapta un AuditRequest ordinario al Issue #3 inventando identidades: usa la
referencia a su fuente sellada y verificador específico. No se recalculan resultados.
Errores: OUTCOME_UNKNOWN, INCOMPLETE_EVIDENCE, DATASET_MISMATCH, PROTOCOL_UNSUPPORTED.

```json
{
  "schema_version": "1.0",
  "contract_kind": "BacktestEvidenceReference",
  "execution_id": "synthetic_execution_001",
  "run_id": "synthetic_run_001",
  "experiment_id": "catalog_design_example_v1",
  "kind": "SYNTHETIC",
  "execution_status": "UNKNOWN",
  "native_status": "UNKNOWN",
  "sealing_status": "UNKNOWN",
  "engine": "StudyBackend v1",
  "protocol": "Synthetic documentation example; no calculation",
  "job_sha256": null,
  "receipt": {
    "reference_id": "synthetic_receipt_01",
    "kind": "SYNTHETIC_DOCUMENTATION",
    "sha256": "81474e18c1b27d61b9adbf57bcec2a030b80ca7cbc36d6d5ab074463aa6a3fb6",
    "verification": "UNVERIFIED",
    "limitations": [
      "No process or calculation executed"
    ]
  },
  "case_ids": [],
  "holdout": "CONSUMED",
  "capital_policy": "RESET_PER_SEGMENT",
  "limitations": [
    "No result exists"
  ],
  "notes": null
}
```

## ValidationAssessment 1.0 propuesto

Productor: Validador o asesor excepcional. Consumidor: host y revisión humana.
Kind ValidationAssessment; estado CONSULTATIVE o NEEDS_REVIEW, sin aprobación.

| Campo | Tipo y obligación |
|---|---|
| schema_version, contract_kind | Constantes obligatorias |
| request_id | ID obligatorio |
| agent_role | validator o coordinator_advisory |
| status | CONSULTATIVE o NEEDS_REVIEW |
| source_run_ids | CatalogID[] obligatorio, vacío solo para incidencia sin run |
| model_review | ModelReview 1.0 existente: schema_version, findings, evidence_references, uncertainties, verdict=NO_DECISION y demo_authorized=false |
| recommendation | NO_DECISION, REQUEST_MORE_EVIDENCE, CONTINUE_RESEARCH o DO_NOT_ADVANCE |
| limitations | Texto[], obligatorio |
| does_not_override_source | Constante true |
| notes | Texto|null, opcional |

Las observaciones, debilidades y riesgos se expresan en findings/uncertainties
citados; no se reescriben métricas o el dictamen primario. El host comprueba que
evidence_references pertenece al paquete. No se introduce un estado favorable
en el catálogo desde esta salida. Errores: INVENTED_REFERENCE, PROMOTION_ATTEMPT,
AUDIT_BLOCKED, METRIC_CONTRADICTION.

```json
{
  "schema_version": "1.0",
  "contract_kind": "ValidationAssessment",
  "request_id": "design_request_001",
  "agent_role": "validator",
  "status": "NEEDS_REVIEW",
  "source_run_ids": [
    "synthetic_run_001"
  ],
  "model_review": {
    "schema_version": "1.0",
    "findings": [
      "No verified execution evidence is available"
    ],
    "evidence_references": [
      "synthetic_receipt_01"
    ],
    "uncertainties": [
      "Execution outcome unknown"
    ],
    "verdict": "NO_DECISION",
    "demo_authorized": false
  },
  "recommendation": "DO_NOT_ADVANCE",
  "limitations": [
    "Documentation example, not an independent audit"
  ],
  "does_not_override_source": true,
  "notes": null
}
```

## CoordinationDecision 1.0 propuesto

Productor exclusivo: coordinador Python. Consumidores: interfaz del operador y
despachador autorizado. El asesor IA no produce este contrato final.

| Campo | Tipo y obligación |
|---|---|
| schema_version, contract_kind | Constantes 1.0 / CoordinationDecision |
| decision_id, request_id | IDs obligatorios |
| actor | Constante coordinator_python |
| decision | WAIT_FOR_OPERATOR, PREPARE_HANDOFF, BLOCK, RECONCILE o CLOSE |
| stage | RESEARCH, DESIGN, IMPLEMENTATION, BACKTEST, AUDIT, BILLING, NOTICE o CLOSED |
| resource_state | Texto|null; estado real leído, no orden de persistir una etiqueta |
| reason_codes | Texto[], obligatorio, al menos uno |
| evidence_reference_ids | ID[] obligatorio; no rutas |
| authorization_reference_id | ID|null; referencia externa comprobable, no un grant |
| next_action | NONE, REVIEW, READ_EXISTING o PREPARE_REVIEW |
| created_at_utc | UTC obligatorio |
| notes | Texto|null, opcional |

No contiene una acción RUN, SEND, APPROVE o TRADE. Un efecto posterior usa su
contrato y frontera existentes. El host aplica precondiciones por estado y registro,
no acepta actor del JSON como prueba de identidad. Errores: STALE_CHECKPOINT,
MISSING_AUTHORIZATION, RESERVATION_UNKNOWN, IDENTITY_CONFLICT, BUDGET_BLOCKED.

```json
{
  "schema_version": "1.0",
  "contract_kind": "CoordinationDecision",
  "decision_id": "synthetic_decision_001",
  "request_id": "design_request_001",
  "actor": "coordinator_python",
  "decision": "RECONCILE",
  "stage": "BACKTEST",
  "resource_state": "UNKNOWN",
  "reason_codes": [
    "RESERVATION_UNKNOWN"
  ],
  "evidence_reference_ids": [
    "synthetic_receipt_01"
  ],
  "authorization_reference_id": null,
  "next_action": "REVIEW",
  "created_at_utc": "2026-11-21T08:00:00Z",
  "notes": "Fictional projection; no real reservation exists"
}
```

## NotificationSummary 1.0 propuesto

Productor: proyección determinista del host. Consumidores: operador y adaptador
de outbox existente; nunca un transporte decidido por el modelo.

| Campo | Tipo y obligación |
|---|---|
| schema_version, contract_kind | Constantes 1.0 / NotificationSummary |
| notification_id, request_id, audit_id | IDs obligatorios |
| status | DRAFT, SENDING, ACCEPTED, RETRYABLE, FAILED o UNKNOWN |
| message | Texto máximo 4096 caracteres y límites de transporte vigentes |
| message_sha256 | SHA de los bytes UTF-8 exactos, obligatorio |
| evidence_reference_ids | ID[] obligatorio |
| recipient_binding_sha256 | SHA|null, fijado por host/operador, nunca por LLM |
| service_message_id | Entero positivo|null; solo con recibo confirmado |
| real_send_performed | Booleano del host, coherente con su evidencia |
| limitations | Texto[], obligatorio |
| notes | Texto|null, opcional |

DRAFT exige real_send_performed=false y service_message_id=null. ACCEPTED
requiere evidencia del servicio; no acredita lectura humana. UNKNOWN conserva
incertidumbre y no autoriza otra entrega. La mera existencia de este resumen no
crea un aviso fuera del contrato técnico soportado por Outbox.preview.
Errores: RECIPIENT_NOT_VERIFIED, MESSAGE_CHANGED, DELIVERY_UNKNOWN, UNSUPPORTED_NOTICE.

```json
{
  "schema_version": "1.0",
  "contract_kind": "NotificationSummary",
  "notification_id": "synthetic_notice_001",
  "request_id": "design_request_001",
  "audit_id": "synthetic_audit_001",
  "status": "DRAFT",
  "message": "Synthetic draft. NO_DECISION. No trading authorization. No message sent.",
  "message_sha256": "20f4cba3914a4c7305489fcd2d8bece22ec27bc22dbea21de2b8812d0be668a4",
  "evidence_reference_ids": [
    "synthetic_receipt_01"
  ],
  "recipient_binding_sha256": null,
  "service_message_id": null,
  "real_send_performed": false,
  "limitations": [
    "Not enqueued; fictional outbox projection"
  ],
  "notes": null
}
```

## 2. Ejemplos, huellas y validación de esta fase

Los hashes de los ejemplos identifican cadenas UTF-8 artificiales publicadas
en esta sección, no archivos ni recibos históricos. Ningún ejemplo concede permisos.
Las marcas UNVERIFIED son deliberadas: no se simula una acreditación real.
Una plantilla que reutiliza un modelo se valida solo estructuralmente con ese
modelo; no se inicializa Store ni se llama al productor real del contrato.

| Bytes artificiales UTF-8 (cadena JSON) | SHA-256 |
|---|---|
| `"synthetic-source-v1"` | `c69dc9fa8b69341d2a67e72629faf631d296b2a5bc214b4be6c7d87e18bfdc24` |
| `"synthetic-receipt-v1"` | `81474e18c1b27d61b9adbf57bcec2a030b80ca7cbc36d6d5ab074463aa6a3fb6` |
| `"# synthetic file; not an implementation\n"` | `e6aad11fa2c99257d0d349db0a0fa9de7620b6099795c9eeb4177d63763d75fb` |
| `"synthetic-catalogue-checkpoint-v1"` | `6c4b5fbe2e70caeef006b93f7f1da77937c00a4f7c99f989671665d1c8e10f72` |

Los contratos nuevos requieren validadores futuros para todos los invariantes de
estas tablas. Parsear los ejemplos y validarlos estructuralmente no constituye una
implementación de agentes o aceptación operativa. Errores estructurales devuelven
salida rechazada y recibo del host; no hay reparación pagada automática.
