# Clasificación, challenge y cuaderno versionado

Protocolo añadido el **2026-10-04**. El motor, Strategy, indicadores, sizing, costes
históricos y YAMLs de experimentos anteriores permanecen intactos. No se ejecutan
grids, challenges históricos ni forward al instalar esta capa.

## Inspección y decisiones de integración

Se revisaron AGENTS, README, PROJECT_STATE, ARCHITECTURE, WORKFLOW, RESEARCH_RULES,
el protocolo Trend RSI, `scripts/lab.py`, schema/CLI/runner/reporting/comparison/resume,
ExperimentStore/provenance, metrics, StudyBackend, carga/auditoría de datasets,
Strategy/Parameters/perfil, los cuatro YAMLs y los tests existentes. El árbol de
módulos y scripts contiene otros runners especializados: sus protocolos no cambian.

El schema ordinario obliga a train/validation/test y genera un producto cartesiano
de parámetros × mercados × modos. Usarlo directamente para A/B/C habría creado
combinaciones no pedidas y llamado TEST a historia con otra función. Se incorpora
por ello `lab.py challenge` con un perfil estricto en `configs/challenges/`. Reutiliza
`lab_runner.prepare`, sus guards/datos/warmup y `evaluate`/StudyBackend, sin crear
periodos TRAIN/TEST ficticios, sin modificar el runner ordinario ni duplicar señales.

El WF ordinario ejecuta solamente el ganador TRAIN de cada fold. Sus ganadores
pueden ser distintos: esa evidencia describe un procedimiento adaptativo, no cuatro
folds de cada una de las miles de configuraciones del grid. Esta distinción se conserva.

## Clasificación lab v1

Reglas configurables y estrictas en `configs/research/lab_classification_v1.yaml`;
se congela el contenido y SHA256 del perfil en cada suplemento. No sustituye gates
de nuevas MTF/refinamiento ni autoriza operaciones. Cambiar reglas requiere nuevo
perfil/ID y suplemento; comparar políticas distintas exige declararlo.

| Estado máximo | Significado |
|---|---|
| FAIL | TRAIN/VALIDATION no son técnicamente evaluables o su provenance de datos/warmup es insuficiente. |
| VALID | Base de TRAIN/VALIDATION y escenarios adverse presentes terminados, sin error, >=1 trade y métricas principales finitas. No implica rentabilidad. |
| RESEARCH_PASS | VALID + reglas TRAIN/base y VALIDATION/base/adverse; exige además TRAIN/adverse técnicamente evaluable. |
| OOS_PASS | RESEARCH_PASS + reglas TEST/base/adverse. TEST no decide el nivel de research. |
| ROBUST_PASS | OOS_PASS + cuatro TEST de WF de esa misma configuración, con los mínimos temporales establecidos. |
| PAPER_TRADING_CANDIDATE | Todos los anteriores + al menos 30 trades de evidencia OOS sin solapamientos ni duplicados de costes. Etiqueta del protocolo; no habilita paper/forward/live. |

Cada configuración conserva booleanos por etapa y una clasificación máxima mutuamente
excluyente. Los motivos identifican periodo, coste y condición incumplida. VALID se
define sobre evidencia pre-TEST para mantener la independencia de RESEARCH_PASS;
un TEST inválido/fallido impide OOS_PASS, pero no cambia el resultado previo.
Métricas principales: trades, retorno, PF, Sharpe, expectancy y DD. Null/NaN/infinito
no se sustituyen por ceros. En particular PF sin pérdidas sigue siendo indefinido,
conforme a metrics.py; no se inventa un PF infinito para aprobar.

| Gate BASE | Trades >= | PF >= | Sharpe >= | Expectancy | DD <= |
|---|---:|---:|---:|---|---:|
| TRAIN | 15 | 1.10 | 0.25 | >=0 | 15% |
| VALIDATION | 5 | 1.05 | 0.15 | >=0 | 15% |
| TEST | 10 | 1.10 | 0.30 | >0 | 15% |

TEST/base exige además retorno >0. VALIDATION/adverse y TEST/adverse requieren
retorno >0, PF>=1 y expectancy>=0, con métricas calculables. TRAIN/adverse se verifica
técnicamente: no se introduce un umbral económico adicional no pedido.

