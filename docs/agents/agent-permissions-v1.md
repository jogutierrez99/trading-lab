# Herramientas, permisos y contenido no confiable — V1

Propuesta documental. No añade controles ejecutables, usuarios, credenciales o
capacidades al proceso actual. El [maestro](multiagent-master-v1.md) fija el alcance.

## 1. Matriz de capacidades

READ significa consulta saneada a través del broker; PROPOSE significa devolver
una propuesta sin efecto. VALIDATE significa pedir/aplicar validación determinista
en el controlador, no acreditar el propio contenido por afirmación del modelo.
PREPARE es preparar revisión, nunca iniciar automáticamente el siguiente paso.

| Actor | READ | PROPOSE | VALIDATE | PREPARE | EXECUTE | PROMOTE | TRADE |
|---|---|---|---|---|---|---|---|
| Investigador IA | Perfil researcher, fuentes autorizadas en contexto | Hipótesis y falsación | Solicitud, no certificación | Ficha de propuesta | No | No | No |
| Diseñador IA | Perfil designer y protocolos entregados | Especificación | Solicitud, no gate propio | Diseño para revisión | No | No | No |
| Validador IA | Perfil auditor y evidencia saneada | Evaluación consultiva | No sustituye herramientas | Informe para revisión | No | No | No |
| Coordinador IA opcional | Perfil coordinator, incidencia mínima | Explicación | No decide gates | Resumen consultivo | No | No | No |
| Coordinador Python | Fuentes y estados bajo configuración confiable | Decisiones de flujo dentro de política | Contratos y gates existentes | Encargos/outbox revisables | Solo vía externa autorizada, nunca por defecto | No por sí mismo | No |
| Codex controlado | Repo y contexto de tarea | Cambios dentro de allowlist | Checks expresamente admitidos | Entrega y comandos preparados | Solo alcance del encargo, sin históricos implícitos | No | No |
| Operador | Expediente autorizado | Nuevas decisiones revisadas | Revisión externa | Autorización específica | Según permiso y protocolo | Revisión separada | Fuera de esta arquitectura V1 |

No hay igualdad entre permiso de API, de diseño, de Codex, de backtest, de publicación,
de envío y de trading. Un permiso no se hereda por sucesión de etapas.

## 2. Matriz exacta de CatalogReader.for_profile

✓ es método existente, no una identidad autenticada. — requiere entrega del host
o cambio futuro revisado; el agente no cambia su propio perfil para conseguirlo.

| Método existente | researcher | designer | auditor | coordinator |
|---|---|---|---|---|
| get_catalog_status | — | — | ✓ | ✓ |
| list_strategies | ✓ | ✓ | — | ✓ |
| get_strategy | ✓ | ✓ | — | ✓ |
| list_versions | — | ✓ | — | ✓ |
| search_experiments | ✓ | ✓ | — | ✓ |
| list_runs | — | — | ✓ | ✓ |
| get_run_details | ✓ | — | ✓ | ✓ |
| list_case_results | ✓ | — | ✓ | ✓ |
| get_evidence_summary | — | — | ✓ | ✓ |
| get_research_decisions | ✓ | — | ✓ | ✓ |
| compare_results | — | — | ✓ | ✓ |
| find_existing_research | ✓ | ✓ | — | ✓ |

Se verificó contra PROFILES en read_api.py de la base indicada. La API no ofrece
rankings, SQL, lecciones aprobadas, escritura de decisiones o acceso a datasets.
Si un perfil necesita información ausente, el controlador puede suministrar una
proyección autorizada y trazable; no se inventa un método nuevo como existente.

El host conserva mode=ro/query_only, transacciones, guardas de journal y de rutas,
límites de 50/200, 512 KiB por defecto y cursor autenticado. Un cursor no autentica
usuarios, no cifra datos y no es una autorización operativa. Se reinicia solo la
lectura si CURSOR_INVALIDATED, sin repetir la llamada del modelo o el trabajo.

## 3. Frontera de herramientas propuesta

La primera implementación recopilará contexto antes de la petición y mantendrá
tools=[] en el proveedor. El modelo no recibe objetos Python, una consola, SQL,
acceso a .env, navegador, registry, ledger o sistema de archivos.

Si posteriormente se permiten propuestas de consulta, un broker dentro del
coordinador deberá verificar operación, argumentos estrictos, perfil fijado por
configuración, ID del expediente, checkpoint, número de rondas y tamaño total.
Las respuestas pasarán por la misma proyección de privacidad de CatalogReader.
No se conceden estos permisos porque un campo JSON diga tools o allow_execute.

