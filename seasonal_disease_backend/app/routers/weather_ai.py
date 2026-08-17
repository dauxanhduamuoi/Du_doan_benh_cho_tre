from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.models import User
from app.security import require_permission
from app.services.weather_ai_service import (
    get_model_status,
    get_weather_ai_options,
    predict_weather_risk,
)
from app.services.weather_ai_runtime import ModelRuntimeError
from app.weather_ai_schemas import WeatherAIPredictRequest, WeatherAIPredictResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/weather-ai", tags=["Weather AI"])

@router.get("/status")
def weather_ai_status(current_user: User = Depends(require_permission("feature.weather_risk"))):
    """Kiểm tra model AI thời tiết đã sẵn sàng chưa."""
    return get_model_status()


@router.get("/options")
def weather_ai_options(current_user: User = Depends(require_permission("feature.weather_risk"))):
    """Lấy nhóm tuổi, giới tính và danh mục nhóm bệnh model đang hỗ trợ."""
    try:
        return get_weather_ai_options()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/predict-risk", response_model=WeatherAIPredictResponse)
def predict_risk(
    payload: WeatherAIPredictRequest,
    current_user: User = Depends(require_permission("feature.weather_risk")),
):
    """
    Xếp hạng tương đối các nhóm bệnh đáng lưu ý trong context hiện tại.

    Cách dùng đơn giản từ frontend:
    - Gửi age_group + gender + latitude + longitude.
    - Không gửi weather: backend tự lấy weather realtime từ Open-Meteo theo tọa độ đã gửi.

    Manual mode phải gửi đủ locked weather features hoặc lịch sử daily 7 ngày.
    Response giữ `top_risks` làm alias tương thích và bổ sung `predictions`, Tier 1, Tier 2.
    """
    try:
        if payload.weather is None and (payload.latitude is None or payload.longitude is None):
            raise HTTPException(status_code=400, detail="Cần gửi latitude và longitude khi dùng thời tiết realtime.")
        return predict_weather_risk(
            age_group=payload.age_group,
            gender=payload.gender,
            top_k=payload.top_k,
            weather=payload.weather,
            latitude=payload.latitude,
            longitude=payload.longitude,
            timezone=payload.timezone,
            target_date=payload.target_date,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelRuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Weather AI request failed")
        raise HTTPException(status_code=500, detail="Weather AI runtime error.") from exc
