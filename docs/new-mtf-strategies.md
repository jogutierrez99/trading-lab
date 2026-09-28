# Nuevas familias MTF: protocolo congelado para ejecución local

Implementación técnica; ningún resultado histórico nuevo se ha calculado como parte
de este trabajo. Ejecución independiente USD-M perpetual LONG_ONLY, BTCUSDT y ETHUSDT.
No optimización, V3, cortos, paper ni live. Las cuatro familias MTF anteriores,
sus scripts y artefactos se conservan.

## Comandos desde la raíz

```powershell
python scripts/preflight_new_mtf_strategies.py
python scripts/run_new_mtf_strategies.py --phase a
python scripts/run_new_mtf_strategies.py --phase analyze
python scripts/run_new_mtf_strategies.py --phase b
```

Alternativamente, tras preflight:

```powershell
python scripts/run_new_mtf_strategies.py --all
```

En PowerShell sin Python en PATH, sustituir `python` por `.\.venv\Scripts\python.exe`.
`--from-run results/new_mtf_strategies/<run_id_A>` permite fijar la fuente de B o
del análisis; por defecto se toma el último A completado por run_id ordenado.
El análisis solo lee artefactos; no simula ni reescribe. A produce clasificación
y elegibilidad automáticamente. B crea otro directorio, sin modificar A.
Un cambio de código entre A y B obliga a repetir A bajo el código nuevo; ejecutar
solo otro preflight no mezcla resultados de versiones distintas.

## Cohorte y controles

`configs/profiles/new_mtf_strategies.yaml` fija rutas y SHA256 de los planes
MTF existentes. Se comprueban particiones, 22 folds, costes/riesgo/capital,
identidades de contratos/mark/funding, fuentes 15m y exactamente los mismos
18 días excluidos. Cambios o datos locales ausentes causan error explícito.
No hay descarga implícita. Ambas fases usan la cohorte matched, incluso V1/V2.

Se reutilizan `mtf_series.run_batch`, su calendario, bloqueo del holdout,
persistencia, auditoría, métricas y clasificaciones históricas. No se llama a
`mtf_series.run` ni se amplía su matriz congelada. El registro descubre las
cuatro clases nuevas; la lista histórica `mtf_execution.FAMILIES` queda intacta.

Capital independiente 10000 USDT. Stop 2 ATR14 aritmético de la última hora cerrada,
salida temporal 72 horas, sin nuevas salidas técnicas. Riesgo 0.5%, exposición
25%, margen/liquidación heredados. ZERO/BASE/ADVERSE y funding son idénticos al
protocolo MTF original. Los campos `_pct` siguen siendo unidades porcentuales.

## Parámetros y traducciones deterministas

Los indicadores están congelados en código; el esquema solo permite architecture
V1/V2/V4 y trade_mode LONG_ONLY, y rechaza parámetros desconocidos.

| Familia | Reglas fijas |
|---|---|
| supertrend_pullback | ATR10 Wilder (media inicial de 10 TR, primera TR indefinida), multiplicador 3. Bandas finales recursivas; dirección inicial alcista cuando existe ATR. Cambio bajista al cerrar debajo de banda inferior final, alcista encima de superior final; igualdad mantiene dirección. Línea inferior si alcista, superior si bajista. |
| keltner_breakout | EMA20 ± 2 ATR20 aritmético; pendiente EMA20 positiva; close>upper y close anterior<=upper anterior. Evento nuevo, sin señal por mera permanencia fuera del canal. |
| roc_momentum | ROC porcentual 5/20; ROC20>0, ROC5>ROC20 y ROC5 creciente; cierre supera máximo de 20 velas anteriores (`shift(1)`). |
| volatility_expansion | Bollinger SMA20, std poblacional ×2, ATR14. Anchura debajo de mediana de 100 anchuras incluyendo la actual; ventana completa, sin futuro. Compresión en alguna de las 3 velas previas, cierre>máximo20 anterior y anchura estrictamente creciente. |

Supertrend V1: tendencia alcista y cierre sobre línea; toque por high/low de línea
Supertrend o EMA20 en 1–3 velas anteriores, tendencia válida ininterrumpida desde
el toque, después cierre alcista (close>open) y close>high anterior.

V2 añade último régimen 4h cerrado: Supertrend alcista; Keltner close>EMA20 y
pendiente positiva; ROC20>0 y no decreciente (se congela la preferencia del prompt);
volatility EMA50>EMA200. V1 no exige régimen 4h.

