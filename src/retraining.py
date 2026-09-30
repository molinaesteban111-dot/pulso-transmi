"""Gate automatic retraining using recent official competition accuracy."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ingest import SupabaseRest, env, git_commit
from pulso_transmi import PulsoTransmiClient


DEFAULT_DISPLAY_NAME = "Juan Esteban Molina"
DEFAULT_THRESHOLD = 65.0
DEFAULT_COOLDOWN_HOURS = 24
RUN_TYPE = "drift_retraining"


def participant_accuracy(board: dict[str, Any], display_name: str) -> float | None:
    row = next(
        (item for item in board.get("data", []) if item.get("display_name") == display_name),
        None,
    )
    if row is None or row.get("accuracy") is None:
        return None
    return float(row["accuracy"])


def retraining_decision(
    accuracy: float | None,
    threshold: float,
    cooldown_active: bool,
) -> tuple[bool, str]:
    if accuracy is None:
        return False, "rolling_accuracy_unavailable"
    if accuracy > threshold:
        return False, "accuracy_above_threshold"
    if cooldown_active:
        return False, "cooldown_active"
    return True, "threshold_reached"


def _write_outputs(values: dict[str, object]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def main() -> None:
    threshold = float(os.getenv("RETRAIN_ACCURACY_THRESHOLD", DEFAULT_THRESHOLD))
    cooldown_hours = int(os.getenv("RETRAIN_COOLDOWN_HOURS", DEFAULT_COOLDOWN_HOURS))
    display_name = os.getenv("PULSO_DISPLAY_NAME", DEFAULT_DISPLAY_NAME)

    with PulsoTransmiClient(
        base_url=os.getenv("PULSO_API_URL"),
        api_key=os.getenv("PULSO_API_KEY"),
    ) as api:
        rolling = api.leaderboard("rolling_24h")
    accuracy = participant_accuracy(rolling, display_name)

    should_retrain, reason = retraining_decision(accuracy, threshold, False)
    trigger_run_id = ""
    if should_retrain:
        db = SupabaseRest(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"))
        try:
            cooldown_start = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
            response = db.client.get(
                "/pipeline_runs",
                params={
                    "select": "run_id,started_at",
                    "run_type": f"eq.{RUN_TYPE}",
                    "started_at": f"gte.{cooldown_start.isoformat()}",
                    "order": "started_at.desc",
                    "limit": 1,
                },
            )
            response.raise_for_status()
            should_retrain, reason = retraining_decision(
                accuracy, threshold, bool(response.json())
            )
            if should_retrain:
                now = datetime.now(timezone.utc).isoformat()
                trigger = db.insert_one(
                    "pipeline_runs",
                    {
                        "run_type": RUN_TYPE,
                        "git_commit": os.getenv("GITHUB_SHA") or git_commit(),
                        "status": "success",
                        "started_at": now,
                        "finished_at": now,
                    },
                )
                trigger_run_id = str(trigger["run_id"])
        finally:
            db.close()

    outputs = {
        "should_retrain": str(should_retrain).lower(),
        "rolling_accuracy": "" if accuracy is None else f"{accuracy:.6f}",
        "threshold": f"{threshold:.2f}",
        "reason": reason,
        "trigger_run_id": trigger_run_id,
    }
    _write_outputs(outputs)
    print(
        json.dumps(
            {
                "status": "retraining_gate_evaluated",
                "participant": display_name,
                **outputs,
                "cooldown_hours": cooldown_hours,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
