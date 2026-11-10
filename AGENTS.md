# Guía para contribuir a ExFuzzy Atlas

Sirve igual para personas y para agentes de código.

## Invariantes

1. Este proyecto es independiente de ExFuzzy Lab. **No editar `Fuminides/exfuzzy-lab`**. Consumir la librería Python `ex_fuzzy` como paquete; **no editar `Fuminides/ex-fuzzy`** salvo petición explícita y aprobación del mantenedor.
2. Leer `MASTER_PLAN.md`, `CONTRACTS.md` (v0.1 ratificado, §7), **`MAP_EXPERIENCE.md`**, `docs/architecture.md` y los issues relacionados antes de tocar código.
3. No iniciar un trabajo que dependa de contratos no ratificados; usar fixtures y mocks mientras el esquema no esté fijado.
4. Mantener cada cambio dentro de su área; los cambios compartidos a `src/atlas/contracts`, `src/atlas/ml`, `apps/api` o `apps/web` van en un PR propio y coordinado.
5. No introducir dependencias cloud de pago, credenciales ni descargar/commitear gigabytes al repositorio.
6. Priorizar reproducibilidad, ingeniería de datos, honestidad científica, mantenimiento y UX. El diferenciador principal de Atlas es **la activación de reglas sobre mapas con geometría verificada**, no un mapa genérico junto a una tabla.
7. **No afirmar causalidad, cobertura conforme, precisión clínica/sanitaria, o capacidades en tiempo real sin validación.** Nunca tratar firing como probabilidad, contribución o riesgo. No interpolar observaciones puntuales como datos de área sin modelo espacial validado. En la interfaz y en los textos generados esto se cumple con **redacción precisa, sin avisos defensivos**: no se escriben frases cuyo único fin es decir lo que algo «no es» (los tests de palabras prohibidas siguen vigentes).

## Idiomas (ES/EN)

- La web es bilingüe: cada texto de la interfaz va con `tr(es, en)` junto a su uso, y los números y fechas pasan por `apps/web/src/lib/format.ts`.
- Lo que manda la API (variables, términos, clases, entidades, atribuciones) es **dato**: no se traduce en la web; el contrato v0.6 añade campos `*_en`, que se muestran con `localized(es, en)` y caen al castellano si faltan.
- Inglés británico (colour, licence, modelled). Un término, una traducción: `apps/web/src/i18n/GLOSSARY.md`, que también recoge la guarda de redacción honesta en inglés.

## Estilo y pruebas

- Python con tipos, pruebas pytest, docstrings claras; TypeScript estricto donde sea posible.
- Comandos reproducibles en `README.md` o `docs/reproduce.md`; datos externos en `data/` ignorado por Git.
- Ejecutar tests del módulo y adjuntar resultados relevantes al PR. Para cambios ML, guardar split y semillas.
- Evitar cambios en APIs públicas sin versión/contrato; incluir tests de compatibilidad.
- Cada PR debe tener: contexto; archivos editados; comandos corridos; evidencia/estadísticas; limitaciones; siguiente paso.
- No lanzar muchas búsquedas o jobs pesados a la vez sobre el mismo nodo; coordinar los benchmarks.

## Protocolo

- **Ramas:** una por issue o tarea, en un worktree propio. Se abre un PR a `main`; el mantenedor lo revisa y lo fusiona con la CI en verde.
- **Contratos:** `src/atlas/contracts` es la forma normativa. Un cambio sube `SCHEMA_VERSION`, regenera `make schemas fixtures`, añade un test de compatibilidad y una enmienda en `CONTRACTS.md`.
- **Decisiones y semántica:** `docs/architecture.md` y `CONTRACTS.md` §7.
- **Identificadores en documentos antiguos:** los informes y enmiendas anteriores citan a los agentes que los escribieron (A0 integración y contratos, A1 aire, A2 agua, A3 movilidad, A4 ML, A5 web, A6 QA) y los issues `AT-xxx` del backlog original. Es historia, no un reparto vigente de rutas.

## Informe final de cada tarea

1. Qué consiguió y qué no.
2. Archivos y símbolos relevantes.
3. Número de observaciones, periodo, calidad y fuente (en tareas de datos).
4. Métricas y protocolo (en tareas ML).
5. Comandos de reproducción/test y su resultado.
6. Riesgos, decisiones por resolver y dependencias para la siguiente tarea.

## Si se modifica la librería upstream

En `Fuminides/ex-fuzzy`, leer `AGENTS.md`, `LLM/DEVELOPMENT.md` y `LLM/DELEGATION.md`; para optimización genética o kernels leer además los documentos de performance requeridos por upstream. Respetar parity y suites de tests. Esto **no está autorizado por defecto**.

## Entorno y operativa

- **Python:** `PYTHON` (Makefile; por defecto `python`) es el intérprete del entorno donde está instalado el proyecto, con `ex-fuzzy==3.4.0` de PyPI (la versión fijada en `pyproject.toml`). Si falta un paquete, se declara en `pyproject.toml`. El Makefile fija `PYTHONPATH=src:apps/api`. Desde el contrato v0.7 se necesita ex-fuzzy 3.4.0, la primera versión con la mezcla de reglas; `EXFUZZY_SRC=<checkout>` (Makefile) usa otro ex_fuzzy en su lugar y registra su commit (`docs/reproduce.md`).
- **Comandos:** `make test`, `make lint`, `make schemas`, `make fixtures`, `make api` (ver `docs/reproduce.md`).
- **Datos:** raw en la raíz de datasets de la máquina (`ATLAS_DATASETS_ROOT`, por defecto `~/Datasets`), con symlink en `data/raw/<source>` (ver `LLM_help/DATASETS_PATHS.md`). No dejar datos reales en git.
- **Fixtures:** las sintéticas van en `fixtures/synthetic/`, llevan `synthetic: true` y nunca se presentan como reales.
- **Memoria y cómputo:** en una máquina de ~15 GB de RAM compartida con otros trabajos (a menudo solo ~4 GB libres), comprobar `free -g` antes de un ETL o un test pesado; ETL en streaming con DuckDB y `memory_limit` explícito, sin cargar históricos completos en pandas; los tests de Python, de fichero en fichero (`python -m pytest <fichero> -q`), sin la suite completa (la ejecuta la CI). Los ajustes pesados (Alemania: unos 9,5 GB por ajuste) van a una máquina remota más grande (CPU/GPU), y sus directorios de run se copian de vuelta.