WF exige exactamente cuatro folds prescritos, solo `wf_N_test`, con fechas del plan:
>=3 retornos BASE positivos, >=3 expectancies BASE no negativas, mediana de retorno
positiva, mediana de expectancy positiva y >=2 retornos ADVERSE positivos. Medianas
descriptivas de periodos con capital reiniciado, no retorno compuesto. Un único fold
espectacular no compensa tres malos. WF TRAIN no participa en este gate.

Una candidata sin los cuatro TEST WF propios no alcanza ROBUST_PASS. El suplemento
muestra separadamente `adaptive_wf` por mercado/timeframe/modo y sus IDs seleccionados;
nunca atribuye la evidencia de otras configuraciones a una candidata fija.

Para el mínimo OOS se cuentan únicamente filas BASE técnicamente válidas: los TEST
WF disjuntos y el TEST final. VALIDATION se añade solo si es completamente disjunto
de los anteriores. Si solapa, se omite entero, sin estimar trades a partir de métricas
agregadas. Se registran periodos incluidos/excluidos. En el protocolo largo actual,
VALIDATION solapa los dos primeros TEST WF y no vuelve a sumarse. TRAIN y ADVERSE
no se suman como observaciones adicionales.

## Independencia de TEST y límites de la reclasificación

`research_stage` proyecta exclusivamente TRAIN/VALIDATION y no recibe métricas de
TEST ni WF para decidir VALID/RESEARCH_PASS. Guarda un hash del conjunto de evidencia
pre-TEST. Solo después de RESEARCH_PASS se ejecuta el gate OOS. Las pruebas cambian
retorno/PF/Sharpe/expectancy/trades/DD de TEST, eliminan TEST o le dan campos arbitrarios
y verifican que research no cambia. Las fechas/cobertura usadas para provenance del
gate research también se limitan a TRAIN/VALIDATION.

Esto es una clasificación secuencial **de artefactos existentes**, no un nuevo bloqueo
pre-ejecución del runner histórico: los grids antiguos ya calcularon todos sus TEST.
La selección y el ranking del runner siguen usando solo TRAIN. El suplemento no prueba
que una persona nunca consultó el holdout, ni convierte reglas introducidas después
del estudio en reglas prospectivas. Si TEST influyó en la candidatura, está consumido.

El lector exige COMPLETE, conteos esperados, IDs/celdas únicos y archivos compactos
coherentes. Hashea sus entradas y registra alcance. Comprueba la cobertura/warmup y
manifests congelados; **no vuelve a auditar bytes de datasets/equity ni trades del ledger**.
Provenance ausente no se inventa. Las referencias de resume siguen siendo necesarias
para la reproducción completa, aunque clasificar/publicar no recorra sus Parquet.

```bat
python scripts/lab.py classify trend_rsi_pullback_v1_single_tf
python scripts/lab.py classify 20260930T043029Z-83c8241784a3
python scripts/lab.py classify trend_rsi_pullback_v1_single_tf --policy configs/research/lab_classification_v1.yaml
```

Un ID de experimento selecciona su último run y exige COMPLETE; no retrocede a uno
antiguo más favorable si el último falló. Un run ID fija la fuente concreta. Cada llamada
crea `reports/lab-classification/<run_id>/<UTC-id>/classification.json`, classification.md,
summary.md y ai_summary.md. No modifica resultados antiguos ni vuelve a simular.
`report` enlaza el suplemento si existe. `compare` mantiene PASS/FAIL legacy y añade
conteos nuevos con perfil/hash cuando exista suplemento vigente. Los conteos globales
repetidos en filas descriptivas del compare no deben sumarse. Clasificación ausente es
ausente, no FAIL ni cero aprobado. Comparaciones antiguas permanecen legibles.

## ETH / HISTORICAL_CHALLENGE

Un solo experimento nuevo: `trend_rsi_pullback_v1_eth_challenge`. ETH challenge y
historical challenge son aquí el mismo protocolo; no hay que ejecutar dos estudios.
El perfil declara que A/B/C fueron elegidos tras consultar TEST y prohíbe retocar sus
parámetros después de observar el challenge. Se conserva la única Strategy V1 existente.

| Candidato | Mercado | Modo | SMA | RSI length | RSI | ATR | Mult. | RR |
|---|---|---|---:|---:|---|---:|---:|---:|
| candidate_a | ETHUSDT 15m | LONG_SHORT | 185 | 25 | 35/65 | 20 | 2.5 | 1.25 |
| candidate_b | ETHUSDT 15m | LONG_ONLY | 200 | 25 | 35/65 | 20 | 2.5 | 1.25 |
| candidate_c | ETHUSDT 15m | LONG_ONLY | 150 | 20 | 35/65 | 20 | 2.5 | 2.0 |

