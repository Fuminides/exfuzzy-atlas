# Atlas Air: meteorología horaria de Madrid y asociación con las estaciones de aire (AT-011)

Cifras de calidad (generadas, no se editan): [`madrid_meteo_quality.md`](madrid_meteo_quality.md). Tabla de features y
split recomendado: [`madrid_no2_h6.md`](madrid_no2_h6.md).

## Fuente

| Qué | URL |
|---|---|
| Dataset horario (2019+) | https://datos.madrid.es/dataset/300352-0-meteorologicos-horarios |
| Intérprete de ficheros | https://datos.madrid.es/dataset/300352-0-meteorologicos-horarios/resource/300352-122-meteorologicos-horarios/download/interpretacic3b3n_datos_meteorologicos.pdf |
| Estaciones meteorológicas (coordenadas oficiales) | https://datos.madrid.es/dataset/300360-0-meteorologicos-estaciones |

Licencia CC BY 4.0, Ayuntamiento de Madrid. Los 146 ficheros (≈ 89 MB) están en
`$ATLAS_DATASETS_ROOT/madrid-meteo/` (+ `madrid-meteo-stations/`), cada directorio con `source_manifest.json`
(URL, sha256, fecha). Las URLs de descarga están en `configs/air/madrid_meteo.json`. 2019-2024: un CSV y un TXT por mes
(el portal ofrece además XML, no se descarga); 2025 en adelante: un único CSV acumulado que el portal amplía cada mes
(a 2026-10-30 llegaba a septiembre de 2026; solo se ingieren 2019-2025). El portal devuelve 403 si se piden muchos
ficheros seguidos: `http_fetch` espera 1,5 s entre peticiones y reintenta con espera creciente.

## Qué dice y qué no dice el intérprete

- Mismo esquema que el del aire (`PROVINCIA;MUNICIPIO;ESTACION;MAGNITUD;PUNTO_MUESTREO;ANO;MES;DIA;H01;V01;...;H24;V24`;
  TXT sin cabecera con el periodo `02`). **Solo `V` es válido** (explícito en el intérprete).
- Magnitudes y unidades (anexo II): 81 velocidad del viento (m/s), 82 dirección (grados; 0 = N, 90 = E), 83 temperatura
  (°C), 86 humedad relativa (%), 87 presión barométrica (mb), 88 radiación solar (W/m²), 89 precipitación (l/m²); 80
  (radiación ultravioleta, «Mw/m2», unidad ambigua) figura en el anexo y solo aparece de enero a mayo de 2019 en las
  estaciones 24, 54 y 59 (20.160 huecos): no se ingiere y se cuenta como magnitud excluida en el informe de calidad.
- **No dice** en qué huso están las horas ni cómo se trata el cambio de hora (solo «H01 corresponde al dato de la 1 de la
  mañana»). Se asume la misma convención que el aire (hora local de Madrid; `Hnn` es la hora que termina a las `nn:00`) y
  **se comprueba con los datos**: en los 7 cambios de marzo 2019-2025 el hueco `H03` es inválido en el 100 % de las filas
  (si `Hnn` empezara en `nn:00` sería `H02`), idéntico a lo observado en el aire. En octubre no hay hueco inválido
  sistemático, así que la asignación de `H03` a la primera ocurrencia sigue siendo una asunción no verificable.
- **2025-10-26** es anómalo también aquí (`H24` inválido en todas las filas; en el aire eran `H02` y `H24`): el día se
  excluye de features y targets.
- Los sensores `81-89` que aparecían en los TXT del aire de 2019 (AT-010) son **la misma red**: las estaciones 102-115 del
  anexo I. En julio-agosto de 2019 el 99,9 % de los valores y el 99,87 % de los códigos de esas filas coinciden con este
  dataset (el resto son diferencias de revalidación). Este dataset trae además los sensores de 13 estaciones de aire (004,
  008, 016, 018, 024, 035, 036, 038, 039, 054, 056, 058, 059) que el aire no publica.

## Coordenadas oficiales

`Datos meteorológicos. Estaciones de control` (CSV, versión mayo 2024, última actualización 03/05/2023): 26 ubicaciones con
`LONGITUD`/`LATITUD` en grados decimales, altitud y los sensores que tiene cada una. Sale como
`data/processed/air/meteo/stations.geojson` (`observed_point`, 26 estaciones, todas con datos). Las 13 estaciones que
comparten código con una estación de aire están en el mismo poste (distancia 0 con las coordenadas del Geoportal), salvo
**28079059** (Juan Carlos I), a ≈ 0,8 km por la discrepancia ya documentada en AT-010 entre el Geoportal y el CSV de
datos.madrid.es. Diferencias entre sensores declarados y datos: la estación 104 (La China) declara solo viento, pero trae
5 magnitudes más durante ≈ 3 % del periodo (solo 2019); el viento es el único dato usable.

## Asociación espacial

Las estaciones meteorológicas **no están co-localizadas** con las de aire (13 de 24 estaciones de aire tienen un sensor en
el mismo poste para alguna magnitud; las demás no). Regla (`atlas.domains.air.association`):

1. Candidatas: estaciones meteorológicas que **miden la variable en los datos** (≥ 1 valor válido) a **≤ 5.000 m** (distancia
   del círculo máximo entre coordenadas oficiales).
2. Se ordenan por distancia y se conservan 3 como máximo. La primera es la **principal**; las otras son **suplentes** que
   se usan hora a hora solo cuando la mejor clasificada no tiene valor válido en esa hora (`meteo_fallback_n` cuenta cuántas
   de las 4 variables salieron de un suplente).
3. Sin candidata, la feature es `null`. No se interpola, no se promedia entre estaciones y no se usa nunca una estación a
   más de 5 km, aunque no haya alternativa.
4. La tabla (estación de aire, variable, rango, estación meteorológica, distancia, `same_station_code`, horas válidas) viaja
   con las features: `association.parquet` y `association.json`.

Resumen (principal por variable; 24 estaciones de aire): temperatura 24 con candidata, mediana 0,13 km, máx. 3,5 km, 13 en el
mismo poste; humedad 24, mediana 0,77 km, máx. 3,5 km, 11 en el mismo poste; viento 23, mediana 2,71 km, máx. 4,61 km, 4 en
el mismo poste; presión 23, mediana 2,78 km, máx. 4,61 km, 3 en el mismo poste. **28079058 (El Pardo)** no tiene viento ni
presión a ≤ 5 km (el sensor más cercano está a 6,7 km): su viento es siempre `null` y nunca entra en filas completas.
El viento es el menos representativo: se mide en solo 10 puntos y, de las 23 estaciones de aire con candidata, 4 lo tienen en su
poste y las otras 19 a 0,3-4,6 km.

## Lagunas de los datos (hechos, no hipótesis)

- Los sensores 102-115 (J.M.D. y similares) **no tienen ninguna fila entre septiembre y diciembre de 2022** en los ficheros
  mensuales; por eso 2022 es el año más pobre en filas completas para las estaciones de aire que dependen de ellos.
- El sensor de temperatura de 28079016 y 28079039 no existe antes de 2022 (el CSV de estaciones no da la fecha de alta);
  28079004 tiene ≈ 74 % de cobertura de temperatura en 2020-2022, igual que su NO₂.
- Valores con código `V` físicamente imposibles (temperatura −55 °C, humedad −25 % o 1030 %, viento 263 m/s, presión de 1 a
  875 mb): se conservan en las observaciones canónicas y se **anulan al construir las features** (rangos en
  `atlas.domains.air.meteo.PLAUSIBLE_RANGE`), y el informe de calidad los cuenta.
