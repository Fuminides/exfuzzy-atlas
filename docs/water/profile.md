# Perfil de datos: calidad del agua de ríos, Northumberland & Tyne (`uk-water-quality`)

Generado por `python -m atlas.domains.water.profile` (AT-020). No editar a mano: se regenera con cada ingesta.
Es un perfil **descriptivo** para AT-021; no elige el target ni valida ningún modelo.

## 1. Resumen

- Versión de datos: `uk-wq-ne-x-h-rivers-2015-2025-20261030`; descarga: 2026-10-30T18:47:16+00:00.
- Rebanada: Environment Agency North East region, area X (Northumberland, Durham and Tees), sub-area H (Northumberland & Tyne); sampling point type F6 (freshwater rivers). Años 2015-2025; determinandos: 9924 (dissolved_oxygen, «Oxygen, Dissolved as O2»), 0111 (ammoniacal_nitrogen, «Ammoniacal Nitrogen as N»), 0180 (orthophosphate_reactive, «Orthophosphate, reactive as P»), 0061 (ph, «pH»), 0076 (water_temperature, «Temperature of Water»).
- Filas canónicas (muestra x determinando): 93,930; muestras: 24,190; puntos de muestreo con datos: 557.
- Rango (hora local): 2015-01-05 08:15:00 a 2025-12-22 10:46:00.
- Geometría: 772 puntos en el listado de la API, 557 con datos en la rebanada; coordenadas de relleno (geometría nula, ver `api_notes.md`): NE-42100407.
- Conciliación con la API: suma de `X-Total-Items` por año = 93,930 = filas CSV = filas canónicas; pares (muestra, determinando) distintos = filas (93,930); duplicados en la clave del contrato: 0.

Por qué estos determinandos (`9924` oxígeno disuelto, `0111` nitrógeno amoniacal, `0180` ortofosfato reactivo, y desde AT-021 `0061` pH y `0076` temperatura del agua, por su relación física con el oxígeno): son determinandos habituales del seguimiento fisicoquímico de ríos (oxígeno, amoniaco, fósforo reactivo), con cobertura alta en toda la década (19,309 / 14,065 / 19,334 / 18,980 / 22,242 observaciones para ammoniacal_nitrogen / dissolved_oxygen / orthophosphate_reactive / ph / water_temperature), una unidad por determinando (mg/l, °C, pH), y comportamiento muy distinto frente al límite de detección (ammoniacal_nitrogen 55.7 % censurado; dissolved_oxygen 0.0 % censurado; orthophosphate_reactive 27.4 % censurado; ph 0.0 % censurado; water_temperature 0.0 % censurado), lo que permite estudiar el tratamiento de la censura. Otras alternativas con cobertura similar quedan descritas en la sección 8 (nitrato, OD en % de saturación).

## 2. Muestras por punto y año

| año (local) | puntos activos | muestras | mediana muestras/punto | media | p90 | % puntos con >= 12 | % con >= 26 | máx. |
|---|---|---|---|---|---|---|---|---|
| 2015 | 235 | 2,208 | 4.0 | 9.4 | 12.0 | 34.9 | 4.7 | 97 |
| 2016 | 246 | 2,245 | 7.0 | 9.1 | 13.0 | 23.2 | 4.1 | 91 |
| 2017 | 281 | 2,459 | 5.0 | 8.8 | 15.0 | 29.2 | 3.9 | 54 |
| 2018 | 278 | 2,514 | 7.0 | 9.0 | 15.0 | 27.0 | 5.0 | 48 |
| 2019 | 325 | 2,866 | 9.0 | 8.8 | 13.0 | 19.1 | 3.4 | 42 |
| 2020 | 237 | 895 | 3.0 | 3.8 | 6.4 | 1.7 | 0.0 | 16 |
| 2021 | 152 | 1,815 | 10.0 | 11.9 | 22.9 | 45.4 | 5.9 | 53 |
| 2022 | 127 | 1,880 | 12.0 | 14.8 | 44.4 | 55.1 | 11.0 | 52 |
| 2023 | 170 | 2,358 | 12.0 | 13.9 | 22.1 | 61.8 | 8.2 | 46 |
| 2024 | 192 | 2,248 | 8.0 | 11.7 | 21.9 | 34.4 | 7.3 | 52 |
| 2025 | 217 | 2,702 | 12.0 | 12.5 | 16.4 | 63.6 | 6.5 | 52 |

