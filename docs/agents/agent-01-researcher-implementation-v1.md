# Investigador Cuantitativo V1 — implementación simulada, 5.9B.1

Implementación local para revisión, sin publicación. Identidad `quant_researcher_v1`,
instrucciones `TLAgents.researcher/1.0`. Base integrada:
`1089e80a2bb62b95d8e88bb363b6c710d64f75dd`. No activa agentes con modelos reales,
flujos, API, tareas operativas, presupuesto, Telegram, Codex o backtests.

## Arquitectura y contratos

Nuevo paquete independiente `src/trading_lab_agents/`, sin dependencias adicionales:

- `models.py`: TLAgents.ResearchRequest y ResearchHypothesis 1.0, subobjetos estrictos,
  estados, límites y fingerprints namespaced. Reutiliza canonical/digest de orquestación
  y el parser de catálogo que rechaza claves duplicadas y números no finitos.
- `context.py`: fuentes sintéticas capturadas como bytes y CatalogReader.researcher.
- `provider.py`: Protocol futuro y FakeProvider explícito; sin clientes, red o claves.
- `researcher.py`: validación, captura, una propuesta simulada y recibo para revisión.
- `receipts.py`: memoización y cronología de simulación en memoria, sin SQLite ni archivos.

Se implementan solo los dos contratos de investigación del [diseño normativo](agent-contracts-v1.md).
HypothesisManifest, contratos del coordinador y catálogo no cambian. La propuesta
no es una ficha admitida y no se registra. Los campos opcionales `notes` admiten null;
los desconocidos se conservan. Extra=forbid, strict=True y sin NaN/Infinity, incluidos
desbordamientos como 1e400. IDs nuevos excluyen latest; CatalogID conserva su dominio 1–160.

El piloto admite una candidata por solicitud; el contrato permite hasta tres para
compatibilidad del diseño, pero el componente bloquea solicitudes con límite distinto
de uno. HYPOTHESIS_PROPOSED requiere condiciones y falsación; NO_HYPOTHESIS requiere
cero candidatas; NEEDS_REVIEW exige faltantes explícitos. No se rellena un manifiesto.

## Catálogo y contexto

`CatalogContext(path, fixture_root=..., limits=...)` exige ruta explícita dentro de
la raíz desechable declarada y sin segmentos de ascenso. No consulta default_path,
LOCALAPPDATA ni el catálogo real. fixture_root es configuración del llamador de confianza,
no una sandbox contra código Python con todos los permisos del operador.

Todas las consultas pasan por `CatalogReader(path).for_profile("researcher")`.
No se utiliza list_versions, list_runs, compare_results o get_evidence_summary.
El adaptador obtiene estrategias, antecedentes y decisiones; las referencias de runs
aportadas por el host o por decisiones pertinentes se resuelven con get_run_details.
No infiere IDs de runs que
el perfil no puede enumerar. Versiones/casos/artefactos referenciados necesitan su
grafo accesible; una referencia no resoluble bloquea, no se inventa.

Se preservan filtros, cursores autenticados y guardas nativas de la API. Páginas
ordenadas por ID, tamaño por defecto 20, máximo 50 en este adaptador; ocho páginas
por consulta y 80 lecturas totales por defecto (configurables hasta 20/128).
Cursor inválido bloquea; invalidación o checkpoint distinto permite solo dos
recapturas completas adicionales de lectura. Nunca se repite una llamada al proveedor.
No se mezclan snapshots. Los cursores permanecen dentro del adaptador.

El inventario general usa una proyección de descubrimiento, sin descripciones o
dictámenes económicos de estrategias ajenas al alcance. Las estrategias candidatas
por activo/timeframe se contrastan con search_experiments para el mercado exacto;
solo las pertinentes o explícitas reciben lectura completa y consulta de decisiones.
Los experimentos idénticos no se duplican al volver a encontrarlos en otra consulta.
Una decisión ligada a un run exige resolver su identidad y mercado; los runs ajenos
descubiertos por esa vía se excluyen. Una referencia explícita a otro activo, mercado
o timeframe se rechaza. Periodos o configuraciones distintos conservan sus IDs y
relación MAIN_QUERY_MATCH/RELATED_CONTEXT: no se convierten en resultados equivalentes.

CONSUMED, RESET_PER_SEGMENT y NO_DECISION se consolidan desde todas las entidades
incluidas, no solo desde find_existing_research. warning_provenance conserva código,
advertencia, entidad, campo/valor, método de origen y alcance (experimento, run,
versión, estrategia o resumen). experiment_scope conserva la pertenencia de cada
experimento. El resumen de una estrategia se mantiene separado del registro de
estrategia incluido en un grafo para no perder su procedencia al resolver un run.
Un mismo ID científico con contenido contradictorio bloquea la captura.

Entrada total saneada hasta 64 KiB UTF-8, salida JSON hasta 32 KiB. Cada fuente
capturada admite hasta 16 KiB; el total del paquete sigue limitado. Un exceso bloquea,
no se trunca. Las referencias efectivas proceden de la API. Los fingerprints de fila
no expuestos por esa API permanecen null; un hash declarado no los sustituye.

