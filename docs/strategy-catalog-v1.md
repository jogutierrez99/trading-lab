# Catálogo de estrategias, Capa 1

El catálogo conserva memoria declarativa de investigación en SQLite propia.
Su módulo es trading_lab_catalog y la entrada es scripts/strategy_catalog.py.
Las consultas y la persistencia no importan motores. El adaptador discover
importa exclusivamente las estrategias locales de confianza mediante
StrategyRegistry.catalogue(), sin instanciarlas ni producir señales.

## Almacenamiento y contratos

Ruta predeterminada %LOCALAPPDATA%/TradingLab/StrategyCatalog/strategy-catalog.sqlite3.
--db admite otra carpeta dedicada. El nombre de base es obligatorio, se rechazan
enlaces y carpetas compartidas con otros archivos. init es explícito. Nunca
apuntar este comando al directorio de evidencias ni a bases operativas.
application_id 0x544C4331, user_version 1. migrate verifica la versión 1 y
rechaza destinos para los que aún no hay migración definida. No hay migraciones
automáticas ni apertura inicializadora durante consultas.

Tablas versionadas:

| Tabla | Relación y contenido |
|---|---|
| strategies | Identidad lógica y origen, fecha declarada si existe |
| versions | FK strategy_id, versión, referencias, código/configuración y esquema de parámetros |
| experiments | FK version_id, activo, timeframe, mercado, dirección, parámetros, costes de protocolo, riesgo y dataset |
| runs | FK experiment_id, motor y versión, kind, estado técnico, commit y evidencia |
| case_results | FK run_id, segmento, escenario, periodo UTC, warmup, capital, costes y métricas |
| artifacts | FK run_id, referencia externa, SHA y estado de verificación |
| research_decisions | FKs estrategia, versión y run opcionales, categoría, dictamen y limitaciones |
| catalog_events | Historial append-only de altas, ingestas, duplicados, conflictos y verificaciones explícitas |

Cada entidad guarda sus campos contractuales en payload JSON canónico, su SHA,
timestamp UTC de registro y columnas relacionales con claves foráneas.
La fecha de registro de strategies proporciona first_seen_at_utc.
Los identificadores externos permanecen diferenciados de las huellas de contenido.
La huella de parámetros se calcula y valida automáticamente.
Las definiciones experimentales/versiones idénticas con otra identidad se rechazan.
Solo un resultado por run, segmento y escenario puede registrarse.

Los contratos Pydantic rechazan campos adicionales y números no finitos.
Los periodos requieren UTC y extremo final exclusivo. Los porcentajes conservan
unidades porcentuales, 0.1 significa 0.1 %. Las métricas indefinidas permanecen
null. No se calcula Sharpe ni robustez a partir de un resumen insuficiente.

Triggers impiden UPDATE y DELETE de datos y eventos. BEGIN IMMEDIATE, FK y
UNIQUE serializan las altas. La ingesta completa se confirma o revierte.
El conflicto registra un evento separado después del rollback. Una interrupción
no deja entidades parciales. Repetir datos idénticos devuelve DUPLICATE y registra
la consulta de ingesta. verify comprueba SQLite, FK y hashes documentales.
--sources añade comprobación de referencias. --record-event registra explícitamente
el resultado de verificación; verify sin esa opción es una consulta.
Las consultas abren mode=ro y query_only y rechazan WAL y journals pendientes.

## Descubrimiento y decisiones

discover conserva versión, código, configuración, esquema de parámetros y
metadata del registro. Un módulo descubierto no acredita experimentos ni
resultados. Las consultas versions, experiments, runs y artifacts permiten
distinguir esas etapas. La descripción declarada se conserva en metadata de
versión. La identidad lógica usa un descriptor estable para coexistir con
adaptadores futuros sin reescribir el primer registro.

Las decisiones son registros nuevos. ECONOMIC, RESEARCH, DEMO_ELIGIBILITY y
AUTHORIZATION son categorías independientes. Una categoría no cambia otra.
Los registros son memoria y nunca ejercen permisos de ejecución.
NO_DECISION se conserva. La fecha de decisión desconocida permanece null.

## Comparaciones