(Una «muestra» es una `sample` de la API: un punto y un instante; varias observaciones cuelgan de ella.) El año 2020 tiene muchas menos muestras que sus vecinos (coincide con la pandemia; la causa no se ha investigado). El número de puntos activos por año cambia mucho (de 84 a 310): la red de muestreo no es constante.

Años con datos por punto:

| años con datos | puntos | mediana de muestras por punto | muestras |
|---|---|---|---|
| 1 | 133 | 12.0 | 1,277 |
| 2 | 95 | 12.0 | 1,291 |
| 3 | 56 | 18.5 | 1,102 |
| 4 | 25 | 27.0 | 608 |
| 5 | 47 | 35.0 | 1,568 |
| 6 | 65 | 30.0 | 2,573 |
| 7 | 29 | 45.0 | 1,736 |
| 8 | 26 | 55.5 | 1,591 |
| 9 | 20 | 74.0 | 1,590 |
| 10 | 18 | 93.5 | 1,925 |
| 11 | 43 | 143.0 | 8,929 |

## 3. Intervalos entre muestras (irregulares)

Huecos entre muestras consecutivas del mismo punto (23,633 intervalos), en días:

| p10 | p25 | mediana | p75 | p90 | p99 | < 1 día | 25-35 d | 13-15 d | > 60 d | > 180 d |
|---|---|---|---|---|---|---|---|---|---|---|
| 5.99 | 9.06 | 25.05 | 34.99 | 63.03 | 391.1 | 1.4 % | 25.6 % | 4.7 % | 10.7 % | 1.6 % |

Por punto con >= 20 intervalos (295 puntos): mediana de las medianas = 30.0 días; coeficiente de variación mediano del hueco = 1.36; 179 puntos con mediana 25-35 d (mensual), 6 con 13-15 d (quincenal), 19 más frecuentes y 70 más espaciados. Días-punto con más de una muestra: 177 de 23,931.

El muestreo es de campaña (rutina mensual en una parte de los puntos, con huecos y cambios de programa). **No hay serie horaria ni diaria**; cualquier problema temporal sería de «siguiente muestra del mismo punto», con huecos de semanas.

## 4. Co-ocurrencia de determinandos en la misma muestra

| OD + amoniaco + ortofosfato | muestras | % |
|---|---|---|
| DO+NH4+PO4 | 13059 | 54.0 |
| -+NH4+PO4 | 6235 | 25.8 |
| -+-+- | 3847 | 15.9 |
| DO+-+- | 994 | 4.1 |
| -+-+PO4 | 39 | 0.2 |
| DO+NH4+- | 11 | 0.0 |
| -+NH4+- | 4 | 0.0 |
| DO+-+PO4 | 1 | 0.0 |

Las tres a la vez: 13,059 muestras (54.0 %). Por año:

| año | muestras | % con las 3 | % con OD | % con amoniaco | % con ortofosfato |
|---|---|---|---|---|---|
| 2015 | 2208 | 56.3 | 56.3 | 91.9 | 91.9 |
| 2016 | 2245 | 48.2 | 50.0 | 86.2 | 86.1 |
| 2017 | 2459 | 42.1 | 54.2 | 76.6 | 76.5 |
| 2018 | 2514 | 35.7 | 50.5 | 68.3 | 68.3 |
| 2019 | 2866 | 64.9 | 70.7 | 80.9 | 81.8 |
| 2020 | 895 | 70.8 | 73.7 | 84.5 | 85.4 |
| 2021 | 1815 | 68.5 | 69.5 | 85.6 | 85.6 |
| 2022 | 1880 | 47.6 | 48.9 | 78.6 | 78.5 |
| 2023 | 2358 | 38.3 | 38.7 | 60.0 | 60.1 |
| 2024 | 2248 | 56.9 | 58.1 | 82.8 | 82.6 |
| 2025 | 2702 | 73.5 | 74.4 | 87.4 | 87.4 |

Por propósito de muestreo:

