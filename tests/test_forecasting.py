from datetime import timedelta

import numpy as np
import pandas as pd

from forecasting import build_forecast_features, build_supervised
from src.pipeline import idempotency_key, make_submission_payload, parse_cycle


def history_frame(stations: int = 1, periods: int = 800) -> pd.DataFrame:
    start = pd.Timestamp("2026-08-01T00:00:00Z")
    rows = []
    for station_number in range(stations):
        station_id = f"{station_number + 1:05d}"
        for index in range(periods):
            rows.append({
                "station_id": station_id,
                "observed_at": start + timedelta(minutes=15 * index),
                "demand": float(100 + station_number + index % 19),
            })
    return pd.DataFrame(rows)


def test_forecast_features_match_training_features_for_all_horizons() -> None:
    data = history_frame()
    cutoff = data["observed_at"].iloc[-5]
    expected = build_supervised(data)
    actual = build_forecast_features(data, ["00001"], cutoff).set_index("horizon_minutes")
    targets = {
        int(horizon): cutoff + timedelta(minutes=int(horizon))
        for horizon in actual.index
    }
    expected = expected.loc[
        expected.apply(lambda row: row["observed_at"] == targets[int(row["horizon_minutes"])], axis=1)
    ].set_index("horizon_minutes")
    columns = ["lag_0", "lag_1", "lag_4", "lag_96", "lag_672", "target_lag_96", "rolling_mean_4", "rolling_mean_96"]
    np.testing.assert_allclose(actual[columns].to_numpy(), expected.loc[actual.index, columns].to_numpy())


def test_payload_contains_exactly_48_distinct_station_targets() -> None:
    cutoff = pd.Timestamp("2026-09-19T12:00:00Z")
    rows = []
    for step in (15, 30, 45, 60):
        for station_number in range(12):
            rows.append({
                "station_id": f"{station_number:05d}",
                "target_at": cutoff + timedelta(minutes=step),
                "prediction": float(100 + station_number),
            })
    payload = make_submission_payload("cyc_test-1", cutoff, pd.DataFrame(rows), "abc1234")
    assert payload["schema_version"] == "1.0"
    assert len(payload["predictions"]) == 48
    assert len({(row["station_id"], row["target_at"]) for row in payload["predictions"]}) == 48
    assert payload["model"]["git_commit"] == "abc1234"


def test_cycle_validation_and_deterministic_idempotency() -> None:
    cycle_id, cutoff = parse_cycle({"cycle_id": "cyc_20260919_01", "data_cutoff": "2026-09-19T12:00:00Z"})
    assert cycle_id == "cyc_20260919_01"
    assert str(cutoff) == "2026-09-19 12:00:00+00:00"
    assert idempotency_key(cycle_id) == idempotency_key(cycle_id)
