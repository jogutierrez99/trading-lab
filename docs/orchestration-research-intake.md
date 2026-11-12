# Flujo 1 · entrada de investigación bajo demanda

`research-intake` recibe un lote JSON `1.0` con una referencia de origen,
fecha UTC y entre una y doce ideas. El coordinador conserva una copia canónica
del lote. OpenAI selecciona como máximo un ID del lote, propone título,
justificación y limitaciones, y declara los campos pendientes. El modelo
recibe solo el lote, con salida estructurada, sin herramientas y con
`store: false`.

Cada idea puede incluir `facts` con los nombres de campo ya existentes en
`HypothesisManifest 1.0` y el campo de ingesta `liquidity_assumption`.
Copia de la fuente las reglas, el dataset, los
parámetros, la ejecución, los costes, el plan temporal y el resto de los
hechos técnicos. El coordinador los usa sin estimarlos con el modelo.
Las ideas que solo traen prosa pueden obtener una selección para revisar.
El coordinador comprueba presencia, tipos y coherencia de la ficha antes de
admitirla en `MANUAL_REVIEW / PREPARE_ONLY / QUEUED`. Conserva las observaciones
del modelo en `model_reported_missing` y los impedimentos de admisión en
`missing`. Si la fuente aporta un campo válido, la observación del modelo
no bloquea el alta. El recibo conserva la respuesta original.
La validación de la ficha no certifica la disponibilidad del dataset.
Declara los supuestos de ejecución y liquidez, los criterios de evaluación y
el plan de robustez. El coordinador conserva el supuesto de liquidez en la
política intrabar de la ficha, sin cambiar `HypothesisManifest`. La salida
estructurada solo admite identificadores de campos en `missing`. Los resultados
económicos y de robustez se evalúan después de ejecutar; su ausencia puede
constar como limitación y no impide el alta.

Se archivan `source.json`, `intent.json`, `provider-receipt.json`,
`manifest.json` cuando es válida, y `result.json`. Repetir el lote
canónico con la misma SQLite y carpeta devuelve el resultado archivado.
La reserva se identifica por el hash del lote en el ledger global, también
si se intenta importar en otro expediente. Un resultado incierto conserva
la reserva y exige reconciliación antes de otra llamada. La reconciliación
preserva el coste calculado y lo distingue del cargo facturado.

## Diagnóstico y prueba real

En PowerShell desde la raíz. Usa el ledger global que ya emplea el auditor y
una cola nueva fuera de OneDrive. En las dos rutas locales del ensayo se
mantiene separado el expediente del archivo SQLite.

```powershell
$py = '.\.venv\Scripts\python.exe'
$ledger = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3'
$env:TRADING_LAB_GLOBAL_API_DB = $ledger
$root = Join-Path $env:LOCALAPPDATA 'TLResearchAcceptance'
$queue = Join-Path $root 'queue\orchestrator.sqlite3'
$artifacts = Join-Path $root 'dossiers'
$batch = '.\examples\orchestration\research_batch_smoke.json'

$raw = & $py -B scripts/orchestrator.py research-doctor $batch --budget-db $ledger
$exitCode = $LASTEXITCODE
$diagnostic = $raw | ConvertFrom-Json
$diagnostic
if ($exitCode -ne 0) { throw 'Revisa los bloqueos del diagnóstico antes de llamar a OpenAI.' }
```

El diagnóstico es offline y muestra presencia de clave, saldo disponible y
reserva máxima. El perfil `gpt-6.1-sol` limita la respuesta a 2.400 tokens
y el lote a 24.000 bytes. Para el coste máximo reserva sobre el contexto
publicado completo de 1.050.000 tokens, con las tarifas largas conservadoras
del auditor, conversión de 1,25 €/USD, margen regional de 1,10 y fiscal de
1,25, redondeando hacia arriba. La reserva de este perfil es **18,11 €**.
El gasto se calcula con el uso devuelto y la factura se concilia por separado.
La revisión de tarifas caduca el 12 de noviembre de 2026 UTC. Sin saldo
reconciliado suficiente, el comando bloquea antes de llamar.

El siguiente comando documenta la prueba histórica. Para una nueva prueba
de alta usa el lote v2 y el perfil reducido de la sección siguiente.

```powershell
& $py -B scripts/orchestrator.py --db $queue research-intake $batch --budget-db $ledger --artifacts $artifacts --confirm-maximum-cents $diagnostic.pricing.maximum_cents
if ($LASTEXITCODE -ne 0) { throw 'Revisa el resultado y la contabilidad antes de continuar.' }
if (Test-Path -LiteralPath $queue) {
  & $py -B scripts/orchestrator.py --db $queue list
}
```

