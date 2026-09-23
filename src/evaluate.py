"""Read official evaluation signals and persist available receipt metrics."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import httpx

from ingest import SupabaseRest
from pulso_transmi import PulsoTransmiClient


def main() -> None:
    api = PulsoTransmiClient(api_key=os.environ.get("PULSO_API_KEY"))
    board = api.leaderboard("cumulative")
    print(json.dumps(board, indent=2, ensure_ascii=False))
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return
    db = SupabaseRest(url, key)
    try:
        latest = db.client.get("/submissions", params={"select": "external_submission_id,run_id", "order": "submitted_at.desc", "limit": 1})
        latest.raise_for_status()
        if not latest.json() or not latest.json()[0].get("external_submission_id"):
            return
        receipt = api.submission_receipt(latest.json()[0]["external_submission_id"])
        print(json.dumps({"latest_receipt": receipt}, indent=2, ensure_ascii=False))
    finally:
        db.close()
        api.close()


if __name__ == "__main__":
    main()
