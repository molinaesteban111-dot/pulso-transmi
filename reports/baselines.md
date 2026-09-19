# Baselines y validación temporal

## Propósito

Los baselines son referencias simples, anteriores a los modelos entrenados. Sirven para comprobar si un modelo más complejo aporta mejora real; todavía no son un modelo champion ni una predicción enviada a la competencia.

## Diseño del backtest

- Datos: histórico público de 12 estaciones, 15 minutos por observación.
- Ventana de evaluación: últimos 7 días del corte disponible, del 2 al 9 de septiembre de 2026 (UTC).
- Cantidad: 8.064 pares estación/target por horizonte; 32.256 predicciones entre los cuatro horizontes.
- Horizontes: +15, +30, +45 y +60 minutos.
- Sin ajuste de parámetros ni entrenamiento, y sin partición aleatoria.
- Se valida que cada estación tenga una grilla regular de 15 minutos y no haya duplicados antes de calcular rezagos.

### Baselines comparados

1. **Persistencia:** para un target `t` y horizonte `h`, predice la última observación disponible al origen `t-h` (rezago de `h` intervalos).
2. **Naive estacional diario:** predice el valor del mismo intervalo del día anterior, `demand(t-96)`. Ese dato ya está disponible para los cuatro horizontes.

La métrica principal es la accuracy oficial: se calcula WAPE dentro de cada estación, se transforma a `100 × max(0, 1 − WAPE)` y se promedia sin ponderar entre las estaciones. Se reportan además WAPE global ponderado y MAE como referencias secundarias.

## Resultado agregado por horizonte

| Baseline | Horizonte | Predicciones | Accuracy macro por estación | WAPE global | MAE |
|---|---:|---:|---:|---:|---:|
| Persistencia | +15 min | 8.064 | 82,58 % | 17,29 % | 62,78 |
| Naive estacional diario | +15 min | 8.064 | 77,89 % | 21,00 % | 76,24 |
| Persistencia | +30 min | 8.064 | 77,94 % | 21,87 % | 79,39 |
| Naive estacional diario | +30 min | 8.064 | 77,89 % | 21,00 % | 76,24 |
| Persistencia | +45 min | 8.064 | 71,87 % | 27,99 % | 101,59 |
| Naive estacional diario | +45 min | 8.064 | 77,89 % | 21,00 % | 76,24 |
| Persistencia | +60 min | 8.064 | 65,48 % | 34,40 % | 124,87 |
| Naive estacional diario | +60 min | 8.064 | 77,89 % | 21,00 % | 76,24 |
| Persistencia | agregado 4 horizontes | 32.256 | 74,47 % | 25,39 % | 92,16 |
| Naive estacional diario | agregado 4 horizontes | 32.256 | 77,89 % | 21,00 % | 76,24 |

## Lectura

- Persistencia es la referencia más fuerte a +15 minutos.
- En +30, +45 y +60 minutos, el naive estacional diario iguala o supera a persistencia en las métricas agregadas; la persistencia se degrada al aumentar el horizonte.
- En el promedio de los cuatro horizontes, el naive diario obtiene 77,89 % frente a 74,47 % de persistencia. Los modelos candidatos posteriores se compararon contra ambos; resultados en [`modelos.md`](modelos.md).
- El naive diario puntúa idéntico en los cuatro horizontes porque usa el mismo target del día anterior y este ya es conocido al origen de cada pronóstico. Es una propiedad del baseline, no evidencia de igualdad de dificultad entre horizontes.
- Estos números corresponden al corte histórico sintético actual; no garantizan el desempeño en la fase competitiva ni prueban causalidad.

## Archivos reproducibles

- Implementación: [`examples/03_baseline_backtest.py`](../examples/03_baseline_backtest.py)
- Métricas por baseline, estación y horizonte: [`baseline_metrics.csv`](baseline_metrics.csv)
- Predicciones evaluadas: [`baseline_predictions.csv`](baseline_predictions.csv)
- Cutoff y ventana de evaluación: [`baseline_metadata.json`](baseline_metadata.json)

Para regenerar los resultados tras descargar los datos:

```bash
python examples/01_download.py
python examples/03_baseline_backtest.py
```
