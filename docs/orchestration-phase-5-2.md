# Fase 5.2 · Publicación supervisada BTC–ETH Statistical Pairs V1

Estado de preparación `READY_FOR_SUPERVISED_PUBLICATION`. La lectura remota
confirmó que `main`, `origin/main` y el checkout partían de
`211f9aa1abb6370df7e425b59be5a28e78118ab9`, con divergencia 0/0 y árbol
limpio. Se preservaron las ramas y los worktrees existentes.

La [ficha lista para copiar como cuerpo](../examples/orchestration/btc_eth_statistical_pairs_v1.json)
cumple el [esquema 1.0 de fase 5.1](../examples/orchestration/github_strategy_proposal.schema.json).
El hash canónico de propuesta es
`75faba77451972b98667c3012bb1b8ec553a4bed4d9dc0c0df07f63435297ff8`.
La fecha 2026-11-12 y la marca 05:25:32 UTC documentan la preparación
local. El encargo identifica la selección de las 09:00 sin aportar
metadatos verificables de esa ejecución. Una lectura simulada de la ficha
completa devolvió `ACCEPTED` en SQLite aislada. La repetición devolvió
el mismo ID de tarea y el mismo hash.

El [preprint v3](https://arxiv.org/abs/2606.04574v3) analiza selección de
múltiples pares, cointegración y una capa de ejecución PPO-LSTM sobre
Binance USD-M horario. El par BTC–ETH, los umbrales, ventanas y costes
de esta ficha son hipótesis y supuestos de la adaptación local.
La ficha incluye las dos patas, funding, comparadores, walk-forward y
periodos separados. El holdout se mantiene `UNKNOWN` hasta revisar su
posible consumo previo.

`lab_runner.py` ejecuta los mercados individualmente.
`perpetual_execution.py` mantiene una única posición por simulación.
El runner disponible requiere un protocolo dedicado para sincronizar
dos patas, marginar y valorar la cartera conjunta. Al validar la ficha
contra el coordinador, `review_spec` devolvió
`Dedicated perpetual implementation requires a separate reviewed protocol`.
El resultado esperado tras una ingesta real es `ACCEPTED` con revisión
manual pendiente. `PREPARED` queda condicionado a verificar un runner de
pares y revisar su protocolo. El ensayo preserva el mercado `perpetual`
y los dos contratos de la hipótesis.

## Permisos y publicación

El conector de esta sesión respondió como `jogutierrez99`, ID `64194024`.
La búsqueda en lectura no devolvió coincidencias para el ID de estrategia
ni Issues con `strategy-intake` en el repositorio. Eso deja pendiente
confirmar la existencia de la etiqueta. También queda por comprobar en
la tarea de las 09:00 el acceso al esquema y la ficha, las acciones de
búsqueda y creación, la identidad efectiva y la aprobación de escritura.
Usa el [texto exacto de la prueba](orchestration-phase-5-2-task-0900.md)
en la tarea existente cuando corresponda. La sesión actual y una tarea
programada pueden tener permisos diferentes.
[Tareas de ChatGPT](https://learn.chatgpt.com/docs/automations)
· [Controles de acciones](https://learn.chatgpt.com/docs/dots/controls)

El publicador necesita acceso al repositorio, `Issues: write` y un rol
capaz de aplicar la etiqueta. GitHub puede omitir etiquetas al crear un
Issue si la cuenta no tiene el acceso necesario. El consumidor necesita
un token restringido al repositorio con `Issues: read`, disponible como
`TRADING_LAB_GITHUB_TOKEN`. La variable y su entrada local estaban ausentes
en esta sesión. Comprueba primero el permiso de lectura y la etiqueta
preexistente. Con un token ya configurado en PowerShell, la consulta de
la etiqueta es de solo lectura.
[GitHub Issues](https://docs.github.com/en/rest/issues/issues#create-an-issue)
· [GitHub Labels](https://docs.github.com/en/rest/issues/labels#get-a-label)

```powershell
$headers = @{
    Authorization = 'Bearer ' + $env:TRADING_LAB_GITHUB_TOKEN
    Accept = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
}
Invoke-RestMethod -Headers $headers -Uri 'https://api.github.com/repos/jogutierrez99/trading-lab/labels/strategy-intake' |
    Select-Object name
```

Tras la autorización de publicación, usa el título del texto preparado,
la etiqueta y el archivo JSON completo en un solo Issue. Si la tarea no
puede publicarlo, el operador puede copiar el mismo borrador en la
interfaz de GitHub. Vuelve a leer el Issue para confirmar autor, etiqueta
y contenido efectivo. Conserva su enlace y solicita la autorización
separada para procesarlo.

## Procesamiento tras la segunda autorización

Desde PowerShell en la raíz. Usa el número real del Issue y un directorio
local nuevo. `--issue` limita la lectura al Issue aprobado. La CLI
anterior solo ofrecía el barrido de todos los Issues abiertos con la
etiqueta. La nueva opción reutiliza el transporte, los reintentos y los
controles de la fase 5.1.

```powershell
$py = '.\.venv\Scripts\python.exe'
$issue = [int](Read-Host 'Número del Issue aprobado')
$root = Join-Path $env:LOCALAPPDATA 'TLGitHubSmoke52'
$db = Join-Path $root 'queue.sqlite3'
& $py -B scripts/github_strategy_intake.py --db $db poll --author-id 64194024 --live-read --issue $issue
& $py -B scripts/github_strategy_intake.py --db $db show --issue $issue
& $py -B scripts/github_strategy_intake.py --db $db poll --author-id 64194024 --live-read --issue $issue
```

Comprueba `source_mode: GITHUB`, el hash revisado, el autor efectivo y
la repetición del ID de tarea. Detén esta propuesta en revisión manual
mientras esté pendiente el protocolo de dos patas. La preparación de un
protocolo compatible seguiría usando el plan local, el hash revisado y
el ledger canónico en lectura. La consulta del ledger en esta fase
mostró 19,90 EUR disponibles y cero reservas pendientes. TLF1UA07 conserva
el aviso `notice_268d85c3d7394ecab999979a7654b586` en `DRAFT`, con cero
intentos.
