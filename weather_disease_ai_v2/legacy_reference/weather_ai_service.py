from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from app.services.data_processing_service import month_to_season_vn

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "app" / "ml" / "weather_ai_risk_model.joblib"

DEFAULT_LATITUDE = 10.790861
DEFAULT_LONGITUDE = 106.6313
DEFAULT_TIMEZONE = "Asia/Bangkok"
MODEL_TRAINING_WEATHER_SCOPE = "Ho Chi Minh City historical weather"
MODEL_RUNTIME_WEATHER_NOTE = (
    "Model was trained with Ho Chi Minh City weather history. At runtime, the selected "
    "location weather is used as input to estimate relative risk."
)
PREDICTED_CASES_UNIT = "estimated_cases_per_day"

# Các cột weather model cần. Nếu artifact có khai báo thì ưu tiên artifact.
DEFAULT_WEATHER_FEATURE_COLS = [
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


def mode_or_nan(series: pd.Series):
    values = series.dropna()
    if values.empty:
        return np.nan
    return values.mode().iloc[0]


@lru_cache(maxsize=2)
def _load_weather_ai_artifact_cached(model_path: str, model_mtime: float) -> dict[str, Any]:
    return joblib.load(model_path)


def load_weather_ai_artifact() -> dict[str, Any]:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            "Chưa có model AI thời tiết. Hãy chạy: python scripts/train_weather_ai_model.py"
        )
    return _load_weather_ai_artifact_cached(str(MODEL_PATH), MODEL_PATH.stat().st_mtime)


def get_model_status() -> dict[str, Any]:
    if not MODEL_PATH.exists():
        return {
            "ready": False,
            "model_path": str(MODEL_PATH),
            "message": "Chưa có app/ml/weather_ai_risk_model.joblib. Hãy chạy scripts/train_weather_ai_model.py.",
        }
    artifact = load_weather_ai_artifact()
    return {
        "ready": True,
        "model_path": str(MODEL_PATH),
        "model_type": artifact.get("model_type"),
        "description": artifact.get("description"),
        "training_weather_scope": MODEL_TRAINING_WEATHER_SCOPE,
        "runtime_weather_note": MODEL_RUNTIME_WEATHER_NOTE,
        "predicted_cases_unit": PREDICTED_CASES_UNIT,
        "age_groups": artifact.get("age_groups", []),
        "genders": artifact.get("genders", []),
        "disease_groups": len(artifact.get("disease_catalog", [])),
        "training_summary": artifact.get("training_summary", {}),
    }


def get_weather_ai_options() -> dict[str, Any]:
    artifact = load_weather_ai_artifact()
    return {
        "age_groups": artifact.get("age_groups", []),
        "genders": artifact.get("genders", []),
        "disease_catalog": artifact.get("disease_catalog", []),
    }


def _clean_open_meteo_hourly(hourly: dict[str, list[Any]]) -> pd.DataFrame:
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
    missing = [c for c in required if c not in hourly]
    if missing:
        raise ValueError(f"Open-Meteo response thiếu hourly fields: {missing}")
    df = pd.DataFrame({c: hourly[c] for c in required})
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"])
    df["date"] = df["time"].dt.normalize()
    for col in required:
        if col != "time":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _hourly_to_daily_features(hourly_df: pd.DataFrame) -> pd.DataFrame:
    daily = (
        hourly_df.groupby("date")
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
    daily["season"] = daily["month"].apply(month_to_season_vn)
    round_cols = [c for c in daily.columns if c not in ["date", "month", "season", "weather_code"]]
    daily[round_cols] = daily[round_cols].round(3)
    return daily


def _daily_weather_series(daily: pd.DataFrame) -> list[dict[str, Any]]:
    """Chuỗi ngày để frontend vẽ tương quan thời tiết, không dùng làm input model."""
    rows: list[dict[str, Any]] = []
    for _, row in daily.iterrows():
        date_value = row.get("date")
        rows.append({
            "date": str(pd.Timestamp(date_value).date()) if pd.notna(date_value) else None,
            "temp_mean_today": None if pd.isna(row.get("temp_mean_today")) else float(row.get("temp_mean_today")),
            "humidity_mean_today": None if pd.isna(row.get("humidity_mean_today")) else float(row.get("humidity_mean_today")),
            "rain_sum_today": None if pd.isna(row.get("rain_sum_today")) else float(row.get("rain_sum_today")),
            "precipitation_sum_today": None if pd.isna(row.get("precipitation_sum_today")) else float(row.get("precipitation_sum_today")),
        })
    return rows


def fetch_current_weather_features(
    latitude: float | None = DEFAULT_LATITUDE,
    longitude: float | None = DEFAULT_LONGITUDE,
    timezone: str = DEFAULT_TIMEZONE,
    target_date: date | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Lấy weather hôm nay + 7 ngày gần nhất từ Open-Meteo Forecast API,
    rồi gom về đúng feature model cần.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "rain",
            "weather_code",
            "wind_speed_10m",
            "wind_gusts_10m",
        ]),
        "past_days": 7,
        "forecast_days": 1,
        "timezone": timezone,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Không lấy được weather realtime từ Open-Meteo: {exc}") from exc

    hourly_df = _clean_open_meteo_hourly(payload.get("hourly", {}))
    daily = _hourly_to_daily_features(hourly_df)

    if target_date is None:
        target_ts = daily["date"].max()
    else:
        target_ts = pd.Timestamp(target_date).normalize()

    row = daily[daily["date"] == target_ts]
    if row.empty:
        raise RuntimeError(f"Không có weather cho ngày {target_ts.date()} trong response Open-Meteo.")
    row = row.iloc[0]
    features = row.drop(labels=["date"]).to_dict()
    meta = {
        "source": "open_meteo",
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "date": str(target_ts.date()),
        "url": url,
        "daily_series": _daily_weather_series(daily),
    }
    return features, meta


