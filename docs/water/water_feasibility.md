# Water: tarjeta de datos y viabilidad de `uk_water_do` (AT-021)

Tabla de **inferencia descriptiva del oxígeno disuelto (OD) a partir de lo que se mide en la misma muestra**. No es un pronóstico. Para A4 (entrenamiento) y A5 (mapa).
Construida con `python -m atlas.domains.water.features` (código en `src/atlas/domains/water/features.py`) a partir de las observaciones canónicas de AT-020. **No se ha entrenado ningún modelo.**
Las cifras corresponden a la versión de datos `uk-wq-ne-x-h-rivers-2015-2025-20261030` y salen de `data/processed/water/features/uk_water_do_feature_report.json`.

> **Qué dice y qué no dice una regla sobre esta tabla.** «Amoniaco ALTO ∧ verano → OD BAJO» describe una asociación en el archivo de la Environment Agency (EA): en las muestras donde el amoniaco es alto y la fecha es de verano, el OD suele ser bajo.
> No es una causa, no es una probabilidad de nada, no es una predicción de lo que pasará, no es una evaluación oficial del estado de la masa de agua y no vale entre puntos de muestreo (los puntos no son tramos de río). La fuerza de activación de una regla no es una probabilidad ni una contribución (`AGENTS.md`, invariante 7).

## 1. Target

- **`target`** = oxígeno disuelto, determinando `9924` («Oxygen, Dissolved as O2»), **mg/l**, de la muestra. Regresión. Rango observado 0,336 a 18,9; media 11,26; desviación típica 1,76.
- Una fila por **muestra de río con OD**: 14.065 muestras con OD en la rebanada (ríos F6 de Northumberland & Tyne, 2015-2025), 14.025 tras las exclusiones de §4.
- El OD nunca es entrada. Ninguna banda derivada del OD es entrada.
- **No se define una versión por bandas** (decisión de datos, no de calendario). Con umbrales de uso común en mg/l solo 75 muestras (0,53 %) están por debajo de 5 mg/l, 220 (1,6 %) por debajo de 7 y 479 (3,4 %) por debajo de 8: una clase «mala» sin masa suficiente para reglas.
  Los esquemas publicados (estándares de la Directiva Marco del Agua del Reino Unido, Directiva de Peces de Agua Dulce) se expresan por percentil y por tipo de masa de agua o de pez, y varios en % de saturación (determinando `9901`, no incluido), de modo que aplicarlos a una muestra suelta en mg/l sería otra cosa que el estándar. **No se han verificado ni citado aquí los valores concretos de esos esquemas**; si se quiere una banda, que sea una etiqueta analítica con cita y comprobación propias, nunca una clasificación de estado.
  Los recuentos por umbral están en el informe (`do_distribution.count_below_mg_l`).

## 2. Entradas (misma muestra) y co-ocurrencia

Se añadieron a la rebanada los determinandos `0061` pH y `0076` temperatura del agua (`configs/water/uk_water_quality.json`; misma rebanada, mismo periodo; 47 peticiones nuevas; manifiesto y conciliación con `X-Total-Items` al día: 93.930 filas CSV = 93.930 canónicas; las 52.708 filas de los tres determinandos originales son idénticas a las de AT-020, comprobado fila a fila en `observation_id, value, censoring, result_raw, timestamp_utc`).
pH 18.980 observaciones y temperatura 22.242 (una censurada cada una, ver §3).

Co-ocurrencia con OD (14.065 muestras con OD): amoniaco + ortofosfato 13.059 (92,8 %); además temperatura 13.059; además pH **13.052 (92,8 %)**. Sobre las 24.190 muestras de la rebanada el 54,0 % tiene OD y todas las entradas (el perfil de AT-020 daba 64,2 % sobre 20.343 muestras, antes de que entraran las muestras que solo tienen pH o temperatura).
Tras exclusiones y con las 6 features recomendadas finitas: **13.045 de 14.025 filas (93,0 %)**; las 980 incompletas (7,0 %) lo son sobre todo por falta de amoniaco (959) o de ortofosfato (970, una de ellas por su `<0,02`), pH (46) o temperatura (3).

