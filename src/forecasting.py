"""Feature construction and candidate model definitions for Pulso TransMi."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


HORIZONS = range(1, 5)
ORIGIN_LAG_STEPS = (0, 1, 4, 96, 672)
NUMERIC_FEATURES = [
    "lag_0", "lag_1", "lag_4", "lag_96", "lag_672", "target_lag_96",
    "rolling_mean_4", "rolling_mean_96", "time_sin", "time_cos",
    "weekday_sin", "weekday_cos", "is_weekend", "horizon_minutes",
]


def build_supervised(data: pd.DataFrame) -> pd.DataFrame:
    """Create supervised rows using only demand known at each forecast origin."""
    data = data.sort_values(["station_id", "observed_at"]).reset_index(drop=True).copy()
    data["observed_at"] = pd.to_datetime(data["observed_at"], utc=True)
    grouped = data.groupby("station_id", sort=False)["demand"]
    rows = []
    for steps in HORIZONS:
        frame = data[["station_id", "observed_at", "demand"]].copy()
        frame["horizon_steps"] = steps
        frame["forecast_origin"] = frame["observed_at"] - timedelta(minutes=15 * steps)
        for lag in ORIGIN_LAG_STEPS:
            frame[f"lag_{lag}"] = grouped.shift(steps + lag).to_numpy()
        frame["target_lag_96"] = grouped.shift(96).to_numpy()
        origin_series = grouped.shift(steps)
        for window in (4, 96):
            frame[f"rolling_mean_{window}"] = origin_series.groupby(frame["station_id"], sort=False).transform(
                lambda values: values.rolling(window, min_periods=window).mean()
            )
        minute_of_day = frame["observed_at"].dt.hour * 60 + frame["observed_at"].dt.minute
        day_of_week = frame["observed_at"].dt.dayofweek
        frame["time_sin"] = np.sin(2 * np.pi * minute_of_day / 1440)
        frame["time_cos"] = np.cos(2 * np.pi * minute_of_day / 1440)
        frame["weekday_sin"] = np.sin(2 * np.pi * day_of_week / 7)
        frame["weekday_cos"] = np.cos(2 * np.pi * day_of_week / 7)
        frame["is_weekend"] = (day_of_week >= 5).astype(int)
        frame["horizon_minutes"] = steps * 15
        rows.append(frame)
    result = pd.concat(rows, ignore_index=True)
    required = [f"lag_{lag}" for lag in ORIGIN_LAG_STEPS] + ["target_lag_96", "rolling_mean_4", "rolling_mean_96"]
    return result.dropna(subset=required).reset_index(drop=True)


def create_models() -> dict[str, object]:
    features = ColumnTransformer(
        [("numeric", StandardScaler(), NUMERIC_FEATURES),
         ("station", OneHotEncoder(handle_unknown="ignore"), ["station_id"])],
        sparse_threshold=0,
    )
    return {
        "ridge": make_pipeline(features, Ridge(alpha=10.0)),
        "hist_gradient_boosting": make_pipeline(
            features,
            HistGradientBoostingRegressor(
                max_iter=120, learning_rate=0.08, max_leaf_nodes=31,
                l2_regularization=1.0, random_state=42,
            ),
        ),
    }


def build_forecast_features(
    observations: pd.DataFrame, station_ids: list[str], data_cutoff: str | pd.Timestamp,
) -> pd.DataFrame:
    """Build 48 future rows for +15/+30/+45/+60m, requiring complete past data."""
    cutoff = pd.Timestamp(data_cutoff)
    cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    history = observations.copy()
    history["station_id"] = history["station_id"].astype("string")
    history["observed_at"] = pd.to_datetime(history["observed_at"], utc=True)
    history = history.loc[history["observed_at"].le(cutoff)].sort_values("observed_at")
    rows: list[dict[str, object]] = []

    for station_id in sorted(set(station_ids)):
        station = history.loc[history["station_id"].eq(station_id)].set_index("observed_at")["demand"]
        if cutoff not in station.index:
            raise ValueError(f"No observation exactly at data_cutoff for station {station_id}")
        for steps in HORIZONS:
            target_at = cutoff + timedelta(minutes=15 * steps)
            origin = target_at - timedelta(minutes=15 * steps)
            row: dict[str, object] = {
                "station_id": station_id,
                "observed_at": target_at,
                "forecast_origin": origin,
                "horizon_minutes": steps * 15,
            }
            for lag in ORIGIN_LAG_STEPS:
                source_at = target_at - timedelta(minutes=15 * (steps + lag))
                if source_at not in station.index:
                    raise ValueError(f"Missing lag-{lag} observation for station {station_id} at {source_at}")
                row[f"lag_{lag}"] = float(station.loc[source_at])
            target_lag_at = target_at - timedelta(minutes=15 * 96)
            if target_lag_at not in station.index:
                raise ValueError(f"Missing same-time-previous-day observation for station {station_id}")
            row["target_lag_96"] = float(station.loc[target_lag_at])
            for window in (4, 96):
                sample_times = [origin - timedelta(minutes=15 * offset) for offset in range(window - 1, -1, -1)]
                if any(timestamp not in station.index for timestamp in sample_times):
                    raise ValueError(f"Missing rolling-window-{window} history for station {station_id}")
                row[f"rolling_mean_{window}"] = float(station.loc[sample_times].mean())
            minute_of_day = target_at.hour * 60 + target_at.minute
            day_of_week = target_at.dayofweek
            row["time_sin"] = np.sin(2 * np.pi * minute_of_day / 1440)
            row["time_cos"] = np.cos(2 * np.pi * minute_of_day / 1440)
            row["weekday_sin"] = np.sin(2 * np.pi * day_of_week / 7)
            row["weekday_cos"] = np.cos(2 * np.pi * day_of_week / 7)
            row["is_weekend"] = int(day_of_week >= 5)
            rows.append(row)
    return pd.DataFrame(rows)
