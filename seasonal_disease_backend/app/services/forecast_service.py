from pathlib import Path
from functools import lru_cache
import numpy as np
import pandas as pd
import joblib
from sqlalchemy.orm import Session

from app.models import ForecastResult, MonthlyStatistic
from app.services.data_processing_service import (
    month_to_season_vn,
    load_disease_codes,
    process_patients,
    create_monthly_stats,
)

APP_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = APP_ROOT / "ml" / "seasonal_disease_forecast_model.pkl"
TRAIN_HISTORY_PATH = APP_ROOT / "ml" / "seasonal_forecast_data" / "train_history.xlsx"

FEATURE_COLS = [
    "disease_target",
    "age_group",
    "target_season",
    "target_year",
    "target_month_num",
    "target_month_sin",
    "target_month_cos",
    "lag_1",
    "lag_2",
    "lag_3",
    "lag_4",
    "lag_5",
    "rolling_3",
    "rolling_5",
    "change_1",
]

@lru_cache(maxsize=4)
def _load_train_monthly_from_excel_cached(file_path: str, mtime: float) -> pd.DataFrame:
    """
    Đọc train_history.xlsx đi kèm model và chuyển thành monthly_statistics trong RAM.

    Quy ước mới: 1 model forecast đi kèm 1 file Excel train_history.xlsx gồm 2 sheet:
    - DS-BenhNhan
    - DS-MaBenh

    File này không import qua API và không lưu vào DB để tránh trộn dữ liệu model với dữ liệu người dùng.
    mtime được đưa vào cache key để nếu thay file và restart/gọi lại thì dữ liệu được đọc lại.
    """
    disease_codes = load_disease_codes(file_path)
    patient_df = process_patients(file_path, disease_codes)
    monthly_stats = create_monthly_stats(patient_df)

    if monthly_stats.empty:
        raise ValueError("File train_history.xlsx không tạo được dữ liệu monthly_statistics cho model.")

    required = ["period", "year", "month", "season", "disease_group", "age_group", "case_count"]
    missing = [c for c in required if c not in monthly_stats.columns]
    if missing:
        raise ValueError(f"Dữ liệu monthly_statistics tạo từ train_history.xlsx thiếu cột: {missing}")

    monthly_stats = monthly_stats[required].copy()
    monthly_stats["period"] = monthly_stats["period"].astype(str)
    monthly_stats["year"] = monthly_stats["year"].astype(int)
    monthly_stats["month"] = monthly_stats["month"].astype(int)
    monthly_stats["case_count"] = monthly_stats["case_count"].astype(int)
    return monthly_stats


def get_train_monthly_stats_df() -> pd.DataFrame:
    if not TRAIN_HISTORY_PATH.exists():
        raise FileNotFoundError(
            "Không tìm thấy file train_history.xlsx đi kèm model tại "
            f"{TRAIN_HISTORY_PATH}. File này cần có 2 sheet: DS-BenhNhan và DS-MaBenh."
        )

    return _load_train_monthly_from_excel_cached(
        str(TRAIN_HISTORY_PATH),
        TRAIN_HISTORY_PATH.stat().st_mtime,
    ).copy()


def get_monthly_stats_df(db: Session, data_type: str) -> pd.DataFrame:
    """
    Lấy dữ liệu monthly_statistics.

    - predict_current: đọc từ DB vì đây là dữ liệu bệnh viện/người dùng import.
    - train_history: đọc trực tiếp từ file Excel cố định đi kèm model tại
      app/ml/seasonal_forecast_data/train_history.xlsx.
    """
    if data_type == "train_history":
        return get_train_monthly_stats_df()

    rows = db.query(MonthlyStatistic).filter(MonthlyStatistic.data_type == data_type).all()

    return pd.DataFrame([
        {
            "period": r.period,
            "year": r.year,
            "month": r.month,
            "season": r.season,
            "disease_group": r.disease_group,
            "age_group": r.age_group,
            "case_count": r.case_count,
        }
        for r in rows
    ])

def get_last_completed_period(predict_monthly: pd.DataFrame, last_completed_period: str = "auto") -> str:
    if last_completed_period == "auto":
        return str(pd.Period(predict_monthly["period"].max(), freq="M"))
    return str(pd.Period(last_completed_period, freq="M"))