| feature | rec. | unidad | `lag_hours` | definición |
|---|---|---|---|---|
| `ammoniacal_nitrogen` | sí | mg/l | 0 | determinando 0111 de la misma muestra, censura armonizada al límite común 0,03 (§3) |
| `orthophosphate_reactive` | sí | mg/l | 0 | determinando 0180 de la misma muestra, límite común 0,01 |
| `water_temperature` | sí | degC | 0 | determinando 0076 de la misma muestra |
| `ph` | sí | pH | 0 | determinando 0061 de la misma muestra |
| `days_from_midwinter` | sí | days | 0 | días entre la fecha local de la muestra y el 21 de diciembre más próximo: 0 en pleno invierno, 183 en pleno verano; **sin costura** de fin de año |
| `local_hour` | sí | hour | 0 | hora de reloj de Europe/London en decimal (10,5 = 10:30); el OD tiene ciclo diario |
| `local_day_of_year` | no | day | 0 | día del año local, 1-366; **con costura** (31 dic y 1 ene lejos). Redundante con `days_from_midwinter` |
| `point_median_phosphate_train` | no | mg/l | 0 | contexto del punto: mediana del ortofosfato armonizado del punto en el **periodo de train cronológico**; nulo con menos de 5 muestras de train (2.103 filas); nunca usa OD |

- **`lag_hours = 0` quiere decir «misma muestra / mismo instante»** (el instante de la toma), no «disponible en tiempo real». Para el contexto del punto, 0 es un convenio: es un perfil del periodo de train, no una observación a `issued_at − lag`.
  Posiblemente el OD, el pH y la temperatura se miden en campo y amoniaco y ortofosfato en laboratorio, con resultados días o meses después (`resultDate`, ver `api_notes.md`); **no se ha verificado en los datos** y la tabla no lo modela.
- Ninguna feature es un indicador 0/1 ni un entero con ≤ 5 valores distintos (`whole_number_features_with_at_most_5_distinct_values: []` en el informe), de modo que ex_fuzzy no categoriza ninguna aunque se use `construct_partitions` con detección automática.
- **Estacionalidad**: `days_from_midwinter` es el recomendado porque el OD de enero y de diciembre son parecidos y `local_day_of_year` los separa. `local_hour` es una hora de reloj local que salta una hora en los cambios de horario (documentado, 0 muestras en esas horas en esta rebanada).
- El número de features recomendadas es 6 (de 8 columnas); `point_median_phosphate_train` es opcional porque deja 15 % de filas sin valor y, en una validación espacial, describe el historial de un punto que en un caso real no existiría (ver §7).

## 3. Censura y límites de detección

**Qué hay.** Amoniaco: 55,7 % censurado (`<x`), con dos límites: `<0,03` (10.308) y `<0,002` (445), más un `<0,3`. Ortofosfato: 27,4 %, límites `<0,01` (5.162) y `<0,001` (137), más un `<0,02`. No se conoce la causa (método, laboratorio o programa).
Hay además muchos valores **medidos por debajo del límite dominante**: en las filas de la tabla, 3.292 amoniaco medidos < 0,03 y 2.443 ortofosfato medidos < 0,01. O sea, conviven un régimen grueso (límite 0,03; solo se informa `<0,03` o ≥ 0,03) y uno fino (límite 0,002; se informa 0,011, 0,014...). Esto es el problema: con `valor = límite` un `<0,03` queda **por encima** de un 0,01 medido aunque lo más probable es que sea menor.

**Decisión: armonizar al límite dominante L** (`encode_input`; L = 0,03 para amoniaco, 0,01 para ortofosfato). Todo resultado que se sabe que es ≤ L se codifica como L:

| caso | valor de la feature |
|---|---|
| medido > L | el valor medido |
| medido = L, medido < L, `<L`, `<` un límite menor que L | L |
| `<` un límite mayor que L (0,3; 0,02), o `>` | nulo (no se sabe si ≤ L) |
| sin resultado | nulo |

Para pH y temperatura (1 resultado censurado cada uno, `<7,9` y `<9,7`) no se armoniza: se anulan. Nada se sustituye en silencio: la tabla guarda el estado de cada fila (`ammoniacal_nitrogen_status`, `orthophosphate_reactive_status`) y el informe los cuenta.

Filas afectadas (de 14.025):

| estado | amoniaco | ortofosfato |
|---|---|---|
| medido > L (sin cambio) | 3.838 | 7.923 |
| medido = L (sin cambio) | 93 | 187 |
| medido < L, **subido a L** | 3.292 | 2.443 |
| `<L` | 5.400 | 2.366 |
| `<` límite menor que L, **subido a L** | 443 | 136 |
| `<` límite mayor que L, anulado | 0 | 1 |
| sin resultado | 959 | 969 |

