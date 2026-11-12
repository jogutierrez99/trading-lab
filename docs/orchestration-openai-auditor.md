# Auditor OpenAI de Trading Lab

La aceptación real del 5 de noviembre de 2026 terminó en `COMPLETED` con una
sola petición `gpt-6.1-sol` sobre el run `20261105T193241Z-dd5fe4efd45a`.
La apertura de noviembre se registró en cero con la captura de Usage y la
confirmación del operador. OpenAI informó 896 tokens de entrada y 240 de salida.
La revisión pasó la validación de esquema y referencias y conservó `NO_DECISION`.
El coste calculado inicialmente fue 0,02 €. El CSV Cost data de OpenAI confirmó
0,004192 USD. El asiento `call_4d5b851c190c4c8bb78afa5c48b82457` quedó `SETTLED`
con una imputación conservadora de 0,01 € y 19,99 € disponibles en noviembre UTC.
El justificante y su SHA256 quedaron registrados en SQLite. Se verificaron los hashes del expediente
y del dictamen determinista original. [Recibo de la revisión](C:/Users/joshu/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/TL46OpenAI/acceptance-001/review_receipt.json)

La revisión `MODEL_ASSISTED` se solicita con `audit-openai` sobre un audit_id
determinista existente. El coordinador comprueba sus hashes y vuelve a verificar
la evidencia primaria con el mismo auditor de solo lectura. El paquete limitado a
16 kB contiene identificadores, métricas seleccionadas, recuentos, límites y
referencias lógicas con SHA256. Se excluyen las rutas locales, los archivos brutos,
las credenciales y los mensajes de implementación.

El transporte usa un POST a `/v1/responses`, `store=false`, tarifa `default`,
sin herramientas y con `text.format` de tipo `json_schema` estricto. El modelo
inicial es `gpt-6.1-sol`. `--model` selecciona el perfil de precio y un modelo sin
perfil revisado queda bloqueado. El adaptador solo lee `OPENAI_API_KEY` del `.env`
del proyecto y la mantiene en memoria local. El entorno filtrado de Codex excluye
variables que contienen `API_KEY`. La configuración no usa un modelo alternativo.

La revisión pasa por `ModelReview` y solo puede citar las referencias del paquete.
`review_request.json`, `review_receipt.json` y `hashes.json` forman un expediente
separado que enlaza el audit_id, el hash del dictamen original y el run. El dictamen
determinista conserva autoridad sobre métricas, filtros, estados y elegibilidad.
Una salida inválida o una respuesta incompleta con uso conocido queda registrada
como `INVALID_REVIEW`. Un timeout, error HTTP o falta de datos fiables de uso queda
como `UNKNOWN_PROVIDER_OUTCOME`. Cada ejecución envía como máximo una petición.
Repetir el mismo execution_id se bloquea incluso si se usa otro destino o si la
facturación ya se ha reconciliado.

## Reserva global

Se usa la SQLite canónica del sistema, identificada explícitamente por
`TRADING_LAB_GLOBAL_API_DB` y `--db`. La base que contiene la evidencia se abre
por separado y en solo lectura. Las operaciones de presupuesto usan las tablas
existentes sin migrar la base v6. El mes se calcula en UTC y el máximo global es
20 €. El saldo requiere apertura mensual con el gasto acumulado conocido de todos
los proveedores. Las reservas sin reconciliar bloquean nuevos envíos, incluso en
otro mes. Todos los consumidores del presupuesto deben usar esa misma base.

