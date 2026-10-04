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


def complete_observation_grid(data: pd.DataFrame) -> pd.DataFrame:
    """Complete 15-minute history for feature construction without fake targets.

    Missing source values are linearly interpolated only for lag/history
    features. Rows whose actual target was missing remain marked as missing and
    are removed from supervised training/validation.
    """
    source = data.copy()
    source["station_id"] = source["station_id"].astype("string")
    source["observed_at"] = pd.to_datetime(source["observed_at"], utc=True)
    source["demand"] = pd.to_numeric(source["demand"], errors="coerce")
    if "quality" not in source:
        source["quality"] = np.where(source["demand"].notna(), "observed", "missing")
    source["quality"] = source["quality"].fillna("observed")
    frames = []
    for station_id, group in source.groupby("station_id", sort=True):
        group = group.sort_values("observed_at").drop_duplicates("observed_at", keep="last")
        index = pd.date_range(group.observed_at.min(), group.observed_at.max(), freq="15min", tz="UTC")
        frame = group.set_index("observed_at").reindex(index)
        frame["station_id"] = station_id
        frame["quality"] = frame["quality"].fillna("missing")
        frame["demand"] = frame["demand"].interpolate(method="time", limit_direction="both")
        frames.append(frame.reset_index(names="observed_at"))
    return pd.concat(frames, ignore_index=True).sort_values(["station_id", "observed_at"]).reset_index(drop=True)


class CalibratedForecastModel:
    """Apply a bounded recent bias correction to a fitted forecasting model."""

    def __init__(
        self,
        model: object,
        factors: dict[str, float],
        default_factor: float = 1.0,
    ) -> None:
        self.model = model
        self.factors = factors
        self.default_factor = default_factor

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        prediction = np.asarray(self.model.predict(frame), dtype=float)
        keys = (
            frame["station_id"].astype(str)
            + "|"
            + frame["horizon_minutes"].astype(str)
        )
        factors = keys.map(self.factors).fillna(self.default_factor).to_numpy()
        return prediction * factors


def fit_calibrated_model(
    model: object,
    frame: pd.DataFrame,
    target: pd.Series,
    calibration_days: int = 3,
    min_samples: int = 8,
    lower_factor: float = 0.75,
    upper_factor: float = 1.25,
) -> CalibratedForecastModel:
    """Fit a model and calibrate recent multiplicative bias without future data.

    The final model is fitted on all supplied rows, but calibration factors are
    estimated from a recent holdout that precedes the rows used for evaluation.
    Factors are shrunk toward 1.0 and bounded because the official metric is
    WAPE-based and an unconstrained correction could amplify noise.
    """
    if calibration_days < 1:
        raise ValueError("calibration_days must be positive")
    if frame.empty:
        raise ValueError("Cannot fit a calibrated model on an empty frame")

    timestamps = pd.to_datetime(frame["observed_at"], utc=True)
    cutoff = timestamps.max() - timedelta(days=calibration_days)
    calibration = frame.loc[timestamps.gt(cutoff)].copy()
    core = frame.loc[timestamps.le(cutoff)].copy()
    if core.empty or calibration.empty:
        model.fit(frame, target)
        return CalibratedForecastModel(model, {})

    core_target = target.loc[core.index]
    model.fit(core, core_target)
    calibration_prediction = np.maximum(0.0, model.predict(calibration))
    calibration = calibration.assign(
        _prediction=calibration_prediction,
        _target=target.loc[calibration.index].to_numpy(),
    )
    factors: dict[str, float] = {}
    for (station_id, horizon), group in calibration.groupby(
        ["station_id", "horizon_minutes"], sort=False
    ):
        if len(group) < min_samples or group["_prediction"].sum() <= 0:
            continue
        # Add a small unit-scale prior so sparse groups remain near 1.0.
        factor = (group["_target"].sum() + group["_prediction"].sum()) / (
            2 * group["_prediction"].sum()
        )
        factors[f"{station_id}|{int(horizon)}"] = float(
            np.clip(factor, lower_factor, upper_factor)
        )

    # Refit the underlying model with all rows; factors came only from the
    # recent pre-evaluation holdout, so the evaluation remains temporal.
    model.fit(frame, target)
    return CalibratedForecastModel(model, factors)


def build_supervised(data: pd.DataFrame) -> pd.DataFrame:
    """Create supervised rows using only demand known at each forecast origin."""
    data = data.copy()
    if "quality" not in data:
        data["quality"] = np.where(data["demand"].notna(), "observed", "missing")
    data = data.sort_values(["station_id", "observed_at"]).reset_index(drop=True).copy()
    data["observed_at"] = pd.to_datetime(data["observed_at"], utc=True)
    grouped = data.groupby("station_id", sort=False)["demand"]
    rows = []
    for steps in HORIZONS:
        frame = data[["station_id", "observed_at", "demand", "quality"]].copy()
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
    return result.loc[result["quality"].eq("observed")].dropna(subset=required + ["demand"]).reset_index(drop=True)


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
