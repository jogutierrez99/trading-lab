# Batch 001: análisis y prompt de implementación adaptado

Fecha: 21 de septiembre de 2026. Este documento rediseña la petición; no implementa
estrategias ni contiene resultados de rentabilidad.

## Diagnóstico del laboratorio

- Caché revalidada mediante `read_bundle`: BTC/USDT spot 1h, 9.704 filas,
  desde 2021-12-23 16:00 UTC hasta 2023-02-01 00:00 UTC exclusivo.
  Incluye 200 horas previas al estudio original. Dataset:
  `77a55251e86f4034b317dd312b3bad06bb95c36f6540c74c4b8121793425b6da`.
- El registro de estrategias está vacío. Las reservas YAML no son estrategias.
- Aunque README todavía describe únicamente fase 2, existen `backtest.py`,
  `risk.py`, `execution_config.py`, `research_run.py`, `metrics.py` y el CLI
  `scripts/run_backtest.py`. No reconstruir estos componentes.
- El motor actual utiliza una posición, stop y objetivo fijos, ATR14 en el runner,
  costes, límites de exposición, entradas al siguiente open y métricas básicas.
  Tiene semántica horaria explícita y no revierte en la misma apertura.
  No ofrece trailing, time stop, sizing de momentum, funding, múltiples patas,
  ledger de experimentos ni validación temporal completa.
- `HistoryRequest` y el proveedor admiten únicamente spot 1h. El motor permite
  cortos sintéticos explícitos; eso no constituye una simulación de futuros reales.
- Los CSV auditados de 2022–2025 tienen una hora ausente el 24/03/2023.
  Estar descargados no los convierte en un dataset completo válido. La validación
  actual revisa meses completos, incluso fuera del intervalo solicitado.

El prompt original exige capacidades y mercados que aún faltan. Su grid Donchian
ya tiene 480 combinaciones antes de multiplicar mercados, periodos y costes;
el de reversión tiene 1.536 antes de añadir time stops. El primer batch debe ser
exploratorio, con presupuesto acotado y reglas congeladas antes de ver resultados.
Modificar lookbacks para ajustarlos al historial crea variantes nuevas: no demuestra
la eficacia de las variantes largas originales.

Verificación de esta revisión: 121 tests superados; Ruff lint y formato correctos
(43 archivos Python), ejecutados con `.venv/Scripts/python.exe`. Se verificó la
caché real y el registry vacío. Solo se añadió este documento; no se ejecutaron
backtests ni se modificaron datos, estrategias o el motor.

## Prompt listo para implementar

Implementa Batch 001 como investigación histórica modular en el laboratorio
existente. Sigue AGENTS.md. Conserva contratos, configuración, registry, datos
originales y pruebas. No implementes trading en vivo. Completa cada etapa con sus
tests antes de avanzar. No presentes capacidades pendientes como implementadas.

### 1. Verificar fundamentos y capacidades

Inspecciona el código y ejecuta los checks del proyecto. Actualiza la documentación
de estado de acuerdo con lo realmente probado. No supongas que faltan componentes
solo porque README esté desactualizado.

Mantén decisiones y features dentro de las estrategias; riesgo, tamaño, trailing,
reversiones y ejecución pertenecen a capas reutilizables. Amplía esas capacidades
una sola vez con contratos tipados y tests, sin condicionales por nombre de estrategia
en el motor. Conserva el comportamiento anterior por defecto y documenta migraciones.
Rechaza explícitamente cualquier configuración no soportada.

### 2. Datos y alcance

**Batch 001A obligatorio: BTC/USDT spot 1h, solo largos ejecutables.**

Usa exclusivamente la caché validada identificada arriba, releyéndola y verificando
su fingerprint. Conserva intacto el bundle. Usa enero de 2022 y las 200 horas previas
como contexto para todas las estrategias; el periodo puntuable común empieza
2022-02-01 y acaba 2023-02-01, extremo exclusivo. Esto permite momentum de 30 días
sin inventar historia. Los indicadores se calculan sobre todo el contexto causal;
el contexto no genera PnL ni operaciones puntuables.