El perfil consultado el 5 de noviembre de 2026 usa el contexto oficial de 1.050.000
tokens como techo de entrada, incluida la sobrecarga del esquema. El paquete real
es mucho más pequeño. El límite de salida son 1.200 tokens, incluido razonamiento.
Para la reserva se aplica el precio largo más alto de escritura de caché estándar
de 10 USD por millón a toda la entrada y 15 USD por millón a la salida. Se aplica
1,25 EUR por USD como techo de conversión, 1,10 de recargo regional y 1,25 de margen
para impuestos. Son límites conservadores de aceptación que el operador debe
comprobar para su cuenta antes de confirmar. El resultado redondeado hacia arriba
es **18,08 €**. La reserva deliberadamente amplia evita depender de un contador
remoto ni de una estimación local de tokens facturables. El perfil caduca el
12 de noviembre de 2026 UTC y exige revisar tarifas para volver a habilitarlo.

| Concepto | Cálculo de la reserva vigente | Resultado |
|---|---|---:|
| Entrada | 1.050.000 × 10 USD / 1.000.000 | 10,500 USD |
| Salida | 1.200 × 15 USD / 1.000.000 | 0,018 USD |
| Conversión | 10,518 USD × 1,25 EUR/USD | 13,1475 € |
| Recargo regional | 13,1475 € × 1,10 | 14,46225 € |
| Margen fiscal | 14,46225 € × 1,25 | 18,0778125 € |
| Redondeo | Al céntimo superior | **18,08 €** |

El supuesto dominante es cobrar **todo el contexto de entrada al mayor precio de
caché del tramo largo**. Representa 10,50 de los 10,518 USD previos a conversión.
El factor de cambio es un techo presupuestario que debe comprobar el operador
para la cuenta, igual que los márgenes. El diagnóstico muestra el desglose y
el tamaño exacto en UTF-8 del cuerpo que construye el transporte, sin la clave.

## Perfil reducido propuesto

En el run `20261105T193241Z-dd5fe4efd45a` el paquete verificado ocupa **1.887 bytes**
y el JSON completo de Responses **3.559 bytes**. El perfil propuesto conserva los
seis casos, el protocolo, los recuentos, las limitaciones y las referencias con
SHA256. Admite hasta 2.048 bytes de paquete y 4.096 de cuerpo. Mantiene `ModelReview`
estricto, tres observaciones breves como objetivo y `max_output_tokens=1200`,
incluido el razonamiento. Un rechazo, truncamiento o referencia inventada invalida
la revisión y conserva el dictamen determinista.

Con un **techo de entrada verificado de 4.096 tokens facturables**, incluida la
sobrecarga del esquema, quedaría en el tramo corto. El cálculo conservador sería
`(4096 × 5 + 1200 × 10) / 1.000.000 × 1,25 × 1,10 × 1,25` euros,
es decir, 0,055825 € antes de redondear y **0,06 €** de reserva.