El valor codificado es L en 9.228 filas de amoniaco (65,8 % de la tabla, 70,7 % de las filas completas) y en 5.132 de ortofosfato (36,6 %). Se cambia el valor numérico de 3.735 amoniaco y 2.579 ortofosfato (los «subidos»).

**Por qué esta y no otra.**
- *Valor = límite reportado* (la ingesta de AT-020): invierte el orden entre regímenes (arriba). Correlación de rango del OD con el amoniaco: −0,168 con esta opción, −0,181 con la armonizada.
- *Límite/2*: tiene la misma inversión, solo desplazada, y exige además un criterio por límite. Correlación −0,182. La diferencia con la armonizada (0,001) está por debajo de lo que esta tabla puede distinguir.
- *Restringir a un régimen*: no se puede identificar el régimen de una fila con valor medido (un 0,04 sale de cualquiera de los dos). Solo se puede descartar las filas censuradas, y entonces el 45 % del amoniaco (los censurados) desaparece y lo que queda son los puntos más contaminados (correlación −0,242 sobre 7.223 filas, otra población).
- *Límite como feature propia*: con la armonización, el «límite reportado» no añade información útil (casi todo es 0,03 o 0,002 y el 0,002 pertenece al régimen que se ha subido a L); y una columna casi constante de 2-3 valores es exactamente lo que se quiere evitar.

Sensibilidad (correlación de rango de Spearman del OD con la feature; descriptiva, sin modelo):

| codificación | amoniaco (n) | ortofosfato (n) |
|---|---|---|
| valor = límite reportado | −0,168 (13.066) | −0,231 (13.056) |
| límite/2 | −0,182 (13.066) | −0,229 (13.056) |
| **armonizada (elegida)** | −0,181 (13.066) | −0,245 (13.055) |
| solo filas no censuradas | −0,242 (7.223) | −0,264 (10.553) |

**Lo que sigue sin ser fiable.** Por debajo de L la tabla no sabe nada: «amoniaco BAJO» significa «≤ 0,03 mg/l» y es el 66 % de las filas. La partición cuantílica de ex_fuzzy sobre esta feature (comprobada sin entrenar, 3 términos, train) produce `Low` y `Medium` que valen ambos 1 en 0,03 y `High` solo por encima: el término BAJO y el MEDIO empiezan en el mismo pico. Es un efecto de los datos y no un error de la tabla; A4 debe decidir si usa más términos o particiones propias.
Los valores por encima de L se toman como se publicaron (máximo 263 mg/l de amoniaco; sin recorte). La armonización pierde la diferencia entre 0,002 y 0,03, que sí es real, y que con los datos de esta rebanada no se puede recuperar.

## 4. La tabla

`data/processed/water/features/uk_water_do/` (Parquet hive `year=/month=`, año y mes UTC de `issued_at_utc`; al leer el directorio aparecen `year` y `month` como columnas: se ignoran). 14.025 filas, 426 puntos, ≈ 3 MB en disco (126 ficheros pequeños). Ordenada por punto y hora.

| columna | tipo | significado |
|---|---|---|
| `entity_id` | VARCHAR | punto de muestreo (`NE-…`), el mismo `entity_id` de `entities.geojson` |
| `sample_id` | VARCHAR | `{punto}/{n}` de la API; único (no hay réplicas en el mismo punto e instante) |
| `issued_at_utc` | TIMESTAMPTZ (UTC) | instante de la toma (hora local de Europe/London pasada a UTC, política de AT-020) |
| `valid_at_utc` | TIMESTAMPTZ (UTC) | **igual que `issued_at_utc`** |
| `target` | DOUBLE | OD, mg/l |
| 8 columnas de feature | DOUBLE | §2 |
| `ammoniacal_nitrogen_status`, `orthophosphate_reactive_status` | VARCHAR | estado de censura de la fila (§3); auditoría, no features |
| `sampling_purpose` | VARCHAR | propósito del muestreo de la API; auditoría, no feature |

**Semántica temporal.** No hay horizonte: el target se mide en la misma muestra cuyas otras determinaciones son las entradas, así que `valid_at_utc = issued_at_utc` y el horizonte es 0 h. El nombre `issued_at_utc` se conserva porque es la clave temporal que el pipeline, la API y la web esperan, y no porque se «emita» nada.
`entity_id + issued_at_utc` es único (comprobado) y la unión por muestra no multiplica filas: filas = muestras con OD que superan las exclusiones. Nulo nunca es 0.