Un subperiodo requiere una vista validada con solicitud coherente y procedencia
del bundle padre. No pases todo el Parquet a una solicitud con fechas incompatibles
ni inventes un nuevo dataset_id como si fuera otra fuente. Guarda identidad del
padre, límites de la vista, contexto e identidad de la derivación.

**Batch 001B: ampliación independiente, condicionada a validación real.**

Intenta preparar BTC spot 1h desde 2023-06-01 hasta 2026-01-01 exclusivo, con
1.440 horas previas de calentamiento: comienza 2023-04-02. Ningún mes de la
solicitud es marzo de 2023. Reutiliza fuentes verificadas o el proveedor público
existente. El importador exige que el manifiesto coincida con la solicitud:
genera procedencia nueva para esta solicitud; no reutilices un manifiesto
incompatible ni debilites su validación. Publica un bundle independiente solo
si todas las comprobaciones pasan. No prometas su aceptación anticipadamente.

No unas los dos tramos como una serie continua. Cada ejecución empieza sin
posición, con capital independiente e indicadores calentados. No mantengas
posiciones ni acumules retornos durante el intervalo excluido. Presenta resultados
por tramo; cualquier agregado debe explicar ponderación y periodos sin observación.
Si falla 001B, conserva el diagnóstico y completa 001A sin fingir historia adicional.

ETH, BNB, SOL, velas 15m y perpetuals quedan fuera de la primera entrega. No se
pueden recuperar velas de 15m a partir de 1h. 4h y 1d son ampliaciones posteriores:
requieren agregación de grupos UTC completos, timestamp de disponibilidad al cierre,
warmup propio, validación/cache de derivados y eliminar supuestos horarios del motor.
200 horas de contexto no equivalen a 200 velas de 4h o 1d.

### 3. Estrategias del primer batch

Implementa módulos independientes con parámetros estrictos, versión, YAML y tests.
Usa las reservas `trend_following` y `mean_reversion`, preservando las configuraciones
anteriores mediante perfiles nuevos. Para momentum utiliza el generador existente.
Relaciona los IDs del informe con nombres y versiones del registry.

**TREND_001 / trend_following**

- Donchian20 sobre las 20 velas anteriores: máximo de high y mínimo de low,
  excluyendo la vela actual mediante shift de una vela.
- Entrada long: close > canal superior y close > EMA200. Short simétrico en tests.
- ATR14 aritmético, conforme al indicador actual; no cambiarlo silenciosamente a
  Wilder. EMA: fijar semilla, `adjust=False` y `min_periods=period` en documentación.
- Stop inicial a 2 ATR de la entrada, usando ATR conocido al cierre de señal.
- Trailing a 3 ATR desde el extremo favorable desde la entrada. Actualizarlo al
  cierre y activarlo solo en la vela siguiente. En largos nunca baja; en cortos
  nunca sube. Combinarlo con el stop inicial sin ampliar riesgo.
- No incluir por defecto el take profit fijo que utiliza hoy el motor. Hacerlo
  opcional en la capa de ejecución antes de llamar a esto TREND_001.
- ADX queda desactivado en esta entrega; no anunciar resultados del filtro.

**MEANREV_001 / mean_reversion**

- Bollinger20 con desviación poblacional (`ddof=0`), multiplicador 2; RSI14 de
  Wilder con semilla documentada y manejo probado de series constantes.
- Entrada long: close < banda inferior y RSI < 30. Short: condiciones simétricas
  con banda superior y RSI > 70.
- Salida long al cierre cuando close >= media o RSI >= 50; ejecución al open
  siguiente. Salida short simétrica. Stop intrabar de 2 ATR14; sin take profit fijo.
- Time stop base desactivado. Variante de 20 velas: contar la vela de entrada
  como primera; al cierre de la vigésima programar salida al siguiente open.
