# Laboratorio local: estrategia → YAML → ejecución → informe

La estrategia define señales; el experimento define datos, mercados, periodos,
parámetros, riesgo/costes y filtros; `lab.py` coordina las capas existentes.
ChatGPT puede proponer un YAML. Codex solo hace falta al cambiar lógica, capacidades
del motor o arquitectura. No hay llamadas a IA, credenciales ni descargas implícitas.

## Primer uso desde PowerShell / VS Code

Desde la raíz del repositorio (Python 3.12 o posterior):

```powershell
# git pull cuando el checkout esté limpio y los cambios estén publicados.
git pull
python -m venv .venv  # Solo si no existe ya.
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python scripts/lab.py strategies
python scripts/lab.py experiments
python scripts/lab.py status
python scripts/lab.py validate trend_btc_1h_001
python scripts/lab.py validate trend_btc_1h_001 --full
# El usuario ejecuta la investigación, no Codex:
python scripts/lab.py run trend_btc_1h_001
python scripts/lab.py report latest
```

Si PowerShell bloquea la activación, usa `.\.venv\Scripts\python.exe` en lugar de
`python`; no necesitas cambiar políticas del sistema. Los comandos encuentran la raíz
desde el módulo instalado editable, independientemente del directorio actual.
`--root <checkout>` va antes del subcomando para utilizar otro directorio.

El ejemplo versionado `configs/experiments/trend_btc_1h_001.yaml` tiene 12 backtests:
dos parámetros × tres periodos × dos costes. No se ha ejecutado en datos históricos
durante esta implementación. Usa un bundle BTC existente, continuo y fijado por hash.
Los datasets están ignorados por Git: una copia nueva del repositorio necesita preparar
los datos con las herramientas existentes, siguiendo `docs/phase-2.md` y
`docs/data-test-2022-jan2023.md`, y fijar la ruta concreta del bundle en el YAML.
Un dataset ausente produce un error; no se descarga ni sustituye silenciosamente.

## Crear otro experimento sin editar Python

```powershell
python scripts/lab.py experiment create trend_eth_4h_002 --from trend_btc_1h_001
code configs/experiments/trend_eth_4h_002.yaml
python scripts/lab.py validate trend_eth_4h_002
python scripts/lab.py run trend_eth_4h_002
python scripts/lab.py report trend_eth_4h_002
```

El generador clona una definición conocida, mantiene sus supuestos y asigna ID y fecha
UTC explícitos. Edita mercados/datos/periodos/parámetros antes de ejecutarla. No genera
configuraciones de datos ficticias. `latest-experiment` ordena por `created_at` UTC y,
en empate, ID lexicográfico. Cambiar mtime no cambia esa selección.

Para ETH 4h, `trend_following` y `mean_reversion` aceptan periodos medidos en **barras**.
Cambiar 1h a 4h cambia la duración física de esos periodos. Ejemplo de mercado con
el bundle existente en este laboratorio (comprueba que el periodo no cruce sus huecos):

```yaml
markets:
  - symbol: ETHUSDT
    timeframe: 4h
    dataset: ../../data/cross_market_timeframe_study_001/ETHUSDT/4h/c528a1e139aa89e5f87c168620b5221067fca4705b01b7a19d24890f7de89477
    warmup_bars: 240
```

No se traducen silenciosamente las estrategias congeladas que usan horas/días. El
catálogo muestra `timeframes`, `modes` y `execution`. Las estrategias long-only rechazan
SHORT_ONLY/LONG_SHORT. MTF V1–V4 y Bollinger Batch 006 requieren sus runners dedicados.
Los bundles admitidos son `history_cache` y `study_data`, siempre con manifiesto y Parquet.
BTCUSDT/ETHUSDT, 1h/4h/1d son los mercados admitidos por el adaptador actual.

## YAML pequeño funcional

Puedes copiar este contenido a `configs/experiments/trend_small.yaml`:

```yaml
experiment_id: trend_small
created_at: 2026-09-27T13:00:00Z
description: Tres periodos de investigación BTC spot.
strategy: {id: trend_following, config: ../profiles/lab_trend.yaml}
markets:
  - symbol: BTCUSDT
    timeframe: 1h
    dataset: ../../data/history/2322037acf66bdb51b4af3bc76c278d0dce85d2bc5bf2d0e8cd97e86d6eac04b
modes: [LONG_ONLY]
strategy_parameters: {donchian_period: [20, 40]}
execution:
  quantity_step: 0.000001
  min_quantity: 0.000001
  min_notional: 10.0
  filter_assumption: Filtros fijos de investigación.
validation:
  train: {start: 2022-02-01T00:00:00Z, end: 2022-04-01T00:00:00Z}
  validation: {start: 2022-04-01T00:00:00Z, end: 2022-05-01T00:00:00Z}
  test: {start: 2022-05-01T00:00:00Z, end: 2022-06-01T00:00:00Z}
```