| propósito | muestras | % con las 3 | % con OD |
|---|---|---|---|
| ENVIRONMENTAL MONITORING STATUTORY (EU DIRECTIVES) | 7975 | 80.2 | 80.8 |
| MONITORING  (NATIONAL AGENCY POLICY) | 5896 | 72.4 | 73.2 |
| MONITORING  (UK GOVT POLICY - NOT GQA OR RE) | 5876 | 19.1 | 19.3 |
| PLANNED INVESTIGATION (LOCAL MONITORING) | 2552 | 28.3 | 29.7 |
| STATUTORY FAILURES (FOLLOW UPS AT NON-DESIGNATED POINTS) | 1220 | 8.0 | 77.5 |
| PLANNED INVESTIGATION (NATIONAL AGENCY POLICY) | 298 | 85.9 | 91.3 |
| STATUTORY FAILURES (FOLLOW UPS AT DESIGNATED POINTS) | 196 | 99.0 | 99.5 |
| UNPLANNED REACTIVE MONITORING (POLLUTION INCIDENTS) | 168 | 0.6 | 0.6 |
| UNPLANNED REACTIVE MONITORING FORMAL (POLLUTION INCIDENTS) | 9 | 0.0 | 0.0 |

## 5. Censura (límite de detección)

`<x` se guarda con `value = x` y `censoring = left`; `>x` con `censoring = right`. `x` es el límite publicado, no una estimación del valor real.

| determinando | filas | censuradas «<» | censuradas «>» | % censurado |
|---|---|---|---|---|
| ammoniacal_nitrogen | 19309 | 10754 | 0 | 55.7 |
| dissolved_oxygen | 14065 | 0 | 0 | 0.0 |
| orthophosphate_reactive | 19334 | 5300 | 0 | 27.4 |
| ph | 18980 | 1 | 0 | 0.0 |
| water_temperature | 22242 | 1 | 0 | 0.0 |

Por año (% censurado):

| determinando | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ammoniacal_nitrogen | 73.5 | 59.1 | 61.5 | 62.0 | 54.5 | 53.8 | 38.3 | 43.5 | 43.2 | 54.4 | 57.7 |
| dissolved_oxygen | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| orthophosphate_reactive | 32.3 | 32.2 | 32.2 | 40.8 | 26.8 | 22.9 | 18.1 | 25.3 | 19.8 | 20.6 | 25.2 |
| ph | 0.1 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| water_temperature | 0.1 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

Límites de detección distintos publicados. Coexisten dos límites principales durante todo el periodo y la tabla por año muestra cómo cambia su peso; no se ha determinado si responde a método, laboratorio o programa. Un `<0.03` y un `<0.002` no son comparables:

| determinando | límite | filas | primer año | último año |
|---|---|---|---|---|
| ammoniacal_nitrogen | 0.03 | 10308 | 2015 | 2025 |
| ammoniacal_nitrogen | 0.002 | 445 | 2015 | 2025 |
| ammoniacal_nitrogen | 0.3 | 1 | 2022 | 2022 |
| orthophosphate_reactive | 0.01 | 5162 | 2015 | 2025 |
| orthophosphate_reactive | 0.001 | 137 | 2015 | 2025 |
| orthophosphate_reactive | 0.02 | 1 | 2021 | 2021 |
| ph | 7.9 | 1 | 2015 | 2015 |
| water_temperature | 9.7 | 1 | 2015 | 2015 |

Filas censuradas por límite y año:

| límite | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ammoniacal_nitrogen <0.002 | 3 | 5 | 8 | 10 | 39 | 19 | 51 | 59 | 32 | 52 | 167 |
| ammoniacal_nitrogen <0.03 | 1489 | 1140 | 1150 | 1055 | 1224 | 388 | 544 | 583 | 579 | 960 | 1196 |
| ammoniacal_nitrogen <0.3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| orthophosphate_reactive <0.001 | 12 | 7 | 9 | 9 | 7 | 0 | 10 | 12 | 10 | 11 | 50 |
| orthophosphate_reactive <0.01 | 644 | 615 | 597 | 692 | 622 | 175 | 270 | 361 | 270 | 371 | 545 |
| orthophosphate_reactive <0.02 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| ph <7.9 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| water_temperature <9.7 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Puntos con más de un límite de detección distinto (determinando, puntos con censura, de ellos con >1 límite): ammoniacal_nitrogen: 394, 45; orthophosphate_reactive: 292, 25; ph: 1, 0; water_temperature: 1, 0.

## 6. Unidades, banderas, materiales y propósitos

| determinando | unidad (símbolo) | unidad (etiqueta API) | filas |
|---|---|---|---|
| ammoniacal_nitrogen | mg/l | MILLIGRAM PER LITRE | 19309 |
| dissolved_oxygen | mg/l | MILLIGRAM PER LITRE | 14065 |
| orthophosphate_reactive | mg/l | MILLIGRAM PER LITRE | 19334 |
| ph | PHUNITS | PH UNITS | 18980 |
| water_temperature | CEL | CELSIUS | 22242 |