SourceDocument recibe bytes del fixture, nunca rutas o URLs que deba abrir. Se
contrasta identidad, tipo y SHA original; solo con un hash de referencia coincidente
la integridad es HASH_VERIFIED. Si falta el hash esperado se conserva UNVERIFIED;
calcular un hash no lo acredita automáticamente. No demuestra autenticidad o auditoría
económica. SOURCE_AUDITED solo se conserva desde el
catálogo acreditado; este adaptador de fuentes no sabe emitirlo ni validar nuevos sellos.
FLOW2 solo admite estadísticas sintéticas con versión, periodo, tamaño de muestra,
exclusiones y número de búsquedas coherentes. No calcula estadísticas o descarga velas.

## Proveedor y seguridad

FakeProvider acepta escenarios reproducibles: valid, none, incomplete, invented,
invalid, truncated, timeout, malicious, error, interrupted y false_oos; o bytes
artificiales explícitos para pruebas negativas. Cuenta invocaciones sin efectos externos.
El constructor del Investigador admite únicamente el FakeProvider concreto implementado,
no adaptadores reales, subclases o callables arbitrarios. El Protocol facilita una
adaptación posterior, pero habilitarla requerirá una frontera revisada y otra autorización.

El proveedor solo recibe bytes JSON saneados, instrucciones fijas y tools=[]. No recibe
objetos del catálogo, Store, conexiones, SQL, funciones, rutas locales o ledger.
Las fuentes son UNTRUSTED_DATA; nunca se interpolan en comandos o instrucciones de
sistema. Respuestas con capacidades extra se rechazan. Se contrastan identidad,
mercado, límite, fuentes, referencias completas y sus estados/checkpoints.
Las limitaciones deterministas CONSUMED, NO_DECISION, capital independiente,
selección y no OOS deben conservarse en las candidatas. Cada advertencia científica
debe citar al menos una de sus entidades de origen efectivamente presentes en el
contexto. Copiar su texto sin una referencia válida se rechaza. La consolidación y
el control de origen usan campos y relaciones estructuradas; no un filtro de palabras.
El host conserva todos los orígenes aunque el modelo cite solo un testigo por código.
Las decisiones económicas y acreditaciones del catálogo no se modifican.

La proyección de privacidad se reutiliza y bloquea texto sensible reconocido. No
detecta todo secreto semántico. El filtro conservador de afirmaciones indebidas
no demuestra veracidad de lenguaje natural ni sustituye revisión humana. La garantía
efectiva de ausencia de acciones está en la falta de capacidades de ejecución, no
en que un prompt ignore todos los ataques posibles. No ejecutamos código no confiable.

SimulationGate permite inyectar precio vencido o ledger desconocido para R14: bloquea
antes de leer contexto/invocar el fake. No acredita tarifas, saldo o permisos reales;
True no autoriza API. No se modifica la caducidad del 12/11/2026 ni se abre el ledger.

## Recibos e idempotencia

ReceiptBook se comparte explícitamente entre lectores. Un lock abarca preparación y
llamada simulada; los reintentos consultan el recibo antes de recapturar catálogo.
La admisión liga bytes exactos de solicitud, fuentes capturadas, instrucciones y límites.
Mismo ID/bytes recupera el resultado; mismo ID/bytes distintos es CONFLICT, incluso
si solo cambia whitespace JSON. Se conserva el resultado y se añade el conflicto al historial.
Un checkpoint nuevo no crea otra invocación para una admisión ya completada.

Máximo 64 admisiones en memoria por defecto, configurable hasta 256. No se expulsan
recibos para permitir repeticiones. Objetos recuperados son copias; los originales
permanecen como bytes inmutables. Se conservan solicitud/contexto/respuesta originales
y hashes SHA-256, fingerprints TLAgents, referencias, versiones y estados.
Los fingerprints finales de candidata incluyen request_id; el ID declarado por el
proveedor no constituye por sí solo una identidad científica global.

Estados del recibo: COMPLETE (validación técnica del payload, no resultado científico),
BLOCKED, UNKNOWN y CONFLICT. Timeout o interrupción mantiene incertidumbre y no reenvía.
No hay reintentos automáticos. RESERVED_SIMULATED es solo un evento de este libro
desechable; no una reserva del ledger ni del coordinador.

`book.export(request_id)` devuelve datos para que un test los conserve bajo tmp_path;
el componente no escribe archivos. **No existe recuperación entre procesos o reinicios**.
Crear otro libro permite otra simulación: no usar esta memoización como protección de
una llamada pagada. La persistencia operativa posterior corresponde al coordinador
existente y requerirá diseño/adaptación autorizados; no se construye otro sistema aquí.

## Uso Python aislado

En un test con catálogo y bytes sintéticos previamente preparados:

