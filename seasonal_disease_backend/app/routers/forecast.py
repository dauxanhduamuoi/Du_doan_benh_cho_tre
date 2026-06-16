from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ForecastResult, MonthlyStatistic, User
from app.security import require_permission
from app.services.forecast_service import run_forecast

router = APIRouter(prefix="/api/forecast", tags=["Forecast"])


def _next_period_after_latest_predict_current(db: Session) -> str | None:
    latest = db.query(func.max(MonthlyStatistic.period)).filter(
        MonthlyStatistic.data_type == "predict_current"
    ).scalar()
    if not latest:
        return None

    import pandas as pd

    return str(pd.Period(str(latest), freq="M") + 1)


def _default_forecast_period(db: Session) -> str | None:
    """
    Forecast screens should follow the current imported patient data.
    If predict_current ends at 2025-04, the default forecast period is 2025-05;
    stale results from older imports/runs must not be mixed into the response.
    """
    expected_period = _next_period_after_latest_predict_current(db)
    if not expected_period:
        return None

    exists = db.query(ForecastResult.id).filter(
        ForecastResult.forecast_period == expected_period
    ).first()
    return expected_period if exists else None

@router.post("/run")
def run_ai_forecast(
    last_completed_period: str = Query("auto"),
    forecast_horizon: int = Query(1, ge=1, le=3),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.forecast")),
):
    try:
        result = run_forecast(
            db=db,
            last_completed_period=last_completed_period,
            forecast_horizon=forecast_horizon,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": "Chạy dự báo thành công.",
        "result": result,
    }


@router.get("/results")
def get_forecast_results(
    forecast_period: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.forecast")),
):
    query = db.query(ForecastResult)

    period_filter = forecast_period or _default_forecast_period(db)
    if period_filter:
        query = query.filter(ForecastResult.forecast_period == period_filter)
    elif forecast_period is None:
        query = query.filter(ForecastResult.id == -1)

    rows = query.order_by(
        ForecastResult.forecast_period.desc(),
        ForecastResult.risk_level.asc(),
        ForecastResult.predicted_cases.desc()
    ).all()

    return rows

@router.get("/group-summary")
def get_group_summary(
    forecast_period: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.forecast")),
):
    query = db.query(ForecastResult)

    period_filter = forecast_period or _default_forecast_period(db)
    if period_filter:
        query = query.filter(ForecastResult.forecast_period == period_filter)
    elif forecast_period is None:
        query = query.filter(ForecastResult.id == -1)

    rows = query.all()

    # Bỏ các dòng "Không thể dự đoán" khi tổng hợp theo nhóm bệnh để
    # predicted_cases tổng không bị kéo xuống bởi các nhóm không dự đoán được.
    rows = [r for r in rows if r.trend != "Không thể dự đoán"]

    summary = {}

    for r in rows:
        key = (r.forecast_period, r.disease_group)

        if key not in summary:
            summary[key] = {
                "forecast_period": r.forecast_period,
                "disease_group": r.disease_group,
                "previous_cases": 0,
                "predicted_cases": 0,
            }

        summary[key]["previous_cases"] += r.previous_cases
        summary[key]["predicted_cases"] += r.predicted_cases

    output = []

    for item in summary.values():
        previous_cases = item["previous_cases"]
        predicted_cases = item["predicted_cases"]

        if previous_cases > 0:
            change_percent = (predicted_cases - previous_cases) / previous_cases * 100
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
        else:
            risk_level = "Thấp"

        item["change_percent"] = round(change_percent, 2) if change_percent is not None else None
        item["trend"] = trend
        item["risk_level"] = risk_level

        output.append(item)

    risk_rank = {"Cao": 3, "Trung bình": 2, "Thấp": 1}

    output = sorted(
        output,
        key=lambda x: (x["forecast_period"], risk_rank.get(x["risk_level"], 0), x["predicted_cases"]),
        reverse=True
    )

    return output


@router.get("/accuracy")
def get_forecast_accuracy(
    forecast_period: str = Query(..., description="Tháng đã dự báo trước đó, ví dụ: 2026-05"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.forecast")),
):
    """
    So sánh dự đoán cũ vs thực tế.
    Lấy forecast_results của tháng đó, đối chiếu với monthly_statistics
    (predict_current) nếu đã có dữ liệu thực tế import vào.
    """
    # Lấy kết quả dự báo cho tháng này
    forecasts = db.query(ForecastResult).filter(
        ForecastResult.forecast_period == forecast_period
    ).all()

    if not forecasts:
        raise HTTPException(
            status_code=404,
            detail=f"Không có kết quả dự báo cho tháng {forecast_period}."
        )

    # Lấy số ca thực tế từ predict_current cho tháng này (nếu đã import)
    actuals = db.query(
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("actual_cases")
    ).filter(
        MonthlyStatistic.data_type == "predict_current",
        MonthlyStatistic.period == forecast_period
    ).group_by(
        MonthlyStatistic.disease_group
    ).all()

    actual_map = {r.disease_group: int(r.actual_cases) for r in actuals}

    if not actual_map:
        raise HTTPException(
            status_code=404,
            detail=f"Chưa có dữ liệu thực tế cho tháng {forecast_period}. "
                   "Hãy import predict_current chứa tháng này để so sánh."
        )

    # Gom predicted_cases theo disease_group (cộng tất cả age_group)
    predicted_map = {}
    for f in forecasts:
        if f.trend == "Không thể dự đoán":
            continue
        if f.disease_group not in predicted_map:
            predicted_map[f.disease_group] = 0
        predicted_map[f.disease_group] += f.predicted_cases

    # So sánh
    output = []
    total_predicted = 0
    total_actual = 0
    total_error = 0

    all_groups = set(predicted_map.keys()) | set(actual_map.keys())

    for dg in all_groups:
        predicted = predicted_map.get(dg, 0)
        actual = actual_map.get(dg, 0)
        error = abs(predicted - actual)
        accuracy = round((1 - error / actual) * 100, 1) if actual > 0 else None

        total_predicted += predicted
        total_actual += actual
        total_error += error

        output.append({
            "disease_group": dg,
            "predicted_cases": predicted,
            "actual_cases": actual,
            "error": error,
            "accuracy_percent": accuracy,
        })

    output.sort(key=lambda x: x["actual_cases"], reverse=True)

    overall_accuracy = round((1 - total_error / total_actual) * 100, 1) if total_actual > 0 else None

    return {
        "forecast_period": forecast_period,
        "overall": {
            "total_predicted": total_predicted,
            "total_actual": total_actual,
            "total_error": total_error,
            "overall_accuracy_percent": overall_accuracy,
        },
        "details": output,
    }
