# Trend Volatility Breakout V1 — protocolo congelado

Hipótesis: las rupturas direccionales con expansión de volatilidad, a favor de una
tendencia principal, pueden generar una ventaja reproducible después de costes.
El laboratorio intenta falsarla. Versión `1.0.1`, estado de implementación `research`;
la hipótesis ETH comienza en `NEW_HYPOTHESIS`, sin resultados económicos nuevos.

La rama RSI no demostró robustez histórica suficiente, según la conclusión aportada
por el usuario. Se conserva su historial, candidatos y runs. Esta familia no utiliza
RSI ni el historical challenge para selección, calibración o periodos de evaluación.

## Señales y fórmula exacta

Todas las ventanas están expresadas en barras 1h. El índice identifica la apertura
de la vela; las features de la fila t están disponibles al cierre t+1h.

EMA: `ewm(span=trend_length, adjust=False, min_periods=trend_length)`, compartida
con `features.ema`. Recurrencia con alpha=2/(L+1), semilla primer cierre del segmento;
se oculta hasta reunir L cierres; las señales esperan además el warmup conservador 5×L.
No se interpreta el warmup como convergencia exacta
a una EMA calculada desde un origen histórico distinto. La ventana y su origen quedan
determinados por el periodo, warmup y dataset congelados.

- LONG: close[t] > EMA[t], EMA[t] > EMA[t-slope_lookback],
  close[t] > max(high[t-N], ..., high[t-1]) y expansión >= threshold.
- SHORT: desigualdades invertidas y close[t] < min(low[t-N], ..., low[t-1]).
- No basta tocar EMA o canal; las comparaciones de dirección/ruptura son estrictas.
  La comparación del threshold de expansión es inclusiva.

ATR reutiliza la media aritmética del true range del laboratorio, no Wilder:

```text
TR[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
ATR_current[t] = sum(TR[i], i=t-A+1..t) / A
ATR_reference[t] = sum(ATR_current[j], j=t-50..t-1) / 50
atr_expansion[t] = ATR_current[t] / ATR_reference[t]
```

La primera TR del segmento es NaN porque necesita el cierre anterior. La referencia
contiene exactamente los 50 ATR anteriores y **excluye el ATR de la vela de señal**.
Las ventanas ATR se solapan: no son observaciones independientes. Se requiere ATR
actual positivo y referencia positiva; cero/NaN no producen señales ni ratios válidos.

## Entrada y riesgo

Decisión al cierre; entrada en la apertura de la siguiente barra mediante StudyBackend.
En barras contiguas, `signal_close == entry_time`; la fila de señal es la barra anterior,
no la barra del fill. Se opera al open con costes adversos, nunca al cierre observado.
Los modos los aplica el backend; la estrategia conserva señales de ambas direcciones.

Con E = precio de entrada efectivo después de slippage/medio spread, d = ATR de la
vela de señal × atr_stop_multiplier:

```text
LONG: stop = E-d; target = E+d*reward_risk
SHORT: stop = E+d; target = E-d*reward_risk
```

Se usan `lab_risk_parameters` → RiskConfig, sizing y protecciones existentes. Hereda
riesgo 1% por trade, posición máxima 25%, exposición máxima 100%, quantity_step y
min_quantity 0.000001, min_notional 10. Una posición, sin piramidación. Sin salidas por
señal; stop/target y liquidación al fin de cada periodo. Stop-first ante ambigüedad
intrabar. Un salto de precio puede ejecutar el stop al open peor que su nivel; la
pérdida efectiva puede superar el presupuesto estimado.

V1 no añade MTF, timing 15m, trailing, break-even, parciales, time stop, ADX, volumen,
averaging ni otros filtros. Solo 1h permite estudiar primero el mecanismo base.
Señales y gestión del riesgo permanecen separadas para futuras hipótesis independientes;
V2 trailing y fases forward no están implementadas ni habilitadas aquí.

## Warmup, timestamps y gaps

```text
required_warmup = max(5*trend_length,
                      breakout_length+1,
                      atr_length+50+1)
```

