"""Export the current Supabase observations used for drift retraining."""

from __future__ import annotations

import argparse
from pathlib import Path

from ingest import SupabaseRest, env
from src.pipeline import load_training_data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/observations.csv"))
    args = parser.parse_args()

    db = SupabaseRest(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"))
    try:
        observations, station_ids = load_training_data(db, include_missing=True)
    finally:
        db.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    observations.to_csv(args.output, index=False)
    print(
        f"Exported {len(observations):,} observations from "
        f"{len(station_ids)} stations to {args.output}"
    )


if __name__ == "__main__":
    main()
