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

## Hipótesis intradía V1 — investigación local

Protocolo: [docs/intraday-strategies-v1.md](docs/intraday-strategies-v1.md).
Una configuración por familia, BTC/ETH, tres modos y BASE/ADVERSE;
120 backtests por experimento incluyendo diagnósticos anuales independientes.
Precios USD-M 15m locales con ejecución synthetic; funding no modelado.

### Validar las dos definiciones y sus datos

```powershell
& .\.venv\Scripts\python.exe scripts/lab.py validate volatility_breakout_intraday_v1_btc_eth_15m
& .\.venv\Scripts\python.exe scripts/lab.py validate volatility_breakout_intraday_v1_btc_eth_15m --full
& .\.venv\Scripts\python.exe scripts/lab.py validate range_mean_reversion_v1_btc_eth_15m
& .\.venv\Scripts\python.exe scripts/lab.py validate range_mean_reversion_v1_btc_eth_15m --full
```

**Función:** Revisa configuración, contratos y, con FULL, integridad y cobertura local.

**Cuándo usarlo:** Antes de ejecutar las pruebas históricas; no hace backtests.

### Ejecutar cada familia

```powershell
& .\.venv\Scripts\python.exe scripts/lab.py run volatility_breakout_intraday_v1_btc_eth_15m
& .\.venv\Scripts\python.exe scripts/lab.py report volatility_breakout_intraday_v1_btc_eth_15m
& .\.venv\Scripts\python.exe scripts/lab.py run range_mean_reversion_v1_btc_eth_15m
& .\.venv\Scripts\python.exe scripts/lab.py report range_mean_reversion_v1_btc_eth_15m
```

**Función:** Genera runs e informes separados usando parámetros predeclarados.

**Cuándo usarlo:** Ejecución histórica local por el usuario después de FULL VALID.

**Notas:** Los años se reinician a capital inicial; no sumar sus métricas con TRAIN/VALIDATION/TEST.
Un código distinto no puede reanudar un run anterior; la excepción histórica de resume sigue congelada.

### Comparar y publicar compactos

```powershell
& .\.venv\Scripts\python.exe scripts/lab.py compare volatility_breakout_intraday_v1_btc_eth_15m range_mean_reversion_v1_btc_eth_15m
& .\.venv\Scripts\python.exe scripts/lab.py publish volatility_breakout_intraday_v1_btc_eth_15m
& .\.venv\Scripts\python.exe scripts/lab.py publish range_mean_reversion_v1_btc_eth_15m
& .\.venv\Scripts\python.exe scripts/lab.py publish-comparison latest
```

**Función:** Compara descriptivamente por activo/modo/periodo/coste y publica la allowlist en research_results/.

**Cuándo usarlo:** Tras completar ambos runs.

**Notas:** Conservar IDs impresos. Si se crean otras comparaciones, sustituir latest por el comparison_id
de estas familias. Publicación no hace commit/push ni promociona metadata a validated.

## Literatura V1 — cuatro hipótesis independientes

[Protocolo, bibliografía y supuestos](docs/literature-hypotheses-v1.md).

### Preparar datos, validar y ejecutar localmente

