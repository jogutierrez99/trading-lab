# Entrega manual de una idea de la investigación de las 9:00

Usa una copia de la [plantilla JSON](../examples/orchestration/research_0900_template.json)
por idea. La plantilla vacía se rechaza deliberadamente. El
[ejemplo válido](../examples/orchestration/manual_valid.json) muestra los tipos y el
nivel de detalle esperados. Ambos siguen el contrato
[HypothesisManifest 1.0](../src/trading_lab_orchestration/contracts.py).

## Del chat a la ficha

1. Extrae una sola hipótesis comprobable y su fundamento. Asigna un
   `hypothesis_id` estable, sin espacios, y una fecha `created_at_utc` en ISO 8601
   con `Z`. Anota la procedencia en `researcher_version` y `source_refs`.
   Identifica el mensaje o informe por fecha y referencia reconocible. Usa
   `UNVERIFIED` para fuentes no comprobadas, sin inventar referencias ni copiar
   credenciales o contenido ajeno a la idea.
2. Especifica activo, marco temporal, horizonte, calentamiento, política de gaps y
   dataset previsto. Si aún no está comprobado, descríbelo en `dataset_refs` y
   marca `PENDING` o `UNVERIFIED` según corresponda.
3. Escribe entradas, salidas y fórmulas con ventanas y unidades explícitas.
   La señal usa información disponible al cierre y la entrada se plantea en
   la siguiente apertura. Para un lado no soportado, pon ambas reglas a
   `null` y añade `LONG_ONLY` o `SHORT_ONLY` a `unsupported_modes`.
   Spot exige excluir `SHORT_ONLY` y usar funding `NOT_APPLICABLE`.
   Synthetic usa `NOT_MODELLED` y perpetual exige `REQUIRED`.
4. Fija los valores de los parámetros y el límite de combinaciones. Con
   `parameters: {}` hay una sola combinación. Documenta runner o protocolo
   previsto, costes, stop, objetivo, tamaño y tratamiento intrabar.
   Usa unidades de porcentaje (`0.05` representa 0,05 %). Si falta una
   decisión necesaria, aclárala con el operador antes de registrar. No
   conviertas costes desconocidos en cero ni unas señales vagas en reglas inventadas.
5. Separa TRAIN, VALIDATION y TEST en intervalos UTC ordenados, disjuntos y con
   fin exclusivo. Declara `UNKNOWN` si desconoces el uso previo del holdout y
   `CONSUMED` si ya se observó. Define métrica, condición de falsación, robustez y
   política de walk-forward. Anota trabajo previo, limitaciones, clase de cómputo y
   si la idea requiere código nuevo. Deja los conteos desconocidos a `null`.
6. Guarda JSON en UTF-8, conserva `schema_version` en `1.0` y `status` en
   `PROPOSED`. Mantén el mismo ID para reenviar la misma ficha. El coordinador
   deduplica la especificación científica exacta, incluso si cambia su título o ID.
   Dos textos distintos pueden describir la misma idea y requerir revisión humana.

## Validar y dejar en cola desde PowerShell

Desde la raíz del repositorio, con el Python del proyecto instalado, copia la
plantilla a una carpeta local y rellénala en un editor antes de continuar.

```powershell
$local = Join-Path $env:LOCALAPPDATA 'TradingLab\research-0900'
New-Item -ItemType Directory -Path $local -Force | Out-Null
$ficha = Join-Path $local "idea-$([guid]::NewGuid().ToString('N')).json"
Copy-Item .\examples\orchestration\research_0900_template.json $ficha
$ficha
```

El bloque siguiente usa una base nueva y aislada. Cuando quieras admitir una
idea en la cola operativa, asigna a `$db` la ruta confirmada del SQLite del
coordinador en disco local, fuera de OneDrive.

```powershell
$db = Join-Path $local "intake-$([guid]::NewGuid().ToString('N')).sqlite3"
python -B scripts/orchestrator.py validate $ficha
if ($LASTEXITCODE -ne 0) { throw 'Corrige la ficha antes de registrarla.' }

$registro = python -B scripts/orchestrator.py --db $db register $ficha
if ($LASTEXITCODE -ne 0) { throw 'Fallo en el registro de la ficha.' }
$alta = $registro | ConvertFrom-Json
$alta
python -B scripts/orchestrator.py --db $db show $alta.task_id
```

`validate` comprueba estructura y coherencia básica. `register` deja la
candidata en `HYPOTHESIS_READY` y su tarea `MANUAL_REVIEW` en `QUEUED`,
con modo `PREPARE_ONLY`. Aquí termina la entrega manual. La revisión de
la idea, sus datos y su viabilidad corresponde a una etapa posterior.
