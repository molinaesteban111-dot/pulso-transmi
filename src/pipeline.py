"""Forecast an open TransMi cycle and submit the versioned predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from forecasting import build_forecast_features, build_supervised, create_models
from ingest import IngestionError, SupabaseRest
from pulso_transmi import PulsoTransmiClient, PulsoTransmiError


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://pulso-transmi.72-60-245-2.sslip.io"
MODEL_KEY = "hist_gradient_boosting"
MODEL_VERSION = "hgb-candidate-v1"
EXPECTED_STATIONS = 12
HORIZONS_MINUTES = (15, 30, 45, 60)
PAGE_SIZE = 1000


class PipelineError(RuntimeError):
    """Raised when a forecast cycle cannot be processed safely."""


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _api_datetime(value: Any, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise PipelineError(f"Cycle response has invalid {field}") from exc
    if timestamp.tzinfo is None:
        raise PipelineError(f"Cycle field {field} must include a timezone")
    return timestamp.tz_convert("UTC")


def parse_cycle(payload: dict[str, Any]) -> tuple[str, pd.Timestamp]:
    cycle_id = payload.get("cycle_id")
    cutoff = payload.get("data_cutoff") or payload.get("cutoff_at")
    if not isinstance(cycle_id, str) or not cycle_id.startswith("cyc_"):
        raise PipelineError("Open-cycle response is missing a valid cycle_id")
    if not cutoff:
        raise PipelineError("Open-cycle response is missing data_cutoff")
    return cycle_id, _api_datetime(cutoff, "data_cutoff")


def idempotency_key(cycle_id: str) -> str:
    digest = hashlib.sha256(f"{cycle_id}|{MODEL_VERSION}".encode()).hexdigest()
    return f"pulso-{digest}"


def make_submission_payload(
    cycle_id: str,
    cutoff: pd.Timestamp,
    predictions: pd.DataFrame,
    commit: str | None,
) -> dict[str, Any]:
    if len(predictions) != EXPECTED_STATIONS * len(HORIZONS_MINUTES):
        raise PipelineError(f"Expected 48 predictions; generated {len(predictions)}")
    if predictions.duplicated(["station_id", "target_at"]).any():
        raise PipelineError("Duplicate station/target pairs in predictions")
    if predictions["station_id"].nunique() != EXPECTED_STATIONS:
        raise PipelineError(f"Expected predictions for {EXPECTED_STATIONS} stations")
    if not predictions.groupby("station_id")["target_at"].nunique().eq(len(HORIZONS_MINUTES)).all():
        raise PipelineError("Each station must have exactly one prediction per horizon")
    if predictions["prediction"].isna().any() or not np.isfinite(predictions["prediction"]).all():
        raise PipelineError("Predictions contain non-finite values")
    rows = []
    for prediction in predictions.sort_values(["target_at", "station_id"]).to_dict(orient="records"):
        rows.append({
            "station_id": str(prediction["station_id"]),
            "target_at": pd.Timestamp(prediction["target_at"]).isoformat().replace("+00:00", "Z"),
            "value": max(0.0, float(prediction["prediction"])),
        })
    body: dict[str, Any] = {
        "schema_version": "1.0",
        "cycle_id": cycle_id,
        "client_run_id": f"pulso-{hashlib.sha256(f'{cycle_id}|{MODEL_VERSION}'.encode()).hexdigest()[:32]}",
        "data_cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "model": {
            "version": MODEL_VERSION,
            "training_data_end": cutoff.isoformat().replace("+00:00", "Z"),
            "git_commit": commit,
        },
        "predictions": rows,
    }
    return body


def _select_all(db: SupabaseRest, table: str, select: str, order: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        response = db.client.get(
            f"/{table}",
            params={"select": select, "order": order},
            headers={"Range-Unit": "items", "Range": f"{start}-{start + PAGE_SIZE - 1}"},
        )
        if response.is_error:
            raise PipelineError(f"Supabase read {table} failed: {response.status_code} {response.text[:400]}")
        page = response.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += len(page)


def load_training_data(db: SupabaseRest) -> tuple[pd.DataFrame, list[str]]:
    station_rows = _select_all(db, "stations", "station_id", "station_id.asc")
    station_ids = sorted({str(row["station_id"]) for row in station_rows})
    if len(station_ids) != EXPECTED_STATIONS or any(len(station_id) != 5 or not station_id.isdigit() for station_id in station_ids):
        raise PipelineError(f"Expected {EXPECTED_STATIONS} valid five-digit station IDs in Supabase")
    observation_rows = _select_all(
        db, "observations", "station_id,observed_at,demand", "station_id.asc,observed_at.asc"
    )
    frame = pd.DataFrame(observation_rows)
    if frame.empty:
        raise PipelineError("Supabase has no observations to train from")
    frame["station_id"] = frame["station_id"].astype("string")
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    frame["demand"] = pd.to_numeric(frame["demand"], errors="raise")
    frame = frame.sort_values(["station_id", "observed_at"]).drop_duplicates(
        ["station_id", "observed_at"], keep="last"
    ).reset_index(drop=True)
    return frame, station_ids


def _get_existing_submission(db: SupabaseRest, idem: str) -> dict[str, Any] | None:
    response = db.client.get(
        "/submissions",
        params={"select": "external_submission_id,status,receipt", "idempotency_key": f"eq.{idem}", "limit": 1},
    )
    if response.is_error:
        raise PipelineError(f"Supabase submission lookup failed: {response.status_code} {response.text[:400]}")
    rows = response.json()
    return rows[0] if rows else None


def _get_or_create_model_version(
    db: SupabaseRest, cutoff: pd.Timestamp, commit: str | None, validation_accuracy: float | None,
) -> str:
    cutoff_label = cutoff.strftime("%Y%m%dT%H%MZ")
    version_name = f"{MODEL_VERSION}-{cutoff_label}-{(commit or 'unknown')[:7]}"
    existing = db.client.get(
        "/model_versions", params={"select": "model_version_id", "version_name": f"eq.{version_name}", "limit": 1}
    )
    if existing.is_error:
        raise PipelineError(f"Supabase model-version lookup failed: {existing.status_code} {existing.text[:400]}")
    rows = existing.json()
    if rows:
        return rows[0]["model_version_id"]
    row = db.insert_one("model_versions", {
        "version_name": version_name,
        "status": "candidate",
        "algorithm": "HistGradientBoostingRegressor",
        "features": {
            "lags_intervals": [0, 1, 4, 96, 672],
            "rolling_windows": [4, 96],
            "calendar": ["time_of_day_cyclic", "day_of_week_cyclic", "is_weekend"],
            "station_one_hot": True,
            "horizons_minutes": list(HORIZONS_MINUTES),
            "hyperparameters": {"max_iter": 120, "learning_rate": 0.08, "max_leaf_nodes": 31, "l2_regularization": 1.0, "random_state": 42},
        },
        "training_cutoff": cutoff.isoformat(),
        "git_commit": commit,
        "validation_accuracy": validation_accuracy,
    })
    return row["model_version_id"]


def _candidate_validation_accuracy() -> float | None:
    path = ROOT / "reports" / "rolling_backtest_metrics.csv"
    if not path.exists():
        return None
    metrics = pd.read_csv(path)
    selected = metrics.loc[
        metrics["model"].eq(MODEL_KEY) & metrics["horizon_minutes"].eq(0),
        "accuracy_macro_station_pct",
    ]
    return float(selected.mean()) if not selected.empty else None


def _persist_submission(
    db: SupabaseRest,
    payload: dict[str, Any],
    idem: str,
    response: dict[str, Any],
    receipt: dict[str, Any],
    run_id: str,
    model_version_id: str,
    predictions: pd.DataFrame,
) -> None:
    external_id = response.get("submission_id") or response.get("id")
    status = response.get("status", "accepted")
    if status not in {"pending", "accepted", "rejected", "failed"}:
        status = "pending"
    db.insert_one("submissions", {
        "external_submission_id": str(external_id) if external_id is not None else None,
        "cycle_id": payload["cycle_id"],
        "run_id": run_id,
        "idempotency_key": idem,
        "prediction_count": len(payload["predictions"]),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "receipt": {"response": response, "receipt": receipt},
    })
    rows = []
    for prediction in predictions.to_dict(orient="records"):
        rows.append({
            "run_id": run_id,
            "model_version_id": model_version_id,
            "station_id": str(prediction["station_id"]),
            "cycle_origin": payload["data_cutoff"],
            "target_at": pd.Timestamp(prediction["target_at"]).isoformat(),
            "prediction": float(prediction["prediction"]),
            "idempotency_key": idem,
        })
    db.upsert("predictions", rows)


def submit_open_cycle() -> dict[str, Any]:
    base_url = os.getenv("PULSO_API_URL") or BASE_URL
    api_key = os.getenv("PULSO_API_KEY")
    api = PulsoTransmiClient(base_url=base_url, api_key=api_key)
    try:
        cycle = api.current_cycle()
        if cycle is None:
            return {"status": "no_open_cycle"}
        cycle_id, cutoff = parse_cycle(cycle)
        if not api_key:
            raise PipelineError("PULSO_API_KEY is required while a forecast cycle is open")
        idem = idempotency_key(cycle_id)
        supabase_url = os.getenv("SUPABASE_URL")
        service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not supabase_url or not service_key:
            raise PipelineError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for forecast training")
        db = SupabaseRest(supabase_url, service_key)
        run_row: dict[str, Any] | None = None
        try:
            # If an earlier attempt reached the API but lost its response, retain
            # one submission per cycle/model and retrieve the original receipt.
            existing = _get_existing_submission(db, idem)
            if existing:
                external_id = existing.get("external_submission_id")
                receipt = api.submission_receipt(external_id) if external_id else existing.get("receipt", {})
                return {"status": "already_submitted", "submission_id": external_id, "receipt": receipt}

            observations, station_ids = load_training_data(db)
            # Do not use observations newer than the cycle's declared cutoff.
            observations = observations.loc[observations["observed_at"].le(cutoff)].copy()
            by_station = observations.groupby("station_id")["observed_at"].max()
            stale = [station for station in station_ids if station not in by_station or by_station[station] != cutoff]
            if stale:
                raise PipelineError(
                    "Supabase data are not complete through cycle data_cutoff for stations: " + ", ".join(stale)
                )
            coverage = observations.groupby("station_id")["observed_at"].agg(["min", "max", "count"])
            expected_counts = ((coverage["max"] - coverage["min"]).dt.total_seconds() / 900).astype(int) + 1
            if not coverage["count"].eq(expected_counts).all():
                raise PipelineError("Supabase observation history has missing or irregular 15-minute intervals")
            supervised = build_supervised(observations)
            train = supervised.loc[supervised["observed_at"].le(cutoff)].copy()
            if train.empty:
                raise PipelineError("Not enough historical rows to train the forecast model")

            run_row = db.insert_one("pipeline_runs", {
                "run_type": "forecast_submission",
                "git_commit": git_commit(),
                "status": "running",
            })
            model = create_models()[MODEL_KEY]
            model.fit(train, train["demand"])
            forecast_features = build_forecast_features(observations, station_ids, cutoff)
            forecast = forecast_features[["station_id", "observed_at", "horizon_minutes"]].copy()
            forecast["prediction"] = np.maximum(0, model.predict(forecast_features))
            forecast = forecast.rename(columns={"observed_at": "target_at"})
            expected_targets = {cutoff + timedelta(minutes=horizon) for horizon in HORIZONS_MINUTES}
            if len(forecast) != 48 or set(forecast["target_at"]) != expected_targets:
                raise PipelineError("Forecast output does not match the 12-station × 4-horizon cycle contract")

            commit = git_commit()
            payload = make_submission_payload(cycle_id, cutoff, forecast, commit)
            response = api.create_submission(payload, idem)
            external_id = response.get("submission_id") or response.get("id")
            receipt = api.submission_receipt(str(external_id)) if external_id else response
            model_version_id = _get_or_create_model_version(
                db, cutoff, commit, _candidate_validation_accuracy()
            )
            _persist_submission(db, payload, idem, response, receipt, run_row["run_id"], model_version_id, forecast)
            db.client.patch(
                "/pipeline_runs",
                params={"run_id": f"eq.{run_row['run_id']}"},
                json={"status": "success", "finished_at": datetime.now(timezone.utc).isoformat()},
            ).raise_for_status()
            return {"status": "submitted", "cycle_id": cycle_id, "submission_id": external_id, "receipt": receipt}
        except Exception as exc:
            if run_row:
                db.client.patch(
                    "/pipeline_runs",
                    params={"run_id": f"eq.{run_row['run_id']}"},
                    json={"status": "failed", "error_message": str(exc)[:1000], "finished_at": datetime.now(timezone.utc).isoformat()},
                )
            if isinstance(exc, (PipelineError, IngestionError, PulsoTransmiError)):
                raise
            raise PipelineError(str(exc)) from exc
        finally:
            db.close()
    finally:
        api.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--receipt", metavar="SUBMISSION_ID", help="retrieve a submission receipt")
    action.add_argument("--leaderboard", choices=("cumulative", "rolling_24h"), help="read the official leaderboard")
    args = parser.parse_args()
    api_key = os.getenv("PULSO_API_KEY")
    base_url = os.getenv("PULSO_API_URL") or BASE_URL
    if (args.receipt or args.leaderboard) and not api_key:
        parser.error("PULSO_API_KEY is required for receipt and leaderboard queries")
    try:
        if args.receipt:
            with PulsoTransmiClient(base_url=base_url, api_key=api_key) as api:
                result = api.submission_receipt(args.receipt)
        elif args.leaderboard:
            with PulsoTransmiClient(base_url=base_url, api_key=api_key) as api:
                result = api.leaderboard(args.leaderboard)
        else:
            result = submit_open_cycle()
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    except (PipelineError, IngestionError, PulsoTransmiError) as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
