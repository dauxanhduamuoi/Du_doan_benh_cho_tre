from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MedicalEvidenceWorkflow = Literal["AUTO", "REVIEWED"]


class MedicalEvidenceProviderSettingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=40)
    workflow: MedicalEvidenceWorkflow
    enabled: bool

    @field_validator("provider_id")
    @classmethod
    def normalize_provider_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("provider_id must not be blank")
        return normalized


class MedicalEvidenceProviderSettingItem(BaseModel):
    provider_id: str
    display_name: str
    description: str
    workflow: MedicalEvidenceWorkflow
    enabled: bool
    capabilities: list[str]
    operational_status: Literal["REGISTERED"] = "REGISTERED"
    updated_at: datetime
    updated_by: int | None


class MedicalEvidenceProviderSettingsResponse(BaseModel):
    providers: list[MedicalEvidenceProviderSettingItem]
