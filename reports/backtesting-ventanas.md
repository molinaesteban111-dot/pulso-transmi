# Backtesting temporal con ventanas expansivas

## Objetivo y protocolo

Comprobar si los resultados de la primera validación de siete días se sostienen en cortes temporales cercanos, sin entrenar con observaciones futuras respecto de cada validación.

- Tres ventanas consecutivas, no solapadas, de siete días cada una.
- En cada ventana se entrena desde el inicio del histórico disponible hasta el inicio de validación; por tanto, el conjunto de entrenamiento crece hacia las ventanas recientes.
- Se comparan persistencia, naive estacional diario (96 intervalos), Ridge e HistGradientBoosting.
- En cada corte se vuelve a ajustar Ridge y HistGradientBoosting.
- La evaluación cubre 12 estaciones, cuatro horizontes (+15, +30, +45 y +60 min) y 32.256 predicciones por método y ventana.
- Métrica principal: promedio no ponderado entre estaciones de `100 × max(0, 1 − WAPE_estación)`.

Las ventanas se enumeran de la más reciente (1) a la más antigua (3). Todas pertenecen al mismo histórico de 45 días, por lo que esta prueba mide consistencia local y no variación estacional anual.

## Resultado agregado de los cuatro horizontes

| Ventana (fin) | HistGradientBoosting | Ridge | Naive estacional | Persistencia |
|---|---:|---:|---:|---:|
| 1 (9 sep 2026) | **85,76 %** | 82,86 % | 77,89 % | 74,47 % |
| 2 (2 sep 2026) | **85,21 %** | 82,23 % | 76,83 % | 74,29 % |
| 3 (26 ago 2026) | **85,44 %** | 82,52 % | 77,80 % | 74,54 % |
| Promedio | **85,47 %** | 82,54 % | 77,51 % | 74,43 % |

HistGradientBoosting gana en las tres ventanas. Su variación entre la puntuación mayor y menor es de 0,55 puntos porcentuales. También queda por encima de Ridge por 2,93 puntos en promedio, del naive estacional por 7,96 y de persistencia por 11,04.

## Accuracy de HistGradientBoosting por horizonte

| Ventana | +15 min | +30 min | +45 min | +60 min |
|---|---:|---:|---:|---:|
| 1 | 86,38 % | 86,13 % | 85,57 % | 84,97 % |
| 2 | 85,90 % | 85,64 % | 85,02 % | 84,28 % |
| 3 | 86,07 % | 85,86 % | 85,32 % | 84,50 % |

El orden entre los cuatro métodos se conserva al agregar los horizontes; HistGradientBoosting supera los baselines en cada horizonte de cada corte. Los resultados por estación se encuentran en `rolling_backtest_metrics.csv`.

## Interpretación y decisión

Los resultados dan soporte para empaquetar HistGradientBoosting como **candidato recomendado**. No lo declaran champion productivo: hay solo tres semanas de validación sobre un mismo tramo histórico, los entrenamientos son expansivos y podría existir deriva en periodos más largos. Antes de conectarlo a una ruta de producción o a la competencia, ampliar el backtest con más histórico/ventanas y revisar estaciones individualmente.

## Reproducción

```bash
python -m pip install -e '.[ml]'
python examples/01_download.py
python examples/05_rolling_backtest.py --windows 3 --validation-days 7
```

El script genera `rolling_backtest_metrics.csv` y el detalle comprimido `rolling_backtest_predictions.csv.gz` en `reports/`.
