# Tarjeta de datos: taxi amarillo de Nueva York por zona y hora (`nyc-tlc`)

Generado por `python -m atlas.domains.mobility.ingest` (AT-030). No editar a mano: se regenera con cada ingesta. Decisiones de diseño y nota de escalado en [`README.md`](README.md).

## Resumen

- Versión de datos: `nyc-tlc-yellow-2024-04_2025-03-v1`; meses locales: 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-03 (periodo cubierto UTC `[2024-04-01T04:00:00+00:00, 2025-04-01T04:00:00+00:00)`).
- Viajes en bruto: 42,812,968; filtrados: 205,426 (0.48%); contados en la serie: 42,607,542.
- Filas zona-hora: 2,303,880 (263 zonas × 8,760 horas UTC); con valor 0: 1,176,709 (51.1%); nulas (hora local ambigua): 526.
- Fuente: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page; descarga: 2026-10-30T17:29:21+00:00.
- Licencia / condiciones: No explicit open-data licence is attached to the files (the TLC page and the NYC Open Data metadata for 'irx2-vgm4' carry none). Published by the NYC Taxi and Limousine Commission as public open data under the NYC Open Data Legal Policy (NYC Administrative Code 23-501 ff.) and the NYC.gov Terms of Use (https://www.nyc.gov/main/terms-of-use); provided as is: 'TLC makes no representations as to the accuracy of these data'. Attribution recommended; review before any public redistribution of derived data.
- Atribución: NYC Taxi & Limousine Commission (TLC) Trip Record Data y Taxi Zones.
- **Qué es y qué no**: viajes completados de taxi amarillo con taxímetro. No es demanda insatisfecha, ni movilidad total, ni emisiones, ni congestión.

## Ficheros de entrada (sha256)

| fichero | sha256 |
|---|---|
| nyc-tlc/data_dictionary_trip_records_yellow.pdf | `b9e9f0ecfa6bd9cc847283379173fd764fe1ab76d2fa143329f541cb1f479993` |
| nyc-tlc/taxi_zone_lookup.csv | `1a99e105092230f8620f301edcca7f80d3080642ff404d28ed957d3fa222c8ed` |
| nyc-tlc/taxi_zones.zip | `f6d711917bb4340f8f644d5366c51665489eb2d426dd1a4a55677721ae5adf17` |
| nyc-tlc/yellow_tripdata_2024-04.parquet | `ce37f736c7cf9e92164c850ef2b502a8f7bb590fc1804b6edbcb80293da01b89` |
| nyc-tlc/yellow_tripdata_2024-05.parquet | `1974230be2b5a3ea92e47b5eb77f32dbf1de896d81ad8df4ab6faba52749ad23` |
| nyc-tlc/yellow_tripdata_2024-06.parquet | `677cf14c8347f745b583f012fbdba072334c6c4efa17bfd6a64369f2ba30329c` |
| nyc-tlc/yellow_tripdata_2024-07.parquet | `af12d6b04daeb78550799ae99933d495b27d715b6dbb0fad9bb750a4537d3070` |
| nyc-tlc/yellow_tripdata_2024-08.parquet | `7315643dd16bafc03e27d9903edbfd35404c2550a695d0da0a3e73852d940cfb` |
| nyc-tlc/yellow_tripdata_2024-09.parquet | `2f42e4a383a6635de803001462848d0aee2b47f6ce899126805d2d05361fb843` |
| nyc-tlc/yellow_tripdata_2024-10.parquet | `d19fe05aa0b259af24eb47051735293287f1e6dc263ba04030ec1ab4c6ec2650` |
| nyc-tlc/yellow_tripdata_2024-11.parquet | `5ef321876de5007a7c147a347389133fc94fd7ac28f82eb1d57d8f2cf05cfd3b` |
| nyc-tlc/yellow_tripdata_2024-12.parquet | `41ebf7db80bebde60c58e5143c14cdf38ad04a0f3e3ff44215b3e240d55f6c78` |
| nyc-tlc/yellow_tripdata_2025-01.parquet | `9af277e4c0d3f9deb30644da822981e1e7df6af58313170fd3aa8a474485488a` |
| nyc-tlc/yellow_tripdata_2025-02.parquet | `037cba555a73663f3a51a2c27816e40e3feb364769942bdf122b9da31e377bd3` |
| nyc-tlc/yellow_tripdata_2025-03.parquet | `20c4b77cce457b7cfdae77c5069ca7dc91c167f876a41467f4502ab69487a186` |

## Esquema por fichero

| columna | 2024-04 | 2024-05 | 2024-06 | 2024-07 | 2024-08 | 2024-09 | 2024-10 | 2024-11 | 2024-12 | 2025-01 | 2025-02 | 2025-03 | entre meses |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `VendorID` | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | igual |
| `tpep_pickup_datetime` | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | igual |
| `tpep_dropoff_datetime` | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | TIMESTAMP | igual |
| `passenger_count` | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | igual |
| `trip_distance` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `RatecodeID` | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | igual |
| `store_and_fwd_flag` | VARCHAR | VARCHAR | VARCHAR | VARCHAR | VARCHAR | VARCHAR | VARCHAR | VARCHAR | VARCHAR | VARCHAR | VARCHAR | VARCHAR | igual |
| `PULocationID` | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | igual |
| `DOLocationID` | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | INTEGER | igual |
| `payment_type` | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | BIGINT | igual |
| `fare_amount` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `extra` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `mta_tax` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `tip_amount` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `tolls_amount` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `improvement_surcharge` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `total_amount` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `congestion_surcharge` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `Airport_fee` | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | DOUBLE | igual |
| `cbd_congestion_fee` | - | - | - | - | - | - | - | - | - | DOUBLE | DOUBLE | DOUBLE | **distinto** |

Columnas que no están en todos los meses: `cbd_congestion_fee`.

## Viajes por mes y filtros

Cada viaje se cuenta bajo **el primer** motivo que cumple (en este orden), así que las columnas suman exactamente `bruto - contados`. Umbral de duración: 6 h (medido en enero y marzo de 2025: la mediana de las duraciones positivas es de ~12 min, el percentil 99,9 de ~1,7 h y solo ~170-200 viajes/mes están entre 3 h y 6 h; por encima de 12 h son casi siempre medidores que se dejaron encendidos).

| mes | bruto | timestamp nulo | recogida fuera del mes del fichero | bajada anterior a la recogida | duración cero | duración mayor que el máximo | PULocationID nulo o fuera del lookup | PULocationID 264/265 o sin polígono | hora local inexistente (primavera) | hora local ambigua (otoño) | contados |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024-04 | 3,514,289 | 0 | 9 | 70 | 1,019 | 1,979 | 0 | 12,712 | 0 | 0 | 3,498,500 |
| 2024-05 | 3,723,833 | 0 | 33 | 42 | 1,105 | 1,978 | 0 | 13,733 | 0 | 0 | 3,706,942 |
| 2024-06 | 3,539,193 | 0 | 51 | 8 | 1,132 | 1,944 | 0 | 13,424 | 0 | 0 | 3,522,634 |
| 2024-07 | 3,076,903 | 0 | 47 | 5 | 1,063 | 1,772 | 0 | 11,648 | 0 | 0 | 3,062,368 |
| 2024-08 | 2,979,183 | 0 | 51 | 9 | 1,009 | 1,732 | 0 | 10,305 | 0 | 0 | 2,966,077 |
| 2024-09 | 3,633,030 | 0 | 49 | 45 | 1,116 | 1,646 | 0 | 11,662 | 0 | 0 | 3,618,512 |
| 2024-10 | 3,833,771 | 0 | 40 | 39 | 963 | 1,757 | 0 | 12,382 | 0 | 0 | 3,818,590 |
| 2024-11 | 3,646,369 | 0 | 50 | 1,078 | 783 | 1,850 | 0 | 11,111 | 0 | 8,741 | 3,622,756 |
| 2024-12 | 3,668,371 | 0 | 34 | 99 | 1,124 | 1,902 | 0 | 11,636 | 0 | 0 | 3,653,576 |
| 2025-01 | 3,475,226 | 0 | 22 | 124 | 1,927 | 1,203 | 0 | 9,463 | 0 | 0 | 3,462,487 |
| 2025-02 | 3,577,543 | 0 | 31 | 93 | 5,071 | 1,133 | 0 | 8,574 | 0 | 0 | 3,562,641 |
| 2025-03 | 4,145,257 | 0 | 33 | 81 | 22,199 | 1,373 | 0 | 9,112 | 0 | 0 | 4,112,459 |
| total | 42,812,968 | 0 | 450 | 1,693 | 38,511 | 20,269 | 0 | 135,762 | 0 | 8,741 | 42,607,542 |

Conteo independiente de cada filtro (un viaje puede cumplir varios):

| mes | pickup_outside_file_month | dropoff_before_pickup | zero_duration | duration_over_max | pickup_zone_invalid | pickup_zone_unknown_or_outside | pickup_nonexistent_local_hour | pickup_ambiguous_local_hour | fuera de mes pero dentro del periodo cubierto |
|---|---|---|---|---|---|---|---|---|---|
| 2024-04 | 9 | 70 | 1,019 | 1,982 | 0 | 12,848 | 0 | 0 | 1 |
| 2024-05 | 33 | 42 | 1,105 | 1,982 | 0 | 13,863 | 0 | 0 | 26 |
| 2024-06 | 51 | 8 | 1,132 | 1,950 | 0 | 13,514 | 0 | 0 | 45 |
| 2024-07 | 47 | 5 | 1,063 | 1,774 | 0 | 11,729 | 0 | 0 | 44 |
| 2024-08 | 51 | 9 | 1,009 | 1,735 | 0 | 10,398 | 0 | 0 | 49 |
| 2024-09 | 49 | 45 | 1,116 | 1,649 | 0 | 11,728 | 0 | 0 | 46 |
| 2024-10 | 40 | 39 | 963 | 1,758 | 0 | 12,453 | 0 | 0 | 39 |
| 2024-11 | 50 | 1,078 | 783 | 1,852 | 0 | 11,175 | 0 | 9,869 | 47 |
| 2024-12 | 34 | 99 | 1,124 | 1,906 | 0 | 11,733 | 0 | 0 | 31 |
| 2025-01 | 22 | 124 | 1,927 | 1,203 | 0 | 9,521 | 0 | 0 | 22 |
| 2025-02 | 31 | 93 | 5,071 | 1,133 | 0 | 8,635 | 0 | 0 | 31 |
| 2025-03 | 33 | 81 | 22,199 | 1,373 | 0 | 9,235 | 0 | 0 | 29 |

Duración cero por `VendorID` (1 CMT, 2 Curb, 6 Myle, 7 Helix): 2024-04: 1=909, 2=108, 6=2; 2024-05: 1=1,017, 2=85, 6=3; 2024-06: 1=1,039, 2=93; 2024-07: 1=969, 2=94; 2024-08: 1=920, 2=89; 2024-09: 1=1,029, 2=86, 6=1; 2024-10: 1=902, 2=61; 2024-11: 1=733, 2=49, 6=1; 2024-12: 1=810, 2=81, 6=3, 7=230; 2025-01: 1=640, 2=76, 6=5, 7=1,206; 2025-02: 1=573, 2=71, 6=7, 7=4,420; 2025-03: 1=622, 2=93, 6=3, 7=21,481. PULocationID 264/265 filtrados: 2024-04: 264=10,821, 265=1,891; 2024-05: 264=11,599, 265=2,134; 2024-06: 264=11,438, 265=1,986; 2024-07: 264=9,520, 265=2,128; 2024-08: 264=8,183, 265=2,122; 2024-09: 264=9,384, 265=2,278; 2024-10: 264=10,147, 265=2,235; 2024-11: 264=9,369, 265=1,742; 2024-12: 264=9,487, 265=2,149; 2025-01: 264=8,089, 265=1,374; 2025-02: 264=7,416, 265=1,158; 2025-03: 264=7,571, 265=1,541. Duplicados exactos detectados (se conservarían): 3.

## Serie zona-hora

Una fila por zona (polígonos del shapefile) y hora UTC de **todo** el periodo cubierto: `value` = nº de recogidas (`feature_name=pickups`, `unit=trips`), `timestamp_utc` = inicio de la hora, `aggregation_window_*_utc` = esa hora, `n_records` = recogidas, `source_timestamp_local` = hora local con desfase.

**0 ≠ null.** Una zona-hora sin recogidas dentro del periodo cubierto es un 0 genuino (`n_records=0`). Fuera del periodo no hay filas. Solo la hora local ambigua de otoño produce `null` (`missing_reason=invalid_observation`, `validity_flag=ambiguous_local_hour`).

| mes local | horas UTC | filas zona-hora | recogidas | filas con 0 | filas null |
|---|---|---|---|---|---|
| 2024-04 | 720 | 189,360 | 3,498,500 | 104,758 | 0 |
| 2024-05 | 744 | 195,672 | 3,706,942 | 104,135 | 0 |
| 2024-06 | 720 | 189,360 | 3,522,634 | 100,918 | 0 |
| 2024-07 | 744 | 195,672 | 3,062,368 | 109,537 | 0 |
| 2024-08 | 744 | 195,672 | 2,966,077 | 107,747 | 0 |
| 2024-09 | 720 | 189,360 | 3,618,512 | 97,319 | 0 |
| 2024-10 | 744 | 195,672 | 3,818,590 | 102,388 | 0 |
| 2024-11 | 721 | 189,623 | 3,622,756 | 96,480 | 526 |
| 2024-12 | 744 | 195,672 | 3,653,576 | 103,789 | 0 |
| 2025-01 | 744 | 195,672 | 3,462,487 | 99,974 | 0 |
| 2025-02 | 672 | 176,736 | 3,562,641 | 75,501 | 0 |
| 2025-03 | 743 | 195,409 | 4,112,459 | 74,163 | 0 |

Zona-horas con 0: **51.1%** en total y 47.5% entre las 245 zonas con ≥ 100 recogidas en el periodo. Recuentos > 0 por zona-hora: mediana 4, p90 130, p99 366, máximo 1062. Serie muy asimétrica y con muchos ceros: pocas zonas concentran la demanda.

### Zonas con más recogidas

| zona | nombre | recogidas | horas con recogidas | % horas con 0 |
|---|---|---|---|---|
| 132 | JFK Airport | 1,990,698 | 8,750 | 0.1% |
| 161 | Midtown Center | 1,971,399 | 8,755 | 0.0% |
| 237 | Upper East Side South | 1,965,071 | 8,720 | 0.4% |
| 236 | Upper East Side North | 1,767,145 | 8,641 | 1.3% |
| 162 | Midtown East | 1,441,024 | 8,752 | 0.1% |
| 230 | Times Sq/Theatre District | 1,434,687 | 8,750 | 0.1% |
| 186 | Penn Station/Madison Sq West | 1,406,257 | 8,758 | 0.0% |
| 142 | Lincoln Square East | 1,328,672 | 8,718 | 0.5% |
| 138 | LaGuardia Airport | 1,291,908 | 8,174 | 6.7% |
| 170 | Murray Hill | 1,205,814 | 8,746 | 0.1% |

### Zonas con menos recogidas (entre las que tienen alguna)

| zona | nombre | recogidas | horas con recogidas | % horas con 0 |
|---|---|---|---|---|
| 176 | Oakwood | 45 | 44 | 99.5% |
| 187 | Port Richmond | 39 | 38 | 99.6% |
| 44 | Charleston/Tottenville | 27 | 25 | 99.7% |
| 84 | Eltingville/Annadale/Prince's Bay | 25 | 22 | 99.8% |
| 204 | Rossville/Woodrow | 22 | 20 | 99.8% |
| 199 | Rikers Island | 17 | 17 | 99.8% |
| 5 | Arden Heights | 11 | 11 | 99.9% |
| 99 | Freshkills Park | 3 | 3 | 100.0% |
| 105 | Governor's Island/Ellis Island/Liberty Island | 3 | 3 | 100.0% |
| 110 | Great Kills Park | 1 | 1 | 100.0% |

Zonas con polígono y **cero** recogidas en todo el periodo: [103, 104].

### Patrón horario y semanal (total de la ciudad, hora local)

Media de recogidas por hora local sobre horas completas; laborable = lun-vie, fin de semana = sáb-dom.

| hora | laborable | fin de semana |
|---|---|---|
| 00 | 2,198 | 6,529 |
| 01 | 1,061 | 5,109 |
| 02 | 578 | 3,641 |
| 03 | 388 | 2,377 |
| 04 | 436 | 1,408 |
| 05 | 813 | 684 |
| 06 | 1,942 | 1,017 |
| 07 | 3,937 | 1,462 |
| 08 | 5,323 | 2,243 |
| 09 | 5,312 | 3,477 |
| 10 | 5,271 | 4,640 |
| 11 | 5,547 | 5,464 |
| 12 | 5,973 | 6,194 |
| 13 | 6,224 | 6,540 |
| 14 | 6,826 | 6,656 |
| 15 | 7,156 | 6,729 |
| 16 | 7,250 | 7,052 |
| 17 | 8,276 | 7,314 |
| 18 | 8,884 | 7,467 |
| 19 | 7,626 | 6,962 |
| 20 | 7,108 | 6,007 |
| 21 | 7,409 | 5,821 |
| 22 | 6,687 | 5,834 |
| 23 | 4,849 | 5,328 |

| día | lun | mar | mié | jue | vie | sáb | dom |
|---|---|---|---|---|---|---|---|
| media diaria de recogidas | 99,516 | 115,464 | 121,059 | 127,370 | 122,312 | 125,719 | 105,691 |

## Horario de verano (DST)

Estrategia (detalle en `aggregate.py` y `README.md`): la malla de horas UTC se construye con `zoneinfo`. La hora local inexistente (02:00-02:59 del día de primavera, p. ej. 9 de marzo de 2025) no puede mostrarla un taxímetro: esas recogidas se descartan y se cuentan. La hora local ambigua (01:00-01:59 del día de otoño, p. ej. 3 de noviembre de 2024) se escribe como `null` en sus dos horas UTC y sus viajes se excluyen. Ambos casos están cubiertos por tests sintéticos; los días con cambio que caen en los meses ingeridos se detallan abajo.

- **2024-11-03**: 25 horas UTC en el día local. Recogidas de toda la ciudad por hora local: 00h=7,368, 01h=-, 02h=2,718, 03h=1,895, 04h=1,369, 05h=1,540, 06h=1,879, 07h=2,083, 08h=2,548, 09h=3,622, 10h=5,047, 11h=5,572, 12h=6,367, 13h=6,832, 14h=7,055, 15h=7,770, 16h=8,103, 17h=7,728, 18h=7,703, 19h=7,598, 20h=6,207, 21h=5,077, 22h=3,573, 23h=2,380. La hora local 01h es ambigua: sus dos horas UTC son null para todas las zonas (recogidas de ese rótulo local excluidas: 8,741).
- **2025-03-09**: 23 horas UTC en el día local. Recogidas de toda la ciudad por hora local: 00h=9,513, 01h=7,854, 03h=6,162, 04h=3,901, 05h=2,038, 06h=1,634, 07h=1,621, 08h=2,238, 09h=3,466, 10h=4,611, 11h=5,238, 12h=6,014, 13h=6,249, 14h=6,482, 15h=6,269, 16h=6,432, 17h=6,447, 18h=6,279, 19h=6,539, 20h=6,238, 21h=5,072, 22h=3,757, 23h=2,545. Recogidas en la hora inexistente 02h: 0.

## Zonas y geometría

- Fuente: `taxi_zones.zip` (shapefile ESRI, EPSG:2263 «NAD83 / New York Long Island (ftUS)», 263 polígonos, 98,192 vértices). Lookup: 265 filas; en el shapefile pero no en el lookup: ninguna; nombre/borough distinto entre lookup y shapefile: ninguna.
- Sin polígono (geometría `null`, por diseño): [264, 265] (264 «Unknown», 265 «Outside of NYC»). Nombres compartidos por varios IDs: «Corona» → [56, 57]; «Governor's Island/Ellis Island/Liberty Island» → [103, 104, 105]. Polígonos de origen inválidos: 0; el recubrimiento original no es un coverage válido (solapes/huecos mínimos).
- `taxi_zones.geojson` (referencia, WGS84, 1e-7°): 98,112 vértices, 2.56 MB, {'POLYGON': 240, 'MULTIPOLYGON': 23}. `taxi_zones_simplified.geojson` (frontend): 17,892 vértices (81.8 % menos), 506 kB.
- Simplificación: GEOS coverage_clean (snap 0.5 ft) + coverage_simplify in EPSG:2263; tolerancia 50 ft (15.24 m), redondeo 1e-5° (~1 m). Polígonos válidos: True; vacíos: False; coverage válido tras simplificar: True (bordes compartidos idénticos a ambos lados); cambio de área total 0.00835 %, máximo por zona 1.2244 %.
- Reproyección: bbox [-74.25559, 40.49612, -73.70001, 40.91553]; todos los centroides dentro del bbox de NYC: True.

## Rendimiento

DuckDB con `memory_limit=1500MB` y 4 hilos, un mes cada vez; los viajes nunca pasan por pandas.

| mes | viajes | segundos | RSS tras el mes (MB) | pico RSS hasta ahora (MB) |
|---|---|---|---|---|
| 2024-04 | 3,514,289 | 1.18 | 1067.5 | 1120.0 |
| 2024-05 | 3,723,833 | 1.05 | 765.1 | 1174.4 |
| 2024-06 | 3,539,193 | 0.89 | 1063.7 | 1174.4 |
| 2024-07 | 3,076,903 | 0.85 | 903.3 | 1174.4 |
| 2024-08 | 2,979,183 | 0.75 | 907.7 | 1174.4 |
| 2024-09 | 3,633,030 | 0.9 | 954.4 | 1174.4 |
| 2024-10 | 3,833,771 | 0.88 | 947.8 | 1174.4 |
| 2024-11 | 3,646,369 | 0.91 | 1019.6 | 1174.4 |
| 2024-12 | 3,668,371 | 0.88 | 993.7 | 1174.4 |
| 2025-01 | 3,475,226 | 0.94 | 962.6 | 1174.4 |
| 2025-02 | 3,577,543 | 0.95 | 1039.8 | 1174.4 |
| 2025-03 | 4,145,257 | 0.98 | 796.7 | 1228.3 |

Total (zonas + meses): 12.62 s; pico RSS del proceso 1228.3 MB (al inicio 100.8 MB).

## Limitaciones conocidas

- Completed yellow-taxi trips only (vendor-reported). Not unmet demand, not all urban mobility (no green cabs, FHV, ride-hailing or transit), and not an emissions or congestion measure.
- Timestamps are naive local wall-clock times (no UTC offset in the files; the data dictionary does not state the zone). Nonexistent spring-forward hours are dropped and counted; the repeated fall-back hour cannot be split between its two occurrences, so both UTC hours are written as null (invalid_observation, validity_flag=ambiguous_local_hour) and the pooled trips are excluded. In the ingested months: 8741 pickups in an ambiguous hour, 0 in a nonexistent hour.
- Zero versus missing: every zone-hour inside the covered period has a row; no pickup means value=0 and n_records=0 (51.1% of zone-hours, 47.5% among the 245 zones with at least 100 pickups). Hours outside the period have no rows. A zero means no recorded yellow-taxi pickup, not that nobody travelled there.
- 205,426 of 42,812,968 trips (0.48%) are filtered (incoherent time, duration above 6 h, or LocationID 264/265). The filter reads the dropoff time of the record, which would not be known at prediction time, but it only removes corrupt records; no dropoff or fare field enters the series.
- Zero-duration trips jump between months and are concentrated in VendorID 7 (Helix); they may be cancelled or test meter activations, so month-to-month totals carry a vendor-reporting component (per-month counts in the dataset card).
- Exact duplicate trip rows: none found with SELECT DISTINCT over all columns; near-duplicates cannot be detected because the files have no trip identifier.
- Zones: 263 polygons; LocationIDs [264, 265] have no polygon (geometry null) and their pickups are not in the series. 2 zone names are shared by several IDs. 2 polygons ([103, 104]) have no pickup at all in the period. Boundaries are the current TLC shapefile applied to the whole period; its Shape_Leng/Shape_Area attributes are in degrees and are ignored (areas are recomputed in EPSG:2263).
- The TLC publishes the data as is and makes no representation as to its accuracy; no explicit open licence is attached. Review the terms before redistributing derived data.
- 12 consecutive months (2024-04 to 2025-03): a single year, so no year-over-year comparison, one occurrence of each holiday and no weather. The cbd_congestion_fee regime (congestion pricing in Manhattan below 60th St) began 2025-01-05 and is inside the window: the first months of the period are before it, the last ones after it.
