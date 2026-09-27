# Batch 006: Bollinger con largos y cortos

Experimento independiente `batch_006_bollinger_long_short`. Implementación de
`BOLLINGER_REGIME_REVERSAL_001`, registrada como `bollinger_regime_reversal` v1.0.0.
No modifica los motores ni estrategias de los lotes anteriores. El YAML general
permanece deshabilitado: el runner independiente habilita las 54 configuraciones.
No existe envío de órdenes reales.

## Matriz congelada

Tres variantes A/B/C, tres modos LONG_ONLY/SHORT_ONLY/LONG_SHORT, BTCUSDT y ETHUSDT
USD-M perpetual, y señales 1h/4h/1d. Cada cuenta comienza con 10.000 USDT,
riesgo inicial máximo 0,5%, exposición inicial (notional más comisión) máxima
25%, margen aislado a 1x. Sin hedge, pyramiding ni reversal inmediato.

A: Bollinger 20/2, RSI <30/>70, ADX <25, stop 2 ATR.
B: Bollinger 20/2,5, RSI <25/>75, ADX <25, stop 2 ATR.
C: Bollinger 20/2, RSI <35/>65, ADX <20, stop 1,5 ATR.
Todas exigen distancia absoluta a EMA200 <8%. Salidas largas al cierre >= media
o RSI >=55; cortas al cierre <= media o RSI <=45. Señal al cierre, ejecución
al siguiente open disponible de esa señal. No reutilizar señales anteriores.

Bollinger usa desviación poblacional; RSI/ADX usan Wilder, EMA200 es recursiva,
ATR14 es media aritmética de true range según la convención existente.
Los periodos de indicadores conservan su significado de barras, no de horas:
20 barras diarias no equivalen a 20 horas. Solo el time stop es invariante en
reloj: 72 horas = 72/18/3 barras. Esta distinción se congela, no se optimiza.

## Datos y limitaciones

La descarga inicial se actualizó antes de medir resultados hasta el 25/09/2026
completo UTC. Histórico común auditado desde 01/01/2020: 58.728 velas horarias
por activo, 11 segmentos continuos y 7.341 eventos de funding por activo.
Los archivos previos a 2020 que la fuente no ofrece quedan registrados como
no disponibles. Se conservan ZIP, checksums, manifest y respuestas públicas.
El informe de cada ejecución guarda el inventario exacto usado y sus hashes.

Se exige correspondencia entre velas 1h, 4h y 1d, días UTC completos, precios
mark disponibles y settlements observados. No se interpolan precios ni se
rellena funding con cero. Se usa la intersección BTC/ETH para comparar exactamente
los mismos días. Los días excluidos se mantienen como huecos: se liquida al
final del segmento, el efectivo se conserva y los indicadores reinician.
Ese cierre de frontera es una convención del backtest, no una capacidad operativa
para anticipar cortes de datos. CASH durante huecos no representa una vela inventada.

El reloj de ejecución es 1h incluso para señales 4h/1d: permite comprobar stops,
funding y liquidación sin fingir un recorrido intradiario de una vela diaria.
Los precios de marca se usan para equity y margen; los precios del contrato para
fills. Aun así, las velas no permiten conocer el orden intrahorario real.

Funding usa tasas y timestamps realmente publicados. La cobertura exige los eventos
observados de 00/08/16 UTC; no se generan eventos faltantes. Algunos timestamps
presentan retrasos inferiores a un segundo. Se conservan: un settlement exactamente
en el open precede salidas/entradas; uno retrasado se aplica después de esas acciones
y antes de fills intrabar. Se aproxima su notional mediante mark-open. No hay datos
tick para resolver ese orden más finamente; offsets >=1 segundo se rechazan.
Positivo en funding_pnl significa ingreso; funding_cost tiene signo opuesto.