def get_forecast_periods(last_completed_period: str, forecast_horizon: int = 1):
    last_p = pd.Period(last_completed_period, freq="M")
    return [str(last_p + i) for i in range(1, forecast_horizon + 1)]

def complete_predict_grid(predict_monthly, combinations, start_period, end_period):
    min_period = pd.Period(start_period, freq="M")
    max_period = pd.Period(end_period, freq="M")

    all_periods = pd.period_range(min_period, max_period, freq="M").astype(str)

    period_df = pd.DataFrame({"period": all_periods})
    period_df["year"] = pd.PeriodIndex(period_df["period"], freq="M").year
    period_df["month"] = pd.PeriodIndex(period_df["period"], freq="M").month
    period_df["season"] = period_df["month"].apply(month_to_season_vn)

    grid = combinations.merge(period_df, how="cross")

    full = grid.merge(
        predict_monthly[["period", "disease_group", "age_group", "case_count"]],
        on=["period", "disease_group", "age_group"],
        how="left"
    )

    full["case_count"] = full["case_count"].fillna(0).astype(int)

    return full.sort_values(["disease_group", "age_group", "period"]).reset_index(drop=True)

def build_prediction_input(
    predict_monthly: pd.DataFrame,
    combinations: pd.DataFrame,
    forecast_period: str,
) -> pd.DataFrame:
    """
    Tạo feature dataframe cho 1 tháng forecast.

    predict_monthly  : dataframe đang lưu lịch sử tháng đã có ca thật + ca đã
                       được dự đoán ở các vòng trước (recursive forecasting).
    combinations     : tập (disease_group, age_group) cần dự báo.
    forecast_period  : 'YYYY-MM' tháng cần dự báo.
    """
    forecast_p = pd.Period(forecast_period, freq="M")

    start_period = str(forecast_p - 5)
    end_period = str(forecast_p - 1)

    predict_full = complete_predict_grid(
        predict_monthly=predict_monthly,
        combinations=combinations,
        start_period=start_period,
        end_period=end_period,
    )

    rows = []

    for _, combo in combinations.iterrows():
        disease_group = combo["disease_group"]
        age_group = combo["age_group"]

        temp = predict_full[
            (predict_full["disease_group"] == disease_group) &
            (predict_full["age_group"] == age_group)
        ].copy()

        def get_cases(period):
            value = temp.loc[temp["period"] == period, "case_count"]
            if value.empty:
                return 0
            return int(value.iloc[0])

        lag_1 = get_cases(str(forecast_p - 1))
        lag_2 = get_cases(str(forecast_p - 2))
        lag_3 = get_cases(str(forecast_p - 3))
        lag_4 = get_cases(str(forecast_p - 4))
        lag_5 = get_cases(str(forecast_p - 5))

        rolling_3 = float(np.mean([lag_1, lag_2, lag_3]))
        rolling_5 = float(np.mean([lag_1, lag_2, lag_3, lag_4, lag_5]))
        change_1 = lag_1 - lag_2

        rows.append(
            {
                "disease_target": disease_group,
                "age_group": age_group,
                "target_year": forecast_p.year,
                "target_month_num": forecast_p.month,
                "target_season": month_to_season_vn(forecast_p.month),
                "target_month_sin": np.sin(2 * np.pi * forecast_p.month / 12),
                "target_month_cos": np.cos(2 * np.pi * forecast_p.month / 12),
                "lag_1": lag_1,
                "lag_2": lag_2,
                "lag_3": lag_3,
                "lag_4": lag_4,
                "lag_5": lag_5,
                "rolling_3": rolling_3,
                "rolling_5": rolling_5,
                "change_1": change_1,
                "previous_cases": lag_1,
                "forecast_period": str(forecast_p),
            }
        )

    return pd.DataFrame(rows)

