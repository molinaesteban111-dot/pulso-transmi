from api.dashboard import personal_metrics


def _board(window, accuracy, rank, calculated_at="2026-09-30T20:00:00Z"):
    return {
        "window": window,
        "data": [
            {
                "display_name": "Otra Persona",
                "accuracy": 99,
                "rank": 1,
            },
            {
                "display_name": "Juan Esteban Molina",
                "accuracy": accuracy,
                "rank": rank,
                "calculated_at": calculated_at,
            },
        ],
    }


def test_personal_metrics_only_exposes_requested_participant():
    payload = personal_metrics(
        _board("cumulative", 74.739116, 12),
        _board("rolling_24h", 73.220351, 17),
    )

    assert payload["participant"] == "Juan Esteban Molina"
    assert payload["metrics"]["position"] == 12
    assert payload["metrics"]["accuracy"] == 74.739116
    assert payload["metrics"]["drift_percentage_points"] == -1.518765
    assert "data" not in payload
    assert "Otra Persona" not in str(payload)


def test_personal_metrics_handles_missing_rolling_window():
    payload = personal_metrics(_board("cumulative", 80.0, 4), None)

    assert payload["metrics"]["drift_percentage_points"] is None
    assert payload["metrics"]["rolling_24h_accuracy"] is None


def test_personal_metrics_handles_missing_participant():
    payload = personal_metrics({"data": []}, {"data": []})

    assert payload["metrics"] is None
    assert "Aún no hay métricas" in payload["message"]
