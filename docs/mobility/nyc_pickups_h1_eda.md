# EDA y recomendación de split: demanda de taxi amarillo a 1 hora (`nyc_pickups_h1`, AT-031)

Generado por `python -m atlas.domains.mobility.features --eda` sobre la tabla de `nyc-tlc-yellow-2024-04_2025-03-v1`. No se edita a mano. Definición de la tabla y de las features en [`nyc_pickups_h1_feature_card.md`](nyc_pickups_h1_feature_card.md). **Las estadísticas que condicionan decisiones de modelado se calculan solo con el periodo de entrenamiento** (emisión en `[2024-04-01T04:00:00Z, 2025-01-01T05:00:00Z)`, filas con target conocido, zonas seleccionadas); la excepción es la tabla mensual, que cubre todo el año porque es lo que justifica el split y es solo descriptiva. No se ha entrenado ningún modelo: las cifras «in-sample» de abajo son descriptivas de los datos de train, no una evaluación.

## 1. Tabla

- Filas: 963,600 = 110 zonas × 8,760 horas de emisión (comprobado: 963,600). Completas (target y las 7 features conocidos): **942,040** (97.76%); incompletas: 21,560, de ellas 18,480 en las primeras 168 h del periodo (el lag semanal cae antes de la cobertura) y 3,080 por la hora ambigua del cambio de hora de otoño (2024-11-03).
- Nulos por columna: `target`=220, `pickups_lag1`=330, `pickups_lag2`=440, `pickups_lag24`=2,860, `pickups_lag168`=18,700, `pickups_mean24h`=5,390, `local_hour`=0, `local_dow`=0.
- Zonas: 263 con polígono en la serie; 110 entran en la tarea; 153 quedan como «sin modelo» (lista y motivos en `nyc_pickups_h1_zone_selection.json`).

## 2. Distribución del target (train, zonas seleccionadas)

| filas | % ceros | media | varianza/media | mediana | p75 | p90 | p99 | p99,9 | máx | asimetría | asimetría de log1p |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 725,890 | 16.5% | 42.9 | 146.4 | 5 | 48 | 145 | 376 | 563 | 847 | 2.88 | 0.40 |

- Entre las zonas seleccionadas el 16.5% de las zona-horas es 0 (en las 263 zonas de la serie es el 51 %). Entre los valores positivos la mediana es 10 y el p90 163.
- Cola pesada: el 1 % de filas con más recogidas aporta el 10.7% del volumen; 111,146 filas (15.3%) tienen ≥ 100 recogidas. La varianza es 146.4 veces la media (un conteo de Poisson daría 1): sobredispersión fuerte, en parte porque se mezclan zonas de escala muy distinta.

## 3. Volumen por zona (train)

Filtro de zonas: media de recogidas por hora conocida en train ≥ 1 (se fija solo con train). Las 110 zonas seleccionadas reúnen el 99.06% de las recogidas de train de las 263 zonas.

| umbral (recogidas/h) | zonas | % de las recogidas de train |
|---|---|---|
| 0.25 | 192 | 99.88% |
| 0.5 | 144 | 99.54% |
| 1 | 110 | 99.06% |
| 2 | 83 | 98.25% |
| 5 | 59 | 96.69% |

Coste del filtro, en recogidas de las 263 zonas que quedan dentro de las zonas seleccionadas (descriptivo; el filtro no se ha ajustado con esto): train 99.06%, validation 98.71%, test 97.91%.

Concentración dentro de las seleccionadas (porcentaje acumulado del volumen): top 1: 5.0%, top 5: 22.1%, top 10: 38.2%, top 25: 72.2%, top 50: 95.9%, top 110: 100.0%. Recogidas medias por hora entre zonas seleccionadas: mín 1.02, p25 2.1, mediana 7.7, p75 71.8, máx 236: **la escala varía más de dos órdenes de magnitud entre zonas**.

