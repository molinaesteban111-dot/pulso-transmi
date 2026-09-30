from api.dashboard import merge_current_drift, personal_metrics, supabase_headers


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


def test_modern_supabase_secret_is_not_used_as_bearer_token():
    headers = supabase_headers("sb_secret_example")

    assert headers["apikey"] == "sb_secret_example"
    assert "Authorization" not in headers


def test_legacy_supabase_service_role_uses_bearer_token():
    headers = supabase_headers("legacy.jwt.value")

    assert headers["Authorization"] == "Bearer legacy.jwt.value"


def test_merge_current_drift_returns_chronological_limited_history():
    stored_descending = [
        {"accuracy": 74.5, "drift": -1.2, "calculated_at": "2026-09-30T20:00:00Z"},
        {"accuracy": 74.0, "drift": -0.8, "calculated_at": "2026-09-30T19:00:00Z"},
    ]
    metrics = {
        "accuracy": 74.7,
        "drift_percentage_points": -1.5,
        "calculated_at": "2026-09-30T21:00:00Z",
    }

    result = merge_current_drift(stored_descending, metrics)

    assert [point["calculated_at"] for point in result] == [
        "2026-09-30T19:00:00Z",
        "2026-09-30T20:00:00Z",
        "2026-09-30T21:00:00Z",
    ]
    assert result[-1]["drift"] == -1.5