- Filtros EMA y percentil de volatilidad quedan fuera del primer grid. Si se
  añaden después, crear variantes identificadas; percentiles calculados sobre
  historia anterior, nunca sobre todo el dataset.

**MOMENTUM_001_BASE_H1 / time_series_momentum**

- Variante horaria explícita del concepto original, sin cruces de medias.
- `momentum[t] = close[t-1] / close[t-N-1] - 1`, con N = días × 24.
  Mantener este retraso para reproducir la fórmula del prompt; con fills al
  siguiente open no es imprescindible por causalidad, pero sí cambia la estrategia.
- Baseline: 14 días; sensibilidad: 7 y 30 días. No convertir días en número de
  velas sin considerar el timeframe. No afirmar que se probó momentum diario.
- Spot: invertir el 25% del equity disponible al entrar con momentum positivo;
  cerrar al pasar a <= 0. No rebalancear mientras se conserve el signo.
- No imponer stop ATR ni take profit a esta versión: hoy el runner los exige,
  por lo que primero hay que añadir sizing por notional y protección opcional
  como capacidades generales. Mantener topes de capital, exposición y costes.
- Prueba señales short simétricas; no ejecutarlas como spot real.
- Versiones VOL, REGIME y lookbacks 60/90/180 días quedan aplazados. Requieren
  especificar volatilidad, anualización, frecuencia de rebalanceo, capital y contexto
  suficiente. No equiparar la versión BASE a esas variantes.

**CRYPTO_001: estado BLOCKED_DATA; clasificación INSUFFICIENT_DATA.**

No implementar una estrategia vacía ni usar spot como proxy de perpetual.
Documentar requisitos: series spot/perpetual sincronizadas, funding histórico con
timestamp de disponibilidad y settlement, precios de valoración y especificaciones
del contrato. Las variantes carry requieren contabilidad de dos patas, capital,
margen y liquidación. No representar funding desconocido como cero.
Implementar adaptadores cuando haya datos y pruebas reales, no solo interfaces
vacías para marcar una casilla. Esta estrategia debe aparecer como pendiente en
el informe con motivo explícito, sin métricas fabricadas.

### 4. Riesgo y ejecución

Para trend y meanrev: `risk_per_trade_pct: 0.5`, `max_position_pct: 25.0`,
`max_exposure_pct: 100.0`, sin apalancamiento. El riesgo porcentual incluye costes
estimados al stop; un gap puede excederlo. Mantener redondeo de cantidades y
rechazos por mínimos, identificando los filtros como supuestos de investigación.
Momentum usa notional del 25%, no se anuncia como riesgo al stop del 0,5%.

Una posición por ejecución independiente. Un batch coordina experimentos; no es
una cartera conjunta y no se deben sumar sus equities como una cartera financiable.

Señales al cierre y órdenes al siguiente open. Prioridad documentada entre gaps,
salidas programadas y protecciones; stops conservadores en ambigüedad intrabar.
No ejecutar un trailing actualizado con el high de una vela contra el low previo
de esa misma vela. No abrir con señales del calentamiento. Liquidar al cierre
final con costes, registrando que es una liquidación administrativa del estudio.

Long es el resultado principal. Short y combined opcionales solo bajo modo
`synthetic`, separados y rotulados como diagnósticos sin préstamo, margen ni
funding; no confundirlos con futuros operables. Cualquier cambio a la política de
reversión del motor debe ser explícito y probado.

### 5. Diseño temporal y presupuesto de experimentos

Todas las fechas UTC, inicio inclusivo y fin exclusivo. Congelar estas reglas,
grids, costes y criterio de selección antes de calcular rentabilidades.

| Batch | Train | Validation | Test final |
| --- | --- | --- | --- |
| 001A | 2022-02-01 a 2022-09-01 | 2022-09-01 a 2022-11-01 | 2022-11-01 a 2023-02-01 |
| 001B, si válido | 2023-06-01 a 2024-07-01 | 2024-07-01 a 2025-01-01 | 2025-01-01 a 2026-01-01 |

