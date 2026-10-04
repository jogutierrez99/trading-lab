# Trend RSI Pullback — decisiones de investigación

Fecha: **2026-10-04**. Decisiones humanas indicadas por el usuario en esta tarea;
no son clasificaciones económicas calculadas automáticamente ni una nueva auditoría
de rentabilidad. Los run IDs y sus estados COMPLETE se comprobaron leyendo metadata.

| Hipótesis | Estado humano | Motivo comunicado | Run de referencia |
|---|---|---|---|
| trend_rsi_pullback_video_reference | DISCARDED | Frecuencia de trades insuficiente; sin evidencia estadística robusta. | 20260929T182249Z-beff1dc16a3a |
| trend_rsi_pullback_v1_single_tf | RESEARCH_CONTINUE | Única rama con una región ETH Single-TF interesante; necesita validación independiente. | 20260930T043029Z-83c8241784a3 |
| trend_rsi_pullback_v1_mtf | DISCARDED | Turnover elevado y resultados OOS negativos. | 20260930T043058Z-5cbdf1de41df |
| trend_rsi_pullback_v1_mtf_slope | DISCARDED | Mejora ligera respecto a MTF, sin edge OOS suficiente. | 20260930T043123Z-ec338308439e |
| trend_rsi_pullback_v1_eth_challenge | NEW_HYPOTHESIS | Falsación histórica de tres candidatos ETH Single-TF congelados. | Pendiente; no ejecutado |

Comparación local relacionada: `20260930T085053Z-5e6e952a9c9c`.
Los candidatos A/B/C proceden de análisis del TEST ya observado. No se puede presentar
ese TEST como selección independiente ni ajustar parámetros después del challenge.
El periodo anterior se denomina HISTORICAL_CHALLENGE; tampoco se declara nuevo TEST.

Los estados humanos de esta tabla no alteran metadata de Strategy ni conceden
PAPER_TRADING_CANDIDATE. Las reglas automáticas, su versión y sus límites están en
[research-evidence](../../docs/research-evidence.md). Los resultados históricos no
implican rentabilidad futura. No se habilitan órdenes ni forward automáticamente.
