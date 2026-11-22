# Trading Lab — Hoja de ruta del MVP y evolución posterior

Planificación, no autorización de ejecución. Prioridad: completar primero el MVP.
Base de esta revisión: `1089e80a2bb62b95d8e88bb363b6c710d64f75dd`.
Se consultaron README, PROJECT_STATE y los diseños existentes; no había una hoja
de ruta central vigente. Las notas antiguas de fases conservan su ámbito histórico.

## MVP — Agentes y flujos

| Fase | Estado / objetivo |
|---|---|
| 5.9B.0 | COMPLETADO e integrado por PR #9: diseño multiagente V1 |
| 5.9B.1 | EN DESARROLLO: Investigador local simulado; implementación pendiente de revisión e integración |
| 5.9B.2 | Pendiente: Diseñador de Estrategias |
| 5.9B.3 | Pendiente: Validador Cuantitativo |
| 5.9B.4 | Pendiente: Coordinador e integración, reutilizando el controlador existente |
| 5.9C | Pendiente: integración, pruebas y piloto IA con autorización separada |
| 6.0A | Pendiente: Flujo 1 de extremo a extremo hasta Telegram verificado y autorizado |
| 6.0B | Pendiente: Flujo 2 de extremo a extremo hasta Telegram verificado y autorizado |

El MVP solo estará completado tras verificar **ambos flujos**, presupuesto global,
trazabilidad y notificaciones bajo sus autorizaciones. Un DRAFT no es un envío.
El Flujo 1 tiene prioridad sobre la integración completa del Flujo 2. La frecuencia
de 2–3 propuestas diarias depende del presupuesto y calidad medidos; no se garantiza.
La implementación de un componente no activa agentes, scheduling, API o trading.

## Pos-MVP — Fase 7.0: biblioteca y formación especializada

Investigación posterior: biblioteca de papers, manuales y metodologías, RAG o
recuperación, ejemplos especializados, memoria de errores verificados, exámenes,
benchmarks por agente, calificaciones/certificaciones, optimización controlada de
instrucciones y evaluación de mejoras sin regresiones. Cada fuente mantendrá
procedencia y será contenido no confiable, nunca una autorización privilegiada.
Nada de esta fase se implementa en 5.9B.1.

## Pos-MVP — Fase 8.0: rendimiento y evolución del motor

Estudiar el backend real y sus cuellos de botella antes de elegir tecnologías:

- Auditoría del motor, indicadores y cálculos; vectorización compatible con su semántica.
- Procesamiento paralelo, caché reproducible y ejecución incremental cuando procedan.
- Rendimiento de backtests masivos, memoria, almacenamiento y escalabilidad por activo/timeframe.
- Benchmark del motor actual frente a VectorBT, Numba y otras alternativas, sin asumir superioridad.
- Comparación de exactitud, tiempos, RAM y reproducibilidad para spot, perpetual y futuros activos.
- Conservación de costes, fills, capital, funding, gaps y auditoría.

Antes de cualquier cambio: benchmarks de referencia, casos de equivalencia
congelados, error numérico medido, semántica de ejecución verificada, resultados
antiguos/nuevos comparados y riesgos de migración revisados. Mejorar eficiencia
no permite cambiar silenciosamente resultados científicos. No se modifica el
motor en 5.9B.1. Las fases 7.0 y 8.0 quedan detrás del MVP y requieren otro encargo.

## Gates comunes

Mantener catálogo/ledger/coordinador existentes; sin contabilidad paralela. Cualquier
proveedor real exige modelos y precios vigentes, reservas máximas, credenciales y
ámbito de factura, gasto conciliado y autorización explícita. Los perfiles de precio
caducados no se renuevan por esta planificación. Demo/live nunca se infieren de un
backtest o de una opinión IA. NO_DECISION y los holdouts CONSUMED se conservan.

El [plan multiagente](agents/agent-test-plan-v1.md) define aceptación incremental;
la [implementación del Investigador](agents/agent-01-researcher-implementation-v1.md)
describe exclusivamente simulaciones y sus límites.
