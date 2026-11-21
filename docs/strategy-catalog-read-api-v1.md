# API Python de lectura del catálogo V1 — Fase 5.9A

Implementación local aditiva dentro de trading_lab_catalog. No es un servidor,
agente, scheduler o motor de ejecución. Funciona sin red ni dependencias nuevas.
Estado: API V1 implementada y publicada en el
[PR #8](https://github.com/jogutierrez99/trading-lab/pull/8).
La auditoría técnica local ha concluido. Según el dictamen comunicado por el
operador, la revisión independiente es favorable con observaciones para Windows
NTFS confiable. La integración en main y el merge siguen pendientes de
autorización expresa. No se han registrado resultados CI remotos satisfactorios.

Los agentes y los flujos 1 y 2 siguen desconectados de esta API. No se ha activado
el trigger de las 09:00 desde esta capa. No hay consumo operativo de OpenAI API
ni autorización para trading.

## Arquitectura

- read_api.py: CatalogReader y perfiles deterministas.
- read_models.py: filtros Pydantic estrictos, Page, errores y proyección pública.
- read_queries.py: una transacción de lectura, selección acotada,
  validación de modelos/huellas/relaciones y proyección de eventos.
- pagination.py: cursores HMAC autenticados, sin archivos de estado.
- local_evidence.py: referencias locales para un operador de confianza,
  separadas de las respuestas destinadas a agentes.
- read_paths.py: anclaje de lectura a objetos NTFS y sus ascendentes.
  Reutiliza primitivas del sistema operativo existentes, sin modificar el
  coordinador ni ejecutar sus operaciones. Es el archivo número 13 del alcance
  final; los 12 archivos originales no incluían esta corrección de seguridad.

Se reutilizan Store.connection, Store.records, los modelos científicos,
la verificación SQLite y service.joined_cases/comparison.compare.
El único cambio en Store es el argumento opcional ids de records, con un máximo
de 200 identidades preparadas y proyección de eventos para esas huellas.
La llamada existente sin ids mantiene su contrato. No cambian ingesta,
acreditación, tablas, triggers, Bundle 1.0, CLI o motores.

CatalogReader no hereda Store ni expone SQL, conexión, ejecución, inicialización,
migración, registro, ingesta o modificación de decisiones.

## Contratos públicos

```python
from trading_lab_catalog.read_api import CatalogReader
from trading_lab_catalog.store import default_path

reader = CatalogReader(default_path())
response = reader.list_strategies(page_size=50)
if response["status"] != "OK":
    raise RuntimeError(response["status"])
```

La ruta es configuración del operador. En entornos con LOCALAPPDATA redirigido
debe resolverse la ubicación real autorizada antes de construir el lector.
La API no busca ni inicializa una base alternativa.

| Método | Datos |
|---|---|
| get_catalog_status(verify=False) | Conteos y verificación SQLite/huellas opcional |
| list_strategies(filters=None, ...) | Estrategias y resúmenes de investigación registrada |
| get_strategy(strategy_id) | Resumen de una estrategia existente |
| list_versions(strategy_id, ...) | Versiones sin fusionarlas |
| search_experiments(filters=None, ...) | Definiciones, incluso sin runs |
| list_runs(experiment_id, status=None, ...) | Ejecuciones de un experimento |
| get_run_details(run_id) | Estrategia, versión, experimento, run, casos, artefactos y decisiones |
| list_case_results(run_id, filters=None, ...) | Casos y contexto de comparación |
| get_evidence_summary(run_id) | Estados efectivos, hashes y procedencia, sin rutas |
| get_research_decisions(strategy_id, category=None, ...) | Decisiones por categoría |
| compare_results(case_ids) | Comparación de IDs existentes, sin filas del consumidor |
| find_existing_research(criteria=None, ...) | Coincidencias exactas o parciales explícitas |
| for_profile(name) | Lista blanca de métodos de consulta |

Las consultas de listas admiten page_size, cursor y sort.
Las respuestas son diccionarios JSON serializables. Los null permanecen null.

Respuesta OK: api_version=1.0, status, schema, checkpoint, query_id, integrity,
items, count, next_cursor, redaction_policy y data_redacted.
count es el tamaño de la página, no el total de coincidencias.
get_catalog_status devuelve conteos globales por separado.
find_existing_research añade match_status.
Los errores devuelven status, reason fija sin rutas privadas, items=[],
count=0 y next_cursor=null.

Errores: INVALID_QUERY, NOT_FOUND, INVALID_CURSOR, CURSOR_INVALIDATED, BLOCKED,
INTEGRITY_ERROR, QUERY_LIMIT_EXCEEDED y RESPONSE_LIMIT_EXCEEDED.
No hay reparaciones o reintentos implícitos.

## Filtros y semántica

StrategyFilters: strategy_id, family, asset y timeframe. Activo/timeframe se
refieren a experimentos registrados, no a compatibilidad supuesta de un módulo.
family busca la declaración almacenada. Esquema 1 no acredita familias:
family se devuelve null, declared_family conserva la declaración y family_status
es UNKNOWN o DECLARED_UNVERIFIED.
Cuando se filtran activo y temporalidad, ambos deben existir en el mismo
experimento. No se combinan coincidencias de investigaciones diferentes.

ExperimentFilters: strategy_id, version_id, experiment_id, asset, timeframe,
market_type, holdout, capital_policy, parameters y parameter_fingerprint.
parameters es una igualdad completa, no coincidencia semántica o subconjunto.
Su fingerprint debe coincidir si se proporcionan ambos.

CaseFilters: segment, scenario, period_start_utc, period_end_utc, asset,
timeframe, version_id, status y audit_status. Las fechas deben ser UTC y se
normalizan al formato JSON UTC. Se conservan los nombres originales,
por ejemplo base/adverse y test_retrospective.

Solo se permiten id y -id para ordenar. Los nombres SQL proceden de listas
blancas y los valores externos se pasan como parámetros preparados.
Se rechazan campos desconocidos, tipos incorrectos, filtros que no sean mappings
o contratos tipados, page_size booleano, cursores excesivos, IDs repetidos y
parámetros no finitos.
Cada llamada revalida también los contratos tipados: un diccionario interno
mutado o model_construct no puede eludir los validadores.

ResearchCriteria añade definition_fingerprint: SHA-256 canónico de la definición
experimental completa excluyendo únicamente id.
EXACT_MATCH exige una identidad existente o ese fingerprint completo.
Filtros parciales producen RELATED_CANDIDATE, que no acredita equivalencia
científica. NO_MATCH significa ausencia bajo los filtros, no hipótesis nueva
globalmente. Sin criterios suficientes devuelve UNKNOWN.
No hay similitud por texto, embedding o modelo.

Los resúmenes separan descubrimiento, experimentos, runs y resultados.
Un run acreditado no convierte toda la estrategia en económicamente validada.
economic_validation y autorización efectiva se mantienen NOT_ASSESSED.
Los dictámenes registrados se devuelven por separado.

## Confianza y evidencias

La clasificación efectiva procede de Store.records y joined_cases, no de una
afirmación manual. Los eventos se proyectan dentro de la misma transacción y
se vinculan al fingerprint completo del registro.

HASH_VERIFIED conserva integridad acreditada. SOURCE_AUDITED conserva auditoría
declarada en una fuente sellada validada. Ninguno modifica NO_DECISION.
get_evidence_summary no abre ni vuelve a auditar archivos. verification_scope
indica que se consultaron acreditaciones persistidas. No implica una nueva
auditoría económica independiente o autorización de trading.

Por defecto se omiten reference, evidence_reference, source y metadata.
Se redactan campos sensibles reconocidos, rutas absolutas, credenciales
reconocibles e identificadores privados. data_redacted advierte que la
proyección no es una copia íntegra del contrato original.
Se inspeccionan también las claves de diccionarios para evitar exponer rutas
privadas usadas como nombres de parámetros.
No es posible identificar todo secreto arbitrario oculto en texto libre no
marcado. La API no autoriza enviar contenido automáticamente a un modelo.

Un operador puede usar explícitamente LocalEvidenceReferences(path).for_run(id)
para obtener locators almacenados. Esa clase separada no está en los perfiles
y tampoco abre los archivos referenciados. No devuelve su contenido.
Una verificación local posterior necesita su propio alcance autorizado.

## Paginación y concurrencia

Page: 50 elementos por defecto, máximo 200. Cursor HMAC-SHA256 ligado a operación,
filtros normalizados, tamaño, orden, último ID y checkpoint.
La manipulación o reutilización con otra consulta se rechaza.
Se exige codificación base64url canónica sin padding. La autenticación del
cursor no autentica al usuario ni establece permisos de acceso.
El contenido del token no está cifrado. Si el último ID contiene una ruta o
valor sensible reconocido, la página devuelve BLOCKED en lugar de incluirlo
codificado dentro del cursor. No se elude la redacción mediante base64.

La clave se genera en memoria por instancia. Los elementos, orden, query_id y
checkpoint son deterministas con los mismos datos. El token depende también
de la instancia y es estable dentro de ella. Un operador puede suministrar una
clave privada de al menos 32 bytes para conservar cursores entre instancias.
La clave no se incluye en las respuestas ni se persiste.

El checkpoint combina estructura, conteos, último evento e identidad de archivo.
Nuevas entidades o eventos del catálogo append-only invalidan la página siguiente.
No se mantienen instantáneas entre peticiones: debe reiniciarse la paginación
ante CURSOR_INVALIDATED. No cubre a un atacante con control arbitrario del host
que reescriba base, hashes y triggers.

Cada petición abre mode=ro y query_only=ON, verifica identidad/esquema,
rechaza journals/sidecars incompatibles y usa una única transacción para el grafo.
No usa immutable=1, no cambia journal_mode ni migra.
La instantánea se cierra también ante error. Un authorizer deniega DML, DDL,
ATTACH y PRAGMA de escritura.

En Windows se exige un volumen local fijo NTFS. Durante toda la transacción se
mantienen abiertos el archivo y todos los directorios ascendentes con
FILE_OPEN, acceso de lectura y sin compartir borrado. NtCreateFile con
OBJ_DONT_REPARSE rechaza atravesar reparse points; la identidad incorpora volumen
e índice del archivo. El archivo debe ser ordinario y tener un único enlace.
Se reutiliza study_storage_windows sin invocar creación, publicación ni limpieza.
No se modifica ninguna ACL. Esto no sustituye una política de acceso del operador.

Las pruebas nativas sin administrador comprobaron aperturas de lectura, ausencia
de sidecars y bloqueo del renombrado del archivo y de su directorio. La sesión
gestionada que no acredita un volumen fijo NTFS devuelve BLOCKED; no existe un
fallback permisivo. La rama POSIX conserva las guardas existentes y rechaza
enlaces duros, pero no acredita la misma protección de ascendentes frente a un
proceso host que pueda sustituir directorios concurrentemente.

En journal DELETE el lector puede retrasar el COMMIT de un escritor temporal.
No se elude ese bloqueo. Las consultas V1 de varias conexiones permanecen intactas.

## Límites

- Respuesta pública: 512 KiB por defecto, configurable entre 1 KiB y 2 MiB.
- Página y comparación: máximo 200 identidades.
- Grafo compuesto: máximo 200 registros por relación. Para conjuntos mayores,
  usar consultas paginadas. No se presenta un grafo truncado como completo.
- Registro capturado: máximo 1 MiB; grupo cargado: máximo 4 MiB.
- Presupuesto SQL/búsqueda: 5 segundos por defecto, máximo 30, con progress handler
  y comprobaciones del bucle. No es un límite duro de proceso.
- Se conserva el busy timeout inicial de 10 segundos del Store; una espera
  inicial puede superar el presupuesto posterior de consulta.

Las selecciones usan LIMIT y avance por ID. No cargan todos los experimentos
en Python para producir una página.
Los filtros JSON y el fingerprint completo pueden recorrer filas en SQLite.
No se añadieron índices o migraciones. Su ampliación necesitará revisión,
esquema explícito y autorización posterior.

## Ejemplos de los cuatro perfiles

Son consultas deterministas, no ejecuciones de agentes IA.

```python
pilot = "btc_spot_sma50_sma200_1h_pilot_v1"

# 01: investigación registrada en BTC 1h.
researcher = reader.for_profile("researcher")
strategies = researcher.query(
    "list_strategies", filters={"asset": "BTCUSDT", "timeframe": "1h"}
)

# 02: versiones y parámetros ya ensayados.
designer = reader.for_profile("designer")
versions = designer.query("list_versions", strategy_id=pilot)
experiments = designer.query("search_experiments", filters={"strategy_id": pilot})
assert experiments["status"] == "OK"
experiment_id = experiments["items"][0]["id"]

# 03: lectura de ejecución y evidencia, sin nueva auditoría.
auditor = reader.for_profile("auditor")
runs = auditor.query("list_runs", experiment_id=experiment_id)
assert runs["status"] == "OK"
run_id = runs["items"][0]["id"]
evidence = auditor.query("get_evidence_summary", run_id=run_id)
cases = auditor.query("list_case_results", run_id=run_id)
comparison = auditor.query(
    "compare_results",
    case_ids=[c["id"] for c in cases["items"] if c["segment"] == "train"],
)

# 04: identidad y decisiones, sin reservas o ejecuciones.
coordinator = reader.for_profile("coordinator")
existing = coordinator.query(
    "find_existing_research", criteria={"experiment_id": experiment_id}
)
decisions = coordinator.query(
    "get_research_decisions", strategy_id=pilot, category="ECONOMIC"
)
```

Los consumidores deben comprobar status y seguir next_cursor.
Una versión sin experimentos o un experimento sin runs no es un permiso
de ejecución ni una decisión de rechazo. No hay cola autónoma o prompts.

## Pruebas y aceptación

Pruebas nuevas en tests/catalog_api: filtros, contratos JSON, null,
paginación, MAC, invalidación por ingesta/eventos, estados efectivos, privacidad,
límites, cierre de conexiones, referencias huérfanas, corrupción,
lectores paralelos y escritor en SQLite temporal.

63 pruebas nuevas aprobadas y una omitida. Las 38 regresiones V1 pasaron:
101 pruebas distintas aprobadas, una omitida, descontando repeticiones del benchmark.
La prueba omitida es el symlink real: winerror 1314, privilegio requerido.
No se solicitó elevación. No se certifica esa prueba como superada.

El cierre de auditoría posterior ejecutó 126 casos distintos: 84 pruebas de la
API y 38 regresiones V1 aprobadas, más cuatro omisiones. Las omisiones son el
symlink real (winerror 1314), dos casos que necesitan junctions y uno de enlace
duro. La creación de estos últimos enlaces fue denegada en la sesión gestionada;
el intento de sustitución no alcanzó su intercalación y quedó inconcluso.
No se presenta ese intento como explotación reproducida ni como prueba aprobada.
Los tres ensayos adicionales requieren TRADING_LAB_NATIVE_LINK_TESTS=1 en un
entorno que ya permita crearlos; la variable solo habilita tests y no modifica
las guardas de ejecución. No se cambiaron privilegios o políticas para forzarlos.

Se reprodujeron y repararon filtros tipados sin revalidar, claves privadas de
diccionarios, cursores no canónicos, exceso de decisiones ajenas al grafo y la
coincidencia incorrecta de activo/temporalidad entre experimentos, además de la
exposición indirecta de un ID privado dentro de un cursor no cifrado. Se reforzó
también la apertura NTFS ante la carrera identificada por inspección. Las
decisiones se seleccionan por estrategia, versión y run antes del límite.
Se preservan los tres estados del comparador, sin rankings ni promoción.

Quedan conservados los fallos iniciales: reproducciones previas a las reparaciones,
guardas que rechazan el volumen de la sesión gestionada y dos pruebas adicionales
cuyo fixture intentaba duplicar la identidad de un caso. Se corrigió el fixture
para utilizar dos runs sintéticos; no se debilitó el índice UNIQUE.

Se corrigieron durante desarrollo una definición repetida en el fixture
de rendimiento y un test de reloj demasiado pequeño para su resolución.
El test final usa reloj determinista. La deduplicación permaneció intacta.
Se ajustó también la expectativa de BLOCKED para una base desconocida.

El fallo preexistente test_implemented_discovery_is_idempotent del registro SMA
sigue separado y sin corregir. Se conserva su reproducción en la base limpia.
No se declaró verde la suite completa del laboratorio.

La aceptación real final conserva 12 consultas con los cuatro perfiles:
40 estrategias, 41 versiones, un experimento, un run, seis casos,
doce artefactos, una decisión y 19 acreditaciones.
Se conservaron NO_DECISION, CONSUMED, RESET_PER_SEGMENT y SOURCE_AUDITED.
El SHA de la SQLite real fue idéntico antes/después; 33 fuentes y 39 ACL
permanecieron intactas.

## Rendimiento observado

Un ensayo local con exactamente 10.000 definiciones sintéticas, sin backtests.
Las mediciones limitadas usan tracemalloc para asignaciones Python.
No son RSS total, benchmark universal o umbrales de aceptación.
La lectura ilimitada usa V1 sin la misma instrumentación.

| Operation | Seconds | Python peak bytes |
|---|---:|---:|
| filtered_search | 0.055629 | 61239 |
| first_page | 0.071885 | 299422 |
| versions | 0.028487 | 55256 |
| strategy_summary | 0.115824 | 53549 |
| run_details | 0.056922 | 93179 |
| case_results | 0.047022 | 76248 |
| existing_unlimited_read | 0.085649 | not measured |
| eight_queries_four_readers | 0.264048 | not measured |

Generación de las definiciones: 1.903157 s. Cifras del cierre de auditoría;
sustituyen las mediciones previas para esta versión revisada.
Primera página: 50 elementos. Ocho consultas paralelas con cuatro lectores,
sin escrituras de los lectores.
El ensayo con escritor devuelve un experimento en la instantánea y dos
después del COMMIT. Lector 0.009357 s;
escritor completo 0.164583 s.
El tiempo del escritor incluye sincronización y espera; no mide solo el lock.

El límite de escala principal es el filtrado JSON sin índices específicos
y el trabajo de conteo/checkpoint. No se cambió el esquema real.

## Preparación para 5.9B y límites restantes

Esta capa no contiene agentes reales. El código está publicado en el PR #8;
la integración en main requiere autorización posterior y expresa de merge.
La fase 5.9B no se ha iniciado.
Un encargo posterior podrá ampliar pruebas de consumidores y contratos,
conservando la separación entre dictámenes, gates y permisos.

La implementación no conecta las 09:00, flujos 1/2, Telegram, OKX o modelos.
No se modificaron integraciones o programaciones.
La configuración externa de la tarea de ChatGPT no se auditó ni alteró:
lo verificado es que no se conectó a esta API.

Riesgo residual LOW en Windows NTFS bajo el modelo de raíz confiable: la matriz
real de enlaces está incompleta, aunque se verificaron handles y bloqueo de
renombrado. La variante POSIX conserva riesgo MEDIUM si procesos no confiables
pueden sustituir ascendentes; ese despliegue requiere revisión adicional.
No se certifica autenticidad frente a control arbitrario del host, protección
frente a todas las carreras NTFS, durabilidad eléctrica o privacidad semántica
de todo texto libre. Los perfiles no son una frontera de aislamiento frente a
código Python arbitrario. Nada autoriza trading.
