# Reparación técnica del piloto — propuesta para revisión, 2026-11-04

**Actualización posterior:** el usuario autorizó la aplicación. Se registró una
identidad manual nueva y se completó4.3 con el piloto1.0.1. Ver [aplicación y recibos](pilot-native-index-repair-applied.md).
Este documento conserva la fase de propuesta, sus resultados y el presupuesto auditado.

**Estado durante la preparación: propuesta probada, aún sin aplicar.** Presupuesto agotado3/3. No se
lanzó ningún modelo desde el coordinador, no se creó otra tarea/implementación ni
se modificaron contadores, recibos o resultados anteriores. Sí se incorporó al
coordinador la comprobación barata solicitada para futuras entregas.

## Contrato y causa comprobados

Tarea task_7c894d7e4dca4f24a164632a703d5d5d, candidata
cand_0b7f6f1e8580418887519e1f67c6ae10, origen
attempt_cb2c94564a6f464f95faaeee58bae9a5, base
131ffaa101f7d04d81dcb47936142802ebba0a4b. Se inspeccionaron ficha/request, módulo,
perfil/test y recorrido HistoryCache → lab_data → lab_runner.window/evaluate →
BaseStrategy.generate_signals → StudyBackend.run.

| Aspecto | Contrato / decisión |
|---|---|
| Frame | open/high/low/close/volume, DatetimeIndex UTC; no columna timestamp |
| Tiempos | Índice de apertura, ordenado/único y con cobertura validada por el laboratorio |
| Timeframe | Ficha y metadata exclusivamente1h; candle_step("1h") equivale a una hora |
| Warmup | Ficha y required_warmup=100; posiciones0..99 sin señales;100 elegible |
| Vela previa | Diferencia de1h; primera observación false; primera fila tras gap false |
| Alineación | Features conservan índice y señales un bool Python por fila, en el mismo orden |
| Ejecución | Decisión al cierre, entrada siguiente apertura; warmup no abre posiciones |

Los tests viejos aportaban columna timestamp y RangeIndex. La operación temporal
pretendida era correcta; el contenedor asumido era incorrecto. UTC evita ambigüedad
de DST. No se adapta timeframe ni calendario.

## Diff propuesto y pruebas

[repair.patch](../examples/orchestration/repairs/manual_engulfing_native_index/repair.patch)
SHA256:e331bdbcc3e97e81b6d648dc37bb6f4f329b920fa7a9d2ce05215952550d0bc5.

Único cambio funcional del módulo:

```diff
- result["valid_previous"] = candles.timestamp.diff() == pd.Timedelta(hours=1)
+ result["valid_previous"] = candles.index.to_series().diff() == pd.Timedelta(hours=1)
```

to_series conserva la alineación; diff es causal y NaT compara false en la primera
observación. No se rellena, ordena, resamplea ni añade una columna artificial. Se
mantienen desigualdades estrictas, shift(1), warmup100, short false, costes, sizing,
stops/targets y protocolo de fills.

Se propone1.0.1 en módulo y perfil, que sigue deshabilitado. Corrige comportamiento
técnico y requiere identidad nueva. El cambio debe aprobarse como enmienda explícita
respecto a la referencia1.0.0 de la ficha inmutable; no reescribirla retrospectivamente.
El tercer archivo del patch reemplaza/amplía tests con fixtures nativas.

12 tests aprobados en5.00s en una copia aislada:

- UTC sin timestamp; índice/frame sin mutación; bool por fila y modos short false.
- Primera observación, vacío, warmup0..99 y elegibilidad100; NaN esperado del shift,
  sin valores inesperados en los flags.
- Cinco fronteras/NaN de entrada; igualdad/NaN de salida.
- Gap en entrada/salida y recuperación en la siguiente comparación contigua.
- Prefix-invariance de features y las cuatro señales al añadir observaciones futuras.
- FULL + lab_runner/StudyBackend real:244 velas generadas, una configuración, tres
  periodos sintéticos y3 backtests COMPLETE. Se fuerza una señal conocida para probar
  fills y entrada exactamente en la siguiente apertura, sin optimizar su resultado.

