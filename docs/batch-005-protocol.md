# Batch 005: protocolo congelado antes de resultados

Cuatro hipótesis nuevas, exactamente tres variantes cada una. BTC/USDT spot 1h,
solo largos, 10.000 USDT por cuenta independiente; sin cartera ni apalancamiento.
No se modifica el motor ni los módulos/configuraciones/resultados de Batch001–004.
No hay órdenes reales. Nuevos cambios derivados de resultados pertenecen a Batch006.

## Datos y splits

Inventario local automático: tres bundles auditados y50 CSV. No hay BTC de2026,
ETH ni otro símbolo disponible. Se inspeccionan timestamps reales y hashes de CSV,
y se validan completamente los bundles; no hay descargas adicionales.
Todo el lote se etiqueta REUSED_HISTORY_DIAGNOSTIC. No es validación independiente.
El preset se detiene si aparece BTC nuevo u otro símbolo: exige auditar y congelar
nuevos splits antes de ejecutar; no ignora datos nuevos para reutilizar historia.

Primario: contexto desde abril2023; train2023-06-04–2024-07-01, validation hasta
2025-01-01, test hasta2025-07-01, final hasta2026-01-01. UTC, fin exclusivo.
Warmup común1.536h. Legacy2022-02-03–2023-03-01 se ejecuta aparte como diagnóstico
de bases. Nunca se rellena ni atraviesa marzo2023, ni se unen posiciones/cuentas.
Se registran símbolo, timeframe, fechas, filas, gaps, warmup, origen y hashes.

## Reglas y ambigüedades resueltas antes de ejecutar

### CHANNEL_BREAK_RETEST_001

Canales24/48/72h excluyendo vela actual. Con EMA50>EMA200 y close>canal previo,
congelar nivel y tolerancia0,25 ATR del breakout. No entrar ese día/barra.
Un solo setup activo: ignorar nuevas rupturas mientras espera.
Aceptar el primer retest posterior en edades1–24 inclusive, si low<=nivel+tolerancia
y close>=nivel−tolerancia. Congelar high/low/ATR de esa vela. Confirmar únicamente
en una vela posterior con close>high del retest. No se impone otra caducidad a la
confirmación; cancelar en cualquier fase si close<EMA200. Sin retest, expira en
edad25. Consumo/cancelación no permiten rearmar en la misma vela.

Stop absoluto=low del retest−0,01 ATR del retest, fijando de forma explícita qué
significa «debajo». Precios continuos simulados como en el motor existente, sin
redondeo de tick de precio. En el siguiente open calcular precio de entrada con
costes; rechazar si open<=stop o distancia entrada ajustada−stop no está en
(0,2,5 ATR de la confirmación]. No trasladar el stop ni convertirlo en ATR fijo.
El setup se consume aunque la orden sea rechazada. Time stop168h, salida close<EMA50.

El nuevo `structural_execution.py` adapta anclas a las distancias del motor existente
en la fase de ejecución: solo consulta el open de llegada, nunca high/low/close de
esa vela. Trailing y target prohibidos para este adaptador. El perfil utiliza el
valor ya soportado `stop_method: structure`; el runner antiguo lo rechaza en vez
de ejecutar silenciosamente otra estrategia. Usar el runner de Batch005.

### TREND_ACCELERATION_001

Slope fast=EMA50/EMA50.shift(N)−1 con N12/24/48, slow=EMA200/EMA200.shift(72)−1.
Aceleración siempre compara slope_fast con su valor24h antes, independientemente
de la variante. EMA50>EMA200, ambos slopes positivos, aceleración positiva y ruptura
máximo previo24h. Stop2 ATR, time stop240h; salidas slope_fast<0 o EMA50<EMA200.

### RSI_MOMENTUM_RESET_001

Reset como cruce descendente desde RSI>=umbral hasta RSI<40/35/30, bajo EMA50>EMA200
y ROC30d>0. El primer cruce arma un plazo48h; no se reinicia mientras está armado.
Recuperación como cruce RSI anterior<=50 y actual>50, estrictamente después del reset,
con close>EMA50, EMA50>EMA200 y ROC30d>0. Consumo único; caduca cuando edad>48.
Filtros de entrada fallidos no producen orden. Stop2 ATR; salidas RSI>70,
close<EMA50, ROC30d<0 o stop.

### VOL_CONTRACTION_EXPANSION_001

Cada ratio ATR14/close compara contra percentiles de720 ratios anteriores.
Contar contracción ratio<p30 en las24 velas anteriores, excluyendo la expansión
actual. Variantes>=6/12/18. Entrada con ratio>p50 y ratio anterior, EMA50>EMA200,
ROC7d>0 y ruptura máximo previo24h. Stop2,5 ATR; trailing highest_close−3 ATR,
activo desde vela siguiente y sin alejarse. Salidas close<EMA50, ROC7d<0 o ratio<p30.
No utiliza Bollinger. ATR14 conserva la media aritmética de TR; RSI usa Wilder.

