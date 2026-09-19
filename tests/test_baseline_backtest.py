import pandas as pd
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SPEC = spec_from_file_location("baseline_backtest", Path(__file__).parents[1] / "examples" / "03_baseline_backtest.py")
MODULE = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
run_backtest = MODULE.run_backtest


def test_backtest_respects_horizons_and_uses_prior_day_lag(tmp_path) -> None:
    timestamps = pd.date_range("2026-01-01", periods=4 * 96, freq="15min", tz="UTC")
    frame = pd.DataFrame({"station_id": "03000", "observed_at": timestamps, "demand": range(len(timestamps))})
    path = tmp_path / "observations.csv"
    frame.to_csv(path, index=False)

    metrics, predictions, metadata = run_backtest(path, validation_days=1)
    row = predictions.loc[
        predictions.station_id.eq("03000")
        & predictions.observed_at.eq(timestamps[-1])
        & predictions.horizon_minutes.eq(60)
    ].iloc[0]
    assert row.prediction_persistence == frame.demand.iloc[-5]
    assert row.prediction_seasonal_96 == frame.demand.iloc[-97]
    assert set(metrics.horizon_minutes) == {0, 15, 30, 45, 60}
    assert metadata["validation_days"] == "1"


def test_model_features_use_target_daily_lag_without_future_values() -> None:
    timestamps = pd.date_range("2026-01-01", periods=8 * 96, freq="15min", tz="UTC")
    frame = pd.DataFrame({"station_id": "03000", "observed_at": timestamps, "demand": range(len(timestamps))})
    from importlib.util import module_from_spec, spec_from_file_location

    path = Path(__file__).parents[1] / "examples" / "04_train_models.py"
    spec = spec_from_file_location("train_models", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    supervised = module.build_supervised(frame)
    row = supervised.loc[
        supervised.observed_at.eq(timestamps[-1]) & supervised.horizon_steps.eq(4)
    ].iloc[0]
    assert row.forecast_origin == timestamps[-5]
    assert row.lag_0 == frame.demand.iloc[-5]
    assert row.target_lag_96 == frame.demand.iloc[-97]
