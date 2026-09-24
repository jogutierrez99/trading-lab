# Batch 002: adaptación congelada antes de probar rentabilidades

El prompt permite implementar las cuatro estrategias con OHLCV BTC/USDT spot de
1h. No se modifican los tres módulos de estrategias anteriores ni las configuraciones
y resultados de Batch 001. Nuevos módulos: `vol_momentum`, `donchian_adx`,
`bb_squeeze` y `regime_meanrev`, versión 1.0.0. Cada uno tiene tres variantes
predefinidas, sin búsquedas adicionales. Los nombres en el informe corresponden
a VOL_MOMENTUM_001, DONCHIAN_ADX_001, BB_SQUEEZE_001 y REGIME_MEANREV_001.

## Historia realmente utilizable

No hay una serie validada 2020–2026. Los CSV disponibles llegan a diciembre de
2025. La política de fuentes valida meses completos y marzo de 2023 sigue siendo
inválido por una hora ausente. No se rellenan velas ni se atraviesa ese mes.

Se revalidaron offline dos subconjuntos de los CSV auditados, conservando sus
checksums y la identidad del manifiesto padre. Validación completa de timestamps,
continuidad, duplicados, finitud y OHLC. Nuevos bundles independientes:

- Principal: `5810d644e2ff492d1a4f0ed9c5327561418be3c20f920c9520d28920f46bf54b`.
  24.144 velas, abril de 2023–diciembre de 2025. Primeras 768 horas como
  calentamiento; periodo puntuable 03/05/2023–01/01/2026 exclusivo.
- Anterior: `2322037acf66bdb51b4af3bc76c278d0dce85d2bc5bf2d0e8cd97e86d6eac04b`.
  10.920 velas, diciembre de 2021–febrero de 2023. Calentamiento 768 horas;
  periodo puntuable 02/01/2022–01/03/2023 exclusivo. Solo diagnóstico de baselines:
  gran parte ya se observó en Batch 001 y no es confirmación independiente.

Usamos el mayor tramo continuo validado para selección y evaluación principal.
El tramo anterior se evalúa por separado para aprovechar historia adicional,
sin concatenar cuentas, posiciones o curvas a través del intervalo excluido.
Los huecos de 2021 continúan fuera de alcance. Enero de 2026 en adelante y 2020
no están presentes en los CSV auditados usados para este lote.

Cada partición/fold usa exactamente 768 horas previas. Ello permite los 720 anchos
anteriores de Bollinger, su ventana de 20 velas y las 24 horas previas de squeeze.
EMA/ADX/RSI reinician sus semillas en el principio de ese contexto. El contexto
no produce operaciones ni PnL. No se cambia el límite de 10.000 warmup bars del
contrato de datos para simular todo el pasado como calentamiento.

## Particiones UTC (fin exclusivo)

| Partición | Inicio | Fin |
| --- | --- | --- |
| Train | 2023-05-03 | 2024-07-01 |
| Validation | 2024-07-01 | 2025-01-01 |
| Test | 2025-01-01 | 2025-07-01 |
| Final holdout | 2025-07-01 | 2026-01-01 |

Por familia: probar las tres variantes solo en train con costes base. Elegibilidad
idéntica a Batch 001: >=20 trades, retorno neto positivo, DD <=25%, Sharpe definido.
Elegir mayor Sharpe; desempatar por menor turnover y después ID. Si no hay
elegibles, usar la baseline solo como diagnóstico. Guardar selección antes de
validation/test. No cambiarla tras observarlos.

Walk-forward: cuatro folds con train móvil de 12 meses y test de 3 meses, movidos
cada 3 meses. Tests: julio–septiembre 2024, octubre–diciembre 2024, enero–marzo
2025, abril–junio 2025. Selección restringida a las mismas tres variantes con la
misma regla y solo datos previos de cada fold. Reiniciar capital en cada fold;
componer porcentajes test como descripción, no como cartera ejecutada. Estos
tests se solapan con validation/test estáticos; no son evidencia independiente.

Abrir final holdout solo después de terminar validation, test y walk-forward;
registrar un marcador de apertura con la selección original. Leer/validar precios
del bundle antes no equivale a usar su rendimiento para seleccionar variantes.
El runner no calcula rentabilidades del holdout antes de ese marcador.

## Fórmulas y ajustes necesarios

