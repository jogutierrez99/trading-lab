# Importación local de CSV de Binance

La importación usa los mismos controles y el mismo formato de caché que el
descargador. No requiere conexión ni credenciales. Comprueba la correspondencia
de la solicitud, todos los meses necesarios, SHA256 de cada CSV, timestamps UTC,
continuidad, orden, duplicados y OHLCV. Valida cada mes completo antes de recortar
al periodo solicitado y sus velas de calentamiento.

## Nuevas descargas

```powershell
python scripts/download_data.py --config configs/profiles/btc_spot_1h/history.yaml --csv-dir data/csv/binance_spot_BTCUSDT_1h
```

`--csv-dir` fuerza la descarga de fuentes aunque ya exista una caché Parquet.
Se conservan CSV originales bajo `<csv-dir>/<sha256_del_zip>/<nombre>.csv` y se
imprime el evento `csv_manifest` con la ruta de un manifiesto inmutable. También
se conservan fuentes incompletas y su manifiesto para poder auditar el rechazo;
que exista un CSV o manifiesto no significa que sea un dataset aprobado.
Si la descarga falla antes de terminar los meses, no se publica ese manifiesto.

## Revalidación offline

```powershell
python scripts/import_csv.py --config configs/profiles/btc_spot_1h/history.yaml --manifest data/csv/binance_spot_BTCUSDT_1h/audit-76d6f0d0b49477baafd18ac2718b4c36390cc275eb6c34af383464bfa3407f00.json --csv-dir data/csv/binance_spot_BTCUSDT_1h
```

El ejemplo utiliza el manifiesto de extracción real anterior a esta integración.
También se aceptan los nuevos `manifest-<sha256>.json` del descargador: ambos
contienen `request` y `sources`, con URL, SHA256 del ZIP y `csv_sha256`.
Las rutas se derivan del símbolo, mes y hash; no se ejecutan ni utilizan rutas
arbitrarias del JSON. El manifiesto debe identificar exactamente una fuente por
mes requerido. Sus hashes verifican integridad respecto de la procedencia local
suministrada; la importación offline no vuelve a autenticarla contra Binance.

La importación sigue auditando los meses posteriores a un CSV inválido y escribe
un informe inmutable en `reports/csv-import/`. Un fallo de datos termina con código
1 y no guarda un bundle. Los errores estructurales del manifiesto se rechazan antes
de leer CSV y se muestran en la salida del comando. Un histórico válido termina
con `dataset_ready`, código 0 y un bundle verificado en `data/history/`.
Los argumentos `--report-dir` y `--cache-dir` permiten elegir otros destinos.
Las revisiones anteriores nunca se sobrescriben; se reutiliza el mismo dataset si
su huella ya existe y pasa la relectura. No se rellenan ni interpolan velas.

## Resultados reales, 21 de septiembre de 2026

- **2022–2025 más 200 horas previas: rechazado.** Los 49 CSV se pudieron leer y
  verificar. Marzo de 2023 tiene 743 de 744 horas; falta 2023-03-24 13:00 UTC.
  Informe: `reports/csv-import/csv-quality-82ced019a8298dda2028bde9bc50737c16fa77e01ebf660579626d6f1127ab4e.json`.
- **Enero de 2022–enero de 2023 inclusive: aprobado.** 9.704 filas, incluidas 200
  horas de calentamiento. Se reconstruyó desde los CSV la misma huella del dataset
  previamente aprobado, `77a55251e86f4034b317dd312b3bad06bb95c36f6540c74c4b8121793425b6da`,
  y se verificó y reutilizó su bundle sin sobrescribirlo.
  Informe: `reports/csv-import/csv-quality-7d19956562f9484b11b77161830a80f48507773a2d913f0a4c83097c87b35229.json`.

Comando del tramo aprobado, con manifiesto derivado de los 14 meses originales:

```powershell
python scripts/import_csv.py --config configs/profiles/btc_spot_1h/history_2022_jan2023.yaml --manifest data/csv/binance_spot_BTCUSDT_1h/manifest-09e10e86e860773b3be9aebbba1b4ea955e4260775944ca2eb8be71b8474e3ca.json --csv-dir data/csv/binance_spot_BTCUSDT_1h
```

Las pruebas de integración cubren el CLI real, transición de milisegundos a
microsegundos, calentamiento, reutilización inmutable, alteración de archivos,
fuentes ausentes o duplicadas, huecos, desorden y OHLCV inválido fuera del tramo
solicitado. Esta integración es de datos; no cambia la política de huecos ni
ejecuta un backtest. Los CSV, manifiestos y reportes locales siguen ignorados por Git.

Verificación tras integrar los cambios: **121 pruebas superadas**, Ruff lint y
formato correctos (42 archivos Python), y `git diff --check` sin errores.
