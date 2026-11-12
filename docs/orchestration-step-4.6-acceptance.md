# Aceptación final del 4.6 en Windows

La aceptación técnica final se completó en Windows el 5 de noviembre de 2026.
Una única orden autorizada en PowerShell llegó a `NOTICE_PREPARED` con código 0
en el primer intento real, con cero reparaciones y `operator_resume_used=false`.
El run `20261105T193241Z-dd5fe4efd45a` completó seis casos válidos. BTC cerró seis
operaciones en cada segmento y ETH cerró cero. Se comprobaron las tres identidades
Windows, 12 hashes de etapa, el dictamen `NO_DECISION` y el aviso `DRAFT` con cero envíos.
La consulta de verificación conservó los bytes de ambas bases y ambos presupuestos
históricos de 3/3. [Comprobante de la ejecución real](C:/Users/joshu/.codex/visualizations/2026/11/03/01a1a33b-ea60-7a40-aae1-de15594f5f85/step46-final-real-verification.json)

En Windows pasaron 21 pruebas unitarias y las 10 integraciones del circuito completo.
El diagnóstico local devolvió `LOCAL_PREFLIGHT_OK`. El ensayo simulado usó SQLite v7,
registró las tres identidades nativas, produjo `NOTICE_PREPARED` y dejó `DRAFT` con
cero intentos. Ruff, formato, dependencias y `git diff --check` pasaron. Coinciden
los bytes de la base operativa v6, los dos presupuestos 3/3, los hashes de 140 JSON
archivados del 4.6 y los de 333 archivos de motor y configuración.

La ficha `c46_pair_final` usa la hipótesis `technical_circuit_pair_final_001` y el
target `integration_candle_pair_v1`. La entrada exige dos velas alcistas contiguas
precedidas por una no alcista, con dos intervalos exactos de una hora. La salida es
el primer cierre no alcista. El oráculo comprueba estas reglas sobre el índice UTC,
incluidos gaps, warmup, alineación, ausencia de cortos e invariancia por prefijos.
El perfil operativo entregado debe estar deshabilitado. El runner usa su copia aislada.

La ficha tiene un intento inicial y hasta dos reparaciones técnicas automáticas.
Reutiliza el coordinador, ejecutor, auditoría `DETERMINISTIC_ONLY` y outbox en preview.
Usa 328 velas artificiales, con tres segmentos de 48h por activo y warmup de 20h.
BTC debe cerrar operaciones en cada segmento y ETH debe cerrar cero. El ensayo
simulado obtuvo seis operaciones por segmento BTC y cero por segmento ETH.
El límite del runner es 120s y el de cada intento de implementación es 300s.
La aceptación es técnica y mantiene el dictamen económico `NO_DECISION`.

## Orden de PowerShell usada para la aceptación

El bloque se conserva para reproducir el procedimiento con un destino nuevo. El
destino de esta aceptación ya contiene el expediente final. Se usa una base dedicada
fuera de OneDrive que se crea en v7 al arrancar. La CLI exige `--db` explícito y
rechaza v6 antes de abrirla para escritura. El diagnóstico comprueba rutas, ficha
y ejecutable. La comprobación de autenticación ocurre al arrancar el circuito.

```powershell
$repo = 'C:\Users\joshu\OneDrive\Escritorio\WEBS\Back_testing\trading-lab'
$root = 'C:\Users\joshu\AppData\Local\TL46Final'
$db = Join-Path $root 'state\acceptance.sqlite3'
$out = Join-Path $root 'evidence'
$card = Join-Path $repo 'examples\orchestration\circuit46_acceptance.json'
$cli = Join-Path $repo 'scripts\orchestrator.py'
$codex = 'C:\Users\joshu\AppData\Local\OpenAI\Codex\bin\a159911ff70742e9\codex.exe'
Set-Location -LiteralPath $repo

python -B $cli --db $db circuit-doctor $card --repo $repo --artifacts $out --codex-executable $codex
if ($LASTEXITCODE -ne 0) { throw 'Diagnóstico bloqueado. Conserva la salida.' }

New-Item -ItemType Directory -Path $root -Force | Out-Null
$log = Join-Path $root ('launch-' + [guid]::NewGuid().ToString('N') + '.log')
# Única orden de arranque real
python -u -B $cli --db $db circuit-run $card --repo $repo --artifacts $out --codex-executable $codex 2>&1 | Tee-Object -FilePath $log
$exitCode = $LASTEXITCODE
Write-Output "Exit=$exitCode  Log=$log" | Tee-Object -FilePath $log -Append
```

El diagnóstico debe devolver `LOCAL_PREFLIGHT_OK`. Si Codex se actualiza y la ruta
de su binario cambia, resuélvela antes del diagnóstico y usa el mismo ejecutable
durante el recorrido. El proceso hijo usa `workspace-write` con aprobación `never`.

## Resultado y evidencias

Consulta el estado desde la misma consola una vez terminado el comando de arranque.
La consulta verifica los hashes de los recibos de etapa y mantiene SQLite en solo lectura.

```powershell
python -B $cli --db $db circuit-show c46_pair_final
```

Para aceptar un recorrido continuo deben coincidir código 0, `NOTICE_PREPARED`,
`simulated=0` y `operator_resume_used=false`. Conserva el log original y los recibos
bajo `$out\c46_pair_final`. Revisa estas evidencias del mismo expediente.

- `model_run_*` y el recibo de implementación enlazan la entrega verificada con su
  intento. Cada intento permanece registrado y el número total queda entre 1 y 3.
- `process_identity_*` conserva PID y `created` para modelo, comprobación nativa y
  runner, con reloj `WINDOWS_FILETIME_100NS`. El coordinador compara las identidades
  nativa y del runner con sus filas SQLite y valida los recibos antes de preparar el aviso.
- `coverage_*` acredita seis backtests sintéticos válidos y la matriz BTC con operaciones
  y ETH sin ellas. El recibo de ejecución contiene `run_id` y hashes de los artefactos.
- El recibo de auditoría debe indicar `DETERMINISTIC_ONLY`, `model_executed=false`
  y `NO_DECISION`. `preview` debe estar en `DRAFT` con cero intentos y `message_id=null`.

Si el arranque acaba en `BLOCKED`, `UNCERTAIN` o con código distinto de 0, registra ese resultado y conserva
el log, SQLite y el árbol de evidencias. Una reanudación explícita queda sellada
en `operator_resume_*`. Si termina después de ella, clasifica el resultado como
recuperado. No reinicies el presupuesto ni reutilices el destino para otro ensayo.
La aceptación usa datos sintéticos y mantiene Telegram en vista previa. OKX queda
fuera del circuito. La base operativa v6 y los dos expedientes 3/3 se consultan por separado.
