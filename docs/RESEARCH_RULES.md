# Reglas de investigación cuantitativa

Estas reglas gobiernan nuevas hipótesis sin cambiar retrospectivamente protocolos,
umbrales ni resultados existentes. Un test técnico valida software; una clasificación
de research describe evidencia bajo supuestos. Ninguno demuestra rentabilidad futura.

## Causalidad, warmup y ejecución

- Toda feature/señal en T usa solo observaciones disponibles en T. Prohibidos rolling
  centrado, backfill desde el futuro y selección retrospectiva de niveles. Un swing se
  fecha al confirmarse, no en la vela que luego resulta ser su extremo.
- Señal al cierre; entrada como pronto a siguiente apertura. HTF solo disponible al
  cierre de su vela completa. Probar prefix-invariance y fronteras de disponibilidad.
- Warmup es contexto anterior: sin trades contabilizados como periodo de estudio ni
  entradas originadas por señales warmup en lab. Mantener NaN hasta tener historia suficiente;
  no rellenar indicadores para forzar operaciones. Reiniciar features/estado ante huecos
  según el adaptador y comprobar continuidad también durante warmup.
- No inventar velas/funding. Conservar UTC, orden, OHLCV, duplicados, hashes y cohortes.
  Excluir fechas altera la hipótesis: documentar exclusión y usar controles comparables.
- Respetar gaps, stop-first e incertidumbre intrabar. Trailing de vela cerrada solo actúa
  después. La mayor resolución de ejecución MTF puede cambiar fills además de señales;
  no atribuir toda diferencia de retorno al filtro.

## Separación temporal y holdout

| Ámbito | Contrato |
|---|---|
| Lab ordinario | `validation.train`, `validation.validation`, `validation.test`, ordenados y no solapados; `test` es el holdout final. No existe campo `final` |
| Lab WF | Cada fold entrena antes de su TEST; TESTs disjuntos y anteriores al holdout final. Solo TRAIN/base selecciona parámetros por fold |
| Runners históricos | Pueden tener TRAIN/VALIDATION/TEST/FINAL o `final_holdout`; respetar fechas y bloqueo propios, no imponer el schema lab |

Congelar hipótesis, parámetros, regla de selección, ranking, filtros, costes y criterio
de éxito antes de consultar periodos reservados. TRAIN sirve para selección; validation
para diagnóstico previsto; TEST/final para evaluación de la decisión congelada. Nunca
optimizar usando final holdout ni volver a seleccionar parámetros a partir de su resultado.

Lab calcula el grid en los tres periodos y lo ordena solo por TRAIN/base. Es responsabilidad
metodológica no seleccionar retrospectivamente por columnas TEST o supervivencia a filtros
que consultan TEST. Si se reutiliza, declarar holdout consumido y resultados exploratorios;
una validación independiente requiere nuevos datos/protocolo, no renombrar el mismo periodo.
Nuevas MTF y timing reutilizan holdout observado: son diagnósticos, aun cuando pasen gates.

WF se resume con TEST, no TRAIN+TEST. Lab reinicia capital por fold: medianas no son cartera
compuesta. Protocolos históricos pueden usar selección fija o encadenados específicos;
no mezclar sus convenciones. Ventanas/operaciones solapadas no son observaciones independientes.

## Costes, riesgo y métricas

Todos los `*_pct` usan porcentajes: 0.05 = 0.05% = 5 bps. Lab aplica comisión a ambos
lados y precio adverso por slippage + medio spread. El sizing considera costes, redondeo,
filtros y topes; el riesgo estimado al stop no garantiza pérdida máxima ante gaps.
No confundir límites de entrada con exposición marcada a mercado posterior.

Fijar costes antes de ver resultados. Stress debe ser una ejecución completa con la
misma hipótesis: costes pueden cambiar tamaño, fills y número de trades. No restar una
comisión teórica a la curva existente. Lab rechaza escenarios stress que reduzcan cualquier
coste base. Los defaults de app no son los de todos los batches.

Funding aplica únicamente en runners perpetuos con datos y semántica de settlement.
ZERO de Batch006/MTF desactiva también funding; BASE/ADVERSE conservan el histórico.
Spot no tiene funding y synthetic no lo modela. No interpretar null como cero observado.
Modelos de margen/filtros fijos son supuestos, no réplica completa de tiers de exchange.

Preservar métricas originales: `metrics.py` usa diarios UTC, sqrt(365), risk-free=0,
valores indefinidos null. PF sin pérdidas no es infinito. Comparar retorno con DD,
expectancy, muestra, exposición, turnover y costes; no declarar ganador solo por retorno.

## Reproducibilidad y selección múltiple

Conservar run/backtest ID, configuración original/resuelta, parámetros, versiones,
periodos/warmup, cohortes/exclusiones, fingerprint y SHA256 de datos, code hash, commit,
estado Git, entorno, timestamps y seeds de cualquier simulación aleatoria. No sobrescribir
historia ni adaptar silenciosamente parámetros de horas a barras. Replay de estrategias
antiguas exige su revisión: el registro V1 no mantiene varias implementaciones por nombre.

Registrar todos los intentos, fallos, exclusiones y grids, no solo la mejor curva.
Declarar múltiples comparaciones entre familias, activos, timeframes y parámetros: el
máximo observado aumenta con el número de pruebas. No atribuir significación estadística
ni corrección por selección si el runner no la implementa. Monte Carlo cross-market es
condicional a sus trades y supuestos; documentar seed/muestreo, no presentarlo como nuevo OOS.

