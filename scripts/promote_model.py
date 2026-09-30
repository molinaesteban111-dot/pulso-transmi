"""Upload candidates and promote the validated HGB artifact as champion."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forecasting import build_supervised
from ingest import SupabaseRest
from src.pipeline import load_champion
from upload_model_artifacts import main as upload_candidates


BUCKET = "pulso-transmi-model-artifacts"


def official_accuracy(frame: pd.DataFrame, predictions: np.ndarray) -> float:
    errors = pd.Series(
        np.abs(frame["demand"].to_numpy() - predictions), index=frame.index
    )
    station_error = errors.groupby(frame["station_id"]).sum()
    station_demand = frame["demand"].groupby(frame["station_id"]).sum()
    return float((100 * (1 - station_error / station_demand).clip(lower=0)).mean())


def current_validation_frame(validation_days: int = 7) -> pd.DataFrame:
    observations = pd.read_csv(
        ROOT / "data" / "observations.csv",
        dtype={"station_id": "string"},
        parse_dates=["observed_at"],
    )
    observations["observed_at"] = pd.to_datetime(
        observations["observed_at"], utc=True
    )
    supervised = build_supervised(observations)
    cutoff = observations["observed_at"].max() - timedelta(days=validation_days)
    return supervised.loc[supervised["observed_at"].gt(cutoff)].copy()


def main() -> None:
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    minimum_improvement = float(os.getenv("MIN_PROMOTION_IMPROVEMENT_PP", "0.10"))
    metrics = pd.read_csv(ROOT / "reports" / "model_metrics.csv")
    score = float(
        metrics.loc[
            (metrics.model == "hist_gradient_boosting")
            & (metrics.horizon_minutes == 0)
            & (metrics.station_id == "ALL"),
            "accuracy_macro_station_pct",
        ].iloc[0]
    )

    db = SupabaseRest(base, key)
    try:
        current = db.client.get(
            "/model_versions",
            params={
                "select": "model_version_id,validation_accuracy,artifact_uri",
                "status": "eq.champion",
                "order": "created_at.desc",
                "limit": 1,
            },
        )
        current.raise_for_status()
        old = current.json()
        current_score = None
        if old:
            champion, _ = load_champion(db)
            validation = current_validation_frame()
            prediction = np.maximum(0, champion.predict(validation))
            current_score = official_accuracy(validation, prediction)
            if score < current_score + minimum_improvement:
                print(
                    json.dumps(
                        {
                            "status": "kept_existing_champion",
                            "candidate_accuracy": score,
                            "champion_accuracy_same_window": current_score,
                            "minimum_improvement_pp": minimum_improvement,
                        },
                        indent=2,
                    )
                )
                return
    finally:
        db.close()

    stamp = upload_candidates()
    version = f"hgb-champion-{stamp}"
    artifact = f"storage://{BUCKET}/candidates/{stamp}/hist_gradient_boosting.joblib"
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ") and key.count(".") == 2:
        headers["Authorization"] = f"Bearer {key}"
    with httpx.Client(base_url=base + "/rest/v1", headers=headers, timeout=60) as client:
        run = client.post("/pipeline_runs", json={"run_type": "model_promotion", "status": "running"}, headers={**headers, "Prefer": "return=representation"})
        run.raise_for_status()
        run_id = run.json()[0]["run_id"]
        if old:
            client.patch("/model_versions", params={"model_version_id": f"eq.{old[0]['model_version_id']}"}, json={"status": "historical"}).raise_for_status()
        row = client.post("/model_versions", json={
            "version_name": version, "status": "champion", "algorithm": "HistGradientBoostingRegressor",
            "features": json.loads((ROOT / "reports" / "model_metadata.json").read_text()),
            "training_cutoff": datetime.now(timezone.utc).isoformat(), "git_commit": os.getenv("GITHUB_SHA"),
            "validation_accuracy": score, "artifact_uri": artifact,
        }, headers={**headers, "Prefer": "return=representation"})
        row.raise_for_status()
        new_id = row.json()[0]["model_version_id"]
        client.post("/model_transitions", json={"from_model_version_id": old[0]["model_version_id"] if old else None, "to_model_version_id": new_id, "run_id": run_id, "reason": "Drift retraining improved the champion on the same recent validation window", "previous_accuracy": current_score, "new_accuracy": score}).raise_for_status()
        client.patch("/pipeline_runs", params={"run_id": f"eq.{run_id}"}, json={"status": "success", "finished_at": datetime.now(timezone.utc).isoformat()}).raise_for_status()
    print(json.dumps({"status": "promoted", "version": version, "accuracy": score, "previous_accuracy_same_window": current_score, "artifact_uri": artifact}, indent=2))


if __name__ == "__main__":
    main()