Run técnico de la propuesta:20261104T001455Z-4287fa9c37da. El nombre TEST que exige el
runner contiene solo datos generados del año2000: no se consumió holdout histórico.
Ruff lint/formato de módulo y test propuestos correctos. Probe nativo barato: VALID,
102 filas UTC (100+2), sin columna timestamp, sin dataset y0 backtests.

Los cambios se aplicaron solo en una copia plana de revisión, sin .git ni datos o
resultados previos. git apply --check pasó. Se fijó -c core.autocrlf=false por comando
para conservar LF; no se cambió Git global. Una primera copia detectó conversión CRLF
durante preparación y quedó conservada como diagnóstico; no era una entrega.

Evidencia bajo:
C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/pilot-native-index-repair-v2/.

- verification.json: comandos, retornos, SHA256 finales, run_id y conservación.
- budget-and-source.json: auditoría SQLite de solo lectura,3 intentos y fuentes.
- proposal-provenance.json: autor real (asistente Codex de este chat), procedencia,
  patch/hash y autorización de aplicación pendiente. No se atribuye a nueva invocación
  de Codex CLI ni a una persona que no escribió el código.
- repair.patch y review-workspace/: copia propuesta para pruebas.
- coordinator-native-gate.patch: cambios incorporados al coordinador frente al runtime
  archivado del último diagnóstico4.3.

Hashes del worktree origen, todos sus artefactos y SQLite operativo antes/después:
idénticos. No hay ImplementationReceipt nuevo del piloto. verification.json está
marcado PROPOSAL_TESTED_NOT_APPLIED_AS_DELIVERY y no sustituye un recibo.

## Control incorporado para futuras entregas

native_interface.py comparte el probe con4.3. El worker admite la acción interna
implementation-interface. Coordinator._verify la ejecuta tras pytest/Ruff, antes
de IMPLEMENTED_VERIFIED/IMPLEMENTATION_READY, con timeout/Job y tiempo restante del
plan. Runtime, resultado y proceso quedan archivados por hashes. No se cambian el
sandbox de Codex ni los límites de intentos.

Python -I -B importa quant_lab del workspace aislado y genera OHLCV sintético UTC
en memoria con timeframe/warmup declarados. Carga app/risk/perfil nativos, habilita
solo en memoria y comprueba índice de features, longitud/tipos mediante BaseStrategy
y ausencia de mutación. No lee historia ni ejecuta fills/backtests/modelos. Warmup
mayor1000 o backend dedicado bloquean para revisión separada.

El recibo futuro conserva los tres checks y añade native_interface. Los recibos legacy
no se recalifican.4.3 mantiene FULL y su probe de TRAIN real: el chequeo sintético no
demuestra causalidad completa, todos los parámetros/datos ni rentabilidad. Para
NEW_EXPERIMENT prueba una configuración representativa, sin barrido.
Los requests nuevos declaran explícitamente native_interface_check=
SYNTHETIC_OHLCV_UTC_V1. Los requests antiguos siguen siendo legibles, con marcador
None, pero no se les añade una orden no declarada ni se recertifican por esa ruta:
requieren otro request revisado. Sus recibos históricos y controles conservan sus hashes.

El simulador4.2 usa ahora clase/perfil nativos y prueba el rechazo de timestamp con
el control real. La fixture incompatible histórica4.3 simula explícitamente un
recibo legacy anterior al control; no se presenta como entrega nueva aprobada.

## Presupuesto y autorización necesaria

Misma tarea, sin duplicarla:

| Nº | Intento | Estado histórico actual |
|---|---|---|
|1|attempt_ee967d986ab94a7199ce5fddede29230|FAILED tras bloqueo y reconciliación|
|2|attempt_4d04e0db523a4130b77ab3262e0eaff8|FAILED tras bloqueo y reconciliación|
|3|attempt_cb2c94564a6f464f95faaeee58bae9a5|SUCCEEDED tras formato; incompatibilidad descubierta después|

La reparación de formato no creó otro intento. El límite sigue en3 en prepare y en
CHECK(number BETWEEN1 AND3). No hay una orden vigente para registrar una reparación
lógica manual con identidad nueva después del límite: prepare --repair la rechazará.

