# Quant Trading Lab

Laboratorio modular de investigación cuantitativa con datos históricos públicos de
Binance. Separa estrategias, configuración experimental, simulación y análisis para
repetir hipótesis con datos, costes y versiones identificables. Un backtest describe
el pasado: no demuestra rentabilidad futura ni preparación para producción.
No hay órdenes reales, retiradas ni paper trading operativo.

La infraestructura [forward SIGNAL_ONLY para OKX EU demo](docs/forward-signal-only.md)
registra señales e intents hipotéticos, sin enviar órdenes. Incluye runner, preflight,
conectividad de lectura y persistencia. Check público REST verificado; cuenta privada
y WebSocket real pendientes. DEMO_EXECUTION y live continúan bloqueados.
ETH 1h/15m son obligatorios para V1; BTC y 4h son monitorización. La vela histórica
ETH 4h no confirmada se registra como aviso, sin rellenarla ni bloquear estas variantes.

## Telegram notifications

El [watcher Telegram](docs/telegram-notifications.md) es un proceso separado que lee
el journal forward en modo READ ONLY. No ejecuta operaciones; el forward continúa
aunque Telegram falle. Configurar `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` y
`TELEGRAM_NOTIFICATIONS_ENABLED=true` en el `.env` de la raíz del proyecto.
El watcher lo carga al arrancar; las variables exportadas en la terminal tienen prioridad.

```powershell
python scripts/notification_watcher.py
# Previsualización sin Telegram ni cambios del cursor:
python scripts/notification_watcher.py --dry-run --replay-last 3 --once
```

El primer arranque omite histórico; los reinicios retoman el cursor persistido aparte.
La guía documenta reintentos, fallos y límites de entrega/deduplicación.

## Guía de lectura

| Documento | Uso |
|---|---|
| [PROJECT_STATE](docs/PROJECT_STATE.md) | Capacidades, datos, estrategias y límites actuales |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Capas técnicas, persistencia y trazabilidad |
| [WORKFLOW](docs/WORKFLOW.md) | Strategy → Experiment → Run → Results |
| [RESEARCH_RULES](docs/RESEARCH_RULES.md) | Causalidad, holdouts y clasificación de evidencia |
| [AGENTS](AGENTS.md) | Contrato operativo para agentes |
| [Manual detallado de lab.py](docs/lab-workflow.md) | YAML, ejemplos y opciones |

Las notas de fases y protocolos históricos se conservan: sus límites describen su
fecha y runner, no todas las capacidades actuales.

## Instalación y comprobación

