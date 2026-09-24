# Batch 004: protocolo anterior a resultados

Cuatro hipótesis nuevas, exactamente tres variantes por hipótesis. BTC/USDT spot 1h,
solo largos, 10.000 USDT independientes por ejecución. No se cambia el motor ni los
módulos/configuraciones/resultados de Batch 001, 002 o 003. No hay órdenes reales.

## Datos y adaptaciones

Inventario automático de tres bundles auditados y 50 CSV locales: no existe BTC
posterior al 01/01/2026 ni ETH. Se comprueban timestamps reales de los CSV, hashes
de fuentes y validación completa de los bundles. No se descarga histórico adicional.
Se usa `REUSED_HISTORY_DIAGNOSTIC` en todas las ejecuciones. Se registran rutas,
origen Binance, símbolo, timeframe, primeras/últimas velas, filas, gaps, warmup y hashes.

Este preset se detiene si el inventario detecta BTC nuevo o ETH: exige auditar y
congelar nuevos splits antes de ejecutar, en vez de ignorar silenciosamente nuevos
datos o presentar historia reutilizada como independiente. Un tramo nuevo corto
debería ejecutarse aparte como FORWARD_DIAGNOSTIC; esta ejecución no dispone de él.

Primario continuo: contexto desde abril 2023, fin exclusivo 2026-01-01.
Warmup común: 1.536 horas, suficiente para ROC60d. Train 2023-06-04–2024-07-01;
validation hasta 2025-01-01; test hasta 2025-07-01; final hasta 2026-01-01.
UTC, extremos finales exclusivos. No forzar splits supuestamente vírgenes.
Legacy 2022-02-03–2023-03-01 se ejecuta separado, solo bases diagnósticas.
Marzo 2023 no se rellena ni se atraviesa; posiciones y capital nunca pasan entre tramos.

## Fórmulas fijadas

- `regime_trend`: EMA50>EMA200, ROC30d>0, ATR_ratio>p40 de las720 velas anteriores,
  ruptura del máximo previo48h y ADX14>18/22/25. Stop2,5 ATR; salidas EMA50, ADX<15,
  ROC30d<0 o stop. Sin trailing.
- `dual_momentum`: close>EMA200, ROC largo>0, corto>0 y corto>largo.
  Pares7/30,14/60,7/60 días; se comparan ROC acumulados sin normalización por horizonte,
  exactamente como en el prompt. Es una hipótesis operativa de comparación de momentum,
  no una estimación matemática aislada de aceleración. Sin filtros adicionales.
  Stop2 ATR; sale por ROC corto<0, corto<largo, close<EMA200 o stop.
- `vol_expansion_trend`: EMA50>EMA200, ROC7d>0, ATR_ratio>SMA24,
  ATR_ratio>p50/60/70 de las720 velas anteriores y ruptura máximo previo24h.
  La SMA24 incluye ratio de la vela actual cerrada. Ventana de percentil720 se
  concreta antes de ejecutar, coherente con los demás filtros de volatilidad.
  Stop2,5 ATR; trailing highest_close-3 ATR, efectivo en la vela siguiente y sin alejarse.
  Salida close<EMA50 o (ROC7d<0 y ratio<SMA24), además del stop.
- `low_vol_pullback`: low anterior<=EMA20 anterior; close>EMA20, RSI14>50,
  EMA50>EMA200, close>EMA200 y ratio<p30/40/50 previo720. Stop1,5 ATR,
  time stop120; sale por close<EMA50 o ratio>p70 previo720, además del stop.

ATR14 conserva la media aritmética del TR existente; ADX14 usa Wilder con semilla
aritmética. Señal al cierre, fill al siguiente open. Los máximos previos excluyen
la vela actual; todos los percentiles excluyen el ratio actual. No hay datos futuros.

## Selección, costes y clasificación

