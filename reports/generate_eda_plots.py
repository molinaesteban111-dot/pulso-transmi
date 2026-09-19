"""Genera las visualizaciones del EDA a partir de data/*.csv."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(exist_ok=True)

plt.style.use("seaborn-v0_8-whitegrid")

obs = pd.read_csv(DATA / "observations.csv", dtype={"station_id": "string"}, parse_dates=["observed_at"])
ctx = pd.read_csv(DATA / "context.csv", parse_dates=["observed_at"])
stations = pd.read_csv(DATA / "stations.csv", dtype={"station_id": "string"})

obs["hour"] = obs.observed_at.dt.hour + obs.observed_at.dt.minute / 60
obs["quarter_hour"] = obs.observed_at.dt.hour * 4 + obs.observed_at.dt.minute // 15
obs["weekday"] = obs.observed_at.dt.day_name()
weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def save(name: str) -> None:
    plt.tight_layout()
    plt.savefig(OUT / name, dpi=160, bbox_inches="tight")
    plt.close()


# 1. Distribución global de la demanda.
plt.figure(figsize=(9, 5))
plt.hist(obs["demand"], bins=50, color="#176b45", edgecolor="white")
plt.axvline(obs.demand.mean(), color="#d97706", linestyle="--", label=f"Media: {obs.demand.mean():.1f}")
plt.axvline(obs.demand.median(), color="#2563eb", linestyle="--", label=f"Mediana: {obs.demand.median():.1f}")
plt.title("Distribución de la demanda")
plt.xlabel("Pasajeros")
plt.ylabel("Frecuencia")
plt.legend()
save("01-distribucion-demanda.png")

# 2. Comparación entre estaciones.
means = obs.groupby("station_id").demand.mean().sort_values()
plt.figure(figsize=(9, 5))
plt.barh(means.index, means.values, color="#2f855a")
plt.title("Demanda promedio por estación")
plt.xlabel("Pasajeros promedio por observación")
plt.ylabel("Estación")
save("02-demanda-por-estacion.png")

# 3. Variabilidad por estación.
groups = [obs.loc[obs.station_id == station, "demand"] for station in means.index]
plt.figure(figsize=(11, 5))
plt.boxplot(groups, tick_labels=means.index, showfliers=False, patch_artist=True,
            boxprops={"facecolor": "#b7dfc8"}, medianprops={"color": "#b91c1c"})
plt.title("Variabilidad de demanda por estación")
plt.xlabel("Estación")
plt.ylabel("Pasajeros")
save("03-variabilidad-por-estacion.png")

# 4. Perfil intradía agregado.
hourly = obs.groupby("quarter_hour").demand.mean()
labels = [f"{int(q // 4):02d}:{int(q % 4) * 15:02d}" for q in hourly.index]
plt.figure(figsize=(12, 5))
plt.plot(labels, hourly.values, color="#176b45", linewidth=2)
plt.xticks(range(0, len(labels), 4), [labels[i] for i in range(0, len(labels), 4)], rotation=45)
plt.title("Perfil promedio de demanda durante el día")
plt.xlabel("Hora")
plt.ylabel("Pasajeros promedio")
save("04-estacionalidad-horaria.png")

# 5. Perfil por día de semana.
daily = obs.groupby("weekday").demand.mean().reindex(weekday_order)
plt.figure(figsize=(9, 5))
plt.bar(daily.index, daily.values, color=["#176b45"] * 5 + ["#d97706", "#2563eb"])
plt.title("Demanda promedio por día de semana")
plt.xlabel("Día")
plt.ylabel("Pasajeros promedio")
plt.xticks(rotation=25)
save("05-estacionalidad-semanal.png")

# 6. Serie temporal agregada y por estación.
series = obs.groupby("observed_at").demand.sum()
plt.figure(figsize=(13, 5))
plt.plot(series.index, series.values, color="#176b45", linewidth=0.8)
plt.title("Demanda total a lo largo del periodo observado")
plt.xlabel("Fecha")
plt.ylabel("Pasajeros agregados")
save("06-serie-temporal-total.png")

# 7. Contexto: distribuciones.
fig, axes = plt.subplots(1, 3, figsize=(14, 4))
for ax, column, color in zip(axes, ["rain_mm", "temperature_c", "event_intensity"], ["#2563eb", "#d97706", "#7c3aed"]):
    ax.hist(ctx[column], bins=30, color=color, alpha=0.85)
    ax.set_title(column)
    ax.set_xlabel("Valor")
    ax.set_ylabel("Frecuencia")
fig.suptitle("Distribución de variables de contexto")
save("07-distribuciones-contexto.png")

# 8. Correlaciones exploratorias con demanda.
merged = obs[["observed_at", "demand"]].merge(ctx, on="observed_at")
columns = ["rain_mm", "rain_forecast", "temperature_c", "temperature_forecast", "event_intensity"]
corr = merged[["demand", *columns]].corr(numeric_only=True).loc[columns, "demand"].sort_values()
plt.figure(figsize=(9, 5))
plt.barh(corr.index, corr.values, color=["#2563eb" if value < 0 else "#d97706" for value in corr.values])
plt.axvline(0, color="black", linewidth=0.8)
plt.title("Correlación lineal contemporánea con la demanda")
plt.xlabel("Correlación de Pearson")
save("08-correlaciones-contexto.png")

# 9. Control de completitud por estación.
coverage = obs.groupby("station_id").observed_at.nunique().sort_values()
plt.figure(figsize=(9, 5))
plt.barh(coverage.index, coverage.values, color="#2f855a")
plt.axvline(obs.observed_at.nunique(), color="#b91c1c", linestyle="--", label="Timestamps esperados")
plt.title("Cobertura temporal por estación")
plt.xlabel("Número de timestamps únicos")
plt.ylabel("Estación")
plt.legend()
save("09-cobertura-por-estacion.png")

print(f"Generadas {len(list(OUT.glob('*.png')))} figuras en {OUT}")
