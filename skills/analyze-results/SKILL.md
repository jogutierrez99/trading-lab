---
name: analyze-results
description: Analizar artefactos de un run ya ejecutado en Trading Lab y redactar un suplemento trazable. No relanza backtests, optimizaciones ni búsquedas completas.
---

# Analizar un run existente

Leer [AGENTS](../../AGENTS.md), sus cinco documentos y el protocolo del estudio.
Seguir [workflow de análisis](../../docs/WORKFLOW.md). Mantener el análisis limitado
al run/casos solicitados; no recorrer miles de artefactos por defecto.

1. Fijar run ID y ruta. `python scripts/lab.py report <experiment_id>` o `report latest`
   localiza solo runs ordinarios; registrar la ruta elegida para evitar un latest móvil.
   En estudios dedicados inspeccionar plan/manifest y encontrar el lote hijo correcto.
2. Leer outcome/verification y conteos, resumen existente, plan, configuración resuelta,
   provenance y manifests. Distinguir éxito, fallo y ausencia de evidencia. Un lab sin
   outcome es incompleto, no COMPLETE. No inferir integridad de todos los trades de un
   recibo leído: declarar alcance de verificación y contrastar hashes pertinentes.
3. Comparar métricas/leaderboard/results seleccionados con TRAIN, validation, TEST/final,
   WF y stress disponibles. Informar mejores y peores con criterio explícito, preservando
   ranking TRAIN y denominadores. No elegir un ganador por retorno TEST ni sumar ventanas
   solapadas como una cartera. Respetar null/PF indefinido y muestras pequeñas.
4. Revisar trades, equity, rechazos o funding de casos concretos si explican anomalías.
   No recalcular fills/métricas para reemplazar resultados originales. Analizar costes,
   drawdown, exposición, estabilidad de parámetros, activos/timeframes y regímenes solo
   donde haya evidencia; marcar lo no evaluado. No cambiar etiquetas/umbrales.
5. Escribir un suplemento nuevo, preferiblemente
   `reports/analysis/<experiment-or-study>/<run_id>/<UTC>-<id>/ai_summary.md`.
   Crear exclusivamente; no sobrescribir `ai_summary.md`, manifest ni otro artefacto
   dentro del run congelado. Esta ruta es convención, no funcionalidad nueva de CLI.

El suplemento debe contener:

- Run/experimento e hipótesis (desconocida si no está registrada), fuentes y hashes.
- Dataset, cohortes, periodos/warmup, versión, configuración, costes y capital.
- Conteos completos/fallidos, mejores/peores según criterio declarado y métricas.
- TRAIN frente a validation/TEST/final, WF, trades, DD, costes y stability/robustness.
- Anomalías, faltantes, sesgos, múltiples comparaciones y holdouts ya consumidos.
- Conclusiones descriptivas y próximos experimentos propuestos, sin ejecutarlos.

Clasificación suplementaria de nuevas MTF tiene herramienta específica:
`python scripts/classify_new_mtf_results.py --run <run_id_A>`. Usarla si se pide esa
clasificación, con fuente válida; genera otro reporte sin backtests ni edición de A.
No otorga V4 a NEAR_PASS. Para análisis ordinario basta leer la clasificación existente.

Entregar enlace al suplemento, hallazgos y límites; no afirmar beneficios futuros,
robustez independiente o readiness paper/live. Nunca relanzar un estudio para analizarlo.
