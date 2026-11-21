# Política de tokens y presupuesto multiagente — V1

Diseño, no concesión de gasto. Ledger existente y canónico; ningún asiento,
apertura mensual, permiso o llamada se crea durante 5.9B.0.

## 1. Fuente contable y alcance

Se reutilizan Budget/ExistingBudgetStore de audit_model.py, tablas api_months y
api_calls del ledger global ya existente, billing.reconcile y billing_snapshots.
MONTHLY_CAP_CENTS es 2000: **20 EUR por mes UTC para el conjunto del proyecto**.
No son 20 EUR por agente, ni un presupuesto adicional sobre gastos anteriores.

La cola operativa, el catálogo científico y el ledger global conservan sus
identidades separadas. La configuración confiable del host selecciona un único
ledger; el modelo no aporta rutas alternativas. Budget acepta un Store como
dependencia: la garantía de utilizar el canónico debe imponerse en la frontera,
no se deduce del nombre de la clase ni de un prompt.
La CLI existente contrasta el destino con TRADING_LAB_GLOBAL_API_DB; el futuro
broker reutilizará esa misma configuración confiable, sin aceptar del modelo
otro --db, --budget-db o valor de entorno. No se leen claves o .env en este diseño.

No se duplica contabilidad en el catálogo, en una nueva base por agente o en un
CSV de saldo. Las referencias por investigación son una vista del mismo ledger,
no otro total financiero. Codex conserva sus intentos y unidades/cuota observada
por separado; no convertir tokens de Codex en EUR ni atribuirlos a la API sin
evidencia de facturación y configuración que lo justifique.

## 2. Comportamiento real ya implementado

| Componente | Garantía observada en código |
|---|---|
| Budget._available | Exige apertura mensual conocida; cualquier RESERVED/UNKNOWN del ledger bloquea nuevas llamadas, incluso si es anterior al mes actual |
| Budget.reserve | Reserva transaccional antes del efecto, máximo positivo y saldo suficiente; once=True impide otra reserva con el mismo purpose |
| Budget.settle | UNKNOWN cuando no hay cargo medido; SETTLED solo con cantidad y procedencia válidas |
| audit_openai.supplement | Una petición explícita, evidencia determinista previa, baseline de facturación, reserva once=True y recibo |
| research_intake.ingest | Reutiliza el purpose de la fuente/recibo y no repite un resultado incierto |
| billing.reconcile | Evidencia Usage/Costs o CSV atribuible, comparación con baseline y revisión conservadora; no basta el coste calculado por tokens |
| flow1.billing_cycle | WAITING_BILLING, WAITING_GLOBAL_LEDGER, READY_FOR_AUDITOR_PREFLIGHT o recuperación del DRAFT, según hechos |

Los costes calculados son estimaciones, no gasto facturado conciliado. Una respuesta
recibida o inválida puede estar cobrada. Un timeout no permite liberar la reserva
como cero ni volver a llamar para averiguar qué ocurrió.

## 3. Estado de perfiles en la base inspeccionada

No se consultaron tarifas externas ni se asignan precios nuevos en este diseño.
Se describen configuraciones del código, no una oferta comercial vigente:

- audit_openai.DEFAULT_MODEL: gpt-6.1-sol; INPUT_CAP 1.050.000, OUTPUT_CAP 1200.
- research_intake: perfiles standard y reduced; reduced identifica
  gpt-4o-mini-2024-07-18, con techo de entrada 128.000 y salida 1200.
- La salida standard del investigador tiene un límite propio de 2400.
- PRICE_REVIEWED=2026-11-05 y PRICE_EXPIRES=2026-11-12 en audit_openai.
  quote comprueba esa vigencia; pricing_profile del investigador también llama a quote.

Al 2026-11-21, esos perfiles no acreditan una tarifa vigente. **Toda futura llamada
real permanece bloqueada** hasta revisión/autorización de precios y controles
correspondientes. No se cambia la fecha para superar el bloqueo. No se presume
que los modelos del entorno Codex sean modelos API autorizados para Trading Lab.