Valores (sin censurados) por determinando:

| determinando | unidad | n | mín. | p1 | mediana | p99 | máx. |
|---|---|---|---|---|---|---|---|
| ammoniacal_nitrogen | mg/l | 8555 | 0.002 | 0.0023 | 0.036 | 1.674 | 263.0 |
| dissolved_oxygen | mg/l | 14065 | 0.336 | 6.3264 | 11.4 | 14.5 | 35.35 |
| orthophosphate_reactive | mg/l | 14034 | 0.001 | 0.0016 | 0.023 | 0.757 | 5.17 |
| ph | PHUNITS | 18979 | 2.72 | 6.03 | 8.0 | 8.76 | 10.27 |
| water_temperature | CEL | 22241 | 0.0 | 1.34 | 8.8 | 18.5 | 25.1 |

La API **no publica bandera de validez** por observación (no existe equivalente a `V`/`N` de Madrid): `validity_flag` es nulo en todas las filas. Combinaciones observadas (bandera, motivo de nulo, censura):

| validity_flag | missing_reason | censoring | filas |
|---|---|---|---|
| (null) | (value present) | (none) | 77874 |
| (null) | (value present) | left | 16056 |

Material de muestra (los puntos son de tipo F6 río, pero hay muestras de otro material; se conservan y se identifican con `sample_material`):

| material | filas | muestras |
|---|---|---|
| RIVER / RUNNING SURFACE WATER | 93753 | 24120 |
| ANY WATER | 89 | 41 |
| MINEWATER | 42 | 15 |
| FINAL SEWAGE EFFLUENT | 26 | 6 |
| SEA WATER | 19 | 7 |
| POND / LAKE / RESERVOIR WATER | 1 | 1 |

Propósito de muestreo:

| propósito | filas | muestras |
|---|---|---|
| ENVIRONMENTAL MONITORING STATUTORY (EU DIRECTIVES) | 34097 | 7975 |
| MONITORING  (NATIONAL AGENCY POLICY) | 24159 | 5896 |
| MONITORING  (UK GOVT POLICY - NOT GQA OR RE) | 19399 | 5876 |
| PLANNED INVESTIGATION (LOCAL MONITORING) | 9768 | 2552 |
| STATUTORY FAILURES (FOLLOW UPS AT NON-DESIGNATED POINTS) | 3553 | 1220 |
| PLANNED INVESTIGATION (NATIONAL AGENCY POLICY) | 1391 | 298 |
| STATUTORY FAILURES (FOLLOW UPS AT DESIGNATED POINTS) | 977 | 196 |
| UNPLANNED REACTIVE MONITORING (POLLUTION INCIDENTS) | 553 | 168 |
| UNPLANNED REACTIVE MONITORING FORMAL (POLLUTION INCIDENTS) | 33 | 9 |

## 7. Hora local y horario de verano

La API entrega `phenomenonTime` sin desfase (p. ej. `2015-02-03T10:28:00`). Se lee como **hora de reloj de Europe/London**, no UTC. Evidencia: si fuera UTC, el muestreo diurno de verano aparecería ~1 h antes que el de invierno; no es así.

| estación | muestras | hora media | mediana | p10 | p90 |
|---|---|---|---|---|---|
| Jun-Aug | 5989 | 10.46 | 10.28 | 8.17 | 12.97 |
| Dec-Feb | 6062 | 10.52 | 10.33 | 8.35 | 12.95 |

Muestras con hora exactamente 00:00:00 (posible «sin hora»): 0 de 24,190; horas distintas: 693. Muestras en la hora 01:xx de un domingo de cambio de hora (primavera / otoño): 0 / 0; filas con hora inexistente: 0; con hora ambigua: 0. La política implementada (hora ambigua = primera ocurrencia, BST; hora inexistente = con el desfase previo, GMT) está probada con datos sintéticos porque esta rebanada no contiene ninguna muestra en esas horas.

## 8. Cobertura de otros determinandos en la rebanada (candidatos: conteos `X-Total-Items` sin descargar los datos)

