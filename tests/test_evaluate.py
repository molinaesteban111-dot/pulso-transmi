import pytest

from evaluate import metric_snapshot


def _board(accuracy, *, starts_at=None, calculated_at="2026-09-30T20:00:00Z"):
    board = {
        "data": [
            {
                "display_name": "Juan Esteban Molina",
                "accuracy": accuracy,
                "raw_wape": 1 - accuracy / 100,
                "coverage": 1.0,
                "calculated_at": calculated_at,
            }
        ]
    }
    if starts_at:
        board["starts_at"] = starts_at
    return board


def test_metric_snapshot_calculates_personal_drift() -> None:
    row = metric_snapshot(
        _board(74.739116),
        _board(73.220351, starts_at="2026-09-29T20:00:00Z"),
        "Juan Esteban Molina",
        "run-id",
        "model-id",
    )

    assert row is not None
    assert row["run_id"] == "run-id"
    assert row["model_version_id"] == "model-id"
    assert row["metric_scope"] == "competition_personal"
    assert row["accuracy"] == pytest.approx(74.739116)
    assert row["drift_score"] == pytest.approx(-1.518765)
    assert row["window_start"] == "2026-09-29T20:00:00Z"


def test_metric_snapshot_skips_unknown_participant() -> None:
    assert (
        metric_snapshot(
            {"data": []},
            {"data": []},
            "Juan Esteban Molina",
            "run-id",
            None,
        )
        is None
    )