**Exclusiones** (14.065 muestras con OD → 14.025 filas; 10.125 de las 24.190 muestras no tienen OD y no son filas):

| causa | solas | en secuencia |
|---|---|---|
| resultado de OD censurado | 0 | 0 |
| material de muestra no fluvial (`ANY WATER` 7, `SEA WATER` 6, `FINAL SEWAGE EFFLUENT` 3) | 16 | 16 |
| punto sin geometría: `NE-42100407`, coordenadas de relleno, `outside_dataset_extent` | 32 | 23 |
| OD > 20 mg/l (límite de plausibilidad de AT-020; 35,35 mg/l, una muestra) | 1 | 1 |
| **filas** | | **14.025** |

La diferencia 32 → 23 son 9 muestras del punto de relleno que ya eran de material no fluvial. Un punto sin geometría no se puede pintar en el mapa; el filtro lee `entities.geojson`, así que otro punto sin coordenadas quedaría fuera con su motivo.
El OD de 35,35 mg/l se conserva en las observaciones; solo se saca del target.

**Filas completas** (target y 6 features recomendadas finitas): 13.045 de 14.025 (93,0 %), 385 puntos. Nulos por columna en `uk_water_do_feature_report.json`.

## 5. Cobertura y distribución

Por año local (la red cambia: de 73 a 261 puntos activos al año y 2020 es el año de menos muestreo):

| año | filas | completas | puntos |
|---|---|---|---|
| 2015 | 1.240 | 1.237 | 187 |
| 2016 | 1.120 | 1.083 | 197 |
| 2017 | 1.312 | 1.036 | 204 |
| 2018 | 1.257 | 897 | 173 |
| 2019 | 2.027 | 1.860 | 261 |
| 2020 | 660 | 633 | 192 |
| 2021 | 1.262 | 1.238 | 108 |
| 2022 | 919 | 894 | 73 |
| 2023 | 912 | 903 | 84 |
| 2024 | 1.307 | 1.278 | 153 |
| 2025 | 2.009 | 1.986 | 168 |

Por punto (filas): p10 = 8, p25 = 12, mediana 23,5, p75 = 41,75, p90 = 74,5, máximo 150; 332 de 426 puntos tienen ≥ 12 filas (318 con ≥ 12 completas). La mayoría de los puntos tiene pocos años de datos: el modelo verá muchos puntos con pocas muestras.

OD (mg/l): p1 6,36; p5 8,40; p10 9,12; p25 10,2; mediana 11,4; p75 12,6; p90 13,3; p99 14,5. Media mensual (hora local): enero 12,75, abril 12,18, julio 9,56, agosto 9,62, octubre 10,59, diciembre 12,37. El ciclo anual es la estructura principal.

## 6. Estructura descriptiva (no es un modelo)

Correlación de rango del OD con cada feature, sobre las 13.045 filas completas: temperatura **−0,845**, `days_from_midwinter` −0,573, ortofosfato −0,244, amoniaco −0,180, pH +0,028, `local_hour` +0,009.

- **La temperatura domina** (Pearson² = 0,59; un ajuste cuadrático solo en temperatura, dentro de la muestra, 0,60): el OD de un agua más fría disuelve más oxígeno (solubilidad física), y casi todo lo que hace una regla con la temperatura es esa física, no la historia del amoniaco. Las reglas que no usan la temperatura se apoyan en `days_from_midwinter` (r de rango con la temperatura 0,74).
  Consecuencia de producto: si la historia del mapa tiene que ser amoniaco/fósforo, conviene que A4 entrene también una variante **sin temperatura** (y comparar), o plantear al usuario el OD en % de saturación (determinando `9901`, 15.964 observaciones en la rebanada), que ya descuenta la temperatura. No se ha hecho aquí por no ser la decisión de producto tomada.
- Dentro de cada tercil de temperatura (frío ≤ 6,4 °C, medio 6,5-11,4, cálido 11,5-22,5) la correlación de rango con el amoniaco es −0,18 / −0,18 / **−0,41** y con el ortofosfato −0,25 / −0,28 / **−0,38**: la asociación de los nutrientes con un OD bajo es más fuerte en agua cálida, que es coherente con la historia «amoniaco alto ∧ verano → OD bajo» como asociación, no como causa.
- Los nutrientes casi no se correlacionan con la temperatura (rango 0,04 amoniaco, 0,10 ortofosfato), de modo que su señal no es solo estacional.

