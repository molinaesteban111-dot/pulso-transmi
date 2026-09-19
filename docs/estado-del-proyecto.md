# Estado y bitácora del proyecto Pulso TransMi

**Corte del documento:** 19 de septiembre de 2026

**Repositorio del equipo:** <https://github.com/molinaesteban111-dot/pulso-transmi>

**Repositorio de referencia/SDK:** <https://github.com/uexternadojz/pulso-transmi-sdk>  
**Curso:** MLOps · Ciencia de Datos

Este documento resume el trabajo realizado hasta ahora, separa lo que solicita la guía académica de lo implementado por el equipo y registra los bloqueos y próximos pasos. No sustituye la guía del profesor ni el contrato técnico vigente.

## 1. Objetivo académico

El proyecto consiste en construir un ciclo MLOps operativo para pronosticar la demanda de pasajeros en 12 estaciones de TransMilenio. No basta con entrenar un modelo una vez: el sistema debe ingestar datos, conservar trazabilidad, producir predicciones, evaluar sus errores, observar degradación y justificar decisiones de reentrenamiento.

La competencia requiere 48 predicciones por ciclo (12 estaciones × horizontes +15, +30, +45 y +60 minutos). Los workflows deben consultar la API para conocer el ciclo y su deadline; no deben asumirlos a partir del cron o del reloj local.

## 2. Trabajo realizado

### Repositorio y SDK

- Se clonó el starter kit oficial y se creó el repositorio del equipo `molinaesteban111-dot/pulso-transmi`.
- El repositorio local usa la rama `main` y apunta al repositorio del equipo, no al upstream del curso.
- Se conservó el SDK oficial para consultar la API, descargar datos y validar checksums.
- El repositorio del equipo está publicado en GitHub, rama `main`. El último commit verificado es `e061c38` (`Add forecast submission pipeline`).

### Datos y análisis exploratorio

- Se descargaron los CSV oficiales de estaciones, observaciones, contexto y metadatos al directorio local `data/`.
- Se analizó un histórico de 51.840 observaciones, 12 estaciones, 45 días y frecuencia de 15 minutos; contexto de 4.320 filas.
- En el corte explorado se halló cobertura completa, sin valores faltantes ni duplicados por estación y timestamp.
- Se documentaron patrones horarios y semanales, diferencias por estación, distribución de demanda y correlaciones exploratorias con variables contextuales.
- Se generó el informe `reports/eda.md`, nueve gráficas PNG en `reports/figures/` y el generador `reports/generate_eda_plots.py`.
- Se agregó `matplotlib` como dependencia opcional `.[eda]`.
- Se compararon dos baselines sin entrenamiento en validación temporal de los últimos 7 días: persistencia inmediata y naive estacional diario de 96 intervalos. Resultados y artefactos están en `reports/baselines.md` y archivos `reports/baseline_*`.
- Se entrenaron Ridge y HistGradientBoosting con rezagos calculados en cada origen, variables temporales y estación, comparándolos con los baselines en la misma ventana de 7 días. HistGradientBoosting logró 85,76 % de accuracy macro agregada de los cuatro horizontes, frente a 77,89 % del naive diario y 74,47 % de persistencia. Son candidatos; aún no se promovió un champion.
- Se amplió la evaluación a tres ventanas temporales consecutivas de siete días con entrenamiento expansivo. HistGradientBoosting conservó el primer lugar en cada ventana (85,76 %, 85,21 % y 85,44 %; promedio 85,47 %) y en cada horizonte. Queda recomendado para empaquetado como candidato, todavía no como champion productivo. Protocolo y resultados: `reports/backtesting-ventanas.md` y `reports/rolling_backtest_metrics.csv`.
- Se implementó `src/pipeline.py` y el workflow manual `forecast-submission.yml`: sincroniza el stream, consulta ciclos, entrena con datos de Supabase hasta el cutoff, valida las 48 predicciones, envía con Bearer e idempotencia, registra la ejecución/submission/predicciones y permite consultar recibos/leaderboard. Sin ciclo abierto, hace no-op. No se habilitó schedule.
- Los artefactos del backtest multiventana están versionados en GitHub: `reports/rolling_backtest_metrics.csv` (60 agregados por modelo, ventana, estación y horizonte) y `reports/rolling_backtest_predictions.csv.gz` (387.072 filas de predicciones de validación de cuatro métodos, con valores observados, origen y ventana). Son resultados históricos evaluados, no pronósticos futuros de una competencia.
- Se revisó el OpenAPI actualmente desplegado (v0.5.0). Expone `POST /v1/submissions`, `GET /v1/submissions/{submission_id}`, `GET /v1/leaderboard` y `GET /v1/portal/leaderboard`; no expone un endpoint documentado para subir CSV de backtest ni para reportar directamente el accuracy local. `POST /v1/submissions` requiere `cycle_id`, `data_cutoff`, trazabilidad del modelo y predicciones.
- Se configuraron en GitHub Actions los secretos `PULSO_API_KEY` y `SUPABASE_SERVICE_ROLE_KEY` (confirmado visualmente por el usuario para el primero y en la configuración compartida previamente para el segundo); `PULSO_API_URL` y `SUPABASE_URL` se usan como variables. Los valores secretos no se registran ni deben compartirse.
- El 19 de septiembre de 2026 se ejecutó manualmente `Pulso TransMi forecast submission` en la rama `main`, commit `e061c38`. El job tuvo estado **Success**: instaló el proyecto y completó la sincronización de observaciones. El paso de predicción devolvió `{"status":"no_open_cycle"}`. Por tanto, esa ejecución no entrenó ni envió pronósticos, no creó submission y no produjo recibo ni evaluación oficial.
- Se explicó que el API key autentica solicitudes, pero no determina por sí mismo el endpoint ni convierte las métricas del backtest en un payload válido de competencia. Queda pendiente pedir al profesor la ruta y el esquema específicos si requiere registrar métricas de backtest con la clave. Hasta recibir esa especificación, no se envían datos a una ruta inventada ni se mandan las predicciones de validación como si fueran predicciones futuras.

