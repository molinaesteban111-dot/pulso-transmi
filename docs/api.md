# API Pulso TransMi

La URL base pública es:

```text
https://pulso-transmi.72-60-245-2.sslip.io
```

## Paginación

`/v1/observations` y `/v1/context` devuelven como máximo 5.000 filas. Una
respuesta incluye `data`, `count` y `next_cursor`. Envía el cursor sin
modificarlo en la solicitud siguiente. `null` indica el final.

```python
cursor = None
while True:
    page = client.observations_page(cursor=cursor, limit=5000)
    process(page["data"])
    cursor = page["next_cursor"]
    if cursor is None:
        break
```

## Filtros

```text
GET /v1/observations?station_id=07107
GET /v1/observations?start=2026-08-01T00:00:00-05:00&limit=5000
GET /v1/context?start=2026-08-01T00:00:00-05:00
```

`start` y `end` son inclusivos y deben incluir zona horaria. Los IDs de estación
son texto: no elimines sus ceros iniciales.

## Descargas completas

```text
GET /v1/downloads/stations.csv
GET /v1/downloads/observations.csv
GET /v1/downloads/context.csv
GET /v1/downloads/metadata.json
```

El SDK verifica automáticamente el SHA-256 declarado en `/v1/meta`.

## Competencia y submissions

La API desplegada expone el stream y las rutas de competencia en Swagger (`/docs`):

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/v1/clock` | Estado y hora del servidor |
| `GET` | `/v1/forecast-cycles/current` | Consultar el ciclo abierto; sin ciclo responde 404 con `detail.code = no_open_cycle` |
| `GET` | `/v1/stream/observations` | Leer observaciones del stream con cursor |
| `POST` | `/v1/submissions` | Enviar los pronósticos de un ciclo |
| `GET` | `/v1/submissions/{submission_id}` | Consultar recibo |
| `GET` | `/v1/leaderboard?window=cumulative` | Consultar leaderboard acumulado o `rolling_24h` |

Las solicitudes de competencia deben incluir `Authorization: Bearer <PULSO_API_KEY>`.
El POST requiere además un `Idempotency-Key` de 8 a 128 caracteres. Reutiliza la
misma clave al reintentar el mismo envío; no generes un intento nuevo solo porque
hubo un timeout.

El cuerpo de submission usa `schema_version: "1.0"` e incluye `cycle_id`,
`client_run_id`, `data_cutoff`, `model` y `predictions`. Cada predicción contiene
`station_id` (texto de cinco dígitos), `target_at` con zona horaria y `value`
numérico no negativo. Para este reto se esperan 48 valores: 12 estaciones × 4
horizontes (+15, +30, +45 y +60 minutos). El objeto `model` registra `version`
y puede incluir `trained_at`, `training_data_end` y `git_commit`.

La submission envía predicciones, no el accuracy local: la evaluación oficial
se realiza con la realidad observada por el servidor. El ciclo abierto es la
fuente de `cycle_id` y `data_cutoff`; no derives esos valores del reloj local.
El pipeline del equipo falla de forma segura si la respuesta del ciclo no
incluye esos campos o si el histórico no llega completo hasta el cutoff.

## Errores

| Código | Significado |
|---:|---|
| 400 | Cursor inválido |
| 404 | Archivo o ruta inexistente |
| 422 | Parámetro inválido |
| 429 | Demasiadas solicitudes; espera antes de reintentar |
| 5xx | Falla temporal del servidor |
