# Conciliación OpenAI bajo demanda

El investigador y el auditor comparten `api_calls` y el techo global de 20 €/mes.
Un recibo con tokens deja el asiento `UNKNOWN` hasta acreditar el cargo. El
diagnóstico de facturación es de solo lectura. La conciliación vuelve a evaluar
la evidencia y usa la transacción del ledger para registrar el importe y liberar
el sobrante una sola vez. `ALREADY_SETTLED` libera cero céntimos. El comando
manual `api-budget-reconcile` sigue disponible para justificantes individuales
verificados por el operador.

## CSV y costes agrupados

Usa exportaciones **Usage de completions** y **Cost** del mismo ámbito y día UTC,
sin filtros distintos entre ambos. Agrupa uso por modelo y nivel de servicio.
Con `--project-id`, ambos CSV deben incluir `project_id` en todas las filas con
datos. Sin ese argumento, el ámbito es el conjunto completo de ambos CSV. El
conciliador exige que el número de peticiones y los totales de tokens coincidan
con los recibos OpenAI del ledger de ese día. Las llamadas del ledger deben
pertenecer al ámbito indicado. Una llamada sin uso verificable, más de una
pendiente en el día o consumo externo sin identificar detienen la atribución.

- Para una única llamada de texto Standard sin caché, se aceptan dos líneas
  monetarias separadas de entrada y salida con cantidades facturadas que coincidan
  exactamente con el recibo. Las cantidades pueden estar en tokens o miles de tokens.
- Para el perfil reducido de GPT-4o mini Standard sin caché se admite un total
  agrupado con `--exclusive-billing-scope`. Úsalo solo si el ámbito facturado
  contiene exclusivamente las llamadas comprobadas, sin cargos externos. Si hay
  llamadas previas ese día, se requieren los dos CSV anteriores a la llamada
  pendiente. El uso anterior debe cuadrar con los asientos ya conciliados y el
  SHA-256 de Cost anterior debe constar en una de sus conciliaciones. Se resta
  ese total facturado del nuevo. El residual debe coincidir exactamente con la
  tarifa publicada de 0,15 USD/M de entrada y 0,60 USD/M de salida. El cálculo
  de tokens verifica la atribución. La cifra que se contabiliza procede de Cost.
  [Tarifa del perfil](https://developers.openai.com/api/docs/models/gpt-4o-mini)

El asiento conserva fuentes y hashes, ámbito, día UTC, llamadas contrastadas,
cargo USD, conversión conservadora y redondeo hacia arriba a céntimos. Si falta
alguna cifra, el gasto sigue `UNKNOWN` y el CLI devuelve `BLOCKED` con código 2.
Vuelve a consultar tras publicar OpenAI ambos datos. Si siguen agregados de forma
ambigua, obtén un desglose o exporta un ámbito que se pueda contrastar. No hay
sondeo automático ni plazo de publicación garantizado por el coordinador.

Desde PowerShell en la raíz, para el asiento real pendiente y una exportación
futura que incluya la cuarta llamada del 6 de noviembre UTC:

```powershell
$py = '.\.venv\Scripts\python.exe'
$ledger = 'C:\Users\joshu\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\TL42\964b59\orchestrator.sqlite3'
$env:TRADING_LAB_GLOBAL_API_DB = $ledger
$call = 'call_c5e2fa7c3c0e480989adf82757ec050c'
$usage = 'C:\RUTA\completions_usage_actualizado.csv'
$costs = 'C:\RUTA\cost_actualizado.csv'
$downloads = 'C:\Users\joshu\Downloads'
$priorUsage = Join-Path $downloads 'completions_usage_2026-10-07_2026-11-06 (2).csv'
$priorCosts = Join-Path $downloads 'cost_2026-10-07_2026-11-06 (2).csv'
$evidence = @($call, '--usage-csv', $usage, '--costs-csv', $costs,
    '--prior-usage-csv', $priorUsage, '--prior-costs-csv', $priorCosts,
    '--exclusive-billing-scope')
& $py -B scripts/orchestrator.py --db $ledger api-budget-billing-doctor @evidence
& $py -B scripts/orchestrator.py --db $ledger api-budget-billing-reconcile @evidence
```

## API de organización

Usage de completions permite intervalos de minuto, hora o día y agrupar por
proyecto, modelo, clave y nivel de servicio, entre otros. Costs ofrece intervalos
diarios y puede agrupar por proyecto, clave y concepto. Sus agregados carecen de
un identificador de petición que permita cruzarlos directamente con el recibo.
[Usage](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/completions) ·
[Costs](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)

La vía `--admin --project-id` usa exclusivamente dos `GET` de organización y
solicita el día UTC de la llamada, agrupado por proyecto, modelo y nivel de servicio
para Usage, y por proyecto y concepto para Costs. Guarda el hash de cada respuesta
y sus parámetros. Requiere `OPENAI_ADMIN_KEY` en el entorno del operador, con
acceso a ambos endpoints de lectura de la organización. OpenAI documenta una
credencial Admin separada para estos endpoints. No está configurada en este
entorno. El adaptador se probó con respuestas simuladas. Para CSV, el operador
necesita acceso de lectura y exportación de Usage en el panel.
[Credencial Admin](https://developers.openai.com/api/reference/cli) ·
[Permisos](https://developers.openai.com/api/docs/guides/rbac)

```powershell
$project = 'proj_ID_DEL_AMBITO_FACTURADO'
& $py -B scripts/orchestrator.py --db $ledger api-budget-billing-doctor $call --admin --project-id $project
& $py -B scripts/orchestrator.py --db $ledger api-budget-billing-reconcile $call --admin --project-id $project
```

El auditor puede continuar en la misma sesión cuando el ledger confirma la
conciliación y no quedan otras reservas pendientes. Si Cost va por detrás de
Usage o no permite atribuir el cargo, el auditor conserva el bloqueo global.