Parameter stability: inspeccionar sensibilidad entre valores vecinos predeclarados en
TRAIN y evidencia temporal, evitando escoger picos aislados o recalibrar con holdout.
Robustness: contrastar costes, años/regímenes, número de trades, mercados y timeframes
compatibles sobre periodos/cohortes comparables. Informar comparaciones no ejecutadas como
pendientes. No lanzar sweeps para completar automáticamente un checklist ni crear evidencia
ficticia de robustez donde solo hay un activo o timeframe.

## Clasificaciones exactas y alcance

La nueva capa lab v1 incorpora FAIL/VALID/RESEARCH_PASS/OOS_PASS/ROBUST_PASS/
PAPER_TRADING_CANDIDATE mediante suplementos separados de PASS legacy. Reglas y
exclusión de TEST del gate research: [research-evidence](research-evidence.md).
Los TEST WF de ganadores cambiantes no acreditan robustez de cada configuración;
no se suman trades de ventanas solapadas ni costes alternativos. Reclasificar no
deshace una selección previa basada en TEST. HISTORICAL_CHALLENGE es falsación de
parámetros congelados elegidos con TEST observado, no un holdout independiente.

Las etiquetas no son intercambiables y pueden coexistir. Mantener thresholds originales
en código/plan; no promover metadata de estrategia automáticamente.

| Ámbito / fuente | Etiquetas y significado |
|---|---|
| `lab_reporting.py` | `PASS` / `FAIL`: filtros predeclarados; no promising/validated |
| `strategies/registry.py` | Metadata permitida: `experimental`, `research`, `promising`, `validated`, `rejected`, `deprecated`. El catálogo actual está en research; no es clasificación automática de performance |
| Batch 003–005 | `REUSED_HISTORY_DIAGNOSTIC` principal; secundarios `REJECTED_TRAIN`, `INSUFFICIENT_DATA`, `FAILED_AFTER_COSTS`, `FAILED_OOS`, `PROMISING_BUT_UNSTABLE`; prioridad y mínimos en sus protocolos |
| `study_analysis.py` | `DIAGNOSTIC_ONLY`, `CROSS_MARKET_PROMISING`, `ASSET_DEPENDENT`, `TIMEFRAME_DEPENDENT`, `COST_SENSITIVE`, `REGIME_DEPENDENT`, `INSUFFICIENT_DATA`, `FAILED_GENERALIZATION`; flags descriptivos, no ROBUST |
| Batch006 / `mtf_reporting.py` | `DIAGNOSTIC_ONLY`, `MARGIN_MODEL_ASSUMED`; pueden añadir `INSUFFICIENT_DATA`, `FAILED_AFTER_COSTS`, `COST_SENSITIVE`, `FAILED_TEMPORAL_VALIDATION`, `PROMISING_BUT_UNCONFIRMED` |
| `new_mtf_reporting.py` / `new_mtf_watchlist.py` | Precedencia `RESEARCH_PASS` → `NEAR_PASS` → `RESEARCH_FAIL`; solo research_pass autoriza evaluar V4 |
| `refinement_reporting.py` | `PAPER_TRADING_CANDIDATE` / `ARCHIVE_NO_PAPER`: gates operativos independientes, sin iniciar paper |
| `entry_timing_reporting.py` | Precedencia `TIMING_WORSE`, después `TIMING_IMPROVED` si todos los gates, si no `TIMING_MIXED`; acciones `ARCHIVE_TIMING_VARIANT`, `CONTINUE_RESEARCH`, `NEED_MORE_DATA` respectivamente |

`PROMISING_BUT_UNCONFIRMED` en Batch006/MTF exige FULL BASE retorno>0, PF>1,
Sharpe>0, validation/test/final_holdout positivos, >=30 trades holdout y >=50% folds
TEST positivos. Nunca equivale a validación independiente de historia reutilizada.

**RESEARCH_PASS nuevas MTF** exige simultáneamente FULL BASE retorno>0, PF>=1.10,
expectancy>0, Sharpe>0, DD<=20%, >=100 trades; HOLDOUT BASE >=20 trades, retorno>=0,
expectancy>0, PF>=1; >=9 positivos de exactamente 22 folds TEST BASE; FULL ADVERSE
retorno>-10%, PF>=0.90. Son trece criterios económicos más integridad de folds.

**NEAR_PASS** requiere FULL BASE retorno/expectancy/Sharpe>0, PF>=1.03, DD<=25%,
>=75 trades; ADVERSE retorno>-20%, PF>=0.80; HOLDOUT >=15 trades y >=7/22 folds
positivos; como máximo dos criterios PASS incumplidos. Valores no finitos/incompletos
no pasan. Solo watchlist: no habilita V4, paper ni live. V4 vuelve a evaluarse, no hereda PASS.

Para los gates relativos de timing/refinamiento consultar
[entry-timing-15m](entry-timing-15m.md) y [execution-refinement-design](execution-refinement-design.md).
No recalcular etiquetas con umbrales propios durante un análisis. Un suplemento conserva
la fuente y documenta su versión sin modificar artefactos anteriores.

## Fronteras operativas

Sin live, routing de órdenes ni retiradas. Una etiqueta paper es descriptiva del protocolo,
no un permiso para operar. Los agentes implementan código/configs, tests y análisis
seleccionados; los estudios largos se ejecutan localmente por el usuario salvo petición
específica. La validación técnica no requiere repetir investigación histórica.
