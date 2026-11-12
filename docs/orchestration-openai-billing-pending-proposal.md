# Propuesta de reserva íntegra mientras llega la facturación

Estado de la propuesta: para revisión. El prototipo vive en
`tests/unit/test_billing_pending_policy_proposal.py` y solo usa SQLite temporales.

## Evidencia del caso real

El ledger reservó `call_c5e2fa7c3c0e480989adf82757ec050c` el 6 de noviembre
de 2026 a las **13:26:59.057208 UTC**. El archivo del recibo se escribió a las
**13:27:03 UTC** según sus metadatos locales. La hora de procesamiento exacta del
proveedor es desconocida. El recibo coincide con el SHA-256 anclado al asiento,
`c325a89cc2c7a64f0c745de570cdd683ba25dc9709f95bc59ece30bf4cb174ff`.
El cliente comprobó el modelo `gpt-4o-mini-2024-07-18` y el nivel `default`
de la respuesta. El recibo contiene 1.425 tokens de entrada, 120 de salida y
cero de caché. La reserva es de 0,04 € y el cargo definitivo está pendiente.

Usage y Costs cubren el día UTC correcto. Según el sistema de archivos, las
copias disponibles se guardaron a las **13:24:30 UTC** y **13:24:53 UTC**,
respectivamente, antes de la reserva. Conservan los hashes de la revisión
anterior. Usage registra las tres llamadas previas y muestra el proyecto
`proj_bq5RVYUokDjvTsRFm3dncFdC`. Costs muestra la organización `Personal`,
`org-TocBjPxOe9BDvSRfrvLXV75c`, con `project_id` vacío y un total diario
agregado de 0,00651160 USD. Los CSV no contienen un registro de todos los
filtros seleccionados al exportar. Estos identificadores describen las
exportaciones y no acreditan el ámbito efectivo de la cuarta llamada.

El cliente HTTP no envió `OpenAI-Organization` ni `OpenAI-Project`, y el
recibo no guarda el ID de respuesta, `x-request-id`, `openai-organization`
ni una hora del proveedor. Tampoco consta un ID de clave de la cuarta llamada
que se pueda cruzar con Usage. La antigüedad de las copias explica su ausencia
en estos archivos. Aún falta distinguir si una exportación posterior seguiría
omitiéndola por retraso de publicación o por ámbito distinto. Para comprobarlo,
obtener Usage y Costs posteriores a las 13:27:03 UTC con el mismo día y ámbito
documentado. Si la llamada pertenece a la misma agrupación, Usage debería pasar
de dos a tres peticiones del modelo reducido, con **4.093 tokens de entrada y
459 de salida**. El importe requiere Costs atribuible por separado. Para futuras
llamadas, fijar los IDs de organización y proyecto permitidos y guardar los
identificadores de respuesta y petición, organización devuelta y tiempos UTC.
Guardar un `X-Client-Request-Id` propio antes del envío permite identificar un
intento aun si hay timeout. Los identificadores no sustituyen a la facturación.
[OpenAI API Reference](https://developers.openai.com/api/reference/overview)

## Admisión propuesta para el auditor de Flujo 1

Separar el resultado del proveedor del estado de facturación. Una llamada
`UNKNOWN` puede clasificarse internamente como **respuesta acreditada con
facturación pendiente** o **resultado o límite incierto**. No se cambia el
significado de `SETTLED` ni se registra un cargo al clasificar una respuesta.

Para la primera categoría, exigir una intención archivada y anclada por hash,
un recibo vinculado a la misma llamada y verificado contra el ledger, y una
respuesta con modelo, nivel y uso dentro de los límites. Verificar que el perfil
estaba vigente al reservar y que el máximo calculado por un perfil permitido
cabe íntegro en la reserva registrada. Las filas antiguas sin evidencia
suficiente siguen bloqueando. En particular, el recibo real tiene hash en el
ledger, pero la intención antigua carece del anclaje adicional que exige el
prototipo. No se propone migrarla por inferencia.

Limitar inicialmente la excepción a **un único investigador con respuesta
acreditada, del mismo mes UTC, y un único auditor dependiente**. Antes de activar
la excepción en producción, validar el vínculo entre ese auditor y la ejecución
de Flujo 1 que originó el investigador, además del dictamen determinista y los
controles de auditoría que ya existen. El prototipo simula ese vínculo con el
propósito del auditor. Rechazar otra llamada en vuelo, pendientes de otros meses,
recibos ausentes o alterados y perfiles con un máximo desconocido o que exceda
la reserva. Aplicar un límite de antigüedad operativo antes de habilitar la
política para evitar acumular facturación pendiente.

El saldo para admitir la segunda llamada es **2.000 céntimos menos el gasto de
apertura, los cargos ya conciliados y las reservas pendientes íntegras**. Comprobar
la identidad del auditor, el saldo y la reserva nueva en la misma transacción
`BEGIN IMMEDIATE`. Registrar el auditor como `RESERVED` antes de enviar. Si dos
procesos compiten, el segundo verá la reserva activa y deberá detenerse.

La conciliación sustituye la reserva por un cargo solo con evidencia atribuible.
Su repetición debe conservar el importe y liberar cero. Hay un requisito previo
a la activación: el conciliador automático actual rechaza dos pendientes del
mismo día. Habilitar primero la conciliación con evidencia separable por llamada
o por grupos que permitan atribuir importes individuales sin ambigüedad. Para
un grupo, validar todos los recibos, importes y hashes antes de liquidar los
asientos en una sola transacción, con identidad de evidencia y control de
repetición. Si el total diario admite varias asignaciones, conservar ambas
reservas y el bloqueo. Un cargo por encima de su reserva requiere revisión
manual y bloqueo de nuevas llamadas.

El prototipo de dos pendientes usa CSV simulados de un mismo proyecto y día UTC.
Usage identifica una sola llamada por modelo y Costs separa las partidas de
entrada y salida por modelo, con cantidades facturadas que coinciden con cada
recibo. Así atribuye los dos importes antes de liquidarlos en una sola transacción.
Al repetir con los mismos archivos, ambos cargos se conservan y se liberan cero
céntimos. Con el mismo Usage y un único total de Costs, ambas reservas se conservan.

Los CSV disponibles del caso real solo tienen un total diario de Costs. El
caso real pudo conciliarse porque había una sola llamada nueva entre dos
exportaciones. Si se añadieran dos a la vez, los identificadores de petición,
proyecto, modelo y tiempo ayudarían a localizar cada uso, pero el total de Costs
no aportaría el importe individual. Hace falta un desglose con cantidades y
costes atribuibles, o instantáneas comparables que aíslen cada cargo por separado.
El comando operativo sigue bloqueando dos pendientes incluso con los CSV
desglosados del prototipo.

## Prueba aislada

Desde PowerShell, en la raíz del repo:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/unit/test_billing_pending_policy_proposal.py
```

El caso con 1,88 € de gasto inicial, 0,04 € retenidos y una reserva simulada del
auditor de 18,08 € ocupa exactamente el techo. Con 1,89 € de gasto inicial se
rechaza el auditor. La cifra del auditor es un dato de prueba. También se cubren
dos reservas concurrentes, timeout sin recibo verificable, reserva en vuelo,
recibo alterado, límite insuficiente y repetición de una liquidación atribuida.
