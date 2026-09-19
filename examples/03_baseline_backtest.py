"""Temporal backtest of two no-training forecasting baselines."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def score(frame: pd.DataFrame, prediction_column: str) -> dict[str, float]:
    absolute_error = (frame["demand"] - frame[prediction_column]).abs()
    wape_by_station = absolute_error.groupby(frame["station_id"]).sum() / frame["demand"].groupby(frame["station_id"]).sum()
    accuracy_by_station = (100 * (1 - wape_by_station).clip(lower=0)).mean()
    total_wape = absolute_error.sum() / frame["demand"].sum()
    return {"accuracy_macro_station_pct": float(accuracy_by_station), "wape_all_rows_pct": float(100 * total_wape), "mae": float(absolute_error.mean())}


def station_score(frame: pd.DataFrame, prediction_column: str) -> pd.DataFrame:
    scored = frame.assign(absolute_error=(frame["demand"] - frame[prediction_column]).abs())
    grouped = scored.groupby("station_id", observed=True).agg(
        absolute_error=("absolute_error", "sum"),
        total_demand=("demand", "sum"),
        mae=("absolute_error", "mean"),
        n_predictions=("demand", "size"),
    )
    grouped["wape_all_rows_pct"] = 100 * grouped["absolute_error"] / grouped["total_demand"]
    grouped["accuracy_macro_station_pct"] = (100 - grouped["wape_all_rows_pct"]).clip(lower=0)
    return grouped.reset_index()


def run_backtest(data_path: Path, validation_days: int = 7) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    data = pd.read_csv(data_path, dtype={"station_id": "string"}, parse_dates=["observed_at"])
    data = data.sort_values(["station_id", "observed_at"]).reset_index(drop=True)
    data["observed_at"] = pd.to_datetime(data["observed_at"], utc=True)

    # Ensure a complete regular grid before interpreting row shifts as 15-minute lags.
    expected = data.groupby("station_id")["observed_at"].agg(["min", "max", "count"])
    expected_count = ((expected["max"] - expected["min"]).dt.total_seconds() / 900).astype(int) + 1
    if not expected["count"].eq(expected_count).all():
        raise ValueError("The dataset has missing or irregular 15-minute timestamps by station")
    if data.duplicated(["station_id", "observed_at"]).any():
        raise ValueError("Duplicate station/timestamp observations found")

    max_time = data["observed_at"].max()
    cutoff = max_time - timedelta(days=int(validation_days))
    group = data.groupby("station_id", sort=False)["demand"]
    data["prediction_persistence"] = group.shift(1)
    data["prediction_seasonal_96"] = group.shift(96)
    summaries: list[dict[str, float | str | int]] = []
    predictions: list[pd.DataFrame] = []

    for horizon_steps in range(1, 5):
        # For target t and horizon h, the forecast origin is t-h. Both baselines
        # use only observations strictly before or at that origin.
        horizon_frame = data.loc[
            data["observed_at"].gt(cutoff),
            ["station_id", "observed_at", "demand", "prediction_persistence", "prediction_seasonal_96"],
        ].copy()
        horizon_frame["prediction_persistence"] = data.groupby("station_id", sort=False)["demand"].shift(horizon_steps).loc[horizon_frame.index]
        horizon_frame["forecast_origin"] = horizon_frame["observed_at"] - timedelta(minutes=15 * horizon_steps)
        horizon_frame["horizon_minutes"] = horizon_steps * 15
        horizon_frame = horizon_frame.dropna(subset=["prediction_persistence", "prediction_seasonal_96"])
        for model, column in [("persistence", "prediction_persistence"), ("seasonal_naive_96", "prediction_seasonal_96")]:
            metrics = score(horizon_frame, column)
            summaries.append({"baseline": model, "station_id": "ALL", "horizon_minutes": horizon_steps * 15, "n_predictions": len(horizon_frame), **metrics})
            for station_metrics in station_score(horizon_frame, column).to_dict(orient="records"):
                summaries.append({"baseline": model, "horizon_minutes": horizon_steps * 15, **station_metrics})
        predictions.append(horizon_frame)

    detail = pd.concat(predictions, ignore_index=True)
    overall_rows = []
    for model, column in [("persistence", "prediction_persistence"), ("seasonal_naive_96", "prediction_seasonal_96")]:
        overall_rows.append({"baseline": model, "station_id": "ALL", "horizon_minutes": 0, "n_predictions": len(detail), **score(detail, column)})
        for station_metrics in station_score(detail, column).to_dict(orient="records"):
            overall_rows.append({"baseline": model, "horizon_minutes": 0, **station_metrics})
    metrics_frame = pd.DataFrame(summaries + overall_rows)
    metadata = {"validation_start_exclusive": str(cutoff), "validation_end_inclusive": str(max_time), "validation_days": str(validation_days)}
    return metrics_frame, detail, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "observations.csv")
    parser.add_argument("--validation-days", type=int, default=7)
    args = parser.parse_args()
    if args.validation_days < 1:
        parser.error("--validation-days must be positive")

    metrics, predictions, metadata = run_backtest(args.data, args.validation_days)
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    metrics.to_csv(out / "baseline_metrics.csv", index=False, float_format="%.6f")
    predictions.to_csv(out / "baseline_predictions.csv", index=False)
    pd.Series(metadata).to_json(out / "baseline_metadata.json", indent=2)

    print(f"Validación: después de {metadata['validation_start_exclusive']} hasta {metadata['validation_end_inclusive']} UTC")
    summary_columns = ["baseline", "horizon_minutes", "n_predictions", "accuracy_macro_station_pct", "wape_all_rows_pct", "mae"]
    print(metrics.loc[metrics.station_id.eq("ALL"), summary_columns].to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"\nResultados guardados en {out}")


if __name__ == "__main__":
    main()
