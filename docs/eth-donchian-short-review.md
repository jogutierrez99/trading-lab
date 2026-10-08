# ETH Donchian + ATR SHORT: revisión y preregistro prospectivo

Revisión acotada de evidencia **ya observada**, sin nueva selección ni simulaciones.
La herramienta `scripts/review_eth_donchian_short.py` valida el protocolo y audita
72 registros históricos y24 TEST recientes. `--full` comprueba además el dataset
congelado, sin descargar datos ni ejecutar backtests. Los demás diagnósticos recientes
reutilizan la publicación con hashes verificados; sus ledgers no se reauditan aquí.

Fuentes fijadas:

- Informe histórico local `reports/eth-short-history/20261008T184034Z-7804ae2eafb6/`.
- Publicación reciente `research_results/trend_expansion/eth_short_regime/20261007T203824Z-364120f09438/`.
- [Protocolo histórico anterior](eth-short-historical-falsification-v1.md), conservado.
- [Preregistro estricto](../configs/research/eth_donchian_short_prospective_v1.yaml):
  seis variantes intactas, futuro desde2026-10-09 como límite inferior; comienzo
  efectivo solo tras aceptar el adaptador y congelar la sesión. No backfill prospectivo.

El preregistro es configuración de investigación, **no una configuración forward**.
Se niega a aceptar flags de órdenes, otros modos o umbrales relajados. Sus hashes
congelan evidencia, criterios y documentación técnica; un cambio exige nuevo protocolo.
Futuras pruebas estadísticas se especifican, pero no se ejecutan ni implementan aquí.

[Conclusiones y criterios](eth-donchian-short-review/conclusions.md),
[adaptaciones forward pendientes](eth-donchian-short-review/forward_readiness.md) y
[viabilidad de cartera](eth-donchian-short-review/portfolio_compatibility.md).

`report` crea exclusivamente otra carpeta compacta en
`research_results/trend_expansion/eth_donchian_short_review/<UTC-id>/` mediante la
allowlist de publicación existente. No sobrescribe informes ni commits. Conserva
IDs, parámetros, hashes, commits/estado Git original y actual, entorno y provenance.
No publica datasets, equity ni ledgers. Los nombres exportados son summary.csv,
historical_evidence.csv, parameter_robustness.csv, cost_sensitivity.csv,
outlier_dependency.csv, regime_comparison.csv, candidate_verdicts.csv,
forward_readiness.md, portfolio_compatibility.md, conclusions.md, sources.json,
prospective_protocol.yaml y metadata.json.

La mediana regional no es una cartera. Las4720 instancias auditadas están duplicadas
entre variantes/escenarios: no son4720 observaciones independientes. Etiquetas nuevas
son descriptivas; no modifican los gates ni conceden elegibilidad paper/live.

## Comandos desde la raíz, Windows

Validación técnica y regeneración ligera de comparativas, sin backtests:

```powershell
.venv\Scripts\python.exe scripts/review_eth_donchian_short.py validate --full
.venv\Scripts\python.exe scripts/review_eth_donchian_short.py report --full
```

El segundo comando imprime la carpeta nueva exacta. Para revisar la entrega más
reciente en PowerShell (guardar la ruta si se requiere una referencia inmutable):

```powershell
$reviewDir = Get-ChildItem research_results/trend_expansion/eth_donchian_short_review -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'metadata.json') } | Sort-Object Name | Select-Object -Last 1
Get-Content (Join-Path $reviewDir.FullName 'conclusions.md')
Import-Csv (Join-Path $reviewDir.FullName 'candidate_verdicts.csv') | Format-Table
```

QA dirigida:

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_eth_donchian_review.py tests/unit/test_donchian_atr_breakout.py tests/unit/test_atr_volatility_breakout.py tests/regression/test_execution.py -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
git diff --check
```

Comparativa original opcional, también sin simulación:

```powershell
.venv\Scripts\python.exe scripts/lab.py eth-short-history compare --runs 20261008T183830Z-e0ff782ccb9f 20261008T183843Z-788bbf8b61dc
```

No hace falta repetir experimentos costosos para esta revisión. Si deliberadamente
se quiere reproducir el histórico, cada comando siguiente crea36 backtests nuevos
(72 total), conserva los originales y debe ejecutarlo localmente el usuario:

```powershell
.venv\Scripts\python.exe scripts/lab.py eth-short-history run eth_short_historical_falsification_v1_atr
.venv\Scripts\python.exe scripts/lab.py eth-short-history run eth_short_historical_falsification_v1_donchian_atr
```

No existe comando aceptado para iniciar Donchian SIGNAL_ONLY ni consultar sus
señales/shadow PnL: falta el adaptador con SL/TP, sizing, persistencia y aislamiento
específicos. Los comandos RMM existentes no certifican Donchian y no se arrancan aquí.
