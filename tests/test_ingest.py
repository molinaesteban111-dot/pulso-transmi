import pandas as pd

from ingest import chunks, load_incremental_data, records


def test_records_serializes_timestamps_and_nulls() -> None:
    frame = pd.DataFrame(
        {"station_id": pd.Series(["03000"], dtype="string"), "observed_at": pd.to_datetime(["2026-01-01T00:00:00Z"]), "value": [None]}
    )
    result = records(frame)
    assert result == [{"station_id": "03000", "observed_at": "2026-01-01T00:00:00Z", "value": None}]


def test_chunks_preserves_all_rows() -> None:
    rows = [{"id": index} for index in range(5)]
    assert chunks(rows, size=2) == [[{"id": 0}, {"id": 1}], [{"id": 2}, {"id": 3}], [{"id": 4}]]


def test_incremental_ingestion_reads_stream_and_keeps_cursor_on_empty_page(monkeypatch) -> None:
    monkeypatch.delenv("PULSO_CURSOR", raising=False)

    class FakeDB:
        def __init__(self):
            self.batches = []

        def latest_cursor(self):
            return "cursor-1"

        def upsert(self, table, rows, on_conflict=None):
            assert table == "observations"
            assert rows[0]["station_id"] == "03000"

        def insert_one(self, table, row):
            self.batches.append(row)
            return {"ingestion_batch_id": len(self.batches)}

    class FakeAPI:
        def __init__(self):
            self.calls = []

        def stream_observations_page(self, *, cursor, limit):
            self.calls.append((cursor, limit))
            if len(self.calls) == 1:
                return {
                    "data": [{"station_id": "03000", "observed_at": "2026-09-01T00:00:00Z", "demand": 2}],
                    "next_cursor": "cursor-2",
                }
            return {"data": [], "next_cursor": None}

    db, api = FakeDB(), FakeAPI()
    result = load_incremental_data(db, api, "run-1")
    assert api.calls == [("cursor-1", 5000), ("cursor-2", 5000)]
    assert result["rows"] == 1
    assert result["next_cursor"] == "cursor-2"
    assert db.batches[-1]["status"] == "no_data"
    assert db.batches[-1]["next_cursor"] == "cursor-2"
