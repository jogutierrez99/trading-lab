# Plan incremental de implementación y pruebas — V1

Diseño 5.9B.0. Esta lista no comunica pruebas de agentes ejecutadas ni autoriza
las fases siguientes. El [maestro](multiagent-master-v1.md) y la política de
[permisos](agent-permissions-v1.md) prevalecen sobre cualquier ejemplo.

## 1. Estrategia de verificación

Separar cuatro niveles:

1. Validación documental actual: enlaces, JSON, campos, correspondencia con código
   existente, hashes de fuentes y diff exclusivamente Markdown.
2. Pruebas futuras deterministas: respuestas simuladas, catálogo/ledger temporales,
   transporte y procesos simulados, reloj fijado y fallos inyectados por barreras.
3. Aceptación nativa futura: permisos, identidades, procesos y aislamiento solo
   en recursos desechables y sin elevar privilegios para superar una restricción.
4. Piloto real de API: autorización separada, precio vigente, máximo mostrado,
   ledger canónico y conciliación. No está autorizado por esta fase.

No usar backtests nuevos, datasets reales, permisos históricos consumidos, SQLite
operativas o mensajes reales para probar estas interfaces.

## 2. 5.9B.1 — Investigador, primer encargo propuesto

Alcance mínimo: implementar contratos TLAgents.ResearchRequest/ResearchHypothesis,
un adaptador de contexto que use el perfil researcher real y un proveedor simulado
inyectable. Una solicitud por escenario; salidas JSON y artefactos solo de prueba.
No ampliar research_intake.Selection para que cambie silenciosamente su significado.
No migrar Store, registrar candidatas reales o añadir otros agentes.

Criterio de cierre de 5.9B.1: el catálogo temporal se consulta solo por lectura,
la entrada se valida, la salida simulada es reproducible y los errores son seguros.
Tras sembrar el fixture, comparar bytes/hashes e inventario antes y después de las
consultas; no crear journals/sidecars inesperados ni usar init, discover, register
o import-confirmed. Espías de efectos deben fallar si se intenta abrir una cola
operativa o crear candidatas, tareas o reservas reales. El proveedor simulado
funciona sin claves, sin leer .env y con transporte externo deshabilitado.
Los únicos archivos escritos son artefactos de prueba bajo raíz desechable.

| ID | Prueba futura | Aceptación |
|---|---|---|
| R01 | Contexto de catálogo temporal con estrategias y sin runs | No se inventa evidencia económica |
| R02 | EXACT_MATCH con identidad/fingerprint existente | Se cita el antecedente sin duplicar una tarea |
| R03 | RELATED_CANDIDATE por activo/timeframe | No se afirma equivalencia científica |
| R04 | Cero hipótesis defendibles | NO_HYPOTHESIS es una salida válida |
| R05 | Fuente incompleta o métricas ausentes | NEEDS_REVIEW, null/UNKNOWN conservados |
| R06 | Holdout CONSUMED | Sin nueva independencia ni promoción |
| R07 | Falsación o condiciones ausentes | Rechazo o revisión, sin rellenar automáticamente |
| R08 | Referencia inventada y campos extra | Rechazo estructural y recibo diagnóstico |
| R09 | Paper pide herramientas, claves o autorizar gasto | Ningún efecto; salida restringida |
| R10 | Misma solicitud repetida y en dos lectores | Misma evidencia de propuesta, una invocación simulada |
| R11 | Mismo ID con bytes cambiados | CONFLICT, no sobrescribir |
| R12 | Cursor inválido/invalidado y página excesiva | Error coherente; solo se reinicia lectura autorizada |
| R13 | Timeout después de reserva simulada | UNKNOWN, sin segundo envío |
| R14 | Precio caducado / ledger desconocido | Bloqueo previo a proveedor, cero llamadas |
| R15 | Contexto sobredimensionado, NaN, claves duplicadas | Rechazo antes de una llamada |
| R16 | Fuente basada en patrones descubiertos en el mismo periodo | Limitación de selección y no OOS explícitos |

Medir tamaño del paquete, tiempo local y número de invocaciones simuladas, no
inventar consumo del modelo. Guardar entradas/salidas y versiones de política.
Las consultas reales del catálogo solo se añadirían bajo alcance de lectura
explícito, sin discover/register/import ni verify --record-event.

## 3. 5.9B.2 — Diseñador

Implementar el adaptador y validadores de StrategySpecification sin lanzar Codex.
Reutilizar HypothesisManifest 1.0; no sustituir la semántica de ImplementationPlan.

