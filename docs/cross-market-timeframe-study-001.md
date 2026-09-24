# Cross-market timeframe study 001

Fase independiente de Batch 001–005: amplia datos y contrasta las 19 configuraciones
solicitadas, sin nuevas estrategias, optimizacion, cartera ni operativa real.
Los archivos anteriores se protegen mediante SHA256 (4267 archivos).

## Datos y reproduccion

```powershell
.venv\Scripts\python.exe scripts/download_cross_market.py
.venv\Scripts\python.exe scripts/verify_cross_market_study.py
.venv\Scripts\python.exe scripts/run_cross_market_study.py
```

El downloader pagina archivos mensuales y dias completos del mes actual de Binance
Spot, verifica el CHECKSUM oficial, guarda ZIPs por hash y checkpoints por pagina.
Una repeticion reutiliza y verifica los originales. Los errores quedan en JSONL;
los datasets se guardan en directorios identificados por hash y nunca se reemplazan.
La fuente documenta timestamps en microsegundos desde enero de 2025:
[Binance public data](https://github.com/binance/binance-public-data).

Ubicacion: `data/cross_market_timeframe_study_001/<asset>/<timeframe>/<hash>/`.
Cada manifiesto contiene procedencia y hashes, auditoria y exclusiones. Los timestamps
de cierre invalidos o de apertura fuera de rejilla se ponen en cuarentena, conservando
el ZIP original y sus timestamps rechazados; no se corrigen precios ni timestamps.
Filas OHLCV invalidas, duplicados o desorden rechazan la pagina, con error registrado.

La descarga realizada cubre 2018-01-01 hasta 2026-09-22 exclusivo. Cada activo tiene
76300 velas horarias, 19100 de cuatro horas y 3186 diarias antes del filtro comun.
Los seis datasets contienen 3152 dias completos comparables, tras intersectar dias
completos y excluir discrepancias de agregacion. Las discrepancias de volumen son
reales, no se absorben aumentando tolerancias. La tolerancia numerica de comparacion
es exclusivamente de redondeo float64: rtol=1e-12 y atol=1e-8.

## Protocolo congelado

- 19 estrategias × 2 activos × 3 timeframes = 114 filas de matriz.
- 108 evaluables; MTF Momentum en 4h/1d y Trend Acceleration A12 en 1d se excluyen
  en ambos activos por incompatibilidad conceptual o duracion no representable.
- EMA, RSI, ADX, ATR y Donchian expresados como periodos intencionales mantienen
  barras. Los ROC, pendientes, canales expresados en horas y time stops conservan
  tiempo real. La distribucion de volatilidad usa 30 dias; no 720 barras en todos
  los marcos. El contador de contraccion 6 de 24 velas y el retest de 24 velas
  conservan su definicion explicita original. Ver documento de traduccion.
- Cuenta independiente de 10000 USDT por combinacion, ventana y escenario de costes.
  No se suman retornos entre cuentas. Dentro de una ejecucion con huecos, el capital
  permanece en efectivo entre tramos; se cierran posiciones antes del hueco y se
  reinician indicadores. No se transportan operaciones entre ventanas.
- Ventanas cronologicas 50/20/15/15 de tiempo calendario. Todas las combinaciones
  y costes de TRAIN/VALIDATION/TEST terminan antes de desbloquear FINAL_HOLDOUT.
  No existe seleccion automatica. FULL y las ejecuciones anuales independientes
  se realizan despues del desbloqueo, para no consultar prematuramente el holdout.
- ETH se etiqueta CROSS_ASSET_VALIDATION; BTC conserva REUSED_HISTORY_DIAGNOSTIC.
  El ano 2026 de BTC se separa como NEW_PERIOD_DIAGNOSTIC, no como paper trading.
- Costes ZERO/BASE/ADVERSE aplicados en fills de cada ejecucion completa.
  BASE: comision0.05%, slippage0.02%, spread completo0.01%.
  ADVERSE: comision0.10%, slippage0.10%, spread completo0.02%.
- Filtros de cantidad/minimo son supuestos fijos de investigacion, no una reconstruccion
  de todos los cambios historicos de filtros de Binance.

## Analisis

Retornos diarios UTC; anualizacion sqrt365; riesgo libre cero. Los huecos de datos
solo se rellenan en la serie de efectivo de la cuenta, nunca en OHLCV. La exposicion
en huecos es cero. La estabilidad anual excluye el ano parcial; los anos completos
pueden contener dias excluidos, cuya cobertura queda registrada por ejecucion.

MFE/MAE informa cotas por incertidumbre intrabar. Time-to-edge usa 1/3/6/12/24 barras
y 24/72/168 horas; horizontes que cruzan un hueco o el final de ventana se censuran.
Son diagnosticos posteriores, sin acceso desde las decisiones de trading.

Las correlaciones usan cuentas equivalentes. El solapamiento mide Jaccard de entradas
ejecutadas y de barras ocupadas, no identidad causal entre hipotesis ni señales sin fill.
Las flags son descriptivas y estan congeladas en plan.json; nunca se asigna ROBUST.
Monte Carlo se limita a cada combinacion FULL/BASE con al menos 30 trades: 10000
permutaciones y 10000 bootstrap de PnL monetario fijo, semillas y muestras guardadas.

## Aislamiento y comprobaciones

El backend temporal es una implementacion independiente de los mismos fills del
motor previo; no modifica el motor ni las estrategias historicas. Una regresion
compara operaciones y equity de las 19 configuraciones en 1h. Se prueban tambien
prefijos causales en 1h/4h/1d, paginacion, reanudacion, hashes, cuarentena, agregacion,
conversiones, huecos, costes y MFE/MAE intrabar diario. El ejecutor exige un preflight
completo con el mismo hash de codigo, registra ledger SQLite y verifica sus hashes.

Los resultados se guardan en `results/cross_market_timeframe_study_001/<RUN_ID>/`.
`summary.md` responde a las 14 preguntas; `4h_analysis.md` compara BTC/ETH 4h frente
a 1h. Los CSV contienen la matriz completa, incluidas exclusiones. Una reanudacion
entre ejecuciones completas admite `--resume <directorio>` solo con codigo y datos
identicos; una ejecucion interrumpida dentro de un item conserva el intento y exige
un nuevo RUN_ID. Ningun resultado se sobrescribe silenciosamente.