V4 activa una oportunidad al publicarse un setup 1h cerrado: Supertrend usa
el pullback horario con tendencia válida; Keltner/ROC su evento V1; volatility
la compresión horaria actual. Oportunidad válida como máximo 4 horas desde ese
cierre; una nueva señal horaria sustituye a la anterior. Un régimen 4h incompatible
invalida la oportunidad. Máximo un trigger por oportunidad, aunque el motor
rechace la orden. Las señales no se rearman solo porque la posición se cierre.

- Supertrend/Keltner: toque EMA20 de 15m después de publicarse el setup, recuperación
  en una vela posterior con close>open y close>high anterior. El cierre debe seguir
  por encima de la línea Supertrend horaria / media Keltner horaria; pérdida de
  estructura invalida el setup. No se admiten toques anteriores al cierre horario.
- ROC: rango de las 3 velas 15m anteriores <=2 ATR14 anterior; cierre alcista por
  encima del máximo de esas tres velas. Las tres deben empezar tras el setup 1h.
- Volatility: misma consolidación/ruptura, más rango actual>ATR14 anterior y ATR14
  creciente. El origen de la oportunidad siempre es compresión 1h, nunca 15m sola.

Disponibilidad utiliza `closed_features` y `complete_bars` existentes; solo se
añade un callback opcional con el comportamiento histórico como valor por defecto.
No se usan agregados parciales. Indicadores y setups nuevos se reinician al encontrar
huecos, también al faltar agregados completos de timeframe superior. Warmup permanece
NaN y no produce entradas. Señal al cierre, entrada como pronto a siguiente apertura.
En V4 las barras del trigger deben ser posteriores a la publicación horaria.

## Fases y RESEARCH_PASS

A = 4 familias × 2 activos × V1/V2 = **16 configuraciones**, cada una con todos
los escenarios/particiones/folds/segmentos heredados. No significa 16 backtests:
el número de ejecuciones es configuraciones ×3 costes ×ventanas del plan.

Se exige simultáneamente:

- FULL BASE: retorno>0, PF>=1.10, expectancy>0 USDT, Sharpe>0, DD<=20%, >=100 trades.
- HOLDOUT BASE: >=20 trades, retorno>=0, expectancy>0, PF>=1.
- WF BASE: >=9 positivos de exactamente los 22 folds TEST; se registra también razón.
- FULL ADVERSE: retorno>-10%, PF>=0.90.

Métricas ausentes, NaN o infinitas fallan; PF indefinido por ausencia de pérdidas
no se convierte a infinito. Filas obligatorias ausentes/duplicadas causan error;
folds incompletos no pueden pasar. Criterios y fallos se guardan por configuración.
Las etiquetas heredadas se mantienen y coexisten con la etiqueta nueva.

B = un V4 por asset+family con algún RESEARCH_PASS en V1 o V2 (0–8 configuraciones).
Sin supervivientes se registra omisión explícita y no se cargan datos para B.
V4 se evalúa nuevamente con los mismos criterios: nunca hereda PASS.
La selección utiliza holdout observado: estas simulaciones son investigación
diagnóstica, no validación OOS independiente ni candidatas paper/live.

Comparaciones V2−V1 y V4−referencia incluyen retorno, PF, expectancy, DD, trades,
costes, Sharpe y folds positivos. Referencia V4: mayor retorno FULL BASE entre
V1/V2, después Sharpe, después V1 en empate; regla descriptiva congelada que no
afecta a elegibilidad. Se muestran ambos valores y delta, sin ganador subjetivo.

## Artefactos y preflight

Cada invocación crea `results/new_mtf_strategies/<run_id>/`. Plan, configuración,
provenance, snapshot, protocolo, resumen y verificación están en la raíz.
El lote vive en `phase_a/<batch_id>/` o `phase_b/<batch_id>/`, con:
plan.json, config.json, results.csv, metrics.csv, trades.csv, segment_metrics.csv,
fold_metrics.csv, holdout.csv, cost_sensitivity.csv, research_pass.csv,
v4_eligibility.json, architecture_deltas.csv, summary.md, verification.json,
artifact_manifest.json, ledger SQLite y trades/equity por ejecución.
La raíz también tiene un manifiesto que cubre los artefactos del lote.

Preflight ejecuta pytest -q, ruff check ., ruff format --check . y pip check.
Cada invocación crea una raíz temporal exclusiva para pytest (también heredada
por sus subprocesos) y desactiva cacheprovider. Así no reutiliza `pytest-of-joshu`
ni `.pytest_cache` creados con otra cuenta de Windows. No modifica ACL ni borra
carpetas compartidas. El recibo registra esa raíz y conserva la salida completa;
los fallos muestran además el final del diagnóstico en consola.
Guarda recibos únicos bajo reports/new_mtf_strategies/preflight, vinculados al hash
de código/config/tests y versiones de Python/dependencias. Código cambiado durante
o después de los checks, checks ausentes o fallidos bloquean el runner.
B verifica hashes del run A y recalcula elegibilidad desde results.csv.
No se sobrescriben resultados ni recibos. No hay reanudación de lotes parciales:
un fallo conserva los artefactos incompletos y una repetición obtiene otro run_id.

