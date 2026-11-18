# Fase 5.5A — StudyBackend aislado y recepción de resultados

Commit de partida `5cef79b45780c9a0e9964b01b2fa46d9531ae18a`.
La única entrada ejecutable de esta fase es `run_synthetic(job_id, scratch)`.
Construye su propio OHLCV artificial y señales fijas del año 2000. No acepta
rutas de datasets, estrategias, planes ni comandos del llamador.

## Motor y aislamiento

El adaptador invitado construye un frame UTC, calcula el ATR aritmético con
`quant_lab.features.atr` y llama a `StudyBackend.run`. Los fills, reglas
intrabar, sizing, costes, operaciones, rechazos y liquidación siguen usando
el motor de D. Las métricas vienen de `quant_lab.metrics.summarize`. La
normalización UTC al entrar al motor resuelve la diferencia de representación
entre el datetime de Pydantic y el índice de Pandas observada en el primer
ensayo real. No se modifica el motor.

El host sella una lista cerrada de dependencias Python extraídas de D y
empaqueta el fixture y el adaptador por stdin. Reutiliza el supervisor de
5.4B, incluida su comprobación de escrituras, red, DNS y sockets VM-host
en padre e hijo. El contenedor no monta archivos del host ni el socket de
Docker. No recibe datos de mercado históricos, YAML operativo, credenciales
ni bases SQLite. Usa un usuario sin privilegios, raíz de solo lectura,
capacidades retiradas, red `none`, una CPU, 768 MiB sin swap, tmpfs de
32 MiB y hasta 64 procesos. El supervisor acota tiempo, stdout y stderr,
persiste la identidad del contenedor y confirma su eliminación. Se usa la
imagen validada de 5.4B por digest local, sin pull. El invitado comprueba
las versiones de NumPy, Pandas, PyArrow, Pydantic y PyYAML. El digest de
imagen cubre el entorno completo.

## Contratos de entrada 1.0 y resultado 1.1

- `Plan` sella trabajo, estrategia, commit, motor, parámetros, riesgo,
  costes, archivo por archivo, dataset, versiones de dependencias, imagen,
  ventanas, precargas y límites. `HISTORICAL_PROPOSAL` es declarativo y
  comprueba el alcance congelado del Issue #3. Ninguna entrada ejecutable
  acepta esa clase de plan. El sobrescrito del entorno no concede permisos.
- `Result` 1.1 es un único documento JSON, menor que 512 KiB, vinculado al
  hash del plan y al dataset, motor, imagen y dependencias. Cada caso
  tiene una clave virtual exacta `cases/<id>.json` y su SHA-256 sobre JSON
  canónico. El host no crea archivos desde nombres enviados por el
  contenedor ni extrae un tar de resultados. No hay transporte de
  ejecutables, enlaces, pickle ni rutas devueltas por el invitado.
  Cada caso declara `open_position: null` porque la liquidación final es
  obligatoria. El recibo anfitrión usa la versión 1.2. Los resultados y
  recibos anteriores se conservan como evidencia de sus propios ensayos.
- `CaseResult` devuelve costes, operaciones, rechazos, métricas, equity y
  exposición. La posición de cada punto fija su hora a partir de inicio y
  frecuencia sellados. El host valida tipos, versión, finitud, identidades,
  número exacto de casos, claves duplicadas, longitud y hashes. Recalcula
  comisiones, spread, deslizamiento, PnL, riesgo presupuestado, retorno,
  drawdown, exposición media, expectancy, win rate y profit factor. Exige
  que PnL y equity de cierre reconcilien con la liquidación del tramo.

## Conciliación económica independiente

La auditoría reprodujo una curva con cero operaciones, exposición
positiva y una pérdida intermedia del 50 %. El resumen y los hashes,
recalculados por quien construyó el JSON, pasaban los controles de la
versión 1.0. La regresión conserva ese ataque con un documento 1.1
formalmente válido. El host lo rechaza con
`REJECTED_SEMANTIC_INCONSISTENCY` y persiste únicamente el fallo y sus
evidencias. Una captura de dos casos Docker anteriores, con los campos
1.1 explícitos, sirve de fixture declarativo para mutaciones independientes.

El host regenera los mismos bytes sintéticos que suministra al invitado
y verifica el SHA-256 frente al plan. El JSON de salida carece de campos
para sustituir las velas. Las ventanas se alinean a UTC y las series
incluyen un punto inicial y un punto por cierre de barra. La señal a
cierre de la barra anterior tiene la misma marca que la apertura
siguiente, momento de la entrada. La salida al abrir usa la apertura de
la barra, una salida intrabar deja `exit_time` nulo y una salida al
cierre usa el extremo de la barra.

