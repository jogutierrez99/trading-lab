# Paso 4.4: auditoría, informe y Telegram manual

2026-11-04. Recorrido determinista implementado y probado sobre artefactos reales.
Telegram simulado y [envío real autorizado aceptado](orchestration-step-4.4-telegram-acceptance.md),
message_id136,1 intento. Perfil/adaptador IA
preparado con pruebas simuladas; **IA real no desplegada ni ejecutada**.
Cierre técnico4.4 cubierto; integración IA real pendiente por separado.
Sin iniciar4.5 ni autorizar demo (paso5).

## Continuidad y decisiones

Se contrastaron encargo, arquitectura maestra y quant_auditor_v1 del ZIP con AGENTS,
manuales actuales, protocolo lab, código4.1–4.3 y artefactos locales. Skills utilizadas:
validate-strategy/analyze-results; sin nuevas skills ni subagentes. El ZIP es diseño;
sus ejemplos no constituyen resultados. Las afirmaciones del encargo se verificaron.

Piloto [corregido1.0.1](pilot-native-index-repair-applied.md): implementación
`repair_9dd2e6ba361d4de5baf13db554ed81fd`, UTC/DatetimeIndex1h/warmup100.
Se verificaron pruebas/sonda archivadas, archivos finales, reparación semántica manual,
enmienda de versión y cadena a la entrega anterior con reparación manual de formato.
Autoría real conservada; no se atribuyeron esas reparaciones al modelo.
**3/3 intentos consumidos**, sin nueva llamada Codex ni cambio de estrategia/perfil.

Run reutilizado `20261104T005019Z-7428e718b634`, ejecución
`execution_0e7131ba2d0344aeb6918648fda75af0`, experimento
`orchestration_technical_smoke`:3/3 completos,0 fallidos,0 trades por periodo,
3 filtros nativos FAIL,0 supervivientes; PF/Sharpe null. Sus periodos train/validation/test
son sintéticos; no se consumió TEST histórico. El holdout original sigue **CONSUMED**;
known_searches/known_variants siguen null. Sin validación económica/demo.

## Código, migración y límites

Todo se añade fuera del motor en trading_lab_orchestration:

- audit_contracts.py: AuditRequest/AuditVerdict1.0 estrictos; IDs exactos, perfil,
  versión/modo efectivo, pins de recibo/config/datasets, límites y referencias SHA256.
  El coordinador asigna audit_id y lo archiva en la solicitud final. Sin latest.
- audit_evidence.py: lectura acotada5000 archivos/64MB por defecto, rechaza links/escapes;
  controles/recibos/IDs/procedencia/finales/adaptaciones/runtime. Reutiliza verificación
  **de lectura**4.3, nunca validate/run. Ledger mode=ro/query_only, conteos, resultados,
  trades, metadata, equity; conserva CSV/JSON/null. Revalida hashes al acabar.
- audit.py: reserva transaccional/lock OS, dossier nuevo inmutable. Dedup de solicitud
  canónica; revisión distinta requiere review_revision>1 y review_reason explícito.
  Recupera PREPARED con mismo ID comparando archivos parciales; no sobrescribe diferencias.
  Auditoría bloqueada no cambia SUCCEEDED de ejecución ni relanza el runner.
- audit_model.py: perfil independiente y adaptador de evidencia primaria compacta,
  sin tools/secretos. Esquema estricto/referencias existentes, ninguna anulación de
  bloqueos/clasificaciones/permisos. Máximo una reparación de salida y sin fallback.
- audit_notifications.py: outbox del coordinador. Reutiliza NoRedirect existente;
  el cliente anterior reintentaba tras timeout, incompatible con4.4. **Watchers intactos**.
- audit_store.py: migración **v4→v5 aditiva**, audits/audit_outbox/api_months/api_calls.
  Conserva inicialización/migraciones1–4. No hay otro ledger experimental o máquina
  de estados científica, ni tablas futuras de autorizaciones/demo.