- Vol momentum usa exactamente `close[t]/close[t-24*días]-1`, EMA200 y volatilidad
  realizada sobre 720 retornos horarios simples, desviación muestral (`ddof=1`),
  anualización sqrt(24*365). Close actual es causal porque se opera al siguiente
  open. Batch 001 usaba una vela adicional de retraso y no filtro EMA: la comparación
  no aísla exclusivamente el efecto de escalar exposición.
- Target `target_volatility_pct: 20.0`; fracción clip(0,20/vol, 0,05, 0,25).
  Volatilidad cero o no finita impide entrar. El prompt no fija rebalanceo:
  se recalcula solo al entrar, sin rebalanceos mientras siga abierta la posición.
  **25% es un límite al entrar, incluyendo la comisión; el porcentaje de exposición
  después puede cambiar con el precio.** No se promete volatilidad de cartera del
  20%. No se añade una variante de rebalanceo no solicitada.
- ADX14 Wilder: movimientos direccionales positivos exclusivos; empate produce
  ambos cero. TR/DM suavizados con semilla aritmética de 14 cambios; DX y luego
  ADX Wilder, primer ADX en índice 27. Sin movimiento, DX=0. El ATR de los stops
  conserva la media aritmética de Batch 001; no se sustituye por ATR Wilder.
- Donchian usa high anteriores excluyendo la vela actual. Nuevo trailing basado
  exclusivamente en máximo de cierres desde entrada. Actualización al cierre,
  efecto en la siguiente vela y sin aflojar el stop. La apertura de entrada no se
  trata como un cierre. El Donchian anterior sigue usando extremos high/low.
- Squeeze: BB20/2 con desviación poblacional. Umbral percentil 15/20/25 del ancho
  de las **720 velas anteriores**, interpolación lineal. Compresión en alguna de
  las **24 velas anteriores**: una compresión detectada por primera vez en la
  vela actual no autoriza comprar esa misma ruptura. Bandas de ruptura incluyen
  el cierre actual como especifica el prompt. Se requiere el contexto completo.
- Regime meanrev: ADX <20 y distancia a EMA <0,05, estrictos; RSI de entrada
  25/30/35, salida RSI >55 estricta o close >= media. RSI Wilder de Batch 001.
- Time stops 120/72 cuentan la vela de entrada; salir en el open posterior al
  cierre de la vela N. Todos los módulos nuevos emiten solo señales long.

Solo se amplía el motor para dos capacidades reutilizables: fracción de entrada
causal y base de trailing configurable. Los valores por defecto conservan Batch
001. `reference_v3` identifica uso de esas capacidades; sin ellas se conserva la
identificación anterior. Ninguna regla depende del nombre de una estrategia.

## Costes, riesgo, resultados y límites

10.000 USDT por ejecución independiente, sin apalancamiento. En las tres
estrategias con stop: riesgo 0,5% y notional máximo 25% al entrar; se elige el
menor tamaño, incorporando costes de entrada/salida al stop. Gaps pueden exceder
el riesgo estimado. No hay cartera conjunta, funding ni cortos.

Escenarios por orden, unidades porcentuales: cero; base comisión 0,05%, slippage
0,02%, spread completo 0,01%; adverso comisión 0,10%, slippage 0,10%, spread
completo 0,02%. Son supuestos, no tarifas históricas verificadas. Se aplican a
fills; no se restan de nuevo al PnL. Benchmarks independientes 25%/100%, igual
calendario y primer open ejecutable, costes, mínimos y liquidación final.

Ledger SQLite, JSON/Parquet y CSV en `results/batch_002/<run_id>/`. Plan/config,
dataset, costes y hashes de código congelados antes de la primera rentabilidad.
Guardar todos los ensayos, selecciones, fallos, trades, equity, rechazos y métricas,
incluyendo CAGR, drawdown, Sharpe, Sortino y duración real. Sharpe/Sortino usan
retornos diarios UTC y convenciones documentadas de Batch 001; indefinidos son null.
Clasificar holdout con las reglas anteriores y conservar flags aunque predomine
INSUFFICIENT_DATA. ROBUST sigue deshabilitada: no se proclama mejora de antemano.

Comandos:

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe scripts/run_batch_002.py --config configs/profiles/batch_002/batch.yaml
.venv\Scripts\python.exe scripts/plot_batch.py results/batch_002/<run_id>
```
