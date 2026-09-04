from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.medical_knowledge_factors import normalize_factor


class GenericFactorSelector(BaseModel):
    """Flat generic selector with a legacy weather-only input bridge."""

    model_config = ConfigDict(extra="forbid")

    factor_type: str | None = Field(default=None, max_length=16)
    factor_key: str | None = Field(default=None, max_length=32)
    factor_value: str | None = Field(default=None, max_length=100)
    weather_factor: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def canonicalize_factor(self):
        factor = normalize_factor(
            factor_type=self.factor_type,
            factor_key=self.factor_key,
            factor_value=self.factor_value,
            weather_factor=self.weather_factor,
        )
        self.factor_type = factor.factor_type
        self.factor_key = factor.factor_key
        self.factor_value = factor.factor_value
        self.weather_factor = factor.weather_factor
        return self

    @property
    def factor_identity(self) -> tuple[str, str, str | None]:
        return (str(self.factor_type), str(self.factor_key), self.factor_value)

    def factor_dump(self) -> dict[str, str | None]:
        return {
            "factor_type": self.factor_type,
            "factor_key": self.factor_key,
            "factor_value": self.factor_value,
            "weather_factor": self.weather_factor,
        }