Todos V1/Single-TF, slope lookback=5 requerido por schema e irrelevante para señales V1.
Lista explícita; no grids ni expansión entre modos. Costes BASE 0.05/0.03/0.01% y
ADVERSE 0.10/0.06/0.02%; capital 10000, perfil de riesgo existente y ATR/RR por candidato.
Precios USD-M, ejecución synthetic sin funding/liquidaciones: se conserva esa limitación.

Historia solicitada: [2020-01-01, 2023-06-04), UTC. Dataset ETH fijado por fingerprint
`9d4bcb5a0627a70513522de8d967c52697af68220dba52ce626a9915730e35c8`.
No hay velas anteriores al 1 de enero en este bundle. Las primeras 1004 velas son
warmup, sin PnL evaluado. Inicio puntuable exacto: **2020-01-11 11:00 UTC**.
No se reduce warmup ni se inventa historia anterior para cubrir la petición.

Tramos naturales, sin etiquetas bull/bear retrospectivas:

- HISTORICAL_CHALLENGE/calendar_2020: 2020-01-11 11:00 → 2021-01-01.
- HISTORICAL_CHALLENGE/calendar_2021: 2021-01-01 → 2022-01-01.
- HISTORICAL_CHALLENGE/calendar_2022: 2022-01-01 → 2023-01-01.
- HISTORICAL_CHALLENGE/calendar_2023_partial: 2023-01-01 → 2023-06-04.

Son periodos independientes con liquidación/reinicio por tramo y warmup causal anterior.
24 backtests = 3 candidatos × 4 tramos × 2 costes. No se llama TEST/FINAL/VALIDATION
a ninguno ni se agrega otra ejecución FULL que duplique evidencia. No hay ranking ni
selección posterior. El resultado histórico sirve para falsar, no para aprobar OOS
independiente o paper automáticamente. `classify` rechaza estos runs sin TRAIN/TEST.

```bat
python scripts/lab.py challenge validate trend_rsi_pullback_v1_eth_challenge
python scripts/lab.py challenge validate trend_rsi_pullback_v1_eth_challenge --full
python scripts/lab.py challenge run trend_rsi_pullback_v1_eth_challenge
```

Solo el último comando simula; lo ejecuta el usuario. Escribe un run nuevo con plan,
snapshot, configuración resuelta, entorno, provenance, candidatos, ledger, métricas,
trades/equity y resúmenes. Un fallo deja outcome FAILED; no se implementa resume para
el protocolo nuevo de 24 pruebas. El resume ordinario conserva sus comprobaciones
estrictas de código; no se flexibiliza para aceptar cambios no auditados.

## Publicar compactos sin Git automático

```bat
python scripts/lab.py publish trend_rsi_pullback_v1_single_tf
python scripts/lab.py publish 20260930T043029Z-83c8241784a3 --max-file-mb 5
python scripts/lab.py publish-comparison latest
python scripts/lab.py publish-comparison 20260930T085053Z-5e6e952a9c9c
python scripts/lab.py publish trend_rsi_pullback_v1_eth_challenge
```

Publicar el challenge requiere haberlo completado. Publicar un run no clasifica de
forma implícita: ejecutar `classify` antes si se quiere incluir su suplemento.
El último comando es para después de la ejecución local; no existe evidencia del
challenge solo por crear su YAML. La referencia histórica puede publicarse sin repetirla.

Destino, allowlist, tamaño, hashes y límite de portabilidad:
[research_results/README.md](../research_results/README.md). Para comparaciones antiguas
sin outcome se exige todo el conjunto compacto y se verifican fuentes COMPLETE y
los hashes fijados en sources.json. No se copian SQLite, Parquet, datasets ni result.json
individuales. No se hace git add/commit/push. Revisar la publicación antes de versionarla.

Las decisiones humanas están en [RESEARCH_STATUS](../research_results/trend_rsi_pullback/RESEARCH_STATUS.md);
proceden de las conclusiones aportadas por el usuario, no de una promoción automática.

## Flujo local completo

