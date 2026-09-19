"""Train and temporally evaluate pooled candidate forecasting models."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from forecasting import build_supervised, create_models


ROOT = Path(__file__).resolve().parents[1]
def official_accuracy(frame: pd.DataFrame, prediction_column: str) -> float:
    error = (frame["demand"] - frame[prediction_column]).abs()
    wape = error.groupby(frame["station_id"]).sum() / frame["demand"].groupby(frame["station_id"]).sum()
    return float((100 * (1 - wape).clip(lower=0)).mean())


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
        "origin_feature_lags_intervals": [0, 1, 4, 96, 672],
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
