# Batch 001A: implementación y uso

Tres estrategias independientes y pruebas históricas sobre el bundle BTC/USDT
spot 1h validado de enero de 2022 a enero de 2023. No se reparó el hueco de marzo
de 2023 ni se descargó otro mercado. El segundo tramo propuesto sigue pendiente;
esta entrega usa exclusivamente datos ya disponibles y validados.

## Perfil y reglas

`configs/profiles/batch_001/batch.yaml` contiene fechas y las 13 configuraciones
predefinidas. Capital: 10.000 USDT por ejecución independiente, solo largos,
sin apalancamiento. Las reservas originales continúan desactivadas.

- `trend_following` 1.0.0: ruptura del high/low de las 20 velas anteriores,
  filtro EMA200, stop inicial 2 ATR14 y trailing 3 ATR14; sin take profit fijo.
- `mean_reversion` 1.0.0: Bollinger20 con desviación poblacional y ancho 2,
  RSI14 Wilder 30/70. Salida a media o RSI50, stop 2 ATR; time stop opcional.
- `time_series_momentum` 1.0.0: cierre anterior / cierre de N+1 horas atrás - 1,
  N=24×días; base 14 días, vecinos 7/30. Posición del 25%, sin stop ni take profit,
  salida al pasar a momentum <=0. No rebalancea ni repite órdenes con igual signo.

Las señales cortas tienen pruebas simétricas; el batch no ejecuta cortos.
CRYPTO_001 se registra como skipped/BLOCKED_DATA/INSUFFICIENT_DATA.
No hay datos de perpetual/funding ni contabilidad de dos patas.

EMA usa `adjust=False`, semilla primera observación y `min_periods=period`.
RSI Wilder inicia promedios con los primeros N cambios: una serie constante
produce 50, solo ganancias 100 y solo pérdidas 0. ATR continúa siendo la media
aritmética del true range, como en fase 2.

## Cambios generales de ejecución

`RiskConfig` añade `atr_period`, `sizing_method`, `position_pct`, `stop_enabled`,
`take_profit_enabled`, `trailing_atr_multiplier` y `max_holding_bars`.
Los valores predeterminados preservan stop/target fijos y sizing por riesgo.
El backend v2 no contiene casos por nombre de estrategia. Los parámetros de señal
pertenecen al módulo; protecciones y tamaño al perfil de riesgo.

El trailing se actualiza al cierre de una vela en que la posición sobrevivió y
solo actúa en la siguiente. Nunca amplía el riesgo del stop. La vela de entrada
cuenta como primera para time stop; tras N velas sale al próximo open.
Prioridad: gap protector, salida de señal, time stop, protecciones intrabar;
si stop y target tocan en una vela, el stop tiene prioridad. Un gap favorable
mantiene el precio del target conservadoramente. No hay reapertura/reversión
en el mismo open de una salida. No se inventa hora exacta de fills intrabar.

El sizing incluye costes previstos, límites de capital, redondeo y mínimos
asumidos. Un gap puede exceder el riesgo estimado. El 25% limita el tamaño al
entrar; la exposición puede variar con el precio, sin rebalanceos ocultos.
`Trade.stop` es el último stop activo; presupuesto y pérdida esperada se refieren
al stop inicial. Duraciones intrabar se expresan en velas observadas.

## Validación temporal y métricas

Contexto común: 23/12/2021 16:00 UTC hasta 01/02/2022; no cuenta como rentabilidad.
Train: febrero–agosto 2022; validation: septiembre–octubre 2022;
test: noviembre 2022–enero 2023. Cada intervalo empieza plano y liquida al cierre
final con costes. Conserva contexto anterior para indicadores, pero ninguna señal
del contexto abre operaciones. Las vistas registran su fingerprint y dataset padre.

Selección exclusiva en train con costes base: >=20 operaciones, retorno positivo,
DD<=25%; mayor Sharpe diario, menor turnover, ID lexicográfico. Sin candidato
elegible se usa la baseline como diagnóstico. La selección se guarda antes de
calcular validation/test. Cuatro folds walk-forward, tests julio–octubre 2022,
entrenan de forma expansiva desde febrero. Se agregan solo porcentajes test;
reinician capital y se solapan con train/validation estáticos: no son evidencia
independiente. El test final no interviene en esos folds.

Costes por orden: cero; base fee 0,05%, slippage 0,02%, spread completo 0,01%;
adverso fee 0,10%, slippage 0,10%, spread 0,02%. Son supuestos, no tarifas históricas
verificadas. Spread se aplica por mitades. Slippage/spread están en los fills;
el desglose no se resta otra vez. Funding spot es null/no aplicable.

Métricas: retorno, drawdown, PnL, fees, deslizamiento, profit factor, win rate,
expectancy, duración, turnover/capital inicial, exposición media al cierre,
CAGR, volatilidad anualizada, Sharpe/Sortino/Calmar. Los retornos diarios incluyen
el cierre final UTC del día; Sharpe usa sqrt(365) y tasa libre de riesgo cero.
Sortino usa raíz del promedio de retornos negativos al cuadrado, incluyendo
días no negativos como cero. Denominadores nulos producen null. La exposición
media al cierre no mide exposición intrabar. Costes desglosados: trades cerrados;
el batch siempre termina plano. Los agregados por régimen son descriptivos.

Benchmarks al 25% y 100% entran una vez en el primer open ejecutable por las
estrategias (01:00 del primer día puntuable), con igual redondeo, costes y liquidación.
Cada ejecución es una cuenta independiente; no sumar sus equities como cartera.

## Persistencia y comandos

Cada ejecución crea `results/batch_001/<run_id>/`: plan/config/código congelados,
ledger SQLite, IDs únicos, JSON, Parquet, métricas CSV, selección y resumen Markdown.
Todos los trials, errores y bloqueos tienen estado. No se sobrescriben resultados.
Si no hay commit Git se registra null y hashes de fuentes/config/tests; no se
presume un checkout limpio. No se incluyen archivos de secretos.

La insuficiencia de muestra tiene prioridad en las etiquetas, pero conserva
banderas de pérdida OOS y tras costes. ROBUST está deshabilitada. Una clasificación
favorable no constituye evidencia de beneficio futuro.

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev,reports]"
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe scripts/run_batch.py --config configs/profiles/batch_001/batch.yaml
.venv\Scripts\python.exe scripts/plot_batch.py results/batch_001/<run_id>
```

Los gráficos leen resultados existentes, sin repetir backtests. Matplotlib es
dependencia opcional `reports`. CLI individual, sobre el estudio original de
13 meses (distinto de los 12 puntuados del batch):

```powershell
.venv\Scripts\python.exe scripts/run_backtest.py --app configs/profiles/batch_001/app.yaml --history configs/profiles/btc_spot_1h/history_2022_jan2023.yaml --execution configs/profiles/batch_001/execution.yaml --strategy trend_following
```

El CLI individual imprime JSON; el batch añade persistencia y selección temporal.
Cambiar fechas, costes o parámetros requiere otra ejecución identificada.
No reinterpretar tests observados como datos vírgenes tras una modificación.
