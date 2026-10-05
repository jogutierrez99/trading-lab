# RMM 4h — protocolo de falsación final V1

POST-SELECTION FALSIFICATION / ROBUSTNESS CHALLENGE. Congelado antes de consultar
nuevos resultados históricos. Usa historia ya observada: no es true unseen holdout.
La evidencia anterior descrita por el usuario motiva la selección, pero no se ha
reauditado ni certificado en esta implementación. Sus run IDs están desconocidos.

## Inspección y fórmula exacta

`risk_managed_momentum_v1` 1.0.0 se conserva sin cambios. Momentum en cierre T:
`close[T] / close[T-N] - 1`. EMA200 usa `ewm(span=200, adjust=False,
min_periods=200)`, y ready exige 1000 barras, momentum/RV válidos y RV>0.
LONG: momentum>0 y close>EMA; SHORT: momentum<0 y close<EMA. Sale al cambio de
signo o cero, no al perder EMA. Sin stop, target, trailing, time stop ni rebalanceo.

RV = desviación muestral (`ddof=1`) de los últimos N retornos simples 4h,
incluido el retorno del cierre de decisión, multiplicada por `sqrt(2190)`;
2190=365×24/4. RV es fracción anual, target_volatility_pct=10 significa 10%=0.10.
`fraction[T] = clip(0.10 / RV[T], 0.05, 0.25)`; RV cero/no finita queda NaN,
no genera entrada. No es simplemente un filtro binario: cambia cantidades.

StudyBackend lee la fracción de la barra anterior a la apertura de ejecución.
Señal a cierre, earliest fill next-open; ningún retorno de esa barra futura entra
en sizing. El tamaño se mantiene durante la operación. Riesgo/exposure/fees y
redondeo se delegan a size_entry:

`quantity = floor_to_step(entry_equity * fraction / (adverse_entry_price * (1+fee)))`.

Step 0.000001, mínimo cantidad 0.000001, notional mínimo10. Cap posición25%,
cap exposición100%, sin apalancamiento; el cap a entrada no limita mecánicamente
la exposición posterior marcada a mercado. Una posición, sin piramidación ni
reversal en la misma apertura. Capital10000 independiente por activo/modo/periodo;
liquidación a final. Synthetic sobre USD-M: funding, borrow y liquidaciones no modelados.

## Candidatos y artefactos congelados

| Candidato | Activo | Modo |
|---|---|---|
| A | BTCUSDT | LONG_ONLY |
| B | BTCUSDT | LONG_SHORT |
| C | ETHUSDT | LONG_ONLY |
| D | ETHUSDT | LONG_SHORT |

Siempre4h. Centro EMA200/momentum180/RV180/target10. SHORT_ONLY no es candidato.
No portfolio ni sustitución por un vecino más rentable. `frozen_candidates.yaml`
guarda planes resueltos, costes, datos, hashes de archivos/config/código y criterios.
`lab.py falsification validate` rechaza cambios en los archivos fijados: otro
protocolo necesita versión/carpeta nueva. No tocar app/risk globales ni fuentes.

Precios locales existentes: 4h completos agregados offline de quarters15m, warmup1000,
2020-01-01→2026-09-26 exclusivo, sin rellenar historia.
BTC ID1000ebd0bbbc0ce230d83c1fc644467bbb3e0d1de001b66d5da4cf2015355f39;
ETH ID2b5103f04503d4870c9a056504c33d4715c4ec3e20caa57fd1b7c6dcff7d6686.
FULL verifica hashes, fingerprint/OHLCV, cobertura y warmup con el loader existente.

## Partición complementaria y WF

TRAIN early: 2020-07-01→2022-07-01.
VALIDATION middle: 2022-07-01→2025-07-01.
TEST recent: 2025-07-01→2026-09-26.
Son nombres del schema lab; reutilizan historia, no independencia restaurada.

