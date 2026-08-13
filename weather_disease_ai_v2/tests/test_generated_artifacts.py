from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_gzip_csv(relative_path: str) -> pd.DataFrame:
    path = PROJECT_ROOT / relative_path
    assert path.is_file(), f"Missing generated artifact; run scripts/03_build_dataset.py: {path}"
    return pd.read_csv(path)


def test_generated_dataset_and_splits_preserve_all_positive_cases() -> None:
    positive = read_gzip_csv("data/interim/positive_cases.csv.gz")
    dataset = read_gzip_csv("data/processed/weather_disease_multiclass.csv.gz")
    train = read_gzip_csv("data/splits/train.csv.gz")
    validation = read_gzip_csv("data/splits/validation.csv.gz")
    test = read_gzip_csv("data/splits/test.csv.gz")

    expected_cases = int(positive["case_count"].sum())
    assert int(dataset["case_count"].sum()) == expected_cases
    assert sum(int(frame["case_count"].sum()) for frame in (train, validation, test)) == expected_cases
    assert len(dataset) == len(positive)
    assert (dataset["case_count"] > 0).all()
    assert "has_case" not in dataset.columns


def test_generated_splits_do_not_share_dates() -> None:
    frames = [
        read_gzip_csv("data/splits/train.csv.gz"),
        read_gzip_csv("data/splits/validation.csv.gz"),
        read_gzip_csv("data/splits/test.csv.gz"),
    ]
    date_sets = [set(frame["date"]) for frame in frames]
    assert not date_sets[0] & date_sets[1]
    assert not date_sets[0] & date_sets[2]
    assert not date_sets[1] & date_sets[2]


def test_generated_schema_has_no_leakage_or_personal_columns() -> None:
    dataset = read_gzip_csv("data/processed/weather_disease_multiclass.csv.gz")
    metadata = json.loads(
        (PROJECT_ROOT / "data/processed/dataset_metadata.json").read_text(encoding="utf-8")
    )
    assert "disease_group_id" not in metadata["input_columns"]
    assert metadata["label_column"] == "disease_group_id"
    assert metadata["weight_column"] == "case_count"
    forbidden_tokens = ("address", "dia_chi", "date_of_birth", "birth_date", "ngay_sinh")
    assert not any(
        token in column.lower() for column in dataset.columns for token in forbidden_tokens
    )
    required = {
        "date",
        "age_group",
        "gender",
        "month",
        "season",
        "day_of_year_sin",
        "day_of_year_cos",
        "weather_code",
        "disease_group_id",
        "disease_group_name",
        "report_group_code",
        "case_count",
    }
    assert required.issubset(dataset.columns)
    assert not dataset[list(required - {"report_group_code"})].isna().any().any()


def test_incomplete_windows_only_occur_before_enough_history_exists() -> None:
    dataset = read_gzip_csv("data/processed/weather_disease_multiclass.csv.gz")
    weather = read_gzip_csv("data/interim/weather_daily_features_v2.csv.gz")
    dataset["date"] = pd.to_datetime(dataset["date"])
    weather_start = pd.to_datetime(weather["date"]).min()
    for window in (1, 3, 7, 14):
        columns = [
            column
            for column in dataset.columns
            if column.endswith(f"_{window}d")
        ]
        eligible = dataset["date"] >= weather_start + pd.DateOffset(days=window - 1)
        assert columns
        assert not dataset.loc[eligible, columns].isna().any().any()

    metadata = json.loads(
        (PROJECT_ROOT / "data/processed/dataset_metadata.json").read_text(encoding="utf-8")
    )
    assert all(
        values["unexpected_missing_rows_after_full_history"] == 0
        for values in metadata["incomplete_weather_windows"].values()
    )


def test_generated_dataset_is_stably_sorted() -> None:
    dataset = read_gzip_csv("data/processed/weather_disease_multiclass.csv.gz")
    comparable = dataset.copy()
    comparable["disease_group_id"] = comparable["disease_group_id"].astype(str)
    sorted_dataset = comparable.sort_values(
        ["date", "age_group", "gender", "disease_group_id"], kind="mergesort"
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(comparable.reset_index(drop=True), sorted_dataset)
