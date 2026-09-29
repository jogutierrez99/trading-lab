---
name: create-experiment
description: Crear una configuración experimental de Trading Lab para una estrategia existente, validar datos y capacidades y entregar el comando local. Usar para variantes de mercado, modo, parámetros, periodos o costes.
---

# Crear experimento sin cambiar señales

Leer [AGENTS](../../AGENTS.md) y sus cinco documentos, luego
[manual YAML](../../docs/lab-workflow.md). Trabajar desde la raíz del repositorio.

1. Inspeccionar `python scripts/lab.py strategies`, la clase/Parameters y el perfil
   habilitado. Identificar `lab_execution`, modos y timeframes reales. No tocar Strategy
   salvo necesidad de lógica nueva explícita; una variante de valores pertenece al YAML.
2. Elegir esquema: `configs/experiments/` es solo `lab_schema.Experiment` (OHLCV).
   Funding, `legacy_mtf`, `legacy_batch_006` y timing usan perfiles/runners dedicados.
   Leer su protocolo; no inventar campos MTF o `final` en lab ni puentear guards.
3. Para lab, clonar una definición conocida con ID nuevo:

   ```powershell
   python scripts/lab.py experiment create trend_btc_1h_002 --from trend_btc_1h_001
   ```

   Sustituir IDs según petición. El clon cambia ID/fecha, no mercado ni hipótesis.
   Preservar el YAML de origen y resultados. Si varía riesgo, crear un perfil nuevo
   compatible en lugar de alterar uno histórico compartido.
4. Editar descripción/hipótesis, `strategy.id/config`, `markets.symbol/timeframe/dataset`,
   `warmup_bars`, `modes`, listas `strategy_parameters`, capital, costes y execution.
   Lab admite BTCUSDT/ETHUSDT, 1h/4h/1d, además de restricciones de estrategia.
   15m requiere una estrategia que lo declare, dataset_format=mtf_quarters y dataset_id
   fijado; precios USD-M con ejecución synthetic, sin funding/liquidaciones. Ver
   [Trend RSI Pullback](../../docs/trend-rsi-pullback.md).
   Spot exige LONG_ONLY; cortos compatibles exigen synthetic, sin funding/préstamo.
   Dejar execution.direction en long: `modes` controla las direcciones.
5. Usar un bundle real con manifest, hash e identidad coincidente. Verificar cobertura
   continua incluyendo warmup. No descargar/sustituir implícitamente ni rellenar huecos.
   Si falta, documentar bloqueo y preparación necesaria sin declarar validación exitosa.
6. Declarar train/validation/test UTC fin exclusivo; TEST es final holdout en lab.
   Definir ranking TRAIN, filtros, folds disjuntos y stress antes de resultados.
   No optimizar con holdout. Rutas del experimento relativas al YAML; las de app, a app.
   `*_pct` son porcentajes; costes completos pueden sobrescribir app. El riesgo del
   perfil prevalece sobre global. Cambiar timeframe cambia duración de parámetros en barras;
   sizing por volatilidad lab solo admite 1h.
7. Ejecutar `python scripts/lab.py validate <id>`; usar `--full` para verificar bytes y
   OHLCV cuando corresponda. No ejecutan backtests. Informar número previsto y cualquier
   limitación. No hace falta full pytest por cada YAML; tests dirigidos si cambia código.

Finalizar con ruta YAML/perfiles, hipótesis, datos/periodos, herencias/overrides, resultados
FAST/FULL y comando exacto `python scripts/lab.py run <id>` seguido de `report <id>`.
En runner dedicado entregar sus argumentos reales y preflight requerido. La computación
pesada queda para ejecución local del usuario salvo instrucción específica; no correr
500 backtests para comprobar una configuración. Actualizar PROJECT_STATE solo si cambian
capacidades, no por añadir cada experimento ordinario.
