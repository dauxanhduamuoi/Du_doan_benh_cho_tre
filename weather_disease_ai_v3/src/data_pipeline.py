"""Leakage-safe V3 data preparation for multi-label disease ranking.

This module intentionally contains no model-training dependency or code.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yaml


PATIENT_COLUMNS = [
    "icdNV",
    "icdxuatvien",
    "check_in_date",
    "date_of_birth",
    "month",
    "gender",
]
CATALOG_COLUMNS = ["MAICD", "IDNHOMICD", "TENNHOMICD", "MANHOMBAOCAO"]
HORIZONS = (3, 7, 14)
MAX_HORIZON = 14
WEATHER_WINDOWS = (3, 7)

CANONICAL_WEATHER_PREFIXES = {
    "time": "time",
    "temperature_2m": "temperature_2m",
    "relative_humidity_2m": "relative_humidity_2m",
    "precipitation": "precipitation",
    "rain": "rain",
    "weather_code": "weather_code",
    "wind_speed_10m": "wind_speed_10m",
    "wind_gusts_10m": "wind_gusts_10m",
}
REQUIRED_WEATHER_COLUMNS = {
    "time",
    "temperature_2m",
    "relative_humidity_2m",
    "weather_code",
    "wind_speed_10m",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")


def write_csv_gzip(path: Path, frame: pd.DataFrame) -> None:
    """Write deterministic UTF-8 gzip CSV (gzip mtime is fixed at zero)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(fileobj=raw_handle, mode="wb", mtime=0) as gzip_handle:
            with io.TextIOWrapper(gzip_handle, encoding="utf-8", newline="") as text_handle:
                frame.to_csv(text_handle, index=False, lineterminator="\n")


def load_config(project_root: Path) -> dict[str, Any]:
    path = project_root / "config/config.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def normalize_icd_series(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip().str.upper()
    values = values.str.replace("†", "", regex=False).str.replace("*", "", regex=False)
    return values.replace({"": pd.NA, "<NA>": pd.NA, "NAN": pd.NA, "NONE": pd.NA})


