from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.weather_ai_features import DEFAULT_TIMEZONE


class WeatherAIPredictRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "age_group": "1-5 tuổi",
                "gender": "Nam",
                "top_k": 5,
                "latitude": 10.790861,
                "longitude": 106.6313,
            }
        }
    )

    @model_validator(mode="before")
    @classmethod
    def unwrap_swagger_example_value(cls, data: Any) -> Any:
        if isinstance(data, dict) and "value" in data and isinstance(data["value"], dict):
            return data["value"]
        return data

    age_group: str = Field(..., description="Nhóm tuổi theo options của model V3")
    gender: str = Field(..., description="Giới tính theo options của model V3")
    top_k: int = Field(5, ge=1, le=20)
    weather: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Bỏ trống để lấy Open-Meteo. Manual mode cần đủ locked weather features "
            "hoặc weather.daily gồm ít nhất 7 ngày."
        ),
    )
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    timezone: str = Field(DEFAULT_TIMEZONE)
    target_date: date | None = None


class Tier1FactorResponse(BaseModel):
    feature: str
    label_vi: str
    category: Literal["DEMOGRAPHIC", "SEASONAL_CALENDAR", "WEATHER"]
    window: Literal["CURRENT", "3D", "7D", "NONE"]
    input_value: Any
    shap_value: float
    direction: Literal["UP", "DOWN"]
    weather_factor: str | None = None


class Tier1Response(BaseModel):
    available: bool
    summary_vi: str | None
    positive_factors: list[Tier1FactorResponse]
    negative_factors: list[Tier1FactorResponse]
    base_value_raw: float | None
    additivity_max_abs_error: float | None
    error: str | None


class MedicalSourceResponse(BaseModel):
    title: str
    organization: str
    url: str
    year: int | None


class Tier2Response(BaseModel):
    available: bool
    reason: str | None
    evidence_status: str | None
    relationship_type: str | None
    matched_weather_factor: str | None
    explanation_short_vi: str | None
    limitations_vi: str | None
    sources: list[MedicalSourceResponse]


class DiseaseRankingResponse(BaseModel):
    rank: int
    disease_id: str
    disease_name: str
    disease_group_id: str
    disease_group_name: str
    report_group_code: str
    ranking_score: float
    tier1: Tier1Response
    tier2: Tier2Response


class WeatherAIPredictResponse(BaseModel):
    message: str
    context: dict[str, Any]
    input: dict[str, Any]
    weather: dict[str, Any]
    predictions: list[DiseaseRankingResponse]
    top_risks: list[DiseaseRankingResponse]
    model: dict[str, Any]
    runtime_ms: dict[str, float]
    disclaimer: str