Diseñador y asesor del Coordinador no tienen hoy adaptadores de proveedor propios.
Su elección requerirá configuración revisada, límites conservadores y adaptación
de recibos/atribución dentro del mismo ledger. Los parsers de billing reconocen
ámbitos/perfiles concretos; un purpose nuevo no se considera conciliable por defecto.

## 4. Techos propuestos para un piloto futuro

Valores de política para revisión, no tarifas ni prueba de capacidad económica.
Si el quote revisado no cabe, se bloquea o se reduce contexto mediante un perfil
admitido; nunca se minora una reserva por estimación optimista.

| Concepto | Propuesta inicial |
|---|---|
| Tope global | 2000 céntimos/mes UTC, inalterado |
| Margen preventivo | Detener admisiones ordinarias al comprometer 1600 céntimos; preservar 400 para incidencias autorizadas |
| Por investigación | Máximo de reservas acumuladas 15 céntimos, todos los roles incluidos; gasto previo y revisiones vinculados |
| Por llamada | Quote garantizado ≤5 céntimos y reserva exacta del quote revisado |
| Investigador | Una llamada, máximo 1200 tokens de salida |
| Diseñador | Una llamada, máximo 2400 tokens si un perfil revisado lo permite |
| Validador | Cero o una llamada, máximo 1200 tokens |
| Coordinador asesor | Cero por defecto; excepcionalmente una plaza no usada del total de tres, máximo 600 tokens |
| Total por investigación | Hasta tres llamadas pagadas, incluidas reparaciones autorizadas; no una cuarta llamada automática |
| Entrada propuesta nueva | Hasta 16.000 tokens incluyendo instrucciones/schema/contexto, si puede acotarse de forma verificable |
| Paquete de contexto | Hasta 64 KiB UTF-8, más límites específicos de fuente y perfil; no garantiza por sí solo el techo de tokens |
| Reintentos de proveedor | Cero automáticos. Una revisión explícita máxima solo tras resultado conocido y conciliado, dentro de llamadas/coste originales |

Los límites existentes de quote no se reducen por poner esos números en un prompt.
Antes de activar un perfil compacto habrá que demostrar la cota real de entrada,
framing/schema y salida (incluidos tokens internos facturables si corresponden),
o reservar el máximo existente y bloquear si excede el techo del piloto.
Un documento o respuesta demasiado grande no se trunca como resultado completo.

La contabilización por investigación es un guard adicional sobre los call_id del
ledger existente. Requiere desarrollo y pruebas; no está implementada por esta fase.
No resetea el gasto al cambiar hypothesis_id, candidato, revisión o mes local.

## 5. Objetivo 2–3 propuestas diarias

No es una obligación de producir ideas ni una garantía de capacidad API.
Con 30 días y 15 céntimos máximos por investigación:

| Objetivo hipotético | Carga máxima de ese subconjunto | Límite |
|---|---|---|
| 2/día, 60 investigaciones | 9 EUR | No incluye gasto ya existente u otros usos del mismo ledger |
| 3/día, 90 investigaciones | 13,50 EUR | No demuestra que un perfil vigente quepa en 5 céntimos |

Estos cálculos son aritmética de techos, no estimaciones de tarifas verificadas.
Se inicia con una solicitud simulada y, solo si se autoriza después, un piloto
real acotado. La admisión diaria dependerá de coste real conciliado, cuotas,
calidad de propuestas y capacidad de verificación. Puede haber cero propuestas.

## 6. Protocolo de cada llamada futura

1. Comprobar autorización API externa, perfil/versión/tarifa vigentes y ledger canónico.
2. Construir paquete inmutable mínimo, identificar actor/rol y su scope; no adjuntar velas completas.
3. Vincular operation_key al request_id, rol, revisión de entrada, fuentes,
   fingerprint/checkpoint pertinente, instrucciones y perfil. Los cambios son
   revisión nueva con historial común; nunca otra identidad para ocultar gasto.