| ID | Prueba futura | Aceptación |
|---|---|---|
| D01 | Señales e indicadores con límites de ventanas y shifts | Reglas inequívocas, dependencias declaradas |
| D02 | Entrada al cierre futuro / rolling centrado / HTF sin cerrar | Bloquear por incompatibilidad causal declarada |
| D03 | Unidades de fees/riesgo, costes en ambos lados | Sin confundir porcentajes y fracciones |
| D04 | Funding spot/synthetic/perpetuo y calendario | No inventar soporte del motor |
| D05 | Warmup, NaN, gaps, stop/target y sizing omitidos | NEEDS_REVIEW, no implementación |
| D06 | Holdout reutilizado o parámetros elegidos usando TEST | Mantener CONSUMED; no validación independiente |
| D07 | Dataset/runner no disponible | PENDING/UNSUPPORTED sin hashes inventados |
| D08 | Cambio de activo/parámetro frente a nueva señal | NEW_EXPERIMENT cuando sea compatible, sin clonar Python |
| D09 | specification_reviewed=true enviado por el modelo | No conceder permiso; campo de control rechazado |
| D10 | Salida truncada, UNKNOWN o repetición | Recibo incompleto/bloqueo, no auto-reparación pagada |
| D11 | Capital, fórmulas o ADVERSE cambian en el suplemento | Mapeo fiel al manifiesto y fingerprint distinto, o bloqueo de admisión; sin duplicado científico falso |
| D12 | Faltan reglas imprescindibles | NEEDS_REVIEW admite manifest/riesgo nulos y listas pendientes, sin fabricar valores ni admitir una ficha incompleta |

Son validaciones de especificación y fixtures, no prueba de causalidad del código
que todavía no existe. Prefix-invariance y fills se prueban al implementar una
estrategia autorizada por el circuito existente, no se certifican con texto.

## 4. 5.9B.3 — Validador

Implementar ValidationAssessment y proyección de contexto primario, preservando
ModelReview/AuditVerdict. No alterar el auditor determinista ni las clasificaciones.

| ID | Prueba futura | Aceptación |
|---|---|---|
| V01 | COMPLETE con NO_DECISION y pocos trades | No promoción económica |
| V02 | HASH_VERIFIED sin SOURCE_AUDITED | No elevar confianza |
| V03 | FUENTE SOURCE_AUDITED y holdout CONSUMED | Conservar significado y limitaciones |
| V04 | Comparación incompatible por periodo/coste/motor/capital | NOT_COMPARABLE con motivos, sin ganador |
| V05 | Capital RESET_PER_SEGMENT y BASE/ADVERSE | No sumar como cartera o muestras independientes |
| V06 | Sharpe, PF o muestra null | No inventar derivados ni significación |
| V07 | Hallazgo con referencia fuera del paquete | Rechazo |
| V08 | demo_authorized=true o cambio de verdict | Rechazo estructural |
| V09 | BLOCKED_EVIDENCE | Cero llamadas pagadas, revisión de fuente |
| V10 | Resultado correcto del modelo | Hash del veredicto determinista original intacto |
| V11 | Instrucciones maliciosas en informe de Codex/CSV | No comandos ni modificación de gates |
| V12 | Timeout/cargo incierto | Conciliación, no reenvío |

El histórico real del Issue #3 no se reimporta ni modifica para fabricar negativos.
Usar un expediente artificial con métricas y costes explícitamente sintéticos.

## 5. 5.9B.4 — Coordinador y transferencias

Extender el coordinador existente tras revisión del diseño de persistencia
preadmisión y perfiles. Si se aprueba una migración, primero sobre copias/fixtures;
la base real necesitará autorización independiente. No ampliar CircuitRequest
técnico mediante modificación de sus identidades congeladas.

| ID | Prueba futura | Aceptación |
|---|---|---|
| C01 | Handoff Investigador→Diseñador→revisión | Hashes y lineage exactos, sin saltar aprobación |
| C02 | Dos solicitudes concurrentes iguales | Una operación/recibo/reserva por clave |
| C03 | Interrupción antes de efecto, después de reserva y después de respuesta | Distinguir nuevo, completo e incierto; no repetir |
| C04 | Simulación de cierre durante commit local | Recuperación con recibo válido o UNKNOWN, nunca COMPLETE parcial |
| C05 | Cargos pendientes, mes nuevo y saldo desconocido | Bloqueo global preservado |
| C06 | Ledger alternativo o purpose manipulado | Rechazo en la frontera confiable |
| C07 | Límite mensual, por investigación y total de llamadas | Sin nueva asignación por rol/revisión/reinicio |
| C08 | Modelo asesor propone RUN/SEND/GRANT | Rechazo; solo recomendación consultiva |
| C09 | Codex simulado, segundo intento y presupuesto 1+2 | No nuevo presupuesto; entrega/checks recibidos por el host |
| C10 | Ejecución simulada UNKNOWN o sello ausente | Detener, conservar y conciliar |
| C11 | Outbox DRAFT/NOTICE_PREPARED | Ningún envío |
| C12 | SENDING/UNKNOWN, reinicio y repetición de trigger | No duplicar aviso ni cambiar destinatario |
| C13 | Baseline/cargo atribuible y conciliación repetida | SETTLED una vez, sin relanzar el proveedor |
| C14 | Cambios entre páginas/etapas y fuente revisada | Invalidación de lectura o revisión nueva, no mezcla silenciosa |
| C15 | Rutas, enlaces y límites del contexto | Fail-closed, sin lectura privada o efectos externos |
| C16 | Cierre de expediente desde estado no permitido | No forzar transición a ARCHIVED/CLOSED |
| C17 | Contexto compuesto con checkpoints diferentes | Recapturar solo lectura con límite; bloquear si no hay coherencia y nunca repetir una operación reservada |