Es el número de muestras para la primera señal habilitada; el primer ready aparece
en índice de posición required_warmup-1. El lab aporta ese número de barras anteriores
y bloquea sus señales para abrir posiciones del estudio. EMA100 requiere **500 barras**,
EMA200 **1000 barras**; máximo del grid: **1000 barras**, declarado en ambos YAML.
La referencia ATR exige A+51 barras contando el primer cierre usado por TR.
La corrección de warmup incrementa la versión desde 1.0.0 a 1.0.1, conforme al
contrato del repositorio. Los runs con warmup anterior conservan sus artefactos y
no se mezclan con esta versión; reproducirlos requiere su revisión Git original.

UTC, alineación horaria, orden y unicidad son obligatorios. Las features reinician
EMA/slope/canal/ATR/referencia tras una discontinuidad, sin rellenar velas ni cruzar
ventanas. El lab rechaza periodos con gaps incluyendo warmup; StudyBackend exige un
segmento continuo. Los gaps de precio entre barras contiguas conservan el modelo
existente de fills y TR.

## Grid y datos

| Parámetro | Valores |
|---|---|
| trend_length | 100, 200 |
| breakout_length | 20, 50 |
| atr_length | 14, 20 |
| atr_expansion_threshold | 1.0, 1.25 |
| atr_stop_multiplier | 1.5, 2.0, 2.5 |
| reward_risk | 1.5, 2.0, 2.5 |
| slope_lookback | 5 |

atr_reference_length=50 fijo, fuera del grid. **144 configuraciones por mercado/modo**,
432 incluyendo tres modos. ETHUSDT y BTCUSDT tienen YAML distintos y el mismo grid.
6072 backtests previstos por experimento: 144×3×2×(3+4) + 3×2×4.
Los tests solo ejecutan fixtures pequeños, nunca estos grids históricos.

Fuente: precios USD-M 1h locales existentes. El script `prepare_lab_1h_prices.py`
fija los IDs fuente, verifica identidad, SHA256, fingerprint y cobertura, audita OHLCV
y exige timestamps UTC únicos, ordenados y alineados a horas completas: una fuente
15m etiquetada como 1h se rechaza. Los gaps horarios reales permanecen registrados,
sin cambiar la política de gaps de ejecución. Escribe un bundle `study_data` con las
mismas filas/valores. Sin descarga, recorte,
resampling ni interpolación. Los manifiestos derivados guardan hashes de fuente;
una repetición verifica el bundle existente y rechaza sobreescrituras inconsistentes.

- ETH fuente: `a65b55a9ad440549555274cbccc1f87bfcd27ed1832a118ad8c488f8eaacfa90`.
  Bundle lab: `1006e4cb8296ab8d1574317f2927c7feb975bbd25a5f195a8c7d97a17d7b70e4`.
- BTC fuente: `d68f6667bc96d9ee7d925e48e563e06c53e284db890c098cf5da4b9f655ceba6`.
  Bundle lab: `874c185c21abeeda4bf17c026a44a55a19bf91ead2ac2b4466b1f37d4a97c00b`.

Los datasets permanecen locales/ignorados. Otro checkout requiere esas fuentes
para preparar los bundles; ausencia o corrupción produce error explícito. Los hashes
derivados están fijados en los YAML. **funding not modelled**; ejecución sintética
colateralizada, sin liquidación de futuros ni réplica de sus filtros históricos.

## Protocolo temporal, costes y clasificación

Reutiliza el protocolo largo vigente del laboratorio; no el challenge RSI:

| Periodo UTC, fin exclusivo | Fechas |
|---|---|
| TRAIN | 2023-06-04 → 2024-07-01 |
| VALIDATION | 2024-07-01 → 2025-01-01 |
| TEST | 2025-07-01 → 2026-09-26 |
| WF 0 | TRAIN 2023-07-01 → 2024-07-01; TEST → 2024-10-01 |
| WF 1 | TRAIN 2023-10-01 → 2024-10-01; TEST → 2025-01-01 |
| WF 2 | TRAIN 2024-01-01 → 2025-01-01; TEST → 2025-04-01 |
| WF 3 | TRAIN 2024-04-01 → 2025-04-01; TEST → 2025-07-01 |

BASE hereda `app.yaml`: fee/slippage/spread 0.05/0.03/0.01%. ADVERSE conserva el
escenario ordinario 0.10/0.06/0.02%. No existe perfil central de stress ordinario;
se declara el escenario en cada YAML, igual que los experimentos actuales.
Ranking por TRAIN/base Sharpe; filtros legacy conservados (1 trade, DD<=25%).

