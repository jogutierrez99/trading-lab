# Workflow: Strategy → Experiment → Run → Results

Leer [estado](PROJECT_STATE.md), [arquitectura](ARCHITECTURE.md) y
[reglas](RESEARCH_RULES.md) antes de cambiar investigación. Para campos y ejemplos
YAML completos, usar [lab-workflow.md](lab-workflow.md); no duplicar schemas en Python.

## 1. Elegir el tipo de cambio

| Petición | Capa y procedimiento |
|---|---|
| Nuevas reglas causales de entrada/salida | Strategy, tests y perfil; skill create-strategy |
| Otro activo, timeframe, modo, parámetro o periodo | Experiment YAML; skill create-experiment |
| Otra política 15m/funding/arquitectura V1–V4 | Perfil y protocolo dedicado; no introducir campos ajenos en lab |
| Explicar un run terminado | Lectura de artefactos; skill analyze-results |
| Validar una candidata | Protocolo previo y evidencia temporal; skill validate-strategy |

## 2. Crear una estrategia nueva

IDEA → reglas explícitas → implementación → tests → discovery → experimento → ejecución
local → resultados. Primero inspeccionar una estrategia comparable y `BaseStrategy`.

```powershell
python scripts/create_strategy.py new_strategy
```

Genera `src/quant_lab/strategies/new_strategy.py`, `configs/strategies/new_strategy.yaml`
y `tests/unit/test_new_strategy.py` sin sobrescribir. Implementar el modelo `Parameters`
con `StrictModel`, features causales y cuatro métodos de señales. Los modos no soportados
se declaran en metadata y se prueban; el motor decide ejecución y tamaño. Añadir pruebas
de comportamiento long/short, warmup y prefix-invariance (añadir futuro no cambia pasado).
Declarar `description`, `status`, fecha UTC explícita, `lab_timeframes`, `lab_modes` y
`lab_execution`; no anunciar capacidades que requieren adaptadores inexistentes.

```powershell
python -m pytest tests/unit/test_new_strategy.py tests/regression/test_causality_contract.py -q
python scripts/lab.py strategies
python scripts/lab.py experiment create new_strategy_001 --from trend_btc_1h_001
```

El registro descubre la clase sin editar listas. Completar primero la implementación y
habilitar su YAML; editar `strategy.id/config` y quitar parámetros heredados incompatibles
en el experimento clonado. Las reservas existentes se implementan sin sobrescribirlas.
Versionar cambios de comportamiento y documentar cómo reproducir la revisión anterior.

## 3. Crear un experimento sin modificar señales

```powershell
python scripts/lab.py experiments
python scripts/lab.py experiment create trend_btc_1h_002 --from trend_btc_1h_001
```

Editar el nuevo YAML, sin alterar la definición histórica:

1. Describir hipótesis y fijar ID/fecha. El clon solo actualiza ID y `created_at`.
2. Elegir `strategy.id` y perfil habilitado `strategy.config` con versión exacta.
3. Fijar `markets`: `symbol`, `timeframe`, ruta de dataset inmutable y `warmup_bars`.
4. Definir `modes` compatibles. Para cortos, `execution.market_mode: synthetic`;
   dejar `execution.direction: long` porque lab traduce `modes` internamente.
5. Fijar listas `strategy_parameters`; un solo valor evita un grid innecesario.
6. Declarar train/validation/test UTC, fin exclusivo; warmup anterior suficiente y continuo.
7. Fijar capital/costes o herencia de app; riesgo en perfil de estrategia (nuevo si varía).
8. Declarar ranking TRAIN, filtros, folds y stress antes de observar resultados.

Cambiar 1h a 4h cambia la duración física de ventanas medidas en barras. Comprobar el
catálogo: estrategias horarias no se traducen automáticamente; volatility sizing en lab
es 1h. Un ETH/4h necesita realmente un bundle ETH/4h, no solo un ID de nombre diferente.
No se permite MTF 15m arbitrario en `Experiment`. Trend RSI Pullback declara soporte
15m con fuente mtf_quarters, identidad fijada y tendencia 1h derivada causalmente; ver
[protocolo](trend-rsi-pullback.md). Las demás familias MTF conservan sus runners. No clonar una estrategia por cambiar capital, modo o activo.

## 4. Validar y entregar ejecución local

```powershell
python scripts/lab.py validate trend_btc_1h_002
python scripts/lab.py validate trend_btc_1h_002 --full
# Usuario, cuando quiera ejecutar la investigación:
python scripts/lab.py run trend_btc_1h_002
python scripts/lab.py report trend_btc_1h_002
python scripts/lab.py report latest
python scripts/lab.py status
```

FAST comprueba schema, versiones, parámetros/capacidades, cobertura y huecos declarados;
no lee todas las velas. FULL añade SHA256/fingerprint/OHLCV y segmentos, sin backtests.
Ambos muestran el número previsto de backtests. Un dataset ausente o inválido es bloqueo
explícito: preparar datos mediante las herramientas existentes, no fabricar/sustituirlos.
`run` siempre repite FULL. El ejemplo disponible `trend_btc_1h_001` prevé 12 ejecuciones.

Codex entrega YAML, resultado de validación, supuestos y comando exacto. No ejecutar
batches, barridos o estudios prolongados salvo instrucción específica. Preflights
especializados no son todos rápidos: entry timing reproduce tres casos históricos,
mientras `--technical-only` no autoriza su runner. Consultar el protocolo correspondiente.

Ejemplos especializados (investigación local, con datos y recibos exigidos):