Margen inicial = notional de entrada; el funding ajusta el margen aislado.
Maintenance 0,5%, comisión de liquidación 0,5%, paso/cantidad mínima 0,001 y
mínimo notional 5 USDT son **supuestos de investigación**, no reconstrucciones
históricas de filtros y tiers del exchange. Liquidación por mark antes del stop
si ambas caben en una hora sin orden observable; fill al extremo adverso del
contrato. Un ajuste de insolvencia limita esa pérdida al margen aislado asignado;
no reconstruye insurance fund ni ADL. El campo `maintenance_margin_at_exit`
conserva la referencia del chequeo: mark-open en salidas al open y el extremo
adverso horario en las demás; no es un snapshot de margen real del exchange.
Todos los resultados llevan
`MARGIN_MODEL_ASSUMED` y `DIAGNOSTIC_ONLY`.

## Validación e informes

ZERO sin costes ni funding; BASE y ADVERSE con tasas históricas idénticas y
comisiones/slippage/spread predefinidos. No se multiplica funding artificialmente.
Cada escenario se vuelve a ejecutar; el drag entre escenarios no equivale a
restar comisiones de una secuencia invariable de operaciones.

TRAIN 50%, VALIDATION 20%, TEST 15%, FINAL HOLDOUT 15% cronológicos. Se permiten
features causales calculadas con historia anterior, nunca una señal de warmup
para entrar justo en el primer open de una partición. Walk-forward móvil
12 meses train, 3 meses test, paso 3 meses, sin selección ni reoptimización.
Con este corte hay 22 folds. Agregación WF exclusiva de TEST; TRAIN queda separado.
Las cuentas WF reinician capital: encadenar sus porcentajes es solo diagnóstico.

Se completan todos los splits anteriores y folds que terminan antes del holdout
antes de desbloquearlo. El ledger exige que todos hayan finalizado correctamente.
FULL y los folds que tocan holdout se ejecutan después. Código, variantes, datos,
metodología, costes y clasificación se congelan en plan/provenance antes de iniciar.
Ninguna variante/modo se selecciona automáticamente. Haber observado antes el
mercado subyacente impide considerar estas particiones evidencia OOS virgen.

Son 7.938 ejecuciones de estrategia y 14 benchmarks: Buy & Hold LONG perpetuo
25/100% con los mismos costes/funding/margen, y CASH, por activo. Los benchmarks
liquidan/reinician en las mismas fronteras de datos y no son buy-and-hold continuo
sobre precios inventados. No se construye benchmark short.

Se separan PnL, PF, expectancy, funding, exposición y MFE/MAE largos/cortos.
`short_incremental_value` = retorno combinado menos retorno LONG_ONLY; incluye
cambios de oportunidades y sizing, no equivale al PnL short aislado.
MFE/MAE short es lineal respecto al precio de entrada, con cotas intrabar.
La duración de una salida intrabar se contabiliza hasta el límite horario superior;
la exposición es una muestra al cierre horario, no tiempo exacto dentro de la vela.
Time-to-edge incluye operaciones ejecutadas y, por separado, todas las señales
válidas, incluidas las ignoradas por tener posición; horizontes solapados no son
observaciones independientes. Los horizontes expresados en horas se publican cuando
son múltiplos exactos del timeframe de señal; los expresados en barras se convierten
a horas. No se cruza un gap ni el final de la partición.

## Comandos

Desde la raíz, con el entorno del proyecto:

```powershell
.venv\Scripts\python.exe scripts/download_batch_006.py
.venv\Scripts\python.exe scripts/verify_batch_006.py
.venv\Scripts\python.exe scripts/run_batch_006.py
```

El preflight exige pytest, ruff check, ruff format --check y pip check y liga el
resultado al hash del código. Cualquier modificación exige repetirlo. Los tests
incluyen simetría, prefijos causales, stops/targets, cortos, costes, orden de funding,
liquidación, bloqueo de holdout e informes sintéticos completos. Resultados en
`results/batch_006_bollinger_long_short/<RUN_ID>/`; hashes del ledger, trades,
equity y artefactos, copia del código congelado en `source_snapshot/`, más comprobación de los 19.490 archivos anteriores protegidos.

Fuentes: [Binance Public Data](https://github.com/binance/binance-public-data),
[histórico de funding USD-M](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History),
[liquidación y mark price](https://www.binance.com/en/support/faq/detail/360033525271).