Las fechas son UTC, sin comillas, para conservar el tipo datetime del YAML estricto.
Las rutas son relativas al YAML del experimento; `app` hereda `../app.yaml`. Los
ficheros de riesgo referenciados por app siguen siendo relativos a app. La configuración
de estrategia debe estar habilitada, coincidir en nombre y versión y declarar parámetros
válidos. Se conserva el YAML antiguo deshabilitado: el ejemplo usa un perfil nuevo.

El capital y los costes heredan app.yaml. El riesgo combina risk.yaml con overrides
explícitos del perfil de estrategia. `initial_cash` y `costs` permiten overrides completos.
Todos los `*_pct` son **porcentajes**: `0.05` significa 0.05%, cinco puntos básicos.
Los grids rechazan nombres desconocidos, tipos/rangos inválidos y combinaciones repetidas.
Se valida el modelo completo por combinación, incluyendo restricciones entre parámetros.

Para cortos, declara ambas cosas:

```yaml
modes: [LONG_ONLY, SHORT_ONLY, LONG_SHORT]
execution:
  market_mode: synthetic
  quantity_step: 0.000001
  min_quantity: 0.000001
  min_notional: 10.0
  filter_assumption: Cortos sintéticos colateralizados, sin funding ni préstamo.
```

La dirección la determina `modes`, no `execution.direction`. No se emulan contratos
perpetuos. Stops ATR, riesgo, exposición, fills, comisiones de ambos lados y liquidación
se delegan a `StudyBackend`, con sus convenciones conservadoras de ambigüedad intrabar.
No hay posiciones que atraviesen periodos. Warmup aporta features pero no operaciones.
Sizing por volatilidad se limita a 1h porque la función existente anualiza horas.

## Walk-forward y costes

Dentro de `validation` puedes añadir:

```yaml
  walk_forward:
    - train: {start: 2022-02-01T00:00:00Z, end: 2022-03-01T00:00:00Z}
      test: {start: 2022-03-01T00:00:00Z, end: 2022-04-01T00:00:00Z}
  cost_stress:
    adverse: {trading_fee_pct: 0.10, slippage_pct: 0.06, spread_pct: 0.02}
```

Cada fold selecciona por la métrica TRAIN/base configurada en `ranking`. Los empates
usan ID determinista; si todas las métricas son indefinidas, el run falla explícitamente.
Solo esa configuración se ejecuta en TEST del fold, con los mismos parámetros en stress.
TEST de distintos folds no puede solaparse y debe terminar antes del holdout final.
Cada fold reinicia capital; las medianas no representan una cartera compuesta.

El grid ordinario conserva resultados de TRAIN, validation y TEST de todas las
configuraciones, ordenadas exclusivamente por TRAIN/base. Consultar y volver a ajustar
usando TEST convierte ese holdout en datos exploratorios; no lo presentes como validación
independiente después de reutilizarlo. No hay búsqueda adaptativa usando resultados futuros.

```yaml
ranking: {metric: sharpe, descending: true, top_n: 10}
filters:
  minimum_trades: 10
  maximum_drawdown_pct: 25.0
  minimum_profit_factor: 1.1
  minimum_sharpe: 0.0
  positive_test: true
  cost_stress_survival: true
```

Estos filtros son declaraciones previas, nunca recalibrados por el programa. Los
umbrales básicos se aplican a cada backtest. Valores indefinidos fallan si existe umbral.
Un superviviente del grid debe aprobar sus tres periodos y todos los escenarios;
walk-forward se informa aparte. PASS no asigna automáticamente estado promising/validated.
Los flags complejos de estudios congelados siguen en sus informes legacy; no se mezclan
con filtros genéricos de significado distinto.

## Validación y preflight

`validate` importa dependencias/registro, revisa schema, capacidades, todas las
combinaciones, costes, identidad y cobertura del manifiesto, warmup y huecos declarados.
No lee las velas ni ejecuta pytest/backtests. Muestra cuántos backtests ejecutaría.

