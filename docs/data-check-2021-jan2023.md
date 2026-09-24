# Prueba de datos: enero de 2021 a enero de 2023 inclusive

Solicitud ejecutada: Binance spot BTC/USDT, 1h, desde 2021-01-01 00:00 UTC
hasta 2023-02-01 00:00 UTC exclusive, con 200 horas de calentamiento anteriores.
Se conserva la configuración original de 2022–2025.

```powershell
python scripts/download_data.py --config configs/profiles/btc_spot_1h/history_2021_jan2023.yaml
```

Resultado: descarga y auditoría de 26 archivos mensuales con checksum verificado,
desde diciembre de 2020 hasta enero de 2023. La solicitud completa fue rechazada;
no se publicó un Parquet validado ni se ejecutó un backtest.

Velas ausentes de los archivos de 2021 (horas de apertura, UTC):

| Mes | Horas ausentes | Cantidad |
| --- | --- | ---: |
| Febrero | 11 de febrero, 04:00 | 1 |
| Marzo | 6 de marzo, 02:00 | 1 |
| Abril | 20 de abril, 02:00 y 03:00; 25 de abril, 05:00, 06:00 y 07:00 | 5 |
| Agosto | 13 de agosto, 02:00 a 05:00 | 4 |
| Septiembre | 29 de septiembre, 07:00 y 08:00 | 2 |

Total: 13 horas ausentes dentro del periodo solicitado. No se han rellenado ni
contrastado individualmente con la API en esta prueba.

Actualización posterior: [contraste diario y API](gap-audit-2021.md) completado para
las 13 horas, tanto en 1h como en 1m. Todas siguen pendientes; no se recuperaron velas.

Además, el archivo de diciembre de 2020 contiene un cierre anterior a su apertura
(apertura Unix ms 1608559200000, cierre 1608558440521). Está fuera de las 200 horas
de calentamiento utilizadas, pero la política actual valida cada archivo mensual
completo y lo rechaza. Independientemente de esta anomalía, los huecos de 2021
impiden aceptar el periodo solicitado.

El tramo de enero de 2022 a enero de 2023 pasó todas las comprobaciones mensuales.
El calentamiento correspondiente en diciembre de 2021 también había pasado la
validación, con un cierre anticipado registrado y disponibilidad al final de la hora.
Ese tramo es un candidato para una solicitud separada; no se cambió automáticamente
el periodo solicitado ni se publicaron resultados de rentabilidad.

Originales e informe inmutable guardados en `data/archives/`:
`quality-b31e41ed2cf04a4a0a2ffa67e063de03ccf2055724f643a7fb89197dfe34f78d.json`.

Verificación del proyecto: 70 pruebas superadas, Ruff lint y formato correctos.
No se modificaron las reglas de validación para aceptar estos archivos.
