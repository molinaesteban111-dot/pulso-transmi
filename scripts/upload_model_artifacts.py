"""Upload trained candidate models to a private Supabase Storage bucket."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx


ROOT = Path(__file__).resolve().parents[1]
BUCKET = "pulso-transmi-model-artifacts"
MODELS = ("ridge", "hist_gradient_boosting")


def main() -> str:
    base_url = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    if not base_url or not service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    model_dir = ROOT / "artifacts" / "candidates"
    metadata_path = ROOT / "reports" / "model_metadata.json"
    metadata = json.loads(metadata_path.read_text())
    trained_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}
    storage_url = f"{base_url}/storage/v1"

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        bucket_response = client.post(
            f"{storage_url}/bucket",
            headers={**headers, "Content-Type": "application/json"},
            json={"id": BUCKET, "name": BUCKET, "public": False},
        )
        if bucket_response.is_error:
            # Creation may report a conflict when this private bucket already exists.
            existing = client.get(f"{storage_url}/bucket/{BUCKET}", headers=headers)
            if existing.is_error:
                raise RuntimeError(
                    f"Could not create or verify the private bucket ({bucket_response.status_code}): "
                    f"{bucket_response.text[:500]}"
                )
            if existing.json().get("public") is True:
                raise RuntimeError(f"Bucket {BUCKET} exists but is public; refusing model upload")

        manifest: dict[str, object] = {
            "bucket": BUCKET,
            "trained_at_utc": trained_at,
            "metadata": metadata,
            "models": {},
        }
        for model_name in MODELS:
            path = model_dir / f"{model_name}.joblib"
            if not path.is_file():
                raise FileNotFoundError(f"Trained artifact not found: {path}")
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            object_name = f"candidates/{trained_at}/{model_name}.joblib"
            response = client.post(
                f"{storage_url}/object/{quote(BUCKET)}/{quote(object_name, safe='/')}?upsert=false",
                headers={
                    **headers,
                    "Content-Type": "application/octet-stream",
                    "x-upsert": "false",
                },
                content=payload,
            )
            response.raise_for_status()
            manifest["models"][model_name] = {
                "path": object_name,
                "size_bytes": len(payload),
                "sha256": digest,
            }
            print(f"Uploaded {object_name} ({len(payload)} bytes, sha256={digest})")

        manifest_name = f"candidates/{trained_at}/manifest.json"
        result = client.post(
            f"{storage_url}/object/{quote(BUCKET)}/{quote(manifest_name, safe='/')}?upsert=false",
            headers={
                **headers,
                "Content-Type": "application/json",
                "x-upsert": "false",
            },
            content=json.dumps(manifest, indent=2).encode(),
        )
        result.raise_for_status()
        print(f"Uploaded {manifest_name}")
    return trained_at


if __name__ == "__main__":
    main()
