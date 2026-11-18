# Fase 5.5B — preparación del histórico aislado del Issue #3

Base de desarrollo: `2986ffa2a85e810cd558ebba3bdf8c42958a0cc3`.
Código congelado de estrategia y StudyBackend: `5cef79b45780c9a0e9964b01b2fa46d9531ae18a`.
El histórico está pendiente de aceptación nativa y de una autorización posterior.
Esta fase conserva 5.5A, el YAML deshabilitado y el trigger que bloquea el piloto
en las rutas antiguas.

## Datos y frontera del trabajo

`check-data` solo lee el Parquet y el manifiesto del bundle fijado. Comprueba
ambos SHA-256 desde los mismos bytes que analiza, la identidad del manifiesto,
UTC, OHLCV finito, orden, unicidad, continuidad y 240 horas previas a cada ventana.
Reporta `BLOCKED_DATASET` ante un bundle ausente o alterado. No hay descarga
implícita. Al preparar el trabajo se sella por separado la proyección JSON de
velas que se suministra al contenedor. El original permanece intacto.

Los casos conservan TRAIN 1 de febrero a 1 de abril, VALIDATION 1 de abril a
1 de mayo y TEST retrospectivo 1 de mayo a 1 de junio de 2022, con fin exclusivo.
Cada ventana tiene BASE y ADVERSE en ese orden y reinicia el capital. La huella
del plan congelado impide cambiar ventanas, costes, casos o parámetros.
TEST conserva `CONSUMED`. El paquete efectivo contiene un conjunto cerrado de
módulos Git de D y los módulos del adaptador. Los hashes de estrategia y motor
en el borrador se verifican tras normalizar archivos de texto a LF si el
archivo Git de Windows entrega CRLF. El trabajo añade los SHA-256 de la
clausura efectiva, la proyección, el manifiesto y el supervisor.
La imagen y las dependencias se comprueban con las identidades fijadas.

## Ejecución y auditoría

El invitado usa la estrategia publicada y StudyBackend v1. El supervisor
independiente reconstruye el cruce SMA50/SMA200 con ventanas causales, ATR
aritmético, la decisión NEXT_OPEN, sizing, gaps, protección, cierre y
liquidación desde las velas selladas. Identifica fills o rechazos omitidos,
añadidos o en un bar distinto. Después reutiliza la conciliación contable de
5.5A para recomponer costes, PnL, equity, exposición y métricas. Las
discrepancias abortan la aceptación. Una diferencia numérica en el signo de un
cruce muy próximo a cero también bloquea la aceptación. No hay tolerancia
para cambiar una decisión.

Se preservan operaciones, rechazos, equity, exposición y métricas por
escenario. El resumen incluye deltas de retorno, recuentos, comisiones y
estadísticas simples de concentración de las operaciones. El informe sintético
emite `NO_DECISION`. El TEST ya consumido no acredita independencia.

## Transporte y persistencia

El transporte 2.0 usa un flujo JSON por líneas. Incluye una cabecera ligada al
SHA-256 del trabajo, seis manifiestos en orden fijo y bloques de hasta 32 KiB
por caso. Cada manifiesto declara identidad, tamaño, cantidad de bloques y
SHA-256 del caso. El receptor verifica orden, tamaño e identidad de cada
bloque y su SHA-256. Un bloque solo usa zlib cuando reduce sus bytes; en los
demás casos se transmite sin compresión. La descompresión rechaza expansión
excesiva, bytes sobrantes o streams incompletos. Tras el sexto caso se exige
fin del flujo. La publicación exige que el auditor valide todos los casos.

### Cota conservadora del lote completo

Cada ventana tiene 1.416, 720 o 744 barras. BASE y ADVERSE suman 5.760 barras
y 5.766 valores en cada serie equity y exposición. Como la primera apertura
no opera señales del warmup, quedan como máximo 5.754 oportunidades de
entrada entre los seis casos. Una oportunidad produce como máximo una
operación cerrada o un rechazo. Los casos no mantienen posiciones abiertas.

La representación de salida del invitado usa floats binarios finitos
serializados por CPython, con hasta 24 bytes por número. Las marcas UTC
horarias de 2022 se emiten con hasta 25 caracteres y sin fracciones. Las
claves de los registros son fijas, los literales de operación están enumerados
y un motivo de rechazo admite hasta 60 caracteres ASCII. Se asignan 1.024
bytes a cada evento y 4.096 a los campos fijos de cada caso, incluidos costes,
métricas y delimitadores. Para un caso de N barras, la cota del JSON es
`4096 + (N - 1) * 1025 + 2 * (N + 1) * 25`. Los máximos por caso son
1.525.321, 777.121 y 802.921 bytes, repetidos para BASE y ADVERSE.

Por caso se añade base64, hasta 4 bytes de redondeo por bloque y hasta 256
bytes de cabecera por manifiesto o bloque. El total máximo, incluida la
cabecera del lote, es **8.332.696 bytes**. El pipe se captura con límite
exclusivo de 8.332.697 y el documento anfitrión con límite exclusivo de
14.255.992 bytes, incluida la copia exacta del flujo en base64. El lector
procesa las líneas en orden y descomprime un bloque a la vez. El anfitrión
conserva la captura completa acotada para sellarla. La memoria del contenedor,
el tmpfs, el CPU, la red y el límite de archivos ordinarios del bootstrap
permanecen fijados. El techo de 512 KiB de 5.5A permanece vigente; se mantiene
en el contrato del piloto como referencia del transporte heredado.

