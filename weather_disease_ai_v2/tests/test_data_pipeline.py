from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.data.dataset import (
    BASE_INPUT_COLUMNS,
    LABEL_COLUMN,
    add_calendar_features,
    split_by_unique_dates,
    stable_sort,
    validate_dataset,
)
from src.data.patients import build_patient_data
from src.features.weather import build_weather_window_features, weather_feature_columns


def make_daily_weather(days: int = 20) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    values = np.arange(1, days + 1, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "temperature_mean_daily": values,
            "temperature_max_daily": values + 1,
            "temperature_min_daily": values - 1,
            "humidity_mean_daily": values + 50,
            "humidity_max_daily": values + 55,
            "humidity_min_daily": values + 45,
            "precipitation_sum_daily": values / 10,
            "rain_sum_daily": np.where(values % 2 == 0, values / 10, 0),
            "weather_code": values,
            "wind_speed_mean_daily": values + 2,
            "wind_speed_max_daily": values + 4,
            "wind_gust_max_daily": values + 8,
        }
    )


def make_dataset(days: int = 20) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=days, freq="D"),
            "age_group": ["1-5 tuổi"] * days,
            "gender": ["Nam"] * days,
            "disease_group_id": ["G1"] * days,
            "disease_group_name": ["Nhóm 1"] * days,
            "report_group_code": ["R1"] * days,
            "case_count": np.arange(1, days + 1),
            "weather_code": [1.0] * days,
        }
    )
    return stable_sort(add_calendar_features(frame))


def test_patient_aggregation_preserves_mapped_case_count(monkeypatch: pytest.MonkeyPatch) -> None:
    patients = pd.DataFrame(
        {
            "icdNV": ["A01", "A01", "B01", "X99"],
            "icdxuatvien": ["A01", "A01", "B01", "X99"],
            "check_in_date": pd.to_datetime(["2024-01-01"] * 4),
            "date_of_birth": pd.to_datetime(["2020-01-01"] * 4),
            "month": [48, 48, 48, 48],
            "gender": ["Nam", "Nam", "Nữ", "Nữ"],
        }
    )
    catalog = pd.DataFrame(
        {
            "MAICD": ["A01", "B01"],
            "IDNHOMICD": ["G1", "G2"],
            "TENNHOMICD": ["Nhóm 1", "Nhóm 2"],
            "MANHOMBAOCAO": ["R1", "R2"],
        }
    )
    monkeypatch.setattr(
        "src.data.patients.read_workbook_tables", lambda *_args, **_kwargs: (patients, catalog)
    )
    result = build_patient_data(None, "patients", "catalog")  # type: ignore[arg-type]
    assert result.stats["mapped_patient_rows"] == 3
    assert result.positive_cases["case_count"].sum() == 3
    assert result.stats["unmapped_patient_rows"] == 1


def test_weather_windows_use_exact_trailing_days_and_no_future() -> None:
    daily = make_daily_weather()
    target = pd.Timestamp("2024-01-14")
    with_future = daily.copy()
    with_future.loc[with_future["date"] > target, "temperature_mean_daily"] = 1_000_000
    features = build_weather_window_features(with_future, target)
    baseline = build_weather_window_features(daily[daily["date"] <= target], target)
    assert features == baseline
    assert features["temperature_mean_3d"] == pytest.approx(np.mean([12, 13, 14]))
    assert features["temperature_mean_7d"] == pytest.approx(np.mean(range(8, 15)))
    assert features["temperature_mean_14d"] == pytest.approx(np.mean(range(1, 15)))
    assert features["rain_days_3d"] == 2
    assert features["weather_code"] == 14


def test_fourteen_day_features_require_fourteen_calendar_days() -> None:
    daily = make_daily_weather(13)
    features = build_weather_window_features(daily, "2024-01-13")
    assert math.isnan(features["temperature_mean_14d"])
    assert math.isnan(features["rain_sum_14d"])


def test_time_splits_have_no_overlapping_dates_and_preserve_cases() -> None:
    dataset = make_dataset()
    train, validation, test, metadata = split_by_unique_dates(dataset)
    date_sets = [set(frame["date"]) for frame in (train, validation, test)]
    assert not date_sets[0] & date_sets[1]
    assert not date_sets[0] & date_sets[2]
    assert not date_sets[1] & date_sets[2]
    assert sum(frame["case_count"].sum() for frame in (train, validation, test)) == dataset[
        "case_count"
    ].sum()
    assert metadata["train"]["unique_dates"] == 14
    assert metadata["validation"]["unique_dates"] == 3
    assert metadata["test"]["unique_dates"] == 3


def test_final_schema_has_no_label_leakage_negative_samples_or_personal_columns() -> None:
    dataset = make_dataset()
    input_columns = [*BASE_INPUT_COLUMNS, "weather_code"]
    checks = validate_dataset(dataset, input_columns, int(dataset["case_count"].sum()))
    assert LABEL_COLUMN not in input_columns
    assert "has_case" not in dataset.columns
    assert (dataset["case_count"] > 0).all()
    assert "date_of_birth" not in dataset.columns
    assert "address" not in dataset.columns
    assert checks["required_columns_present"]


def test_stable_sort_is_reproducible() -> None:
    dataset = make_dataset()
    first = stable_sort(dataset.sample(frac=1, random_state=1))
    second = stable_sort(dataset.sample(frac=1, random_state=2))
    pd.testing.assert_frame_equal(first, second)


def test_weather_feature_schema_has_all_configured_windows() -> None:
    columns = weather_feature_columns(make_daily_weather(), (1, 3, 7, 14))
    for window in (1, 3, 7, 14):
        assert f"temperature_mean_{window}d" in columns
        assert f"humidity_max_{window}d" in columns
        assert f"rain_days_{window}d" in columns
        assert f"wind_gust_max_{window}d" in columns
