"""Evaluate candidate forecasters on consecutive expanding-window backtests."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from importlib.util import module_from_spec, spec_from_file_location


ROOT = Path(__file__).resolve().parents[1]
_SPEC = spec_from_file_location("train_models", ROOT / "examples" / "04_train_models.py")
_TRAINING = module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_TRAINING)


def summarize(frame: pd.DataFrame) -> dict[str, float]:
    errors = (frame["demand"] - frame["prediction"]).abs()
    station_wape = errors.groupby(frame["station_id"]).sum() / frame["demand"].groupby(frame["station_id"]).sum()
    return {
        "accuracy_macro_station_pct": float((100 * (1 - station_wape).clip(lower=0)).mean()),
        "wape_all_rows_pct": float(100 * errors.sum() / frame["demand"].sum()),
        "mae": float(errors.mean()),
    }


def run(data_path: Path, windows: int = 3, validation_days: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    observations = pd.read_csv(data_path, dtype={"station_id": "string"}, parse_dates=["observed_at"])
    observations = observations.sort_values(["station_id", "observed_at"]).reset_index(drop=True)
    observations["observed_at"] = pd.to_datetime(observations["observed_at"], utc=True)
    coverage = observations.groupby("station_id")["observed_at"].agg(["min", "max", "count"])
    expected = ((coverage["max"] - coverage["min"]).dt.total_seconds() / 900).astype(int) + 1
    if not coverage["count"].eq(expected).all() or observations.duplicated(["station_id", "observed_at"]).any():
        raise ValueError("Expected complete, duplicate-free 15-minute observations per station")

    supervised = _TRAINING.build_supervised(observations)
    last_time = observations["observed_at"].max()
    metric_rows: list[dict[str, object]] = []
    prediction_rows: list[pd.DataFrame] = []
    model_names = ("persistence", "seasonal_naive_96", "ridge", "hist_gradient_boosting")

    for window_index in range(windows, 0, -1):
        end = last_time - timedelta(days=(window_index - 1) * validation_days)
        start = end - timedelta(days=validation_days)
        train = supervised.loc[supervised["observed_at"].le(start)]
        validation = supervised.loc[supervised["observed_at"].gt(start) & supervised["observed_at"].le(end)]
        if train.empty or validation.empty:
            raise ValueError(f"Insufficient data for validation window ending {end}")

        split = validation[["station_id", "observed_at", "forecast_origin", "horizon_minutes", "demand"]].copy()
        split["window"] = window_index
        split["validation_start_exclusive_utc"] = str(start)
        split["validation_end_inclusive_utc"] = str(end)
        split["training_rows"] = len(train)

        persistence = validation["lag_0"].to_numpy()
        seasonal = validation["target_lag_96"].to_numpy()
        for name, values in (("persistence", persistence), ("seasonal_naive_96", seasonal)):
            frame = split.copy()
            frame["model"] = name
            frame["prediction"] = values
            prediction_rows.append(frame)

        for name, model in _TRAINING.create_models().items():
            model.fit(train, train["demand"])
            frame = split.copy()
            frame["model"] = name
            frame["prediction"] = np.maximum(0, model.predict(validation))
            prediction_rows.append(frame)

    predictions = pd.concat(prediction_rows, ignore_index=True)
    for (window, model_name, horizon), frame in predictions.groupby(["window", "model", "horizon_minutes"], sort=True):
        metric_rows.append({
            "window": int(window), "model": model_name, "horizon_minutes": int(horizon),
            "n_predictions": len(frame), **summarize(frame),
        })
    for (window, model_name), frame in predictions.groupby(["window", "model"], sort=True):
        metric_rows.append({
            "window": int(window), "model": model_name, "horizon_minutes": 0,
            "n_predictions": len(frame), **summarize(frame),
        })
    return pd.DataFrame(metric_rows), predictions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "observations.csv")
    parser.add_argument("--windows", type=int, default=3)
    parser.add_argument("--validation-days", type=int, default=7)
    args = parser.parse_args()
    if args.windows < 2 or args.validation_days < 1:
        parser.error("--windows must be at least 2 and --validation-days must be positive")

    metrics, predictions = run(args.data, args.windows, args.validation_days)
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    metrics.to_csv(reports / "rolling_backtest_metrics.csv", index=False, float_format="%.6f")
    predictions.to_csv(reports / "rolling_backtest_predictions.csv.gz", index=False, compression="gzip")
    summary = metrics.loc[metrics.horizon_minutes.eq(0)].pivot(index="window", columns="model", values="accuracy_macro_station_pct")
    print("Accuracy macro por estación; horizon_minutes=0 agrega los cuatro horizontes")
    print(summary.to_string(float_format=lambda value: f"{value:.3f}%"))
    print(f"\nMétricas: {reports / 'rolling_backtest_metrics.csv'}")
    print(f"Predicciones: {reports / 'rolling_backtest_predictions.csv.gz'}")


if __name__ == "__main__":
    main()
