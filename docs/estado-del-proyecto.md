# Estado del proyecto Pulso TransMi

**Corte:** 5 de octubre de 2026
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

[`forecast-submission.yml`](../.github/workflows/forecast-submission.yml) quedó implementado y fue verificado en producción. Al cierre del proyecto, los workflows automáticos están **deshabilitados** para detener nuevos consumos; el código y la configuración permanecen versionados en `main`. Cuando se habilitan, sincronizan observaciones, consultan `/v1/forecast-cycles/current`, terminan sin enviar si no hay ciclo, cargan el champion, validan y envían 48 predicciones con idempotencia.

La migración [`20260924025600_add_external_forecast_scheduler.sql`](../supabase/migrations/20260924025600_add_external_forecast_scheduler.sql) habilita `pg_cron` y `pg_net`, crea una función privada y programa `dispatch-pulso-transmi-forecast` en los minutos `1, 6, 11, ...`. El token fine-grained de GitHub se lee cifrado desde Vault con el nombre `github_actions_token`; nunca se guarda en Git. El cron quedó detenido al cierre.

### Entrenamiento, evaluación y CI

[`train-and-promote.yml`](../.github/workflows/train-and-promote.yml) entrena candidatos y promueve solo si mejora. [`evaluate-and-monitor.yml`](../.github/workflows/evaluate-and-monitor.yml) consulta leaderboard y recibos. [`ci.yml`](../.github/workflows/ci.yml) instala dependencias y ejecuta pruebas. La verificación local más reciente fue de **30 pruebas exitosas**. Todos los workflows quedaron deshabilitados al cierre.

El reentrenamiento automático está controlado por
[`drift-triggered-retraining.yml`](../.github/workflows/drift-triggered-retraining.yml).
Cada hora realiza únicamente una consulta liviana del leaderboard `rolling_24h`.
Si el accuracy de Juan Esteban Molina es **65 % o menor**, sincroniza el stream,
exporta el histórico actualizado desde Supabase y reentrena los candidatos. Un
cooldown de 24 horas evita repetir entrenamiento mientras la métrica siga baja;
si cambia el commit de la lógica de entrenamiento, se permite una ejecución de
migración para que el nuevo calibrador llegue al champion.
El entrenamiento diario incondicional quedó desactivado; `train-and-promote.yml`
se conserva para ejecución manual. Antes de promover, candidato y champion se
comparan sobre la misma ventana reciente y se exige una mejora mínima de 0,10
puntos porcentuales.

Cuando se entrena por drift, cada candidato incorpora además una calibración
reciente por estación y horizonte: usa los últimos tres días previos a la
validación, aplica factores multiplicativos acotados entre 0,75 y 1,25 y los
guarda dentro del artefacto `.joblib`. La calibración no usa datos futuros y no
puede reemplazar al champion si no demuestra mejora en la ventana comparable.

## 8. Entrega final de la fase v2

La corrida [`37218595992`](https://github.com/molinaesteban111-dot/pulso-transmi/actions/runs/37218595992) recuperó la ingesta v2 y entregó el ciclo final:

- Ciclo: `cyc_official-20260921_20260921T060000Z`
- Submission: `sub_a469812d9f244ab483595004d6f3c13d`
- Estado: `accepted`
- Predicciones: `48/48`
- Registros v2 procesados: `816`
- Registros observados: `3.820`
- Faltantes conservados: `18`
- Registros inválidos: `0`
- Accuracy acumulado: `62.222901 %`
- Accuracy rolling 24h: `21.471029 %`
- Posición: `16`
- Cobertura: `91.625616 %`
- Drift: `-40.751873` puntos porcentuales

La ejecución de reentrenamiento [`37243469015`](https://github.com/molinaesteban111-dot/pulso-transmi/actions/runs/37243469015) terminó correctamente después de corregir los huecos: los targets faltantes se excluyen del entrenamiento y los valores imputados solo se usan como historial auxiliar para generar features.

## 9. Entregas oficiales históricas

La API ha aceptado **7 submissions y 336 predicciones**. La entrega más reciente es:

- Ciclo: `cyc_official-20260921_20260911T160000Z`
- Submission: `sub_b2201c55efa547978c4af9a049b8b2e7`
- Estado: `accepted`
- Predicciones: 48/48
- Modelo: `hgb-champion-20260919T035232Z`

El leaderboard acumulado registró para **Juan Esteban Molina**: accuracy **3.45896 %**, accuracy@20 **3.92628 %**, WAPE **0.96645** y cobertura **7.69 %**. Estas métricas cambian conforme se liberan nuevos valores reales.

## 10. Variables y secretos

GitHub Actions usa las variables `PULSO_API_URL` y `SUPABASE_URL`, y los secrets `PULSO_API_KEY` y `SUPABASE_SERVICE_ROLE_KEY`. Supabase Vault guarda `github_actions_token` cifrado y limitado al repositorio. Nunca se deben subir `.env`, API keys, service-role keys ni tokens.

## 11. Correcciones importantes

- Se corrigió la importación del módulo `src` en CI.
- Se añadió `released_at` a `observations`.
- Se completaron intervalos faltantes de observaciones.
- Se separó entrenamiento de inferencia mediante un champion empaquetado.
- Se corrigió la clase `PulsoTransmiClient` en el evaluador (`fffcccf`).
- Se corrigió `PulsoTransMiError` en el cliente de submissions (`5af6ae7`).
- Se añadió Supabase Cron como disparador externo confiable cada 5 minutos.
- Se verificaron dispatch automáticos reales (`35949663504` y `35950027778`): el primero devolvió `already_submitted` sin duplicar la entrega y el siguiente terminó correctamente con `no_open_cycle`.

## 12. Verificación y operación

```bash
PYTHONPATH=. python -m pytest -q
python -m src.ingest --incremental
python -m src.pipeline
python -m src.pipeline --leaderboard cumulative
```

En GitHub Actions, los runs `workflow_dispatch` pueden ser manuales o creados automáticamente por Supabase Cron. `no_open_cycle` significa que no había ciclo, `accepted` confirma un envío válido y `already_submitted` confirma que la idempotencia evitó un duplicado.

## 13. Cierre

El proyecto queda cerrado con los workflows automáticos y el cron detenidos. El repositorio conserva el código, la documentación, las migraciones, los reportes, las pruebas y la evidencia de la última entrega.