### Modelo de datos

- Se diseñó el diagrama Mermaid en `docs/modelo-entidad-relacion.md`.
- Incluye estaciones, observaciones, contexto, ejecuciones, lotes de ingesta, versiones de modelo, predicciones, submissions, evaluaciones, snapshots de métricas y transiciones del modelo.
- Se documentaron relaciones, claves, restricciones recomendadas y etapas de implementación.

### Supabase

- Se creó el proyecto **Pulso TransMi**, referencia `bppwpnpidjffhzojquml`, en la organización personal y región `sa-east-1`.
- El proyecto se verificó en estado `ACTIVE_HEALTHY`.
- Se aplicó una migración que creó las 11 tablas del modelo y sus relaciones, restricciones e índices.
- Se habilitó RLS en las tablas. No se añadieron políticas de acceso público; por tanto, el acceso desde clientes públicos permanece cerrado.
- Se verificó el esquema mediante el listado de tablas y el asesor de seguridad. El asesor indicó RLS habilitado sin políticas en las 11 tablas, deliberadamente mientras no se defina un modelo de acceso público.
- La base está creada, pero todavía no contiene el histórico del equipo: la carga inicial no se ha ejecutado.

### Ingesta y automatización

- Se implementó `src/ingest.py` para carga inicial (`--initial`) e ingesta incremental (`--incremental`).
- La carga inicial hace upsert de estaciones, contexto y observaciones para que pueda repetirse sin duplicar los registros identificados por sus claves naturales.
- La ruta incremental recupera el cursor confirmado de `ingestion_batches`, procesa observaciones y registra las ejecuciones/lotes. El cursor se registra después de que termina el upsert de observaciones.
- Se añadió `.github/workflows/ingestion.yml`, invocable manualmente con `initial` o `incremental`. El cron quedó comentado a la espera de la frecuencia que indique el profesor.
- Se configuró `SUPABASE_URL` como variable del repositorio de GitHub.
- Se añadieron pruebas en `tests/test_ingest.py`. Tras corregir la importación del módulo, las cinco pruebas locales pasaron; el workflow CI más reciente también aparece exitoso en GitHub.
- La clave `SUPABASE_SERVICE_ROLE_KEY` aún debe guardarse en GitHub Actions Secrets. No debe ponerse en el código, en archivos versionados ni en el chat.

## 3. Evidencia y archivos principales