| determinando | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0061 pH | 1,583 | 1,680 | 1,967 | 2,068 | 2,533 | 784 | 1,485 | 1,265 | 1,693 | 1,597 | 2,325 | 18,980 |
| 0076 Temperature of Water | 1,993 | 1,940 | 2,146 | 2,186 | 2,654 | 847 | 1,811 | 1,876 | 1,865 | 2,234 | 2,690 | 22,242 |
| 0111 Ammoniacal Nitrogen as N | 2,029 | 1,936 | 1,884 | 1,718 | 2,318 | 756 | 1,553 | 1,477 | 1,415 | 1,861 | 2,362 | 19,309 |
| 0180 Orthophosphate, reactive as P | 2,029 | 1,933 | 1,882 | 1,718 | 2,345 | 764 | 1,553 | 1,475 | 1,416 | 1,857 | 2,362 | 19,334 |
| 9924 Oxygen, Dissolved as O2 | 1,243 | 1,122 | 1,334 | 1,270 | 2,027 | 660 | 1,262 | 919 | 912 | 1,307 | 2,009 | 14,065 |
| 0117 Nitrate as N | 1,965 | 1,740 | 1,575 | 1,348 | 2,162 | 729 | 1,553 | 1,467 | 1,416 | 1,859 | 2,351 | 18,165 |
| 9901 Oxygen, Dissolved, % Saturation | 1,258 | 1,148 | 1,388 | 1,406 | 2,126 | 754 | 1,504 | 1,280 | 1,198 | 1,580 | 2,322 | 15,964 |

## 9. Estructura descriptiva (no es validación de ningún modelo)

- Sobre 13,059 muestras con las tres: correlación de rangos (Pearson sobre rangos) OD-amoniaco = -0.18, OD-ortofosfato = -0.23, amoniaco-ortofosfato = 0.6 (los censurados empatan en el límite).
- Fracción de la varianza del OD explicada solo por la media de cada punto (253 puntos con >= 20 muestras de OD, 12,236 muestras): 0.22.
- Pares de muestras consecutivas de OD en el mismo punto con 20-45 días de hueco (8,005): correlación = 0.72; |diferencia| mediana = 0.8 mg/l (media 0.98); desviación típica global del OD = 1.77 mg/l.

## 10. Problemas candidatos (preliminar; el target lo decide AT-021)

1. **Clasificar la condición de una muestra a partir de determinandos co-medidos** (p. ej. banda de oxígeno disuelto o de ortofosfato a partir de los otros dos + estación + atributos del punto). Lo que respalda el dato: 13,059 muestras con las tres (54.0 %), 557 puntos, 11 años, unidad única; pocas variables, lo que favorece reglas legibles. Lo que no: son pocas entradas (dos determinandos y calendario), el OD falta en el ~31 % de las muestras (sobre todo las de seguimiento «UK GOVT POLICY» y las investigaciones locales, ver sección 4), las muestras del mismo punto están muy correlacionadas (hay que partir por punto o por tiempo, no al azar), y cualquier «banda» sería una convención descriptiva, no una clasificación regulatoria (los estándares de la Directiva Marco del Agua dependen del tipo de masa de agua).
2. **Inferir un determinando a partir de los demás en la misma muestra** (regresión de ortofosfato o amoniaco, con la censura tratada explícitamente). Soporta: misma estructura de muestra. No soporta bien: amoniaco está censurado en un 55.7 % de las filas y coexisten límites de detección distintos (0.03 y 0.002), así que un target numérico tendría una masa grande en un límite que no es homogéneo; habría que modelar solo la parte detectada o definir una clase «por encima de un umbral común».
3. **Valor/categoría en la siguiente muestra del mismo punto** (horizonte = la siguiente campaña, no una hora). Soporta: puntos con ~mensual regularidad (179 puntos con mediana 25-35 d de 295 con >= 20 intervalos). Limita: la mediana de muestras por punto y año es baja (sección 2) y el coeficiente de variación del hueco es alto. No soporta: horizontes horarios o diarios, ni series regulares; hay que fijar la relación entre `issued_at` (última muestra conocida) y `valid_at` (la siguiente, a un hueco variable) y comparar con persistencia del último valor y climatología por punto y mes. Descriptivamente, el OD de muestras consecutivas ya está correlacionado (r = 0.72), lo que deja poco margen sobre la persistencia.

Descartado desde ya: cualquier promesa de predicción horaria, alertas en tiempo real o interpolación entre puntos (ver `AGENTS.md`, invariante 7).