| zona | nombre | recogidas (train) | media/h | % horas con 0 |
|---|---|---|---|---|
| 132 | JFK Airport | 1,558,105 | 236.1 | 0.1% |
| 237 | Upper East Side South | 1,475,265 | 223.6 | 0.4% |
| 161 | Midtown Center | 1,459,674 | 221.2 | 0.0% |
| 236 | Upper East Side North | 1,312,512 | 198.9 | 1.2% |
| 162 | Midtown East | 1,081,554 | 163.9 | 0.0% |
| 230 | Times Sq/Theatre District | 1,058,455 | 160.4 | 0.1% |
| 186 | Penn Station/Madison Sq West | 1,041,545 | 157.8 | 0.0% |
| 138 | LaGuardia Airport | 1,010,041 | 153.1 | 6.8% |
| 142 | Lincoln Square East | 997,623 | 151.2 | 0.4% |
| 170 | Murray Hill | 903,237 | 136.9 | 0.1% |

Excluidas por barrio (con polígono): Bronx: 41 de 43; Brooklyn: 33 de 61; EWR: 1 de 1; Manhattan: 9 de 69; Queens: 49 de 69; Staten Island: 20 de 20. Zonas sin ninguna recogida en train: ['103', '104']. Las excluidas con más demanda, justo bajo el umbral: 189 (Prospect Heights, 0.98/h), 40 (Carroll Gardens, 0.97/h), 157 (Maspeth, 0.94/h), 219 (Springfield Gardens South, 0.85/h), 14 (Bay Ridge, 0.83/h).

## 4. Patrón horario y semanal (train, media del target por zona-hora seleccionada)

| hora local | laborable (lun-vie) | fin de semana (sáb-dom) |
|---|---|---|
| 00 | 20.3 | 54.8 |
| 01 | 9.7 | 43.3 |
| 02 | 5.1 | 31.2 |
| 03 | 3.4 | 20.0 |
| 04 | 3.6 | 11.5 |
| 05 | 6.7 | 5.4 |
| 06 | 16.6 | 8.7 |
| 07 | 33.7 | 12.8 |
| 08 | 45.8 | 19.9 |
| 09 | 46.8 | 31.0 |
| 10 | 47.3 | 41.5 |
| 11 | 50.1 | 49.0 |
| 12 | 54.0 | 55.6 |
| 13 | 56.2 | 58.3 |
| 14 | 61.7 | 59.4 |
| 15 | 64.3 | 60.1 |
| 16 | 65.1 | 62.8 |
| 17 | 73.2 | 64.5 |
| 18 | 78.1 | 64.7 |
| 19 | 67.1 | 59.9 |
| 20 | 62.2 | 51.7 |
| 21 | 65.0 | 50.0 |
| 22 | 59.4 | 49.2 |
| 23 | 43.7 | 44.5 |

| día | lun | mar | mié | jue | vie | sáb | dom |
|---|---|---|---|---|---|---|---|
| media por zona-hora | 37.1 | 43.0 | 45.0 | 46.8 | 44.7 | 45.4 | 38.7 |

Pico vespertino los laborables (17-19 h) y de madrugada los fines de semana (00-02 h, sobre todo la noche del viernes y del sábado): la hora local y el día de la semana **interactúan**, por eso la feature de hora se acompaña del día. Con la hora codificada 0-23 sin más, la madrugada del sábado y del domingo (00-03 h) queda en el extremo bajo de la escala aunque sea demanda alta; ver la tarjeta de features.

### Correlación del target con cada feature de historial (train, filas completas)

| feature | Pearson agrupada | Pearson agrupada de log1p | mediana por zona | mín por zona | máx por zona |
|---|---|---|---|---|---|
| `pickups_lag1` | 0.953 | 0.936 | 0.746 | 0.186 | 0.937 |
| `pickups_lag2` | 0.883 | 0.890 | 0.558 | 0.097 | 0.829 |
| `pickups_lag24` | 0.923 | 0.925 | 0.554 | 0.143 | 0.911 |
| `pickups_lag168` | 0.947 | 0.940 | 0.694 | 0.045 | 0.917 |
| `pickups_mean24h` | 0.756 | 0.847 | 0.249 | 0.059 | 0.520 |

