from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES
from .medical_knowledge_factor_schemas import GenericFactorSelector
from .medical_knowledge_models import (
    EVIDENCE_LEVELS,
    EVIDENCE_SCOPES,
    POPULATION_RELEVANCES,
)


EvidenceLevel = Literal["SUPPORTED", "LIMITED_OR_INDIRECT", "CONFLICTING", "INSUFFICIENT"]
EvidenceScope = Literal["WHOLE_GROUP", "PARTIAL_GROUP"]
SourceRelevance = Literal["DIRECT", "INDIRECT", "NOT_SUPPORTIVE"]
PopulationRelevance = Literal[
    "PEDIATRIC_DIRECT", "MIXED_AGE", "ADULT_ONLY", "ELDERLY_ONLY", "UNKNOWN"
]
EvidenceContentKind = Literal["ABSTRACT", "PMC_FULL_TEXT", "PMC_FULL_TEXT_EXCERPT"]


class DraftGenerationRequest(GenericFactorSelector):
    model_config = ConfigDict(extra="forbid")

    disease_group_id: str = Field(min_length=1, max_length=100)
    # The service owns the configurable business limit so an over-limit API
    # request receives DRAFT_TOO_MANY_SOURCES instead of a generic schema 422.
    source_ids: list[int]

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
    evidence_content_id: int | None = None
    content_kind: EvidenceContentKind
    evidence_text: str = Field(min_length=1)
    content_origin: str
    pmcid: str | None = None
    license_name: str | None = None
    license_url: str | None = None


class DraftGenerationContext(GenericFactorSelector):
    model_config = ConfigDict(extra="forbid")

    disease_group_id: str
    disease_group_name: str
    report_group_code: str | None = None
    sources: list[DraftSourceInput]


class SourceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: int
    relevance: SourceRelevance
    note_vi: str = Field(min_length=1, max_length=1000)
    population_relevance: PopulationRelevance
    population_note: str = Field(min_length=1, max_length=1000)

    @field_validator("note_vi", "population_note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("note_vi must not be blank")
        return value

    @field_validator("population_relevance")
    @classmethod
    def validate_population_relevance(cls, value: str) -> str:
        if value not in POPULATION_RELEVANCES:
            raise ValueError("population_relevance is invalid")
        return value


class MedicalKnowledgeDraftProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_level: EvidenceLevel
    evidence_scope: EvidenceScope
    short_explanation_vi: str = Field(min_length=1, max_length=2000)
    detailed_explanation_vi: str = Field(min_length=1, max_length=10000)
    limitations_vi: str = Field(min_length=1, max_length=5000)
    source_assessments: list[SourceAssessment] = Field(
        min_length=1,
        max_length=MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES,
    )

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

    @model_validator(mode="after")
    def whole_group_requires_direct_source(self):
        if self.evidence_scope == "WHOLE_GROUP" and not any(
            assessment.relevance == "DIRECT" for assessment in self.source_assessments
        ):
            raise ValueError("WHOLE_GROUP requires at least one DIRECT source assessment")
        return self


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
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Editable draft fields cannot be null")
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
    content_kind: EvidenceContentKind | None
    pmcid: str | None
    content_origin: str
    source_role: str
    sort_order: int
    relevance_note: str | None
    population_relevance: PopulationRelevance
    population_note: str | None


class DraftRevisionSummary(BaseModel):
    id: int
    revision_number: int
    status: str
    evidence_level: str
    evidence_scope: str
    generated_by_llm: bool
    created_at: datetime
    updated_at: datetime
    is_published: bool = False


class DraftTopicResponse(GenericFactorSelector):
    id: int
    disease_group_id: str
    disease_group_name: str
    published_revision_id: int | None


class DraftRevisionResponse(DraftRevisionSummary, GenericFactorSelector):
    topic_id: int
    disease_group_id: str
    disease_group_name: str
    short_explanation_vi: str
    detailed_explanation_vi: str
    limitations_vi: str
    parent_display_allowed: bool
    llm_model: str | None
    prompt_version: str | None
    created_by: int | None
    reviewed_by: int | None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None
    published_by: int | None = None
    published_by_name: str | None = None
    published_at: datetime | None = None
    sources: list[DraftSourceResponse]
    parent_tier2_eligible: bool = False
    parent_tier2_ineligibility_reasons: list[str] = Field(default_factory=list)


class RevisionApprovalResponse(BaseModel):
    revision_id: int
    status: Literal["APPROVED"]
    approved_by: int
    approved_by_name: str
    approved_at: datetime
    parent_display_allowed: Literal[False]
    published_revision_id: int | None


class RevisionPublicationResponse(BaseModel):
    revision_id: int
    topic_id: int
    status: Literal["APPROVED"]
    is_published: Literal[True]
    parent_display_allowed: Literal[True]
    published_by: int
    published_by_name: str
    published_at: datetime
    previous_published_revision_id: int | None


class RevisionUnpublicationResponse(BaseModel):
    revision_id: int
    topic_id: int
    status: Literal["APPROVED"]
    is_published: Literal[False]
    parent_display_allowed: Literal[False]
    unpublished_by: int
    unpublished_by_name: str
    unpublished_at: datetime


class DraftTopicHistoryResponse(BaseModel):
    topic: DraftTopicResponse | None
    revisions: list[DraftRevisionSummary]