- CLI existente ampliada; ejemplo local audit_pilot.json y pruebas dirigidas nuevas.

Puertas conservadoras acreditables: A INTEGRITY_OK/FAIL, B DESIGN_LIMITED/NOT_VERIFIABLE,
C INSUFFICIENT_EVIDENCE, D NOT_READY. Esta versión solo emite **NO_DECISION** económico;
no certifica rentabilidad general ni eleva a paper por PASS. La presencia de campos o
recibos no acredita causalidad/independencia completa. Pruebas anteriores verificadas
como evidencia archivada; no se vuelven a ejecutar aquí.

Archivos existentes modificados en esta entrega: AGENTS.md, README.md,
docs/PROJECT_STATE.md, docs/ARCHITECTURE.md, docs/WORKFLOW.md,
src/trading_lab_orchestration/store.py y cli.py. Nuevos: los seis módulos audit*
anteriores, esta guía, examples/orchestration/audit_pilot.json y
tests/unit/test_audit_orchestration.py. Se conservaron cambios previos sin reset/stash.

## API: preparado y pendiente

Máximo **20EUR/mes=2000 céntimos globales**, en la misma SQLite canónica de todo el
sistema. Apertura mensual explícita con gasto acumulado real de todos los proveedores
y procedencia; nunca cero supuesto. Reserva atómica del máximo garantizado antes de
llamar; liquidación con medición/facturación independiente del modelo. Reserva≠gasto.
RESERVED/UNKNOWN sin reconciliar bloquea llamadas, incluso al cambiar mes. No crear
otra DB/mes para eludirlo. No controla facturación externa que ignore este coordinador.

Adaptador probado **solo con proveedor simulado**. Falta seleccionar/configurar un
conector real con techo garantizado por llamada y facturación verificable; por ello
**CLI MODEL_ASSISTED bloqueada**. No se seleccionó servicio de pago silenciosamente.
Las cuotas/créditos Codex no se equiparan automáticamente a gasto API. Este piloto
sintético no necesita API para establecer insuficiencia económica.

Diagnóstico sin llamadas: `python scripts/orchestrator.py --db $db api-budget`.
Solo con importes conocidos y justificantes, plantillas (no copiar con datos inventados):

```text
api-budget-open --opening-spend-cents IMPORTE_REAL --provenance REFERENCIA_FACTURACION
api-budget-reconcile call_ID --actual-cents IMPORTE_REAL --provenance REFERENCIA_FACTURACION
```

## Telegram: configuración y semántica

En la comprobación inicial no había variables Telegram exportadas en el proceso.
Posteriormente se localizaron las credenciales existentes en.env y se cargaron
selectivamente para el envío explícitamente autorizado; chat privado verificado.
La CLI no carga.env automáticamente. Para futuras órdenes configurar localmente
mediante el mecanismo de secretos habitual; **no pegar secretos en chat/Git/logs**:
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (ID positivo del chat privado propio conocido),
TRADING_LAB_TELEGRAM_VERIFIED_PRIVATE_CHAT_ID (mismo ID, tras verificar su titularidad).
No IDs de grupos ni destinatarios supuestos. No se leyó auth.json.

