# Notas de la API: Water Quality Explorer (Environment Agency, Inglaterra)

Verificado el **2026-10-30** contra el servicio real (AT-020). Todo lo de esta página se comprobó con peticiones
reales, salvo lo marcado como *no verificado*. El cliente que lo implementa es `src/atlas/domains/water/client.py`.

## 1. Cómo se llega a la API

1. Ficha del dato: <https://www.data.gov.uk/dataset/583e771f-1af6-4934-b8f0-28f1d1ddd48c/water-quality-explorer>
   (publisher Environment Agency, actualizada el 18/09/2026; enlaza al Explorer y a su FAQ).
2. Explorer web: <https://environment.data.gov.uk/water-quality> (menú «Downloads», «API», «FAQ»).
3. Documentación de la API (Swagger UI): <https://environment.data.gov.uk/water-quality/api-docs>; la UI carga la
   especificación **OpenAPI 3.1** de <https://environment.data.gov.uk/water-quality/api/swagger>
   (también en `/water-quality/openapi.json`): título «Water Quality Archive», versión **1.3.1**.
4. FAQ de la retirada de la API antigua (11/12/2025): el enlace de la tarea,
   `https://dsp.environment.data.gov.uk/support/faqs/275879249/1156874241`, **no resolvía por DNS desde la red de desarrollo**; la misma
   página está en <https://environment.data.gov.uk/support/faqs/275879249/1156874241> («Turning off the legacy Water
   Quality Archive»). Es una página renderizada en el cliente: el texto está en el JSON `__NEXT_DATA__` del HTML.

## 2. Resumen

| Aspecto | Valor |
|---|---|
| URL base | `https://environment.data.gov.uk/water-quality` |
| Clave / credenciales | **Ninguna.** Sin registro ni cabecera de autenticación |
| Licencia | Open Government Licence v3.0 (el pie del Explorer: «All content is available under the Open Government Licence v3.0») |
| Atribución | «© Environment Agency copyright and/or database right 2025. All rights reserved.» (ficha de data.gov.uk). Con OGL v3.0: «Contains public sector information licensed under the Open Government Licence v3.0.» |
| Paginación | `skip` + `limit` (desplazamiento). Cabeceras `X-Total-Items`, `X-Page-Skip`, `X-Page-Limit` y `Link` (`self`, `first`, `last`, `next`, `previous`); JSON-LD añade `totalItems` y `view.next` |
| Último página | La respuesta no trae `rel="next"` en `Link` (ni `view.next`). Pedir una página más allá del final devuelve **200 con cuerpo vacío** |
| Tamaño de página | Observaciones: **2500** (CSV, JSON Lines), **250** (JSON-LD). Puntos de muestreo: 250 en JSON-LD (el esquema OpenAPI dice 250 para `GET`). Más allá: HTTP 422 |
| Límite de tiempo | Consulta de **varios puntos**: el rango `dateFrom`–`dateTo` debe ser **menor de un año** (HTTP 400 «maximum temporal range is 1 year»; `2015-01-01` a `2016-01-01` ya se rechaza). Un solo punto (`/sampling-point/{id}/observation`): sin límite (probado 21 años) |
| Límite de puntos | `pointNotation` admite como mucho 100 códigos separados por coma |
| Cuotas / rate limit | **No documentados** y no se envía ninguna cabecera `RateLimit-*` ni `Retry-After`. En ~650 peticiones a ≤ 2 por segundo no se vio un 429 ni un 5xx. No se probó por encima de ese ritmo |
| Resultado vacío | HTTP **204** sin cuerpo (ni `X-Total-Items`) cuando el filtro no encuentra nada |
| Reintentos | El cliente reintenta 429, 500, 502, 503, 504 y errores de red con espera exponencial (2, 4, 8, 16 s; tope 60 s) y respeta `Retry-After` |
| Cortesía | `User-Agent` descriptivo con contacto, 0,5 s mínimo entre peticiones, una petición a la vez, sin paralelismo |

## 3. Endpoints (OpenAPI 1.3.1)

Todos cuelgan de la URL base. Los marcados con ✓ se usan en AT-020.

