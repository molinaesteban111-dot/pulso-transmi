"""Train and temporally evaluate pooled candidate forecasting models."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parents[1]
HORIZONS = range(1, 5)
ORIGIN_LAG_STEPS = (0, 1, 4, 96, 672)


def build_supervised(data: pd.DataFrame) -> pd.DataFrame:
    """Create one row per target/horizon using features known at forecast origin."""
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
        # Same target time on the previous day. It is known at origin for h<=60m.
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
    feature_columns = [f"lag_{lag}" for lag in ORIGIN_LAG_STEPS] + ["target_lag_96", "rolling_mean_4", "rolling_mean_96"]
    return result.dropna(subset=feature_columns).reset_index(drop=True)


def official_accuracy(frame: pd.DataFrame, prediction_column: str) -> float:
    error = (frame["demand"] - frame[prediction_column]).abs()
    wape = error.groupby(frame["station_id"]).sum() / frame["demand"].groupby(frame["station_id"]).sum()
    return float((100 * (1 - wape).clip(lower=0)).mean())


def create_models() -> dict[str, object]:
    numeric = [
        "lag_0", "lag_1", "lag_4", "lag_96", "lag_672", "target_lag_96", "rolling_mean_4", "rolling_mean_96",
        "time_sin", "time_cos", "weekday_sin", "weekday_cos", "is_weekend", "horizon_minutes",
    ]
    features = ColumnTransformer(
        [("numeric", StandardScaler(), numeric), ("station", OneHotEncoder(handle_unknown="ignore"), ["station_id"])],
        sparse_threshold=0,
    )
    return {
        "ridge": make_pipeline(features, Ridge(alpha=10.0)),
        "hist_gradient_boosting": make_pipeline(
            features,
            HistGradientBoostingRegressor(max_iter=120, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0, random_state=42),
        ),
    }


def run(data_path: Path, validation_days: int = 7) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object], dict[str, object]]:
    observations = pd.read_csv(data_path, dtype={"station_id": "string"}, parse_dates=["observed_at"])
    observations = observations.sort_values(["station_id", "observed_at"]).reset_index(drop=True)
    observations["observed_at"] = pd.to_datetime(observations["observed_at"], utc=True)
    expected = observations.groupby("station_id")["observed_at"].agg(["min", "max", "count"])
    expected_count = ((expected["max"] - expected["min"]).dt.total_seconds() / 900).astype(int) + 1
    if not expected["count"].eq(expected_count).all() or observations.duplicated(["station_id", "observed_at"]).any():
        raise ValueError("Expected a duplicate-free, complete 15-minute grid per station")

    cutoff = observations["observed_at"].max() - timedelta(days=validation_days)
    supervised = build_supervised(observations)
    train = supervised.loc[supervised["observed_at"].le(cutoff)].copy()
    validation = supervised.loc[supervised["observed_at"].gt(cutoff)].copy()
    if train.empty or validation.empty:
        raise ValueError("Not enough data for the requested temporal split")

    candidates = create_models()
    prediction_frames = []
    metric_rows = []
    baseline_columns = {"persistence": "lag_0", "seasonal_naive_96": "target_lag_96"}
    for name, column in baseline_columns.items():
        baseline = validation[["station_id", "observed_at", "forecast_origin", "horizon_minutes", "demand", column]].copy()
        baseline = baseline.rename(columns={column: "prediction"})
        baseline["model"] = name
        prediction_frames.append(baseline)

    for name, model in candidates.items():
        model.fit(train, train["demand"])
        prediction = np.maximum(0, model.predict(validation))
        predicted = validation[["station_id", "observed_at", "forecast_origin", "horizon_minutes", "demand"]].copy()
        predicted["prediction"] = prediction
        predicted["model"] = name
        prediction_frames.append(predicted)
        model_dir = ROOT / "artifacts" / "candidates"
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, model_dir / f"{name}.joblib")

    all_predictions = pd.concat(prediction_frames, ignore_index=True)
    for (model_name, horizon), subset in all_predictions.groupby(["model", "horizon_minutes"], sort=True):
        metric_rows.append({
            "model": model_name,
            "horizon_minutes": int(horizon),
            "station_id": "ALL",
            "n_predictions": len(subset),
            "accuracy_macro_station_pct": official_accuracy(subset, "prediction"),
            "wape_all_rows_pct": 100 * (subset.demand - subset.prediction).abs().sum() / subset.demand.sum(),
            "mae": (subset.demand - subset.prediction).abs().mean(),
        })
        for station, station_rows in subset.groupby("station_id", sort=True):
            station_wape = (station_rows.demand - station_rows.prediction).abs().sum() / station_rows.demand.sum()
            metric_rows.append({
                "model": model_name,
                "horizon_minutes": int(horizon),
                "station_id": station,
                "n_predictions": len(station_rows),
                "accuracy_macro_station_pct": max(0.0, 100 * (1 - station_wape)),
                "wape_all_rows_pct": 100 * station_wape,
                "mae": (station_rows.demand - station_rows.prediction).abs().mean(),
            })

    for model_name, subset in all_predictions.groupby("model", sort=True):
        station_wape = (subset.demand - subset.prediction).abs().groupby(subset.station_id).sum() / subset.demand.groupby(subset.station_id).sum()
        metric_rows.append({
            "model": model_name,
            "horizon_minutes": 0,
            "station_id": "ALL",
            "n_predictions": len(subset),
            "accuracy_macro_station_pct": (100 * (1 - station_wape).clip(lower=0)).mean(),
            "wape_all_rows_pct": 100 * (subset.demand - subset.prediction).abs().sum() / subset.demand.sum(),
            "mae": (subset.demand - subset.prediction).abs().mean(),
        })
        for station, station_rows in subset.groupby("station_id", sort=True):
            station_wape_value = (station_rows.demand - station_rows.prediction).abs().sum() / station_rows.demand.sum()
            metric_rows.append({
                "model": model_name,
                "horizon_minutes": 0,
                "station_id": station,
                "n_predictions": len(station_rows),
                "accuracy_macro_station_pct": max(0.0, 100 * (1 - station_wape_value)),
                "wape_all_rows_pct": 100 * station_wape_value,
                "mae": (station_rows.demand - station_rows.prediction).abs().mean(),
            })

    metrics = pd.DataFrame(metric_rows)
    metadata = {
        "validation_start_exclusive_utc": str(cutoff),
        "validation_end_inclusive_utc": str(observations.observed_at.max()),
        "training_rows": int(len(train)),
        "validation_rows": int(len(validation)),
        "origin_feature_lags_intervals": list(ORIGIN_LAG_STEPS),
        "target_same_time_previous_day_lag_intervals": 96,
        "features": "past demand lags/rolling means, cyclic time/day, weekend, station one-hot, horizon; no future context",
        "candidates": {
            "ridge": {"alpha": 10.0},
            "hist_gradient_boosting": {"max_iter": 120, "learning_rate": 0.08, "max_leaf_nodes": 31, "l2_regularization": 1.0, "random_state": 42},
        },
    }
    return metrics, all_predictions, metadata, candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "observations.csv")
    parser.add_argument("--validation-days", type=int, default=7)
    args = parser.parse_args()
    if args.validation_days < 1:
        parser.error("--validation-days must be positive")
    metrics, predictions, metadata, _ = run(args.data, args.validation_days)
    report_dir = ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    metrics.to_csv(report_dir / "model_metrics.csv", index=False, float_format="%.6f")
    predictions.to_csv(report_dir / "model_predictions.csv", index=False)
    (report_dir / "model_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    summary = metrics.loc[metrics.station_id.eq("ALL"), ["model", "horizon_minutes", "n_predictions", "accuracy_macro_station_pct", "wape_all_rows_pct", "mae"]]
    print(f"Entrenamiento: {metadata['training_rows']:,} filas; validación desde {metadata['validation_start_exclusive_utc']}")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"\nMétricas: {report_dir / 'model_metrics.csv'}")
    print("Artefactos candidatos locales: artifacts/candidates/ (aún no promovidos)")


if __name__ == "__main__":
    main()