La conciliación parte del capital inicial y reconstruye en orden una
posición larga como máximo. Comprueba la apertura contra las velas, los
niveles contra el ATR aritmético de la vela de señal y el tamaño
redondeado hacia abajo según riesgo, efectivo y paso de cantidad. El
saldo descuenta la comisión de entrada sin descontar el valor
nocional. Cuando hay posición, el equity es saldo más
`cantidad × (cierre − precio efectivo de entrada)` y la exposición es
`cantidad × cierre / equity` si el equity es positivo. Para una cuenta
plana el equity es el saldo y la exposición es cero.

Al cerrar se suma el PnL realizado bruto y se resta la comisión de
salida. El precio efectivo aplica slippage y medio spread en la
dirección adversa. Un gap de stop usa la apertura y uno de objetivo
usa el nivel del objetivo. Las protecciones al abrir se comprueban
antes de una salida por señal. Sin salida en la apertura, el stop
intrabar tiene prioridad sobre el objetivo. Si queda una posición en
la última barra y no se activa otra salida, se liquida al cierre.
La barra de salida ya muestra exposición cero. Se verifica que queda
una cuenta plana al terminar, incluso si se declaran cero operaciones.

Se contrasta cada punto de equity y exposición y se recalculan las
métricas sobre las series reconstruidas y las operaciones validadas.
La comparación usa tolerancias `rel_tol=1e-9` y `abs_tol=1e-8`,
suficientes para diferencias de coma flotante y de unos 0,00001 USDT
a un equity de 10.000 USDT. La cantidad se compara con tolerancia
absoluta de `1e-10`, inferior al paso de `0,000001 BTC`. El resultado
recibido se conserva con sus propios datos.

Esta comprobación acredita consistencia contable con velas selladas y
operaciones declaradas. La verificación de que se declararon todas las
señales y ejecuciones de la estrategia, y de su causalidad, corresponde
al supervisor independiente de 5.5B. El adaptador de esta fase sigue
rechazando planes históricos.

## Recepción y recuperación

### Decisión de almacenamiento

