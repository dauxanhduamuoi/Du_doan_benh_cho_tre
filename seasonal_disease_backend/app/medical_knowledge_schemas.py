from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .medical_knowledge_factor_schemas import GenericFactorSelector
from .medical_knowledge_models import (
    EVIDENCE_CONTENT_KINDS,
    EVIDENCE_CONTENT_ORIGINS,
    EVIDENCE_LEVELS,
    EVIDENCE_SCOPES,
    REVISION_STATUSES,
    SOURCE_ROLES,
    SOURCE_TYPES,
)


def _validate_choice(value: str, allowed: tuple[str, ...], field_name: str) -> str:
    if value not in allowed:
        raise ValueError(f"{field_name} must be one of: {', '.join(allowed)}")
    return value


class MedicalTopicCreate(GenericFactorSelector):
    disease_group_id: str = Field(min_length=1, max_length=100)
    created_by: int | None = None


class MedicalRevisionCreate(BaseModel):
    topic_id: int
    revision_number: int = Field(gt=0)
    evidence_level: str
    evidence_scope: str
    short_explanation_vi: str = Field(min_length=1)
    detailed_explanation_vi: str = Field(min_length=1)
    limitations_vi: str = Field(min_length=1)
    status: str = "DRAFT"
    parent_display_allowed: bool = False
    generated_by_llm: bool = False
    llm_model: str | None = Field(default=None, max_length=100)
    prompt_version: str | None = Field(default=None, max_length=100)
    created_by: int | None = None
    reviewed_by: int | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None

    @field_validator("evidence_level")
    @classmethod
    def validate_evidence_level(cls, value: str) -> str:
        return _validate_choice(value, EVIDENCE_LEVELS, "evidence_level")

    @field_validator("evidence_scope")
    @classmethod
    def validate_evidence_scope(cls, value: str) -> str:
        return _validate_choice(value, EVIDENCE_SCOPES, "evidence_scope")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        return _validate_choice(value, REVISION_STATUSES, "status")


class MedicalEvidenceSourceCreate(BaseModel):
    source_type: str
    pmid: str | None = Field(default=None, max_length=32)
    doi: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1)
    authors: str | None = None
    journal: str | None = Field(default=None, max_length=255)
    publication_year: int | None = None
    abstract_text: str | None = None
    url: str | None = None
    retrieved_at: datetime | None = None
    raw_metadata_json: dict[str, Any] | list[Any] | None = None

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, value: str) -> str:
        return _validate_choice(value, SOURCE_TYPES, "source_type")


class MedicalEvidenceContentCreate(BaseModel):
    source_id: int
    content_kind: str
    content_origin: str
    external_identifier: str | None = Field(default=None, max_length=64)
    evidence_text: str = Field(min_length=1)
    retrieved_at: datetime
    is_truncated: bool = False
    license_name: str | None = Field(default=None, max_length=255)
    license_url: str | None = None
    provenance_json: dict[str, Any] | list[Any] | None = None
    content_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")

    @field_validator("content_kind")
    @classmethod
    def validate_content_kind(cls, value: str) -> str:
        return _validate_choice(value, EVIDENCE_CONTENT_KINDS, "content_kind")

    @field_validator("content_origin")
    @classmethod
    def validate_content_origin(cls, value: str) -> str:
        return _validate_choice(value, EVIDENCE_CONTENT_ORIGINS, "content_origin")


class MedicalRevisionSourceCreate(BaseModel):
    revision_id: int
    source_id: int
    evidence_content_id: int | None = None
    source_role: str
    sort_order: int = Field(default=0, ge=0)
    relevance_note: str | None = None
    population_relevance: str = "UNKNOWN"
    population_note: str = Field(
        default="Legacy revision has no stored population assessment.",
        min_length=1,
        max_length=1000,
    )

    @field_validator("source_role")
    @classmethod
    def validate_source_role(cls, value: str) -> str:
        return _validate_choice(value, SOURCE_ROLES, "source_role")

    @field_validator("population_relevance")
    @classmethod
    def validate_population_relevance(cls, value: str) -> str:
        from app.medical_knowledge_models import POPULATION_RELEVANCES

        return _validate_choice(value, POPULATION_RELEVANCES, "population_relevance")