def classify_trend_and_risk(previous_cases, predicted_cases, rolling_3):
    previous_cases = float(previous_cases)
    predicted_cases = float(predicted_cases)
    rolling_3 = float(rolling_3) if not pd.isna(rolling_3) else 0

    if previous_cases > 0:
        change_percent = ((predicted_cases - previous_cases) / previous_cases) * 100
    else:
        change_percent = None

    if previous_cases == 0 and predicted_cases > 0:
        trend = "Tăng từ 0 ca"
    elif change_percent is None:
        trend = "Không đủ dữ liệu"
    elif change_percent >= 30:
        trend = "Tăng mạnh"
    elif change_percent >= 10:
        trend = "Tăng"
    elif change_percent <= -30:
        trend = "Giảm mạnh"
    elif change_percent <= -10:
        trend = "Giảm"
    else:
        trend = "Ổn định"

    if change_percent is None:
        risk_level = "Trung bình" if predicted_cases > 0 else "Thấp"
    elif change_percent >= 30 and predicted_cases >= 5:
        risk_level = "Cao"
    elif change_percent >= 10 and predicted_cases >= 5:
        risk_level = "Trung bình"
    elif predicted_cases >= max(rolling_3 * 1.5, 10):
        risk_level = "Cao"
    else:
        risk_level = "Thấp"

    return trend, risk_level, change_percent

def _validate_window(predict_monthly: pd.DataFrame, forecast_period: str) -> None:
    """
    Kiểm tra cửa sổ 5 tháng liền trước forecast_period có đủ trong predict_monthly
    hay không. Thiếu tháng dễ khiến model dự đoán sai (vì các tháng thiếu sẽ bị
    coi là 0 ca khi build features).
    """
    forecast_p = pd.Period(forecast_period, freq="M")
    needed = {str(forecast_p - i) for i in range(1, 6)}
    available = set(predict_monthly["period"].astype(str).unique())
    missing = sorted(needed - available)

    if missing:
        raise ValueError(
            "Dữ liệu predict_current thiếu các tháng cần thiết để dự báo "
            f"{forecast_period}: {missing}. "
            "Hãy import file predict_current chứa đủ 5 tháng liền trước."
        )


