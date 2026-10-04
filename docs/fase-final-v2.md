# Fase final: adaptación a observaciones v2

## Contrato y decisión de ingesta

La ingesta acepta páginas mixtas v1/v2 de `/v1/stream/observations`.

- v1: usa `demand` y se normaliza como `schema_version=1`, `quality=observed`.
- v2: convierte `measurement.value` de texto decimal a `demand` numérico.
- `quality=missing` conserva `demand=NULL`; nunca se convierte en cero.
- `released_at`, `schema_version` y `quality` quedan persistidos en `observations`.
- IDs y timestamps se normalizan antes del upsert idempotente por estación y timestamp.

La migración es [`20261004090000_support_observation_v2.sql`](../supabase/migrations/20261004090000_support_observation_v2.sql).

## Tratamiento de faltantes

Los faltantes se conservan para auditoría, pero se excluyen del conjunto de entrenamiento. Si dejan incompleto el historial necesario para generar los lags de un ciclo, el pipeline falla de forma segura y no envía una predicción inventada.

## Evidencia que debe registrarse

Para cada corrida de collector se deben conservar el cursor inicial/final, filas recibidas, versión de esquema, cantidad de faltantes, cobertura por estación y `released_at` máximo. Para cada entrenamiento se registra el rango temporal utilizado, filas observadas, filas faltantes excluidas, cutoff, commit, métrica de validación y modelo promovido.

La primera corrida posterior al cambio debe documentar: detección de v2, decisión de reparación, primer ciclo recuperado, submission ID, estado del recibo, cobertura y accuracy. El dashboard debe mostrar esa corrida junto con la evolución del drift.

## Criterio de adaptación

El reentrenamiento por drift continúa usando el accuracy `rolling_24h` personal. Si llega a 65 % o menos, actualiza la ingesta, excluye faltantes, entrena con datos observados, calibra sesgo reciente y solo promueve si mejora al champion en la misma ventana temporal.
