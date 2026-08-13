"""Leakage-safe weather feature engineering for exact trailing calendar windows."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


CANONICAL_PREFIXES = {
    "time": "time",
    "temperature_2m": "temperature_2m",
    "relative_humidity_2m": "relative_humidity_2m",
    "precipitation": "precipitation",
    "rain": "rain",
    "weather_code": "weather_code",
    "wind_speed_10m": "wind_speed_10m",
    "wind_gusts_10m": "wind_gusts_10m",
}
REQUIRED_CANONICAL_COLUMNS = {
    "time",
    "temperature_2m",
    "relative_humidity_2m",
    "weather_code",
    "wind_speed_10m",
}


def mode_or_nan(series: pd.Series) -> float:
    values = series.dropna()
    return float(values.mode().iloc[0]) if not values.empty else float("nan")


def find_weather_header_row(weather_csv: Path) -> int:
    with weather_csv.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle):
            if line.strip().startswith("time,"):
                return line_number
    raise ValueError("Weather CSV has no header row beginning with 'time,'")


def _canonical_name(column: str) -> str | None:
    stripped = str(column).strip()
    for prefix, canonical in CANONICAL_PREFIXES.items():
        if stripped == prefix or stripped.startswith(f"{prefix} ") or stripped.startswith(
            f"{prefix}("
        ):
            return canonical
    return None


def read_weather_hourly(weather_csv: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    header_row = find_weather_header_row(weather_csv)
    raw = pd.read_csv(weather_csv, skiprows=header_row)
    actual_columns = [str(column) for column in raw.columns]
    rename: dict[str, str] = {}
    for column in raw.columns:
        canonical = _canonical_name(str(column))
        if canonical is not None:
            if canonical in rename.values():
                raise ValueError(f"Multiple weather columns map to {canonical!r}")
            rename[str(column)] = canonical

    available = set(rename.values())
    missing = sorted(REQUIRED_CANONICAL_COLUMNS - available)
    if missing:
        raise ValueError(
            f"Weather CSV is missing required fields {missing}; actual columns: {actual_columns}"
        )

    hourly = raw[list(rename)].rename(columns=rename).copy()
    hourly["time"] = pd.to_datetime(hourly["time"], errors="coerce")
    invalid_timestamps = int(hourly["time"].isna().sum())
    hourly = hourly.dropna(subset=["time"]).copy()
    numeric_columns = [column for column in hourly.columns if column != "time"]
    for column in numeric_columns:
        hourly[column] = pd.to_numeric(hourly[column], errors="coerce")
    hourly["date"] = hourly["time"].dt.normalize()
    hourly = hourly.sort_values("time", kind="mergesort").reset_index(drop=True)

    metadata = {
        "header_row_zero_based": int(header_row),
        "actual_columns": actual_columns,
        "canonical_column_mapping": rename,
        "hourly_rows": int(len(hourly)),
        "invalid_timestamps": invalid_timestamps,
        "duplicate_timestamps": int(hourly.duplicated("time").sum()),
        "missing_values": {
            column: int(hourly[column].isna().sum()) for column in numeric_columns
        },
    }
    return hourly, metadata


def build_daily_weather_base(hourly: pd.DataFrame) -> pd.DataFrame:
    aggregations: dict[str, tuple[str, str | Any]] = {
        "temperature_mean_daily": ("temperature_2m", "mean"),
        "temperature_max_daily": ("temperature_2m", "max"),
        "temperature_min_daily": ("temperature_2m", "min"),
        "humidity_mean_daily": ("relative_humidity_2m", "mean"),
        "humidity_max_daily": ("relative_humidity_2m", "max"),
        "humidity_min_daily": ("relative_humidity_2m", "min"),
        "weather_code": ("weather_code", mode_or_nan),
        "wind_speed_mean_daily": ("wind_speed_10m", "mean"),
        "wind_speed_max_daily": ("wind_speed_10m", "max"),
    }
    if "precipitation" in hourly.columns:
        aggregations["precipitation_sum_daily"] = ("precipitation", "sum")
    if "rain" in hourly.columns:
        aggregations["rain_sum_daily"] = ("rain", "sum")
    if "wind_gusts_10m" in hourly.columns:
        aggregations["wind_gust_max_daily"] = ("wind_gusts_10m", "max")

    daily = hourly.groupby("date", as_index=False).agg(**aggregations)
    return daily.sort_values("date", kind="mergesort").reset_index(drop=True)


def weather_feature_columns(
    daily_weather: pd.DataFrame, windows: Iterable[int] = (1, 3, 7, 14)
) -> list[str]:
    columns: list[str] = ["weather_code"]
    for window in windows:
        suffix = f"{int(window)}d"
        columns.extend(
            [
                f"temperature_mean_{suffix}",
                f"temperature_max_{suffix}",
                f"temperature_min_{suffix}",
                f"humidity_mean_{suffix}",
                f"humidity_max_{suffix}",
                f"humidity_min_{suffix}",
            ]
        )
        if "precipitation_sum_daily" in daily_weather.columns:
            columns.append(f"precipitation_sum_{suffix}")
        if "rain_sum_daily" in daily_weather.columns:
            columns.extend([f"rain_sum_{suffix}", f"rain_days_{suffix}", f"rain_max_daily_{suffix}"])
        columns.extend([f"wind_speed_mean_{suffix}", f"wind_speed_max_{suffix}"])
        if "wind_gust_max_daily" in daily_weather.columns:
            columns.append(f"wind_gust_max_{suffix}")
    return columns


def build_weather_window_features(
    weather_df: pd.DataFrame,
    target_date: object,
    windows: Iterable[int] = (1, 3, 7, 14),
) -> dict[str, float]:
    """Build exact inclusive trailing windows ending at ``target_date``.

    ``weather_df`` must be daily weather produced by :func:`build_daily_weather_base`.
    A window is populated only when every calendar day is available. Rows after the
    target date are explicitly excluded, preventing future leakage.
    """
    target = pd.Timestamp(target_date).normalize()
    dates = pd.to_datetime(weather_df["date"], errors="coerce").dt.normalize()
    historical = weather_df.loc[dates <= target].copy()
    historical["date"] = dates.loc[dates <= target]
    current = historical[historical["date"] == target]
    output: dict[str, float] = {
        "weather_code": mode_or_nan(current["weather_code"]) if not current.empty else np.nan
    }

    for window_value in windows:
        window = int(window_value)
        if window <= 0:
            raise ValueError(f"Weather window must be positive, received {window}")
        suffix = f"{window}d"
        expected_dates = pd.date_range(
            target - pd.DateOffset(days=window - 1), target, freq="D"
        )
        selected = historical[historical["date"].isin(expected_dates)].copy()
        selected = selected.drop_duplicates("date", keep=False).sort_values("date")
        complete = len(selected) == window and set(selected["date"]) == set(expected_dates)

        feature_names = [
            f"temperature_mean_{suffix}",
            f"temperature_max_{suffix}",
            f"temperature_min_{suffix}",
            f"humidity_mean_{suffix}",
            f"humidity_max_{suffix}",
            f"humidity_min_{suffix}",
        ]
        if "precipitation_sum_daily" in weather_df.columns:
            feature_names.append(f"precipitation_sum_{suffix}")
        if "rain_sum_daily" in weather_df.columns:
            feature_names.extend(
                [f"rain_sum_{suffix}", f"rain_days_{suffix}", f"rain_max_daily_{suffix}"]
            )
        feature_names.extend([f"wind_speed_mean_{suffix}", f"wind_speed_max_{suffix}"])
        if "wind_gust_max_daily" in weather_df.columns:
            feature_names.append(f"wind_gust_max_{suffix}")

        if not complete:
            output.update({name: np.nan for name in feature_names})
            continue

        output.update(
            {
                f"temperature_mean_{suffix}": selected["temperature_mean_daily"].mean(),
                f"temperature_max_{suffix}": selected["temperature_max_daily"].max(),
                f"temperature_min_{suffix}": selected["temperature_min_daily"].min(),
                f"humidity_mean_{suffix}": selected["humidity_mean_daily"].mean(),
                f"humidity_max_{suffix}": selected["humidity_max_daily"].max(),
                f"humidity_min_{suffix}": selected["humidity_min_daily"].min(),
                f"wind_speed_mean_{suffix}": selected["wind_speed_mean_daily"].mean(),
                f"wind_speed_max_{suffix}": selected["wind_speed_max_daily"].max(),
            }
        )
        if "precipitation_sum_daily" in selected.columns:
            output[f"precipitation_sum_{suffix}"] = selected[
                "precipitation_sum_daily"
            ].sum(min_count=window)
        if "rain_sum_daily" in selected.columns:
            output[f"rain_sum_{suffix}"] = selected["rain_sum_daily"].sum(
                min_count=window
            )
            output[f"rain_days_{suffix}"] = int((selected["rain_sum_daily"] > 0).sum())
            output[f"rain_max_daily_{suffix}"] = selected["rain_sum_daily"].max()
        if "wind_gust_max_daily" in selected.columns:
            output[f"wind_gust_max_{suffix}"] = selected["wind_gust_max_daily"].max()
    return output


def build_weather_daily_features(
    daily_weather: pd.DataFrame, windows: Iterable[int] = (1, 3, 7, 14)
) -> pd.DataFrame:
    windows_tuple = tuple(int(window) for window in windows)
    records = []
    for target_date in daily_weather["date"]:
        records.append(
            {
                "date": pd.Timestamp(target_date).normalize(),
                **build_weather_window_features(daily_weather, target_date, windows_tuple),
            }
        )
    features = pd.DataFrame(records)
    ordered = ["date", *weather_feature_columns(daily_weather, windows_tuple)]
    features = features[ordered].sort_values("date", kind="mergesort").reset_index(drop=True)
    numeric = [column for column in features.columns if column not in {"date", "weather_code"}]
    features[numeric] = features[numeric].round(6)
    return features