compare filtra por activo, familia, timeframe, versión, periodo, motor, mercado,
escenario, segmento, investigación y dictamen. COMPARABLE exige iguales dataset,
ventana, segmento, warmup, capital y política de capital, costes, riesgo,
supuestos, protocolo, motor y tipo de ejecución. Campos diferentes o desconocidos
devuelven NOT_COMPARABLE. Holdout consumido, muestra pequeña, auditoría ausente
o ejecución incompleta producen COMPARABLE_WITH_LIMITATIONS.
El umbral descriptivo de muestra pequeña es 30 operaciones y no constituye
un gate científico. winner siempre es null.
No se suman retornos de capital reiniciado ni operaciones BASE y ADVERSE.
La familia desconocida permanece null; el esquema de activos es abierto.

## Importación de evidencia

Bundle 1.0 es la interfaz Python y JSON general para registros revisados.
register es una escritura explícita de ese contrato. Sus afirmaciones proceden
del operador. No certifica independientemente sus datos.

El adaptador import-preview del Issue #3 exige el directorio exportado, la ruta
del recibo anfitrión sellado y su SHA revisado por el operador. El SHA es el
ancla de confianza externa. El manifest autocontenido solo aporta integridad.
Se capturan una vez bytes acotados y se rechazan enlaces, archivos inesperados,
claves JSON duplicadas, NaN, Infinity, transportes inválidos y diferencias entre
casos, CSV, resumen y recibo.
Se reutilizan Job, CaseResult y el transporte 2.0, sin importar historical_pilot
ni ejecutar auditorías económicas o backtests. SOURCE_AUDITED significa que se
preservó la auditoría de una fuente sellada, no una nueva auditoría independiente.
No se reproduce ni modifica la evidencia. Su procedencia y hashes se referencian.
La versión semántica no acreditada por el recibo permanece null.

import-confirmed repite la validación y escribe únicamente en el catálogo
inicializado. En esta fase el Issue #3 real solo se valida con import-preview.
La aceptación de escrituras utiliza exclusivamente fuentes artificiales.

## PowerShell

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$py = 'python'
$db = Join-Path $env:LOCALAPPDATA 'TradingLab/StrategyCatalog/strategy-catalog.sqlite3'
& $py -B scripts/strategy_catalog.py --help
& $py -B scripts/strategy_catalog.py --db $db init
& $py -B scripts/strategy_catalog.py --db $db discover
& $py -B scripts/strategy_catalog.py --db $db list
& $py -B scripts/strategy_catalog.py --db $db versions --id btc_spot_sma50_sma200_1h_pilot_v1
& $py -B scripts/strategy_catalog.py --db $db stats
& $py -B scripts/strategy_catalog.py --db $db compare --asset BTCUSDT --scenario base --segment train
& $py -B scripts/strategy_catalog.py --db $db verify
# Lectura de evidencia, sin alta:
& $py -B scripts/strategy_catalog.py import-preview --source $export --sealed-source $receipt --receipt-sha256 $reviewedHash
# Solo tras una autorización de importación posterior:
& $py -B scripts/strategy_catalog.py --db $db import-confirmed --source $export --sealed-source $receipt --receipt-sha256 $reviewedHash
```

--format json es el predeterminado. --format text produce JSON indentado para
terminal. show, versions, experiments, runs y decisions admiten --id para filtrar
la entidad o su vínculo. register recibe un archivo Bundle JSON revisado.
Códigos estables 0 OK, 3 NOT_FOUND, 4 CONFLICT, 5 BLOCKED_SOURCE,
6 INTEGRITY_ERROR. init y migrate son acciones explícitas.

## Límites y evolución

La Capa 1 tiene un adaptador de exportación sellada y un contrato general.
Los resultados de runners diferentes requieren sus propios adaptadores futuros.
No hay importación masiva implícita ni ranking económico automático.
Las ACL del catálogo son responsabilidad del operador. Las protecciones no
certifican autenticidad frente a un usuario capaz de reescribir la base y
las evidencias con todos sus permisos. Las fuentes selladas requieren el
ancla de hash revisada. Un proceso con control total del host queda fuera de
este modelo. No hay certificación frente a pérdida de alimentación.

Python/CLI y Bundle facilitan consumidores futuros, pero esta fase no conecta
agentes IA, servicios, Telegram, OKX ni programación periódica.