```python
from trading_lab_agents import CatalogContext, FakeProvider, QuantResearcher, ReceiptBook

context = CatalogContext(fixture_catalogue, fixture_root=tmp_path)
provider, book = FakeProvider(), ReceiptBook()
researcher = QuantResearcher(context, provider, book)
result = researcher.run(request_bytes, documents=synthetic_documents)
repeat = researcher.run(request_bytes, documents=synthetic_documents)
assert repeat == result
assert provider.calls == 1
receipt_data = book.export("req_01")
```

Fixtures y ejecutor aislado: `tests/researcher/conftest.py` y sus tres módulos de
pruebas. Cada catálogo se prepara antes de medir; después se comparan inventario,
hashes y ausencia de sidecars. Nunca se abren bases reales. Ejecución desde PowerShell:

```powershell
python -B -m pytest tests/researcher -q -p no:cacheprovider
python -B -m ruff check src/trading_lab_agents tests/researcher --no-cache
python -B -m ruff format --check src/trading_lab_agents tests/researcher --no-cache
git diff --check
```

En Windows, los handles NTFS requieren los permisos ordinarios de la sesión del
operador; un bloqueo del sandbox no se convierte en un pase. No se elevan privilegios
administrativos, cambian ACL o repiten los ensayos de enlaces antes omitidos.

## Aceptación y continuación

R01–R16 cubren catálogo sin runs, exactos/relacionados, salida cero, faltantes,
holdout, falsación, referencias, inyección, idempotencia/concurrencia, conflicto,
páginas/checkpoints, timeout/interrupción, gate simulado, límites y sesgo de descubrimiento.
Aceptación inicial de implementación: **100 pruebas nuevas y 122 regresiones aprobadas**;
cuatro ensayos de enlaces deseleccionados y no acreditados. Ruff y formato correctos.
Se midieron 53 invocaciones del fake en toda la batería nueva, con paquetes de
3413–12139 bytes. No son tokens ni costes de modelos. Las consultas dejan intactos
los hashes/inventarios de sus fixtures. Un primer pase detectó defectos en las pruebas
nuevas (aserciones, nombre obligatorio de SQLite e ID de parametrización demasiado
largo para Windows), corregidos antes de esta aceptación. El sandbox bloqueó una
apertura nativa; el pase final se ejecutó con el usuario ordinario, sin cambios de ACL.
La inspección final reprodujo un RecursionError con JSON muy anidado de entrada y
salida. La frontera decode ahora lo convierte en error controlado; dos regresiones
adicionales pasaron en la aceptación final. El parser del catálogo no se modificó.
Los resultados realmente ejecutados, métricas y fallos iniciales se conservan en
el informe local de esta entrega; el plan de diseño no es una prueba ejecutada.

Revisión independiente posterior: se reprodujeron siete fallos con el código previo,
incluida la pérdida de advertencias secundarias y el exceso de contexto por leer
decisiones de todo el inventario. Las correcciones son locales a contexto, validación
y citas del fake; no cambian ResearchRequest/ResearchHypothesis 1.0 ni SQLite.
Aceptación posterior: **241 pruebas aprobadas (119 del Investigador, incluidas 19
regresiones nuevas de revisión, y 122 del catálogo/API)**. Los cuatro ensayos de enlaces
siguen deseleccionados, no superados. R01–R16 se conservan.

Medición de una ejecución por configuración sobre 40 estrategias, 120 experimentos
y 80 decisiones sintéticos (cuatro estrategias pertinentes, 12 experimentos y ocho
decisiones en el alcance):

| Página | Consultas del perfil | Captura | Paquete completo | Tiempo de captura |
|---|---:|---:|---:|---:|
| 20 | 15 | 55.726 bytes | 57.739 bytes | 0,109 s |
| 5 | 23 | 56.700 bytes | 58.713 bytes | 0,155 s |

Se midieron llamadas de la API, no sentencias SQL internas. El lector existente
todavía calcula resúmenes para el inventario y puede leer decisiones internamente;
esta corrección acota las consultas explícitas y el contenido entregado, sin
modificar ni prometer una optimización del SQL interno del catálogo. Antes se bloqueó tras
27 consultas por superar 64 KiB, sin producir paquete final ni llamar al fake.
Ahora solo se consultan decisiones de cuatro estrategias. Tiempo y tamaño dependen
del contenido; estas mediciones no garantizan capacidad universal. Límites de
32 KiB, diez consultas y una página bloquean correctamente, con cero llamadas al
proveedor; 40 estrategias todas pertinentes también pueden exceder el límite y
se bloquean sin truncamiento silencioso. No se amplían los límites para ocultarlo.

Queda pendiente revisión y autorización de publicación. No comienza 5.9B.2 aquí.
Su siguiente encargo podrá implementar el Diseñador con proveedor simulado y gate
de mapeo científico, sin Codex anidado o backtests. La [hoja de ruta](../ROADMAP.md)
prioriza ambos flujos del MVP y deja biblioteca/RAG y motor para fases 7.0 y 8.0.
