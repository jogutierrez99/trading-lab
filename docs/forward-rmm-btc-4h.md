# RMM BTC 4h: prueba independiente OKX DEMO

2026-10-05. Variante operativa autorizada para continuar mientras ETH no dispone
del warmup requerido. Conserva la estrategia y los parámetros del
[protocolo conjunto](forward-rmm-4h.md): EMA200, momentum180, volatilidad180,
target10%, capital10000, warmup1000 y costes BASE. No es nueva evidencia histórica.

Configuración `configs/forward/okx_demo_rmm_btc_4h.yaml`. Solo BTC AUTO; C
`rmm_btc_long_short_4h` es MAIN seleccionada, D `rmm_btc_long_only_4h_shadow`
permanece SHADOW_CANDIDATE sin órdenes. Resultados y journal separados en
`results/forward/rmm_btc_4h/`. La configuración ETH/BTC original se conserva.

Desde la raíz del proyecto, en CMD:

```bat
.venv\Scripts\python.exe scripts/verify_forward_rmm.py validate --config configs/forward/okx_demo_rmm_btc_4h.yaml
.venv\Scripts\python.exe scripts/verify_forward_rmm.py warmup --config configs/forward/okx_demo_rmm_btc_4h.yaml
.venv\Scripts\python.exe scripts/verify_forward_rmm.py account --config configs/forward/okx_demo_rmm_btc_4h.yaml
```

`account` comprueba ahora BTC: configurar su contrato demo en net_mode, isolated1x.
La comprobación previa ETH no certifica el leverage del contrato BTC. Claves dedicadas
OKX_DEMO_API_* exportadas en esta terminal; no se cargan desde `.env`.

Si ambas comprobaciones pasan, iniciar la observación y dejar la terminal abierta:

```bat
.venv\Scripts\python.exe scripts/run_forward.py --config configs/forward/okx_demo_rmm_btc_4h.yaml --mode signal-only
```

En otra terminal:

```bat
.venv\Scripts\python.exe scripts/notification_watcher.py --db results/forward/rmm_btc_4h/forward.sqlite --startup-message
```

Gate específico: SIGNAL_ONLY>=4h, nuevas evaluaciones confirmadas BTC, heartbeat,
intención ENTRY válida de C, Telegram recibido y ninguna incidencia operativa.
Después detener el runner con Ctrl+C y revisar sus informes. No verificar una
sesión fallida ni usar el journal conjunto. Usar la ruta impresa por el runner:

```bat
.venv\Scripts\python.exe scripts/shadow_pnl.py "RUTA_SESION_BTC"
```

Solo tras cumplir el gate, revisar y confirmar Telegram:

```bat
.venv\Scripts\python.exe scripts/verify_forward_rmm.py verify --config configs/forward/okx_demo_rmm_btc_4h.yaml --session "RUTA_SESION_BTC" --telegram-verified --receipt reports/forward/rmm_btc_verification.json
.venv\Scripts\python.exe scripts/run_forward.py --config configs/forward/okx_demo_rmm_btc_4h.yaml --mode demo-execution --verification reports/forward/rmm_btc_verification.json
```

`RUTA_SESION_BTC` es un placeholder para la carpeta real. El recibo está ligado a
código, configuración, instrumentos y eventos; no sirve para activar ETH/BTC.
Se mantienen todos los guards demo y reconciliación del protocolo original. Live
continúa bloqueado. No se arrancó una observación real ni se enviaron órdenes o
mensajes durante esta implementación; los tests usan datos y transporte simulados.

## Incidencias de conexión y órdenes demo

### Fallo de lectura del reloj en SIGNAL_ONLY

Corrección 2026-10-08: `URLError`, timeout y otros `OSError` del broker GET-only
se propagan como `ConnectionError` sanitizado. Durante la observación activan la
recuperación existente: DATA_GAP, pausa de decisiones, backoff y auditoría REST
antes de reconectar. Si persisten, se detiene al alcanzar `max_reconnects`.
No se utiliza un reloj caducado cuando falla su refresco. Rechazos HTTP/API,
redirects y respuestas inválidas siguen siendo errores; el transporte POST demo
no cambia ni se reenvían órdenes por esta corrección.

