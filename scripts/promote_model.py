"""Upload candidates and promote the validated HGB artifact as champion."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

from upload_model_artifacts import main as upload_candidates


ROOT = Path(__file__).resolve().parents[1]
BUCKET = "pulso-transmi-model-artifacts"


def main() -> None:
    stamp = upload_candidates()
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    metrics = pd.read_csv(ROOT / "reports" / "rolling_backtest_metrics.csv")
    score = float(metrics.loc[(metrics.model == "hist_gradient_boosting") & (metrics.horizon_minutes == 0), "accuracy_macro_station_pct"].mean())
    version = f"hgb-champion-{stamp}"
    artifact = f"storage://{BUCKET}/candidates/{stamp}/hist_gradient_boosting.joblib"
    with httpx.Client(base_url=base + "/rest/v1", headers=headers, timeout=60) as client:
        current = client.get("/model_versions", params={"select": "model_version_id,validation_accuracy", "status": "eq.champion", "limit": 1})
        current.raise_for_status()
        old = current.json()
        if old and float(old[0].get("validation_accuracy") or 0) >= score:
            print(json.dumps({"status": "kept_existing_champion", "accuracy": score}, indent=2))
            return
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
        client.post("/model_transitions", json={"from_model_version_id": old[0]["model_version_id"] if old else None, "to_model_version_id": new_id, "run_id": run_id, "reason": "Temporal backtest improved or no champion existed", "previous_accuracy": float(old[0]["validation_accuracy"]) if old else None, "new_accuracy": score}).raise_for_status()
        client.patch("/pipeline_runs", params={"run_id": f"eq.{run_id}"}, json={"status": "success", "finished_at": datetime.now(timezone.utc).isoformat()}).raise_for_status()
    print(json.dumps({"status": "promoted", "version": version, "accuracy": score, "artifact_uri": artifact}, indent=2))


if __name__ == "__main__":
    main()
