from src.retraining import participant_accuracy, retraining_decision


def test_retraining_starts_at_exact_threshold() -> None:
    assert retraining_decision(65.0, 65.0, False) == (
        True,
        "threshold_reached",
    )


def test_retraining_skips_healthy_accuracy() -> None:
    assert retraining_decision(65.01, 65.0, False) == (
        False,
        "accuracy_above_threshold",
    )


def test_retraining_respects_cooldown() -> None:
    assert retraining_decision(50.0, 65.0, True) == (
        False,
        "cooldown_active",
    )


def test_retraining_skips_missing_official_metric() -> None:
    assert retraining_decision(None, 65.0, False) == (
        False,
        "rolling_accuracy_unavailable",
    )


def test_participant_accuracy_only_reads_requested_student() -> None:
    board = {
        "data": [
            {"display_name": "Otra Persona", "accuracy": 10},
            {"display_name": "Juan Esteban Molina", "accuracy": 64.5},
        ]
    }
    assert participant_accuracy(board, "Juan Esteban Molina") == 64.5
