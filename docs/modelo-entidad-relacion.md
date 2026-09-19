# Modelo entidad-relación — Pulso TransMi

Este modelo representa la memoria operacional recomendada para Supabase/PostgreSQL. Separa los datos observados, la operación del pipeline, los modelos y la evaluación de predicciones.

## Diagrama

```mermaid
erDiagram
    STATIONS ||--o{ OBSERVATIONS : "tiene"
    OBSERVATIONS }o--|| CONTEXT : "ocurre en"
    PIPELINE_RUNS ||--o{ INGESTION_BATCHES : "ejecuta"
    INGESTION_BATCHES ||--o{ OBSERVATIONS : "incorpora"
    MODEL_VERSIONS ||--o{ PREDICTIONS : "produce"
    PIPELINE_RUNS ||--o{ PREDICTIONS : "genera"
    PREDICTIONS }o--|| STATIONS : "corresponde a"
    SUBMISSIONS ||--o{ PREDICTIONS : "contiene"
    SUBMISSIONS ||--o{ EVALUATIONS : "se evalua con"
    PREDICTIONS ||--o{ EVALUATIONS : "recibe resultado"
    OBSERVATIONS ||--o{ EVALUATIONS : "aporta realidad"
    MODEL_VERSIONS ||--o{ MODEL_TRANSITIONS : "origen"
    MODEL_VERSIONS ||--o{ MODEL_TRANSITIONS : "destino"
    PIPELINE_RUNS ||--o{ METRIC_SNAPSHOTS : "calcula"
    MODEL_VERSIONS ||--o{ METRIC_SNAPSHOTS : "mide"

    STATIONS {
        text station_id PK
        text station_name
        text corridor
        numeric latitude
        numeric longitude
        timestamptz created_at
    }

    OBSERVATIONS {
        bigint observation_id PK
        text station_id FK
        timestamptz observed_at UK
        numeric demand
        bigint ingestion_batch_id FK
        timestamptz loaded_at
    }

    CONTEXT {
        bigint context_id PK
        timestamptz observed_at UK
        numeric rain_mm
        numeric rain_forecast
        numeric temperature_c
        numeric temperature_forecast
        numeric event_intensity
    }

    PIPELINE_RUNS {
        uuid run_id PK
        text run_type
        text git_commit
        timestamptz started_at
        timestamptz finished_at
        text status
        text error_message
    }

    INGESTION_BATCHES {
        bigint ingestion_batch_id PK
        uuid run_id FK
        text source_cursor
        text next_cursor
        int rows_received
        timestamptz source_cutoff
        timestamptz ingested_at
        text status
    }

    MODEL_VERSIONS {
        uuid model_version_id PK
        text version_name UK
        text status
        text algorithm
        jsonb features
        timestamptz training_cutoff
        text git_commit
        numeric validation_accuracy
        text artifact_uri
        timestamptz created_at
    }

    PREDICTIONS {
        bigint prediction_id PK
        uuid run_id FK
        uuid model_version_id FK
        text station_id FK
        timestamptz cycle_origin
        timestamptz target_at
        numeric prediction
        timestamptz emitted_at
        text idempotency_key
    }

    SUBMISSIONS {
        uuid submission_id PK
        text external_submission_id
        text cycle_id
        uuid run_id FK
        text idempotency_key UK
        int prediction_count
        timestamptz submitted_at
        text status
        jsonb receipt
    }

    EVALUATIONS {
        bigint evaluation_id PK
        uuid submission_id FK
        bigint prediction_id FK
        bigint observation_id FK
        numeric absolute_error
        numeric wape_component
        numeric accuracy
        timestamptz evaluated_at
    }

    METRIC_SNAPSHOTS {
        bigint metric_snapshot_id PK
        uuid run_id FK
        uuid model_version_id FK
        text metric_scope
        text station_id FK
        text horizon
        numeric wape
        numeric accuracy
        numeric coverage
        numeric drift_score
        timestamptz window_start
        timestamptz window_end
        timestamptz calculated_at
    }

    MODEL_TRANSITIONS {
        bigint transition_id PK
        uuid from_model_version_id FK
        uuid to_model_version_id FK
        uuid run_id FK
        text reason
        numeric previous_accuracy
        numeric new_accuracy
        timestamptz transitioned_at
    }
```

## Relaciones principales

| Relación | Cardinalidad | Propósito |
|---|---:|---|
| `stations` → `observations` | 1:N | Una estación tiene muchas observaciones temporales. |
| `observations` ↔ `context` | N:1 por `observed_at` | La demanda se relaciona con el contexto disponible en el mismo instante. |
| `pipeline_runs` → `ingestion_batches` | 1:N | Una ejecución puede procesar uno o varios lotes paginados. |
| `model_versions` → `predictions` | 1:N | Cada predicción debe identificar el modelo que la produjo. |
| `submissions` → `predictions` | 1:N | Una submission agrupa las predicciones de un ciclo. |
| `predictions` → `evaluations` | 1:0..1 o 1:N | Una predicción puede evaluarse cuando aparece la realidad; la evaluación puede ser progresiva. |
| `model_versions` → `model_transitions` | 1:N | Permite reconstruir cuándo y por qué un modelo pasó a ser champion o fue reemplazado. |
| `metric_snapshots` → modelo/estación/horizonte | N:1 | Conserva accuracy, cobertura y drift a lo largo del tiempo. |

## Restricciones recomendadas

```sql
-- No duplicar una observación de una estación en el mismo instante.
UNIQUE (station_id, observed_at)

-- No duplicar el mismo intento lógico de submission.
UNIQUE (idempotency_key)

-- Una predicción debe ser única por modelo, estación, ciclo y objetivo.
UNIQUE (model_version_id, station_id, cycle_origin, target_at)

-- La demanda no puede ser negativa.
CHECK (demand >= 0)

-- Una predicción enviada debe ser finita y no negativa.
CHECK (prediction >= 0)
```

## Notas de implementación

- `station_id` debe almacenarse como `text`, porque la documentación de la API exige conservar ceros iniciales.
- `source_cursor` y `next_cursor` deben guardarse sin modificarlos. El cursor solo se confirma después de completar el `upsert` del lote.
- `model_versions` debe guardar el `artifact_uri` de Supabase Storage; nunca se debe cargar simplemente “el archivo más reciente”.
- `pipeline_runs` registra también las ejecuciones sin novedades y las fallidas.
- La API key y las credenciales de Supabase no pertenecen a ninguna tabla: deben permanecer en GitHub Actions Secrets.
- El modelo permite consultar tanto el desempeño acumulado como el rolling de 24 horas mediante `metric_snapshots`.

## Prioridad de construcción

### Mínimo inicial

`stations`, `observations`, `context`, `pipeline_runs`, `ingestion_batches`, `model_versions` y `predictions`.

### Operación competitiva

Agregar `submissions`, `evaluations` y `metric_snapshots`.

### Trazabilidad avanzada

Agregar `model_transitions`, rollback y auditoría detallada de decisiones.