## 5. Varianza explicada «in-sample» por referencias sencillas (train; no es una evaluación)

Fracción de la varianza total del target en train que explica la media de cada celda calculada sobre esas mismas filas (descriptivo: dice cuánta estructura hay que una climatología por zona ya captura y cuánta escala aporta la identidad de la zona; un modelo real se evalúa fuera de muestra con A4).

| referencia | R² in-sample (target) | R² in-sample (log1p del target) |
|---|---|---|
| zone mean | 0.537 | 0.710 |
| zone x local hour | 0.853 | 0.900 |
| zone x hour of week | 0.928 | 0.935 |

## 6. Evolución mensual (todo el año; solo descriptivo)

| mes (UTC de emisión) | filas con target | media por zona-hora | % ceros |
|---|---|---|---|
| 2024-04 | 78,760 | 43.7 | 18.6% |
| 2024-05 | 81,840 | 44.9 | 16.5% |
| 2024-06 | 79,200 | 44.2 | 16.3% |
| 2024-07 | 81,840 | 37.0 | 19.1% |
| 2024-08 | 81,840 | 36.0 | 18.3% |
| 2024-09 | 79,200 | 45.2 | 14.1% |
| 2024-10 | 81,840 | 46.1 | 15.6% |
| 2024-11 | 78,980 | 45.4 | 14.4% |
| 2024-12 | 81,840 | 44.2 | 15.9% |
| 2025-01 | 81,840 | 41.6 | 16.0% |
| 2025-02 | 73,920 | 47.3 | 9.4% |
| 2025-03 | 81,840 | 49.4 | 6.6% |
| 2025-04 | 440 | 54.5 | 1.6% |

Misma evolución por grupo de volumen (el grupo se fija con la media de **train** de cada zona; media del target por zona-hora y, entre paréntesis, % de ceros):

| grupo (media de train) | 2024-04 | 2024-05 | 2024-06 | 2024-07 | 2024-08 | 2024-09 | 2024-10 | 2024-11 | 2024-12 | 2025-01 | 2025-02 | 2025-03 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1) < 3/h | 1.5 (41%) | 1.7 (36%) | 1.8 (36%) | 1.5 (42%) | 1.6 (40%) | 2.3 (31%) | 1.9 (34%) | 2.1 (31%) | 1.8 (35%) | 2.1 (33%) | 3.4 (19%) | 4.5 (13%) |
| 2) 3-10/h | 5.3 (15%) | 5.4 (13%) | 5.4 (13%) | 4.1 (17%) | 4.3 (16%) | 6.2 (11%) | 5.5 (13%) | 5.7 (12%) | 5.1 (13%) | 5.6 (16%) | 8.8 (8%) | 10.4 (6%) |
| 3) 10-50/h | 26.0 (6%) | 26.6 (5%) | 26.8 (5%) | 21.7 (6%) | 21.6 (5%) | 28.3 (5%) | 27.1 (5%) | 25.6 (5%) | 24.6 (5%) | 23.0 (6%) | 28.4 (5%) | 30.5 (4%) |
| 4) >= 50/h | 114.8 (1%) | 117.8 (1%) | 115.5 (1%) | 97.1 (1%) | 93.9 (1%) | 116.9 (1%) | 121.0 (1%) | 119.0 (1%) | 116.6 (1%) | 109.1 (1%) | 120.6 (1%) | 124.3 (1%) |

Las zonas de poco volumen no están estables: en febrero y marzo de 2025 sus medias se multiplican por 2-3 respecto a train mientras las de 10-50/h suben alrededor de un 25 % y las de ≥ 50/h un 5-10 %. Consulta ad hoc sobre los ficheros crudos (no forma parte del pipeline): en las 57 zonas seleccionadas con < 10 recogidas/h, los viajes del `VendorID` 2 pasan de ~81 k en diciembre a 94 k, 147 k y 206 k en enero, febrero y marzo de 2025, y los del `VendorID` 7 (Helix, ya señalado en la tarjeta de datos por los viajes de duración cero) de 0 en diciembre a 223 en marzo, mientras el `VendorID` 1 cambia poco. La causa (cambio de proveedor o de cobertura de reporte, más uso de e-hail en barrios exteriores…) **no está verificada**; lo que sí se ve es que el nivel de esas zonas en test no se parece al de train.

