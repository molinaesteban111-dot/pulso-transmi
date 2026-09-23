# Estado del proyecto Pulso TransMi

**Corte:** 23 de septiembre de 2026
**Repositorio:** <https://github.com/molinaesteban111-dot/pulso-transmi>
**SDK de referencia:** <https://github.com/uexternadojz/pulso-transmi-sdk>

Este documento resume los entregables, decisiones técnicas, resultados y automatizaciones implementadas para el proyecto MLOps de pronóstico de demanda de TransMilenio.

## 1. Objetivo y contrato de la competencia

El sistema pronostica la demanda de 12 estaciones para cuatro horizontes: +15, +30, +45 y +60 minutos. Cada ciclo requiere **48 predicciones**. La API oficial define el ciclo abierto, el `data_cutoff`, la ventana de envío y los targets; el pipeline nunca inventa esos valores.

El flujo operativo es: consultar el ciclo, sincronizar observaciones, cargar el modelo campeón, generar y validar 48 predicciones, enviarlas con `Bearer` e `Idempotency-Key`, guardar la trazabilidad y consultar recibo, leaderboard y métricas.

## 2. Análisis exploratorio

El EDA se encuentra en [`reports/eda.md`](../reports/eda.md). Incluye distribución de demanda, comparación entre estaciones, variabilidad, estacionalidad horaria/semanal, serie temporal, contexto y cobertura.

Las nueve gráficas reproducibles están en [`reports/figures/`](../reports/figures/) y se generan con [`reports/generate_eda_plots.py`](../reports/generate_eda_plots.py).

Archivos principales: `reports/eda.md`, `reports/figures/*.png`, `reports/baselines.md` y `reports/backtesting-ventanas.md`.

## 3. Modelos y resultados

Se compararon persistencia, naive estacional diario, Ridge y HistGradientBoosting mediante validación temporal y ventanas rolling. HistGradientBoosting fue el mejor candidato, con un promedio aproximado de **85,47 % de accuracy** en las tres ventanas evaluadas.

El informe completo está en [`reports/modelos.md`](../reports/modelos.md). Los resultados reproducibles están en `reports/model_metrics.csv`, `reports/rolling_backtest_metrics.csv`, `reports/model_predictions.csv`, `reports/rolling_backtest_predictions.csv.gz` y `reports/model_metadata.json`.

El accuracy del backtest es una métrica local de selección. La API de competencia evalúa posteriormente las predicciones enviadas contra valores reales y calcula el leaderboard oficial.

## 4. Modelo campeón y empaquetado

El modelo campeón promovido es `hgb-champion-20260919T035232Z`, algoritmo HistGradientBoosting, con accuracy de validación `85.470003`. El artefacto `hist_gradient_boosting.joblib` está en el bucket privado `pulso-transmi-model-artifacts`.

El pipeline carga el `.joblib` desde Supabase Storage; ya no reentrena en cada ciclo. El entrenamiento y la promoción están separados en [`train-and-promote.yml`](../.github/workflows/train-and-promote.yml) y [`scripts/promote_model.py`](../scripts/promote_model.py). Solo se promueve un candidato si supera al campeón actual y la versión anterior queda como `historical`.

## 5. Modelo entidad-relación y Supabase

El diseño está documentado en [`modelo-entidad-relacion.md`](modelo-entidad-relacion.md). El proyecto Supabase utilizado es `bppwpnpidjffhzojquml`.

Tablas implementadas:

| Tabla | Propósito |
|---|---|
| `stations` | Catálogo de estaciones |
| `context` | Variables contextuales por timestamp |
| `observations` | Demanda observada e historial ingerido |
| `pipeline_runs` | Ejecuciones y estados del pipeline |
| `ingestion_batches` | Cursores y lotes de ingesta |
| `model_versions` | Versiones candidate/champion/historical |
| `model_transitions` | Historial de promociones y rollback |
| `predictions` | Predicciones por estación y horizonte |
| `submissions` | Envíos a la API y recibos |
| `evaluations` | Errores y accuracy por predicción |
| `metric_snapshots` | Accuracy, WAPE, cobertura y drift |