## Selección y ejecución

Señales al cierre, entrada más temprana al siguiente open. Riesgo estimado inicial
al stop<=0,5%; exposición inicial<=25% incluyendo comisión, usando el menor tamaño.
No rebalanceo: la exposición puede crecer después y gaps superar la pérdida prevista.
Sin carry: todas las cuentas se liquidan al final de cada partición.

Costes base: fee0,05%, slippage0,02%, spread completo0,01%. Adversos:0,10%,0,10%,0,02%.
Zero/base/adverse se vuelven a ejecutar completamente para cada selección en
train/validation/test/final. Drag=zero−base y base−adverse en puntos porcentuales;
pueden variar fills, tamaños, rechazos y número de trades.

Elegibilidad exclusivamente train/base: net>0, Sharpe>0, PF>1, trades>=40, DD<20%.
Orden: mayor Sharpe, menor DD, mayor PF, ID determinista, con empates exactos.
Si ninguna pasa, base A diagnóstica: INSUFFICIENT_DATA si todas<40 trades;
en otro caso REJECTED_TRAIN. Selección congelada antes de validation.

WF: cuatro folds12m/3m, step3m, desde test julio2024. Siempre la selección inicial,
sin reoptimizar. Capital independiente, compuesto solo de tests. Se solapa con
validation/test estáticos y no aporta evidencia independiente adicional.

Principal REUSED_HISTORY_DIAGNOSTIC, nunca ROBUST. Diagnóstico secundario prioriza
fallo/insuficiencia train, luego<30 trades finales, FAILED_AFTER_COSTS si zero positivo
y base no positivo, FAILED_OOS si cualquier validation/test/final no positivo y,
de otro modo, PROMISING_BUT_UNSTABLE. Adverse/WF se muestran sin ocultar pérdidas.

## Calidad de entrada y seguimiento a horizonte fijo

Excursiones brutas respecto al open de entrada antes de costes; MAE como magnitud
positiva. En salidas al open, excluir high/low de la vela de salida. Al cierre,
incluirla. En salidas intravela no se conoce qué extremos precedieron el fill:
usar extremos de velas completas y precio de salida como cotas inferiores, y los
extremos completos de la vela de salida solo como cotas superiores. No fingir que
todo el high/low de esa vela ocurrió durante la operación.

MFE/MAE principal=ratio de medias de las cotas inferiores, **no** ratio verdadero
identificado cuando hay censura intravela. También se registran ratios por trade,
media/mediana, cotas superiores y conteo censurado. Tiempo hasta extremo: intervalo
horario de la primera aparición del extremo observado, no instante exacto. El reporte
no permite concluir por sí solo que una buena señal tenga mala gestión de salida.

Time-to-edge: close disponible exactamente6/12/24/48/72h después de la entrada,
dividido entre open de entrada, menos1. Puede continuar tras salir del trade; no es
PnL de la estrategia. Nunca usar datos posteriores al final de la partición, aunque
existan en el dataset padre. Horizontes ausentes se censuran, no se convierten en0.
Registrar media, mediana, n disponible y censurado. Trades/horizontes solapados no
son observaciones independientes. Estos análisis nunca cambian reglas del lote.

## Otros análisis y control

Regímenes y Monte Carlo conservan las reglas de Batch004. Dos ejes solapados:
EMA50/200 con lateral<=0,25% y ATR_ratio frente a p30/p70 anteriores720. No sumar ejes.
Gross de los mismos trades usa referencias de fill; no equivale al escenario zero.

Cada ejecución con>=30 trades recibe10.000 permutaciones y10.000 bootstraps de PnLs
monetarios fijos, semillas deterministas y percentiles5/25/50/75/95 de terminal,
DD entre trades y rachas. Permutación conserva retorno terminal; bootstrap lo varía.
Sin resizing, dependencia temporal ni pronóstico futuro. Paths de equity no positiva
se conservan como estrés sin absorción. Registrar omisiones por muestra insuficiente.

Quince selecciones congeladas Batch001–004, como REFERENCE_DIAGNOSTIC, y benchmarks
buy-and-hold25/100% sobre periodos idénticos completo/final. No reoptimizar ni comparar
cifras originales de periodos distintos como equivalentes.154 backtests previstos.

Snapshot de3.145 archivos previos, incluidos datasets, antes de implementar.
Verificar hashes antes/después, preflight con tests/Ruff/formato/pip check y hash del
código validado. Plan/provenance antes del primer backtest; selección antes de
validation; marcador antes de final. Archivos exclusivos e ID único, nunca sobrescribir.

```powershell
.venv\Scripts\python.exe scripts/run_batch_005.py
.venv\Scripts\python.exe scripts/report_batch_005.py results/batch_005/<RUN_ID>
```

El runner requiere evidencia válida en `reports/batch_005/preflight.json`, incluyendo
code_sha256 de `quant_lab.experiments.provenance`. Código cambiado o checks fallidos
bloquean ejecución. Resultados y datasets locales siguen ignorados por Git.