def run_forecast(db: Session, last_completed_period: str = "auto", forecast_horizon: int = 1):
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Không tìm thấy model tại {MODEL_PATH}. Hãy copy file .pkl từ notebook vào app/ml/."
        )

    predict_monthly = get_monthly_stats_df(db, "predict_current")
    train_monthly = get_monthly_stats_df(db, "train_history")

    if predict_monthly.empty:
        raise ValueError(
            "Chưa có dữ liệu predict_current. Hãy import file predict_current.xlsx trước."
        )

    if train_monthly.empty:
        raise ValueError(
            "Chưa đọc được dữ liệu train_history đi kèm model. Hãy kiểm tra app/ml/seasonal_forecast_data/train_history.xlsx."
        )

    last_completed_period = get_last_completed_period(predict_monthly, last_completed_period)
    forecast_periods = get_forecast_periods(last_completed_period, forecast_horizon)

    # Combinations chỉ lấy từ train_history vì model chỉ có thể dự đoán đáng
    # tin cho các combo (nhóm bệnh + nhóm tuổi) đã từng nhìn thấy lúc huấn luyện.
    # Combo chỉ xuất hiện ở predict_current sẽ được báo cáo riêng qua field
    # untrained_groups thay vì đưa cho model dự đoán bừa.
    train_combos = (
        train_monthly[["disease_group", "age_group"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )

    # Phát hiện các combo chỉ có trong predict_current (model chưa học).
    train_keys = set(
        zip(train_combos["disease_group"], train_combos["age_group"])
    )

    untrained_rows = []

    if not predict_monthly.empty:
        latest_period = predict_monthly["period"].max()

        predict_combos = (
            predict_monthly[["disease_group", "age_group"]]
            .drop_duplicates()
            .reset_index(drop=True)
        )

        for _, combo in predict_combos.iterrows():
            key = (combo["disease_group"], combo["age_group"])
            if key in train_keys:
                continue

            recent = predict_monthly[
                (predict_monthly["disease_group"] == combo["disease_group"]) &
                (predict_monthly["age_group"] == combo["age_group"]) &
                (predict_monthly["period"] == latest_period)
            ]
            recent_cases = int(recent["case_count"].sum()) if not recent.empty else 0

            untrained_rows.append({
                "disease_group": combo["disease_group"],
                "age_group": combo["age_group"],
                "recent_cases": recent_cases,
                "recent_period": str(latest_period),
            })

    # Sắp xếp untrained groups theo số ca giảm dần để phần đáng chú ý nhất lên đầu.
    untrained_rows.sort(key=lambda x: x["recent_cases"], reverse=True)

    model = joblib.load(MODEL_PATH)

    all_results = []

    # Recursive forecasting. Sau khi dự đoán tháng k, ta thêm kết quả vào
    # working_monthly để khi dự đoán tháng k+1, lag_1 chính là kết quả vừa
    # dự đoán thay vì 0.
    working_monthly = predict_monthly.copy()

    for forecast_period in forecast_periods:
        _validate_window(working_monthly, forecast_period)

        predict_input = build_prediction_input(
            predict_monthly=working_monthly,
            combinations=train_combos,
            forecast_period=forecast_period,
        )
        X_forecast = predict_input[FEATURE_COLS]

        predicted = model.predict(X_forecast)
        predicted = np.clip(predicted, 0, None)

        result_df = predict_input.copy()
        result_df["predicted_cases"] = np.round(predicted).astype(int)

        for _, row in result_df.iterrows():
            trend, risk_level, change_percent = classify_trend_and_risk(
                row["previous_cases"],
                row["predicted_cases"],
                row["rolling_3"]
            )

            all_results.append(
                ForecastResult(
                    forecast_period=row["forecast_period"],
                    disease_group=row["disease_target"],
                    age_group=row["age_group"],
                    previous_cases=int(row["previous_cases"]),
                    predicted_cases=int(row["predicted_cases"]),
                    change_percent=round(change_percent, 2) if change_percent is not None else None,
                    trend=trend,
                    risk_level=risk_level,
                )
            )

        # Append kết quả tháng vừa dự đoán vào working_monthly để vòng kế dùng làm lag.
        appended = pd.DataFrame(
            {
                "period": result_df["forecast_period"],
                "year": pd.PeriodIndex(result_df["forecast_period"], freq="M").year,
                "month": pd.PeriodIndex(result_df["forecast_period"], freq="M").month,
                "season": [
                    month_to_season_vn(pd.Period(p, freq="M").month)
                    for p in result_df["forecast_period"]
                ],
                "disease_group": result_df["disease_target"],
                "age_group": result_df["age_group"],
                "case_count": result_df["predicted_cases"].astype(int),
            }
        )
        working_monthly = pd.concat([working_monthly, appended], ignore_index=True)

    # Thêm các dòng "Không thể dự đoán" cho untrained groups, để dashboard
    # hiển thị đầy đủ và staff/IT biết những nhóm bệnh nào cần cập nhật model.
    # previous_cases lấy số ca thực tế ở tháng last_completed_period.
    last_completed_str = str(pd.Period(last_completed_period, freq="M"))

    for combo in untrained_rows:
        disease_group = combo["disease_group"]
        age_group = combo["age_group"]

        matching = predict_monthly[
            (predict_monthly["disease_group"] == disease_group) &
            (predict_monthly["age_group"] == age_group) &
            (predict_monthly["period"] == last_completed_str)
        ]
        previous_cases = int(matching["case_count"].sum()) if not matching.empty else 0

        for forecast_period in forecast_periods:
            all_results.append(
                ForecastResult(
                    forecast_period=forecast_period,
                    disease_group=disease_group,
                    age_group=age_group,
                    previous_cases=previous_cases,
                    predicted_cases=0,
                    change_percent=None,
                    trend="Không thể dự đoán",
                    risk_level="Không xác định",
                )
            )

    # Xóa kết quả cũ của các tháng dự báo rồi lưu lại
    db.query(ForecastResult).filter(ForecastResult.forecast_period.in_(forecast_periods)).delete(synchronize_session=False)
    db.add_all(all_results)
    db.commit()

    response = {
        "last_completed_period": last_completed_period,
        "forecast_periods": forecast_periods,
        "rows": len(all_results),
        "untrained_groups_count": len(untrained_rows),
        "untrained_groups": untrained_rows,
    }

    if untrained_rows:
        response["warning"] = (
            f"Có {len(untrained_rows)} nhóm bệnh - độ tuổi xuất hiện trong dữ liệu hiện tại "
            "nhưng không có trong dữ liệu huấn luyện. Mô hình bỏ qua các nhóm này để giữ "
            "độ tin cậy của dự báo. Cân nhắc bổ sung dữ liệu vào train_history và huấn luyện "
            "lại model và cập nhật file train_history.xlsx đi kèm model."
        )

    return response
