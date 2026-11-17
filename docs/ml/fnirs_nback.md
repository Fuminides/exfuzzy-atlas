# fNIRS n-back: reajuste con ex-fuzzy 3.5.0 (`fnirs_nback_v1`)

2026-11-16 · `configs/ml/fnirs_nback_experiment.json` · código `atlas.ml.experiment_fnirs` (commit `550c231`) · datos y
protocolo en [`docs/fnirs/README.md`](../fnirs/README.md).

## Protocolo

- 702 bloques de 26 sujetos; 72 entradas (36 canales × HbO/HbR, mmol/L). Clases: 0-back (1/3) frente a 2/3-back (2/3).
- **Test:** los sujetos 3, 4, 5, 9, 16 y 19 del manuscrito (162 bloques: 54 de 0-back y 108 de 2/3-back). **Train:** los otros
  20 (540 bloques).
- **Selección:** rejilla de 24 formas (`inference` ∈ {winning_rule, mixture}, condiciones ordinales sí/no, `nRules` ∈ {5, 10,
  20}, `nAnts` ∈ {2, 3}; 3 términos por cuantiles, `n_gen` 100, `pop_size` 50, `patience` 20, `allow_unknown`). Cada forma se
  ajusta en 5 pliegues de 4 sujetos de train (`[1, 8, 23, 24]`, `[7, 18, 21, 26]`, `[11, 12, 14, 17]`, `[2, 6, 10, 15]`,
  `[13, 20, 22, 25]`) con 2 semillas del GA: 240 ajustes. Criterio fijado antes: mayor macro-F1 medio de validación.
- **Final:** la forma elegida sobre los 540 bloques de train con las semillas 0–4. Se publica la semilla 0, fijada en la
  configuración antes de correr. El test se puntúa una vez.
- **Criterio de publicación**, decidido por el mantenedor con la validación a la vista y el test sin leer: se publica salvo que el
  test quede por debajo de la clase mayoritaria (macro-F1 0,40).

## Validación (sujetos de train, 5 pliegues)

| Modelo | macro-F1 | sd | MCC | accuracy |
|---|---|---|---|---|
| **ExFuzzy `mixture-r20-a2-ordinal`** (elegido; 9,8 reglas de media) | **0,686** | 0,042 | 0,398 | 0,744 |
| ExFuzzy `mixture-r5-a3-ordinal` | 0,669 | 0,059 | 0,308 | 0,701 |
| ExFuzzy `winning_rule-r10-a2` | 0,664 | 0,039 | 0,326 | 0,683 |
| Random forest | 0,714 | 0,062 | 0,432 | 0,743 |
| SVM RBF | 0,679 | 0,062 | 0,372 | 0,707 |
| Regresión logística | 0,627 | 0,127 | 0,292 | 0,637 |
| Clase mayoritaria | 0,400 | 0 | 0 | 0,667 |

Las tres primeras formas de ExFuzzy están dentro del ruido entre pliegues; la elección entre ellas es poco informativa. Con las
condiciones ordinales, la mezcla mejora en 5 de las 6 combinaciones de `nRules` × `nAnts` y la winning-rule solo en 2.

## Test (6 sujetos, 162 bloques)

| Modelo | macro-F1 | accuracy | balanced acc. | MCC | reglas |
|---|---|---|---|---|---|
| **ExFuzzy, semilla 0 (publicada)** | **0,778** | 0,815 | 0,764 | 0,568 | 8 |
| ExFuzzy, semillas 0–4 | 0,773 ± 0,029 | 0,809 ± 0,023 | | 0,555 ± 0,056 | 8–13 |
| SVM RBF | 0,855 | 0,870 | 0,856 | 0,710 | |
| Random forest | 0,842 | 0,858 | 0,847 | 0,686 | |
| Regresión logística | 0,751 | 0,772 | 0,759 | 0,504 | |
| Clase mayoritaria | 0,400 | 0,667 | 0,500 | 0 | |

Ningún bloque de test se queda sin clase (`share_unknown` = 0). En train, la semilla 0 da macro-F1 0,742: el test sale mejor
que train y que la validación, como en el manuscrito; con 6 sujetos la varianza entre particiones es grande, y todos los
modelos puntúan más en test que en validación. En test, SVM y random forest sacan unas 0,07–0,08 de macro-F1 a ExFuzzy, más
que en validación.

**Frente al manuscrito** (ex-fuzzy 2.1.3, 6 reglas winning-rule, test accuracy 0,82 y MCC 0,62): cifras parecidas, pero no
comparables, porque allí la configuración y la semilla se eligieron mirando el test.

## Barras de error (`seeds`)

`python -u -m atlas.ml.experiment_fnirs seeds --config $C` reajusta cada baseline con las semillas 0–4 sobre la misma partición y
recoge, para validación, la puntuación de cada pliegue de sujetos. Solo ExFuzzy (el GA) y el random forest dependen de la semilla;
la SVM, la regresión logística y la clase mayoritaria dan siempre lo mismo.

