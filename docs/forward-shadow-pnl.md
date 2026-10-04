# Shadow Position / Hypothetical PnL — forward SIGNAL_ONLY

La contabilidad vive exclusivamente en `forward/shadow.py`, con proyecciones en
`shadow_reporting.py` y reconstrucción de lectura en `shadow_reconstruct.py`.
No modifica lab.py, experimentos Trend RSI, estrategias, filtros ni motores históricos.
Las cuentas BASELINE y OPTIONAL_15M_FILL son alternativas independientes, nunca cartera.

## Integración y seguridad

`ForwardEngine.accept` abre el observador solo para intents publicados. Un vínculo
explícito signal_id une ambas alternativas. Los datos de observación no se usan para
admitir señales, cambiar stops o recalcular sizing. La ocupación y equity legacy del
forward siguen gobernando esas decisiones. Se reutiliza la función canónica de PnL
lineal en el saldo legacy, con la misma fórmula anterior.
`allow_live_trading: false`, `trading_enabled: false` y los brokers GET-only continúan
intactos. No place_order, cancel_order ni close_position; tampoco órdenes demo.

Checkpoint transaccional: posiciones completas, IDs, barras, costes, extremos y cierres.
El reinicio con el mismo stream restaura todo; un intent repetido no crea otra posición.
Un cambio de código/config crea otro stream según el contrato forward existente: no
migra posiciones entre versiones ni modifica sesiones anteriores. El proceso externo
ya arrancado mantiene su versión cargada; no se reinicia automáticamente.

Eventos nuevos SHADOW_POSITION_OPENED, SHADOW_POSITION_UPDATED (solo incertidumbre)
y SHADOW_POSITION_CLOSED con shadow_position_id. Los cierres legacy sin ese campo se
conservan por compatibilidad: no contarlos como trades del nuevo observador. El journal
es append-only; shadow_trades.csv es su proyección de cierres única por posición.

## Precios, unidades y costes

Solo Instrument lineal de cantidad base validado por el broker. quantity es ETH/BTC:
contracts × contract_size. Se valida contra target_quantity, lot_size y min_size.
La moneda monetaria se toma de settlement_currency; USD y USDC no se suman entre sí.

Entrada = estimated_entry_price del intent. Contiene ya slippage y medio spread del
perfil BASE heredado; el precio de referencia es la cotización observada (ask para
la estrategia LONG actual). Se mantiene ese supuesto conservador del forward: no se
reinterpreta el ask como midpoint ni se añade otra vez el ajuste al precio de entrada.
CostModel original aplica el ajuste adverso al precio de salida. Comisiones calculadas
sobre notional de cada fill. ZERO/ADVERSE no se mezclan con BASE.

- LONG gross = (precio - entrada estimada) × cantidad base; SHORT invierte el signo.
- Realized gross usa ambos precios ajustados; net = gross - entry_fee - exit_fee.
- Reference gross usa precios de referencia sin ajuste; net = reference gross - total_cost.
- total_cost separa fee, slippage y spread por lado. NO se resta otra vez del gross
  calculado sobre fills ajustados.
- Unrealized gross usa el último close verificado; net estimate incluye el ajuste y
  fee de una salida hipotética a esa referencia, además del fee de entrada.
- Sin funding, liquidación ni réplica del balance de una cuenta de futuros.

## Causalidad y límites de paridad

Baseline observa 1h; optional observa 15m. Ambos usan protective_fill del backtest:
stop intrabar al stop, gap adverso al open, con costes. Stop tiene prioridad frente a
MAX_HOLDING. Timestamp exacto intrabar desconocido: exit_timestamp queda null y se
conservan exit_bar_open/exit_observed_after; nunca inventar la hora de ejecución.
La estrategia MtfStrategy devuelve false en ambas salidas: no existe EXIT_SIGNAL
que implementar para estas variantes.

Solo cuentan velas completas posteriores a la cotización de entrada. 72 horas son
72 barras 1h o 288 barras 15m; no convertir el límite en 72 cuartos. MAX_HOLDING se
marca al cierre de la última barra completa contabilizada. Una primera barra parcial
no incrementa el contador. Por ello el observador puede diferir del cierre legacy
basado en la frontera horaria (hasta una barra), sin alterar aquella ocupación/sizing.
No se afirma paridad económica exacta de las dos contabilidades.

Si la entrada llega unos milisegundos después del open, el OHLC de esa vela incluye
información anterior a la posición: solo se usa su close posterior para excursiones.
Si su rango toca el stop, no se puede ubicar ese toque antes/después de la entrada:
coverage=INDETERMINATE_ENTRY_BAR, PnL abierto desconocido, sin cierre inventado.
MFE/MAE usan high/low completos solo en barras íntegramente posteriores a entrada.
En vela de stop se usan open y stop/fill, evitando extremos posiblemente posteriores
al cierre. Los extremos resultantes son límites observados, marcados por
excursion_quality; no equivalen a MFE/MAE tick a tick.

Ante un hueco no se avanza next_bar, PnL o bars_held. Solo una secuencia recuperada
continua permite seguir; el runner recupera después de auditar todos los feeds
obligatorios. No se consumen recovery_bars parciales ni monitoring_bars como sustitutos.
No se generan entradas retrospectivas. Un dato faltante sigue faltando.

## Salidas y reconstrucción

Nuevas sesiones: shadow_positions.csv, shadow_trades.csv y entry_timing_comparison.csv,
además de las secciones Shadow Trading y Entry Timing Comparison en ambos resúmenes.
Agrupación por estrategia/moneda; siempre HYPOTHETICAL / SHADOW RESULTS. Las estadísticas
son descriptivas, muestran denominadores y valores indefinidos null. La comparación
final de PnL exige que ambas alternativas estén CLOSED, nunca mezcla PnL abierto/cerrado.
Las filas OPEN incluyen fecha as_of: no son cotizaciones en tiempo real.

