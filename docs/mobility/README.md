# Atlas Mobility: recogidas de taxi amarillo de NYC por zona y hora (AT-030)

Pipeline reproducible de los ficheros mensuales Parquet de la TLC a una serie canónica «recogidas por taxi zone y hora» (Parquet,
validada con `atlas.contracts.validate_observations`), más las taxi zones oficiales como `EntityCollection` (referencia y copia
simplificada para el frontend) y un informe de calidad. Resultados de la última ingesta real, con todas las cifras:
[`nyc_tlc_yellow_dataset_card.md`](nyc_tlc_yellow_dataset_card.md) (generado, no se edita). La tabla de features y del target a una hora (AT-031) se describe
en [`nyc_pickups_h1_feature_card.md`](nyc_pickups_h1_feature_card.md) y su EDA con la recomendación de split en [`nyc_pickups_h1_eda.md`](nyc_pickups_h1_eda.md); se construye con `python -m atlas.domains.mobility.features`. El target relativo «baja / normal / alta / muy alta» y sus features relativas (AT-031b) están en [`nyc_pickups_h1_level.md`](nyc_pickups_h1_level.md) (`python -m atlas.domains.mobility.levels`).

## Reproducir

```bash
# desde la raíz del checkout (o worktree); python = el del entorno del proyecto
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data   # si se comparte el data/ de otro checkout
PYTHONPATH=src python -m atlas.domains.mobility.ingest --months 2024-04..2025-03
PYTHONPATH=src python -m atlas.domains.mobility.features --write-spec --eda     # AT-031: tabla de features, feature_spec.json, EDA
```

Hace, en este orden (todo idempotente):

1. **Descarga** a `$ATLAS_DATASETS_ROOT/nyc-tlc/` (por defecto `~/Datasets`; `--datasets-root` o `ATLAS_DATASETS_ROOT`) y crea el enlace
   `data/raw/nyc-tlc`. `source_manifest.json` (`SourceManifest`) guarda URL, sha256, bytes, licencia, atribución y fecha por fichero. Los
   ficheros raw quedan en solo lectura y no se vuelven a bajar si el sha256 coincide. Los PDF de `www.nyc.gov/assets` devuelven HTTP 403 a
   clientes automáticos: si falla, se busca `nyc-tlc/manual/<nombre>` (guardarlo desde un navegador). El diccionario de datos de esta
   ingesta entró por esa vía.
2. **Zonas**: `taxi_zones.zip` + `taxi_zone_lookup.csv` a `data/processed/mobility/taxi_zones.geojson` (referencia) y
   `taxi_zones_simplified.geojson` (frontend).
3. **Serie**: un mes cada vez con DuckDB (limpieza, localización horaria, recuento por zona y hora UTC, relleno de ceros) a
   `data/processed/mobility/observations/year=YYYY/month=M/part-0.parquet`.
4. **Validación** con `validate_observations` (falla la ingesta si hay violaciones) y comprobación de que
   `bruto - filtrados = contados = suma de la serie`.
5. **Informes**: `quality_report.json` (`QualityReport`), `ingest_details.json` y la tarjeta de datos de esta carpeta.

Otras opciones: `--download-only`, `--skip-download`, `--refresh`, `--out-dir`, `--doc`/`--no-doc`, `--memory-limit`, `--threads`.
Tests (sin red ni datos reales): `make test` o `PYTHONPATH=src python -m pytest tests/mobility`. Los tests que necesitan
`shapely>=2.2`, `pyproj` y `pyshp` se saltan solos si no están instalados.

## Qué se ingiere y por qué

- **Meses: 2024-04 a 2025-03** (12 meses consecutivos, yellow; AT-031 amplió los tres meses de invierno de AT-030, 2025-01 a 2025-03, para tener un split cronológico honesto con lags semanales). Los nueve
  ficheros de 2024 tienen las mismas 19 columnas y tipos que los de 2025 salvo `cbd_congestion_fee` (tasa de la zona de congestión, desde 2025-01-05), que solo está en 2025 y no se usa; no hubo ningún problema de esquema.
  La ventana incluye los dos cambios de hora reales: domingo 3 de noviembre de 2024 (otoño, hora ambigua) y domingo 9 de marzo de 2025 (primavera). La TLC publica ya hasta 2026-09; 2026-07 en adelante añade la columna `request_source`
  (comprobado con los metadatos Parquet remotos), pero se prefirió una ventana con un esquema estable y verificado. Cambiar de meses es editar `configs/mobility/nyc_tlc.json` (lista de ficheros y `data_version`) y pasar `--months`.
- **Qué mide**: viajes completados de taxi amarillo, tal y como los envían los proveedores TPEP. No es demanda insatisfecha, ni movilidad
  total, ni emisiones, ni congestión.