Python 3.12 o posterior, desde la raíz del repositorio:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python scripts/lab.py --help
python scripts/lab.py strategies
python scripts/lab.py experiments
python scripts/lab.py status
python -m pytest tests/unit/test_config.py tests/unit/test_strategy.py tests/unit/test_lab.py -q
```

Si PowerShell bloquea la activación, usa `.\.venv\Scripts\python.exe` en lugar de
`python`. En macOS/Linux: `source .venv/bin/activate`. El install editable permite
importar el paquete `src`. Para gráficos especializados instala `.[dev,reports]`.
No hacen falta `.env` ni credenciales privadas; imports y catálogo no descargan datos.

## Estructura real

```text
trading-lab/
├── src/quant_lab/            configuración, datos, motores, métricas, runners
│   ├── strategies/          BaseStrategy, registro y 29 implementaciones
│   ├── execution_policies/  políticas de timing separadas de señales
│   └── lab_*.py             schema, datos, CLI, orquestación y reporting ordinario
├── scripts/                 entrypoints; lab.py vive aquí
├── configs/
│   ├── app.yaml             capital, costes, seed y referencias compartidas
│   ├── risk.yaml            riesgo global
│   ├── markets.yaml         catálogo configurado, no inventario de descargas
│   ├── strategies/          perfiles de estrategia y reservas deshabilitadas
│   ├── experiments/         definiciones YAML ordinarias
│   └── profiles/            perfiles históricos y protocolos especializados
├── data/                    fuentes, bundles y manifests locales (ignorado)
├── results/                 runs únicos y operaciones (ignorado)
├── reports/                 preflights, auditorías y suplementos (ignorado)
├── tests/                   unit, integration y regression
├── docs/                    manuales actuales y protocolos históricos
└── skills/                  cuatro SKILL.md enrutadas desde AGENTS.md
```

La CLI general usa `StudyBackend v1`, no VectorBT. Los runners especializados
conservan motores de referencia, perpetuos/funding y MTF propios.

## Conceptos fundamentales

**Strategy**: lógica reutilizable de features, entradas y salidas long/short.
`BaseStrategy` produce decisiones al cierre; riesgo, fills y estado de ejecución
pertenecen a otras capas.

**Experiment**: configuración concreta de una hipótesis: estrategia y versión,
activo, timeframe, dataset, modo, parámetros, periodos, costes, capital y filtros.
Cambiar BTC por ETH o parámetros normalmente requiere otro YAML, no otra clase.
Las capacidades reales de estrategia/backend limitan las combinaciones admitidas.

**Run**: ejecución identificada por UTC + UUID con configuración, datos, código y
entorno congelados. Puede contener varios backtests. La tabla histórica SQLite
`experiments` identifica backtests individuales; no equivale a los YAML de experimentos.

**Batch / Study**: protocolo especializado con matrices, cohortes, selección,
walk-forward, benchmarks o diagnósticos. Puede tener varios runs hijos; no es un alias
de un experimento ordinario ni comparte todas sus opciones.

## Crear y ejecutar un experimento

Clasificación escalonada sin rerun, challenge ETH de tres candidatos congelados y
publicación compacta a Git: [research-evidence](docs/research-evidence.md).
`lab.py classify ID` conserva PASS legacy; `lab.py publish ID` escribe únicamente
el cuaderno [research_results](research_results/README.md), sin commit/push.
El nuevo challenge usa `lab.py challenge validate|run ID` y no llama TEST a su historia.

```powershell
python scripts/lab.py experiment create trend_btc_1h_002 --from trend_btc_1h_001
# Editar configs/experiments/trend_btc_1h_002.yaml antes de ejecutarlo.
python scripts/lab.py validate trend_btc_1h_002
python scripts/lab.py validate trend_btc_1h_002 --full
# Investigación local, ejecutada por el usuario:
python scripts/lab.py run trend_btc_1h_002
python scripts/lab.py report trend_btc_1h_002
```

Clonar cambia ID y fecha UTC, conserva los demás supuestos. Cambiar el nombre no
cambia el activo. `validate` comprueba schema, capacidades, grids y manifiestos;
`--full` verifica además bytes, fingerprints y OHLCV. Ninguno simula backtests.
`run` repite FULL antes de simular.

Para recuperar una ejecución interrumpida: `python scripts/lab.py run ID --resume --check`
audita sin simular; `python scripts/lab.py run ID --resume` reutiliza los resultados
verificados y calcula los pendientes en otra carpeta. Conserva las carpetas originales:
`reuse.json` las referencia sin duplicar equity. [Contrato y límites](docs/lab-workflow.md#resultados-y-fallos).

El ejemplo existente se ejecuta con `python scripts/lab.py run trend_btc_1h_001`:
12 backtests, dos configuraciones × tres periodos × dos costes. Un clon nuevo no
incluye datos ni resultados: prepara un bundle válido siguiendo [Phase 2](docs/phase-2.md)
o [CSV import](docs/csv-import.md) y fija su ruta en el YAML. No hay descarga ni
sustitución implícita. La solicitud spot continua 2022–2025 sigue bloqueada por huecos;
los bundles independientes no los rellenan.

Comandos: `strategies`, `experiments`, `status`, `experiment create ID --from ID`,
`validate ID [--full]`, `run ID`, `report ID`. `latest-experiment` selecciona por
`created_at` e ID, no mtime; `report latest` selecciona el último run ordinario.
`--root PATH` va antes del subcomando. `report` muestra rutas sin recalcular informes.

## Configuración y límites

Lab admite BTCUSDT/ETHUSDT y 1h/4h/1d, restringidos además por estrategia.
La familia [Trend RSI Pullback](docs/trend-rsi-pullback.md) añade 15m con fuente
`mtf_quarters` explícita y variantes de tendencia 15m/1h completamente cerrada. Spot exige
`LONG_ONLY`; `SHORT_ONLY`/`LONG_SHORT` requieren `market_mode: synthetic` y una
estrategia compatible. Los cortos sintéticos no modelan préstamo ni funding.
Perpetuos y timing 15m usan protocolos dedicados, no claves MTF inventadas en lab.

Rutas experimentales: relativas al YAML. Referencias de app: relativas a `app.yaml`.
El riesgo explícito del perfil prevalece sobre `risk.yaml`; capital/costes del
experimento prevalecen sobre app. YAML rechaza claves duplicadas, campos desconocidos
y parámetros inválidos. `*_pct` son porcentajes: `0.05 = 0.05% = 5 bps`.
Fechas UTC, fin exclusivo; ejemplos YAML con timestamps sin comillas.

Warmup aporta features, no operaciones. Señal al cierre, entrada como pronto en
la siguiente apertura. TRAIN selecciona parámetros; reutilizar TEST para ajustar
convierte ese holdout en evidencia exploratoria. Véanse las [reglas](docs/RESEARCH_RULES.md).

## Resultados

Cada run ordinario crea `results/<experiment_id>/<UTC>-<uuid>/`:

- `run.json`, `outcome.json`: identidad y estado; sin outcome, ejecución incompleta.
- `experiment_snapshot.yaml`, `resolved.json`: configuración original y resuelta.
- `provenance.json`, `environment.json`, `plan.json`: código, entorno y plan.
- `ledger.sqlite`: ciclo de vida y hashes por backtest.
- `metrics.csv`, `leaderboard.csv`, `summary.json`: resultados y filtros; ranking TRAIN/base.
- `summary.md`, `ai_summary.md`: síntesis local, sin llamadas a modelos.
- `<backtest_id>/metadata.json`, `result.json`, `equity.parquet`: detalle de ejecución.

Empieza por estado y resumen; contrasta después métricas, configuración y operaciones
seleccionadas. No sobrescribas runs ni conviertas PASS en robustez. Los estudios
históricos conservan sus formatos. [WORKFLOW](docs/WORKFLOW.md) explica el análisis.

## Añadir una estrategia y verificar

```powershell
python scripts/create_strategy.py new_strategy
```

Crea módulo, YAML deshabilitado y test sin sobrescribir. Implementa `Parameters`,
`prepare_features` y cuatro métodos de señales; añade pruebas causales y de comportamiento.
El registro descubre clases locales: no se edita `lab.py`. Habilita el perfil tras
implementar sus reglas. Incrementa versión al cambiar comportamiento; el registro V1
admite una implementación por nombre y versiones antiguas requieren su revisión Git.
No crear detectores CME a partir de velas Binance.

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m pip check
```