Esta cota cubre la salida serializada válida del invitado, incluso con todos
los bloques sin comprimir. En pruebas, el receptor aceptó el máximo de 5.754
eventos de forma estructural y el auditor rechazó los fills ficticios. Los
límites no garantizan que un resultado numéricamente inválido o un proceso
que agote el tiempo pueda terminar. Esos casos no se publican como COMPLETE.

Se reutilizan el preflight, supervisor Docker, recursos, captura original de
stdout y limpieza de 5.5A. La evidencia terminal queda en un documento NTFS
sellado, con la captura exacta y su hash, diagnóstico de preflight, identidad
del plan y resumen. El documento se sella en el registro antes de publicarse
sin reemplazo. Una interrupción anterior a la publicación queda pendiente. Un
documento existente solo se devuelve si conserva identidad, sello y auditoría.
No se modificaron las huellas ni los contratos de 5.5A.

## Autorización independiente

`HISTORICAL_BACKTEST_ONCE` tiene su propio registro SQLite con identificador de
aplicación y esquema 1. El registro se aprovisiona fuera de scratch y
fuera de las bases operativas, en una raíz NTFS dedicada con ACL de operador.
La preparación, el lanzamiento Codex y el permiso sintético carecen de poder
para reservar un histórico. La fila de ejecución se inserta con
`BEGIN IMMEDIATE` y una clave única que referencia el permiso. La inserción es
a la vez reserva y consumo de un único lote, antes de Docker. El permiso,
su confirmación y las reservas consumidas no se sobrescriben. Los estados
reservados, inciertos o sellados sin documento pasan a revisión del operador.
No hay rearme automático.

La propuesta no concede permiso. La función de autorización posterior exige
terminal interactiva, operador Windows, evidencia del intento original e
identidad del recibo de implementación. La frase incluye propósito, intento
y huella del trabajo completo. La reserva vuelve a cotejar operador e
identidad del piloto; el acceso al expediente viejo es de solo lectura.
El programa de preparación solo expone lectura, propuesta y ensayo sintético.
El lanzamiento histórico independiente se mantiene fuera del comando
de preparación y requiere el permiso persistido y explícito.

El registro y sus ficheros auxiliares SQLite son infraestructura de confianza.
Mantener un único registro operativo designado bajo ACL que impidan a terceros
crear, borrar o sustituir entradas. Una cuenta que controle ambos almacenes
puede falsificar hashes y reservas. No se ha ensayado pérdida de alimentación.
El expediente original y su trigger permanecen intactos.

## Operación de preparación y aceptación nativa

Desde el checkout de la rama local de desarrollo y la sesión habitual de
Windows, con Python de desarrollo y Docker Desktop Linux iniciados:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:TRADING_LAB_VERIFICATION_IMAGE = 'sha256:539a1a6c2f1669b6c36612417f9cf70fe28e822095433d8a1453e706396b5f2e'
$env:TRADING_LAB_55B_DOCKER = '1'
$repoDatos = Read-Host 'Ruta del checkout que contiene el bundle local congelado'
$evidence = Join-Path $env:LOCALAPPDATA ('TL55B-' + [guid]::NewGuid())
python -B scripts/prepare_historical_pilot.py check-data --data-repo $repoDatos
python -B -m pytest -q -ra -p no:cacheprovider --basetemp $evidence tests/unit/test_historical_pilot.py
```

El ensayo nativo exige `COMPLETE`, auditoría de los seis casos, timeout
controlado, limpieza, recibo sellado e idempotencia. Conservar el registro y
scratch. Consultar ACL y comprobar la ausencia de los nombres de contenedores
registrados. Con permisos para leer el expediente de implementación original,
generar en una ubicación privada la propuesta exacta para revisión del operador:

```powershell
$queue = Join-Path $env:LOCALAPPDATA 'TradingLab/GitHubIntake53/queue.sqlite3'
$registry = Read-Host 'Ruta NTFS del registro histórico designado fuera del repositorio'
$private = Join-Path $env:LOCALAPPDATA ('TL55B-proposal-' + [guid]::NewGuid() + '.json')
python -B scripts/prepare_historical_pilot.py proposal --data-repo $repoDatos --coordinator-db $queue --registry $registry |
    Set-Content -LiteralPath $private -Encoding UTF8
if ($LASTEXITCODE -ne 0) { throw 'No se emitió una propuesta válida' }
```

El resultado esperado de ese comando es `PROPOSAL_ONLY`. Se debe usar el
registro histórico designado por el operador para comprobar si un permiso
ya fue consumido. La consulta no crea una SQLite ni concede permiso. En una etapa posterior
y tras aprobación independiente, la frase será
`AUTHORIZE HISTORICAL_BACKTEST_ONCE <attempt_id> <job_sha256>` con los valores
reales de la propuesta revisada. Antes de presentarla comprobar el recibo,
la clausura efectiva, la imagen, las seis ventanas y los límites exactos.
Conservar la propuesta y el SHA-256 fuera del checkout. Cualquier cambio
posterior de huella requiere otra revisión, conservando las reservas existentes.
El transporte 2.0 requiere repetir las dos pruebas nativas 5.5B de Docker.
En la sesión de desarrollo, el proceso no pudo abrir el directorio de trabajo
del piloto para reverificar el recibo y el motor Docker denegó el canal local.
Los ensayos de cálculo y transporte ejecutados por pytest usaron datos
artificiales. Queda pendiente la ejecución nativa en Docker y la generación
de la propuesta nominativa a partir de su expediente verificado.