Cada partición empieza plana y termina liquidada; permite contexto anterior para
features, sin contabilizar sus retornos. No cruzar operaciones entre particiones.
El test 001A no es entrenamiento de 001B. Si los resultados de 001A inspiran
cambios, registrarlos antes de abrir el test de 001B; no reutilizar 001A como
confirmación independiente de esos cambios.

Grid acotado, sin producto cartesiano adicional:

- Trend: base y cuatro vecinos cambiando una variable: Donchian 10 o 30;
  trailing 2 o 4. EMA200 y stop2 fijos. Total: 5.
- Meanrev: base y cuatro vecinos: Bollinger std 1,5 o 2,5; umbrales RSI 25/75;
  time stop20. Total: 5.
- Momentum: lookbacks 7, 14 y 30 días. Total: 3.

Total: 13 configuraciones por tramo para train. Registrar todas, también fallidas,
rechazadas y sin operaciones. No ampliar el grid tras mirar los holdouts.

Seleccionar por estrategia solo en train bajo costes base: elegibilidad mínima
20 trades cerrados, retorno neto positivo y drawdown <= 25%; maximizar Sharpe de
retornos diarios, desempatar por menor turnover y finalmente ID lexicográfico.
Si ninguna es elegible, conservar la baseline como diagnóstico, sin llamarla
selección exitosa. Estos umbrales son reglas operativas, no garantías estadísticas.

Validation sirve como auditoría del candidato congelado, sin cambiar parámetros.
Si se decide iterar, abrir otro batch y registrar que validation ya fue observada.
Test se ejecuta una sola vez por candidato y escenario de costes predefinido.
Comparar tres estrategias también es selección: no escoger una ganadora por test
y presentar el mismo test como prueba independiente de esa elección.

Walk-forward exploratorio de 001A: train expansivo desde febrero; tests mensuales
julio, agosto, septiembre y octubre de 2022; reelección solo con meses anteriores
a cada test. Agregar únicamente ventanas de test, con liquidación entre ventanas.
Estos meses se solapan con train/validation estáticos: informar el solapamiento,
no contarlos como evidencia independiente ni incluir noviembre–enero.
Monte Carlo se aplaza; no añadir un placeholder que finja soporte.

### 6. Costes, métricas y diagnósticos

Escenarios por orden, en unidades porcentuales del proyecto:

| Escenario | trading_fee_pct | slippage_pct | spread_pct |
| --- | ---: | ---: | ---: |
| Sin fricción | 0 | 0 | 0 |
| Base asumido | 0.05 | 0.02 | 0.01 |
| Adverso | 0.10 | 0.10 | 0.02 |

Son supuestos, no tarifas históricas verificadas. Spread completo: aplicar media
horquilla por lado, como el modelo actual. Cobrar entrada y salida; no descontar
dos veces el slippage ya incorporado al precio. Seleccionar exclusivamente con
escenario base. Ejecutar sensibilidad de costes sobre los candidatos congelados.
Funding es no aplicable para spot; en derivados ausentes es desconocido.

Guardar retorno, PnL neto, drawdown, trades, win rate, profit factor, ganancias y
pérdidas medias, expectancy, duración, exposición, turnover, fees y coste de
slippage separado del spread. Definir cada denominador y unidad. Sharpe/Sortino
con retornos diarios UTC, tasa libre de riesgo asumida cero y anualización sqrt(365).
CAGR, volatilidad anualizada y Calmar deben indicar duración observada; devolver
null con motivo para denominadores nulos, ausencia de pérdidas u otras métricas
indefinidas. No convertir indefinidos en ceros ni infinito en JSON.

Comparar BTC buy-and-hold al 100% y una referencia al 25% con resto en efectivo,
ambas con iguales fechas y costes. Mostrar diferencias de exposición y riesgo.