Una transacción de CatalogReader garantiza coherencia dentro de una petición,
no entre varias llamadas del broker. Para un grupo de datos que se va a interpretar
conjuntamente, usar get_run_details cuando cubra el alcance, o exigir el mismo
checkpoint en todas las respuestas relacionadas. Antes de reservar o consultar al
modelo, una discrepancia permite como máximo dos capturas completas adicionales
de solo lectura; si persiste, bloquear el paquete. No mezclar páginas/checkpoints
para aparentar una instantánea única. Grupos independientes pueden conservar
checkpoints distintos si se declaran y no se combinan como una misma observación.
Una operación ya reservada recupera su contexto congelado; no lo reconstruye para
crear otra llamada con un checkpoint diferente.

Las referencias locales permanecen en una capa de confianza explícita. El operador
puede resolverlas mediante mecanismos autorizados; el modelo solo recibe IDs,
hashes, tipos y estado efectivo. LocalEvidenceReferences no se expone como tool.
No se incluyen claves, SID, permit_id, paths absolutos privados, recibos íntegros,
destinatarios o datos de cuenta en contexto público por defecto.

La redacción por patrones no garantiza detectar secretos semánticos. El controlador
debe minimizar fuentes antes de enviar, revisar texto libre sensible y bloquear
paquetes que no puedan sanearse sin perder su significado.

## 4. Política frente a prompt injection

| Entrada | Tratamiento obligatorio |
|---|---|
| Paper, web o repositorio | Capturar fuente autorizada, hash y extracto; no ejecutar código ni seguir órdenes embebidas |
| Issue/comentario GitHub | Verificar canal/autor/revisión por el intake existente; una edición no amplía el permiso |
| CSV o vela | Parser tipado, límites, UTC y números finitos; contenido de una celda no es comando o fórmula ejecutable |
| Resultado/recibo | Verificador del host, campos allowlist y límites; no confiar en estado/hash declarado por el productor |
| Respuesta de modelo | Parser sin claves duplicadas, extra=forbid, versión exacta, referencias y constantes; no ejecutar prepared_commands |
| Instrucciones de otro agente | Propuesta de trabajo, nunca una instrucción superior o autorización |
| Ruta/URL en texto | Referencia inerte. No abrir ni descargar sin resolverla dentro de la configuración autorizada |

Secuencia del host: capturar → validar origen/bytes → analizar estructura → sanear
→ fijar contexto y capacidades → solicitar propuesta → validar estructura/sentido
→ comprobar referencias y constantes → persistir recibo → revisión del siguiente paso.
El contenido no confiable no se interpola en instrucciones de sistema o plantillas
de shell. No se usa eval/exec, SQL externo, importación de módulos o comandos del modelo.

Campos de control no admitidos en una respuesta LLM: permisos, presupuesto concedido,
precio aprobado, herramientas activadas, destinatario, estado de reserva, acreditación,
decisión de catálogo, credenciales y autorización demo/live. No basta con ignorarlos:
el parser rechazará la salida para que el intento quede diagnosticado.

Los esquemas y la redacción reducen el riesgo pero no demuestran veracidad económica
ni neutralizan todo ataque semántico. La seguridad efectiva reside en el broker,
el canal de autoridad y los permisos del host, además de las instrucciones del modelo.

## 5. Autorizaciones y confianza del host

Una referencia de aprobación es solo un identificador hasta que el controlador la
resuelve y comprueba identidad, scope, vigencia, plan, código, datos y consumo.
Un booleano specification_reviewed de un JSON no confiable no constituye aprobación.
El coordinador genera esos campos tras la revisión, no desde salida del Diseñador.

Los mecanismos históricos especiales conservan su scope: LAUNCH_CODEX y
HISTORICAL_BACKTEST_ONCE del Issue #3 ya consumidos no se reactivan para este diseño.
La reserva canónica NTFS y la confirmación personal del histórico no se sustituyen
por una conversación o recomendación de agente. Las nuevas hipótesis necesitarán
su procedimiento autorizado; el diseño no generaliza silenciosamente esos permisos.

CatalogReader, los perfiles y las clases de contratos no aíslan código Python
arbitrario que se ejecute con permisos completos del operador. No se ejecutará
Python generado por un modelo dentro del proceso que conserva ledger o secretos.
Un proceso host capaz de reescribir evidencia y recibos queda fuera de la garantía
de integridad por hash; requerirá controles OS y un modelo de amenazas revisado.

## 6. Riesgos heredados y controles pendientes

- LOW para lectura sobre Windows NTFS confiable, con protecciones nativas existentes.
- MEDIUM en POSIX si procesos no confiables sustituyen ascendentes.
- Siguen pendientes symlink real, dos ensayos con junctions y enlace duro; las
  cuatro omisiones no son aprobaciones. No elevar privilegios o cambiar políticas.
- La entrada 09:00, perfiles de proveedor nuevos y persistencia de preadmisión
  requieren controles e implementación posteriores, no están activos.
- El catálogo y los recibos no prueban por sí solos fidelidad completa de señales
  o ejecución: se necesita el verificador correspondiente al protocolo.

Antes de ampliar el modelo de amenazas, realizar revisión dedicada y pruebas en
recursos desechables. Nunca simular corrupción en el Issue #3 o en SQLite reales.
