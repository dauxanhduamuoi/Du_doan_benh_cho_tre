from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DiseaseKnowledge, ForecastResult
from app.services.weather_ai_service import (
    DEFAULT_TIMEZONE,
    get_weather_ai_options,
    predict_weather_risk,
)

router = APIRouter(prefix="/api/public", tags=["Public"])


class ParentRiskRequest(BaseModel):
    age_group: str = Field(..., description="Nhóm tuổi của trẻ, ví dụ: 1-5 tuổi")
    gender: str = Field(..., description="Giới tính của trẻ")
    top_k: int = Field(5, ge=1, le=20)
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = Field(DEFAULT_TIMEZONE)
    weather: dict[str, Any] | None = None

@router.get("/current-risks")
def current_risks(
    forecast_period: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(ForecastResult)

    if forecast_period:
        query = query.filter(ForecastResult.forecast_period == forecast_period)

    rows = query.all()

    # Bỏ các dòng "Không thể dự đoán" để public chỉ thấy nhóm bệnh đã được dự báo.
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
        key=lambda x: (risk_rank.get(x["risk_level"], 0), x["predicted_cases"]),
        reverse=True
    )

    return output

@router.get("/disease-knowledge")
def disease_knowledge(db: Session = Depends(get_db)):
    rows = db.query(DiseaseKnowledge).order_by(DiseaseKnowledge.id.desc()).all()
    return [
        {
            "id": r.id,
            "disease_group": r.disease_group,
            "title": r.title,
            "description": r.description,
            "symptoms": r.symptoms,
            "warning_signs": r.warning_signs,
            "prevention": r.prevention,
        }
        for r in rows
    ]


@router.get("/weather-options")
def public_weather_options():
    try:
        return get_weather_ai_options()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/parent-risk")
def parent_risk(payload: ParentRiskRequest):
    """
    Public endpoint cho trang phụ huynh.
    Không yêu cầu đăng nhập; chỉ dùng tuổi, giới tính và tọa độ trình duyệt để lấy thời tiết realtime.
    """
    try:
        if payload.weather is None and (payload.latitude is None or payload.longitude is None):
            raise HTTPException(
                status_code=400,
                detail="Thiếu tọa độ để lấy thời tiết realtime. Hãy bật định vị hoặc chọn tỉnh/thành phố có tọa độ.",
            )
        return predict_weather_risk(
            age_group=payload.age_group,
            gender=payload.gender,
            top_k=payload.top_k,
            weather=payload.weather,
            latitude=payload.latitude,
            longitude=payload.longitude,
            timezone=payload.timezone,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
