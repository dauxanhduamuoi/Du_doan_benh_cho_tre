from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.baseline import FrequencyRankingBaseline
from src.data_pipeline import (
    age_to_group,
    build_sparse_targets,
    build_weather_features,
    split_anchor_dates_with_purge,
)
from src.metrics import ndcg_at_k, recall_at_k, reciprocal_rank


def _daily_weather(days: int = 30) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    values = np.arange(1, days + 1, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "weather_code_daily": np.zeros(days),
            "temperature_mean_daily": values,
            "temperature_max_daily": values + 2,
            "temperature_min_daily": values - 2,
            "humidity_mean_daily": values + 50,
            "humidity_max_daily": values + 55,
            "humidity_min_daily": values + 45,
            "wind_speed_mean_daily": values / 10,
            "wind_speed_max_daily": values / 5,
            "precipitation_sum_daily": values,
            "rain_sum_daily": values,
            "wind_gust_max_daily": values / 4,
        }
    )


def test_raw_month_is_age_month_fallback_not_calendar_month() -> None:
    groups = age_to_group(pd.Series([0 / 12, 11 / 12, 12 / 12, 72 / 12, np.nan]))
    assert groups.iloc[0] == groups.iloc[1]
    assert groups.iloc[2] != groups.iloc[0]
    assert groups.iloc[3] != groups.iloc[2]
    assert "rõ" in groups.iloc[4] or "rÃµ" in groups.iloc[4]


def test_weather_current_3d_7d_use_only_d_and_past() -> None:
    daily = _daily_weather()
    features, provenance, _ = build_weather_features(daily)
    row = features.loc[features["anchor_date"] == pd.Timestamp("2024-01-07")].iloc[0]
    assert row["temperature_mean_current"] == 7
    assert row["temperature_mean_3d"] == pytest.approx((5 + 6 + 7) / 3)
    assert row["precipitation_sum_3d"] == 5 + 6 + 7
    assert row["temperature_mean_7d"] == pytest.approx(sum(range(1, 8)) / 7)
    assert row["precipitation_sum_7d"] == sum(range(1, 8))

    changed_future = daily.copy()
    changed_future.loc[changed_future["date"] > pd.Timestamp("2024-01-07"), "temperature_mean_daily"] = 99_999
    changed, _, _ = build_weather_features(changed_future)
    changed_row = changed.loc[changed["anchor_date"] == pd.Timestamp("2024-01-07")].iloc[0]
    assert changed_row["temperature_mean_current"] == row["temperature_mean_current"]
    assert changed_row["temperature_mean_3d"] == row["temperature_mean_3d"]
    assert changed_row["temperature_mean_7d"] == row["temperature_mean_7d"]

    source = provenance.loc[provenance["anchor_date"] == pd.Timestamp("2024-01-07")].iloc[0]
    assert source["current_start"] == pd.Timestamp("2024-01-07")
    assert source["current_end"] == pd.Timestamp("2024-01-07")
    assert source["lookback_3d_start"] == pd.Timestamp("2024-01-05")
    assert source["lookback_3d_end"] == pd.Timestamp("2024-01-07")
    assert source["lookback_7d_start"] == pd.Timestamp("2024-01-01")
    assert source["lookback_7d_end"] == pd.Timestamp("2024-01-07")


def test_h3_h7_h14_exact_boundaries_and_monotonic_counts() -> None:
    dates = pd.date_range("2024-01-10", periods=15, freq="D")
    daily_cases = pd.DataFrame(
        {
            "date": dates,
            "age_group": ["1-5"] * len(dates),
            "gender": ["Nam"] * len(dates),
            "disease_group_id": ["A"] * len(dates),
            "case_count_day": np.arange(1, len(dates) + 1),
        }
    )
    contexts = pd.DataFrame(
        {
            "query_id": ["Q1"],
            "anchor_date": [pd.Timestamp("2024-01-10")],
            "age_group": ["1-5"],
            "gender": ["Nam"],
        }
    )
    targets = build_sparse_targets(daily_cases, contexts)
    row = targets.iloc[0]
    assert row["case_count_h3"] == sum(range(1, 4))
    assert row["case_count_h7"] == sum(range(1, 8))
    assert row["case_count_h14"] == sum(range(1, 15))
    assert row["case_count_h3"] <= row["case_count_h7"] <= row["case_count_h14"]
    assert row["has_case_h3"] == row["has_case_h7"] == row["has_case_h14"] == 1


def test_temporal_split_has_exact_h14_purge() -> None:
    dates = pd.date_range("2023-01-01", periods=150, freq="D")
    split = split_anchor_dates_with_purge(dates, purge_gap_days=13)
    assert len(split["purge_train_validation"]) == 13
    assert len(split["purge_validation_test"]) == 13
    assert split["train"].max() + pd.to_timedelta(13, unit="D") < split["validation"].min()
    assert split["validation"].max() + pd.to_timedelta(13, unit="D") < split["test"].min()
    assert not (set(split["train"]) & set(split["validation"]) & set(split["test"]))


def test_multilabel_metrics_count_two_of_three_positives() -> None:
    positives = ["A", "B", "C"]
    ranking = ["A", "X", "C", "Y", "Z"]
    assert recall_at_k(positives, ranking, 5) == pytest.approx(2 / 3)
    assert 0 < ndcg_at_k(positives, ranking, 5) < 1
    assert reciprocal_rank(positives, ranking) == 1.0


def test_baseline_uses_train_only_and_hierarchical_frequency() -> None:
    contexts = pd.DataFrame(
        {
            "query_id": ["Q1", "Q2", "Q3"],
            "age_group": ["1-5", "1-5", "6-10"],
            "gender": ["Nam", "Nam", "Nữ"],
            "month": [1, 1, 2],
        }
    )
    targets = pd.DataFrame(
        {
            "query_id": ["Q1", "Q2", "Q3"],
            "disease_group_id": ["A", "B", "C"],
            "case_count_h3": [5, 2, 9],
            "case_count_h7": [5, 2, 9],
            "case_count_h14": [5, 2, 9],
        }
    )
    baseline = FrequencyRankingBaseline.fit_train(
        contexts, targets, ["A", "B", "C", "D"], 3, split_name="train"
    )
    assert baseline.rank(contexts.iloc[0], top_k=2) == ["A", "B"]
    with pytest.raises(ValueError, match="train split"):
        FrequencyRankingBaseline.fit_train(
            contexts, targets, ["A", "B", "C"], 3, split_name="validation"
        )