| Fold | TRAIN (24 meses) | TEST (6 meses) |
|---|---|---|
| 1 | 2020-07-01→2022-07-01 | 2022-07-01→2023-01-01 |
| 2 | 2021-01-01→2023-01-01 | 2023-01-01→2023-07-01 |
| 3 | 2021-07-01→2023-07-01 | 2023-07-01→2024-01-01 |
| 4 | 2022-01-01→2024-01-01 | 2024-01-01→2024-07-01 |
| 5 | 2022-07-01→2024-07-01 | 2024-07-01→2025-01-01 |
| 6 | 2023-01-01→2025-01-01 | 2025-01-01→2025-07-01 |

UTC, fines exclusivos, TESTs WF disjuntos/anterior al TEST principal. TRAINs
solapan. Warmup anterior solo aporta features: no abre operaciones contabilizadas.
Cada experimento tiene UN único conjunto de parámetros; runner conserva su rama
de referencia fija y ejecuta todos los candidatos, sin seleccionar parámetros ni
descartar candidatos por TRAIN/PASS. `walk_forward.csv` distingue TRAIN/TEST;
summary usa solo TEST: positivos/negativos/ceros, mediana, peor/mejor, std e IQR.
No compone capital ni combina ventanas como observaciones independientes.

## Ablation y vecinos

Cuatro experimentos ordinarios nuevos, cada uno176 backtests, total704:

- `rmm_falsification_v1_scaled_180`: original V1.
- `rmm_falsification_v1_fixed_180`: misma clase, parámetros y señales; perfil
  separado con `fixed_notional`, position_pct15. Sin clon de Strategy.
- `rmm_falsification_v1_scaled_150`: momentum150 / volatility150.
- `rmm_falsification_v1_scaled_210`: momentum210 / volatility210.

Se usan singleton YAML separados para impedir producto cartesiano150/180/210
y selección WF adaptativa. EMA200/target10 permanecen; no buscar más vecinos.

Control fijo=15% del equity de entrada, fracción constante, no dólares constantes.
Elegido previamente como punto medio de5–25%, sin calibrarlo al resultado. Ambos
usan misma protección/costes/caps/filtros/capital. Comparación con el mismo orden
de magnitud de exposición y sin leverage, pero NO riesgo empíricamente igualado.
El escalado puede estar entre un tercio y5/3 del notional fijo antes de costes.
`sizing_ablation.csv` publica exposición efectiva, ratio entre sistemas, volatilidad
del equity, deltas y ratios descriptivos retorno/exposición y DD/exposición.
Compara también fechas/side de trades: mínimos/redondeo/cash pueden alterar fills.
Fuera de ratio exposición[2/3,1.5] o con fechas diferentes, incrementalidad queda
INCONCLUSIVE; no presentar menor notional como mejora probada del riesgo.
No reescalar ex post ni añadir un sizing ganador.

## Anuales, costes y diagnósticos

Años independientes:2020 desde julio;2021–2025 completos;2026 hasta septiembre26.
Reportados para todos los candidatos, variantes y costes. Accounts reiniciadas,
solapan main/WF: no sumar trades entre clases de ventanas.

BASE explícito fee/slippage/full-spread0.05/0.03/0.01%; ADVERSE0.10/0.06/0.02%.
Comisión a entrada/salida, precio adverso por slippage+medio spread. Stress se
simula realmente y puede variar tamaño/rechazos. SEVERE omitido por alcance opcional.
Return/CAGR/Sharpe/Sortino/DD/PF/expectancy/trades/exposure/contribuciones/costes:
métricas existentes. PF sin pérdidas/null no se convierte en infinito ni cero.
Sharpe/Sortino usan retornos diarios UTC,365 días,risk-free0.

