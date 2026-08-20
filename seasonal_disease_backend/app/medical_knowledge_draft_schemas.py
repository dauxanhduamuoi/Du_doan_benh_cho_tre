from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .medical_knowledge_models import EVIDENCE_LEVELS, EVIDENCE_SCOPES, WEATHER_FACTORS


EvidenceLevel = Literal["SUPPORTED", "LIMITED_OR_INDIRECT", "CONFLICTING", "INSUFFICIENT"]
EvidenceScope = Literal["WHOLE_GROUP", "PARTIAL_GROUP"]
SourceRelevance = Literal["DIRECT", "INDIRECT", "NOT_SUPPORTIVE"]


class DraftGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disease_group_id: str = Field(min_length=1, max_length=100)
    weather_factor: str
    source_ids: list[int] = Field(min_length=1, max_length=8)

    @field_validator("weather_factor")
    @classmethod
    def validate_weather_factor(cls, value: str) -> str:
        if value not in WEATHER_FACTORS:
            raise ValueError(f"weather_factor must be one of: {', '.join(WEATHER_FACTORS)}")
        return value

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("source_ids must contain positive database identifiers")
        if len(set(values)) != len(values):
            raise ValueError("source_ids must not contain duplicates")
        return values


class DraftSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: int
    source_type: str
    pmid: str | None = None
    doi: str | None = None
    title: str
    authors: str | None = None
    journal: str | None = None
    publication_year: int | None = None
    publication_types: list[str] = Field(default_factory=list)
    abstract_text: str | None = None


class DraftGenerationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disease_group_id: str
    disease_group_name: str
    report_group_code: str | None = None
    weather_factor: str
    sources: list[DraftSourceInput]


class SourceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: int
    relevance: SourceRelevance
    note_vi: str = Field(min_length=1, max_length=1000)

    @field_validator("note_vi")
    @classmethod
    def validate_note(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("note_vi must not be blank")
        return value


class MedicalKnowledgeDraftProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_level: EvidenceLevel
    evidence_scope: EvidenceScope
    short_explanation_vi: str = Field(min_length=1, max_length=2000)
    detailed_explanation_vi: str = Field(min_length=1, max_length=10000)
    limitations_vi: str = Field(min_length=1, max_length=5000)
    source_assessments: list[SourceAssessment] = Field(max_length=8)

    @field_validator("short_explanation_vi", "detailed_explanation_vi", "limitations_vi")
    @classmethod
    def validate_explanation_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Draft explanation fields must not be blank")
        return value

    @field_validator("source_assessments")
    @classmethod
    def unique_assessment_sources(cls, values: list[SourceAssessment]) -> list[SourceAssessment]:
        ids = [value.source_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("source_assessments must not contain duplicate source IDs")
        return values


class DraftRevisionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_level: EvidenceLevel | None = None
    evidence_scope: EvidenceScope | None = None
    short_explanation_vi: str | None = Field(default=None, min_length=1, max_length=2000)
    detailed_explanation_vi: str | None = Field(default=None, min_length=1, max_length=10000)
    limitations_vi: str | None = Field(default=None, min_length=1, max_length=5000)

    @field_validator("short_explanation_vi", "detailed_explanation_vi", "limitations_vi")
    @classmethod
    def validate_patch_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Draft explanation fields must not be blank")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one editable draft field is required")
        return self


class DraftSourceResponse(BaseModel):
    id: int
    source_type: str
    pmid: str | None
    doi: str | None
    title: str
    authors: str | None
    journal: str | None
    publication_year: int | None
    abstract_text: str | None
    url: str | None
    source_role: str
    sort_order: int
    relevance_note: str | None


class DraftRevisionSummary(BaseModel):
    id: int
    revision_number: int
    status: str
    evidence_level: str
    evidence_scope: str
    generated_by_llm: bool
    created_at: datetime
    updated_at: datetime


class DraftTopicResponse(BaseModel):
    id: int
    disease_group_id: str
    disease_group_name: str
    weather_factor: str
    published_revision_id: int | None


class DraftRevisionResponse(DraftRevisionSummary):
    topic_id: int
    disease_group_id: str
    disease_group_name: str
    weather_factor: str
    short_explanation_vi: str
    detailed_explanation_vi: str
    limitations_vi: str
    parent_display_allowed: bool
    llm_model: str | None
    prompt_version: str | None
    created_by: int | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    sources: list[DraftSourceResponse]


class DraftTopicHistoryResponse(BaseModel):
    topic: DraftTopicResponse | None
    revisions: list[DraftRevisionSummary]
