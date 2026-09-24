# Propuesta inicial: BTC/USDT spot, 1 hora

Estado actualizado: herramientas de fase 2 implementadas; el historial tiene un hueco
y no está aprobado para backtesting. Ver [auditoría de fase 2](phase-2.md).
Lo siguiente conserva la propuesta original, sin backtest ejecutado. La fase 1 permite
cargar el perfil `configs/profiles/btc_spot_1h/app.yaml`, pero todavía no descarga
datos, valida estos parámetros de estrategia ni simula operaciones. La estrategia
permanece deshabilitada. No se han modificado los perfiles originales.

## Mercado y periodo

- Binance spot, BTC/USDT (símbolo API `BTCUSDT`), velas de 1 hora en UTC.
- Periodo por apertura de vela: desde `2022-01-01T00:00:00Z` inclusive hasta
  `2026-01-01T00:00:00Z` exclusive. Incluye todo 2025.
- Capital inicial: 10.000 USDT simulados. Solo posiciones largas; vender sirve
  exclusivamente para cerrar BTC comprado. Sin préstamo ni apalancamiento.
- Descargar además 200 velas anteriores para calentamiento, sin operaciones ni
  resultados en ese tramo. Exigir datos completos, ordenados, únicos y OHLC válidos;
  detener el estudio ante huecos sin resolver, sin inventar velas.

Las fechas, spot, dirección y límite de una posición son requisitos de este documento:
el esquema actual todavía no dispone de campos para validarlos o ejecutarlos.
El endpoint público de Binance admite `1h` y UTC; la integración sigue pendiente:
[documentación oficial](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#klinecandlestick-data).

## Reglas exactas propuestas

Una referencia sencilla de seguimiento de tendencia, sin optimizar parámetros:

1. SMA50 y SMA200: medias aritméticas de los últimos 50 y 200 cierres, incluyendo
   el cierre actual. TR = máximo de `high-low`, `abs(high-prev_close)` y
   `abs(low-prev_close)`. ATR14 = media aritmética de los últimos 14 TR, sin suavizado
   de Wilder. No emitir señales si falta cualquier valor actual o previo necesario.
2. Estando sin posición, señal de compra al cierre T si `SMA50[T] > SMA200[T]`
   y `SMA50[T-1] <= SMA200[T-1]`. Comprar en la apertura siguiente con costes.
   Una sola posición; sin añadir compras mientras esté abierta.
3. Guardar ATR14 de T. Con precio efectivo de entrada E, fijar stop `S = E - 2*ATR14[T]`
   y objetivo `E + 4*ATR14[T]`. Rechazar entradas con ATR no positivo o S no positivo.
   Stop y objetivo permanecen fijos, sin trailing stop.
4. Cerrar toda la posición por stop, objetivo o cruce bajista:
   `SMA50[T] < SMA200[T]` y `SMA50[T-1] >= SMA200[T-1]`. El cruce provoca venta en
   la siguiente apertura. No abrir cortos. Tras salir, esperar un nuevo cruce alcista.
5. Stop y objetivo se activan desde la entrada. Si una vela toca ambos, ejecutar
   primero el stop. Si abre por debajo del stop, vender a esa apertura; si abre por
   encima del objetivo, usar el objetivo conservadoramente. En otro caso, ejecutar
   al nivel tocado. Aplicar costes de venta a todos esos precios de referencia.
   Si coincide una salida por cruce con un gap, priorizar el stop y después el
   objetivo antes de la salida por cruce. No reentrar en la misma apertura.
6. No ejecutar entradas cuya apertura caiga fuera del periodo. Liquidar cualquier
   posición restante al último cierre de 2025, con costes, identificando esa salida
   como cierre forzado del estudio. Cancelar señales pendientes.

## Riesgo y costes

Presupuesto por operación: `B = patrimonio_actual * 0.005`, inicialmente **50 USDT**.
El tamaño se calcula al ejecutar, con el efectivo disponible y el ATR de la señal.
Exposición máxima del 100%, incluyendo reserva para comisión; nunca endeudarse.

Hipótesis iniciales configurables en el perfil: comisión 0,10% por lado,
deslizamiento adverso 0,03% por lado y spread completo 0,02% (mitad por lado).
Son supuestos de simulación, no tarifas históricas verificadas de la cuenta.
[Binance publica sus tarifas aquí](https://www.binance.com/en/fee/trading).

Convención exacta para el futuro motor: `f = trading_fee_pct/100` y
`a = (slippage_pct + spread_pct/2)/100`. Para referencia P, compra efectiva
`P*(1+a)` y venta efectiva `P*(1-a)`. Comisión en USDT = `cantidad*precio_efectivo*f`.
Stop/objetivo se comparan contra OHLC antes de costes de salida.

Con E y S anteriores, salida esperada por stop `X = S*(1-a)` y pérdida por BTC
`L = E-X + f*(E+X)`. Comprar:

`cantidad = min(B/L, efectivo_disponible/(E*(1+f)))`.

Redondear hacia abajo según los filtros de cantidad del mercado, comprobar el
mínimo nocional y omitir la operación si no es válida. Registrar los filtros usados
y cualquier limitación de su disponibilidad histórica. Un gap o mayor deslizamiento
puede superar el 0,5% presupuestado. El objetivo es 2R por distancia de precio;
la relación neta es inferior por costes.

## Validación y siguientes fases

Mantener estas reglas fijas para una primera referencia. Si posteriormente se ajustan,
usar solo 2022–2023 para selección, 2024 para validación y reservar 2025 para una
evaluación final sin ajustes. Reportar por separado esos tramos, costes, operaciones,
rentabilidad y drawdown. No hay resultados ni evidencia de rentabilidad todavía.

Siguiente trabajo según el roadmap: fase 2 (datos, validación/cache y características),
fase 3 (riesgo, ejecución y métricas), e implementación de la estrategia en su fase.
Cada avance requiere sus pruebas; esta propuesta no adelanta esas capacidades.