Concentración por celda y pooled train/validation/test DISJUNTOS con capital
reiniciado: netPnL, mejor/top3/top5, % del net profit positivo y del gross profit
positivo, y leave-best-out PnL. Net share puede exceder100%; con net<=0 queda null.
Se eliminan solo trades positivos; no reconstruye curva, CAGR, DD, Sharpe ni
un backtest ejecutable. No pooling de años+WF+main ni capital compartido BTC/ETH.

MFE/MAE reutiliza excursiones OHLC conservadoras y reflexión de shorts; promedios
por lado/winners/losers, cotas superiores incluidas. No precisión tick ni inferencia
de fallo inmediato a partir solo de MAE. Sin stops en esta V1. PnL long/short por
año/main/WF/coste permite revisión; contribución positiva de shorts sola no prueba
diversificación. Dependencia bull/bear/movimientos excepcionales se revisa con años
y concentración; no se inventa un clasificador retrospectivo de regímenes.

## Criterios previos y clasificación

Guías descriptivas congeladas; no optimizar thresholds para pasar:

- FAIL_TEMPORAL: más de la mitad de TESTs WF negativos en BASE o ADVERSE.
- FAIL_COST:2/3 periodos principales ADVERSE con return o expectancy<=0.
- FAIL_GENERALIZATION: TRAIN BASE positivo, validation y test BASE no positivos.
- FAIL_ROBUSTNESS: centro positivo en validation/test BASE y ambos vecinos
  no positivos en ambas ventanas. Revisar también degradación gradual y ADVERSE.
- FAIL_CONCENTRATION: pooled temporal con beneficio positivo desaparece al quitar
  top3 o top3 explica>=80% del net profit. Revisar top1/top5, muestra y costes.
- FAIL_RISK_MANAGEMENT: comparación con exposición/fechas comparables y Sharpe
  no superior/DD sin mejora>5% en todos los periodos principales BASE.

Una sugerencia prometedora exige sin flags,>=30 trades principales BASE,>=5
por periodo/coste, los3 positivos/PF>1/expectancy>0/DD<=25% en ambos costes,
WF estrictamente mayoría positivo en ambos costes, vecinos positivos en validation/test
BASE y mejora de riesgo comparable: mediana Sharpe+0.05 con DD no degradado>5%,
o mediana DD mejor>=5% sin degradación Sharpe. Esto es guía, no promoción.

`conclusion.json` conserva `classification: INCONCLUSIVE` y HUMAN_REVIEW_REQUIRED
hasta revisión humana, más `provisional_classification`/flags para esa revisión.
Las clases finales disponibles son REJECTED/INCONCLUSIVE/PROMISING_BUT_UNCONFIRMED/
DEMO_FORWARD_CANDIDATE. Ningún resultado asigna automáticamente la última; requiere
valorar estabilidad anual, suficiente muestra, excepciones y todas las tablas.
No toca metadata research, forward, OKX, signal-only, Telegram ni trading_enabled.
Una recomendación demo futura sería observación operacional, no validación/live.

## Comandos locales exactos

```powershell
Set-Location 'C:\Users\joshu\OneDrive\Escritorio\WEBS\Back_testing\trading-lab'
$py = '.\.venv\Scripts\python.exe'

# 1. Validate todos (FAST); FULL audita datos sin simular.
& $py scripts/lab.py falsification validate
& $py scripts/lab.py falsification validate --full

# 2. Frozen Candidates Challenge. Incluye 3.WF, 6.Anuales y 7.Cost Stress.
& $py scripts/lab.py run rmm_falsification_v1_scaled_180

# 4. Sizing Ablation: control; comparar con scaled_180.
& $py scripts/lab.py run rmm_falsification_v1_fixed_180

# 5. Parameter Robustness: vecinos predefinidos, ambos obligatorios.
& $py scripts/lab.py run rmm_falsification_v1_scaled_150
& $py scripts/lab.py run rmm_falsification_v1_scaled_210

# 9. Compare tras completar los cuatro, sin seleccionar ganador.
& $py scripts/lab.py compare rmm_falsification_v1_scaled_180 rmm_falsification_v1_fixed_180 rmm_falsification_v1_scaled_150 rmm_falsification_v1_scaled_210

# 8.Concentration y 10.Generate research_results (solo lectura de backtests).
# Sustituir por los CUATRO run IDs impresos; no usar latest ni IDs de experimentos.
& $py scripts/lab.py falsification report --runs '<RUN_SCALED_180>' '<RUN_FIXED_180>' '<RUN_SCALED_150>' '<RUN_SCALED_210>'
```