| Método y ruta | Para qué | Notas |
|---|---|---|
| `GET /sampling-point` ✓ | Puntos de muestreo (filtros abajo) | JSON-LD (`application/ld+json`) o GeoJSON; **CRS** por cabecera `Accept-Crs`, por defecto BNG |
| `GET /sampling-point/{pointNotation}` | Un punto | |
| `POST /data/sampling-point` | Puntos dentro de un polígono GeoJSON (cuerpo) | |
| `GET /sampling-point/{p}/sample`, `.../sampling` | Muestras / muestreos de un punto | JSON-LD |
| `GET /sampling-point/{p}/sample/{n}` | Una muestra | |
| `GET /sampling-point/{p}/observation` | Observaciones de un punto | sin tope de un año |
| `GET /sampling-point/{p}/sample/{n}/observation/{det}` | Una observación | |
| `POST /data/observation` ✓ | Observaciones de varios puntos | **POST** con cuerpo vacío o polígono; `GET` da 405 |
| `GET /codelist/determinand` ✓ (consulta) | 8 082 determinandos (`notation`, `prefLabel`, `altLabel`) | `prefLabel=` busca por texto, `notation=` exacto |
| `GET /codelist/unit` ✓ | 181 unidades (`prefLabel` «MILLIGRAM PER LITRE», `altLabel` «mg/l») | |
| `GET /codelist/sample-material` | 354 materiales (p. ej. `2AZZ` río/agua superficial corriente) | |
| `GET /codelist/sampling-point-type` | 113 tipos (`F6` = «FRESHWATER - RIVERS») | |
| `GET /codelist/sampling-point-status`, `/sampling-purpose` | estados y propósitos | |

La API **no** tiene un endpoint de «determinands con cobertura»: la cobertura se obtiene contando (`X-Total-Items` con
`limit=1`). Una copia de la especificación se puede volver a descargar de la URL del apartado 1.

### Filtros de `/data/observation` y `/sampling-point`

`determinand` (lista separada por comas), `samplingPurpose`, `sampleMaterialType`, `complianceOnly`, `dateFrom`, `dateTo`,
`samplingPointType`, `samplingPointStatus`, `prefLabel`, y **un solo grupo** de selección espacial:

- `region` (p. ej. `NE`), **o** `area` (+ `subArea`), **o** `precannedArea`, **o** `pointNotation`, **o**
  `easting`/`northing`/`radius`, **o** `latitude`/`longitude`/`radius`, **o** polígono en el cuerpo.
  Mezclar grupos da HTTP 400 («Only one of the following parameter groups can be provided»).
- Los códigos de `area` y `subArea` son la **letra suelta**, no el código compuesto que aparece en la respuesta
  (`"X-H"`): `area=X&subArea=H` selecciona «Northumberland & Tyne»; `subArea=X-H` no encuentra nada (204) y `subArea=H`
  sola mezcla las sub-áreas H de todas las áreas.

## 4. Cosas que no son obvias (y que rompieron una primera versión)

1. **`dateTo` es exclusivo.** `dateFrom=dateTo` devuelve 204; `dateFrom=2015-01-05&dateTo=2015-01-06` devuelve las 49 filas
   del 5 de enero. Un año natural no cabe en una consulta (se rechazan 365 días), así que `download` usa dos ventanas
   semestrales `[01-01, 07-01)` y `[07-01, 01-01 del año siguiente)`. Una primera versión usaba `dateTo=YYYY-12-31` y habría
   perdido en silencio las muestras del 31 de diciembre (en esta rebanada no existe ninguna, y el total es idéntico, pero
   el bug estaba ahí). Hay un test de regresión.
2. **Hace falta `Accept` explícito.** Sin él (`*/*`) la ruta cae al frontend y devuelve un 404 HTML. Valores válidos:
   `application/ld+json`, `application/x-jsonlines`, `text/csv`, `application/geo+json` (solo puntos, y solo con
   `Accept-Crs: …/4326`).
3. **`phenomenonTime` no lleva desfase horario** (`2015-02-03T10:28:00`). Se lee como hora de reloj de Europe/London;
   la evidencia está en `docs/water/profile.md` §7.
4. **Censura:** el resultado llega como texto: `"<0.03"`. En JSON-LD el mismo valor es
   `numericValue: null, upperBound: 0.03, lowerBound: null`. En esta rebanada solo aparece `<`; el cliente también
   interpreta `>`.
5. **Hora de muestreo y fecha de resultado.** `phenomenonTime` de la observación coincide con `startTime` del recurso
   `…/sampling/{n}` (comprobado en 3 muestras). Ese recurso trae también `resultDate` (fecha del resultado de laboratorio),
   que va de días a meses después (p. ej. muestra del 2018-01-09 con `resultDate` 2018-06-30). **No viene en el CSV** y AT-020 no lo
   descarga: si AT-021 necesita fijar cuándo estaba disponible un valor (`issued_at`), hay que traerlo de
   `GET /sampling-point/{p}/sampling`. Los filtros `dateFrom`/`dateTo` actúan sobre la hora de muestreo.
6. **Puntos con coordenadas de relleno.** `NE-42100407` («… MISCELLANEOUS LOCATIONS - SEE SAMPLE SPECIFIC GRID REF») publica
   BNG `500000, 3` (sale en el Canal de la Mancha, fuera de la extensión que declara la ficha del dato); el recurso de muestra no
   trae geometría. Se escribe con `geometry: null` y la marca `coordinate_flag`.
7. **No hay bandera de validez ni de cumplimiento** en CSV, JSON Lines ni JSON-LD (solo el filtro `complianceOnly`).
   Los datos se corrigen en el refresco mensual del archivo («monthly refresh … may include corrections»).
