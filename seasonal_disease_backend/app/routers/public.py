from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DiseaseKnowledge
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