Para documentación/YAML, usa verificación dirigida según [WORKFLOW](docs/WORKFLOW.md).
Codex implementa y comprueba; el usuario lanza estudios largos localmente.
Las [cuatro skills](AGENTS.md#skills-del-repositorio) guían implementación, configuración,
análisis seleccionado y validación sin orquestación multiagente.

## Protocolos conservados

| Línea | Documentación y entrypoint |
|---|---|
| Fundamentos/datos | [Phase 1](docs/phase-1.md), [Phase 2](docs/phase-2.md), [prueba alternativa](docs/data-test-2022-jan2023.md) |
| Batch 001A | [Implementación](docs/batch-001-implementation.md), [resultados](docs/batch-001-results.md); `scripts/run_batch.py` |
| Batch 002 | [Diseño](docs/batch-002-design.md), [resultados](docs/batch-002-results.md); `scripts/run_batch_002.py` |
| Batch 003–005 | [003](docs/batch-003-protocol.md), [004](docs/batch-004-protocol.md), [005](docs/batch-005-protocol.md); scripts `run_batch_003.py`, `run_batch_004.py`, `run_batch_005.py` |
| Cross-market | [Estudio](docs/cross-market-timeframe-study-001.md), [traducciones](docs/cross-market-timeframe-translation.md), [resultados](docs/cross-market-timeframe-study-001-results.md); `scripts/run_cross_market_study.py` |
| Batch 006 | [Diseño](docs/batch-006-design.md), [resultados](docs/batch-006-results.md); `scripts/run_batch_006.py` |
| Serie MTF | [Diseño](docs/mtf-series-design.md), [resultados](docs/mtf-series-results.md); `scripts/run_mtf_series.py` |
| Refinamiento | [Diseño](docs/execution-refinement-design.md), [resultados](docs/execution-refinement-results.md); `scripts/run_execution_refinement.py` |
| Nuevas MTF | [Protocolo y clasificación](docs/new-mtf-strategies.md); `scripts/run_new_mtf_strategies.py` |
| Timing 15m | [Protocolo](docs/entry-timing-15m.md); `scripts/run_entry_timing_15m.py` |

Consulta cada protocolo para argumentos, datos fijados y preflight. Algunos preflights
incluyen reproducciones históricas: no son validadores rápidos de YAML.
`scripts/run_backtest.py --help` documenta la interfaz offline anterior de un backtest
(`--app`, `--history`, `--execution`, `--strategy`), que permanece disponible.
Dashboard, integración VectorBT y paper/live siguen sin implementarse.

## Trend RSI Pullback

[Protocolo, grids y comandos](docs/trend-rsi-pullback.md): una familia para V1 15m,
V2 con tendencia 1h cerrada y V3 con slope SMA. Video Reference tiene una configuración;
cada grid tiene 486, antes de activos/modos/periodos/costes. Ejecución por lab.py,
sintética sobre precios USD-M, sin funding/liquidaciones; no integrada al forward.
`lab.py compare ID1 ID2 ...` genera nuevos resúmenes comparativos de runs completos
sin ejecutar backtests ni reescribir resultados.
