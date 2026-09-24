# Batch 004: resultados

Run `20260922T152534Z-9e98df5faaac`: 146 backtests completados. 196 tests pasan,
Ruff/formato y pip check correctos. Los 2.082 archivos protegidos de código,
configuración, datasets y resultados anteriores conservan sus hashes. Código del
experimento sin cambios desde preflight/freeze. Ninguna orden real.

Inventario: tres bundles auditados y50 CSV locales; no hay BTC de2026 ni ETH.
Todas las ejecuciones son **REUSED_HISTORY_DIAGNOSTIC**, sin validación independiente.
Primario puntuado desde2023-06-04 hasta2026-01-01, contexto común1.536h.
Legacy se ejecuta aparte; ninguna posición atraviesa marzo2023.

| Estrategia / variante | Train % | Validation % | Test % | Final base % | Final adverso % | WF % |
|---|---:|---:|---:|---:|---:|---:|
| Regime trend / ADX18, base diagnóstica | 8,19 | 2,37 | -1,52 | 0,70 | -0,87 | 0,82 |
| Dual momentum / ROC7/30 | 3,68 | 0,43 | -1,86 | 1,50 | -0,09 | -1,43 |
| Vol expansion trend / p50, base diagnóstica | 8,59 | 1,28 | -2,92 | -3,92 | -5,08 | -1,68 |
| Low vol pullback / p40 | 0,05 | -2,06 | -0,86 | -0,40 | -3,76 | -2,90 |

Train termina2024-07-01, validation2025-01-01, test2025-07-01 y final2026-01-01,
todos fines exclusivos UTC. Tabla muestra cuentas independientes, nunca cartera.

Solo dual momentum7/30, dual momentum14/60 y low-vol p40 fueron elegibles en train.
Se seleccionaron7/30 y p40 por los criterios congelados. Regime trend y vol expansion
no alcanzan40 trades en ninguna variante train; sus bases siguen solo como diagnóstico.

Todas las selecciones/bases pierden en test y en final con costes adversos.
Dual momentum tiene21 trades finales y regime trend12: INSUFFICIENT_DATA, pese a
retorno final base positivo. Vol expansion sigue INSUFFICIENT_DATA por train;
las pérdidas posteriores no se ocultan. Low-vol p40 queda FAILED_AFTER_COSTS:
final zero+1,42%, base−0,40%, adverso−3,76%. Los escenarios cambian incluso el número
de operaciones:49/50/52; sensibilidad calculada con reejecución completa.

No hay candidata con evidencia favorable conjunta ni clasificación ROBUST.
Para Batch005 conviene priorizar datos no observados; los resultados no justifican
seguir añadiendo filtros elegidos sobre el mismo histórico.

Monte Carlo:69 ejecuciones elegibles,10.000 permutaciones y10.000 bootstraps cada una;
77 casos omitidos explícitamente por<30 operaciones. Retorno terminal constante en
permutación de PnL fijo; bootstrap varía el terminal. Sin predicción ni resizing.
Los dos ejes de régimen concilian gross/net; no sumarlos entre sí.

- [Informe completo:13 respuestas y tabla ampliada](../results/batch_004/20260922T152534Z-9e98df5faaac/batch_004_summary.md).
- [Métricas de todas las ejecuciones](../results/batch_004/20260922T152534Z-9e98df5faaac/metrics.csv).
- [Verificación](../results/batch_004/20260922T152534Z-9e98df5faaac/verification.json).
- [Gráfico general](../results/batch_004/20260922T152534Z-9e98df5faaac/charts/overview.png).
- [Protocolo y adaptaciones](batch-004-protocol.md).

Se conservan hashes de todos los artefactos en artifact_manifest.json. Las once
referencias Batch001/002/003 están congeladas y etiquetadas REFERENCE_DIAGNOSTIC,
comparadas en periodos idénticos. Resultados y datos locales permanecen ignorados
por Git; no se han sobrescrito resultados ni creado commits.
