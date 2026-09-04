from typing import Any

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import (
    AUTO_MEDICAL_KNOWLEDGE_INSUFFICIENT_STALE_DAYS,
    AUTO_MEDICAL_KNOWLEDGE_MAX_RETRIES,
)
from app.models import DiseaseKnowledge
from app.published_medical_knowledge_schemas import (
    PublishedMedicalKnowledgeBatchRequest,
    PublishedMedicalKnowledgeBatchResponse,
)
from app.services.published_medical_knowledge_read_service import (
    PublishedMedicalKnowledgeReadService,
)
from app.services.auto_medical_knowledge_service import AutoMedicalKnowledgeQueueService
from app.services.weather_ai_service import (
    DEFAULT_TIMEZONE,
    get_weather_ai_options,
    predict_weather_risk,
)
from app.services.weather_ai_runtime import ModelRuntimeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["Public"])


class ParentRiskRequest(BaseModel):
    age_group: str = Field(..., description="Nhóm tuổi của trẻ, ví dụ: 1-5 tuổi")
    gender: str = Field(..., description="Giới tính của trẻ")
    top_k: int = Field(5, ge=1, le=20)
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = Field(DEFAULT_TIMEZONE)
    weather: dict[str, Any] | None = None


def get_published_medical_knowledge_read_service(
    db: Session = Depends(get_db),
) -> PublishedMedicalKnowledgeReadService:
    queue = AutoMedicalKnowledgeQueueService(
        db,
        max_retries=AUTO_MEDICAL_KNOWLEDGE_MAX_RETRIES,
        insufficient_stale_days=AUTO_MEDICAL_KNOWLEDGE_INSUFFICIENT_STALE_DAYS,
    )
    return PublishedMedicalKnowledgeReadService(
        db,
        auto_queue=queue,
    )

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


@router.post(
    "/medical-knowledge/published",
    response_model=PublishedMedicalKnowledgeBatchResponse,
)
def published_medical_knowledge(
    payload: PublishedMedicalKnowledgeBatchRequest,
    service: PublishedMedicalKnowledgeReadService = Depends(
        get_published_medical_knowledge_read_service
    ),
):
    """Return only consistent, current publication-safe Medical Knowledge views."""

    return service.read_batch(payload)


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
                status_code=422,
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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelRuntimeError as exc:
        raise HTTPException(status_code=503, detail="Weather AI model service is unavailable.") from exc
    except Exception as exc:
        logger.exception("Public parent Weather AI request failed")
        raise HTTPException(status_code=500, detail="Weather AI runtime error.") from exc
