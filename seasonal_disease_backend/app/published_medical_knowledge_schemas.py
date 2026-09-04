from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES
from app.medical_knowledge_factor_schemas import GenericFactorSelector


ParentWeatherFactor = Literal[
    "temperature",
    "humidity",
    "precipitation",
    "wind",
    "weather_condition",
]
ParentEvidenceLevel = Literal["SUPPORTED", "LIMITED_OR_INDIRECT"]
ParentEvidenceScope = Literal["WHOLE_GROUP", "PARTIAL_GROUP"]


class PublishedMedicalKnowledgeSelector(GenericFactorSelector):
    model_config = ConfigDict(extra="forbid")

    disease_group_id: str = Field(pattern=r"^[0-9]{1,6}$")


class PublishedMedicalKnowledgeBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublishedMedicalKnowledgeSelector] = Field(min_length=1, max_length=100)


class ParentMedicalKnowledgeCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=2000)
    journal: str | None = Field(default=None, max_length=255)
    publication_year: int | None = Field(default=None, ge=1800, le=2100)
    pmid: str | None = Field(default=None, pattern=r"^[0-9]{1,16}$")
    doi: str | None = Field(default=None, max_length=255)
    pmcid: str | None = Field(default=None, pattern=r"^PMC[0-9]+$")
    url: str | None = None


class PublishedMedicalKnowledgeItem(GenericFactorSelector):
    model_config = ConfigDict(extra="forbid")

    disease_group_id: str = Field(pattern=r"^[0-9]{1,6}$")
    knowledge_type: Literal["REVIEWED", "AUTO"]
    generation_mode: Literal["AI_FULL", "SAFE_FALLBACK"] | None = None
    warning: str | None = Field(default=None, max_length=500)
    revision_id: int = Field(gt=0)
    evidence_level: ParentEvidenceLevel
    evidence_scope: ParentEvidenceScope
    short_explanation_vi: str = Field(min_length=1, max_length=2000)
    detailed_explanation_vi: str = Field(min_length=1, max_length=10000)
    limitations_vi: str = Field(min_length=1, max_length=5000)
    sources: list[ParentMedicalKnowledgeCitation] = Field(
        min_length=1,
        max_length=MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES,
    )


class PublishedMedicalKnowledgeBatchResponse(BaseModel):
    items: list[PublishedMedicalKnowledgeItem]