- **Entradas permitidas para el target de demanda**: solo la hora y la zona de recogida. La hora de bajada se lee únicamente para contar y
  descartar registros incoherentes; ningún campo de bajada, tarifa o distancia llega a la serie (hay un test).

## Decisiones de diseño

| Tema | Decisión |
|---|---|
| Entidad | `entity_id` = `PULocationID` como texto (`"1"`..`"263"`); una fila por zona con polígono y hora UTC. |
| Observación | `feature_name=pickups`, `unit=trips`, `timestamp_utc` = inicio de la hora, `aggregation_window_*_utc` = esa hora, `n_records` = recogidas, `source_timestamp_local` = hora local con desfase (`2025-01-01 00:00-0500`), `source_id=nyc-tlc-yellow`. |
| Partición | `year=/month=` del **mes local del fichero** (no UTC como en `air`): cada mes es una unidad independiente y reemplazable. |
| Filtros (en este orden, cada viaje cuenta bajo el primero que cumple) | timestamp nulo; recogida fuera del mes del fichero (intervalo semiabierto); bajada < recogida; duración 0; duración > 6 h; `PULocationID` nulo o fuera del lookup; 264/265 o sin polígono; hora local inexistente; hora local ambigua. Todos se cuentan, nada se descarta en silencio. |
| Umbral de 6 h | En enero y marzo: mediana de las duraciones positivas ≈ 12 min, p99,9 ≈ 1,7 h, solo ~170-200 viajes/mes entre 3 h y 6 h y casi todo lo que pasa de 12 h son medidores que se dejaron encendidos. 6 h deja pasar cualquier viaje real largo y quita lo claramente corrupto (0,03 %). Es un parámetro (`max_trip_hours` en `configs/mobility/nyc_tlc.json`). |
| IDs 264 y 265 | Son entidades de la `EntityCollection` con `geometry: null` (no existe polígono, no se inventa). Sus recogidas (0,24 % de los viajes) se filtran y cuentan; no hay filas en la serie porque no hay dónde pintarlas. |
| Nombres repetidos | 56/57 «Corona» y 103/104/105 «Governor's Island/Ellis Island/Liberty Island» son IDs distintos con polígono propio; se mantienen separados y llevan `display_name` con el ID. 103 y 104 no tienen ninguna recogida en los 12 meses. |
| Duplicados | No hay identificador de viaje. Se cuentan los duplicados exactos (`SELECT DISTINCT *`): 0. No se eliminan. |

### Horario de verano

Los timestamps de la TLC son horas de reloj locales sin desfase. Se construye con `zoneinfo` la malla completa de horas UTC del mes local y
la hora local de cada una; con eso:

- **Hora inexistente** (02:00-02:59 del 9-mar-2025): un taxímetro no puede marcarla, no se sabe la hora real; esas recogidas se descartan y
  se cuentan (`pickup_nonexistent_local_hour`; en estos datos: 0). El eje UTC no pierde ninguna hora: pasa de 06Z (01:xx EST) a 07Z (03:xx EDT).
- **Hora ambigua** (01:00-01:59 del 2-nov): una hora local ingenua mezcla las dos ocurrencias y no hay forma de separarlas sin inventar
  recuentos. Sus viajes se descartan y se cuentan (`pickup_ambiguous_local_hour`), y las **dos** horas UTC (05Z y 06Z) de todas las zonas se escriben
  con `value=null`, `missing_reason=invalid_observation`, `validity_flag=ambiguous_local_hour`. Es la única fuente de nulls de la serie.
  AT-031 trata esas dos horas como no observadas: son null en el target y en toda feature que las necesite (ver la tarjeta de features), nunca 0.
- Con datos reales (2024-11-03, dentro del dataset desde AT-031): 8.741 recogidas con hora local 01:xx excluidas (9.869 sin contar el orden de los filtros), 526 filas null (2 horas × 263 zonas), 0 recogidas en hora inexistente en 2025-03-09.
  Para comparar, en ese día la hora 00:xx tiene 7.368 recogidas en toda la ciudad y la 02:xx 2.718. La hora 01:xx pooled es mayor que la de un domingo normal pero **no** llega al doble, así que estos datos no demuestran por sí solos
  si todos los proveedores registran hora de reloj ingenua; es la hipótesis de trabajo (la documentación no lo dice).

### Cero frente a ausente

Dentro del periodo cubierto (cada hora UTC de cada mes local ingerido) una zona-hora sin recogidas es un **0 genuino** (`value=0`,
`n_records=0`); la serie es densa (263 zonas × todas las horas). Fuera del periodo no hay filas. `null` solo aparece en la hora ambigua.
Cuidado al interpretar: el 51 % de las zona-horas son 0 (47 % entre las 245 zonas con ≥ 100 recogidas en el periodo); un 0 significa «ninguna recogida
registrada de taxi amarillo», no que la zona estuviese inactiva. Para el mapa, `0` y `null` deben dibujarse distinto.

