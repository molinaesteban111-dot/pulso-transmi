"""Persist official personal metrics and performance-drift snapshots."""

from __future__ import annotations

import json
import os
from typing import Any

from ingest import SupabaseRest
from pulso_transmi import PulsoTransmiClient, PulsoTransmiError


DEFAULT_DISPLAY_NAME = "Juan Esteban Molina"
METRIC_SCOPE = "competition_personal"


def participant(board: dict[str, Any], display_name: str) -> dict[str, Any] | None:
    return next(
        (row for row in board.get("data", []) if row.get("display_name") == display_name),
        None,
    )


def metric_snapshot(
    cumulative: dict[str, Any],
    rolling_24h: dict[str, Any],
    display_name: str,
    run_id: str,
    model_version_id: str | None,
) -> dict[str, Any] | None:
    current = participant(cumulative, display_name)
    recent = participant(rolling_24h, display_name)
    if current is None:
        return None

    cumulative_accuracy = float(current["accuracy"])
    recent_accuracy = float(recent["accuracy"]) if recent else None
    drift = recent_accuracy - cumulative_accuracy if recent_accuracy is not None else None
    calculated_at = current.get("calculated_at")
    return {
        "run_id": run_id,
        "model_version_id": model_version_id,
        "metric_scope": METRIC_SCOPE,
        "horizon": "rolling_24h_vs_cumulative",
        "wape": current.get("raw_wape"),
        "accuracy": cumulative_accuracy,
        "coverage": current.get("coverage"),
        "drift_score": drift,
        "window_start": rolling_24h.get("starts_at"),
        "window_end": calculated_at,
        "calculated_at": calculated_at,
    }


def persist_snapshot(
    db: SupabaseRest,
    cumulative: dict[str, Any],
    rolling_24h: dict[str, Any],
    display_name: str,
) -> dict[str, Any] | None:
    latest_response = db.client.get(
        "/submissions",
        params={
            "select": "external_submission_id,run_id",
            "order": "submitted_at.desc",
            "limit": 1,
        },
    )
    latest_response.raise_for_status()
    submissions = latest_response.json()
    if not submissions or not submissions[0].get("run_id"):
        return None

    model_response = db.client.get(
        "/model_versions",
        params={
            "select": "model_version_id",
            "status": "eq.champion",
            "order": "created_at.desc",
            "limit": 1,
        },
    )
    model_response.raise_for_status()
    models = model_response.json()
    row = metric_snapshot(
        cumulative,
        rolling_24h,
        display_name,
        submissions[0]["run_id"],
        models[0]["model_version_id"] if models else None,
    )
    if row is None:
        return None

    existing_response = db.client.get(
        "/metric_snapshots",
        params={
            "select": "metric_snapshot_id",
            "metric_scope": f"eq.{METRIC_SCOPE}",
            "window_end": f"eq.{row['window_end']}",
            "limit": 1,
        },
    )
    existing_response.raise_for_status()
    if existing_response.json():
        return {"status": "already_recorded", **row}

    stored = db.insert_one("metric_snapshots", row)
    return {"status": "recorded", **stored}


def main() -> None:
    display_name = os.getenv("PULSO_DISPLAY_NAME", DEFAULT_DISPLAY_NAME)
    try:
        with PulsoTransmiClient(api_key=os.environ.get("PULSO_API_KEY")) as api:
            cumulative = api.leaderboard("cumulative")
            rolling_24h = api.leaderboard("rolling_24h")
    except PulsoTransmiError as exc:
        # Monitoring must not fail the operational pipeline when the external
        # leaderboard is temporarily unavailable.
        print(json.dumps({"status": "leaderboard_unavailable", "error": str(exc)}, ensure_ascii=False))
        return

    current = participant(cumulative, display_name)
    recent = participant(rolling_24h, display_name)
    output: dict[str, Any] = {
        "status": "metrics_read",
        "participant": display_name,
        "accuracy": current.get("accuracy") if current else None,
        "position": current.get("rank") if current else None,
        "rolling_24h_accuracy": recent.get("accuracy") if recent else None,
    }

    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        db = SupabaseRest(url, key)
        try:
            output["snapshot"] = persist_snapshot(
                db, cumulative, rolling_24h, display_name
            )
        finally:
            db.close()
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
