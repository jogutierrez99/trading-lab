---
name: validate-strategy
description: Preparar o revisar validación más estricta de una estrategia candidata en Trading Lab con separación temporal, stress y estabilidad, conservando holdout y reglas del runner.
---

# Validar una candidata

Leer [AGENTS](../../AGENTS.md), sus cinco documentos y el protocolo relevante.
Identificar estrategia/versión, experimento/run fuente, backend, datos y qué periodos
ya han sido observados. No confundir `lab.py validate` (validación técnica) con evidencia
económica independiente. Esta skill no autoriza simulaciones largas ni paper/live.

1. Auditar causalidad con tests existentes y dirigidos: prefix-invariance, warmup,
   disponibilidad HTF, señales al cierre/fills posteriores, costes y gaps. Verificar
   manifests/fingerprints y cobertura continua del protocolo. No cambiar el motor para
   mejorar una candidata ni reparar problemas ajenos sin autorización de alcance.
2. Congelar hipótesis, parámetros, selección TRAIN, criterios, mercados/timeframes,
   costes y tamaño de muestra antes de examinar resultados reservados. Mantener IDs,
   versiones, hashes, entorno y seeds. Si el holdout ya influyó en la candidatura,
   declararlo consumido: solo diagnóstico, pendiente de nueva evidencia independiente.
3. Adaptar Candidate → Train → Validation → Test → Final Holdout a capacidades reales:
   lab tiene train/validation/test y TEST es final, sin cuarta clave `final`.
   Runners dedicados pueden separar test/final_holdout. No inventar campos ni periodos.
   Prohibido optimizar usando final holdout o utilizarlo para reseleccionar parámetros
   y volver a llamarlo validación independiente.
4. Preparar experimentos nuevos para cost stress y parameter stability predeclarada;
   no modificar el original ni ajustar umbrales hasta pasar. WF lab selecciona en
   TRAIN/base y evalúa TEST del fold; protocols legacy pueden usar selección fija.
   No sumar folds solapados ni tratar mediana como cartera compuesta.
5. Planificar asset/timeframe robustness solo con datos y adaptadores compatibles.
   Lab: BTC/ETH, 1h/4h/1d según catálogo; volatilidad sizing solo 1h; shorts synthetic
   no sustituyen perpetuos. Para MTF/funding usar protocolo dedicado, no ampliar alcance
   automáticamente ni cambiar una estrategia solo para poder pasar el validador.
6. Ejecutar FAST y FULL según corresponda sin backtests, junto a tests dirigidos.
   Entregar comandos locales para evaluaciones históricas solicitadas y señalar costes
   computacionales/conteos disponibles. No invocar preflights con replays históricos
   como si fueran comprobaciones ligeras; revisar qué hacen primero.
7. Si ya hay resultados, leerlos usando [analyze-results](../analyze-results/SKILL.md).
   Conservar cada clasificación exacta: PASS genérico no es robustez; RESEARCH_PASS
   nuevas MTF permite solo investigación V4; NEAR_PASS no habilita V4/paper/live.
   No modificar metadata research a validated automáticamente.

Resultado: protocolo o revisión trazable con candidata, particiones, holdout consumido
o intacto, checks realizados, matriz de evidencia disponible/pendiente, límites, archivos
nuevos y comandos exactos. No emitir aprobación económica si faltan pruebas ni ejecutar
una búsqueda masiva para completar el informe.