Contrato contrastado con documentación oficial: [getChat](https://core.telegram.org/bots/api#getchat),
[sendMessage](https://core.telegram.org/bots/api#sendmessage) y
[retry_after](https://core.telegram.org/bots/api#responseparameters).

Preview sin red/token. Envío explícito: getChat solo sobre ese ID configurado, exige
private/ID idéntico y después un sendMessage. Sin descubrimiento, botones, callbacks,
órdenes o interpretación de OK. No activar watchers ni TELEGRAM_NOTIFICATIONS_ENABLED.
La ruta local del informe es consultable en el portátil; no se publica ni se inventa URL.

Un aviso técnico por auditoría; evento constante y hash de destinatario vinculado
una sola vez al reservar: más restrictivo que varias ternas destinatario/evento/auditoría.
No permite retarget. Dossier íntegro persistido antes de encolar/enviar. Reserva
concurrente, máximo3 intentos manuales, cooldown global/retry_after; sin worker o retry automático.

| Estado | Acción/significado |
|---|---|
| DRAFT | Preparado, sin transmisión |
| SENDING | Reservado; si se interrumpe, reconciliar |
| ACCEPTED | Telegram aceptó con message_id; no acredita lectura |
| RETRYABLE | Rechazo seguro/429 o preflight fallido; retry manual tras cooldown |
| FAILED | Definitivo; investigar, no forzar reenvío |
| UNKNOWN | Timeout/5xx/respuesta ambigua tras posible envío; no blind retry |

Reconciliación UNKNOWN/SENDING: lock libre, confirmación de proceso detenido, motivo
y evidencia. accepted exige message_id verificado; not-sent requiere saber que no se
transmitió. Un timeout **no** demuestra not-sent. uncertain conserva bloqueo. No se
reinician intentos ni se promete exactly-once. Un fallo no reabre auditoría/backtest.
El transporte no expone URL/token/cuerpo/excepción remota en logs o SQLite.

## Comandos exactos para este portátil

Desde el repo con Python/instalación editable vigentes; SQLite/artefactos fuera de OneDrive:

```powershell
$db = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3'
$artifacts = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL44\audit-b7ae3f64\dossiers'
$audit = 'audit_bbac0e00b8e449d78599c5c2150430d5'
$notice = 'notice_f1cedfa29db34e7dbf35bec3ba09c4dc'

# Misma solicitud devuelve mismo expediente, sin runner nuevo.
python scripts/orchestrator.py --db $db audit examples/orchestration/audit_pilot.json --artifacts $artifacts
python scripts/orchestrator.py --db $db audit-show $audit
python scripts/orchestrator.py --db $db notify-preview $audit
python scripts/orchestrator.py --db $db notify-show $notice
python scripts/orchestrator.py --db $db api-budget
```

audit_pilot.json identifica artefactos **reales locales**, no una fixture portable.
Otro run necesita sus propios IDs/pins; no descubre latest. --artifacts separado
de repo/SQLite/fuentes/datasets/resultados. No migrar almacenamiento experimental.

**Solo con orden explícita del operador**, después de configurar/verificar su chat y revisar la preview:

```powershell
python scripts/orchestrator.py --db $db notify-send $notice
python scripts/orchestrator.py --db $db notify-show $notice
```

Este aviso ya está ACCEPTED/message_id136; no volver a enviarlo.
La ejecución autorizada usó el loader Telegram existente sobre.env y vinculó el ID
privado solo en memoria tras getChat. No se copiaron secretos a esta guía o al DB.

Si RETRYABLE y corregida su causa, tras cooldown:
`python scripts/orchestrator.py --db $db notify-send $notice --retry`.

Recuperar auditoría PREPARED:
`python scripts/orchestrator.py --db $db audit-reconcile $audit`.

Conservar incertidumbre de un envío interrumpido, sin reenviar:

```powershell
python scripts/orchestrator.py --db $db notify-reconcile $notice --outcome uncertain --confirm-stopped --reason 'Proceso terminado; sin evidencia remota de aceptación o rechazo'
```

Solo UNKNOWN/SENDING; el aviso actual ACCEPTED no necesita reconciliación.
Con aceptación probada: --outcome accepted --message-id ID_REAL; con evidencia
de no transmisión: --outcome not-sent. Registrar siempre el motivo real.
audit/reconcile devuelve2 si bloqueado; notify-send solo0 cuando ACCEPTED.
Las consultas devuelven0 aunque consulten un estado bloqueado.

## Evidencias y resultados de verificación

Auditoría **audit_bbac0e00b8e449d78599c5c2150430d5**, DETERMINISTIC_ONLY,
2210 referencias verificadas; COMPLETED_WITH_LIMITATIONS/NO_DECISION.
A INTEGRITY_OK,B DESIGN_LIMITED,C INSUFFICIENT_EVIDENCE,D NOT_READY.

Raíz local:
`C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL44\audit-b7ae3f64`.
Dossier `dossiers/audit_bbac0e00b8e449d78599c5c2150430d5`:

- audit_verdict.json SHA256 `f12c4e8a8f73e85eea73f2dfbae02daa2691b01c46db92249fde674b7f646618`.
- audit_report.md SHA256 `6d6bfe609c4e9b7ac0df47314d3af3075f809bce66fb64618b0abc92b8d49a51`.
- acceptance.json/backup orchestrator-before-4.4.sqlite3 de la entrega inicial:
  siete tablas previas idénticas; src/quant_lab/configs idénticos;0 nuevos backtests,
  0 modelos y0 envíos reales en esa fase. La prueba posterior Telegram se conserva
  en telegram-acceptance-accepted.json, sin reescribir esa evidencia inicial.

Primer ensayo sobre copia SQLite registró BLOCKED_EVIDENCE porque Git recibió
Permission denied al abrir el worktree externo desde el entorno restringido.
Conservado en visualización local step44/dossiers/audit_97b7992871ba41608d536c3ef8df11df.
No se reinterpretó como fallo económico. La revisión real accedió a sus rutas concretas
con permiso para esta operación, sin cambiar sandbox o protecciones de Codex.

**127 casos distintos aprobados en grupos**:44 nuevos de4.4,34 ingesta4.1,
18 contratos4.3 y31 integración4.2 con Codex **simulado**. No sumar repeticiones. Últimos pases:95/95 en a53,44/44 en a55 y31/31 en c44.
Las fixtures nuevas prueban recibos/ledger artificiales y omiten explícitamente solo
los sellos heredados4.3; la auditoría real ejecutó ese verificador completo.
Cobertura: cero trades/null/PASS/holdout consumido; hash/ausencia/identidad antigua;
dedupe/dos procesos/recuperación/migración; IA malformada/ref falsa/permiso indebido,
proveedor ausente y presupuesto concurrente/exhausto/desconocido; Telegram simulado
éxito/config/token ausentes/destino incorrecto o cambiado/error/429/timeout,
concurrencia/no retry incierto y secretos ausentes en salida/logs/SQLite.

```powershell
$tmp = 'C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85'
python -m pytest tests/unit/test_audit_orchestration.py tests/unit/test_orchestration.py tests/unit/test_execution_contracts.py -q -p no:cacheprovider --basetemp "$tmp/a53"
python -m pytest tests/unit/test_audit_orchestration.py -q -p no:cacheprovider --basetemp "$tmp/a55"
python -m pytest tests/integration/test_codex_orchestration.py -q -p no:cacheprovider --basetemp "$tmp/c44"
python -m ruff check .
python -m ruff format --check .
python -m pip check
git diff --check
```

Ruff/check/formato globales (472 archivos), pip check y diff check correctos.
Sin suite completa ni nuevas ejecuciones del motor. La aceptación4.3 se conserva
mediante contratos y lectura de su run real archivado. Sin repetir pruebas12 del piloto.

## Cierre y pendientes

1. Telegram real: **cubierto** en la prueba posterior autorizada. ACCEPTED/message_id136,
   un intento, recibo independiente; [evidencia](orchestration-step-4.4-telegram-acceptance.md).
2. IA real, aceptación separada: conector/límites/facturación y contabilidad global
   conocidos; MODEL_ASSISTED sigue bloqueado. No declarar todo quant_auditor desplegado.
3. Metodología/economía/robustez y brecha operativa siguen sin demostrar. No son
   permiso para investigaciones nuevas ni para demo, ni requisitos económicos de esta prueba.

Motor, estrategias, configuraciones operativas, forward, runs y recibos previos
conservados. Sin backtests nuevos, TEST histórico, modelos reales, descargas,
scheduling, OKX, commit, push o merge. Numeración:4.5 piloto completo,5 autorización
demo,6 investigación diaria y7 patrones, todos fuera de esta entrega.
