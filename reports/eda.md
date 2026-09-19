# Análisis exploratorio de datos — Pulso TransMi

## Alcance

EDA del corte estático descargado el 16 de septiembre de 2026 desde la API pública. El corte contiene demanda histórica de 12 estaciones y variables de contexto. La descarga se realizó con `examples/01_download.py`.

## Calidad y estructura

| Recurso | Filas | Columnas | Cobertura |
|---|---:|---:|---|
| Estaciones | 12 | 5 | Catálogo geográfico |
| Observaciones | 51.840 | 3 | 2026-07-26 00:00 a 2026-09-08 23:45 (UTC-05) |
| Contexto | 4.320 | 6 | Mismo periodo, cada 15 minutos |

No se encontraron valores faltantes en demanda ni contexto. Tampoco hay duplicados por la llave `(station_id, observed_at)`. Cada estación tiene exactamente 4.320 observaciones y cada timestamp tiene 12 estaciones: la malla está completa. La frecuencia observada es de 15 minutos.

## Demanda

La demanda tiene media **356,52**, mediana **263**, desviación estándar **319,47**, mínimo **14** y máximo **2.284**. La media es superior a la mediana, lo que evidencia asimetría positiva y picos de demanda.

Las estaciones con mayor demanda promedio son 7111 (**683,72**), 5100 (**591,06**) y 6000 (**510,94**). Las de menor promedio son 9000 (**217,87**), 6111 (**238,89**) y 9122 (**249,80**). Por ello, conviene modelar por estación o incluir `station_id` y variables específicas de estación; un modelo global sin identificar la estación perdería información.

## Estacionalidad temporal

- La demanda laboral promedio es aproximadamente **380**, frente a **298–296** los domingos y sábados.
- La primera franja fuerte ocurre entre 05:00 y 09:00; el promedio máximo de la serie agregada está cerca de 07:15 (**694**).
- Hay una segunda franja fuerte entre 16:00 y 19:00; el máximo agregado está cerca de 17:45 (**731**).b
- La madrugada presenta los valores más bajos, alrededor de 01:30–03:00 (**137–139**).

Esto justifica crear features de hora, cuarto de hora, día de semana, fin de semana y variables cíclicas (`sin`/`cos`). Para predecir +15, +30, +45 y +60 minutos también son candidatos naturales los rezagos de 1, 2, 4 y 96 intervalos, además de promedios móviles calculados únicamente con información anterior al `data_cutoff`.

## Contexto

El contexto no tiene faltantes. `rain_mm` tiene media 0,26 y máximo 7,72; `temperature_c` varía entre 6,75 y 22,32 °C; `event_intensity` es cero en la gran mayoría de los registros y alcanza máximo 1.

En una correlación exploratoria contemporánea y no causal, la temperatura presenta la relación lineal más alta con la demanda (**0,208**), seguida por la lluvia (**-0,010**) y la intensidad de eventos (**0,088**). Estas correlaciones son débiles frente al patrón horario, por lo que el contexto debe evaluarse mediante backtesting temporal y no asumirse como predictor útil sin evidencia. Además, no debe usarse información futura que no estuviera disponible en el momento de inferir.

## Hipótesis para experimentar

1. Los rezagos recientes y el mismo cuarto de hora del día anterior explicarán más demanda que las variables meteorológicas aisladas.
2. La estacionalidad cambia entre estaciones; los modelos deben comparar estrategia global con modelos por estación.
3. El modelo debe distinguir días laborales de fines de semana y capturar dos picos diarios.
4. Los errores pueden aumentar durante picos y en estaciones de mayor volumen; deben reportarse por estación y horizonte, no solo de forma agregada.
5. Los eventos y la lluvia podrían ser útiles únicamente en ciertos periodos; su valor se debe comprobar con validación temporal.

## Decisiones siguientes

- Construir al menos dos baselines: persistencia de la última observación y persistencia estacional de hace 96 intervalos.
- Usar backtesting temporal, reservando los últimos 7 días como validación final y sin mezclar aleatoriamente los registros.
- Comparar un modelo global con `station_id` frente a modelos separados por estación.
- Evaluar WAPE/accuracy por estación, horizonte y ventana temporal.
- Conservar este corte, el `cutoff`, las features y las métricas como evidencia del experimento.

## Reproducibilidad

```bash
.venv/bin/python examples/01_download.py
```

Los datos analizados se encuentran en `data/` y fueron descargados desde los endpoints oficiales documentados en el SDK.
