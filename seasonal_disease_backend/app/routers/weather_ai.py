from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict, model_validator

from app.models import User
from app.security import require_permission
from app.services.weather_ai_service import (
    DEFAULT_TIMEZONE,
    get_model_status,
    get_weather_ai_options,
    predict_weather_risk,
)

router = APIRouter(prefix="/api/weather-ai", tags=["Weather AI"])


class WeatherAIPredictRequest(BaseModel):
    # Ví dụ mẫu HIỂN THỊ trực tiếp đúng body cần gửi.
    # Không dùng dạng {"summary": ..., "value": ...} vì Swagger có thể copy nhầm
    # cả wrapper đó vào request body, làm API báo thiếu age_group/gender.
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "age_group": "1-5 tuổi",
                "gender": "Nam",
                "top_k": 5,
            }
        }
    )

    @model_validator(mode="before")
    @classmethod
    def unwrap_swagger_example_value(cls, data):
        """
        Chống lỗi khi người dùng lỡ copy nguyên ví dụ Swagger dạng:
        {"summary": "...", "value": {"age_group": "1-5 tuổi", ...}}
        Khi gặp dạng này, tự lấy phần value để API vẫn chạy.
        """
        if isinstance(data, dict) and "value" in data and isinstance(data["value"], dict):
            return data["value"]
        return data

    age_group: str = Field(..., description="Nhóm tuổi. Ví dụ: 1-5 tuổi", examples=["1-5 tuổi"])
    gender: str = Field(..., description="Giới tính. Ví dụ: Nam hoặc Nữ", examples=["Nam"])
    top_k: int = Field(5, ge=1, le=20, description="Số nhóm bệnh muốn lấy ở kết quả top")

    # Nếu không gửi weather hoặc gửi weather={} thì backend tự lấy Open-Meteo realtime.
    # Nếu muốn test không cần internet, gửi weather thủ công.
    weather: dict[str, Any] | None = Field(
        default=None,
        description="Bỏ trống để backend tự lấy weather realtime. Chỉ gửi khi muốn test thủ công.",
    )

    latitude: float | None = Field(None, description="Tọa độ latitude dùng khi tự lấy Open-Meteo")
    longitude: float | None = Field(None, description="Tọa độ longitude dùng khi tự lấy Open-Meteo")
    timezone: str = Field(DEFAULT_TIMEZONE, description="Timezone dùng khi tự lấy Open-Meteo")
    target_date: date | None = Field(default=None, description="Để trống để dùng ngày mới nhất từ Open-Meteo")


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


@router.post("/predict-risk")
def predict_risk(
    payload: WeatherAIPredictRequest,
    current_user: User = Depends(require_permission("feature.weather_risk")),
):
    """
    Dự đoán top nhóm bệnh có nguy cơ ghi nhận ca cao theo thời tiết.

    Cách dùng đơn giản từ frontend:
    - Gửi age_group + gender + latitude + longitude.
    - Không gửi weather: backend tự lấy weather realtime từ Open-Meteo theo tọa độ đã gửi.

    Cách test không cần internet:
    - Gửi thêm weather thủ công gồm temperature/humidity/rain...
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