Los límites de bytes se pueden comprobar localmente sobre el paquete y el cuerpo
exactos. Esos bytes no establecen por sí solos un techo de tokens facturables.
La documentación oficial advierte de la sobrecarga de esquemas y ofrece un POST
adicional a `/v1/responses/input_tokens` para contar el mismo payload. Para activar
el perfil reducido habría que verificar la política de coste de esa operación,
usar el mismo cuerpo y modelo, y bloquear la generación si el conteo supera 4.096.
El diagnóstico local no hace ese POST y la orden de aceptación conserva una sola
petición de generación. **El perfil reducido es una propuesta y 0,06 € no es una
reserva habilitada**. La CLI mantiene 18,08 € hasta disponer de un límite de entrada
verificable. [Conteo de tokens de OpenAI](https://developers.openai.com/api/docs/guides/token-counting)

El recibo separa tokens informados por Responses, coste calculado conservador y
coste reconciliado. Con uso conocido, la estimación cobra toda la entrada al mayor
precio de escritura de caché del tramo correspondiente y no descuenta caché.
SQLite retiene la reserva completa hasta `api-budget-reconcile` con justificante
de facturación. El cálculo queda preservado en el expediente y en la procedencia
del asiento, separado del importe facturado. Un timeout de socket de 45 s deja
consumo incierto y tampoco habilita un reintento.

Fuentes oficiales consultadas. [Modelo](https://developers.openai.com/api/docs/models/gpt-6.1-sol) ·
[Tarifas](https://developers.openai.com/api/docs/pricing?latest-pricing-expanded=true) ·
[Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses) ·
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

## Procedimiento de aceptación desde PowerShell

Usa el run sintético existente `20261105T193241Z-dd5fe4efd45a`. El diagnóstico local
verificó sus seis casos y encontró `OPENAI_API_KEY` presente. Inicialmente devolvió
`GLOBAL_API_ACCOUNTING_UNKNOWN` hasta que el operador confirmó el gasto del mes.
El expediente de este run ya se creó. Los comandos siguientes documentan el procedimiento.

La verificación final aprobó 85 pruebas de auditoría, verificación de piloto y
contratos del circuito. Las simulaciones cubrieron clave ausente, saldo insuficiente,
salida inválida, referencias inventadas, timeout, deduplicación después de reconciliar
y transporte de un solo POST. El pase anterior obtuvo 83 aprobadas y un fallo porque
la prueba todavía esperaba el texto antiguo del rechazo de `MODEL_ASSISTED` por la
CLI genérica. Se actualizó la expectativa para exigir la orden explícita `audit-openai`.
Ruff, formato, dependencias y `git diff --check` pasaron. Se verificaron los bytes
de la base global v6, 140 JSON históricos y 12 recibos de la aceptación 4.6. La
base global tenía cero filas en `api_months` y `api_calls` antes de la aceptación.

```powershell
$repo = 'C:\Users\joshu\OneDrive\Escritorio\WEBS\Back_testing\trading-lab'
$local = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local'
$ledger = Join-Path $local 'TL42\964b59\orchestrator.sqlite3'
$source = Join-Path $local 'TL46Final\state\acceptance.sqlite3'
$dossier = 'C:\Users\joshu\AppData\Local\TL46OpenAI\acceptance-001'
$env:TRADING_LAB_GLOBAL_API_DB = $ledger
$audit = 'audit_dc0310c9855f41289ce594507bea1b71'
Set-Location -LiteralPath $repo
python -B scripts/orchestrator.py --db $ledger audit-openai-doctor $audit --source-db $source --model gpt-6.1-sol
```

Si falta la apertura del mes, obtén el gasto acumulado de todos los proveedores y
su justificante antes de ejecutar este paso. Si ya hay un mes abierto, consulta
sus asientos con `api-budget` y reconcilia los pendientes con sus justificantes.
Una tabla local vacía no acredita gasto cero. Introduce cero solo si el extracto
del periodo UTC verifica cero en todo el ámbito del presupuesto. Si hay consumo
pendiente o falta un justificante, conserva el bloqueo. Con esta reserva deben
quedar al menos 1.808 céntimos disponibles de los 2.000 del mes.

```powershell
$known = Read-Host 'Gasto global conocido en centimos EUR'
if ($known -notmatch '^\d+$') { throw 'Indica un importe conocido y documentado.' }
$opening = [int]$known
$provenance = Read-Host 'Referencia del justificante global'
python -B scripts/orchestrator.py --db $ledger api-budget-open --opening-spend-cents $opening --provenance $provenance
```

Después de repetir el diagnóstico y obtener `READY`, esta es la única orden de
aceptación real. `--confirm-maximum-cents` confirma el techo y las condiciones del
perfil vigente que se mostraron en el diagnóstico.

```powershell
python -B scripts/orchestrator.py --db $ledger audit-openai $audit --source-db $source --model gpt-6.1-sol --artifacts $dossier --confirm-maximum-cents 1808
```

Conserva el `call_id` y los recibos. Usa `api-budget-reconcile CALL_ID
--actual-cents CENTIMOS_FACTURADOS --provenance JUSTIFICANTE` al disponer de la
facturación. Telegram sigue en preview y el conector queda fuera del circuito 4.6,
OKX, la investigación diaria y el programador.
