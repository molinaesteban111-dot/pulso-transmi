import pandas as pd

from ingest import chunks, records


def test_records_serializes_timestamps_and_nulls() -> None:
    frame = pd.DataFrame(
        {"station_id": pd.Series(["03000"], dtype="string"), "observed_at": pd.to_datetime(["2026-01-01T00:00:00Z"]), "value": [None]}
    )
    result = records(frame)
    assert result == [{"station_id": "03000", "observed_at": "2026-01-01T00:00:00Z", "value": None}]


def test_chunks_preserves_all_rows() -> None:
    rows = [{"id": index} for index in range(5)]
    assert chunks(rows, size=2) == [[{"id": 0}, {"id": 1}], [{"id": 2}, {"id": 3}], [{"id": 4}]]
