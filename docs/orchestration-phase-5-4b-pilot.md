# Fase 5.4B — Preparación del piloto técnico de BTC spot

El borrador del Issue **[strategy-intake] BTC Spot SMA50 SMA200 1H —
Technical Pilot V1** tiene como identificador
`btc_spot_sma50_sma200_1h_pilot_v1`. Usa una sola configuración causal
del cruce SMA50/SMA200, con ejecución ordinaria de BTC spot en 1h y
precarga verificada de 240 velas por tramo. La fuente es la propuesta inicial
del repositorio fijada a su commit. El preflight acredita compatibilidad y
cobertura de datos. Los tramos son retrospectivos y el holdout figura como
`CONSUMED`.

- [Cuerpo JSON íntegro](../examples/orchestration/phase-5-4b/issue-body.json)
- [Plan local en borrador](../examples/orchestration/phase-5-4b/implementation-plan.draft.json)
- [Evidencia del preflight](../examples/orchestration/phase-5-4b/preflight-evidence.json)
- [Solicitud pendiente de autorización](../examples/orchestration/phase-5-4b/authorization-request.draft.json)

## Procedencia y admisión

El contrato 1.0 conserva `chatgpt-daily-0900` para la investigación,
y admite `supervised-technical-pilot` para pruebas supervisadas con una
fuente citada bajo `docs/` de este repositorio y fijada a un SHA de commit
completo. Se comprueba la forma del enlace localmente. Para este piloto,
la ruta y los bytes del documento se verificaron contra el objeto Git.
El receptor conserva el autor numérico, etiqueta, URL, hashes, cuota
diaria y deduplicación. El nombre reservado del piloto requiere su origen técnico.

La admisión sigue en `MANUAL_REVIEW / PREPARE_ONLY / QUEUED`. El puente
GitHub y el coordinador bloquean la preparación del piloto. El diagnóstico
puede comprobar una vinculación estructural de autorización, y conserva el
bloqueo incluso con una vinculación válida. La solicitud pendiente es un
documento de revisión y carece de operador, Issue, tarea y commit base definitivos.
La habilitación de una ruta de preparación con autorización efectiva queda
pendiente de una fase posterior.

## Revisión del commit y del Issue

El inventario de base futura incluye los cambios locales de 5.3 y 5.4A,
el esquema y controles de procedencia, las regresiones, esta guía y los
cuatro JSON del piloto. El archivo de evidencia cita `base_checkout` como
el HEAD observado durante el preflight, previo al futuro commit.
El hash del plan es canónico. El campo `specification_reviewed` cumple el
contrato de plan y por sí solo carece de valor de autorización.

Tras revisar y autorizar los cambios, crear un commit con el inventario
exacto y comprobar sus bytes. Publicar el JSON íntegro en un Issue nuevo
solo tras autorización independiente y tras confirmar que el receptor
dispone del esquema revisado. Tras la admisión, comparar el hash canónico
con el borrador y registrar aparte el hash del cuerpo recibido. GitHub puede
ajustar los finales de línea, por lo que se comparan ambos hashes por separado.
Los Issues #1 y #2 conservan sus expedientes.

Para una futura preparación real, verificar inmediatamente antes el
operador, los IDs y hashes, el commit, la exclusión mutua y la ausencia
de intentos previos o trabajo activo/incierto. Volver a consultar el ledger
canónico de 20 EUR. El piloto propuesto consume cuota Codex de ChatGPT y
presupuesta 0 EUR de API, una sola implementación, 600 s y 60 s por
comprobación. La autorización de lanzamiento sería separada. El objetivo
termina en `IMPLEMENTED_VERIFIED`, con verificaciones ligeras y sin backtests.
