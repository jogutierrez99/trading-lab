# Batch 003 — protocolo congelado

Cuatro estrategias nuevas, tres variantes cada una, BTC/USDT spot 1h solo largos.
No cambia el motor, las siete estrategias anteriores ni sus configuraciones/resultados.
Todas las ejecuciones llevan `REUSED_HISTORY_DIAGNOSTIC`; no existe histórico auditado
posterior a diciembre de 2025. Ningún resultado se clasifica ROBUST.

## Adaptaciones anteriores a ejecutar

- Pullback significa que el low de la vela anterior toca/cruza su EMA, seguido de
  recuperación al cierre actual y filtros RSI/tendencia. No hay búsqueda retrospectiva
  de la duración del retroceso.
- Warmup común de 1.536 horas: cubre ROC60d y EMA200 en 4h. Las velas 4h se agrupan
  en UTC desde medianoche; se descartan bloques parciales y solo se publican al cierre.
- Primario: train 2023-06-04–2024-07-01, validation hasta 2025-01-01,
  test hasta 2025-07-01, final hasta 2026-01-01. Fin exclusivo, UTC.
- Legacy: 2022-02-03–2023-03-01 en cuentas independientes, bases diagnósticas.
  Marzo2023 no se rellena ni se atraviesa. No unir las curvas.
- Selección train/base: retorno>0, Sharpe>0, PF>1, trades>=40, DD<20%.
  Entre elegibles a distancia<=0,01 del mayor Sharpe: menor DD, mayor PF y luego ID.
  Si ninguna pasa, solo base diagnóstica: INSUFFICIENT_DATA si todas tienen<40 trades;
  de lo contrario REJECTED_TRAIN. Ninguna observación posterior altera selección.
- Walk-forward: cuatro folds 12 meses train /3 meses test, step3m, desde test julio2024.
  Repite la variante inicialmente seleccionada; nunca vuelve a seleccionar en folds.
  Capital independiente, compuesto solo de tests. Se solapa con validation/test.
- Exposición máxima25% al entrar incluyendo comisión. Sin rebalanceo continuo; el
  porcentaje marcado a mercado puede superar25%. Riesgo estimado inicial al stop<=0,5%;
  los gaps pueden producir pérdidas mayores. Sin apalancamiento.
- Regímenes: dos ejes, porque tendencia y volatilidad se solapan. EMA50/200 con
  distancia absoluta relativa<=0,25% define lateral; ATR14/close frente a percentiles
  30/70 de720 ratios anteriores define volatilidad baja/normal/alta. UNKNOWN durante
  calentamiento. Trades atribuidos al régimen de la señal; PnL por barra al régimen
  conocido al inicio; contribuciones divididas entre capital inicial. Nunca sumar ejes.
- Monte Carlo: 10.000 permutaciones de PnLs monetarios realizados, >=30 trades,
  semillas SHA256(candidato/partición/base), cada ejecución primaria nueva con costes
  base. Sin remuestreo de tamaños ni repetición de fills; retorno final invariante.
  DD entre trades y rachas no equivalen a DD intrabar ni pronóstico futuro.
- Gross es PnL a precios de referencia de los mismos trades ejecutados. Escenario zero
  se vuelve a simular desde cero: no sustituirlo por gross ni restar costes a posteriori.
- Referencias anteriores: parámetros y riesgos de las selecciones originales, sin
  reoptimización, recreadas en exactamente los mismos periodos completo/final con
  1.536 barras de contexto. Las cifras originales permanecen intactas.

## Clasificación

Etiqueta principal siempre REUSED_HISTORY_DIAGNOSTIC. Diagnóstico secundario prioriza
rechazo/insuficiencia train; después insuficiencia de trades finales (<30),
FAILED_AFTER_COSTS si zero positivo y base no positivo, FAILED_OOS si cualquier tramo
validation/test/final es no positivo; en otro caso PROMISING_BUT_UNSTABLE. Costes
adversos y estabilidad WF se muestran por separado. No hay proclamación de ganador.

## Reproducción

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe scripts/run_batch_003.py
.venv\Scripts\python.exe scripts/report_batch_003.py results/batch_003/<RUN_ID>
```

El ejecutor requiere evidencia previa en `reports/batch_003/preflight.json` y el
snapshot de1.067 archivos anteriores en `protected_previous.json`. Comprueba estos
hashes antes/después, congela código/configuración en provenance y plan antes del
primer backtest y registra selección antes de validation. Resultados exclusivos con
ID único; no sobrescribir. ledger registra hashes y estado de cada experimento.
Las hipótesis derivadas de resultados pertenecen a Batch004.
