# Fase 5.4A — Revisión técnica de propuestas GitHub

El receptor de la fase 5.3 conserva su recorrido. El comando local
`review_github_intake.py` lee un checkpoint y las filas de la propuesta,
la candidata y la tarea en una transacción SQLite de solo lectura.
El diagnóstico vuelve a validar `HypothesisManifest 1.0` y coteja el
hash canónico, la identidad de la propuesta y los manifiestos registrados.
Comprueba el repositorio, el autor numérico admitido por el receptor y
el vínculo con la tarea original. Conserva el hash del cuerpo recibido
como evidencia del checkpoint. La cola no guarda el cuerpo bruto, así que
este diagnóstico no puede recalcular su hash.

## Consultar una propuesta

Desde la raíz del repositorio en PowerShell. Para la aceptación, apunta
`$db` a una copia coherente obtenida mediante SQLite Backup de la cola.
Para una consulta local posterior, el mismo comando admite la cola real
en modo de solo lectura. El ledger también se abre en modo de solo lectura.

```powershell
$py = '.\.venv\Scripts\python.exe'
$db = Join-Path $env:LOCALAPPDATA 'TradingLab\GitHubIntake53\queue.sqlite3'
$env:TRADING_LAB_GLOBAL_API_DB = (Get-Content -Raw examples/orchestration/flow1_billing_worker.json | ConvertFrom-Json).ledger
& $py -B scripts/review_github_intake.py --db $db --issue 1 --task-id task_bb7af5dcfa84410e8079a7f0c6401dd6
& $py -B scripts/review_github_intake.py --db $db --issue 2 --task-id task_dd8cda9345b74b1bb79fba65b10e6461
```

El JSON distingue `REJECTED` ante un checkpoint inadmisible o un vínculo
inválido, `INSUFFICIENT_INFORMATION` si faltan condiciones para revisar
la ficha, `REQUIRES_TECHNICAL_PROTOCOL` si el camino ordinario no verifica
el protocolo y `COMPATIBLE_FOR_REVIEW` si supera la revisión preliminar.
Devuelve el esquema de señales, parámetros, ejecución y evaluación para
contrastar con el plan. La coherencia económica y causal de reglas redactadas
en texto requiere revisión humana. El proceso devuelve 2 para `REJECTED`
y 0 para los demás estados de diagnóstico.

## Resultado de la revisión

Ambas propuestas están en `MANUAL_REVIEW / PREPARE_ONLY / QUEUED` y
requieren un protocolo dedicado. En ambas, la disponibilidad de datos está
declarada `UNVERIFIED` y el holdout `UNKNOWN`. Antes de avanzar, deben
documentarse las fuentes de velas, precios de marca y funding efectivo,
las huellas y alineación temporal, el tratamiento de gaps y la cobertura de
precarga más las ventanas propuestas. La declaración del manifiesto no
acredita presencia, cobertura ni independencia del holdout.
Se localizaron manifiestos locales de Batch 006 para ambos activos.
Su cobertura y aptitud para estas dos fichas quedan por acreditar.

- Issue #1, `btc_eth_statistical_pairs_v1`. Spread BTC–ETH en perpetuos
  de 1h, con 720 barras de precarga. El protocolo debe fijar la ejecución
  de las dos patas long/short, el tratamiento de una pata sin ejecutar,
  el margen y el funding por pata, y la valoración conjunta.
- Issue #2, `btc_eth_long_only_multihorizon_tsmom_4h_v1`. Cartera
  long-only en perpetuos de 4h, con 2160 barras de precarga. El protocolo
  debe fijar la asignación y ejecución simultáneas, el capital y margen
  compartidos, el funding de las posiciones y el drawdown de la cartera.

El runner ordinario de preparación no verifica carteras sincronizadas.
El protocolo congelado Batch 006 modela cada mercado por separado.
Una ficha multiactivo se dirige a revisión de protocolo porque el contrato
actual no distingue de forma estructurada un estudio independiente por
activo de una cartera con decisiones o riesgo conjuntos.

## Autorización y recuperación

Con `--plan <archivo>` se valida `ImplementationPlan 1.0`, su operación
se contrasta con `requires_new_strategy_code` y se muestran límites,
archivos esperados, comprobaciones rápidas y hash del plan canónico.
`--authorization <archivo>` comprueba el vínculo de una autorización
local candidata con repositorio, número e ID del Issue, tarea, hash de la
propuesta, hash del plan, operación, permiso `PREPARE_ONLY`, identidad
de revisor y fecha UTC. Un vínculo válido solo acredita coherencia
estructural. En esta fase no se autentican revisores, no se graba una
aprobación y `execution_enabled` siempre es falso.

El diagnóstico inspecciona el presupuesto global de 20 EUR, las reservas
pendientes y el trabajo activo o incierto registrado. La lectura no
adquiere el cerrojo del receptor ni el del coordinador. Ante interrupción
o contención SQLite, repite la consulta; no se escriben checkpoints.
Los estados inciertos de ejecución requieren los procedimientos de
reconciliación existentes. Las lecturas de cola y ledger son independientes.

Para 5.4B se requiere autorización independiente, identidad del operador
verificada, un plan local vinculado a la huella exacta y comprobaciones
vigentes de presupuesto, intentos y exclusión mutua en el punto de
preparación. Los Issues #1 y #2 requieren además sus protocolos, datos
y procedencia de holdout. Los controles previos de preparación del
coordinador siguen en vigor.