| Propósito | Archivo |
|---|---|
| Análisis exploratorio | `reports/eda.md` |
| Baselines y backtest temporal | `reports/baselines.md` |
| Script del backtest | `examples/03_baseline_backtest.py` |
| Modelos candidatos y evaluación | [`reports/modelos.md`](../reports/modelos.md) |
| Entrenamiento reproducible | `examples/04_train_models.py` |
| Backtesting temporal multiventana | [`reports/backtesting-ventanas.md`](../reports/backtesting-ventanas.md), `reports/rolling_backtest_metrics.csv` y `reports/rolling_backtest_predictions.csv.gz` |
| Pipeline de predicción/submission | [`src/pipeline.py`](../src/pipeline.py) y [workflow manual](../.github/workflows/forecast-submission.yml) |
| Generación de gráficas | `reports/generate_eda_plots.py` |
| Gráficas del EDA | `reports/figures/*.png` |
| Diagrama entidad-relación | `docs/modelo-entidad-relacion.md` |
| Ingesta a Supabase | `src/ingest.py` |
| Workflow manual de ingesta | `.github/workflows/ingestion.yml` |
| Pruebas de ingesta | `tests/test_ingest.py` |
| Variables de entorno de ejemplo | `.env.example` |
| Guía técnica para estudiantes | `docs/student-project.md` |

## 4. Qué falta antes de continuar

1. Confirmar con el profesor si las métricas del backtest deben entregarse enlazando los artefactos del repositorio o cargándolas a un endpoint privado; si es lo último, solicitar ruta, esquema, autenticación y formato exactos. Los archivos ya están publicados en `reports/`.
2. Cuando haya un ciclo abierto, ejecutar **Actions → Pulso TransMi forecast submission → Run workflow → forecast**. Confirmar en el log un `submission_id` y recibo; después seleccionar `receipt` o `leaderboard` en una nueva ejecución para recuperar evaluación y posición oficial.
3. Verificar la carga de histórico a Supabase: 12 estaciones, 4.320 filas de contexto y 51.840 observaciones según el corte original. La documentación previa registra que la carga inicial estaba pendiente; confirmar el estado directamente en la base antes de asumir que se completó.
4. Revisar el modo incremental contra el contrato del profesor y añadir evaluación de accuracy/drift sobre predicciones resueltas.
5. Extender la validación temporal y analizar resultados por estación antes de promover un champion productivo.

## 5. Diferencia entre guía y decisiones implementadas

La guía del profesor es la autoridad para entregables, tiempos y reglas de competencia. El SDK aporta endpoints de lectura, ejemplos y plantillas. El EDA, el esquema detallado de Supabase y el módulo de ingesta son trabajo del equipo para cumplir esos objetivos.

Supabase se recomendó para la memoria operacional en la guía metodológica, mientras que el starter kit también describe Supabase como opción recomendada. Dashboard, MLflow y otras capacidades de visualización/versionamiento avanzado son bonos; no reemplazan los requisitos nucleares.

## 6. Seguridad y operación

- Nunca subir `SUPABASE_SERVICE_ROLE_KEY`, API keys de competencia, contraseñas ni tokens.
- Mantener RLS habilitado. Antes de exponer tablas a `anon` o `authenticated`, definir políticas que correspondan al uso previsto y verificar los grants de Data API.
- No desplegar horarios competitivos hasta que el profesor confirme la frecuencia y el contrato vigente.
- Cada carga e inferencia debe conservar commit, cutoff, versión del modelo, errores y evidencia operacional.

## 7. Historial reciente de cambios

| Commit | Cambio |
|---|---|
| `c89a775` | Primer EDA escrito y diagrama entidad-relación |
| `8c58eaa` | Gráficas del EDA y generador reproducible |
| `26f84b6` | Módulo de ingesta, pruebas iniciales y workflow de GitHub Actions |
| `47690a7` | Corrección del import de ingesta; CI verificado exitosamente |
| `2b1b97d` | Baselines y resultados del backtest rolling |
| `e061c38` | Pipeline de pronóstico/submission, cliente API, workflow manual y pruebas (13 aprobadas) |

## 8. Comandos útiles

```bash
# Ejecutar pruebas
python -m pip install -e '.[dev]'
python -m pytest -q

# Regenerar gráficas del EDA
python -m pip install -e '.[eda]'
python reports/generate_eda_plots.py

# Ejecutar ingesta desde un entorno que ya tenga las credenciales configuradas
python -m src.ingest --initial
python -m src.ingest --incremental
```
