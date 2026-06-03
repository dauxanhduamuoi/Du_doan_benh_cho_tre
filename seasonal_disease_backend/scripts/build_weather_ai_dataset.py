"""
Build dataset train cho AI nguy cơ bệnh theo thời tiết.

Input mặc định:
- Tool/weather/open-meteo-10.79N106.63E6m.csv
- Tool/weather/train_history.xlsx

Output mặc định:
- Tool/weather/output_weather_ai/weather_ai_train_dataset.csv.gz
- Tool/weather/output_weather_ai/disease_group_catalog.csv
- Tool/weather/output_weather_ai/weather_daily_features.csv
- Tool/weather/output_weather_ai/dataset_summary.json

Logic chính:
1. Đọc DS-BenhNhan.
2. Đọc DS-MaBenh.
3. Map DS-BenhNhan.main_icd với DS-MaBenh.MAICD.
4. Lấy mã nhóm bệnh THẬT từ DS-MaBenh:
   - IDNHOMICD -> disease_group_id
   - MANHOMBAOCAO -> report_group_code
   - TENNHOMICD -> disease_group_name
5. Gom bệnh nhân thành số ca theo ngày + tuổi + giới tính + nhóm bệnh.
6. Gom weather hourly thành weather daily + rolling 3 ngày/7 ngày.
7. Ghép bệnh + weather theo date.
8. Tạo thêm mẫu âm case_count = 0 để train classifier/regressor.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

PATIENT_SHEET_CANDIDATES = ["DS-BenhNhan", "DS_BenhNhan", "BenhNhan", "Sheet1"]
DISEASE_SHEET_CANDIDATES = ["DS-MaBenh", "DS_MaBenh", "MaBenh"]

ICD_ADMISSION_COL = "icdNV"
ICD_DISCHARGE_COL = "icdxuatvien"
CHECK_IN_DATE_COL = "check_in_date"
DATE_OF_BIRTH_COL = "date_of_birth"
GENDER_COL = "gender"
MONTH_AGE_COL = "month"

ICD_CODE_COL = "MAICD"
DISEASE_GROUP_ID_COL = "IDNHOMICD"
DISEASE_GROUP_NAME_COL = "TENNHOMICD"
REPORT_GROUP_CODE_COL = "MANHOMBAOCAO"

WEATHER_FEATURE_COLS = [
    "temp_mean_today",
    "temp_max_today",
    "temp_min_today",
    "humidity_mean_today",
    "precipitation_sum_today",
    "rain_sum_today",
    "weather_code",
    "wind_speed_max_today",
    "wind_gusts_max_today",
    "temp_mean_3d",
    "humidity_mean_3d",
    "precipitation_sum_3d",
    "rain_sum_3d",
    "temp_mean_7d",
    "humidity_mean_7d",
    "precipitation_sum_7d",
    "rain_sum_7d",
    "rain_days_7d",
]

OUTPUT_COLUMNS = [
    "date",
    "age_group",
    "gender",
    "disease_group_id",
    "report_group_code",
    "disease_group_name",
    "case_count",
    "has_case",
    "month",
    "season",
] + WEATHER_FEATURE_COLS


def read_sheet_flexible(file_path: Path, candidates: list[str]) -> pd.DataFrame:
    xls = pd.ExcelFile(file_path)
    for sheet in candidates:
        if sheet in xls.sheet_names:
            return pd.read_excel(xls, sheet_name=sheet)
    raise ValueError(f"Không tìm thấy sheet {candidates}. Sheet thực tế: {xls.sheet_names}")


def normalize_icd_series(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip().str.upper()
    # Một số mã ICD trong danh mục có ký tự đặc biệt như † hoặc *.
    values = values.str.replace("†", "", regex=False).str.replace("*", "", regex=False)
    return values.replace({"": pd.NA, "<NA>": pd.NA, "NAN": pd.NA})


def parse_mixed_date_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", dayfirst=True)
    numeric = pd.to_numeric(series, errors="coerce")
    mask = numeric.between(20000, 80000) & numeric.notna()
    if mask.any():
        parsed.loc[mask] = pd.to_datetime("1899-12-30") + pd.to_timedelta(numeric.loc[mask], unit="D")
    return parsed


def normalize_gender(value) -> str:
    if pd.isna(value):
        return "Không rõ"
    text = str(value).strip()
    low = text.lower()
    if low in ["nam", "male", "m", "1"]:
        return "Nam"
    if low in ["nữ", "nu", "female", "f", "0", "2"]:
        return "Nữ"
    return text if text else "Không rõ"


def age_to_group(age: pd.Series) -> pd.Series:
    conditions = [age.isna(), age < 1, age <= 5, age <= 10, age <= 15]
    choices = ["Không rõ", "Dưới 1 tuổi", "1-5 tuổi", "6-10 tuổi", "11-15 tuổi"]
    return pd.Series(np.select(conditions, choices, default="Trên 15 tuổi"), index=age.index)


def month_to_season(month: int | float) -> str:
    if pd.isna(month):
        return "Không rõ"
    month = int(month)
    if month in [12, 1, 2, 3, 4]:
        return "Mùa khô"
    if month in [5, 6, 7, 8, 9, 10, 11]:
        return "Mùa mưa"
    return "Không rõ"


def mode_or_nan(series: pd.Series):
    values = series.dropna()
    if values.empty:
        return np.nan
    return values.mode().iloc[0]


def find_weather_header_row(weather_csv: Path) -> int:
    with weather_csv.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if line.startswith("time,"):
                return i
    raise ValueError("Không tìm thấy dòng header bắt đầu bằng 'time,' trong CSV thời tiết.")


def clean_weather_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for col in df.columns:
        c = col.strip()
        if c == "time":
            rename[col] = "time"
        elif c.startswith("temperature_2m"):
            rename[col] = "temperature_2m"
        elif c.startswith("relative_humidity_2m"):
            rename[col] = "relative_humidity_2m"
        elif c.startswith("precipitation"):
            rename[col] = "precipitation"
        elif c.startswith("rain"):
            rename[col] = "rain"
        elif c.startswith("weather_code"):
            rename[col] = "weather_code"
        elif c.startswith("wind_speed_10m"):
            rename[col] = "wind_speed_10m"
        elif c.startswith("wind_gusts_10m"):
            rename[col] = "wind_gusts_10m"
    df = df.rename(columns=rename)
    required = [
        "time",
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "rain",
        "weather_code",
        "wind_speed_10m",
        "wind_gusts_10m",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"File thời tiết thiếu cột: {missing}")
    return df[required].copy()


def build_daily_weather(weather_csv: Path) -> pd.DataFrame:
    header_row = find_weather_header_row(weather_csv)
    hourly = pd.read_csv(weather_csv, skiprows=header_row)
    hourly = clean_weather_columns(hourly)
    hourly["time"] = pd.to_datetime(hourly["time"], errors="coerce")
    hourly = hourly.dropna(subset=["time"])
    hourly["date"] = hourly["time"].dt.normalize()

    for col in [
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "rain",
        "weather_code",
        "wind_speed_10m",
        "wind_gusts_10m",
    ]:
        hourly[col] = pd.to_numeric(hourly[col], errors="coerce")

    daily = (
        hourly.groupby("date")
        .agg(
            temp_mean_today=("temperature_2m", "mean"),
            temp_max_today=("temperature_2m", "max"),
            temp_min_today=("temperature_2m", "min"),
            humidity_mean_today=("relative_humidity_2m", "mean"),
            precipitation_sum_today=("precipitation", "sum"),
            rain_sum_today=("rain", "sum"),
            weather_code=("weather_code", mode_or_nan),
            wind_speed_max_today=("wind_speed_10m", "max"),
            wind_gusts_max_today=("wind_gusts_10m", "max"),
        )
        .reset_index()
        .sort_values("date")
    )

    daily["temp_mean_3d"] = daily["temp_mean_today"].rolling(3, min_periods=1).mean()
    daily["humidity_mean_3d"] = daily["humidity_mean_today"].rolling(3, min_periods=1).mean()
    daily["precipitation_sum_3d"] = daily["precipitation_sum_today"].rolling(3, min_periods=1).sum()
    daily["rain_sum_3d"] = daily["rain_sum_today"].rolling(3, min_periods=1).sum()
    daily["temp_mean_7d"] = daily["temp_mean_today"].rolling(7, min_periods=1).mean()
    daily["humidity_mean_7d"] = daily["humidity_mean_today"].rolling(7, min_periods=1).mean()
    daily["precipitation_sum_7d"] = daily["precipitation_sum_today"].rolling(7, min_periods=1).sum()
    daily["rain_sum_7d"] = daily["rain_sum_today"].rolling(7, min_periods=1).sum()
    daily["rain_days_7d"] = (daily["rain_sum_today"] > 0).astype(int).rolling(7, min_periods=1).sum()
    daily["month"] = daily["date"].dt.month
    daily["season"] = daily["month"].apply(month_to_season)

    round_cols = [c for c in daily.columns if c not in ["date", "month", "season", "weather_code"]]
    daily[round_cols] = daily[round_cols].round(3)
    return daily


def build_disease_codes(train_history: Path) -> pd.DataFrame:
    codes = read_sheet_flexible(train_history, DISEASE_SHEET_CANDIDATES)
    required = [ICD_CODE_COL, DISEASE_GROUP_ID_COL, REPORT_GROUP_CODE_COL, DISEASE_GROUP_NAME_COL]
    missing = [c for c in required if c not in codes.columns]
    if missing:
        raise ValueError(f"DS-MaBenh thiếu cột: {missing}")

    out = codes[required].copy()
    out[ICD_CODE_COL] = normalize_icd_series(out[ICD_CODE_COL])
    out["disease_group_id"] = out[DISEASE_GROUP_ID_COL].astype("string").str.strip()
    out["report_group_code"] = out[REPORT_GROUP_CODE_COL].astype("string").str.strip()
    out["disease_group_name"] = out[DISEASE_GROUP_NAME_COL].astype("string").str.strip()
    out = out.dropna(subset=[ICD_CODE_COL, "disease_group_id", "disease_group_name"])
    out = out.drop_duplicates(subset=[ICD_CODE_COL], keep="last")
    return out[[ICD_CODE_COL, "disease_group_id", "report_group_code", "disease_group_name"]]


def load_patient_cases(train_history: Path, disease_codes: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    patients = read_sheet_flexible(train_history, PATIENT_SHEET_CANDIDATES)
    required = [ICD_ADMISSION_COL, ICD_DISCHARGE_COL, CHECK_IN_DATE_COL, DATE_OF_BIRTH_COL, GENDER_COL]
    missing = [c for c in required if c not in patients.columns]
    if missing:
        raise ValueError(f"DS-BenhNhan thiếu cột: {missing}")

    patients = patients.copy()
    raw_rows = len(patients)
    patients[CHECK_IN_DATE_COL] = parse_mixed_date_series(patients[CHECK_IN_DATE_COL])
    patients[DATE_OF_BIRTH_COL] = parse_mixed_date_series(patients[DATE_OF_BIRTH_COL])
    patients[ICD_ADMISSION_COL] = normalize_icd_series(patients[ICD_ADMISSION_COL])
    patients[ICD_DISCHARGE_COL] = normalize_icd_series(patients[ICD_DISCHARGE_COL])

    patients = patients.dropna(subset=[CHECK_IN_DATE_COL])
    patients = patients.dropna(subset=[ICD_ADMISSION_COL, ICD_DISCHARGE_COL], how="all")
    patients["main_icd"] = patients[ICD_DISCHARGE_COL].fillna(patients[ICD_ADMISSION_COL])
    patients["main_icd"] = normalize_icd_series(patients["main_icd"])

    df = patients.merge(disease_codes, left_on="main_icd", right_on=ICD_CODE_COL, how="left")
    unmapped = int(df["disease_group_id"].isna().sum())
    df = df.dropna(subset=["disease_group_id", "disease_group_name"])

    df["gender"] = df[GENDER_COL].apply(normalize_gender)
    age = (df[CHECK_IN_DATE_COL] - df[DATE_OF_BIRTH_COL]).dt.days / 365.25
    if MONTH_AGE_COL in df.columns:
        month_age = pd.to_numeric(df[MONTH_AGE_COL], errors="coerce")
        age = age.fillna(month_age / 12)
    age = age.where(age >= 0)
    df["age_group"] = age_to_group(age)
    df["date"] = df[CHECK_IN_DATE_COL].dt.normalize()

    positive = (
        df.groupby(["date", "age_group", "gender", "disease_group_id", "report_group_code", "disease_group_name"])
        .size()
        .reset_index(name="case_count")
    )
    positive["has_case"] = 1
    stats = {
        "raw_patient_rows": raw_rows,
        "valid_patient_rows_after_date_icd_filter": int(len(patients)),
        "mapped_patient_rows": int(len(df)),
        "unmapped_patient_rows": unmapped,
        "positive_rows": int(len(positive)),
        "positive_total_cases": int(positive["case_count"].sum()),
    }
    return positive, stats


def create_negative_samples(
    positive: pd.DataFrame,
    daily_weather: pd.DataFrame,
    negative_ratio: int,
    random_seed: int,
) -> pd.DataFrame:
    rng = np.random.default_rng(random_seed)
    dates = daily_weather[
        (daily_weather["date"] >= positive["date"].min())
        & (daily_weather["date"] <= positive["date"].max())
    ]["date"].drop_duplicates().to_numpy()
    age_groups = np.array(sorted(positive["age_group"].unique().tolist()), dtype=object)
    genders = np.array(sorted(positive["gender"].unique().tolist()), dtype=object)
    catalog = positive[["disease_group_id", "report_group_code", "disease_group_name"]].drop_duplicates()
    diseases = catalog.to_dict("records")
    disease_idx = np.arange(len(diseases))

    target_n = len(positive) * negative_ratio
    key_cols = ["date", "age_group", "gender", "disease_group_id"]
    positive_keys = positive[key_cols].drop_duplicates().copy()
    positive_keys["_is_positive"] = 1

    result_parts = []
    result_count = 0
    for _ in range(30):
        if result_count >= target_n:
            break
        need = target_n - result_count
        batch_size = max(100_000, min(1_000_000, need * 3))
        chosen_idx = rng.choice(disease_idx, size=batch_size, replace=True)
        disease_rows = [diseases[i] for i in chosen_idx]
        batch = pd.DataFrame({
            "date": rng.choice(dates, size=batch_size, replace=True),
            "age_group": rng.choice(age_groups, size=batch_size, replace=True),
            "gender": rng.choice(genders, size=batch_size, replace=True),
            "disease_group_id": [r["disease_group_id"] for r in disease_rows],
            "report_group_code": [r["report_group_code"] for r in disease_rows],
            "disease_group_name": [r["disease_group_name"] for r in disease_rows],
        })
        batch = batch.merge(positive_keys, on=key_cols, how="left")
        batch = batch[batch["_is_positive"].isna()].drop(columns=["_is_positive"])
        batch = batch.drop_duplicates(subset=key_cols)
        result_parts.append(batch)
        negatives = pd.concat(result_parts, ignore_index=True)
        negatives = negatives.drop_duplicates(subset=key_cols).head(target_n)
        result_parts = [negatives]
        result_count = len(negatives)

    negatives = result_parts[0].copy() if result_parts else pd.DataFrame(columns=[
        "date", "age_group", "gender", "disease_group_id", "report_group_code", "disease_group_name"
    ])
    negatives["case_count"] = 0
    negatives["has_case"] = 0
    return negatives


def write_csv_file(df: pd.DataFrame, path: Path) -> None:
    """Ghi CSV bằng csv.writer để tránh lỗi treo pandas.to_csv với text dài."""
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(list(df.columns))
        for row in df.itertuples(index=False, name=None):
            writer.writerow(row)


def write_gzip_csv_file(df: pd.DataFrame, path: Path) -> None:
    """Ghi thêm bản nén để lưu trữ/chia sẻ dataset train nhẹ hơn."""
    with gzip.open(path, "wt", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(list(df.columns))
        for row in df.itertuples(index=False, name=None):
            writer.writerow(row)


def build_dataset(
    weather_csv: Path,
    train_history: Path,
    out_dir: Path,
    negative_ratio: int = 1,
    random_seed: int = 42,
) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    weather = build_daily_weather(weather_csv)
    weather.to_csv(out_dir / "weather_daily_features.csv", index=False, encoding="utf-8-sig")

    disease_codes = build_disease_codes(train_history)
    disease_codes.drop_duplicates(subset=["disease_group_id", "report_group_code", "disease_group_name"]).to_csv(
        out_dir / "disease_group_catalog_from_ds_mabenh.csv", index=False, encoding="utf-8-sig"
    )
    positive, patient_stats = load_patient_cases(train_history, disease_codes)

    # Chỉ giữ bệnh nhân nằm trong khoảng weather để train. Nếu dữ liệu thật đến 04/2025
    # và weather đến 2025-04-30 thì giá trị này phải là 0.
    before_weather_filter = len(positive)
    positive = positive.merge(weather[["date"]], on="date", how="inner")
    dropped_outside_weather = before_weather_filter - len(positive)
    if positive.empty:
        raise ValueError("Không còn dòng bệnh nào sau khi ghép ngày với weather.")

    positive.to_csv(out_dir / "weather_ai_positive_cases.csv", index=False, encoding="utf-8-sig")
    negative = create_negative_samples(positive, weather, negative_ratio, random_seed)
    dataset = pd.concat([positive, negative], ignore_index=True)
    dataset = dataset.merge(weather, on="date", how="left")

    if dataset[WEATHER_FEATURE_COLS].isna().any().any():
        missing_count = int(dataset[WEATHER_FEATURE_COLS].isna().any(axis=1).sum())
        raise ValueError(f"Có {missing_count} dòng thiếu weather features.")

    dataset = dataset.sample(frac=1, random_state=random_seed).reset_index(drop=True)
    dataset["date"] = dataset["date"].dt.strftime("%Y-%m-%d")
    dataset = dataset[OUTPUT_COLUMNS]

    train_path = out_dir / "weather_ai_train_dataset.csv"
    write_csv_file(dataset, train_path)
    compressed_train_path = out_dir / "weather_ai_train_dataset.csv.gz"
    write_gzip_csv_file(dataset, compressed_train_path)

    duplicate_keys = int(dataset.duplicated(["date", "age_group", "gender", "disease_group_id", "has_case"]).sum())
    bad_month = int((pd.to_datetime(dataset["date"]).dt.month != dataset["month"]).sum())
    expected_season = dataset["month"].apply(month_to_season)
    bad_season = int((expected_season != dataset["season"]).sum())

    summary = {
        "weather_file": weather_csv.name,
        "train_history_file": train_history.name,
        "train_file": train_path.name,
        "train_file_gzip": compressed_train_path.name,
        "negative_ratio": negative_ratio,
        "weather_date_from": str(weather["date"].min().date()),
        "weather_date_to": str(weather["date"].max().date()),
        "patient_date_from": str(positive["date"].min().date()),
        "patient_date_to": str(positive["date"].max().date()),
        **patient_stats,
        "positive_rows_after_weather_filter": int(len(positive)),
        "dropped_positive_rows_outside_weather_range": int(dropped_outside_weather),
        "negative_rows": int(len(negative)),
        "final_train_rows": int(len(dataset)),
        "total_case_count_train_file": int(dataset["case_count"].sum()),
        "disease_groups_used": int(dataset["disease_group_id"].nunique()),
        "age_groups": sorted(dataset["age_group"].unique().tolist()),
        "genders": sorted(dataset["gender"].unique().tolist()),
        "missing_weather_rows": 0,
        "duplicate_key_rows": duplicate_keys,
        "bad_month_rows": bad_month,
        "bad_season_rows": bad_season,
    }
    (out_dir / "dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "dataset_summary.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in summary.items()), encoding="utf-8"
    )
    return dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build weather AI train dataset")
    parser.add_argument("--weather-csv", default="Tool/weather/open-meteo-10.79N106.63E6m.csv")
    parser.add_argument("--train-history", default="Tool/weather/train_history.xlsx")
    parser.add_argument("--out-dir", default="Tool/weather/output_weather_ai")
    parser.add_argument("--negative-ratio", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = build_dataset(
        weather_csv=Path(args.weather_csv),
        train_history=Path(args.train_history),
        out_dir=Path(args.out_dir),
        negative_ratio=args.negative_ratio,
        random_seed=args.random_seed,
    )
    print("Tạo dataset thành công.")
    print(f"Số dòng: {len(dataset):,}")
    print(f"Tổng case_count: {int(dataset['case_count'].sum()):,}")
    print(f"File train: {Path(args.out_dir) / 'weather_ai_train_dataset.csv'}")
    print(f"File train gzip: {Path(args.out_dir) / 'weather_ai_train_dataset.csv.gz'}")


if __name__ == "__main__":
    main()