La tabla `predictions` ya contiene las predicciones generadas. `evaluations` y `metric_snapshots` quedan preparadas para llenarse cuando la API libere los valores ground truth evaluables. RLS está habilitado y las credenciales privilegiadas no se versionan.

## 6. Ingesta de datos

[`src/ingest.py`](../src/ingest.py) implementa carga inicial (`--initial`), carga incremental (`--incremental`), persistencia del cursor después del upsert y registro de lotes y ejecuciones. La ingesta incremental se ejecuta antes del pronóstico.

## 7. Automatización en GitHub Actions

### Pronóstico y envío

[`forecast-submission.yml`](../.github/workflows/forecast-submission.yml) está activo en `main` y se ejecuta cada 10 minutos. Sincroniza observaciones, consulta `/v1/forecast-cycles/current`, termina sin enviar si no hay ciclo, carga el champion, valida y envía 48 predicciones con idempotencia. También permite acciones manuales `forecast`, `receipt` y `leaderboard`.

### Entrenamiento, evaluación y CI

[`train-and-promote.yml`](../.github/workflows/train-and-promote.yml) entrena candidatos y promueve solo si mejora. [`evaluate-and-monitor.yml`](../.github/workflows/evaluate-and-monitor.yml) consulta leaderboard y recibos. [`ci.yml`](../.github/workflows/ci.yml) instala dependencias y ejecuta pruebas. La verificación local más reciente fue de **13 pruebas exitosas**.

## 8. Entregas oficiales

La API aceptó una submission:

- Ciclo: `cyc_official-20260921_20260911T030000Z`
- Submission: `sub_f07f77f168144ea9a03f81fbb70ee99a`
- Estado: `accepted`
- Predicciones: 48/48
- Modelo: `hgb-champion-20260919T035232Z`

El leaderboard acumulado registró para **Juan Esteban Molina**: accuracy **3.45896 %**, accuracy@20 **3.92628 %**, WAPE **0.96645** y cobertura **7.69 %**. Estas métricas cambian conforme se liberan nuevos valores reales.

## 9. Variables y secretos

GitHub Actions usa las variables `PULSO_API_URL` y `SUPABASE_URL`, y los secrets `PULSO_API_KEY` y `SUPABASE_SERVICE_ROLE_KEY`. Nunca se deben subir `.env`, API keys, service-role keys ni tokens.

## 10. Correcciones importantes

- Se corrigió la importación del módulo `src` en CI.
- Se añadió `released_at` a `observations`.
- Se completaron intervalos faltantes de observaciones.
- Se separó entrenamiento de inferencia mediante un champion empaquetado.
- Se corrigió la clase `PulsoTransmiClient` en el evaluador (`fffcccf`).
- Se corrigió `PulsoTransMiError` en el cliente de submissions (`5af6ae7`).
- Se verificó la ejecución automática por `schedule` cada 10 minutos.

## 11. Verificación y operación

```bash
PYTHONPATH=. python -m pytest -q
python -m src.ingest --incremental
python -m src.pipeline
python -m src.pipeline --leaderboard cumulative
```

En GitHub Actions, `schedule` significa ejecución automática, `workflow_dispatch` manual, `no_open_cycle` significa que no había ciclo y `accepted` confirma un envío válido.

## 12. Próximos pasos

1. Mantener activo el workflow de pronóstico y revisar sus ejecuciones automáticas.
2. Confirmar una submission aceptada por cada ciclo nuevo.
3. Persistir en `evaluations` y `metric_snapshots` las métricas oficiales cuando la API exponga el ground truth.
4. Revisar periódicamente el champion y promover solo con evidencia de mejora.