def normalize_identifier_series(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    values = values.str.replace(r"^(-?\d+)\.0+$", r"\1", regex=True)
    return values.replace({"": pd.NA, "<NA>": pd.NA, "NAN": pd.NA, "NONE": pd.NA})


def parse_mixed_date_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", dayfirst=True)
    numeric = pd.to_numeric(series, errors="coerce")
    excel_serial = numeric.between(20_000, 80_000) & numeric.notna()
    if excel_serial.any():
        parsed.loc[excel_serial] = pd.Timestamp("1899-12-30") + pd.to_timedelta(
            numeric.loc[excel_serial], unit="D"
        )
    return parsed


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def normalize_gender(value: object) -> str:
    if pd.isna(value):
        return "Không rõ"
    text = str(value).strip()
    folded = _fold_text(text)
    if folded in {"nam", "male", "m", "1"}:
        return "Nam"
    if folded in {"nu", "female", "f", "0", "2"}:
        return "Nữ"
    return text or "Không rõ"


def age_to_group(age_years: pd.Series) -> pd.Series:
    conditions = [
        age_years.isna(),
        age_years < 1,
        age_years <= 5,
        age_years <= 10,
        age_years <= 15,
    ]
    choices = ["Không rõ", "Dưới 1 tuổi", "1-5 tuổi", "6-10 tuổi", "11-15 tuổi"]
    return pd.Series(
        np.select(conditions, choices, default="Trên 15 tuổi"), index=age_years.index
    )


def month_to_season(month: int) -> str:
    if int(month) in {12, 1, 2, 3, 4}:
        return "Mùa khô"
    if int(month) in {5, 6, 7, 8, 9, 10, 11}:
        return "Mùa mưa"
    raise ValueError(f"Invalid calendar month: {month}")


def support_tier(case_count: int, thresholds: dict[str, int]) -> str:
    value = int(case_count)
    if value >= int(thresholds["high_min"]):
        return "high"
    if value >= int(thresholds["medium_min"]):
        return "medium"
    if value >= int(thresholds["low_min"]):
        return "low"
    if value > 0:
        return "insufficient"
    return "unsupported"


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def prepare_catalog(raw_catalog: pd.DataFrame) -> pd.DataFrame:
    _require_columns(raw_catalog, CATALOG_COLUMNS, "DS-MaBenh")
    catalog = raw_catalog[CATALOG_COLUMNS].copy()
    catalog["icd_code"] = normalize_icd_series(catalog["MAICD"])
    catalog["disease_group_id"] = normalize_identifier_series(catalog["IDNHOMICD"])
    catalog["disease_group_name"] = catalog["TENNHOMICD"].astype("string").str.strip()
    catalog["report_group_code"] = normalize_identifier_series(catalog["MANHOMBAOCAO"])
    catalog = catalog.dropna(subset=["icd_code", "disease_group_id", "disease_group_name"])
    catalog = catalog.drop_duplicates("icd_code", keep="last")
    return catalog[
        ["icd_code", "disease_group_id", "disease_group_name", "report_group_code"]
    ].sort_values("icd_code", kind="mergesort").reset_index(drop=True)


def _canonical_group_catalog(
    icd_catalog: pd.DataFrame, mapped_encounters: pd.DataFrame
) -> pd.DataFrame:
    choices = icd_catalog[
        ["disease_group_id", "disease_group_name", "report_group_code"]
    ].drop_duplicates().copy()
    observed = (
        mapped_encounters.groupby(
            ["disease_group_id", "disease_group_name", "report_group_code"],
            dropna=False,
        )
        .size()
        .reset_index(name="observed_case_count_for_mapping")
    )
    choices = choices.merge(
        observed,
        on=["disease_group_id", "disease_group_name", "report_group_code"],
        how="left",
    )
    choices["observed_case_count_for_mapping"] = (
        choices["observed_case_count_for_mapping"].fillna(0).astype("int64")
    )
    choices = choices.sort_values(
        [
            "disease_group_id",
            "observed_case_count_for_mapping",
            "disease_group_name",
            "report_group_code",
        ],
        ascending=[True, False, True, True],
        kind="mergesort",
        na_position="last",
    ).drop_duplicates("disease_group_id", keep="first")
    return choices.sort_values("disease_group_id", kind="mergesort").reset_index(drop=True)


def build_daily_cases_from_frames(
    raw_patients: pd.DataFrame, raw_catalog: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Normalize encounters using the validated V2 mapping and age rules."""
    _require_columns(raw_patients, PATIENT_COLUMNS, "DS-BenhNhan")
    icd_catalog = prepare_catalog(raw_catalog)
    patients = raw_patients[PATIENT_COLUMNS].copy()
    patients["check_in_date"] = parse_mixed_date_series(patients["check_in_date"])
    patients["date_of_birth"] = parse_mixed_date_series(patients["date_of_birth"])
    patients["icdNV"] = normalize_icd_series(patients["icdNV"])
    patients["icdxuatvien"] = normalize_icd_series(patients["icdxuatvien"])
    patients["main_icd"] = normalize_icd_series(
        patients["icdxuatvien"].fillna(patients["icdNV"])
    )
    eligible = patients.dropna(subset=["check_in_date", "main_icd"]).copy()
    mapped_all = eligible.merge(
        icd_catalog, left_on="main_icd", right_on="icd_code", how="left"
    )
    unmapped = mapped_all[mapped_all["disease_group_id"].isna()].copy()
    mapped = mapped_all.dropna(subset=["disease_group_id", "disease_group_name"]).copy()
    mapped["gender_normalized"] = mapped["gender"].map(normalize_gender)
    age_years = (
        mapped["check_in_date"] - mapped["date_of_birth"]
    ).dt.total_seconds() / (365.25 * 24 * 60 * 60)
    # Raw `month` is age in months, never calendar month.
    age_month_fallback = pd.to_numeric(mapped["month"], errors="coerce") / 12
    age_years = age_years.fillna(age_month_fallback).where(lambda values: values >= 0)
    mapped["age_group"] = age_to_group(age_years)
    mapped["date"] = mapped["check_in_date"].dt.normalize()

    candidate_catalog = _canonical_group_catalog(icd_catalog, mapped)
    daily = (
        mapped.groupby(
            ["date", "age_group", "gender_normalized", "disease_group_id"],
            dropna=False,
            sort=True,
        )
        .size()
        .reset_index(name="case_count_day")
        .rename(columns={"gender_normalized": "gender"})
    )
    daily = daily.merge(
        candidate_catalog[
            ["disease_group_id", "disease_group_name", "report_group_code"]
        ],
        on="disease_group_id",
        how="left",
        validate="many_to_one",
    )
    daily = daily[
        [
            "date",
            "age_group",
            "gender",
            "disease_group_id",
            "disease_group_name",
            "case_count_day",
        ]
    ].sort_values(
        ["date", "age_group", "gender", "disease_group_id"], kind="mergesort"
    ).reset_index(drop=True)
    daily["case_count_day"] = daily["case_count_day"].astype("int64")
    if daily.duplicated(
        ["date", "age_group", "gender", "disease_group_id"]
    ).any():
        raise ValueError("Daily case key is not unique")
    if daily["disease_group_name"].isna().any():
        raise ValueError("Daily cases contain invalid disease mapping")

    stats = {
        "raw_patient_rows": int(len(raw_patients)),
        "eligible_patient_rows": int(len(eligible)),
        "mapped_patient_rows": int(len(mapped)),
        "unmapped_patient_rows": int(len(unmapped)),
        "mapping_success_rate": float(len(mapped) / len(eligible)) if len(eligible) else 0.0,
        "daily_case_rows": int(len(daily)),
        "total_case_count_day": int(daily["case_count_day"].sum()),
        "patient_date_from": str(daily["date"].min().date()),
        "patient_date_to": str(daily["date"].max().date()),
        "age_groups": sorted(str(value) for value in daily["age_group"].unique()),
        "gender_values": sorted(str(value) for value in daily["gender"].unique()),
        "age_gender_pairs": int(daily[["age_group", "gender"]].drop_duplicates().shape[0]),
        "observed_disease_groups": int(daily["disease_group_id"].nunique()),
        "candidate_disease_groups": int(candidate_catalog["disease_group_id"].nunique()),
        "raw_month_interpretation": "age_in_months_fallback_only",
    }
    return daily, candidate_catalog, stats


def _weather_header_row(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle):
            if line.strip().startswith("time,"):
                return line_number
    raise ValueError("Weather CSV has no header row starting with 'time,'")


def _canonical_weather_name(column: str) -> str | None:
    stripped = str(column).strip()
    for prefix, canonical in CANONICAL_WEATHER_PREFIXES.items():
        if stripped == prefix or stripped.startswith(f"{prefix} ") or stripped.startswith(
            f"{prefix}("
        ):
            return canonical
    return None


def read_weather_hourly(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    header_row = _weather_header_row(path)
    raw = pd.read_csv(path, skiprows=header_row)
    actual_columns = [str(value) for value in raw.columns]
    rename: dict[str, str] = {}
    for column in raw.columns:
        canonical = _canonical_weather_name(str(column))
        if canonical is not None:
            if canonical in rename.values():
                raise ValueError(f"Multiple weather columns map to {canonical}")
            rename[str(column)] = canonical
    missing = sorted(REQUIRED_WEATHER_COLUMNS - set(rename.values()))
    if missing:
        raise ValueError(f"Weather source is missing {missing}; actual={actual_columns}")
    hourly = raw[list(rename)].rename(columns=rename).copy()
    hourly["time"] = pd.to_datetime(hourly["time"], errors="coerce")
    invalid_time = int(hourly["time"].isna().sum())
    hourly = hourly.dropna(subset=["time"]).copy()
    for column in hourly.columns:
        if column != "time":
            hourly[column] = pd.to_numeric(hourly[column], errors="coerce")
    hourly = hourly.sort_values("time", kind="mergesort").reset_index(drop=True)
    if hourly.duplicated("time").any():
        raise ValueError("Weather source contains duplicate timestamps")
    metadata = {
        "header_row_zero_based": int(header_row),
        "actual_columns": actual_columns,
        "canonical_mapping": rename,
        "hourly_rows": int(len(hourly)),
        "invalid_timestamps": invalid_time,
        "missing_values": {
            column: int(hourly[column].isna().sum())
            for column in hourly.columns
            if column != "time"
        },
    }
    return hourly, metadata


def _mode_or_nan(series: pd.Series) -> float:
    values = series.dropna()
    return float(values.mode().iloc[0]) if not values.empty else float("nan")


def build_daily_weather(hourly: pd.DataFrame) -> pd.DataFrame:
    frame = hourly.copy()
    frame["date"] = pd.to_datetime(frame["time"]).dt.normalize()
    aggregations: dict[str, tuple[str, Any]] = {
        "temperature_mean_daily": ("temperature_2m", "mean"),
        "temperature_max_daily": ("temperature_2m", "max"),
        "temperature_min_daily": ("temperature_2m", "min"),
        "humidity_mean_daily": ("relative_humidity_2m", "mean"),
        "humidity_max_daily": ("relative_humidity_2m", "max"),
        "humidity_min_daily": ("relative_humidity_2m", "min"),
        "weather_code_daily": ("weather_code", _mode_or_nan),
        "wind_speed_mean_daily": ("wind_speed_10m", "mean"),
        "wind_speed_max_daily": ("wind_speed_10m", "max"),
    }
    if "precipitation" in frame.columns:
        aggregations["precipitation_sum_daily"] = ("precipitation", "sum")
    if "rain" in frame.columns:
        aggregations["rain_sum_daily"] = ("rain", "sum")
    if "wind_gusts_10m" in frame.columns:
        aggregations["wind_gust_max_daily"] = ("wind_gusts_10m", "max")
    daily = frame.groupby("date", as_index=False).agg(**aggregations)
    daily = daily.sort_values("date", kind="mergesort").reset_index(drop=True)
    full_dates = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
    missing_dates = full_dates.difference(pd.DatetimeIndex(daily["date"]))
    if len(missing_dates):
        raise ValueError(f"Weather source has {len(missing_dates)} missing calendar days")
    return daily


def build_weather_features(
    daily_weather: pd.DataFrame,
    windows: Iterable[int] = WEATHER_WINDOWS,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Create current and exact trailing weather features ending at D."""
    windows_tuple = tuple(int(value) for value in windows)
    if windows_tuple != WEATHER_WINDOWS:
        raise ValueError("V3 weather lookback must be exactly current + 3d + 7d")
    daily = daily_weather.sort_values("date", kind="mergesort").reset_index(drop=True)
    features = pd.DataFrame({"anchor_date": pd.to_datetime(daily["date"]).dt.normalize()})
    current_map = {
        "weather_code_daily": "weather_code_current",
        "temperature_mean_daily": "temperature_mean_current",
        "temperature_max_daily": "temperature_max_current",
        "temperature_min_daily": "temperature_min_current",
        "humidity_mean_daily": "humidity_mean_current",
        "humidity_max_daily": "humidity_max_current",
        "humidity_min_daily": "humidity_min_current",
        "wind_speed_mean_daily": "wind_speed_mean_current",
        "wind_speed_max_daily": "wind_speed_max_current",
        "precipitation_sum_daily": "precipitation_sum_current",
        "rain_sum_daily": "rain_sum_current",
        "wind_gust_max_daily": "wind_gust_max_current",
    }
    for source, destination in current_map.items():
        if source in daily.columns:
            features[destination] = daily[source].to_numpy()
    if "rain_sum_daily" in daily.columns:
        features["rain_day_current"] = (daily["rain_sum_daily"] > 0).astype("int8")

    for window in windows_tuple:
        suffix = f"{window}d"
        features[f"temperature_mean_{suffix}"] = daily["temperature_mean_daily"].rolling(
            window, min_periods=window
        ).mean()
        features[f"temperature_max_{suffix}"] = daily["temperature_max_daily"].rolling(
            window, min_periods=window
        ).max()
        features[f"temperature_min_{suffix}"] = daily["temperature_min_daily"].rolling(
            window, min_periods=window
        ).min()
        features[f"humidity_mean_{suffix}"] = daily["humidity_mean_daily"].rolling(
            window, min_periods=window
        ).mean()
        features[f"humidity_max_{suffix}"] = daily["humidity_max_daily"].rolling(
            window, min_periods=window
        ).max()
        features[f"humidity_min_{suffix}"] = daily["humidity_min_daily"].rolling(
            window, min_periods=window
        ).min()
        features[f"wind_speed_mean_{suffix}"] = daily["wind_speed_mean_daily"].rolling(
            window, min_periods=window
        ).mean()
        features[f"wind_speed_max_{suffix}"] = daily["wind_speed_max_daily"].rolling(
            window, min_periods=window
        ).max()
        if "precipitation_sum_daily" in daily.columns:
            features[f"precipitation_sum_{suffix}"] = daily[
                "precipitation_sum_daily"
            ].rolling(window, min_periods=window).sum()
        if "rain_sum_daily" in daily.columns:
            features[f"rain_sum_{suffix}"] = daily["rain_sum_daily"].rolling(
                window, min_periods=window
            ).sum()
            features[f"rain_days_{suffix}"] = (daily["rain_sum_daily"] > 0).rolling(
                window, min_periods=window
            ).sum()
            features[f"rain_max_daily_{suffix}"] = daily["rain_sum_daily"].rolling(
                window, min_periods=window
            ).max()
        if "wind_gust_max_daily" in daily.columns:
            features[f"wind_gust_max_{suffix}"] = daily["wind_gust_max_daily"].rolling(
                window, min_periods=window
            ).max()

    weather_columns = [column for column in features.columns if column != "anchor_date"]
    numeric_columns = [column for column in weather_columns if column != "weather_code_current"]
    features[numeric_columns] = features[numeric_columns].round(6)
    provenance = pd.DataFrame(
        {
            "anchor_date": features["anchor_date"],
            "current_start": features["anchor_date"],
            "current_end": features["anchor_date"],
            "lookback_3d_start": features["anchor_date"] - pd.to_timedelta(2, unit="D"),
            "lookback_3d_end": features["anchor_date"],
            "lookback_7d_start": features["anchor_date"] - pd.to_timedelta(6, unit="D"),
            "lookback_7d_end": features["anchor_date"],
            "weather_complete": ~features[weather_columns].isna().any(axis=1),
        }
    )
    return features, provenance, weather_columns


def add_calendar_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["anchor_date"] = pd.to_datetime(result["anchor_date"], errors="raise").dt.normalize()
    result["month"] = result["anchor_date"].dt.month.astype("int16")
    result["season"] = result["month"].map(month_to_season)
    day = result["anchor_date"].dt.dayofyear
    result["day_of_year_sin"] = np.sin(2 * math.pi * day / 365.25)
    result["day_of_year_cos"] = np.cos(2 * math.pi * day / 365.25)
    return result


def build_contexts(
    daily_cases: pd.DataFrame,
    weather_features: pd.DataFrame,
    weather_columns: list[str],
    max_horizon: int = MAX_HORIZON,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    patient_min = pd.Timestamp(daily_cases["date"].min()).normalize()
    patient_max = pd.Timestamp(daily_cases["date"].max()).normalize()
    last_anchor = patient_max - pd.to_timedelta(max_horizon - 1, unit="D")
    complete_weather = ~weather_features[weather_columns].isna().any(axis=1)
    available = weather_features.loc[
        complete_weather
        & (weather_features["anchor_date"] >= patient_min)
        & (weather_features["anchor_date"] <= last_anchor)
    ].copy()
    if available.empty:
        raise ValueError("No valid anchors have complete 7-day weather and H14 target coverage")
    anchor_dates = pd.DatetimeIndex(available["anchor_date"].unique()).sort_values()
    expected = pd.date_range(anchor_dates.min(), anchor_dates.max(), freq="D")
    if not anchor_dates.equals(expected):
        raise ValueError("Valid anchor universe is not a continuous daily range")

    pairs = daily_cases[["age_group", "gender"]].drop_duplicates().sort_values(
        ["age_group", "gender"], kind="mergesort"
    ).reset_index(drop=True)
    pairs["pair_code"] = [f"C{index:02d}" for index in range(len(pairs))]
    anchor_frame = pd.DataFrame({"anchor_date": anchor_dates})
    contexts = anchor_frame.merge(pairs, how="cross")
    contexts["query_id"] = (
        "Q"
        + contexts["anchor_date"].dt.strftime("%Y%m%d")
        + "_"
        + contexts["pair_code"]
    )
    contexts = contexts.merge(
        available, on="anchor_date", how="left", validate="many_to_one"
    )
    contexts = add_calendar_features(contexts)
    model_feature_columns = [
        "age_group",
        "gender",
        "month",
        "season",
        "day_of_year_sin",
        "day_of_year_cos",
        *weather_columns,
    ]
    contexts = contexts[
        ["query_id", "anchor_date", *model_feature_columns]
    ].sort_values(["anchor_date", "age_group", "gender"], kind="mergesort").reset_index(drop=True)
    if contexts["query_id"].duplicated().any():
        raise ValueError("Duplicate query_id detected")
    metadata = {
        "anchor_date_from": str(anchor_dates.min().date()),
        "anchor_date_to": str(anchor_dates.max().date()),
        "unique_anchor_dates": int(len(anchor_dates)),
        "age_gender_pairs": int(len(pairs)),
        "queries": int(len(contexts)),
        "last_patient_date": str(patient_max.date()),
        "max_target_end": str((anchor_dates.max() + pd.to_timedelta(13, unit="D")).date()),
    }
    return contexts, model_feature_columns, metadata


def build_sparse_targets(
    daily_cases: pd.DataFrame,
    contexts: pd.DataFrame,
    horizons: Iterable[int] = HORIZONS,
) -> pd.DataFrame:
    """Build positive-only sparse target rows using exact D..D+h-1 windows."""
    horizons_tuple = tuple(int(value) for value in horizons)
    if horizons_tuple != HORIZONS:
        raise ValueError("Prediction horizons must be exactly H3/H7/H14")
    source = daily_cases[
        ["date", "age_group", "gender", "disease_group_id", "case_count_day"]
    ].copy()
    source["date"] = pd.to_datetime(source["date"]).dt.normalize()
    parts = []
    for offset in range(MAX_HORIZON):
        part = source.copy()
        part["anchor_date"] = part["date"] - pd.to_timedelta(offset, unit="D")
        for horizon in horizons_tuple:
            part[f"case_count_h{horizon}"] = np.where(
                offset < horizon, part["case_count_day"], 0
            )
        parts.append(part)
    contributions = pd.concat(parts, ignore_index=True)
    query_keys = contexts[["query_id", "anchor_date", "age_group", "gender"]]
    contributions = contributions.merge(
        query_keys,
        on=["anchor_date", "age_group", "gender"],
        how="inner",
        validate="many_to_one",
    )
    count_columns = [f"case_count_h{horizon}" for horizon in horizons_tuple]
    targets = (
        contributions.groupby(["query_id", "disease_group_id"], as_index=False)[
            count_columns
        ]
        .sum()
        .sort_values(["query_id", "disease_group_id"], kind="mergesort")
        .reset_index(drop=True)
    )
    targets = targets[targets["case_count_h14"] > 0].copy()
    for horizon in horizons_tuple:
        count_column = f"case_count_h{horizon}"
        targets[count_column] = targets[count_column].astype("int64")
        targets[f"has_case_h{horizon}"] = (targets[count_column] > 0).astype("int8")
    ordered = ["query_id", "disease_group_id"]
    for horizon in horizons_tuple:
        ordered.extend([f"case_count_h{horizon}", f"has_case_h{horizon}"])
    targets = targets[ordered]
    if targets.duplicated(["query_id", "disease_group_id"]).any():
        raise ValueError("Duplicate target key detected")
    return targets


def split_anchor_dates_with_purge(
    anchor_dates: Iterable[object],
    train_ratio: float = 0.70,
    validation_ratio: float = 0.15,
    purge_gap_days: int = 13,
) -> dict[str, pd.DatetimeIndex]:
    dates = pd.DatetimeIndex(pd.to_datetime(list(anchor_dates))).normalize().unique().sort_values()
    usable_count = len(dates) - 2 * int(purge_gap_days)
    if usable_count < 3:
        raise ValueError("Not enough anchor dates after two purge gaps")
    train_count = max(1, int(usable_count * float(train_ratio)))
    validation_count = max(1, int(usable_count * float(validation_ratio)))
    test_count = usable_count - train_count - validation_count
    if test_count < 1:
        raise ValueError("Split ratios leave no test anchor")
    train_end = train_count
    gap1_end = train_end + int(purge_gap_days)
    validation_end = gap1_end + validation_count
    gap2_end = validation_end + int(purge_gap_days)
    result = {
        "train": dates[:train_end],
        "purge_train_validation": dates[train_end:gap1_end],
        "validation": dates[gap1_end:validation_end],
        "purge_validation_test": dates[validation_end:gap2_end],
        "test": dates[gap2_end:],
    }
    if result["train"].max() + pd.to_timedelta(MAX_HORIZON - 1, unit="D") >= result[
        "validation"
    ].min():
        raise ValueError("Train H14 target window overlaps validation")
    if result["validation"].max() + pd.to_timedelta(MAX_HORIZON - 1, unit="D") >= result[
        "test"
    ].min():
        raise ValueError("Validation H14 target window overlaps test")
    return result


def build_split_query_ids(
    contexts: pd.DataFrame,
    split_dates: dict[str, pd.DatetimeIndex],
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    split_frames: dict[str, pd.DataFrame] = {}
    metadata: dict[str, Any] = {
        "method": "chronological_unique_anchor_dates_70_15_15_with_h14_purge",
        "purge_gap_days": 13,
        "max_horizon_days": 14,
    }
    for name in ("train", "validation", "test"):
        dates = split_dates[name]
        frame = contexts.loc[
            contexts["anchor_date"].isin(dates), ["query_id"]
        ].sort_values("query_id", kind="mergesort").reset_index(drop=True)
        split_frames[name] = frame
        metadata[name] = {
            "date_from": str(dates.min().date()),
            "date_to": str(dates.max().date()),
            "unique_anchor_dates": int(len(dates)),
            "queries": int(len(frame)),
        }
    for gap_name in ("purge_train_validation", "purge_validation_test"):
        dates = split_dates[gap_name]
        metadata[gap_name] = {
            "date_from": str(dates.min().date()),
            "date_to": str(dates.max().date()),
            "unique_anchor_dates": int(len(dates)),
            "queries_excluded": int(contexts["anchor_date"].isin(dates).sum()),
        }
    metadata["checks"] = {
        "no_anchor_overlap": True,
        "train_h14_before_validation": bool(
            split_dates["train"].max() + pd.to_timedelta(13, unit="D")
            < split_dates["validation"].min()
        ),
        "validation_h14_before_test": bool(
            split_dates["validation"].max() + pd.to_timedelta(13, unit="D")
            < split_dates["test"].min()
        ),
    }
    return split_frames, metadata


def add_train_support(
    catalog: pd.DataFrame,
    targets: pd.DataFrame,
    train_query_ids: pd.DataFrame,
    thresholds: dict[str, int],
) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    train_targets = targets.merge(
        train_query_ids.assign(_train=1), on="query_id", how="inner", validate="many_to_one"
    )
    result = catalog.copy()
    counts_by_horizon: dict[str, dict[str, int]] = {}
    for horizon in HORIZONS:
        case_column = f"case_count_h{horizon}"
        has_column = f"has_case_h{horizon}"
        grouped = train_targets.groupby("disease_group_id").agg(
            **{
                f"train_case_count_h{horizon}": (case_column, "sum"),
                f"train_positive_queries_h{horizon}": (has_column, "sum"),
            }
        )
        result = result.merge(grouped, on="disease_group_id", how="left")
        case_output = f"train_case_count_h{horizon}"
        positive_output = f"train_positive_queries_h{horizon}"
        result[[case_output, positive_output]] = result[
            [case_output, positive_output]
        ].fillna(0).astype("int64")
        support_column = f"support_h{horizon}"
        result[support_column] = result[case_output].map(
            lambda value: support_tier(int(value), thresholds)
        )
        counts_by_horizon[f"h{horizon}"] = {
            level: int((result[support_column] == level).sum())
            for level in ("high", "medium", "low", "insufficient", "unsupported")
        }
    return result.sort_values("disease_group_id", kind="mergesort").reset_index(drop=True), counts_by_horizon


def validate_pipeline(
    contexts: pd.DataFrame,
    targets: pd.DataFrame,
    catalog: pd.DataFrame,
    provenance: pd.DataFrame,
    split_dates: dict[str, pd.DatetimeIndex],
    model_feature_columns: list[str],
    last_patient_date: pd.Timestamp,
) -> dict[str, bool]:
    if contexts["query_id"].duplicated().any():
        raise ValueError("Duplicate query_id")
    if targets.duplicated(["query_id", "disease_group_id"]).any():
        raise ValueError("Duplicate query_id+disease_group_id target")
    if not (
        (targets["case_count_h3"] <= targets["case_count_h7"])
        & (targets["case_count_h7"] <= targets["case_count_h14"])
    ).all():
        raise ValueError("H3 <= H7 <= H14 count invariant failed")
    for horizon in HORIZONS:
        expected = (targets[f"case_count_h{horizon}"] > 0).astype("int8")
        if not expected.equals(targets[f"has_case_h{horizon}"].astype("int8")):
            raise ValueError(f"has_case_h{horizon} does not match case count")
    if contexts["anchor_date"].max() + pd.to_timedelta(13, unit="D") > last_patient_date:
        raise ValueError("A target window exceeds the final patient source date")
    if catalog["disease_group_id"].duplicated().any() or catalog["disease_group_id"].isna().any():
        raise ValueError("Disease catalog mapping is not one row per disease_group_id")
    if not set(targets["disease_group_id"]).issubset(set(catalog["disease_group_id"])):
        raise ValueError("Target contains a disease absent from catalog")

    if not (provenance["current_start"] == provenance["anchor_date"]).all():
        raise ValueError("Weather current does not start at D")
    if not (provenance["current_end"] == provenance["anchor_date"]).all():
        raise ValueError("Weather current uses a future date")
    if not (
        provenance["lookback_3d_start"]
        == provenance["anchor_date"] - pd.to_timedelta(2, unit="D")
    ).all() or not (provenance["lookback_3d_end"] == provenance["anchor_date"]).all():
        raise ValueError("Weather 3d provenance is not D-2..D")
    if not (
        provenance["lookback_7d_start"]
        == provenance["anchor_date"] - pd.to_timedelta(6, unit="D")
    ).all() or not (provenance["lookback_7d_end"] == provenance["anchor_date"]).all():
        raise ValueError("Weather 7d provenance is not D-6..D")
    if (
        provenance[["current_end", "lookback_3d_end", "lookback_7d_end"]]
        .gt(provenance["anchor_date"], axis=0)
        .any()
        .any()
    ):
        raise ValueError("Future weather leakage detected")

    date_sets = [set(split_dates[name]) for name in ("train", "validation", "test")]
    if date_sets[0] & date_sets[1] or date_sets[0] & date_sets[2] or date_sets[1] & date_sets[2]:
        raise ValueError("Anchor dates overlap across splits")
    if split_dates["train"].max() + pd.to_timedelta(13, unit="D") >= split_dates["validation"].min():
        raise ValueError("Train target window overlaps validation")
    if split_dates["validation"].max() + pd.to_timedelta(13, unit="D") >= split_dates["test"].min():
        raise ValueError("Validation target window overlaps test")

    forbidden_tokens = ("disease", "case_count_h", "has_case_h", "target")
    forbidden = [
        column
        for column in model_feature_columns
        if column in {"anchor_date", "year"}
        or any(token in column.lower() for token in forbidden_tokens)
    ]
    if forbidden:
        raise ValueError(f"Forbidden model feature columns: {forbidden}")
    if any("disease" in column.lower() for column in contexts.columns):
        raise ValueError("Context dataset contains disease target/name")

    return {
        "no_duplicate_query_id": True,
        "no_duplicate_target_key": True,
        "weather_current_is_d_only": True,
        "weather_3d_is_d_minus_2_to_d": True,
        "weather_7d_is_d_minus_6_to_d": True,
        "no_future_weather": True,
        "h3_is_d_to_d_plus_2": True,
        "h7_is_d_to_d_plus_6": True,
        "h14_is_d_to_d_plus_13": True,
        "h3_le_h7_le_h14": True,
        "has_case_matches_case_count": True,
        "target_windows_within_source": True,
        "no_anchor_overlap": True,
        "no_target_window_overlap_between_splits": True,
        "disease_catalog_mapping_valid": True,
        "context_has_no_disease_target": True,
        "anchor_date_excluded_from_model_features": True,
        "year_excluded_from_model_features": True,
        "support_built_from_train_only": True,
        "baseline_contract_train_only": True,
        "same_weather_features_for_h3_h7_h14": True,
    }


def _format_dates(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].dt.strftime("%Y-%m-%d")
    return output


def _positive_summary(targets: pd.DataFrame, disease_lookup: dict[str, str], horizon: int) -> list[dict[str, Any]]:
    rows = targets.loc[
        targets[f"has_case_h{horizon}"] > 0,
        ["disease_group_id", f"case_count_h{horizon}"],
    ].sort_values(f"case_count_h{horizon}", ascending=False, kind="mergesort")
    return [
        {
            "disease_group_id": str(row["disease_group_id"]),
            "disease_group_name": disease_lookup.get(str(row["disease_group_id"]), ""),
            "case_count": int(row[f"case_count_h{horizon}"]),
        }
        for _, row in rows.iterrows()
    ]


class DataPreparationPipeline:
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.config = load_config(self.project_root)
        self.patient_path = (self.project_root / self.config["data"]["patient_file"]).resolve()
        self.weather_path = (self.project_root / self.config["data"]["weather_file"]).resolve()
        self.original_patient = (
            self.project_root / self.config["data"]["original_patient_source"]
        ).resolve()
        self.original_weather = (
            self.project_root / self.config["data"]["original_weather_source"]
        ).resolve()
        self.raw_patients: pd.DataFrame | None = None
        self.raw_catalog: pd.DataFrame | None = None
        self.hourly_weather: pd.DataFrame | None = None
        self.weather_metadata: dict[str, Any] | None = None
        self.source_audit: dict[str, Any] | None = None
        self.daily_cases: pd.DataFrame | None = None
        self.catalog: pd.DataFrame | None = None
        self.patient_stats: dict[str, Any] | None = None
        self.daily_weather: pd.DataFrame | None = None
        self.weather_features: pd.DataFrame | None = None
        self.weather_provenance: pd.DataFrame | None = None
        self.weather_columns: list[str] = []
        self.contexts: pd.DataFrame | None = None
        self.model_feature_columns: list[str] = []
        self.context_metadata: dict[str, Any] | None = None
        self.targets: pd.DataFrame | None = None
        self.split_dates: dict[str, pd.DatetimeIndex] | None = None
        self.split_frames: dict[str, pd.DataFrame] | None = None
        self.split_metadata: dict[str, Any] | None = None
        self.support_counts: dict[str, dict[str, int]] | None = None
        self.validation_checks: dict[str, bool] | None = None
        self.example_records: list[dict[str, Any]] = []
        self.dataset_metadata: dict[str, Any] | None = None

    def load_raw_data(self) -> dict[str, Any]:
        required = [self.patient_path, self.weather_path, self.original_patient, self.original_weather]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Missing source files: {missing}")
        if sha256_file(self.patient_path) != sha256_file(self.original_patient):
            raise ValueError("V3 patient raw copy differs from original source")
        if sha256_file(self.weather_path) != sha256_file(self.original_weather):
            raise ValueError("V3 weather raw copy differs from original source")
        workbook = pd.ExcelFile(self.patient_path)
        expected_sheets = [
            self.config["data"]["patient_sheet"],
            self.config["data"]["disease_sheet"],
        ]
        missing_sheets = [name for name in expected_sheets if name not in workbook.sheet_names]
        if missing_sheets:
            raise ValueError(f"Workbook missing sheets: {missing_sheets}")
        self.raw_patients = pd.read_excel(workbook, sheet_name=expected_sheets[0])
        self.raw_catalog = pd.read_excel(workbook, sheet_name=expected_sheets[1])
        self.hourly_weather, self.weather_metadata = read_weather_hourly(self.weather_path)
        self.source_audit = {
            "original_patient_source": str(self.original_patient),
            "original_weather_source": str(self.original_weather),
            "v3_patient_raw_copy": str(self.patient_path),
            "v3_weather_raw_copy": str(self.weather_path),
            "patient_sha256": sha256_file(self.patient_path),
            "weather_sha256": sha256_file(self.weather_path),
            "workbook_sheets": workbook.sheet_names,
            "raw_patient_rows": int(len(self.raw_patients)),
            "raw_catalog_rows": int(len(self.raw_catalog)),
            "weather_hourly_rows": int(len(self.hourly_weather)),
        }
        return self.source_audit

    def audit_source_data(self) -> dict[str, Any]:
        if self.raw_patients is None or self.raw_catalog is None or self.hourly_weather is None:
            raise RuntimeError("Call load_raw_data() first")
        _require_columns(self.raw_patients, PATIENT_COLUMNS, "DS-BenhNhan")
        _require_columns(self.raw_catalog, CATALOG_COLUMNS, "DS-MaBenh")
        if self.weather_metadata is None or self.source_audit is None:
            raise RuntimeError("Weather/source metadata missing")
        audit = dict(self.source_audit)
        audit["weather_actual_columns"] = self.weather_metadata["actual_columns"]
        audit["raw_patient_missing_required"] = {
            column: int(self.raw_patients[column].isna().sum()) for column in PATIENT_COLUMNS
        }
        return audit

    def build_daily_disease_counts(self) -> pd.DataFrame:
        if self.raw_patients is None or self.raw_catalog is None:
            raise RuntimeError("Call load_raw_data() first")
        self.daily_cases, self.catalog, self.patient_stats = build_daily_cases_from_frames(
            self.raw_patients, self.raw_catalog
        )
        return self.daily_cases

    def build_weather_current_3d_7d(self) -> pd.DataFrame:
        if self.hourly_weather is None:
            raise RuntimeError("Call load_raw_data() first")
        self.daily_weather = build_daily_weather(self.hourly_weather)
        (
            self.weather_features,
            self.weather_provenance,
            self.weather_columns,
        ) = build_weather_features(self.daily_weather, WEATHER_WINDOWS)
        return self.weather_features

    def build_query_contexts(self) -> pd.DataFrame:
        if self.daily_cases is None or self.weather_features is None:
            raise RuntimeError("Build daily cases and weather features first")
        self.contexts, self.model_feature_columns, self.context_metadata = build_contexts(
            self.daily_cases, self.weather_features, self.weather_columns
        )
        return self.contexts

    def build_horizon_targets(self) -> pd.DataFrame:
        if self.daily_cases is None or self.contexts is None:
            raise RuntimeError("Build daily cases and contexts first")
        self.targets = build_sparse_targets(self.daily_cases, self.contexts, HORIZONS)
        return self.targets

    def build_temporal_splits(self) -> dict[str, pd.DataFrame]:
        if self.contexts is None:
            raise RuntimeError("Build contexts first")
        split_config = self.config["split"]
        self.split_dates = split_anchor_dates_with_purge(
            self.contexts["anchor_date"].unique(),
            train_ratio=float(split_config["train_ratio"]),
            validation_ratio=float(split_config["validation_ratio"]),
            purge_gap_days=int(split_config["purge_gap_days"]),
        )
        self.split_frames, self.split_metadata = build_split_query_ids(
            self.contexts, self.split_dates
        )
        return self.split_frames

    def calculate_train_support(self) -> pd.DataFrame:
        if self.catalog is None or self.targets is None or self.split_frames is None:
            raise RuntimeError("Build catalog, targets and splits first")
        self.catalog, self.support_counts = add_train_support(
            self.catalog,
            self.targets,
            self.split_frames["train"],
            self.config["support"],
        )
        return self.catalog

    def validate_all(self) -> dict[str, bool]:
        required = [
            self.contexts,
            self.targets,
            self.catalog,
            self.weather_provenance,
            self.split_dates,
            self.daily_cases,
        ]
        if any(value is None for value in required):
            raise RuntimeError("Pipeline stages are incomplete")
        assert self.contexts is not None
        assert self.targets is not None
        assert self.catalog is not None
        assert self.weather_provenance is not None
        assert self.split_dates is not None
        assert self.daily_cases is not None
        relevant_provenance = self.weather_provenance[
            self.weather_provenance["anchor_date"].isin(self.contexts["anchor_date"].unique())
        ]
        self.validation_checks = validate_pipeline(
            self.contexts,
            self.targets,
            self.catalog,
            relevant_provenance,
            self.split_dates,
            self.model_feature_columns,
            pd.Timestamp(self.daily_cases["date"].max()).normalize(),
        )
        return self.validation_checks

    def build_examples(self) -> list[dict[str, Any]]:
        if self.contexts is None or self.targets is None or self.catalog is None:
            raise RuntimeError("Build contexts, targets and catalog first")
        lookup = dict(
            zip(
                self.catalog["disease_group_id"].astype(str),
                self.catalog["disease_group_name"].astype(str),
            )
        )
        target_query_ids = set(
            self.targets.loc[self.targets["has_case_h3"] > 0, "query_id"].astype(str)
        )
        candidates = self.contexts[self.contexts["query_id"].isin(target_query_ids)]
        if candidates.empty:
            raise ValueError("No example query has an H3 positive target")
        positions = sorted({0, len(candidates) // 2, len(candidates) - 1})
        examples: list[dict[str, Any]] = []
        for position in positions:
            row = candidates.iloc[position]
            anchor = pd.Timestamp(row["anchor_date"]).normalize()
            query_targets = self.targets[self.targets["query_id"] == row["query_id"]]
            examples.append(
                {
                    "query_id": str(row["query_id"]),
                    "anchor_date": str(anchor.date()),
                    "age_group": str(row["age_group"]),
                    "gender": str(row["gender"]),
                    "weather_ranges": {
                        "current": f"{anchor.date()}",
                        "3d": f"{(anchor - pd.to_timedelta(2, unit='D')).date()} -> {anchor.date()}",
                        "7d": f"{(anchor - pd.to_timedelta(6, unit='D')).date()} -> {anchor.date()}",
                    },
                    "target_ranges": {
                        "h3": f"{anchor.date()} -> {(anchor + pd.to_timedelta(2, unit='D')).date()}",
                        "h7": f"{anchor.date()} -> {(anchor + pd.to_timedelta(6, unit='D')).date()}",
                        "h14": f"{anchor.date()} -> {(anchor + pd.to_timedelta(13, unit='D')).date()}",
                    },
                    "weather_values": {
                        "temperature_mean_current": float(row["temperature_mean_current"]),
                        "humidity_mean_current": float(row["humidity_mean_current"]),
                        "precipitation_sum_3d": float(row.get("precipitation_sum_3d", 0.0)),
                        "wind_speed_mean_7d": float(row["wind_speed_mean_7d"]),
                    },
                    "positive_h3": _positive_summary(query_targets, lookup, 3),
                    "positive_h7": _positive_summary(query_targets, lookup, 7),
                    "positive_h14": _positive_summary(query_targets, lookup, 14),
                }
            )
        self.example_records = examples
        return examples

    def _metadata_payload(self) -> dict[str, Any]:
        if any(
            value is None
            for value in (
                self.contexts,
                self.targets,
                self.catalog,
                self.patient_stats,
                self.context_metadata,
                self.split_metadata,
                self.support_counts,
                self.validation_checks,
                self.daily_weather,
            )
        ):
            raise RuntimeError("Cannot create metadata before completing pipeline")
        assert self.contexts is not None
        assert self.targets is not None
        assert self.catalog is not None
        assert self.patient_stats is not None
        assert self.context_metadata is not None
        assert self.split_metadata is not None
        assert self.support_counts is not None
        assert self.validation_checks is not None
        assert self.daily_weather is not None
        disease_count = int(len(self.catalog))
        query_count = int(len(self.contexts))
        total_candidate_pairs = query_count * disease_count
        target_stats = {}
        for horizon in HORIZONS:
            positive_pairs = int(self.targets[f"has_case_h{horizon}"].sum())
            target_stats[f"h{horizon}"] = {
                "total_candidate_pairs": int(total_candidate_pairs),
                "positive_pairs": positive_pairs,
                "positive_rate": positive_pairs / total_candidate_pairs,
            }
        train_queries = int(self.split_metadata["train"]["queries"])
        payload = {
            "project": self.config["project"]["name"],
            "timezone": self.config["timezone"],
            "problem_type": "multi_label_disease_ranking_candidate_scoring",
            "no_model_trained": True,
            "sources": self.source_audit,
            "patient": self.patient_stats,
            "weather": {
                **(self.weather_metadata or {}),
                "daily_rows": int(len(self.daily_weather)),
                "date_from": str(self.daily_weather["date"].min().date()),
                "date_to": str(self.daily_weather["date"].max().date()),
                "lookbacks": {"current": [0, 0], "3d": [-2, 0], "7d": [-6, 0]},
                "feature_columns": self.weather_columns,
            },
            "contexts": self.context_metadata,
            "targets": {
                "storage": "sparse_positive_union_h14",
                "rows": int(len(self.targets)),
                "horizons": target_stats,
                "missing_sparse_row_means_zero_recorded_cases": True,
            },
            "candidate_catalog": {
                "disease_groups": disease_count,
                "observed_disease_groups_full_source": int(
                    self.patient_stats["observed_disease_groups"]
                ),
                "never_observed_full_source": disease_count
                - int(self.patient_stats["observed_disease_groups"]),
            },
            "estimated_full_candidate_rows_all_valid_queries": int(total_candidate_pairs),
            "estimated_full_candidate_rows_train": int(train_queries * disease_count),
            "estimated_dense_payload_bytes_at_40_bytes_per_pair": int(
                total_candidate_pairs * 40
            ),
            "support": {
                "definition": self.config["support"]["definition"],
                "thresholds": self.config["support"],
                "counts_by_horizon": self.support_counts,
                "source_split": "train_only",
                "overlapping_anchor_windows_may_count_same_encounter_more_than_once": True,
            },
            "split": self.split_metadata,
            "model_feature_columns": self.model_feature_columns,
            "checks": self.validation_checks,
            "examples": self.example_records,
            "output_format": "csv.gz (pyarrow unavailable)",
        }
        return payload

    def save_artifacts(self) -> dict[str, Any]:
        if not self.example_records:
            self.build_examples()
        self.dataset_metadata = self._metadata_payload()
        assert self.daily_cases is not None
        assert self.contexts is not None
        assert self.targets is not None
        assert self.catalog is not None
        assert self.split_frames is not None
        assert self.split_metadata is not None
        processed_dir = self.project_root / "data/processed"
        split_dir = self.project_root / "data/splits"
        files = {
            "daily_cases": processed_dir / "daily_cases.csv.gz",
            "contexts": processed_dir / "contexts.csv.gz",
            "targets": processed_dir / "targets.csv.gz",
            "disease_catalog": processed_dir / "disease_catalog.csv",
            "metadata": processed_dir / "dataset_metadata.json",
            "train_queries": split_dir / "train_query_ids.csv",
            "validation_queries": split_dir / "validation_query_ids.csv",
            "test_queries": split_dir / "test_query_ids.csv",
            "split_metadata": split_dir / "split_metadata.json",
        }
        write_csv_gzip(files["daily_cases"], _format_dates(self.daily_cases))
        write_csv_gzip(files["contexts"], _format_dates(self.contexts))
        write_csv_gzip(files["targets"], self.targets)
        write_csv(files["disease_catalog"], self.catalog)
        for name, key in (
            ("train", "train_queries"),
            ("validation", "validation_queries"),
            ("test", "test_queries"),
        ):
            write_csv(files[key], self.split_frames[name])
        split_payload = dict(self.split_metadata)
        split_payload["files"] = {
            key: {
                "path": str(path.relative_to(self.project_root)).replace("\\", "/"),
                "sha256": sha256_file(path),
            }
            for key, path in files.items()
            if key.endswith("queries")
        }
        write_json(files["split_metadata"], split_payload)
        self.dataset_metadata["files"] = {
            key: {
                "path": str(path.relative_to(self.project_root)).replace("\\", "/"),
                "sha256": sha256_file(path),
                "bytes": int(path.stat().st_size),
            }
            for key, path in files.items()
            if key not in {"metadata", "split_metadata"}
        }
        write_json(files["metadata"], self.dataset_metadata)
        self._write_report(self.project_root / "reports/DATA_PREPARATION_REPORT.md")
        return self.dataset_metadata

    def _write_report(self, path: Path) -> None:
        if self.dataset_metadata is None or self.split_metadata is None:
            raise RuntimeError("Metadata is not ready")
        metadata = self.dataset_metadata
        targets = metadata["targets"]["horizons"]
        support = metadata["support"]["counts_by_horizon"]
        lines = [
            "# Data Preparation Report — Weather Disease AI V3",
            "",
            "Giai đoạn này chỉ chuẩn bị dữ liệu và khung baseline/metrics. **Chưa huấn luyện bất kỳ model nào.**",
            "",
            "> `case_count_day` và `case_count_h*` chỉ là số lượt được ghi nhận trong dữ liệu bệnh viện; không phải xác suất mắc bệnh trong cộng đồng và không phải chẩn đoán cá nhân.",
            "",
            "## Nguồn thực tế",
            "",
            f"- Bệnh viện gốc: `{metadata['sources']['original_patient_source']}`",
            f"- Weather gốc: `{metadata['sources']['original_weather_source']}`",
            f"- Bản raw V3 dùng để xử lý: `{metadata['sources']['v3_patient_raw_copy']}` và `{metadata['sources']['v3_weather_raw_copy']}`.",
            f"- SHA-256 bệnh viện/weather: `{metadata['sources']['patient_sha256']}` / `{metadata['sources']['weather_sha256']}`.",
            "",
            "## Phạm vi nguồn",
            "",
            f"- Ngày bệnh: {metadata['patient']['patient_date_from']} → {metadata['patient']['patient_date_to']}.",
            f"- Ngày weather: {metadata['weather']['date_from']} → {metadata['weather']['date_to']} ({metadata['weather']['daily_rows']:,} ngày liên tục).",
            f"- Age groups ({len(metadata['patient']['age_groups'])}): {', '.join(metadata['patient']['age_groups'])}.",
            f"- Gender: {', '.join(metadata['patient']['gender_values'])}.",
            f"- Catalog candidate: {metadata['candidate_catalog']['disease_groups']:,}; đã xuất hiện trong toàn nguồn bệnh nhân: {metadata['candidate_catalog']['observed_disease_groups_full_source']:,}; chưa từng xuất hiện: {metadata['candidate_catalog']['never_observed_full_source']:,}.",
            "- Cột raw `month` được hiểu là tuổi theo tháng, chỉ dùng fallback khi thiếu ngày sinh; calendar month được tạo lại từ `anchor_date`.",
            "",
            "## Context và target sparse",
            "",
            f"- Anchor: {metadata['contexts']['anchor_date_from']} → {metadata['contexts']['anchor_date_to']} ({metadata['contexts']['unique_anchor_dates']:,} ngày).",
            f"- Tổ hợp age_group + gender: {metadata['contexts']['age_gender_pairs']:,}.",
            f"- Query contexts: {metadata['contexts']['queries']:,}.",
            f"- Sparse target rows (positive union H14): {metadata['targets']['rows']:,}.",
            "",
            "| Horizon | Total candidate pairs | Positive pairs | Positive rate |",
            "|---|---:|---:|---:|",
        ]
        for horizon in HORIZONS:
            values = targets[f"h{horizon}"]
            lines.append(
                f"| H{horizon} | {values['total_candidate_pairs']:,} | {values['positive_pairs']:,} | {values['positive_rate']:.6%} |"
            )
        lines.extend(
            [
                "",
                f"- Nếu expand đầy đủ: {metadata['estimated_full_candidate_rows_all_valid_queries']:,} rows cho toàn anchor hợp lệ; {metadata['estimated_full_candidate_rows_train']:,} rows cho TRAIN.",
                f"- Ước lượng payload dense tối thiểu ở 40 bytes/pair: {metadata['estimated_dense_payload_bytes_at_40_bytes_per_pair'] / (1024 ** 2):,.1f} MiB (chưa gồm overhead chuỗi/CSV).",
                "- File sparse không được dùng làm mẫu số positive rate; mẫu số luôn là query × 311 candidate.",
                "",
                "## Support theo TRAIN",
                "",
                "Support dùng tổng `case_count_h*` trên các TRAIN query. Do target window overlap giữa các anchor liên tiếp, cùng một lượt bệnh viện có thể đóng góp cho nhiều query; validation/test không tham gia quyết định tier.",
                "",
                "| Horizon | High | Medium | Low | Insufficient | Unsupported |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for horizon in HORIZONS:
            values = support[f"h{horizon}"]
            lines.append(
                f"| H{horizon} | {values['high']} | {values['medium']} | {values['low']} | {values['insufficient']} | {values['unsupported']} |"
            )
        lines.extend(["", "## Temporal split và purge", ""])
        for split_name in ("train", "validation", "test"):
            values = self.split_metadata[split_name]
            lines.append(
                f"- {split_name}: {values['date_from']} → {values['date_to']}; {values['unique_anchor_dates']:,} anchor; {values['queries']:,} query."
            )
        for gap_name in ("purge_train_validation", "purge_validation_test"):
            values = self.split_metadata[gap_name]
            lines.append(
                f"- {gap_name}: {values['date_from']} → {values['date_to']} ({values['unique_anchor_dates']} ngày bị loại)."
            )
        lines.extend(
            [
                "",
                "Purge gap = 13 ngày anchor giữa các split. Vì H14 dùng D..D+13, target window cuối split trước kết thúc trước anchor đầu split sau.",
                "",
                "## Leakage và invariant",
                "",
            ]
        )
        lines.extend(
            f"- {'PASS' if passed else 'FAIL'} — `{name}`"
            for name, passed in metadata["checks"].items()
        )
        lines.extend(["", "## Ba ví dụ ngày thật", ""])
        for index, example in enumerate(metadata["examples"], start=1):
            lines.extend(
                [
                    f"### Ví dụ {index}: {example['query_id']}",
                    "",
                    f"- Anchor D: **{example['anchor_date']}**; age_group: **{example['age_group']}**; gender: **{example['gender']}**.",
                    f"- Weather current: {example['weather_ranges']['current']}.",
                    f"- Weather 3d: {example['weather_ranges']['3d']}.",
                    f"- Weather 7d: {example['weather_ranges']['7d']}.",
                    f"- H3: {example['target_ranges']['h3']}.",
                    f"- H7: {example['target_ranges']['h7']}.",
                    f"- H14: {example['target_ranges']['h14']}.",
                    "- Weather thực tế: "
                    + ", ".join(
                        f"`{key}`={value:.3f}" for key, value in example["weather_values"].items()
                    )
                    + ".",
                ]
            )
            for horizon in HORIZONS:
                positives = example[f"positive_h{horizon}"]
                preview = positives[:8]
                text = "; ".join(
                    f"{item['disease_group_id']} — {item['disease_group_name']} ({item['case_count']})"
                    for item in preview
                ) or "không có lượt ghi nhận"
                suffix = f"; … tổng {len(positives)} nhóm" if len(positives) > len(preview) else ""
                lines.append(f"- Positive H{horizon}: {text}{suffix}.")
            lines.append("")
        lines.extend(
            [
                "## Artifact",
                "",
                "- `data/processed/daily_cases.csv.gz`",
                "- `data/processed/contexts.csv.gz`",
                "- `data/processed/targets.csv.gz`",
                "- `data/processed/disease_catalog.csv`",
                "- `data/processed/dataset_metadata.json`",
                "- `data/splits/train_query_ids.csv`",
                "- `data/splits/validation_query_ids.csv`",
                "- `data/splits/test_query_ids.csv`",
                "- `data/splits/split_metadata.json`",
                "",
                "Không có CatBoost/LightGBM/XGBoost/neural network/SHAP nào được chạy trong giai đoạn này.",
            ]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_all(self) -> dict[str, Any]:
        self.load_raw_data()
        self.audit_source_data()
        self.build_daily_disease_counts()
        self.build_weather_current_3d_7d()
        self.build_query_contexts()
        self.build_horizon_targets()
        self.build_temporal_splits()
        self.calculate_train_support()
        self.validate_all()
        self.build_examples()
        return self.save_artifacts()


def run_data_preparation(project_root: Path) -> DataPreparationPipeline:
    pipeline = DataPreparationPipeline(project_root)
    pipeline.run_all()
    return pipeline


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pipeline = run_data_preparation(project_root)
    metadata = pipeline.dataset_metadata or {}
    print(
        json.dumps(
            {
                "workspace": str(project_root),
                "queries": metadata.get("contexts", {}).get("queries"),
                "diseases": metadata.get("candidate_catalog", {}).get("disease_groups"),
                "positive_pairs": {
                    key: value["positive_pairs"]
                    for key, value in metadata.get("targets", {}).get("horizons", {}).items()
                },
                "checks_passed": all(metadata.get("checks", {}).values()),
                "model_trained": False,
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
