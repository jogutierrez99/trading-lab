# Prueba aprobada: enero de 2022 a enero de 2023

BTC/USDT Binance spot, velas de 1h UTC. Periodo de estudio:
2022-01-01 00:00 inclusive a 2023-02-01 00:00 exclusive.
Configuración: `configs/profiles/btc_spot_1h/history_2022_jan2023.yaml`.
Se mantienen intactas las solicitudes anteriores.

Resultado: 9.504 velas del estudio más 200 de calentamiento desde
2021-12-23 16:00 UTC: 9.704 filas. Los 14 archivos mensuales pasaron checksum,
validación de timestamps, continuidad, duplicados, finitud y coherencia OHLCV.
Se registró el cierre anticipado conocido del calentamiento del 24 de diciembre;
la disponibilidad se mantiene al final de la hora.

El Parquet y manifiesto se publicaron en:
`data/history/77a55251e86f4034b317dd312b3bad06bb95c36f6540c74c4b8121793425b6da/`.
La relectura verificó checksum y huella de contenido.

SMA50, SMA200 y ATR14 se calcularon sobre el historial real. Ningún valor del
periodo de estudio quedó vacío o no finito. ATR fue positivo. Se verificó que añadir
observaciones futuras no cambiara valores anteriores en 11 cortes, incluidos los
límites de calentamiento. Se contrastaron las tres fórmulas de forma independiente
en cinco posiciones, y se comprobó que los datos de entrada no cambiaran.

Informe de comprobaciones:
`reports/data-test-58cecc26a88701f7c3ff33795445f925197c727e3bba84dbe1ec1f6657bc51b9.json`.
Pruebas del proyecto: 82 superadas; lint y formato correctos.

Acceso corregido el 20 de septiembre de 2026, con autorización explícita del usuario:
la carpeta de este dataset y sus dos archivos heredaron los permisos del proyecto.
Se verificaron desde el entorno restringido la reutilización offline de la caché,
checksum, huella de contenido, 9.704 filas e indicadores completos en las 9.504 filas
del estudio. No cambió el contenido del Parquet ni del manifiesto. El informe JSON
anterior se conserva como registro de las comprobaciones previas a esta corrección.
El cambio se limitó a este dataset; no modifica la creación de futuras cachés.

Esta prueba es de datos e indicadores, no un backtest. No se han simulado órdenes,
capital, riesgo o costes. El intervalo aprobado no se extiende a todo 2022–2025:
el hueco de marzo de 2023 permanece sin resolver.
