---
name: create-strategy
description: Implementar una nueva lógica de estrategia causal en Trading Lab con Parameters, señales, discovery y tests. Usar para reglas nuevas, no para cambiar activo, periodo o parámetros de un experimento.
---

# Crear estrategia en Trading Lab

Trabajar desde la raíz. Leer [AGENTS](../../AGENTS.md) y su secuencia README →
PROJECT_STATE → ARCHITECTURE → WORKFLOW → RESEARCH_RULES, más el protocolo afectado.
Inspeccionar `src/quant_lab/strategies/base.py`, `registry.py` y una estrategia/test
comparable antes de escribir. No inferir capacidades por el nombre de la estrategia.

1. Traducir la hipótesis a reglas observables al cierre, ventanas, warmup, entradas y
   salidas. Separar features/señales de sizing, fills y estado de ejecución.
2. Comprobar nombres existentes y reservas. Para nombre nuevo ejecutar
   `python scripts/create_strategy.py new_strategy`, reemplazando el identificador.
   Crea módulo/YAML/test exclusivos; no sobrescribir perfiles ni usar el generador para
   una reserva existente. No modificar backend por una adición ordinaria.
3. Implementar `Parameters` basado en `StrictModel`, rangos y validadores entre campos,
   `prepare_features` y los cuatro métodos `generate_long_entries`, `generate_long_exits`,
   `generate_short_entries`, `generate_short_exits`. Un bool Python por fila, mismo orden.
   Métodos de modos no soportados deben tener comportamiento explícito y probado.
4. Asset, timeframe, period, capital y mode pertenecen preferentemente a configuración.
   Ventanas reutilizables sí son parámetros de estrategia. Respetar excepciones reales
   de protocolos MTF con `architecture`/`trade_mode`; no introducir una variante por activo.
5. Declarar versión, descripción, status, fecha UTC explícita y capacidades
   `lab_timeframes`, `lab_modes`, `lab_execution`. Anunciar `ohlcv` solo si el adaptador
   ordinario ejecuta fielmente las reglas. Discovery es automático: no editar lab.py ni
   una lista central. No ocultar imports fallidos/duplicados.
6. Añadir pruebas de parámetros inválidos, entradas/salidas long/short pertinentes,
   warmup y prefix-invariance de features/señales. En MTF, probar disponibilidad de
   cierres completos, reinicios por huecos y fronteras temporales. Nada de datos futuros.
7. Habilitar el YAML solo tras implementar y comprobar. Ejecutar test del módulo,
   regresiones relacionadas y Ruff. `python scripts/lab.py strategies` verifica discovery.
   Cambios a reglas existentes requieren versión nueva y reproducción por revisión Git.
8. Crear un experimento compatible según [create-experiment](../create-experiment/SKILL.md)
   si forma parte de la petición. Para adaptadores dedicados, usar su protocolo; no fingir
   que lab puede ejecutarlos. Evaluar actualización de PROJECT_STATE por la nueva capacidad.

Entregar archivos, reglas, supuestos, pruebas y comando exacto de ejecución local del
experimento preparado. No hacer optimización automática ni lanzar batches/sweeps largos.
No cambiar estrategias/configs/resultados congelados ajenos a la petición.