## 7. Split cronológico recomendado para A4

Por tiempo de emisión (semiabierto `[desde, hasta)`, UTC), con `embargo_hours = 168` (el lag semanal es lo más antiguo que mira una feature; el target y los lags de las filas del periodo siguiente caen así fuera del periodo anterior). Coincide con `SplitSpec` (`validation_from = train_to + embargo`, `test_from = validation_to + embargo`).

| periodo | emisión desde (UTC) | emisión hasta (UTC) | fechas locales | filas | filas completas |
|---|---|---|---|---|---|
| train | 2024-04-01T04:00:00Z | 2025-01-01T05:00:00Z | 2024-04-01 a 2024-12-31 | 726,110 | 704,550 |
| (embargo 168 h) | 2025-01-01T05:00:00Z | 2025-01-08T05:00:00Z | 2025-01-01 a 2025-01-07 | - | - |
| validación | 2025-01-08T05:00:00Z | 2025-02-01T05:00:00Z | 2025-01-08 a 2025-01-31 | 63,360 | 63,360 |
| (embargo 168 h) | 2025-02-01T05:00:00Z | 2025-02-08T05:00:00Z | 2025-02-01 a 2025-02-07 | - | - |
| test | 2025-02-08T05:00:00Z | 2025-04-01T04:00:00Z | 2025-02-08 a 2025-03-31 | 137,170 | 137,170 |

Justificación y límites:

- Train son 9 meses (abril a diciembre, 275 días); las 18,480 filas incompletas del arranque (primeras 168 h, lag semanal) y las 3,080 de la hora ambigua quedan fuera de las filas completas, de modo que entrenan 704,550 de 726,110. Validación y test no tienen filas incompletas (63,360 y 137,170).
- **Estacionalidad**: train no incluye ningún invierno y validación/test son enero-marzo. Un modelo que lea el mes (no lo hace: las features son historial y reloj) o que aprenda niveles de verano verá un cambio de nivel. Los lags recientes absorben parte; comparar con una persistencia y con una climatología hora × día de la semana ajustada en train.
- **Peaje de congestión**: la tarifa de entrada a la zona de congestión de Manhattan (`cbd_congestion_fee`) empieza el 2025-01-05, dentro del periodo de validación y antes de todo el test. El test es posterior al cambio de régimen y el train, anterior: es un cambio estructural real, no solo estacional, que afecta sobre todo a Manhattan por debajo de la calle 60. Conviene medir por zona y no solo en agregado.
- **Un solo año**: cada festivo ocurre una vez y cae en un solo periodo. Las features de calendario no codifican festivos (ver tarjeta); Thanksgiving, Navidad y Año Nuevo quedan en train y MLK Day y Presidents' Day en validación y test.
- Las 526 filas ambiguas de la serie (2 h × 263 zonas, 2024-11-03) están en train; `target` nulo y features que las usan, nulas hasta 168 h después. A4 debe entrenar y evaluar solo con filas completas y contar cuántas se descartan.

## 8. ¿Transformación del target o baseline por zona?

