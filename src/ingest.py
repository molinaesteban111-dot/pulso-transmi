"""Ingesta inicial e incremental de Pulso TransMi hacia Supabase.

Requiere SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY. La service-role key solo
debe existir en el entorno local seguro o en GitHub Actions Secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from pulso_transmi import PulsoTransmiClient


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


class IngestionError(RuntimeError):
    """Raised when ingestion cannot safely complete."""


@dataclass
class SupabaseRest:
    url: str
    service_role_key: str
    timeout: float = 60.0

    def __post_init__(self) -> None:
        self.client = httpx.Client(
            base_url=self.url.rstrip("/") + "/rest/v1",
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            timeout=self.timeout,
        )

    def close(self) -> None:
        self.client.close()

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str | None = None) -> None:
        if not rows:
            return
        params = {"on_conflict": on_conflict} if on_conflict else None
        response = self.client.post(f"/{table}", params=params, json=rows)
        if response.is_error:
            raise IngestionError(f"Supabase upsert {table} failed: {response.status_code} {response.text}")

    def insert_one(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(
            f"/{table}",
            params={"select": "*"},
            headers={"Prefer": "return=representation"},
            json=row,
        )
        if response.is_error:
            raise IngestionError(f"Supabase insert {table} failed: {response.status_code} {response.text}")
        return response.json()[0]

    def latest_cursor(self) -> str | None:
        response = self.client.get(
            "/ingestion_batches",
            params={"select": "next_cursor", "order": "ingestion_batch_id.desc", "limit": 1},
        )
        if response.is_error:
            raise IngestionError(f"Supabase cursor lookup failed: {response.status_code} {response.text}")
        rows = response.json()
        return rows[0]["next_cursor"] if rows and rows[0]["next_cursor"] else None


def env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise IngestionError(f"Missing required environment variable: {name}")
    return value


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    clean = frame.copy()
    for column in clean.columns:
        if pd.api.types.is_datetime64_any_dtype(clean[column]):
            clean[column] = clean[column].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    clean = clean.astype(object).where(pd.notna(clean), None)
    return json.loads(clean.to_json(orient="records"))


def chunks(rows: list[dict[str, Any]], size: int = 500) -> list[list[dict[str, Any]]]:
    return [rows[start : start + size] for start in range(0, len(rows), size)]


def load_static_data(db: SupabaseRest, data_dir: Path = DATA_DIR) -> dict[str, int]:
    stations = pd.read_csv(data_dir / "stations.csv", dtype={"station_id": "string"})
    observations = pd.read_csv(data_dir / "observations.csv", dtype={"station_id": "string"}, parse_dates=["observed_at"])
    context = pd.read_csv(data_dir / "context.csv", parse_dates=["observed_at"])

    db.upsert("stations", records(stations), on_conflict="station_id")
    for batch in chunks(records(context)):
        db.upsert("context", batch, on_conflict="observed_at")
    for batch in chunks(records(observations)):
        db.upsert("observations", batch, on_conflict="station_id,observed_at")
    return {"stations": len(stations), "context": len(context), "observations": len(observations)}


def load_incremental_data(db: SupabaseRest, api: PulsoTransmiClient, run_id: str) -> dict[str, int | str | None]:
    """Consume the public stream from the saved cursor supplied by the caller.

    The cursor is only advanced by the caller after this function returns
    successfully, so a failed upsert is safe to retry.
    """
    cursor = os.getenv("PULSO_CURSOR") or db.latest_cursor()
    page = api.observations_page(cursor=cursor, limit=5000)
    rows = page.get("data", [])
    next_cursor = page.get("next_cursor")
    if rows:
        frame = pd.DataFrame(rows)
        frame["station_id"] = frame["station_id"].astype("string")
        frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
        for part in chunks(records(frame)):
            db.upsert("observations", part, on_conflict="station_id,observed_at")
        # Persist the cursor only after every observation upsert succeeds. If the
        # batch log fails, retrying the same cursor is safe thanks to the upsert.
        batch = db.insert_one("ingestion_batches", {"run_id": run_id, "source_cursor": cursor, "next_cursor": next_cursor, "rows_received": len(frame), "source_cutoff": frame["observed_at"].max().strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "success"})
        return {"rows": len(frame), "next_cursor": next_cursor, "batch_id": batch["ingestion_batch_id"]}
    db.insert_one("ingestion_batches", {"run_id": run_id, "source_cursor": cursor, "next_cursor": next_cursor, "rows_received": 0, "status": "no_data"})
    return {"rows": 0, "next_cursor": next_cursor, "batch_id": None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", action="store_true", help="Carga el histórico local en Supabase")
    parser.add_argument("--incremental", action="store_true", help="Consume una página nueva de la API")
    args = parser.parse_args()
    if args.initial == args.incremental:
        parser.error("elige exactamente una opción: --initial o --incremental")

    db = SupabaseRest(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"))
    try:
        if args.initial:
            print(json.dumps(load_static_data(db), indent=2))
            return
        run = db.insert_one("pipeline_runs", {"run_type": "collector", "git_commit": git_commit(), "status": "running"})
        with PulsoTransmiClient() as api:
            result = load_incremental_data(db, api, run["run_id"])
        db.client.patch(f"/pipeline_runs?run_id=eq.{run['run_id']}", json={"status": "success", "finished_at": pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")})
        print(json.dumps(result, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