Un traceback anterior que solo indica `URLError` no permite identificar DNS,
TLS o timeout. Conservar la sesión fallida y su journal; volver a ejecutar el
comando SIGNAL_ONLY anterior crea otra sesión. No verificar la sesión fallida:
el cambio de código exige una nueva observación válida y recibo vigente.
Verificación con transporte simulado, sin conectar a OKX ni iniciar un forward real.

### Consulta de órdenes demo

Una excepción de transporte durante POST no prueba que OKX rechazara la orden.
SUBMITTING se guarda antes de enviar; conservar journal y clOrdId, sin reenviar.
En la terminal con las claves dedicadas demo, consultar solo mediante GET:

```bat
.venv\Scripts\python.exe scripts/verify_forward_rmm.py order --config configs/forward/okx_demo_rmm_btc_4h.yaml --session "RUTA_SESION_DEMO_FALLIDA"
```

Imprime campos permitidos de la orden durable y su estado exchange. No modifica
journal, posiciones, recibos ni gates, ni envía/cancela órdenes. Orden no localizada
o consulta fallida requiere revisión; no convertir ausencia en rechazo definitivo.
Errores de transporte nuevos distinguen GET/POST y muestran tipo de excepción o
HTTP status sin mostrar URLs, headers, mensajes externos o claves. El traceback
antiguo no conserva la causa original.22 tests RMM dirigidos pasan.

El diagnóstico ahora imprime también el código OKX numérico de un rechazo API,
sin `msg` ni datos privados completos. Si GET devuelve51603, consulta posiciones
y órdenes pendientes del mismo instrumento, solo lectura y campos permitidos.
Estas instantáneas no demuestran ausencia de fills históricos ni descartan otra
cuenta/clave; no cambian SUBMITTING ni autorizan reenvío.27 tests RMM pasan.
Ante51603 el diagnóstico incluye hasta100 fills del instrumento desde60s antes
de submitted_at (endpoint limitado a3 días) y `perm/acctLv/posMode` de account/config.
No muestra UID ni claves, no modifica permisos, ni interpreta una página vacía
como auditoría histórica completa. Confirmar que la clave demo tiene permiso Trade
antes de otra fase de ejecución. Referencia [OKX EEA API](https://my.okx.com/docs-v5/en/).

Verificación:88 tests forward dirigidos pasan; Ruff check/format de los cinco
archivos Python afectados y git diff --check pasan. Validación YAML y preflight
público BTC pasan:1000 velas4h confirmadas continuas, fuente nativa.

## Saldo virtual de trading demo

`account` y cada entrada nueva comprueban por GET que `totalEq` sea finito y positivo.
Un saldo cero o desconocido bloquea antes de crear la orden durable o enviar POST.
Esta comprobación mínima no garantiza margen suficiente ni cambia sizing/capital
congelados. Las salidas reduceOnly no dependen de este guard. El ledger modelado de
10000 USD no deposita fondos virtuales en OKX.

Si el saldo API es cero, revisar la cuenta vinculada a la clave demo. En la web demo,
Assets > Demo trading > My assets > Reset restaura el importe virtual inicial cuando
no hay posiciones ni órdenes pendientes en toda la cuenta, según la
[guía oficial de OKX](https://www.okx.com/en-sg/help/how-do-i-use-demo-trading).
No resuelve por sí solo una orden SUBMITTING incierta: conservar el journal y revisar
la evidencia exchange. Repetir `account` después. Los cambios de código requieren
una nueva fase SIGNAL_ONLY>=4h válida y un nuevo recibo antes de otra ejecución demo.
35 tests RMM dirigidos pasan, incluidos bloqueo sin POST y salida con saldo cero;
Ruff check/format pasan. No se restauró saldo ni se enviaron órdenes desde Codex.