- **Transformación**: la asimetría del target es 2.88 y la de `log1p(target)` 0.40; con un 51 % de ceros en el conjunto total de zonas (tarjeta de datos) (y 16.5% en las seleccionadas) `log1p` es la transformación natural que mantiene el 0 en 0 y comprime la cola. Es recomendable **como variante a comparar**, no como sustitución: el objetivo del GA de ex_fuzzy es el R² del target tal como se le dé, así que en escala original el error lo dominan unas pocas zonas de Midtown y los aeropuertos; en `log1p` pesan todas. Hay que invertir (`expm1`) y reportar MAE/RMSE en conteos y por zona, y avisar de que la media de `expm1(E[log1p y])` subestima la media. Si se usa log1p en el target, las features de conteo (`pickups_*`) deberían transformarse igual para que las reglas hablen de la misma escala.
- **Baseline por zona**: sí, imprescindible. La identidad de la zona explica por sí sola gran parte de la varianza (§5) porque la escala difiere en más de dos órdenes de magnitud, y las features de historial son recuentos absolutos, así que un modelo común sin ninguna normalización por zona aprende sobre todo «zona grande / zona pequeña». Referencias mínimas: persistencia (`pickups_lag1`), misma hora la semana anterior (`pickups_lag168`) y media por zona × hora local × día de la semana ajustada en train. Una alternativa a explorar (no hecha aquí, porque cambiaría el significado de las features) es modelar la razón `target / media_de_zona_en_train` o entrenar con features normalizadas por la media de train de cada zona; esa media tendría que calcularse solo con train.
- **Zonas con poco volumen**: ya se excluyen las de < 1 recogida/hora; incluso las incluidas cercanas al umbral tienen muchos ceros y un ruido de conteo (Poisson) que ningún modelo puede reducir, así que el error relativo por zona crece al bajar el volumen.


## Apéndice: zonas excluidas de la tarea («sin modelo» en el mapa)

Motivo común: media de recogidas por hora conocida en train inferior al umbral (entre paréntesis, la media de cada zona; 0 = ninguna recogida en train). Siguen en `taxi_zones*.geojson` y en la serie de observaciones; no tienen filas en la tabla de features ni modelo. Los IDs 264 y 265 (`Unknown`, `Outside of NYC`) no tienen polígono y no están en la serie.