Se comparó SQLite dedicada con un documento único que contiene la evidencia
y el recibo. SQLite ofrece unicidad, consultas e interrupciones recuperables
mediante transacciones, y sería útil para un almacén indexado de muchos
trabajos. Requiere proteger en Windows la apertura por nombre del archivo y
la creación o reapertura de los auxiliares de rollback o WAL. Una SQLite
separada sin esa protección habría dejado abierta la redirección de R3.
El perfil 5.5A tiene un resultado inmutable por trabajo y un escritor
exclusivo por raíz. Se adoptó un documento único sobre NTFS para reducir
las entradas mutables, conservar la consulta local y evitar una base
auxiliar o un VFS propio.
[SQLite y sus archivos auxiliares](https://www.sqlite.org/atomiccommit.html)

### Publicación y recuperación

- **R1.** El anfitrión captura stdout una vez después del cálculo y de
  confirmar la limpieza. Valida los bytes, calcula SHA-256 y conserva la
  captura exacta en base64 junto con los logs capturados y sus hashes. El
  recibo anfitrión 1.2 incluye identidad del plan, trabajo, imagen, motor y
  protocolo. Los casos e identidades de ejecución están dentro del export
  económico, que mantiene su versión 1.1. El fichero fijo `result.json`
  contiene todo lo necesario para verificar `COMPLETE`. El fichero mutable
  `study.stdout` queda como diagnóstico y `accepted-stdout.json` ya no forma
  parte de la publicación. Ningún nombre recibido del invitado se convierte
  en una ruta local.
- **R2.** Se abre el temporal con `CREATE_NEW` y sin compartición. Se
  verifica su contenido usando el mismo handle tras flush y fsync. La
  promoción NTFS por handle se realiza con reemplazo deshabilitado.
  Antes de intentar promover, un fallo puede marcar para borrado solo el
  objeto adquirido. A partir del intento de promoción se conserva la
  evidencia ambigua, ya que el nombre final podría haberse instalado.
  Un temporal preexistente conserva sus bytes.
- **R3.** El almacenamiento exige una ruta local NTFS con letra de unidad.
  Se anclan los ascendentes sin compartir borrado. `NtCreateFile` con
  `OBJ_DONT_REPARSE` bloquea reparses durante la creación o apertura de
  directorios y durante la instalación de los ficheros de anclaje. Una vez
  instalados y abiertos en exclusiva, los anclajes mantienen ocupados los
  directorios raíz, trabajo y configuración Docker. NTFS rechaza adjuntar
  el junction a un directorio ocupado. Las aperturas de evidencia y
  temporales también excluyen reparses de la hoja. Se rechazan enlaces
  duros en las evidencias de control. Todas las operaciones del almacén que
  usan rutas mantienen el anclaje durante la operación.
  [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
  [InitializeObjectAttributes](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/nf-ntdef-initializeobjectattributes)
  [FILE_RENAME_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_rename_info)

El directorio del trabajo es el primer marcador de reserva. Antes de Docker
se publica el plan de reserva. El cerrojo nativo excluye otra invocación en la
misma raíz. Si el proceso termina antes de promover el resultado, se conserva
la reserva y una consulta indica que requiere conciliación. Si terminó después,
la consulta recupera el resultado solo si concilian plan, recibo, hashes, bytes
capturados y validación económica. Un `UNKNOWN`, un archivo corrupto o una
reserva sin cierre detienen nuevos cálculos en esa raíz. El operador debe
preservar la carpeta original y revisar el marcador, los logs y la identidad
del contenedor. Repetir la consulta del mismo trabajo nunca relanza una reserva.
Los expedientes experimentales 1.1 se conservan en su raíz original. El
lector 1.2 no migra ni reinterpreta sus recibos.

### Límite de confianza

Usar una raíz dedicada bajo una carpeta local del operador, con ACL que
excluyan a otros usuarios de escritura, borrado y cambios de permisos sobre
el almacén. Los handles y el rechazo de reparses controlan la sustitución de
directorios durante una invocación. El código no instala una ACL ni administra
permisos. Los hashes detectan divergencias respecto al recibo, y un usuario
que pueda reescribir toda la evidencia, cambiar la asignación de una unidad o
eliminar todas las reservas requiere una frontera de seguridad distinta.
El sondeo de 5.5A crea `<trabajo>/preflight` y su `docker-config` con
apertura nativa exclusiva, rechazo de reparses y anclajes durante toda la
comprobación. El supervisor recibe esa ruta antes del primer comando. Sus
logs y canario tienen nombres fijos; las lecturas se acotan y el canario
se crea en exclusiva. Los diagnósticos se conservan en el expediente.
No hay limpieza recursiva para esta ruta de preflight. La eliminación
del contenedor sigue a cargo del supervisor.

La reauditoría reprodujo en la versión anterior una redirección por
junction del directorio temporal del sondeo, antes de `docker image inspect`.
El proceso anfitrión creó `docker-config`, `image.stdout` e `image.stderr`
en un directorio externo desechable. Este hallazgo afecta al proceso
anfitrión. Para el cambio actual se comprobaron por simulación la ruta
vinculada, la adquisición exclusiva, el rechazo de rutas inválidas y el
estado incierto ante permisos denegados. Queda pendiente la aceptación
nativa del preflight actualizado.

La llamada sin directorio explícito conserva el comportamiento anterior
para los verificadores ajenos al adaptador 5.5A. Como cambió el código del
verificador compartido, cambia su huella. Una autorización que todavía
dependiera de la huella anterior requeriría revisión mediante el control
existente. Los recibos ya emitidos mantienen su huella original.

El almacén protege la identidad de los directorios durante una invocación.
La prueba de reapertura observó que mover toda la raíz y recrearla vacía
en el mismo nombre oculta el registro de reserva a la siguiente invocación.
La idempotencia se aplica a la raíz que conserva sus registros. El
anclaje persistente entre invocaciones requeriría una identidad esperada
conservada fuera de esa raíz.
El documento único elimina la ventana entre dos publicaciones y se verificó
con salidas abruptas del proceso antes y después de la promoción. No se ha
probado un corte de energía o pérdida completa del volumen. El fsync y
la escritura write-through sincronizan el archivo, y queda sujeta al
sistema de archivos la persistencia de la entrada del directorio tras una
pérdida de energía.

## Ensayos

Desde Windows con el motor Linux disponible, en un checkout de este
cambio y con las dependencias de desarrollo instaladas:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:TRADING_LAB_VERIFICATION_IMAGE = 'sha256:539a1a6c2f1669b6c36612417f9cf70fe28e822095433d8a1453e706396b5f2e'
$env:TRADING_LAB_55A_REAL_ISOLATION_TEST = '1'
$evidence = Join-Path $env:LOCALAPPDATA ('TL55A-' + [guid]::NewGuid())
python -B -m pytest -q -p no:cacheprovider --basetemp $evidence tests/unit/test_isolated_study.py
```

El ensayo Docker usa casos BASE y ADVERSE artificiales y exige operaciones
con objetivo y stop. Un segundo ensayo provoca un timeout del supervisor
y verifica que elimina el contenedor. Los dobles de prueba cubren errores
de esquema, rutas, hashes, finitud, coherencia, duplicados, concurrencia,
interrupción y recuperación. El ensayo real reutiliza el sondeo adversarial
del supervisor y conserva los logs bajo la raíz de pytest.

La aceptación del rediseño en Windows, anterior a la corrección del
preflight, ejecutó 107 casos pytest distintos
entre el adaptador y las regresiones de autorización y verificación.
La cuenta carecía de permisos para crear un symlink real y ese caso quedó
omitido. Se seleccionó el sondeo real del adaptador y se excluyó el sondeo
Docker redundante del grupo anterior. Pasaron los junctions reales, el
enlace duro, los dos cierres abruptos del proceso, BASE y ADVERSE,
aislamiento y timeout. Un oráculo independiente contrastó las dos curvas y
rechazó las 27 mutaciones económicas. El motor y las rutas de ejecución
histórica quedan fuera de estos cambios.

## Propuesta 5.5B y límites pendientes

El [borrador de autorización](../examples/orchestration/phase-5-5a/historical-authorization.draft.json)
documenta la propuesta del Issue #3 con la estrategia publicada, D y el
bundle local fijado. Esta copia de revisión omite los identificadores y
la huella del recibo del expediente operativo. El archivo es un
borrador sin confirmación ni reserva. El hash de protocolo del borrador
fija el manifiesto del Issue. Antes de autorizar, sellar además la
clausura completa de entradas y el supervisor histórico definitivo.

Los casos son TRAIN 2022-02-01 a 2022-04-01, VALIDATION 2022-04-01 a
2022-05-01 y TEST retrospectivo 2022-05-01 a 2022-06-01, a medianoche
UTC con fin exclusivo. Cada tramo tiene BASE y ADVERSE, 240 velas
independientes de precarga, SMA50/SMA200 fijas, spot LONG_ONLY, NEXT_OPEN,
stop inicial de 2 ATR14, 2R, riesgo 0,5 %, capital de 10.000 USDT y
posición y exposición máximas del 100 %. Paso y mínimo 0,000001 BTC,
nocional mínimo 10 USDT, sin funding, trailing ni time stop. BASE usa
0,10 % de comisión, 0,03 % de slippage y 0,02 % de spread; ADVERSE
duplica los tres. Se conserva el orden de fills y gaps del manifiesto,
con stop primero intrabar sin reentrada en la misma apertura y
liquidación de fin de tramo. Holdout `CONSUMED`, sin selección de
parámetros ni afirmación de independencia.

Antes de una ejecución real hay que cerrar el límite de exportación a
escala, reservar y reconciliar el caso de un corte del supervisor, y
aplicar la normalización UTC en la adaptación del runner histórico.
Probar esos puntos con fixtures de hasta seis casos y volumen límite.
El transporte actual rechaza salidas de 512 KiB o más. Antes de reservar
los seis casos se requiere verificar la capacidad o definir un
transporte acotado en partes. Presupuesto de propuesta de una invocación de
lote de hasta 120 s de cálculo, más preflight y limpieza acotados, seis
casos exactos y 0 EUR de API. El rendimiento histórico no se ha medido.

El rechazo de `Executor.prepare` para el piloto y el trigger
`pilot_launch_no_backtest` permanecen intactos. El futuro diff protegido
debe introducir un permiso distinto de `LAUNCH_CODEX`, vincularlo al
plan y al supervisor definitivos, y reservar permiso y lote en la
misma transacción. Las rutas antiguas deben conservar su rechazo.
El registro tendrá identidad de operador y confirmación interactiva,
reserva única, exclusión global, estados inciertos y cierre auditable.
La política exige cero llamadas API, Codex, OKX y Telegram, sin reintentos
automáticos. Cualquier mecanismo futuro se revisará y probará primero
en SQLite temporal. Ni el borrador ni el adaptador sintético autorizan
operaciones sobre el expediente original.

Para publicar 5.5A, revisar el diff y los hashes sobre D, repetir las
regresiones, verificar que `origin/main` sigue en D y solicitar
aprobación de commit y push fast-forward. La revisión, la autorización
histórica y el lanzamiento de 5.5B son acciones posteriores.