4. Buscar call_id previo. Si hay recibo válido, recuperar; si hay reserva o estado
   incierto, conciliar sin repetir. Cada stage receipt conserva el purpose y call_id.
5. Verificar presupuesto mensual y por investigación; capturar baseline atribuible.
6. Reservar el quote exacto con once=True antes de contactar al proveedor.
7. Persistir intención y hacer una única petición por el adaptador revisado, sin tools.
8. Registrar respuesta, usage, estado de validación, hashes y outcome real.
9. Mantener UNKNOWN/CALCULATED_PENDING_RECONCILIATION hasta evidencia independiente.
10. billing.reconcile atribuye el cargo y lleva el asiento a SETTLED. Solo entonces
    la siguiente llamada puede superar el bloqueo global, si aún tiene permiso/saldo.

No hay paralelismo de llamadas pagadas bajo el comportamiento conservador actual.
Los lectores del catálogo pueden ser concurrentes; eso no autoriza concurrencia API.

La clave de admisión se resuelve ANTES de consultar de nuevo el catálogo o cambiar
de perfil. En el primer intento se congelan contexto, checkpoint, instrucciones y
configuración; los reintentos de la misma admisión recuperan ese paquete y su
operation_key. Un checkpoint posterior no permite crear otra llamada para la misma
solicitud. Actualizar contexto o modelo requiere una revisión explícita vinculada,
que conserva el gasto y los intentos anteriores.

## 7. Errores, prioridad y recuperación

| Situación | Actuación |
|---|---|
| Mes sin apertura conocida | Bloquear; revisión del saldo global, sin crear apertura automática |
| Precio vencido o no verificable | Bloquear modelo, no actualizar fechas por código |
| Provider timeout o recibo ausente | UNKNOWN/RESERVED, preservar, no reintentar |
| Respuesta inválida pero cargo conocido | Registrar fallo y conciliar; revisión pagada solo con autorización separada |
| Cost/Usage ajenos o no atribuibles | Mantener reserva y bloqueo; no prorratear arbitrariamente |
| Token/salida excedidos | Resultado incompleto; no ampliar límites silenciosamente |
| Coste mayor al máximo garantizado | Bloquear integración y revisión del proveedor; no ocultar exceso |
| Límite mensual o soft limit | Pausar admisión; revisión humana, no segundo ledger |

Prioridad: conciliación y recuperación determinista, después cierre de trabajo ya
admitido y, por último, nueva investigación. El asesor IA nunca recibe una plaza
extra para explicar por qué se agotó el presupuesto. El margen de 400 céntimos
también requiere autorización y no sube el hard cap de 2000.

## 8. Pruebas y condiciones de activación

Simular reserva concurrente, duplicado once, rollover mensual con pendiente,
timeout, cargo cero acreditado, coste desconocido, respuesta inválida, reconciliación
idempotente y perfil vencido. Verificar que todos usan la misma base canónica.
No llamar aquí a open_month, reserve, settle o reconcile sobre datos reales.

Un piloto real posterior exigirá autorización independiente, precios revisados,
scope de facturación verificable y techo exacto mostrado al operador. No se
garantiza que el saldo mencionado en documentos históricos siga disponible hoy.

Gate previo obligatorio a cualquier llamada real: verificar disponibilidad y
compatibilidad del modelo elegido, tarifas actuales y fecha de revisión, reservas
máximas calculadas con contexto/salida completos, credenciales del operador y su
ámbito de facturación, saldo conciliado y autorización explícita del alcance.
No validar credenciales mediante una llamada pagada implícita. No copiar claves,
proyectos o cuentas privadas al contexto del agente o al repositorio.
Las simulaciones deben arrancar sin claves OpenAI y sin leer .env: proveedor falso
inyectado explícitamente, sin fallback a un adaptador real ni a precios caducados.
