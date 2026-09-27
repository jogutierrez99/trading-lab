# Protocolo MTF 01–04

Cuatro familias independientes: trend_pullback, bollinger, donchian y ema_adx.
V1 ejecuta el baseline 1h; V2 añade el régimen 4h a los mismos disparadores;
V3 combina alineación 4h/1h/15m; V4 emplea recuperación tras retroceso.
Parámetros fijos, sin optimización ni selección de resultados entre MTF01–03.

## Traducciones deterministas del prompt

- EMA 20/50/200, RSI14 y ADX14 Wilder; Bollinger SMA20 y dos desviaciones
  poblacionales; Donchian de las veinte velas ANTERIORES.
- Retroceso reciente: toque de EMA20/50 o media Bollinger en una de las tres
  velas anteriores, viniendo del lado favorable; recuperación al cierre y
  ruptura del máximo anterior. Cortos simétricos, mínimo anterior.
- Rotura Bollinger: cruce desde dentro al exterior de la banda.
- Cerca del extremo Donchian 1h: percentil del canal >=80% para largos,
  <=20% para cortos. Consolidación V4: rango de las tres velas previas <=2 ATR15m.
- Momentum Bollinger V4: cierre sobre media, pendiente positiva y anchura no
  decreciente; corto invierte precio/pendiente, nunca la expansión.
- V3 trend exige EMA20>EMA50 y ruptura previa en 15m; V4 exige recuperación.
  EMAADX V3 combina EMA20/50 con ruptura20; V4 combina retroceso y ruptura20.

El prompt no define salidas nuevas. Se heredan stop 2 ATR14 de la última vela
1h cerrada y salida temporal a 72 horas, sin objetivo ni salida técnica nueva.
El régimen filtra entradas; no fuerza salidas. Capital independiente 10000 USDT,
riesgo inicial máximo 0,5%, exposición inicial más comisión <=25%, aislado 1x.
ZERO/BASE/ADVERSE copian exactamente los costes de Batch006; financiación real
idéntica en BASE/ADVERSE y desactivada en ZERO. Sin piramidación ni reversión
automática. Reglas de margen/liquidación y ambigüedad intrabar heredadas.

## Disponibilidad, datos y cohortes

Las velas 4h/1h solo se publican cuando están completas y cerradas. Señal al
cierre y ejecución como pronto en la apertura siguiente. Las pruebas comparan
prefijos y fronteras de disponibilidad. Las características se reinician tras
huecos; las posiciones se cierran antes de ellos, arrastrando solo efectivo.

MTF01–02 conservan el histórico original congelado de Batch006: BTCUSDT/ETHUSDT
USD-M, 2020-01-01 a 2026-09-26 exclusivo. Para MTF03 se auditan velas 15m
independientes contra OHLC1h. Se excluyen simétricamente los 18 días con mark
price ausente/discrepante, según autorización del usuario; se repiten V1/V2
como controles junto a V3/V4 sobre exactamente esas mismas fechas. Las dos
discrepancias de volumen BTC se registran; ninguna regla usa volumen.
No se sustituyen los precios originales ni se inventan velas/financiación.

El adaptador de reloj transforma intervalos 15m en unidades del motor horario
existente y revierte todos los timestamps de salida a UTC real. No cambia
precios, cantidades ni tasas. 72 horas son 288 barras de ejecución. V3/V4
observan stops/liquidaciones con mayor resolución: el salto V2→V3 no permite
atribuir toda la diferencia de rendimiento al filtro MTF.

## Validación y fases

Se conservan fechas TRAIN/VALIDATION/TEST/HOLDOUT y los 22 folds de Batch006.
Se evalúa TRAIN global; los folds fijos no ajustan parámetros y ejecutan solo
sus ventanas TEST. Cada segmento continuo también se evalúa independientemente.
Los retornos de segmentos no se suman como si fueran una cartera.
Se completan todas las ventanas anteriores al holdout antes de desbloquearlo.
La historia ya observada es diagnóstica, no OOS nuevo ni paper trading.

MTF04 solo ejecutará SHORT_ONLY y LONG_SHORT para filas LONG_ONLY comparables
con etiqueta heredada PROMISING_BUT_UNCONFIRMED: FULL BASE positivo, PF>1,
Sharpe>0, VALIDATION/TEST/HOLDOUT positivos, >=30 operaciones holdout y >=50%
folds TEST positivos. Si ninguna cumple, se registrará expresamente que no hay
supervivientes. No se relajarán criterios para obtener resultados direccionales.

Se guardan plan previo, código congelado, costes, hashes de datos, ledger,
trades/equity por ejecución, métricas, señales aceptadas/rechazadas y evolución
V1→V4. El seguimiento futuro de señales rechazadas es descriptivo bruto, no
beneficio ejecutado. El retraso mide la edad del toque previo en entradas
llenadas, no un emparejamiento causal de oportunidades V1/V4.