## Inventario de implementación

- Nuevos módulos y YAML homónimos: mtf_supertrend_pullback, mtf_keltner_breakout,
  mtf_roc_momentum y mtf_volatility_expansion, bajo src/quant_lab/strategies y
  configs/strategies respectivamente.
- Soporte nuevo bajo src/quant_lab: new_mtf_features.py, new_mtf_strategy.py,
  new_mtf_runner.py, new_mtf_reporting.py y new_mtf_preflight.py.
- Nuevo perfil configs/profiles/new_mtf_strategies.yaml, este documento y los
  scripts run_new_mtf_strategies.py / preflight_new_mtf_strategies.py.
- Tests nuevos: los cuatro test_mtf_<familia>.py, test_new_mtf_architectures.py,
  test_new_mtf_protocol.py y tests/integration/test_new_mtf_runner.py.
- Archivos existentes modificados por esta ampliación: mtf_features.py (callback
  opcional), tests/unit/test_config.py y tests/unit/test_strategy.py (expectativas
  del catálogo ampliado). No se altera ninguna fórmula o familia histórica.

La integración usa 21 ejecuciones sintéticas pequeñas del motor existente; la
prueba de A→B emplea fixtures de métricas, no un batch histórico. Se comprueban
los trece umbrales, integridad de artefactos, preflight caducado, deduplicación
de elegibilidad, omisión de B sin supervivientes y evaluación independiente de V4.

Verificación técnica del 27-09-2026: preflight completo aprobado (pytest, Ruff
check, Ruff format --check y pip check). Comprobación offline de identidades de
datos, 22 folds y 18 exclusiones aprobada. No se ejecutó ninguna fase histórica.
Los recibos completos con salidas y fingerprint quedan en el directorio de
preflight indicado arriba; no se altera ni elimina el recibo del primer intento.

## NEAR_PASS: seguimiento sin progresión automática

La precedencia es RESEARCH_PASS, después NEAR_PASS, después RESEARCH_FAIL.
Los trece criterios económicos de RESEARCH_PASS y el booleano `research_pass`
no cambian. La elegibilidad V4 sigue usando exclusivamente ese booleano.

NEAR_PASS requiere simultáneamente FULL BASE retorno>0, expectancy>0, Sharpe>0,
PF>=1.03, DD<=25%, trades>=75; ADVERSE retorno>-20%, PF>=0.80;
HOLDOUT trades>=15; >=7 positivos entre los 22 folds. Además puede incumplir
como máximo dos de los trece criterios PASS. Métricas no finitas o folds
incompletos impiden NEAR_PASS. La integridad es una condición adicional, no un
decimocuarto criterio económico. No hay score ni ranking de calidad.

Los nuevos runs añaden research_classification.csv, near_pass.csv y la sección
NEAR_PASS WATCHLIST al resumen. Se registran criterios booleanos PASS y mínimos,
fallos exactos y su número, motivo, valor/umbral y diferencia firmada en unidades
nativas. Para límites estrictos, igualar el umbral no basta. Las categorías de
problema se enumeran sin asignar una prioridad subjetiva. Orden: asset/family/architecture.

Para clasificar historia existente SIN ejecutar backtests, SIN exigir que el código
actual coincida con el antiguo y SIN modificar sus artefactos:

```powershell
python scripts/classify_new_mtf_results.py
python scripts/classify_new_mtf_results.py --run 20260927T174926Z-38873feafe95
```

El comando predeterminado elige el último A completo con entradas válidas; los
runs rechazados se registran en verification.json. `--run` exige exactamente ese
run y falla si no es válido. Se verifican hashes de métricas, planes, resumen,
provenance, verificación y elegibilidad; no se vuelven a recorrer todos los trades.
Se confirma que los thresholds PASS y la elegibilidad original siguen idénticos.

Salida complementaria exclusiva en
`reports/new_mtf_classification/<run_id_A>/<report_id>/`: research_classification.csv,
near_pass.csv, summary.md (resumen original más extensión), provenance.json,
verification.json y artifact_manifest.json. Cada invocación crea otro report_id;
la clasificación es determinista. El clasificador no importa ni invoca un runner
de experimentos ni requiere un preflight nuevo para leer resultados anteriores.
Las comprobaciones normales de preflight/código de los runners A/B siguen intactas.