8. **El formato importa para el tamaño:** una observación pesa ~2,9 KB en JSON-LD y ~0,4 KB en CSV. Se usa CSV (2500 filas ≈ 1 MB, ≈ 1 s).
9. **CSV de observaciones:** 17 columnas fijas (`id`, `samplingPoint.*` con `easting`/`northing` en BNG, `phenomenonTime`,
   `samplingPurpose`, `sampleMaterialType`, `determinand.notation`/`prefLabel`, `result`, `unit`). La muestra y la
   observación se identifican por el `id`: `…/sampling-point/{punto}/sample/{n}/observation/{determinando}`. El lector
   falla si la cabecera cambia.
10. **Coordenadas:** BNG (EPSG:27700) a 1 m por defecto (JSON-LD, CSV). Con `Accept-Crs: http://www.opengis.net/def/crs/EPSG/0/4326`
   el JSON-LD da WGS84 **redondeado a 4 decimales** (~8 m); con `Accept: application/geo+json` (que solo admite WGS84) da 9 decimales.
   Se guarda como oficial el BNG y se convierte en local (`src/atlas/domains/water/bng.py`, Helmert OSGB36 a WGS84, sin dependencias):
   frente al GeoJSON de la propia API la diferencia en los 772 puntos de la rebanada es ≤ 1,5 m (media 0,9 m), y es idéntica a la de pyproj.
11. **Discrepancia con la FAQ:** la FAQ dice «`/data/observation`: all formats 250 results per page»; en la práctica CSV y JSON
   Lines admiten 2500 (lo dice el OpenAPI y se comprobó con CSV; 2501 da 422).
12. **Escala del archivo (2026-10-30):** 66 318 puntos de muestreo; la ficha dice > 72 millones de observaciones de > 5 millones de muestras desde 2000.

## 5. Peticiones de ejemplo

```bash
UA='exfuzzy-atlas/0.1 (open-data research; contact you@example.org)'
B=https://environment.data.gov.uk/water-quality

# Puntos de río de Northumberland & Tyne (772; 4 páginas de 250), BNG
curl -s -H "User-Agent: $UA" -H 'Accept: application/ld+json' \
  "$B/sampling-point?samplingPointType=F6&area=X&subArea=H&limit=250&skip=0" -D - -o /dev/null | grep -i 'x-total-items\|^link'

# Determinandos por nombre
curl -s -H "User-Agent: $UA" -H 'Accept: application/ld+json' "$B/codelist/determinand?prefLabel=Ammoniacal&limit=5"

# Observaciones: OD, amoniaco y ortofosfato, primer semestre de 2015 (POST sin cuerpo, CSV, 2500 por página)
curl -s -X POST -H "User-Agent: $UA" -H 'Accept: text/csv' \
  "$B/data/observation?samplingPointType=F6&area=X&subArea=H&determinand=9924,0111,0180&dateFrom=2015-01-01&dateTo=2015-07-01&limit=2500&skip=0"

# Solo contar (cobertura): cabecera X-Total-Items con limit=1
curl -s -X POST -D - -o /dev/null -H "User-Agent: $UA" -H 'Accept: text/csv' \
  "$B/data/observation?samplingPointType=F6&area=X&subArea=H&determinand=0061&dateFrom=2015-01-01&dateTo=2015-07-01&limit=1" | grep -i x-total-items

# Una observación censurada en JSON-LD (upperBound en lugar de numericValue)
curl -s -H "User-Agent: $UA" -H 'Accept: application/ld+json' \
  "$B/sampling-point/NE-41000003/observation?determinand=0111&dateFrom=2015-05-01&dateTo=2015-06-01&limit=2"
```

## 6. Determinandos de la rebanada

| Código | Etiqueta (API) | Unidad | Nombre canónico |
|---|---|---|---|
| `9924` | Oxygen, Dissolved as O2 | mg/l | `dissolved_oxygen` |
| `0111` | Ammoniacal Nitrogen as N | mg/l | `ammoniacal_nitrogen` |
| `0180` | Orthophosphate, reactive as P | mg/l | `orthophosphate_reactive` |

Otros códigos útiles: `0061` pH, `0076` Temperature of Water, `0117` Nitrate as N, `9901` Oxygen, Dissolved, % Saturation.
Hay muchos códigos casi homónimos (p. ej. `0082` oxígeno de laboratorio, `7786` sonda YSI): conviene fijar el código, no el nombre.

## 7. Qué no se ha verificado

- Que no existan cuotas diarias o por IP: no hay documentación y no se probó un ritmo alto (por cortesía).
- La causa de los dos límites de detección simultáneos del amoniaco y el ortofosfato (`docs/water/profile.md` §5).
- Estabilidad de las URL del OpenAPI y de los códigos de `area`/`subArea` a largo plazo; versión de la API observada: 1.3.1 (`API-Version: 1` se envía y se devuelve).
- El comportamiento fuera de la rebanada (otras regiones, otros determinandos, `precannedArea`, polígonos).