`validate --full` añade SHA256/fingerprint y auditoría OHLCV de datos y segmentos,
incluyendo warmup. `run` repite siempre esas comprobaciones completas para evitar
aceptar un preflight anterior obsoleto; congela código, entorno y todos los defaults.
Los preflights de batches/MTF/refinamiento mantienen sus contratos originales.
Como cambia el hash del código, sus certificaciones antiguas pueden quedar obsoletas;
antes de una nueva ejecución legacy usa el preflight que indique su documentación.

## Resultados y fallos

`results/<experiment_id>/<UTC>-<uuid>/` es nuevo en cada ejecución. Incluye snapshot
original, configuración resuelta de las dependencias YAML, manifests/hashes, versión de
estrategia, hash del código, commit/estado Git, entorno, ledger SQLite, métricas, trades,
equity/exposición y leaderboard. No modifica ningún resultado antiguo.

`report latest` o `report <experiment_id>` muestra las rutas; no vuelve a simular ni
reescribe informes. `status` inspecciona únicamente metadatos de runs, no miles de trades.
Un run sin outcome es INCOMPLETE (activo o interrumpido), nunca COMPLETE por inferencia.
Los fallos conservan los resultados terminados y el error. No hay resume genérico en v1:
corrige la causa y lanza un nuevo run. Los runners legacy mantienen su propio resume.

Pasa `ai_summary.md` a ChatGPT. Contiene identidad, datos, fechas, conteos, ranking TRAIN,
holdouts, WF, stress, contribuciones netas long/short, métricas, filtros y frecuencias de
parámetros entre supervivientes. `metrics.csv` contiene todos los detalles. El resumen
presenta estadísticas descriptivas; no declara ganadores ni rentabilidad futura.

## Integrar una estrategia futura

```powershell
python scripts/create_strategy.py strategy_x_v1
```

El scaffolder existente crea módulo, YAML deshabilitado y test. Implementa el modelo
`Parameters` con rangos, `prepare_features` causal y los cuatro métodos de señales de
`BaseStrategy`; completa pruebas de comportamiento y prefix-invariance. Describe
`description`, `status`, `created_at` UTC explícito, `lab_timeframes` y `lab_modes`.
`lab_execution="ohlcv"` permite usar el adaptador genérico. Estrategias que necesiten
datos externos/estado de ejecución especial requieren un adaptador apropiado; no basta
con anunciar capacidades. No implementes parámetros internos que contradigan `modes`.

Habilita el YAML solo tras implementar los métodos. El registro descubre automáticamente
la clase concreta; no se edita lab.py. Incrementa versión cuando cambien las reglas.

```powershell
python -m pytest tests/unit/test_strategy_x_v1.py
python scripts/lab.py strategies
python scripts/lab.py experiment create strategy_x_001 --from trend_btc_1h_001
# Editar strategy.id/config y parámetros en el YAML clonado.
python scripts/lab.py validate strategy_x_001
python scripts/lab.py run strategy_x_001
```

Las fechas de estrategias históricas desconocidas se muestran null, sin inventarlas a
partir del filesystem. Las futuras se ordenan por fecha explícita e ID. El catálogo no
implica que un scaffold esté habilitado ni que una estrategia sea rentable.

## Compatibilidad y verificación

No se elimina ni depreca ningún runner existente. Consulta `lab-architecture-audit.md`
para las decisiones por capa. El motor, las señales y los artefactos congelados se
preservan; los metadatos de capacidades no cambian las reglas de señal.
No se añaden dependencias, paper trading ni agente autónomo.

Las pruebas nuevas usan bundles sintéticos y cubren discovery, schema, errores, CLI,
latest, hash/corrupción, 1h/4h y long/short, selección causal, filtros, informes, fallo e
inmutabilidad. Verificación dirigida, Ruff y smokes de CLI; no batches históricos.

Verificación de implementación (2026-09-27): 101 tests dirigidos aprobados, incluidos
23 nuevos tests de lab (repetidos tras los últimos ajustes: 23/23). Ruff check y format
check correctos (203 archivos Python); `pip check` sin requisitos rotos. El ejemplo
versionado pasa FAST y FULL, que prevén 12 backtests sin ejecutarlos. `strategies`
descubre 24 implementaciones. `git diff --check` correcto; ningún motor de ejecución,
configuración histórica ni artefacto de resultados fue modificado por este trabajo.

```powershell
python -m pytest tests/unit/test_lab.py tests/unit/test_strategy.py tests/unit/test_config.py tests/integration/test_scaffolding.py tests/regression/test_causality_contract.py tests/regression/test_batch_strategies.py tests/regression/test_execution.py -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
```
