# Atlas fNIRS: n-back a partir de promedios por bloque

Cuarto dominio de Atlas, que llega en varios PR: datos y ajuste (este), contrato v0.9 (dominio `fnirs` y geometría de
montaje), publicación y la vista del cuero cabelludo en la web.

## Datos

- **Tabla:** `block_avg_tmb.csv` de la demo ex-Fuzzy fNIRS (J. Caterson et al., https://github.com/jjcato9/ex_fuzzy_fnirs_demo,
  commit `244d8a0`, licencia MIT). Complementa el manuscrito «Formal Statistical Guarantees for the Explainable
  Multivariate Pattern Analysis of fNIRS» (Caterson et al. 2025, en revisión).
- **Registros originales:** Shin et al. (2018), *Simultaneous acquisition of EEG and NIRS during cognitive tasks for an open
  access dataset*, Scientific Data 5, 180003; https://doc.ml.tu-berlin.de/simultaneous_EEG_NIRS/. Licencia **CC0 1.0** según el
  registro DepositOnce (`dc.rights.uri`, doi:10.14279/depositonce-5830, consultado el 2026-11-16).
- **En disco:** `<raíz>/fnirs-nback` (`source_manifest.json` con sha256), con el enlace `data/raw/fnirs-nback`. Contiene la tabla, su
  `LICENSE` y la descripción del dataset (`dataset_description_MATLAB.pdf`), que trae las coordenadas de los 36 canales NIRS.

**Filas:** 702 = 26 sujetos × 27 bloques de la tarea n-back (9 de 0-back, 9 de 2-back y 9 de 3-back por sujeto), sin huecos ni valores no
finitos. **Entradas:** 72 = 36 canales × {HbO (`s1`), HbR (`s2`)}, en mmol/L. Cada una es la media del cambio de concentración entre 10 y
40 s tras el inicio del bloque menos la media entre −5 y −2 s (`001_Pre_Processing.m`: filtro paso bajo de 0,2 Hz y corrección de
línea base; `002_Block_Averaging.ipynb`). **Objetivo:** 0-back (evento 7, 234 filas) frente a 2-back o 3-back (eventos 8 y 9, 468 filas),
la agrupación del manuscrito. En la web se muestran como «Carga baja» (tarea fácil) y «Carga alta» (tarea difícil), sin la jerga n-back (`display_label` del esquema); la clave sigue siendo la del dataset.

**Canales:** se nombran por la posición 10-5 más cercana al punto medio entre fuente y detector (separación de 30 mm): 16 prefrontales,
4 alrededor de C3, 4 de C4, 4 de P3, 4 de P4 y 4 de POz. Sus coordenadas (esfera unidad; x a la derecha, y al frente, z arriba) están en
la tabla «Locations of NIRS channels in Cartesian coordinate system» de la descripción del dataset.

## Ajuste (`atlas.ml.experiment_fnirs`)

```bash
C=configs/ml/fnirs_nback_experiment.json
PYTHONPATH=src python -u -m atlas.ml.experiment_fnirs select --config $C   # validación cruzada por sujetos, sin test
PYTHONPATH=src python -u -m atlas.ml.experiment_fnirs final  --config $C   # forma elegida, semillas, baselines y test
```

- **Test:** los 6 sujetos del manuscrito (`random.seed(1); random.sample(range(1, 27), 6)` → 3, 4, 5, 9, 16 y 19). Ningún sujeto
  está en train y en test.
- **Selección:** k-fold de 5 grupos de 4 sujetos de train (semilla de pliegues 0) y 2 semillas del GA por pliegue. Gana la forma con
  mayor macro-F1 medio de validación; los baselines se puntúan en los mismos pliegues. El manuscrito eligió su modelo mirando el
  test; aquí no, así que las cifras de test no son comparables con las suyas.
- **Final:** la forma elegida, sobre los 20 sujetos de train, con las semillas 0–4; se publica la semilla 0, fijada antes de correr. Los
  baselines (clase mayoritaria, regresión logística, random forest y SVM RBF) ven las mismas entradas y la misma partición.
- Particiones: tres términos por cuantiles por entrada, calculados con las filas de ajuste. Una fila sin regla activa cuenta como error.

Resultados: [`docs/ml/fnirs_nback.md`](../ml/fnirs_nback.md).

## Publicación (contrato v0.9)

```bash
PYTHONPATH=src python -m atlas.domains.fnirs.montage   # configs/fnirs/montage.json, de la tabla del PDF
PYTHONPATH=src python -m atlas.domains.fnirs.regions   # configs/fnirs/regions.json, del cuaderno 005
PYTHONPATH=src python -m atlas.domains.fnirs.publish --run artifacts/fnirs_nback/mixture-r20-a2-ordinal-seed0
```

El publicador recalcula con ex_fuzzy la traza de los 702 ensayos, comprueba que su clase es la de `predict` del run y escribe
`artifacts/published/exfuzzy-fnirs_nback-mixture-r20-a2-ordinal-seed0/` con la entrada de registro `view: montage`. Las regiones son
las del cuaderno 005 de la demo (asignación aproximada por nombre de canal, con el área de Brodmann), y el castellano es traducción
de Atlas. La API (`docs/api.md` §9) y el export estático (`docs/static_export.md` §15) solo leen esos ficheros.
