# Cuaderno de investigación

Esta carpeta se versiona en Git. `results/`, `reports/` y `data/` siguen locales e ignorados.
Los informes compactos no sustituyen los backtests completos ni sus datasets, trades,
equity, ledger y provenance. Conservar también las fuentes de cualquier `reuse.json`.

Estructura de publicación:

```
research_results/<strategy_family>/<experiment_id>/<run_id>/
research_results/<strategy_family>/comparison/<comparison_id>/
research_results/<strategy_family>/RESEARCH_STATUS.md
```

La familia se obtiene del identificador de estrategia quitando únicamente el sufijo
`_vN`, si existe. Comparaciones de varias familias usan `cross_family/comparison/`.
El nombre de cada publicación es determinista; repetir no sobrescribe su contenido.
`metadata.json` se escribe al final y registra fuente portable, periodos, supuestos,
clasificación si existe, omisiones por tamaño y SHA256 de todos los otros archivos
publicados. No incluye un hash de sí mismo.

Solo se publica una allowlist de textos/CSV/JSON. Límite por archivo: 5.000.000 bytes,
configurable con `--max-file-mb`. Nunca copiar equity, datasets, ledger, credenciales
ni carpetas completas. Un archivo omitido se muestra en consola y en metadata.
Sin `metadata.json`, una publicación interrumpida está incompleta: conservarla como
evidencia y revisar antes de añadir archivos a Git. No hay commit/push automáticos.

`metrics_compact.csv` conserva ejemplos ordenados previamente por TRAIN y todos los
TEST seleccionados de WF; no elige ejemplos por su TEST ni por clasificación final.
En challenges incluye todas las filas. `leaderboard.csv` conserva la información
legacy; sus PASS no acreditan edge ni aptitud para paper. Los suplementos de
clasificación son retrospectivos y no hacen que un holdout observado sea independiente.

Procedimiento y comandos: [docs/research-evidence.md](../docs/research-evidence.md).
Decisiones humanas: [Trend RSI Pullback](trend_rsi_pullback/RESEARCH_STATUS.md).