Train/base exclusivamente: net>0, Sharpe>0, PF>1, >=40 trades y DD<20%.
Mayor Sharpe; empates exactos por menor DD, mayor PF e ID. Si ninguna pasa, base A
como diagnóstico: INSUFFICIENT_DATA si todas tienen<40 trades, si no REJECTED_TRAIN.
Congelar selección antes de validation. No grid search ni reselección por fold.

Base: fee0,05%, slippage0,02%, spread completo0,01%. Adverso:0,10%,0,10%,0,02%.
Zero/base/adverse son ejecuciones completas en train/validation/test/final para cada
selección. Cost drag=zero-base; adverse drag=base-adverse, en puntos porcentuales.
Los cambios de fills/tamaño/número de trades forman parte de la sensibilidad.

Riesgo inicial al stop<=0,5%, exposición inicial<=25% incluyendo comisión.
Sin rebalanceo continuo: exposición marcada a mercado puede subir; gaps pueden
superar el riesgo estimado. Se liquidan todas las posiciones al final de cada ejecución.

Etiqueta principal siempre REUSED_HISTORY_DIAGNOSTIC, nunca ROBUST. Diagnóstico
secundario prioriza rechazo/insuficiencia train, luego <30 trades finales; después
FAILED_AFTER_COSTS si zero positivo/base no positivo, FAILED_OOS si cualquier retorno
validation/test/final es no positivo y, de otro modo, PROMISING_BUT_UNSTABLE.
Adverse y WF se muestran por separado, sin poder establecer robustez sobre estos datos.

## Análisis y comparaciones

WF: cuatro folds móviles12m train/3m test, step3m desde julio2024, con selección
inicial fija. Solo se componen tests; cada fold usa una cuenta independiente.
Se solapan con validation/test estáticos y no son evidencia adicional independiente.

Regímenes: dos ejes solapados, tendencia EMA50/EMA200 con lateral<=0,25% de distancia
relativa absoluta, y volatilidad ATR_ratio frente a p30/p70 previos720.
Trades se atribuyen al régimen de la señal; PnL por barra al régimen conocido al inicio.
Contribuciones divididas por capital inicial, exposición media condicional al régimen.
Gross usa precios de referencia de los mismos trades; no equivale al escenario zero.

Monte Carlo por CADA ejecución con>=30 trades:10.000 permutaciones y10.000 bootstraps
con reemplazo de PnLs monetarios fijos. Semillas SHA256 de candidato/partición/costes/
benchmark/método. Permutar conserva PnL terminal; bootstrap lo varía. DD entre trades,
rachas y terminal PnL/retorno con p5/25/50/75/95. Sin resizing ni reejecución; ignora
dependencia de trades/regímenes. Retiene paths de estrés de equity no positiva, sin
absorción por quiebra. No es pronóstico.

Benchmarks buy-and-hold25/100% y once selecciones originales de Batch001/002/003
sobre periodos idénticos completo/final. Referencias etiquetadas REFERENCE_DIAGNOSTIC,
sin reoptimización, con contexto común1.536h. No comparar sus cifras originales de
otros periodos como equivalentes. No combinar las cuentas en una cartera.

## Verificación y reproducción

Snapshot de2.082 archivos: código/configuraciones anteriores, datasets y resultados.
Comprobar hashes antes y después. Tests críticos antes de ejecutar; el runner rechaza
preflight fallido o un hash de código diferente al validado. Plan/provenance antes del
primer backtest, selección antes de validation y marcador antes de abrir final.
146 backtests previstos; ningún cambio de hipótesis tras resultados.

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe scripts/run_batch_004.py
.venv\Scripts\python.exe scripts/report_batch_004.py results/batch_004/<RUN_ID>
```

El runner exige `reports/batch_004/preflight.json` con resultados y code_sha256 de
`quant_lab.experiments.provenance`. Cada ejecución crea un ID nuevo, ledger y archivos
exclusivos. Los gráficos y el informe tampoco sobrescriben resultados. Nuevas reglas
derivadas del análisis pertenecen a Batch005.