Regímenes descriptivos causales: close respecto a EMA200 horaria para tendencia;
ATR14/close respecto a su mediana móvil de las 720 horas anteriores para volatilidad.
Etiquetar información insuficiente como unknown. No usar etiquetas retrospectivas
de bull/bear como si fueran conocidas en tiempo real. Para trades usar régimen
del cierre de señal y para retornos diarios el régimen conocido al inicio del día;
documentar ambos denominadores. Desglose mensual y por año realmente observado.

Gráficos: equity, drawdown, retornos mensuales, distribución de trades y Sharpe
móvil de 90 días solo donde haya ventana completa. Ausencia de datos debe verse
como ausencia, no como curvas vacías con métricas aparentes.

### 7. Evidencia, almacenamiento y clasificación

Implementar ledger SQLite y artefactos JSON/Parquet inmutables bajo
`results/batch_001/<batch_run_id>/<experiment_id>/`; añadir `results/` al ignore
antes de escribir datos. Conservar summaries por ejecución, sin sobrescribirlos.
El `batch_001_summary.md` de cada ejecución muestra las cuatro familias por separado.

Registrar estado started/completed/failed/skipped, motivo, todos los parámetros,
config resuelta, estrategia/versión, dirección, mercado, partición, fechas,
calentamiento, dataset padre/derivado, costes, métricas, trades, equity, rechazos,
seed, entorno y código. Si Git no tiene commit o hay cambios sin registrar,
guardar ese estado y un hash del código relevante; no afirmar una revisión limpia.
No leer ni almacenar secretos para calcular procedencia.

Reglas en orden para clasificación; guardar además banderas individuales para
no ocultar fallos cuando se cumplan varios criterios:

1. INSUFFICIENT_DATA: faltan datos/capacidades necesarias, menos de 30 trades
   cerrados en test, menos de 90 días de test o métricas necesarias indefinidas.
2. FAILED_AFTER_COSTS: test positivo sin fricción y <= 0 bajo costes base.
3. FAILED_OOS: retorno test con costes base <= 0, profit factor < 1 o
   drawdown test > 25%, sin haberse activado la regla anterior.
4. PROMISING_BUT_UNSTABLE: supera lo anterior, pero la evidencia sigue siendo
   exploratoria o falla sensibilidad temporal/de costes/de parámetros en train.
   La bandera de sensibilidad exige al menos la mitad de candidatos train con
   retorno positivo y drawdown <= 25%, y candidato positivo en test adverso.
5. ROBUST queda deshabilitada en este batch. Una etiqueta así requerirá un
   protocolo posterior registrado, más evidencia independiente y controles de
   selección múltiple. Ni 13 meses ni muchos trades horarios bastan por sí solos.

Reportar tamaño de muestra y cautelas junto a las métricas. Las etiquetas son
diagnósticos de investigación, no recomendaciones de inversión.

### 8. Orden y aceptación

Primero verificar motor y datos; después implementar las capacidades generales
faltantes; después features y tres estrategias; después ledger/splits/batch;
finalmente ejecutar y reportar. No ejecutar rentabilidades reales antes de que
las pruebas de esas capas pasen.

Tests obligatorios: valores manuales de indicadores, señales long/short,
prefix-invariance en features/señales, next-open, costes en ambos lados,
stop y trailing con gaps/ambigüedad, time stop, momentum sin órdenes repetidas,
sizing/topes, separación de particiones, calentamiento, benchmark con costes,
ledger inmutable y CLI offline individual/batch. Fixtures sintéticos son válidos
para tests; nunca deben aparecer como evidencia histórica.

Ejecutar pytest, Ruff lint y formato. Inspeccionar diff y archivos no seguidos.
Entregar comandos realmente ejecutados, configuración congelada, paths de
resultados y limitaciones. Una estrategia bloqueada debe aparecer como tal;
no declarar las cuatro implementadas ni llamar backtest a una prueba de indicadores.