**Antes de aplicarla como nueva entrega debe autorizarse expresamente una reparación
técnica manual versionada de esta misma tarea**, sin modelo, con1.0.1 y este diff,
y la extensión mínima del registro necesaria para una nueva identidad vinculada al
origen. No es permiso para editar filas/hashes antiguos, reiniciar3/3 o duplicar tareas.

Procedimiento tras esa autorización, todavía no ejecutado ni expuesto como comando:

1. Revisar patch/enmienda de versión y habilitar una ruta explícita y acotada para
   registrar reparación manual con su autorización/procedencia. Resolver identidad/FK:
   executions referencia attempts. No basta escribir un JSON ni alterar la fila vieja.
2. Crear espacio e identidad nuevos vinculados al mismo task y al origen; conservar
   todo lo anterior y el3/3 histórico. Registrar autor real, patch/hash, base, archivos
   finales, enmienda y evidencia. No permitir invocar un modelo por esa ruta.
3. Aplicar el diff allí, repetir regresiones/probe/lint/formato y runner sintético;
   generar recibo nuevo tras contrastar bytes finales. No usar repair-format ni
   retocar ModelDelivery/recibo antiguos para atribuirles el arreglo.
4. Crear una solicitud4.3 vinculada exclusivamente a esa identidad/recibo. No redirigir
   ejecuciones FAILED/BLOCKED anteriores. Sin holdouts reservados ni permiso demo.

## Repetir la revisión local

Usar un temporal nuevo para conservar la evidencia anterior:

```powershell
$review = 'C:\Users\joshu\.codex\visualizations\2026\11\03\01a1a33b-ea60-7a40-aae1-de15594f5f85\pilot-native-index-repair-v2'
$workspace = Join-Path $review 'review-workspace'
$test = Join-Path $workspace 'tests\unit\test_manual_engulfing_breakout_v1.py'
$temporary = Join-Path $review ('pytest-review-' + [guid]::NewGuid().ToString('N'))
Set-Location $workspace
python -I -B (Join-Path $review 'run_proposal_tests.py') $workspace $test $temporary
python -m ruff check src/quant_lab/strategies/manual_engulfing_breakout_v1.py tests/unit/test_manual_engulfing_breakout_v1.py
python -m ruff format --check src/quant_lab/strategies/manual_engulfing_breakout_v1.py tests/unit/test_manual_engulfing_breakout_v1.py
```

No ejecutar el template de examples contra el paquete principal donde el piloto no
existe. No aplicar repair.patch al worktree histórico. Sin cambios al motor, push,
merge, Telegram, OKX, datos reservados ni optimización.

## Verificación del coordinador en esta revisión

103 casos distintos de orquestación/contratos aprobados en grupos, más los12 de la
propuesta (115 distintos). Primer pase dirigido:82 aprobados y20 errores de setup
en307.37s. Los20 fallaron antes del código probado por Git `'$GIT_DIR' too big` en
ese temporal largo. Se repitió únicamente ese módulo con --basetemp pn3, sin cambios
de permisos ni motor:20 aprobados en346.68s. No se presenta el primer pase como limpio.

Tras declarar el probe en el contrato se repitieron los casos real positivo/negativo:
2 aprobados en25.33s. Se añadió el rechazo de requests legacy sin orden declarada:
1 aprobado en4.56s (nuevo caso). Los otros pases repetidos no se suman como tests nuevos.
Ruff global/formato, pip check y git diff --check correctos; no suite completa.

Comandos desde la raíz del repo (usar --basetemp corto y nuevo dentro de una carpeta
permitida en este entorno Windows):

```powershell
python -m pytest tests/unit/test_orchestration.py tests/integration/test_codex_orchestration.py tests/unit/test_execution_contracts.py tests/integration/test_execution_orchestration.py -q -p no:cacheprovider
python -m ruff check .
python -m ruff format --check .
python -m pip check
git diff --check
```

Cambios efectivos: native_interface.py, implementation.py/implementation_contracts.py,
execution_worker.py y regresiones/fixtures de integración. El motor y los archivos
del piloto en su worktree no cambiaron. Cambios solo propuestos: módulo1.0.1,
perfil1.0.1 aún disabled y test nativo descritos en repair.patch. No se ejecutó
prepare/run/reconcile/repair-format contra la implementación operativa.