## 7. Particiones

**Cronológica por fecha de muestra** (`configs/water/uk_water_do.json`, `split`; periodos semiabiertos `[from, to)` en UTC, embargo 30 días = `embargo_hours` 720; valida con `SplitSpec`):

| periodo | intervalo | filas | completas | puntos |
|---|---|---|---|---|
| train | [2015-01-01, 2021-12-01) | 8.756 | 7.862 | 335 |
| (embargo) | [2021-12-01, 2022-01-01), [2023-12-01, 2024-01-01) | 193 | 193 | – |
| validation | [2022-01-01, 2023-12-01) | 1.760 | 1.726 | 103 |
| test | [2024-01-01, 2026-01-01) | 3.316 | 3.264 | 195 |

Dos años completos de test (2024 y 2025). Los huecos reales son de 31 días (límites en el primer día del mes), ≥ el embargo declarado. El embargo es aquí un parche contra la autocorrelación entre muestras consecutivas del mismo punto (r = 0,72 con 20-45 días de hueco, perfil §9), no contra una fuga de target (no hay horizonte).
**El test contiene puntos no vistos en train**: 824 de 3.316 filas (25 %) y 348 de 1.760 en validación, porque la red cambia. Así que este split mezcla generalización temporal y cierta generalización espacial.

**Espacial (puntos enteros fuera)** — `uk_water_do_spatial_split.json`, `spatial_split` de la configuración. Cada punto va a `train` (70 %), `validation` (10 %) o `test` (20 %) según `sha256("{seed}:{entity_id}")` (primeros 8 bytes entre 2⁶⁴), con `seed = 20261030`. Es determinista, no depende del contenido de la tabla ni del generador de números aleatorios de ninguna librería, y la lista de puntos queda escrita en el JSON.

| grupo | puntos | filas | completas |
|---|---|---|---|
| train | 280 | 9.286 | 8.665 |
| validation | 46 | 1.218 | 1.074 |
| test | 100 | 3.521 | 3.306 |

Se usan todas las fechas, así que train y test comparten calendario (meteorología regional): mide el paso a puntos nuevos, no a años nuevos. Se puede combinar con la cronológica (train = puntos de train ∩ periodo de train; test = puntos de test ∩ periodo de test), cuyo recuento no se ha tabulado.
**`SplitSpec` solo describe periodos**: el split espacial lo tiene que aplicar A4 con una máscara por `entity_id` (hay una función `spatial_assignment`). Con él, **no usar `point_median_phosphate_train`**: está calculada sobre el historial de entradas del punto en el periodo de train cronológico, algo que un punto nuevo no tendría (sin usar OD, pero no es «punto no visto»).

## 8. Referencias descriptivas esperables (solo definiciones, sin entrenar)

- **Media global**: la media del target en train, aplicada a todo. Su error es la dispersión del OD (≈ 1,76 mg/l).
- **Media del punto**: la media del OD del punto en train; media global si el punto no está en train. Solo vale en la partición cronológica; en la espacial colapsa a la media global. *Usa el OD pasado del mismo punto: es una referencia, nunca una feature.*
- **Solo estación**: media (o mediana) del OD en train por mes local o por tramo de `days_from_midwinter`; sin punto, sin nutrientes. Es el listón que tiene que batir cualquier regla que quiera decir algo más que «es invierno».
- La climatología de `atlas.ml.baselines` (hora × día de la semana de `valid_at`, por entidad) **no tiene sentido** aquí; hay que sustituirla por la «solo estación». Tampoco hay `persistence_feature`.

## 9. Riesgos