- **Bronx** (41): 3 Allerton/Pelham Gardens (0.21); 18 Bedford Park (0.34); 20 Belmont (0.23); 31 Bronx Park (0.05); 32 Bronxdale (0.23); 46 City Island (0.04); 47 Claremont/Bathgate (0.35); 51 Co-Op City (0.68); 58 Country Club (0.02); 59 Crotona Park (0.01); 60 Crotona Park East (0.27); 69 East Concourse/Concourse Village (0.82); 78 East Tremont (0.41); 81 Eastchester (0.27); 94 Fordham South (0.17); 119 Highbridge (0.48); 126 Hunts Point (0.32); 136 Kingsbridge Heights (0.27); 147 Longwood (0.27); 159 Melrose South (0.73); 167 Morrisania/Melrose (0.51); 169 Mount Hope (0.45); 174 Norwood (0.27); 182 Parkchester (0.49); 183 Pelham Bay (0.11); 184 Pelham Bay Park (0.02); 185 Pelham Parkway (0.21); 199 Rikers Island (0.00); 200 Riverdale/North Riverdale/Fieldston (0.22); 208 Schuylerville/Edgewater Park (0.28); 212 Soundview/Bruckner (0.33); 213 Soundview/Castle Hill (0.69); 220 Spuyten Duyvil/Kingsbridge (0.34); 235 University Heights/Morris Heights (0.52); 240 Van Cortlandt Park (0.04); 241 Van Cortlandt Village (0.35); 242 Van Nest/Morris Park (0.34); 248 West Farms/Bronx River (0.33); 250 Westchester Village/Unionport (0.30); 254 Williamsbridge/Olinville (0.50); 259 Woodlawn/Wakefield (0.27)
- **Brooklyn** (33): 11 Bath Beach (0.16); 14 Bay Ridge (0.83); 21 Bensonhurst East (0.27); 22 Bensonhurst West (0.40); 26 Borough Park (0.56); 29 Brighton Beach (0.36); 34 Brooklyn Navy Yard (0.36); 40 Carroll Gardens (0.97); 54 Columbia Street (0.23); 55 Coney Island (0.74); 63 Cypress Hills (0.53); 67 Dyker Heights (0.22); 77 East New York/Pennsylvania Avenue (0.59); 85 Erasmus (0.75); 106 Gowanus (0.47); 108 Gravesend (0.29); 111 Green-Wood Cemetery (0.01); 123 Homecrest (0.39); 133 Kensington (0.42); 149 Madison (0.32); 150 Manhattan Beach (0.18); 154 Marine Park/Floyd Bennett Field (0.08); 155 Marine Park/Mill Basin (0.57); 165 Midwood (0.60); 178 Ocean Parkway South (0.15); 189 Prospect Heights (0.98); 190 Prospect Park (0.19); 210 Sheepshead Bay (0.53); 217 South Williamsburg (0.36); 222 Starrett City (0.67); 227 Sunset Park East (0.28); 228 Sunset Park West (0.74); 257 Windsor Terrace (0.26)
- **EWR** (1): 1 Newark Airport (0.75)
- **Manhattan** (9): 103 Governor's Island/Ellis Island/Liberty Island (0.00); 104 Governor's Island/Ellis Island/Liberty Island (0.00); 105 Governor's Island/Ellis Island/Liberty Island (0.00); 120 Highbridge Park (0.03); 127 Inwood (0.57); 128 Inwood Hill Park (0.05); 153 Marble Hill (0.09); 194 Randalls Island (0.24); 202 Roosevelt Island (0.30)
- **Queens** (49): 2 Jamaica Bay (0.01); 8 Astoria Park (0.03); 9 Auburndale (0.10); 15 Bay Terrace/Fort Totten (0.09); 16 Bayside (0.15); 19 Bellerose (0.23); 27 Breezy Point/Fort Tilden/Riis Beach (0.03); 28 Briarwood/Jamaica Hills (0.71); 30 Broad Channel (0.01); 38 Cambria Heights (0.26); 53 College Point (0.17); 56 Corona (0.60); 57 Corona (0.04); 64 Douglaston (0.10); 73 East Flushing (0.07); 83 Elmhurst/Maspeth (0.52); 86 Far Rockaway (0.46); 92 Flushing (0.56); 96 Forest Park/Highland Park (0.04); 98 Fresh Meadows (0.15); 101 Glen Oaks (0.14); 102 Glendale (0.27); 117 Hammels/Arverne (0.46); 121 Hillcrest/Pomonok (0.36); 122 Hollis (0.17); 124 Howard Beach (0.38); 131 Jamaica Estates (0.34); 134 Kew Gardens (0.75); 135 Kew Gardens Hills (0.30); 139 Laurelton (0.27); 157 Maspeth (0.94); 160 Middle Village (0.34); 171 Murray Hill-Queens (0.16); 173 North Corona (0.27); 175 Oakland Gardens (0.12); 180 Ozone Park (0.27); 191 Queens Village (0.56); 192 Queensboro Hill (0.14); 196 Rego Park (0.57); 198 Ridgewood (0.61); 201 Rockaway Park (0.16); 203 Rosedale (0.31); 205 Saint Albans (0.65); 207 Saint Michaels Cemetery/Woodside (0.32); 218 Springfield Gardens North (0.56); 219 Springfield Gardens South (0.85); 252 Whitestone (0.16); 253 Willets Point (0.04); 258 Woodhaven (0.44)
- **Staten Island** (20): 5 Arden Heights (0.00); 6 Arrochar/Fort Wadsworth (0.08); 23 Bloomfield/Emerson Hill (0.03); 44 Charleston/Tottenville (0.00); 84 Eltingville/Annadale/Prince's Bay (0.00); 99 Freshkills Park (0.00); 109 Great Kills (0.01); 110 Great Kills Park (0.00); 115 Grymes Hill/Clifton (0.01); 118 Heartland Village/Todt Hill (0.01); 156 Mariners Harbor (0.01); 172 New Dorp/Midland Beach (0.01); 176 Oakwood (0.00); 187 Port Richmond (0.00); 204 Rossville/Woodrow (0.00); 206 Saint George/New Brighton (0.01); 214 South Beach/Dongan Hills (0.02); 221 Stapleton (0.02); 245 West Brighton (0.01); 251 Westerleigh (0.01)
