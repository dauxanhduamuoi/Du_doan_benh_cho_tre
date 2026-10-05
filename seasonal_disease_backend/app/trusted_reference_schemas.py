from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.published_medical_knowledge_schemas import (
    PublishedMedicalKnowledgeBatchRequest,
    PublishedMedicalKnowledgeSelector,
)


# Reuse the canonical selector, legacy weather bridge and 1..100 batch bound.
TrustedReferenceBatchRequest = PublishedMedicalKnowledgeBatchRequest


class TrustedReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: int = Field(gt=0)
    provider_id: str | None = None
    external_id: str | None = None
    source_type: str = Field(min_length=1)
    source_kind: str | None = None
    title: str = Field(min_length=1)
    journal: str | None = None
    publication_year: int | None = Field(default=None, ge=1800, le=2100)
    original_url: HttpUrl


class TrustedReferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: PublishedMedicalKnowledgeSelector
    references: list[TrustedReference]


class TrustedReferenceBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TrustedReferenceItem]
