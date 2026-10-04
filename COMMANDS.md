# Trading Lab — Comandos auxiliares

Referencia rápida de comandos manuales utilizados durante la operación, monitorización, diagnóstico y análisis del Trading Lab.

Este archivo contiene principalmente comandos auxiliares que no forman parte necesariamente del flujo estándar mostrado por Codex.

No sustituye a `README.md`, `AGENTS.md`, `docs/PROJECT_STATE.md` ni a la documentación específica de estrategias o experimentos. Ejecutar los comandos desde la raíz del repositorio.

---

## 1. Notification Watcher

### Arrancar watcher

```shell
python scripts/notification_watcher.py --startup-message
```

**Función:**\
Arranca el watcher de notificaciones del Trading Lab y envía el mensaje de inicio correspondiente.

**Cuándo usarlo:**\
Cuando se inicia el sistema de monitorización/notificaciones y queremos mantener activo el watcher.

**Notas:**\
Requiere la configuración de Telegram y las notificaciones habilitadas (`TELEGRAM_NOTIFICATIONS_ENABLED=true`). El mensaje de inicio se envía después de la primera lectura correcta del registro observado.

---

## 2. Shadow PnL

### Analizar una sesión

```shell
python scripts/shadow_pnl.py <SESSION_ID>
```

Ejemplo:

```shell
python scripts/shadow_pnl.py 20260929T044711Z-407b9289e807
```

**Función:**\
Calcula los resultados/PnL hipotéticos asociados a una sesión concreta de shadow/forward trading y genera informes para su revisión.

**Cuándo usarlo:**\
Después de disponer de actividad en una sesión y querer revisar posiciones, costes y PnL hipotético generado.

**Notas:**\
Sustituir `<SESSION_ID>` por el identificador real de la sesión. El script también acepta un directorio de sesión. Por defecto, guarda los informes bajo `reports/shadow-pnl` y muestra en consola la ruta de salida, no directamente el PnL. Es una reconstrucción offline y no inicia el runner de forward.

---

## Convenciones para futuros comandos

Cuando se añadan nuevos comandos auxiliares a este archivo, utilizar siempre esta estructura:

### Nombre del comando

```shell
<comando>
```

**Función:**\
Descripción breve de lo que hace.

**Cuándo usarlo:**\
Situación concreta en la que debe ejecutarse.

**Notas:**\
Opcional. Añadir únicamente cuando exista alguna precaución, parámetro importante o comportamiento que convenga recordar.

---

## Trend Volatility Breakout V1 — investigación local

Protocolo: [docs/trend-volatility-breakout.md](docs/trend-volatility-breakout.md).
144 configuraciones por mercado/modo; 6072 backtests por experimento completo.
Preparación/validate no simulan; run es para ejecución local por el usuario.

```powershell
python scripts/prepare_lab_1h_prices.py ETHUSDT
python scripts/lab.py validate trend_volatility_breakout_v1_eth_1h
python scripts/lab.py validate trend_volatility_breakout_v1_eth_1h --full
python scripts/lab.py run trend_volatility_breakout_v1_eth_1h
python scripts/lab.py classify trend_volatility_breakout_v1_eth_1h
python scripts/lab.py robust trend_volatility_breakout_v1_eth_1h
python scripts/lab.py publish trend_volatility_breakout_v1_eth_1h
# BTC futuro: misma lógica, sin recalibrar
python scripts/prepare_lab_1h_prices.py BTCUSDT
python scripts/lab.py validate trend_volatility_breakout_v1_btc_1h --full
python scripts/lab.py run trend_volatility_breakout_v1_btc_1h
python scripts/lab.py classify trend_volatility_breakout_v1_btc_1h
python scripts/lab.py robust trend_volatility_breakout_v1_btc_1h
python scripts/lab.py publish trend_volatility_breakout_v1_btc_1h
python scripts/lab.py compare trend_volatility_breakout_v1_eth_1h trend_volatility_breakout_v1_btc_1h
python scripts/lab.py publish-comparison latest
```

Reclasificar crea otro suplemento sin backtests. Publicar no sobrescribe una
publicación anterior ni hace Git. Ninguno conecta esta familia a forward.