No invocar Codex real anidado en pruebas: usar el ejecutable simulado del patrón
existente. Los procesos desechables no heredan credenciales de proveedor o trading.
Las pruebas nativas omitidas siguen identificadas y no se fuerzan con elevación.

## 6. Piloto real posterior, sujeto a otra autorización

Precondiciones mínimas: revisión de código/contratos, pruebas simuladas completas,
controles nativos pertinentes, perfil de precios vigente, ledger canónico y saldo
conciliado, ámbito de factura atribuible y permiso explícito del operador.

Propuesta de piloto: una única solicitud del Investigador con contexto saneado,
una llamada y límite exacto revisado. Sin Codex, backtest, importación o Telegram.
Al terminar: conservar raw response/usage en dossier privado, validar salida y
conciliar el cargo. Si falta recibo o cargo, detenerse sin repetir. Los siguientes
agentes requerirán decisiones de activación independientes.

La fecha PRICE_EXPIRES de la base está vencida: el piloto no está listo para una
llamada real hasta resolverlo por revisión, sin tocarlo en esta entrega documental.
No es necesario desbloquearlo para implementar y probar 5.9B.1 con simulaciones.
La disponibilidad del modelo, las credenciales y el ámbito de facturación también
deben verificarse antes de autorizar el piloto; una simulación no los acredita.

## 7. Qué medir y cómo reportar

Separar pruebas ejecutadas, aprobadas, fallidas, omitidas y controles por inspección.
No contar un caso repetido como prueba distinta. Reportar tokens solo si se midieron;
estimación de precio, reserva y factura conciliada son columnas diferentes.
Registrar número de propuestas, descartes justificados, errores de contrato,
recuperaciones, lecturas y efectos externos evitados, sin ranking de rentabilidad.

Rendimiento: paquetes acotados, páginas y lecturas concurrentes en catálogos de
prueba. No generar miles de backtests para medir una interfaz. El benchmark 5.9A
es antecedente de su API, no medición de los agentes que aún no existen.

## 8. Decisiones abiertas, dueño y gate

El orden de integración es Flujo 1 hasta Telegram con controles y envío autorizado,
y después Flujo 2 de extremo a extremo. El diseño compartido no adelanta 6.0B ni
convierte el plan de notificación en permiso de envío real durante estas pruebas.

| ID | Decisión o trabajo pendiente | Dueño / antes de |
|---|---|---|
| P01 | Aprobación de este diseño y de los cuatro prompts | Operador/revisor, antes de 5.9B.1 |
| P02 | Contratos TLAgents y broker simulado | Desarrollo 5.9B.1–3, sin efectos reales |
| P03 | Persistencia preadmisión aditiva en el Store existente | Revisión 5.9B.4, antes de producción |
| P04 | Revisión de precios/contextos y perfiles permitidos | Operador y revisión técnica, antes de cualquier llamada real |
| P05 | Atribución de factura para Diseñador y asesor | Revisión billing en 5.9B.4, antes de sus llamadas |
| P06 | Canal/identidad del trigger 09:00 y publicación | Fase posterior autorizada, no asumir integración ChatGPT/GitHub |
| P07 | Cobertura y estadísticas de Flujo 2 | 6.0B, sin modificar motor |
| P08 | Modelos de amenaza más exigentes y ensayos reales de enlaces | Revisión de seguridad posterior |
| P09 | Frecuencia sostenible 2–3 propuestas/día | Operador tras datos reales de calidad/coste, no promesa actual |
| P10 | Tipos de aviso general y registro científico revisado | Adaptación futura de outbox/catálogo, sin autoingesta o permisos |

## 9. Cierre de diseño y siguiente encargo concreto

5.9B.0 se cierra con documentos enlazados, contratos y ejemplos revisados, inventario
y comprobación de que ningún archivo ejecutable o base cambió. La revisión de fuentes
no sustituye una auditoría de procesos o servicios operativos actuales.

Siguiente encargo propuesto: implementar SOLO 5.9B.1 en rama local, con dos contratos
TLAgents, contexto CatalogReader.researcher, proveedor simulado y pruebas R01–R16.
Conservar el patrón de contabilidad y scopes como dependencias simuladas; no cambiar
precios, ledger real, HypothesisManifest o el intake antiguo. Detenerse antes de
llamadas reales, registro operativo, commit, push o activación del Diseñador.