### Geometría

- Fuente oficial: `taxi_zones.zip` de la TLC, shapefile ESRI en EPSG:2263 (NAD83 / New York Long Island, pies US survey; se lee el `.prj`).
  263 polígonos (240 Polygon, 23 MultiPolygon), 0 inválidos. Se reproyecta con `pyproj` a WGS84 (el paso NAD83 a WGS84 no lleva
  transformación de datum, error posicional del orden de 1 m, irrelevante a escala de zona).
- **Referencia** `taxi_zones.geojson`: todos los vértices, redondeo a 1e-7° (~1 cm), anillos exteriores antihorarios (RFC 7946). 2,6 MB.
- **Frontend** `taxi_zones_simplified.geojson`: `coverage_clean` de GEOS (snap 0,5 ft) para que las fronteras compartidas coincidan, `coverage_simplify` a 50 ft
  (15,2 m) en EPSG:2263 (los bordes comunes se simplifican igual a ambos lados, así que no quedan huecos ni solapes) y redondeo a 1e-5° (~1 m).
  17.892 vértices (82 % menos), 506 kB, todos los polígonos válidos, cambio de área total 0,008 %, máximo por zona 1,2 % (zonas diminutas). El recubrimiento original
  **no** es un coverage válido (35 ft² de solapes en total); `coverage_clean` lo arregla con cambios de ~1e-4 % de área.
- Atributos de cada entidad: borough, zone, service_zone (lookup), `special_id`, `has_geometry`, `display_name` si el nombre se repite, `label_lon_lat`
  (`point_on_surface`, siempre dentro del polígono) y `area_km2` (recalculada en EPSG:2263; los atributos `Shape_Leng/Shape_Area` del shapefile están en grados y se ignoran).

## Nota de escalado a varios años

Medido en la estación de trabajo (4 hilos, `memory_limit=1500MB`, ficheros en disco local): 12 meses (42,8 M de viajes, ~690 MB de Parquet) tardan 12,6 s de punta a punta con pico de RSS de 1,23 GB; con tres meses (11,2 M de viajes) eran 3,9 s y 1,20 GB: **el pico no
crece con el número de meses**, porque cada mes se agrega aparte y solo se retiene su tabla zona-hora (~190 k filas, ~260 kB en Parquet). Casi todo el pico viene del escaneo de duplicados exactos (`SELECT DISTINCT *`); sin él, ~0,9 GB.
Los viajes nunca pasan por pandas. La tabla de features (AT-031) lee la serie completa (2,3 M de filas) en DuckDB: 1-2 s y ~1,0 GB de pico.

Extrapolación **no medida**: el coste es lineal en el número de meses, ~1 s por mes más la descarga (~60-70 MB/mes), así que diez años serían unos 2-3 min de CPU, ~8 GB de
raw y ~35 MB de salida, con la misma memoria. Cómo extenderlo:

- **Unidad de trabajo = mes local**: ya es la partición (`year=/month=`) y los meses no dependen entre sí. Para añadir un mes, procesar solo ese y reemplazar su partición. Hoy
  `run` borra y rehace todo `observations/`; con ~1 s por mes es válido relanzar el rango entero. Hacer el reemplazo de una sola partición es un cambio pequeño si hiciera falta.
- **Fuera de RAM**: ni siquiera un mes entero se carga; DuckDB lee las tres columnas necesarias del Parquet y desborda a disco (`temp_directory`) si hace falta.
  Los ficheros de salida están ordenados por (zona, hora), así que los group-by y las ventanas por zona de AT-031 (lags) leen cada zona de forma contigua y se pueden hacer por bloque de zonas.
- **Cuidado con la deriva de esquema y de zonas entre años**: `inventory_schema` falla en voz alta si falta una columna requerida y la tarjeta de datos tabula las
  diferencias de tipos y columnas por fichero. Con 2024-04 a 2025-03 solo difiere `cbd_congestion_fee`. No se han probado ficheros anteriores a 2024-04: no se verificó la presencia de `PULocationID` en ficheros antiguos, ni cambios de
  límites de zona entre años (el shapefile es el vigente); hay que revisarlo antes de apilar más años.
- Los meses con hora ambigua (octubre-noviembre) producen 2 horas null; los de marzo, una hora UTC menos en el mes.

## Límites y avisos

Resumidos en `known_limitations` de `quality_report.json` y en la tarjeta de datos. Lo principal: solo taxi amarillo completado; un solo año (12 meses, 2024-04 a 2025-03; el régimen del peaje de congestión empieza a mitad del periodo); variación del recuento
de viajes de duración cero entre meses ligada a un proveedor (VendorID 7); condiciones de uso sin licencia abierta explícita; hora ambigua tratada como no observada.