```bat
python scripts/lab.py classify trend_rsi_pullback_video_reference
python scripts/lab.py classify trend_rsi_pullback_v1_single_tf
python scripts/lab.py classify trend_rsi_pullback_v1_mtf
python scripts/lab.py classify trend_rsi_pullback_v1_mtf_slope
python scripts/lab.py compare trend_rsi_pullback_video_reference trend_rsi_pullback_v1_single_tf trend_rsi_pullback_v1_mtf trend_rsi_pullback_v1_mtf_slope
python scripts/lab.py publish trend_rsi_pullback_video_reference
python scripts/lab.py publish trend_rsi_pullback_v1_single_tf
python scripts/lab.py publish trend_rsi_pullback_v1_mtf
python scripts/lab.py publish trend_rsi_pullback_v1_mtf_slope
python scripts/lab.py publish-comparison latest
python scripts/lab.py challenge validate trend_rsi_pullback_v1_eth_challenge --full
python scripts/lab.py challenge run trend_rsi_pullback_v1_eth_challenge
python scripts/lab.py publish trend_rsi_pullback_v1_eth_challenge
```

Los comandos de publicación no sobrescriben directorios existentes. Si ya se publicó
un run antes de reclasificarlo, revisar/versionar esa publicación antes de reemplazarla
manualmente; el programa no modifica el cuaderno anterior a escondidas.

## Archivos y verificación de implementación

Archivos creados:

- `src/quant_lab/lab_evidence.py`: lectura compacta COMPLETE, identidades y hashes.
- `src/quant_lab/lab_classification_policy.py`: schema estricto de gates versionados.
- `src/quant_lab/lab_classification.py`: etapas, suplemento y lookup por hashes.
- `src/quant_lab/lab_challenge.py`: candidatos explícitos y runner de falsación.
- `src/quant_lab/lab_publish.py`: allowlist, compactos, metadata y límite de tamaño.
- `configs/research/lab_classification_v1.yaml`: thresholds iniciales solicitados.
- `configs/challenges/trend_rsi_pullback_v1_eth_challenge.yaml`: A/B/C y cronología.
- `tests/unit/test_lab_classification.py`: gates, leakage, WF y no doble conteo.
- `tests/unit/test_lab_research_workflow.py`: clasificación/publicación/comparación inmutables.
- `tests/integration/test_lab_challenge.py`: tres candidatos exactos y backend sintético.
- `research_results/README.md`: contrato del cuaderno Git.
- `research_results/trend_rsi_pullback/RESEARCH_STATUS.md`: decisiones humanas e IDs.
- `docs/research-evidence.md`: este protocolo y comandos.

Archivos modificados:

- `src/quant_lab/lab_cli.py`: classify, publish, publish-comparison, challenge y enlaces report.
- `src/quant_lab/lab_comparison.py`: etiquetas legacy explícitas y suplementos separados.
- `.gitignore`: cuaderno versionable y exclusión adicional de pesados en él.
- `AGENTS.md`, `README.md`, `docs/PROJECT_STATE.md`, `docs/ARCHITECTURE.md`,
  `docs/WORKFLOW.md`, `docs/RESEARCH_RULES.md`: referencias y fronteras de la nueva capa.

No se modificaron Strategy, StudyBackend, métricas, riesgo, runner ordinario, resume,
los cuatro YAMLs anteriores ni resultados originales. La clasificación real de referencia
creó únicamente un suplemento bajo reports, sin sustituir evidencia congelada.

Verificación 2026-10-04:

- Grupo ampliado: **126 passed** (35.77 s), incluidos lab/resume/Trend RSI previos.
- Tras los últimos ajustes de identidad, publicación y trazabilidad: **62 passed**
  (13.75 s), nuevas pruebas y la integración Trend RSI previa.
- Ruff check global correcto; format check correcto, 321 archivos; pip check correcto;
  git diff --check correcto. No se ejecutó toda la suite ni investigación pesada.
- Challenge real FULL: VALID, 3 candidatos, 24 backtests previstos; ninguno ejecutado.
- Smoke real `classify trend_rsi_pullback_video_reference`: suplemento creado sobre
  132 filas existentes. No se reclasificaron automáticamente los tres grids grandes.
- Git ignore: results/reports y un Parquet dentro del cuaderno ignorados; RESEARCH_STATUS
  versionable. No se ejecutó git add/commit/push.

Comando del grupo ampliado:

```bat
python -m pytest tests/unit/test_lab_classification.py tests/unit/test_lab_research_workflow.py tests/integration/test_lab_challenge.py tests/unit/test_lab.py tests/unit/test_lab_resume.py tests/unit/test_trend_rsi_pullback_v1.py tests/integration/test_trend_rsi_lab.py -q
```