def complete_manual_weather_features(weather: dict[str, Any] | None, target_date: date | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Cho phép frontend gửi weather thủ công để test API không cần internet.
    Nếu thiếu feature rolling 3d/7d, service tự fill bằng giá trị today.
    """
    if weather is None:
        raise ValueError("weather không được để trống khi dùng manual mode.")
    d = dict(weather)
    today = datetime.now().date() if target_date is None else target_date
    month = int(d.get("month") or today.month)
    d["month"] = month
    d["season"] = d.get("season") or month_to_season_vn(month)

    # Alias ngắn cho frontend dễ gửi.
    alias = {
        "temperature": "temp_mean_today",
        "temp": "temp_mean_today",
        "humidity": "humidity_mean_today",
        "rain": "rain_sum_today",
        "precipitation": "precipitation_sum_today",
        "wind_speed": "wind_speed_max_today",
        "wind_gusts": "wind_gusts_max_today",
    }
    for src, dst in alias.items():
        if src in d and dst not in d:
            d[dst] = d[src]

    if "temp_mean_today" not in d:
        raise ValueError("Thiếu temp_mean_today hoặc temperature.")
    if "humidity_mean_today" not in d:
        raise ValueError("Thiếu humidity_mean_today hoặc humidity.")
    if "rain_sum_today" not in d:
        d["rain_sum_today"] = 0
    if "precipitation_sum_today" not in d:
        d["precipitation_sum_today"] = d.get("rain_sum_today", 0)
    if "temp_max_today" not in d:
        d["temp_max_today"] = d["temp_mean_today"]
    if "temp_min_today" not in d:
        d["temp_min_today"] = d["temp_mean_today"]
    if "weather_code" not in d:
        d["weather_code"] = 0
    if "wind_speed_max_today" not in d:
        d["wind_speed_max_today"] = 0
    if "wind_gusts_max_today" not in d:
        d["wind_gusts_max_today"] = d.get("wind_speed_max_today", 0)

    # Fill rolling features nếu frontend chưa gửi đủ.
    d.setdefault("temp_mean_3d", d["temp_mean_today"])
    d.setdefault("humidity_mean_3d", d["humidity_mean_today"])
    d.setdefault("precipitation_sum_3d", d["precipitation_sum_today"])
    d.setdefault("rain_sum_3d", d["rain_sum_today"])
    d.setdefault("temp_mean_7d", d["temp_mean_today"])
    d.setdefault("humidity_mean_7d", d["humidity_mean_today"])
    d.setdefault("precipitation_sum_7d", d["precipitation_sum_today"])
    d.setdefault("rain_sum_7d", d["rain_sum_today"])
    d.setdefault("rain_days_7d", 1 if float(d.get("rain_sum_today") or 0) > 0 else 0)

    # Cast numeric nhẹ để model không nhận string.
    for col in DEFAULT_WEATHER_FEATURE_COLS + ["month"]:
        if col in d:
            try:
                d[col] = float(d[col]) if col != "month" else int(d[col])
            except Exception:
                pass
    meta = {
        "source": "manual",
        "date": str(today),
        "daily_series": [{
            "date": str(today),
            "temp_mean_today": float(d.get("temp_mean_today", 0)),
            "humidity_mean_today": float(d.get("humidity_mean_today", 0)),
            "rain_sum_today": float(d.get("rain_sum_today", 0)),
            "precipitation_sum_today": float(d.get("precipitation_sum_today", d.get("rain_sum_today", 0))),
        }],
    }
    return d, meta


def _risk_level(score: float, quantiles: dict[str, float]) -> str:
    q75 = float(quantiles.get("q75", 0.15))
    q90 = float(quantiles.get("q90", 0.35))
    if score >= q90:
        return "Cao"
    if score >= q75:
        return "Trung bình"
    return "Thấp"




def _normalize_option(value: str, valid_values: list[str], field_name: str) -> str:
    """Chuẩn hoá input text và báo lỗi rõ nếu frontend gửi sai option."""
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"Thiếu {field_name}.")

    if value in valid_values:
        return value

    lower_map = {str(v).strip().lower(): v for v in valid_values}
    matched = lower_map.get(value.lower())
    if matched is not None:
        return matched

    preview = ", ".join(map(str, valid_values[:10]))
    if len(valid_values) > 10:
        preview += ", ..."
    raise ValueError(
        f"{field_name} không hợp lệ: {value!r}. "
        f"Hãy gọi GET /api/weather-ai/options để lấy danh sách hợp lệ. "
        f"Một số giá trị hợp lệ: {preview}"
    )

def predict_weather_risk(
    age_group: str,
    gender: str,
    top_k: int = 5,
    weather: dict[str, Any] | None = None,
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    timezone: str = DEFAULT_TIMEZONE,
    target_date: date | None = None,
) -> dict[str, Any]:
    artifact = load_weather_ai_artifact()
    top_k = max(1, min(int(top_k), 20))

    # Swagger UI hay tạo ví dụ "weather": {}. Dict rỗng không phải manual weather,
    # nên coi như không gửi weather để backend tự lấy Open-Meteo realtime.
    if isinstance(weather, dict) and len(weather) == 0:
        weather = None

    age_group = _normalize_option(age_group, artifact.get("age_groups", []), "age_group")
    gender = _normalize_option(gender, artifact.get("genders", []), "gender")

    if weather is None:
        if latitude is None or longitude is None:
            raise ValueError("latitude va longitude la bat buoc khi dung thoi tiet realtime.")
        weather_features, weather_meta = fetch_current_weather_features(latitude, longitude, timezone, target_date)
    else:
        weather_features, weather_meta = complete_manual_weather_features(weather, target_date)

    month = int(weather_features.get("month") or (target_date or datetime.now().date()).month)
    season = str(weather_features.get("season") or month_to_season_vn(month))

    rows = []
    for disease in artifact["disease_catalog"]:
        row = {
            "age_group": age_group,
            "gender": gender,
            "disease_group_id": str(disease["disease_group_id"]),
            "report_group_code": str(disease.get("report_group_code") or ""),
            "season": season,
            "month": month,
        }
        for col in artifact.get("weather_feature_columns", DEFAULT_WEATHER_FEATURE_COLS):
            row[col] = weather_features.get(col)
        # weather_code là categorical trong model, để dạng string ổn định.
        row["weather_code"] = str(row.get("weather_code", 0))
        rows.append(row)

    X = pd.DataFrame(rows)
    X = X[artifact["feature_columns"]]
    prob = artifact["classifier"].predict_proba(X)[:, 1]
    pred_log_cases = artifact["regressor"].predict(X)
    pred_cases = np.clip(np.expm1(pred_log_cases), 0, 1_000_000)
    scores = prob * np.log1p(pred_cases)

    output = []
    for disease, p, cases, score in zip(artifact["disease_catalog"], prob, pred_cases, scores):
        output.append({
            "disease_group_id": str(disease["disease_group_id"]),
            "report_group_code": str(disease.get("report_group_code") or ""),
            "disease_group_name": str(disease.get("disease_group_name") or ""),
            "probability": round(float(p), 4),
            "predicted_cases": round(float(cases), 2),
            "predicted_cases_unit": PREDICTED_CASES_UNIT,
            "risk_score": round(float(score), 4),
            "risk_level": _risk_level(float(score), artifact.get("risk_score_quantiles", {})),
        })

    output.sort(key=lambda x: (x["risk_score"], x["predicted_cases"], x["probability"]), reverse=True)
    top = output[:top_k]

    return {
        "message": "Dự đoán nhóm bệnh nguy cơ cao theo thời tiết. Đây là cảnh báo thống kê, không phải chẩn đoán y tế.",
        "input": {
            "age_group": age_group,
            "gender": gender,
            "top_k": top_k,
        },
        "weather": {
            "meta": weather_meta,
            "features": {k: weather_features.get(k) for k in artifact.get("weather_feature_columns", DEFAULT_WEATHER_FEATURE_COLS)},
            "month": month,
            "season": season,
        },
        "top_risks": top,
        "model": {
            "model_type": artifact.get("model_type"),
            "training_summary": artifact.get("training_summary", {}),
            "training_weather_scope": MODEL_TRAINING_WEATHER_SCOPE,
            "runtime_weather_note": MODEL_RUNTIME_WEATHER_NOTE,
            "predicted_cases_unit": PREDICTED_CASES_UNIT,
        },
    }
