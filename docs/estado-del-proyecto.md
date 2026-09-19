# Estado y bitácora del proyecto Pulso TransMi

**Corte del documento:** 18 de septiembre de 2026  
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
- El último estado conocido está sincronizado con `origin/main` en el commit `47690a7`.

### Datos y análisis exploratorio

- Se descargaron los CSV oficiales de estaciones, observaciones, contexto y metadatos al directorio local `data/`.
- Se analizó un histórico de 51.840 observaciones, 12 estaciones, 45 días y frecuencia de 15 minutos; contexto de 4.320 filas.
- En el corte explorado se halló cobertura completa, sin valores faltantes ni duplicados por estación y timestamp.
- Se documentaron patrones horarios y semanales, diferencias por estación, distribución de demanda y correlaciones exploratorias con variables contextuales.
- Se generó el informe `reports/eda.md`, nueve gráficas PNG en `reports/figures/` y el generador `reports/generate_eda_plots.py`.
- Se agregó `matplotlib` como dependencia opcional `.[eda]`.

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
| Generación de gráficas | `reports/generate_eda_plots.py` |
| Gráficas del EDA | `reports/figures/*.png` |
| Diagrama entidad-relación | `docs/modelo-entidad-relacion.md` |
| Ingesta a Supabase | `src/ingest.py` |
| Workflow manual de ingesta | `.github/workflows/ingestion.yml` |
| Pruebas de ingesta | `tests/test_ingest.py` |
| Variables de entorno de ejemplo | `.env.example` |
| Guía técnica para estudiantes | `docs/student-project.md` |

## 4. Qué falta antes de continuar

1. Crear en Supabase una clave secreta de servidor o recuperar la `service_role` desde **Project Settings → API Keys**. No usar `anon` ni `sb_publishable_...` para la carga.
2. Guardar la clave en GitHub: **Settings → Secrets and variables → Actions → New repository secret**, con el nombre exacto `SUPABASE_SERVICE_ROLE_KEY`.
3. Ejecutar manualmente **Actions → Pulso TransMi ingestion → Run workflow → initial**.
4. Verificar en Supabase que se cargaron 12 estaciones, 4.320 filas de contexto y 51.840 observaciones, y comprobar que una segunda carga inicial no produce duplicados.
5. Revisar y probar el modo incremental. El stream competitivo y sus endpoints/cursor deben contrastarse con el contrato técnico que publique el profesor; el actual modo incremental es una primera implementación basada en paginación de observaciones de lectura.
6. Construir y comparar al menos dos baselines mediante validación temporal, por ejemplo persistencia inmediata y rezago estacional de 96 intervalos.
7. Definir versiones y promoción del modelo champion, y luego implementar la inferencia/submission de acuerdo con el contrato competitivo definitivo.
8. Añadir evaluación de accuracy y señales de drift sobre predicciones resueltas.

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