La utilidad toma una transacción SQLite mode=ro/query_only, sin adquirir el lock del
runner ni abrir Store. Reconstruye intents de la sesión elegida con barras/senales
persistidas de su stream hasta su último evento. Como alternativa usa copias de los
CSV, rechazando si cambian durante la lectura. Solo bars.csv / MARKET_BAR_CLOSED son
historia aceptada: las observaciones auxiliares y staging no prueban continuidad.
Sin vínculo causal signal_id, no inventa parejas. Gaps o barra inicial ambigua se
reportan explícitamente; no afirma posición abierta/cerrada actual fuera de cobertura.

Escribe un directorio nuevo reports/shadow-pnl/SESSION/UTC-id con source_snapshot.json,
hash SHA256/procedencia, shadow_positions_reconstructed.csv,
shadow_trades_reconstructed.csv, entry_timing_comparison.csv y shadow_pnl_summary.md.
No modifica archivos originales ni SQLite; repetir produce otro informe inmutable.
El informe llega al último dato registrado de la instantánea, no necesariamente al ahora.

## Comandos desde la raíz

```powershell
python scripts/preflight_forward.py --technical-only
python scripts/shadow_pnl.py 20260929T044711Z-407b9289e807
# Solo cuando el usuario decida arrancar una nueva sesión (no junto a otro runner):
python scripts/run_forward.py --mode signal-only --config configs/forward/okx_demo.yaml
# Consultar posteriormente usando la sesión deseada:
python scripts/shadow_pnl.py <SESSION_ID>
```

El forward activo no necesita reiniciarse para reconstruir sus datos registrados.
Para nuevas sesiones, sus CSV/resúmenes shadow se actualizan en cada heartbeat.
Los cuatro comandos lab.py run trend_rsi_pullback_* no cambian y no se ejecutan
como parte de esta implementación.

## Reconstrucción observada de la sesión solicitada

Instantánea `20260929T220312Z-eb231696`, sesión `20260929T044711Z-407b9289e807`.
Última barra observada: 2026-09-29 22:00 UTC. Ambas alternativas OPEN sin toque de
stop en las barras disponibles; no se afirma su estado posterior. Cantidad 0.702 ETH.

| Alternativa | Entrada | Último precio | Gross abierto USD | Net estimado USD | Costes entrada + salida estimada USD | MFE USD | MAE USD | Barras completas |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| BASELINE | 2695.493705 | 2676.80 | -13.122981 | -15.478200 | 2.828160 | 0.000000 | -13.509081 | 2/72 (1h) |
| OPTIONAL_15M_FILL | 2692.472950 | 2676.80 | -11.002411 | -13.356569 | 2.826569 | 0.398069 | -11.388511 | 7/288 (15m) |

MFE/MAE observados excluyen extremos de la primera barra parcial, marcada explícitamente.
Las cifras netas no restan dos veces el ajuste de entrada. El resultado realizado y
la comparación final de PnL no existen todavía; no inferir superioridad estadística.
Fuente derivada: `reports/shadow-pnl/20260929T044711Z-407b9289e807/20260929T220312Z-eb231696/`.
Los archivos de la sesión activa no fueron editados por esta implementación.

## Archivos y verificación

Creados: src/quant_lab/forward/shadow.py, shadow_reporting.py y shadow_reconstruct.py;
scripts/shadow_pnl.py; tests/unit/test_forward_shadow.py;
tests/integration/test_forward_shadow_integration.py; docs/forward-shadow-pnl.md.
Modificados: src/quant_lab/forward/engine.py y store.py;
docs/forward-signal-only.md y docs/PROJECT_STATE.md.

Las 17 pruebas nuevas dirigidas pasan. Los cuatro validate --full de Trend RSI pasan:
132 / 40872 / 40872 / 40872 previstos. scripts/run_forward.py --help y
scripts/shadow_pnl.py --help correctos, sin iniciar una sesión de red. Las pruebas
forward existentes ejercitan arranque, recovery y bloqueo de mutaciones con mocks.
No se ha vuelto a comprobar la conectividad real OKX ni se ha enviado ninguna orden.
No se modificaron los archivos de lab.py, estrategia RSI, grids o backend histórico.


Actualización con el código final: instantánea `20260929T221843Z-459f1373`.
OPTIONAL tiene una nueva barra 22:00-22:15 UTC: cierre STOP al precio de referencia
2624.63, precio ajustado 2623.9738425, gross realizado -48.086373 USD, net realizado
-49.952446 USD y costes desglosados totales 2.799106 USD. MFE observado 0.398069 USD,
MAE observado -47.625751 USD (límite de vela stop), 8 barras completas de 15m.
BASELINE sigue con última observación 22:00 UTC y las cifras abiertas de la tabla
anterior: todavía no existe vela horaria cerrada posterior en esta instantánea.
No se compara su PnL abierto con el realizado optional como resultado final.
El timestamp exacto intrabar del stop sigue desconocido. La reconstrucción incluye
intents anteriores del mismo stream al consultar sesiones que retoman posiciones;
CSV sin journal advierte que puede faltar esa historia entre sesiones.


Preflight técnico final con árbol estable: **672 passed** en 264.82 s, Ruff check
correcto, 307 archivos formateados y pip check sin dependencias rotas. Los 774 avisos
son deprecaciones Matplotlib del reporting histórico. Recibo:
`reports/forward/preflight/20260929T222325Z-11aed8ce55a1.json`.
Incluye la prueba de reconstrucción de posiciones heredadas entre sesiones.
