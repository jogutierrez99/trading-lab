# Batch 005: resultados

Run `20260922T181556Z-cdb7fe6f8d52`:154 backtests completados,219 pruebas correctas,
Ruff/formato y pip check pasan. Sin cambios en el código desde la congelación ni en
los3.145 archivos previos protegidos. Motor anterior intacto; stop absoluto mediante
adaptador nuevo, sin sustituirlo por un stop ATR fijo. Ninguna orden real.

Todo es **REUSED_HISTORY_DIAGNOSTIC**: inventario local sin BTC de2026 ni otro activo.
No existe validación independiente ni clasificación ROBUST.

| Estrategia / variante | Train % | Validation % | Test % | Final base % | Final adverso % | WF % |
|---|---:|---:|---:|---:|---:|---:|
| Channel break retest24h, diagnóstico | 4,92 | 1,28 | -2,23 | -0,18 | -0,36 | -0,98 |
| Trend acceleration12h | 10,54 | -0,23 | -2,48 | -1,54 | -2,51 | -2,70 |
| RSI momentum reset40, diagnóstico | -1,92 | -1,94 | -1,96 | -0,52 | -1,45 | -3,87 |
| Vol contraction expansion6/24, diagnóstico | 6,03 | 1,71 | 0,23 | -1,62 | -2,21 | 1,94 |

Train2023-06-04–2024-07-01, validation hasta2025-01-01, test hasta2025-07-01,
final hasta2026-01-01. UTC, fin exclusivo.10.000 USDT por cuenta independiente.
Warmup1.536h; legacy separado sin atravesar marzo2023.

Solo trend_acceleration_a12 superó train, con40 operaciones. Channel retest y
contracción–expansión no llegan a40 en ninguna variante; siguen como bases diagnósticas.
RSI reset queda REJECTED_TRAIN. Los otros tres quedan INSUFFICIENT_DATA, por train
o por muestra final:13/19/11 trades. Todas las pérdidas se conservan.

Contracción–expansión tuvo3/4 folds positivos y WF+1,94%, pero no fue elegible en
train y perdió en final. No se eleva a candidata por ese resultado aislado.

## Calidad de entrada

En el tramo final/base, ratios de medias MFE/MAE: retest2,70; aceleración2,50;
RSI reset2,11; contracción–expansión0,68. Son excursiones brutas y, en salidas
intravela, cocientes de cotas inferiores, no ratios verdaderos identificados.
No demuestran por sí solos buena señal o mala gestión de salida.

Retornos medios del activo a72h desde entrada, antes de costes, incluso después de
salir del trade: retest+0,05%, aceleración+0,84%, RSI reset−1,10%, contracción−0,32%.
Muestras pequeñas de13/19/14/11 entradas. Medianas respectivas−0,50%,+0,63%,−0,66%,
−0,66%. No son PnL de estrategia ni evidencia independiente; no se modificaron exits.
El informe incluye también6/12/24/48h y los intervalos de tiempo hasta extremos.

Auditoría adicional:578 trades estructurales comprobados contra sus anclas y cap;
223 rechazos por distancia>2,5 ATR, contando todas las ejecuciones y escenarios.
Las5.940 operaciones del lote incluyen ventanas solapadas, costes y referencias;
no son una muestra de operaciones independientes. Excursiones y horizontes concilian
con los límites de partición, y gross/net por régimen concilian con equity.

Monte Carlo:50 ejecuciones elegibles con10.000 permutaciones y10.000 bootstraps;
104 omitidas explícitamente por<30 trades. Retorno terminal de permutación constante;
bootstrap variable. Sin predicción futura ni resizing.

- [Informe completo:15 respuestas y tabla ampliada](../results/batch_005/20260922T181556Z-cdb7fe6f8d52/batch_005_summary.md).
- [Métricas](../results/batch_005/20260922T181556Z-cdb7fe6f8d52/metrics.csv).
- [Calidad de entrada](../results/batch_005/20260922T181556Z-cdb7fe6f8d52/charts/entry_quality_comparison.png).
- [Verificación](../results/batch_005/20260922T181556Z-cdb7fe6f8d52/verification.json).
- [Auditoría adicional](../results/batch_005/20260922T181556Z-cdb7fe6f8d52/additional_audit.json).
- [Protocolo y adaptaciones previas](batch-005-protocol.md).

Quince referencias congeladas Batch001–004 y benchmarks en periodos idénticos.
Resultados locales y datasets ignorados por Git, sin commits ni sobrescrituras.
Nuevas hipótesis derivadas de este análisis corresponden a Batch006 y requieren
datos no observados para validación independiente.