| Modelo | Test, macro-F1 (5 semillas) | Validación, macro-F1 (5 pliegues) |
|---|---|---|
| ExFuzzy | 0,773 ± 0,029 | 0,686 ± 0,033 |
| SVM RBF | 0,855 ± 0 | 0,679 ± 0,062 |
| Random forest | 0,835 ± 0,015 | 0,714 ± 0,062 |
| Regresión logística | 0,751 ± 0 | 0,627 ± 0,127 |
| Clase mayoritaria | 0,400 ± 0 | 0,400 ± 0 |

(media ± desviación típica; en validación, ExFuzzy promedia antes sus dos semillas del GA en cada pliegue).

## Variabilidad entre personas (`nested`)

`python -u -m atlas.ml.experiment_fnirs nested --config $C` (unos 16 min con 5 procesos): las 26 personas en 5 grupos (6, 5, 5, 5
y 5); cada grupo hace de test una vez. Dentro de cada pliegue externo, la forma de ExFuzzy se elige otra vez con la misma rejilla y 5
pliegues internos de las demás personas, y todos los modelos se reajustan con las 5 semillas (media por grupo). Formas elegidas:
`mixture-r20-a2-ordinal`, `mixture-r20-a2` (tres veces) y `mixture-r10-a3-ordinal`. El modelo publicado no cambia.

| Modelo | Macro-F1 por grupo | Media ± desv. típica |
|---|---|---|
| ExFuzzy | 0,743 · 0,717 · 0,707 · 0,649 · 0,666 | 0,697 ± 0,038 |
| Random forest | 0,804 · 0,781 · 0,815 · 0,700 · 0,694 | 0,759 ± 0,058 |
| SVM RBF | 0,824 · 0,779 · 0,741 · 0,705 · 0,651 | 0,740 ± 0,067 |
| Regresión logística | 0,797 · 0,716 · 0,699 · 0,606 · 0,575 | 0,679 ± 0,089 |
| Clase mayoritaria | 0,400 en los cinco | 0,400 ± 0 |

Con personas distintas varían todos los modelos que aprenden algo; la clase mayoritaria no, porque cada persona hizo la misma
proporción de bloques (un tercio de carga baja). Los seis sujetos de test del manuscrito dan cifras más altas para todos los modelos
(0,77–0,86) que la media sobre personas: son un grupo más fácil.

## Reglas publicadas (semilla 0)

Mezcla de reglas (`inference='mixture'`, pesos no negativos): ninguna regla decide sola; cada regla suma a cada clase su peso
centrado por cuánto se cumple, y gana la clase de mayor puntuación. Se agrupan por la clase que más apoyan (`strongest_class`
de `rules.json`, lo que muestra la web), con su peso centrado. La clase que el GA asignó a cada regla solo sirvió en la
búsqueda y no coincide siempre (R01, R03, R04 y R05).

- Apoyan 0-back: R02 HbO PPOz como mucho Medium (+0,38); R03 HbR AFFz como mucho Medium (+0,21); R04 HbR AF7 al menos
  Medium (+0,37); R05 HbO AFp7 como mucho Medium y HbR PPO4 Medium (+0,26).
- Apoyan 2/3-back: R01 HbR AFp7 como mucho Medium (+0,45); R06 HbO AF1 Low (+0,31); R07 HbO AFF3h Low y HbR PPOz como mucho
  Medium (+0,90); R08 HbO AF1 Medium y HbR AFp7 Low (+0,80).

## Miradas al test fuera del protocolo

Hubo dos antes de fijar la rejilla. Un sondeo de tiempos ajustó dos formas sobre los 20 sujetos de train con la semilla 0 e
imprimió su test: `winning_rule-r10-a3` (macro-F1 0,604) y `mixture-r10-a3` (0,750). Las dos forman parte de la rejilla, y
ninguna salió elegida. El `final` de una prueba de humo con 3 generaciones imprimió 0,712. La rejilla ya incluía las dos
inferencias, y la elección salió solo de la validación cruzada.

## Reproducción

```bash
C=configs/ml/fnirs_nback_experiment.json
PYTHONPATH=src python -u -m atlas.ml.experiment_fnirs select --config $C   # ~8 min con 6 procesos de un hilo
PYTHONPATH=src python -u -m atlas.ml.experiment_fnirs final  --config $C   # ~1 min
```

Salidas: `artifacts/fnirs_nback/experiments/fnirs_nback_v1-{select,final}.json` y un directorio de run por semilla
(`model.pkl`, `predictions.parquet`, `run.json`, `SHA256SUMS`). La selección se ejecutó dos veces (la segunda, con los baselines añadidos): la forma elegida y las cinco primeras filas de la
tabla coinciden.