```powershell
python scripts/run_batch_002.py --config configs/profiles/batch_002/batch.yaml
python scripts/preflight_new_mtf_strategies.py
python scripts/run_new_mtf_strategies.py --phase a
python scripts/run_new_mtf_strategies.py --phase analyze
python scripts/run_new_mtf_strategies.py --phase b
```

La fase analyze lee artefactos; A/B simulan. B respeta elegibilidad y hash de A;
repetir un preflight no permite mezclar fuentes de código incompatibles.

## 5. Analizar un run ejecutado

Fijar ruta/run ID antes de analizar: `latest` cambia cuando llegan nuevas ejecuciones.
`report` solo localiza runs lab. En estudios dedicados, seguir plan/manifests hasta
su lote hijo, no interpretar cualquier carpeta como el formato ordinario.

| Leer primero | Pregunta |
|---|---|
| `outcome.json` o `verification.json`, y ledger | ¿Terminó? ¿Cuántas ejecuciones faltan/fallaron? |
| `ai_summary.md` / `summary.md`, `summary.json` | ¿Qué resume y qué limita la evidencia? |
| `plan.json`, snapshot/config/resolved, provenance | ¿Hipótesis, parámetros, periodos, datos, costes, versión y entorno? |
| `metrics.csv`, leaderboard o comparison/results | ¿Mejores y peores según criterio predeclarado? ¿TRAIN frente a holdouts? |
| Folds, holdout, cost sensitivity, clasificación cuando existan | ¿Estabilidad, muestra, costes y reglas satisfechas? |
| `result.json`, trades/equity de casos seleccionados | ¿DD, costes, rechazos o fills anómalos? |

No releer miles de operaciones por defecto. Verificar hashes requeridos por el protocolo;
indicar qué se verificó y qué solo se leyó. Datos ausentes, métricas null y runs parciales
son límites, nunca ceros ni éxito inferido. Si falta outcome lab, estado INCOMPLETE;
para recuperar, corregir la causa y usar `lab.py run ID --resume --check` primero.
Después `lab.py run ID --resume` calcula los pendientes en una continuación nueva;
conservar el run fuente y todos los directorios referenciados en `reuse.json`.
Véase [el contrato de recuperación](lab-workflow.md#resultados-y-fallos).

El `ai_summary.md` automático es un artefacto congelado. Para análisis adicional, crear
`reports/analysis/<experiment-or-study>/<run_id>/<UTC>-<id>/ai_summary.md` en ubicación
nueva. Esta es una convención de documentación, no un comando nuevo. Incluir identidad,
fuentes/hash, hipótesis (o desconocida), datos, periodos, configuración, mejores/peores,
métricas, trades, DD, costes, TRAIN/validation/TEST, estabilidad, robustness, anomalías,
sesgos, conclusiones descriptivas y propuestas separadas de evidencia observada.
Nunca reescribir el resumen original ni relanzar una búsqueda para completar el análisis.

El suplemento de clasificación existente puede generarse sin backtests con
`python scripts/classify_new_mtf_results.py --run 20260927T174926Z-38873feafe95`,
si ese run existe. Escribe otro reporte y comprueba sus entradas; no reaudita cada trade
ni cambia los criterios RESEARCH_PASS/V4.

## 6. Iteración y verificación técnica

Nueva capa ordinaria: `lab.py classify ID` produce un suplemento versionado de gates;
`lab.py compare ID1 ID2` lo incluye cuando existe y coincide por hashes. `lab.py publish ID`
y `publish-comparison ID` preparan compactos en research_results para revisión y Git manual.
La falsación de candidatos explícitos usa `lab.py challenge validate|run ID`, sin grids
ni TEST ficticio. Comandos completos en [research-evidence](research-evidence.md).

RESULTS → ANALYSIS → HYPOTHESIS → NEW EXPERIMENT. Registrar la razón del siguiente
experimento y todos los intentos; no ajustar hasta encontrar rentabilidad ni reutilizar
el holdout observado como evidencia independiente. Asset/timeframe robustness requiere
comparaciones declaradas y compatibles, no elegir retrospectivamente el mejor mercado.

Para cambios ordinarios de orquestación/documentación, grupo dirigido reproducible:

```powershell
python -m pytest tests/unit/test_lab.py tests/unit/test_strategy.py tests/unit/test_config.py tests/integration/test_scaffolding.py tests/regression/test_causality_contract.py tests/regression/test_batch_strategies.py tests/regression/test_execution.py -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
```

La suite completa es `python -m pytest`; para YAML rutinario basta `validate`, con FULL
cuando corresponda verificar datos. No arreglar fallos ajenos al alcance ni ejecutar un
batch histórico como requisito de documentación. Inspeccionar diff y archivos nuevos;
no versionar datos, secretos o resultados. Actualizar PROJECT_STATE solo ante cambios
significativos de capacidades/arquitectura, no por cada run.

## Verificación de esta capa documental (2026-09-28)

Tests before: **101 passed** (19.69 s). Tests after: **101 passed** (13.47 s), usando
el mismo grupo dirigido anterior. Ruff check y format correctos (247 archivos Python),
`pip check` sin dependencias rotas. El ejemplo `trend_btc_1h_001` pasa FAST y FULL:
12 backtests previstos, ninguno ejecutado por esas validaciones. Los tests sí usan sus
fixtures/simulaciones sintéticas pequeñas; no se lanzó investigación histórica.

Las cuatro skills pasan `quick_validate.py` de skill-creator; enlaces locales revisados.
Diff limitado a README, AGENTS, estos cuatro manuales y cuatro SKILL.md. Sin cambios
de Python, YAML de producción, estrategias, datos ni resultados. No se ejecutó la suite
completa ni se volvieron a certificar los estudios históricos.