Una segunda orden idéntica permite consultar el resultado archivado sin
otra petición. `NEEDS_REVIEW` se conserva en el expediente sin crear
tarea. La automatización termina en la cola y el operador conserva la
revisión del expediente.

La prueba real con el lote de ejemplo registró una petición y devolvió
`NEEDS_REVIEW`. El modelo seleccionó la ruptura sintética y pidió concretar
la disponibilidad y generación de la serie, la evaluación y los supuestos
de ejecución. El expediente quedó archivado sin tarea. La prueba simulada
acredita por separado el registro idempotente en cola.

## Alta directa con un lote sintético nuevo

El lote original `examples/orchestration/research_batch_direct_queue.json`
definía la serie de 508 velas horarias, la precarga, las ventanas, los costes,
el criterio de evaluación y el plan de robustez. El modelo seleccionó
`sawtooth_cross_1h` y enumeró como pendientes evidencia económica, pruebas de
robustez y condiciones de liquidez/deslizamiento. La ingesta devolvió
`NEEDS_REVIEW` antes de llamar al validador. Una comprobación offline de la
ficha reconstruida confirmó que los hechos originales pasaban el esquema.
El lote y el expediente originales conservan su identidad y decisión.

En la prueba real del lote v2, el modelo enumeró los diez campos como ausentes
aunque estaban en la fuente. El cuerpo no se guardó como archivo separado.
La reconstrucción a partir de `source.json` produjo el mismo SHA-256 registrado
en `intent.json` y confirmó los diez campos en `input`. La reproducción offline
de la selección archivada con la validación corregida se hizo en otro expediente.

`examples/orchestration/research_batch_direct_queue_v2.json` añade el supuesto
que faltaba: liquidez sintética suficiente para el tamaño del 10 % del capital,
sin libro de órdenes, fills parciales, impacto ni variaciones de liquidez.
Se mantienen el spread y deslizamiento fijos. El volumen de las velas no
limita el tamaño simulado. Se conservan las reglas, los costes y el plan.

El perfil explícito `reduced` usa `gpt-4o-mini-2024-07-18` en modo
Standard. Su contexto publicado de 128.000 tokens establece el techo de
entrada incluyendo formato y esquema. La petición desactiva truncamiento
y limita la salida a 1.200 tokens. Con 0,15 y 0,60 USD por millón de tokens
de entrada y salida, respectivamente, y los mismos márgenes conservadores
del ledger, el máximo redondeado es **0,04 €**. Se mantiene el
vencimiento de tarifas del 12 de noviembre de 2026 UTC. Es un perfil para
esta aceptación, con retirada del modelo anunciada para enero de 2027.
[Modelo y tarifas](https://developers.openai.com/api/docs/models/gpt-4o-mini) ·
[Calendario de retirada](https://developers.openai.com/api/docs/deprecations)

Desde la raíz en PowerShell. La primera orden es local. El bloque se detiene
si hay gasto pendiente, falta saldo o cambia alguno de los límites revisados.
Antes de usarlo, concilia con justificante de facturación la llamada
`call_5c824d4fb451437b908383b7c25578e6` (reserva de 0,04 €).
`research-intake` verifica de nuevo la reserva en el ledger y hace como
máximo una petición de generación. Repetir la orden de alta con las mismas
rutas consulta el resultado archivado.

```powershell
$py = '.\.venv\Scripts\python.exe'
$ledger = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3'
$env:TRADING_LAB_GLOBAL_API_DB = $ledger
$root = Join-Path $env:LOCALAPPDATA 'TLResearchDirectQueueV2'
$queue = Join-Path $root 'queue\orchestrator.sqlite3'
$artifacts = Join-Path $root 'dossiers'
$batch = '.\examples\orchestration\research_batch_direct_queue_v2.json'
$raw = & $py -B scripts/orchestrator.py research-doctor $batch --budget-db $ledger --profile reduced
$code = $LASTEXITCODE
$check = $raw | ConvertFrom-Json
$check
if ($code -ne 0 -or $check.status -ne 'READY' -or $check.available_cents -lt 4 -or
    $check.pricing.model -ne 'gpt-4o-mini-2024-07-18' -or
    $check.pricing.input_token_ceiling -ne 128000 -or
    $check.pricing.output_token_limit -ne 1200 -or $check.pricing.maximum_cents -ne 4) {
    throw 'Prueba real bloqueada: revisar la conciliación y los límites del perfil.'
}
& $py -B scripts/orchestrator.py --db $queue research-intake $batch --budget-db $ledger --profile reduced --artifacts $artifacts --confirm-maximum-cents 4
```