Clasificación existente: VALID → RESEARCH_PASS → OOS_PASS → ROBUST_PASS →
PAPER_TRADING_CANDIDATE, con FAIL cuando corresponde. Perfil global y umbrales sin
cambios. RESEARCH_PASS usa exclusivamente TRAIN/VALIDATION y estrés correspondiente;
el gate TEST solo se aplica tras research. Es clasificación secuencial de artefactos:
el runner ordinario ya calcula todos los periodos, no implementa un bloqueo de ejecución
TEST condicionado a RESEARCH_PASS.

Cada fold WF ejecuta solo el ganador TRAIN; una configuración fija necesita sus cuatro
TEST WF propios para ROBUST_PASS. Ganadores distintos no se atribuyen a cada candidato.
La segunda fase `robust` congela únicamente candidatos RESEARCH_PASS y OOS_PASS y
completa sus TEST WF propios BASE/ADVERSE que falten. Reutiliza celdas verificadas,
incluidas celdas completas de una fase interrumpida, comprobando identidad, parámetros,
fechas, configuración, código, dataset, ledger y hashes de artefactos. No vuelve a
seleccionar ganadores ni modifica umbrales. `walk_forward_selection` conserva la
evidencia adaptativa original; `fixed_candidate_robustness` documenta cada candidato
y fold, validez técnica, retorno, expectancy y razones de fallo.
Cada ejecución escribe un suplemento nuevo en `reports/lab-robustness/<run>/<id>/`
y reclasifica automáticamente. Publicación compacta: `robustness.json`,
`robustness_summary.md` y `robustness_metrics_compact.csv`; equity y ledgers son locales.
ETH/BTC compare es descriptivo; no fusiona evidencia ni concede promociones automáticas.

TEST es OOS del protocolo de esta estrategia, pero el histórico 2020–2026 ya observado
en el proyecto no es evidencia absolutamente virgen. Distinguir research historical
evidence de independent future evidence. Un buen backtest no aprueba trading real;
la evidencia nueva deberá proceder después de forward/signal-only/demo en otra tarea.

## Comandos locales exactos

Desde la raíz, con el entorno Python del proyecto activado:

```powershell
python scripts/prepare_lab_1h_prices.py ETHUSDT
python scripts/lab.py validate trend_volatility_breakout_v1_eth_1h
python scripts/lab.py validate trend_volatility_breakout_v1_eth_1h --full
python scripts/lab.py run trend_volatility_breakout_v1_eth_1h
python scripts/lab.py classify trend_volatility_breakout_v1_eth_1h
python scripts/lab.py robust trend_volatility_breakout_v1_eth_1h
python scripts/lab.py report trend_volatility_breakout_v1_eth_1h
python scripts/lab.py publish trend_volatility_breakout_v1_eth_1h
# En el futuro, sin cambiar parámetros:
python scripts/prepare_lab_1h_prices.py BTCUSDT
python scripts/lab.py validate trend_volatility_breakout_v1_btc_1h --full
python scripts/lab.py run trend_volatility_breakout_v1_btc_1h
python scripts/lab.py classify trend_volatility_breakout_v1_btc_1h
python scripts/lab.py robust trend_volatility_breakout_v1_btc_1h
python scripts/lab.py publish trend_volatility_breakout_v1_btc_1h
python scripts/lab.py compare trend_volatility_breakout_v1_eth_1h trend_volatility_breakout_v1_btc_1h
python scripts/lab.py publish-comparison latest
```

`classify` se puede repetir: crea suplemento nuevo sin simular ni tocar resultados.
Tras `robust` repetirlo es opcional. Si no hay candidatos elegibles, `robust` no
ejecuta backtests y deja constancia explícita de ello.
Para fijar una fuente, reemplazar el ID del experimento por el run ID. `publish`
incluye clasificación solo si existe suplemento vigente; conserva allowlist y límites
de tamaño. No sobrescribe una publicación existente: revisarla antes de reemplazarla
manualmente. Destino `research_results/trend_volatility_breakout/<experiment>/<run>/`;
comparaciones en el destino del publisher existente. `results/` sigue ignorado y
`research_results/` versionado. Ningún comando realiza Git ni conecta al bot OKX.
