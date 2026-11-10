# Cobertura de la tabla `madrid_no2_h6_traffic`

Generado por `python -m atlas.domains.air.traffic_features` (AT-012). No editar a mano. Contexto, regla de asociación y limitaciones: [`madrid_traffic.md`](madrid_traffic.md).

Versión: `madrid-no2-h6-traffic-v1`; filas: 631,128 = 24 estaciones x 26,297 horas de emisión (UTC), mismas claves que `madrid_no2_h6` restringidas a 2023-01-01T00:00:00Z - 2025-12-31T16:00:00Z.

## Fracción de filas con cada feature no nula, por año de emisión

| año | filas | traffic_intensity_last | traffic_intensity_lag24h | traffic_n_points |
|---|---|---|---|---|
| 2023 | 210,240 | 91.4 % | 91.2 % | 100.0 % |
| 2024 | 210,816 | 91.4 % | 91.4 % | 100.0 % |
| 2025 | 210,072 | 90.8 % | 90.8 % | 100.0 % |

## Fracción de filas con `traffic_intensity_last` no nulo, por estación y año

| estación | nombre | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| 28079004 | Pza. de España | 99.9 % | 99.8 % | 99.2 % |
| 28079008 | Escuelas Aguirre | 99.9 % | 99.7 % | 99.1 % |
| 28079011 | Ramón y Cajal | 100.0 % | 99.8 % | 99.2 % |
| 28079016 | Arturo Soria | 99.9 % | 99.8 % | 99.1 % |
| 28079017 | Villaverde | 99.3 % | 99.7 % | 99.2 % |
| 28079018 | Farolillo | 99.4 % | 99.7 % | 99.2 % |
| 28079024 | Casa de Campo | 0.0 % | 0.0 % | 0.0 % |
| 28079027 | Barajas Pueblo | 99.8 % | 99.7 % | 99.0 % |
| 28079035 | Pza. del Carmen | 99.5 % | 99.3 % | 99.0 % |
| 28079036 | Moratalaz | 99.8 % | 99.8 % | 99.1 % |
| 28079038 | Cuatro Caminos | 100.0 % | 99.8 % | 99.2 % |
| 28079039 | Barrio del Pilar | 100.0 % | 100.0 % | 99.2 % |
| 28079040 | Vallecas | 99.9 % | 99.8 % | 99.1 % |
| 28079047 | Méndez Álvaro | 99.9 % | 99.8 % | 99.2 % |
| 28079048 | Castellana | 99.9 % | 99.7 % | 99.2 % |
| 28079049 | Parque del Retiro | 99.9 % | 99.7 % | 98.9 % |
| 28079050 | Plaza Castilla | 100.0 % | 99.8 % | 99.2 % |
| 28079054 | Ensanche de Vallecas | 98.9 % | 99.8 % | 98.9 % |
| 28079055 | Urb. Embajada | 99.8 % | 99.7 % | 99.0 % |
| 28079056 | Pza. Elíptica | 100.0 % | 99.9 % | 99.2 % |
| 28079057 | Sanchinarro | 99.8 % | 99.7 % | 99.0 % |
| 28079058 | El Pardo | 0.0 % | 0.0 % | 0.0 % |
| 28079059 | Juan Carlos I | 99.8 % | 99.8 % | 99.0 % |
| 28079060 | Tres Olivos | 98.8 % | 98.9 % | 99.2 % |

Estaciones sin ninguna hora con tráfico válido: 28079024, 28079058. Para ellas la feature es nula en todas las filas; no se toma tráfico de otra estación ni de la ciudad.

## Features

| feature | unidad | lag_hours | recomendada |
|---|---|---|---|
| `traffic_intensity_last` | veh/h | 1 | sí |
| `traffic_intensity_lag24h` | veh/h | 25 | sí |
| `traffic_n_points` | count | 1 | no |
| `traffic_n_associated` | count | 1 | no |