`run` repite FULL. `falsification validate` audita además el contrato congelado;
ejecutarlo antes del primer run. Mantener el mismo checkout/entorno para los4.
La comparación general usa últimos runs: para análisis definitivo el reporte especializado
exige IDs exactos y plan/código/config/datos iguales. No hay comando WF adicional.
Interrupciones usan `lab.py run EXPERIMENT_ID --resume --check` y luego `--resume`;
conservar fuentes de reuse.json y pasar el ID de continuación al reporte.

## Salidas y envío posterior

Backtests pesados permanecen en `results/<experiment>/<run>/`, ignorados.
Compare: `reports/lab-comparison/<comparison>/`.
Research compacto: `research_results/risk_managed_momentum_v1_final_falsification/`
tiene freeze y archivos iniciales PREPARED_NOT_EXECUTED, sin resultados ficticios.
Cada reporte completo crea un subdirectorio `<UTC>-<id>/`, sin sobrescribir anteriores.
Audita ledger/result/equity SHA, referencias de recuperación y matriz completa;
CSV principales deben coincidir con JSON verificado. Exportación allowlist<=5MB/archivo,
sin equity, SQLite, parquet, barras ni logs. outcome distinto de COMPLETE no usable.
metadata guarda source/run IDs, git revision/status, code hash, environment, dataset
IDs/SHA, sizing, backend y hashes de compactos; desconocidos siguen desconocidos.

Pasar SOLO del subdirectorio de reporte COMPLETE:
ai_summary.md, summary.md, compact_metrics.csv, walk_forward.csv,
walk_forward_summary.csv, sizing_ablation.csv, parameter_robustness.csv,
yearly_diagnostics.csv, concentration_diagnostics.csv, mfe_mae.csv,
long_short_diagnostics.csv, conclusion.json, metadata.json y frozen_candidates.yaml.
No hace falta metrics.csv local: el reporte conserva métricas y diagnósticos necesarios;
si falla, pasar error/outcome y los4 run IDs, no carpetas completas.

## Verificación

Tests de prefijos/cálculos/caps/zero/singletons/folds, CLI y pipeline sintético
con señales iguales/cantidades distintas, reporte compacto, corrupción e inmutabilidad.
No se ejecuta el challenge histórico como prueba de software. Resultado actualizado
al terminar la verificación técnica; ninguna conclusión económica disponible todavía.


Verificación técnica completada: `python -m pytest -q`:939 passed,774 avisos de
Matplotlib/pandas de reporting histórico,347.40s. Tras cerrar el lock de freeze,
los11 tests nuevos dirigidos vuelven a pasar (15.88s), incluyendo cambio de criterios
y cambio del propio lock después de ejecutar. Ruff check/format globales, pip check
y git diff --check correctos; FAST/FULL VALID para los4,176 cada uno/704 total.
Solo fixtures sintéticos; ningún challenge histórico ejecutado.

`configs/research/rmm_falsification_v1.yaml` fija SHA256 del frozen_candidates.yaml.
Ese lock entra en provenance de cada run (configs/*.yaml): reporte rechaza cambiar
criterios tras ejecución incluso si alguien actualiza también el lock local.
La comparación entre fuentes exige el mismo code hash/dependencias; environment
completo se conserva para revisión. El resultado económico anterior no fue reauditable
sin selección explícita de run IDs, por lo que se mantiene desconocido en este protocolo.