```powershell
Set-Location 'C:\Users\joshu\OneDrive\Escritorio\WEBS\Back_testing\trading-lab'
$py = '.\.venv\Scripts\python.exe'
# Preparación offline explícita; ya realizada en este checkout, repetición verifica identidades.
& $py scripts/prepare_literature_data.py

# 1. Validate Donchian
& $py scripts/lab.py validate donchian_trend_v1_btc_eth_4h
& $py scripts/lab.py validate donchian_trend_v1_btc_eth_4h --full
# 2. Run Donchian
& $py scripts/lab.py run donchian_trend_v1_btc_eth_4h
& $py scripts/lab.py report donchian_trend_v1_btc_eth_4h
# 3. Validate Risk Managed Momentum
& $py scripts/lab.py validate risk_managed_momentum_v1_btc_eth_4h --full
& $py scripts/lab.py validate risk_managed_momentum_v1_btc_eth_1d --full
# 4. Run Risk Managed Momentum 4H
& $py scripts/lab.py run risk_managed_momentum_v1_btc_eth_4h
& $py scripts/lab.py report risk_managed_momentum_v1_btc_eth_4h
# 5. Run Risk Managed Momentum 1D
& $py scripts/lab.py run risk_managed_momentum_v1_btc_eth_1d
& $py scripts/lab.py report risk_managed_momentum_v1_btc_eth_1d
# 6. Validate RSI Momentum
& $py scripts/lab.py validate rsi_momentum_regime_v1_btc_eth_4h --full
# 7. Run RSI Momentum
& $py scripts/lab.py run rsi_momentum_regime_v1_btc_eth_4h
& $py scripts/lab.py report rsi_momentum_regime_v1_btc_eth_4h
# 8. Validate Funding Conditional
& $py scripts/lab.py validate funding_conditional_momentum_v1_btc_eth_1h --full
# 9. Run Funding Conditional
& $py scripts/lab.py run funding_conditional_momentum_v1_btc_eth_1h
& $py scripts/lab.py report funding_conditional_momentum_v1_btc_eth_1h
# 10. Compare — solo tras completar los cinco runs
& $py scripts/lab.py compare donchian_trend_v1_btc_eth_4h risk_managed_momentum_v1_btc_eth_4h risk_managed_momentum_v1_btc_eth_1d rsi_momentum_regime_v1_btc_eth_4h funding_conditional_momentum_v1_btc_eth_1h
# 11. Generate research_results
& $py scripts/lab.py publish donchian_trend_v1_btc_eth_4h
& $py scripts/lab.py publish risk_managed_momentum_v1_btc_eth_4h
& $py scripts/lab.py publish risk_managed_momentum_v1_btc_eth_1d
& $py scripts/lab.py publish rsi_momentum_regime_v1_btc_eth_4h
& $py scripts/lab.py publish funding_conditional_momentum_v1_btc_eth_1h
& $py scripts/lab.py publish-comparison latest
```

**Función:** Prepara snapshots offline inmutables, valida contratos y datos, ejecuta
las cinco pruebas predeclaradas y publica compactos por familia.

**Cuándo usarlo:** Los runs históricos los ejecuta el usuario después de FULL VALID.

**Notas:** Preparación/validate no hacen backtests ni descargas. 564 backtests previstos;
ningún tuning. Warmup/periodos y backend Funding difieren de diario/synthetic; no
comparar por retorno bruto ni sumar años con periodos principales. Conservar IDs;
latest refiere la comparación recién creada si no se generan otras entre medias.
Publicación no hace commit/push, ni conecta a paper/forward/OKX.


## RMM 4h final falsification V1

Protocolo: docs/rmm-final-falsification-v1.md. POST-SELECTION FALSIFICATION,
cuatro candidatos sin optimización. Cada run incluye WF/anuales/BASE/ADVERSE.

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py scripts/lab.py falsification validate --full
& $py scripts/lab.py run rmm_falsification_v1_scaled_180
& $py scripts/lab.py run rmm_falsification_v1_fixed_180
& $py scripts/lab.py run rmm_falsification_v1_scaled_150
& $py scripts/lab.py run rmm_falsification_v1_scaled_210
& $py scripts/lab.py compare rmm_falsification_v1_scaled_180 rmm_falsification_v1_fixed_180 rmm_falsification_v1_scaled_150 rmm_falsification_v1_scaled_210
# Reemplazar por IDs exactos de runs COMPLETE, en este orden:
& $py scripts/lab.py falsification report --runs '<RUN_SCALED_180>' '<RUN_FIXED_180>' '<RUN_SCALED_150>' '<RUN_SCALED_210>'
```

El último comando audita ledger/JSON/equity SHA256 y publica únicamente compactos
nuevos bajo research_results/risk_managed_momentum_v1_final_falsification/<id>/.
No simula, no selecciona vecinos y deja clasificación final pendiente de revisión humana.
