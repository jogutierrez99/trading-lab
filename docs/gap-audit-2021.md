# Contraste de las 13 horas ausentes de 2021

Se ejecutó `python scripts/audit_2021_gaps.py` para las 13 horas identificadas en
la auditoría mensual de BTCUSDT spot. El comando está limitado explícitamente a
esos huecos de 2021; no es un reparador automático del historial.

Por cada hora se consultaron cuatro fuentes: archivo diario de velas 1h, API pública
de velas 1h, archivo diario de velas 1m y API pública de velas 1m. Los ZIP diarios se
verificaron contra sus checksums SHA256. Las respuestas originales, incluidas las
listas vacías de la API, se conservaron con su hash, URL y fecha de consulta.

| Fecha UTC | Horas investigadas | Velas 1h por hora, diario/API | Minutos por hora, diario/API |
| --- | --- | --- | --- |
| 2021-02-11 | 04:00 | 0 / 0 | 0 / 0 |
| 2021-03-06 | 02:00 | 0 / 0 | 0 / 0 |
| 2021-04-20 | 02:00, 03:00 | 0 / 0 | 0 / 0 |
| 2021-04-25 | 05:00, 06:00, 07:00 | 0 / 0 | 0 / 0 |
| 2021-08-13 | 02:00, 03:00, 04:00, 05:00 | 0 / 0 | 0 / 0 |
| 2021-09-29 | 07:00, 08:00 | 0 / 0 | 0 / 0 |

Resultado: 52 comprobaciones con respuesta, ninguna con error de transporte o formato;
13 horas pendientes y 0 candidatas recuperadas. No hay velas de un minuto en estas
respuestas con las que reconstruir las horas.

Solo se propone una candidata si existe una vela horaria válida o 60 minutos
consecutivos válidos. La agregación usa apertura inicial, máximo, mínimo, cierre final
y suma de volumen con aritmética decimal. Se rechazan datos incompletos, duplicados,
desordenados, OHLCV inválido y cierres fuera de intervalo. Si las fuentes completas
discrepan se registra conflicto, sin aplicar sustituciones.

Una respuesta vacía no prueba ausencia de negociación ni confirma mantenimiento.
No se inspeccionaron archivos de transacciones ni avisos de interrupción en esta
comprobación. No se usaron futuros, otros exchanges ni precios arrastrados.
Los conjuntos y los informes anteriores permanecen intactos.

Informe inmutable:
`data/gap-audits/audit-3c8ed4835fd6e1aeb30d5fce00a03d9684a16ff59c3f0ecc94ec1475f1989cd8.json`.
Respuestas originales: `data/gap-audits/evidence/<sha256>`.
Son evidencias locales ignoradas por Git, no un dataset validado.

Para aceptar 2021 sigue siendo necesario resolver los huecos o definir una política
explícita de discontinuidades. Otra opción ya identificada es preparar una solicitud
separada para enero de 2022 a enero de 2023 inclusive.

Verificación: 82 pruebas superadas, incluidas agregación de minutos, rechazo de datos
incorrectos, evidencias, conflictos y errores de checksum/red. Sin backtest ni cambios
en las reglas de validación del historial.