- **Límites de detección heterogéneos** (§3): el 66 % del amoniaco y el 37 % del ortofosfato son «≤ L». La información por debajo de L no está.
- **Temperatura dominante** (§6): el modelo puede acabar siendo «OD según temperatura» con adornos; que los nutrientes aporten algo se tiene que medir con la variante sin temperatura.
- **Muestreo disperso y de campaña**: mediana de 23,5 filas por punto y 426 puntos; muchos pocas. El OD solo se mide en el 58 % de las muestras, en programas concretos (falta sobre todo en el seguimiento «UK GOVT POLICY» y en investigaciones locales, perfil §4): el conjunto de muestras con OD no es una muestra aleatoria de la red.
- **Cambios de red**: puntos activos por año 73-261; 2020 con 660 filas; 25 % de las filas de test en puntos sin train.
- **Sin bandera de calidad**: la API no publica QA; `validity_flag` es nulo en toda la fuente y eso no equivale a «válido verificado». No se ha depurado nada salvo el OD > 20 mg/l.
- **La rebanada no es una cuenca**: sub-área H de la EA (Northumberland & Tyne) es una división administrativa. No hay tramos de río ni interpolación espacial; entidades = puntos de muestreo.
- **Disponibilidad**: la tabla es una reconstrucción histórica; los resultados de laboratorio llegan días o meses después (`resultDate`, ver `api_notes.md`). No se afirma capacidad de tiempo real ni de alerta.
- **Corrección posterior del archivo**: la EA refresca el archivo mensualmente (hay correcciones); la versión de datos lleva la fecha de descarga.
- **Contexto de punto**: incluye la propia muestra en train (no es «dejar uno fuera»); en train la feature está algo más cerca de la propia entrada que en test. No usa el target.
- **Autocorrelación**: muestras consecutivas de un punto se parecen (r = 0,72); el split aleatorio sería engañoso, por eso se parte por tiempo o por punto.
- **Coste de entrenamiento**: 7.862 filas completas de train son pocas frente a las tablas de Madrid y NYC (cientos de miles); un ajuste de ex_fuzzy es rápido y el riesgo es de sobreajuste, no de coste.

## 10. Por qué no se plantea un pronóstico

- **Por hora o por día**: la serie no existe. El muestreo es de campaña, la mediana de huecos entre muestras de un punto es de 25 días, el 10 % pasa de 60 días y no hay datos horarios ni diarios.
- **«Siguiente muestra del mismo punto»** (problema 3 del perfil): el hueco es variable, el OD consecutivo ya tiene r = 0,72 y la persistencia deja poco margen; sería un problema de series irregulares con una referencia que depende del OD pasado, que el usuario descartó con la decisión de producto.
- **Interpolar el OD entre puntos o dibujar tramos**: sin modelo espacial validado (`AGENTS.md`, invariante 7).

## 11. Propuestas de contrato (no se ha tocado `contracts`)

1. **Horizonte 0.** Verificado en el código actual: `SplitSpec.embargo_hours` admite 0 (`ge=0`) y la comprobación de fuga con horizonte 0 es trivial, pero `RunManifest.horizon_hours`, `TaskInfo.horizon_hours` y `RegistryEntry.horizon_hours` son `gt=0`. Cambio mínimo: `ge=0` en los tres (la regla `embargo_hours ≥ horizon_hours` sigue valiendo) y regenerar los esquemas. Un 0 significaría «inferencia en el mismo instante»; la web no debería mostrar «a +0 h» como horizonte (decisión de A0/A5).
   *Alternativa sin cambiar el contrato*: en la configuración de A4 usar `horizon_hours = 1` y `embargo_hours = 720`. **No es un horizonte real**, pero el pipeline pondrá `valid_at_utc = issued_at_utc + 1 h` en `predictions.parquet`, distinto del de la tabla, y hay que decirlo en `warnings` del manifiesto.
2. **`available_at_utc`.** La fecha del resultado de laboratorio (`resultDate`) no viene en el CSV masivo; está en el recurso de cada muestra, que costaría una petición por muestra (≈ 14.000). No es necesaria para esta tarea descriptiva y no se ha pedido. Propuesta: seguir pendiente y no bloquear AT-021; la tarjeta ya dice que no hay tiempo real.
3. **Máscara por entidad en la partición.** `SplitSpec` es solo cronológico; el split espacial necesita una máscara que A4 aplica por `entity_id`.

## 12. Reproducir

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data      # datos compartidos entre worktrees
PYTHONPATH=src python -m atlas.domains.water.ingest --skip-download   # normaliza desde la caché (5 determinandos)
PYTHONPATH=src python -m atlas.domains.water.features --write-spec    # tabla + informe + split espacial + feature_spec
PYTHONPATH=src python -m pytest tests/water -q
```

La tabla se construye en ≈ 2 s con un pico de RSS de ≈ 230 MB. Salidas en `data/processed/water/features/`: `uk_water_do/`, `uk_water_do_feature_report.json` (todas las cifras de este documento), `uk_water_do_spatial_split.json`.
Para publicar un modelo (`docs/api.md`): `--features 'data/processed/water/features/uk_water_do/**/*.parquet'`, `--entities data/processed/water/entities.geojson`, `--feature-spec configs/water/feature_spec.json`.
