# Modelos candidatos y validación temporal

## Qué se entrenó

Se entrenaron dos modelos pooled (un modelo global para estaciones y horizontes), después de implementar los baselines:

- **Ridge:** regresión lineal regularizada, `alpha=10`.
- **HistGradientBoostingRegressor:** boosting de histogramas, 120 iteraciones, tasa 0,08, 31 hojas máximas y semilla fija 42.

Ambos se compararon con persistencia y naive estacional diario en exactamente la misma partición temporal, misma cobertura y métrica.

## Validación y prevención de fuga

- Entrenamiento: **142.728** filas objetivo hasta el cutoff.
- Validación: **32.256** predicciones por método, en los últimos 7 días (2–9 de septiembre de 2026 UTC), con 8.064 por horizonte.
- Los targets de validación no participan en el ajuste.
- Cada fila calcula rezagos y promedios móviles con información disponible en su origen de pronóstico.
- Variables: estación (one-hot), hora y día cíclicos, fin de semana, horizonte, rezagos al origen (0, 1, 4, 96 y 672 intervalos), promedios móviles y demanda del mismo intervalo del día anterior (`target_lag_96`). Este último es conocido antes del origen para horizontes de hasta 60 minutos.
- Se excluyó el contexto meteorológico: el corte no proporciona una variable de pronóstico futuro alineada y disponible en cada origen; usar el clima observado del target produciría fuga.
- Predicciones recortadas a cero para respetar demanda no negativa.

La métrica principal es la accuracy oficial: WAPE por estación, transformado a `100 × max(0, 1 − WAPE)` y promedio no ponderado entre las 12 estaciones. WAPE global y MAE son referencias auxiliares.

## Accuracy macro por estación

| Método | +15 min | +30 min | +45 min | +60 min | Cuatro horizontes |
|---|---:|---:|---:|---:|---:|
| Persistencia | 82,58 % | 77,94 % | 71,87 % | 65,48 % | 74,47 % |
| Naive estacional diario | 77,89 % | 77,89 % | 77,89 % | 77,89 % | 77,89 % |
| Ridge | 83,67 % | 83,64 % | 82,76 % | 81,38 % | 82,86 % |
| HistGradientBoosting | **86,38 %** | **86,13 %** | **85,57 %** | **84,97 %** | **85,76 %** |

HistGradientBoosting supera a ambos baselines en esta partición y en cada horizonte. Ridge también supera ambos baselines desde +30 minutos y mejora la persistencia en +15. Es evidencia favorable, pero proviene de una única ventana temporal.

## Estado de promoción

Los modelos son **candidatos**, no champion desplegado. Se ejecutó un backtest adicional con tres ventanas de validación consecutivas, no solapadas, de siete días y entrenamiento expansivo antes de cada ventana. HistGradientBoosting mantuvo el primer lugar en las tres: su accuracy macro fue 85,76 %, 85,21 % y 85,44 % (promedio 85,47 %), por encima de Ridge (promedio 82,54 %) y del naive estacional (77,51 %). También superó a los baselines en cada horizonte de las tres ventanas.

Esto aporta evidencia de estabilidad en un periodo de tres semanas, pero no equivale a una validación estacional larga. Los tres modelos se entrenan con conjuntos crecientes y las ventanas son consecutivas; no son muestras independientes. Antes de llamarlo champion operativo aún se recomienda evaluar más semanas y revisar los resultados por estación. Por ahora HistGradientBoosting queda como **candidato recomendado para empaquetado**, no como modelo desplegado.

El protocolo y los resultados reproducibles están en [`backtesting-ventanas.md`](backtesting-ventanas.md), `rolling_backtest_metrics.csv` y `rolling_backtest_predictions.csv.gz`; el script es [`examples/05_rolling_backtest.py`](../examples/05_rolling_backtest.py).

## Artefactos y reproducción

- Script: [`examples/04_train_models.py`](../examples/04_train_models.py)
- Métricas por estación y horizonte: [`model_metrics.csv`](model_metrics.csv)
- Predicciones de validación: [`model_predictions.csv`](model_predictions.csv)
- Cutoff, variables e hiperparámetros: [`model_metadata.json`](model_metadata.json)
- Backtesting de tres ventanas: [`backtesting-ventanas.md`](backtesting-ventanas.md)
- Artefactos serializados: `artifacts/candidates/*.joblib` durante el entrenamiento. Según la confirmación del equipo, el workflow manual terminó correctamente y cargó los candidatos al bucket privado `pulso-transmi-model-artifacts` de Supabase; no son todavía un champion productivo.

```bash
python -m pip install -e '.[ml]'
python examples/01_download.py
python examples/04_train_models.py
python examples/05_rolling_backtest.py --windows 3 --validation-days 7
```
