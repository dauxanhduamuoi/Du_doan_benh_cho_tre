from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.medical_knowledge_factor_schemas import GenericFactorSelector


class ReviewedProviderSearchRequest(GenericFactorSelector):
    model_config = ConfigDict(extra="forbid")

    disease_group_id: str = Field(min_length=1, max_length=100)
    disease_terms: list[str] = Field(min_length=1, max_length=8)
    provider_ids: list[str] = Field(default_factory=lambda: ["PUBMED"], min_length=1, max_length=8)
    max_results: int = Field(default=10, ge=1, le=25)
    year_from: int | None = Field(default=None, ge=1800, le=2100)
    year_to: int | None = Field(default=None, ge=1800, le=2100)

    @field_validator("provider_ids")
    @classmethod
    def normalize_providers(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = value.strip().upper()
            if normalized and normalized not in result:
                result.append(normalized)
        if not result:
            raise ValueError("At least one provider is required")
        return result

    @field_validator("disease_terms")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = " ".join(value.split())
            if not normalized:
                continue
            if not 2 <= len(normalized) <= 120 or any(
                character in normalized for character in ('"', "[", "]", "\r", "\n")
            ):
                raise ValueError("Disease terms are invalid")
            key = normalized.casefold()
            if key not in seen:
                seen.add(key)
                result.append(normalized)
        if not result:
            raise ValueError("Disease terms are invalid")
        return result


class ReviewedProviderSource(BaseModel):
    provider_id: str
    external_id: str
    source_kind: str
    title: str
    authors: str | None
    publisher_or_journal: str | None
    publication_date: str | None
    publication_year: int | None
    doi: str | None
    url: str | None
    abstract_text: str | None
    license_name: str | None
    license_url: str | None
    usability: str
    usable_for_draft: bool
    source_id: int | None = None
    in_topic_library: bool = False
    relevance: Literal["DIRECT_TOPIC", "RELATED_CONTEXT", "BROAD_CONTEXT", "EXACT_LOOKUP"]
    query_level: str


class ReviewedProviderExactLookupRequest(GenericFactorSelector):
    model_config = ConfigDict(extra="forbid")
    disease_group_id: str = Field(min_length=1, max_length=100)
    provider_id: str = Field(min_length=1, max_length=40)
    identifier: str = Field(min_length=1, max_length=255)

    @field_validator("provider_id")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().upper()


class ReviewedProviderExactLookupResponse(BaseModel):
    lookup_mode: Literal["EXACT"] = "EXACT"
    requested_identifier: str
    result: ReviewedProviderSource


class ReviewedProviderWarning(BaseModel):
    provider_id: str
    code: str
    message: str


class ReviewedProviderQueryAttempt(BaseModel):
    level: str
    relevance: Literal["DIRECT_TOPIC", "RELATED_CONTEXT", "BROAD_CONTEXT"]
    query: str
    provider_match_count: int
    fetched_count: int
    normalized_count: int
    disease_match_count: int
    factor_match_count: int
    relevant_count: int
    direct_count: int
    related_count: int
    rejected_count: int
    pages_fetched: int
    budget_exhausted: bool
    provider_exhausted: bool
    stop_reason: Literal[
        "TARGET_REACHED",
        "PROVIDER_EXHAUSTED",
        "CANDIDATE_BUDGET_REACHED",
        "QUERY_ATTEMPT_COMPLETE",
        "PROVIDER_ERROR",
    ]
    status: Literal["SUCCESS", "PROVIDER_ERROR"]
    warning: ReviewedProviderWarning | None = None


class ReviewedProviderSearchGroup(BaseModel):
    provider_id: str
    display_name: str
    requested_count: int
    requested_relevant_count: int
    effective_limit: int
    returned_count: int
    total_available: int | None = None
    provider_total_available: int | None = None
    provider_invoked: bool
    provider_status: Literal["SUCCESS", "PROVIDER_ERROR"]
    raw_result_count: int
    raw_candidates_examined: int
    normalized_count: int
    normalized_candidates: int
    disease_match_count: int
    factor_match_count: int
    relevant_count: int
    rejected_count: int
    pages_fetched: int
    budget_exhausted: bool
    provider_exhausted: bool
    stop_reason: Literal[
        "TARGET_REACHED",
        "PROVIDER_EXHAUSTED",
        "CANDIDATE_BUDGET_REACHED",
        "QUERY_PLAN_EXHAUSTED",
        "PROVIDER_ERROR",
    ]
    direct_count: int
    related_count: int
    contextual_count: int
    status: Literal["SUCCESS", "NO_RESULTS", "PROVIDER_ERROR"]
    query: str
    warning: ReviewedProviderWarning | None = None
    query_attempts: list[ReviewedProviderQueryAttempt]
    results: list[ReviewedProviderSource]


class ReviewedProviderSearchResponse(BaseModel):
    requested_count: int
    provider_count: int
    max_candidates: int
    count: int
    unique_count: int
    providers: list[ReviewedProviderSearchGroup]
    # Additive compatibility fields for clients migrating from the V1 flat
    # response. New UI must render `providers`, which retains source context.
    results: list[ReviewedProviderSource]
    queries: dict[str, str]
    warnings: list[ReviewedProviderWarning]


class ReviewedProviderSourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1, max_length=40)
    external_id: str = Field(min_length=1, max_length=255)
    canonical_url: str | None = Field(default=None, max_length=2048)
    source_kind: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=1000)
    authors: str | None = Field(default=None, max_length=2000)
    publisher_or_journal: str | None = Field(default=None, max_length=255)
    publication_date: str | None = Field(default=None, max_length=64)
    publication_year: int | None = Field(default=None, ge=1800, le=2100)
    doi: str | None = Field(default=None, max_length=255)

    @field_validator("provider_id")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("external_id", "canonical_url", "title", "authors", "publisher_or_journal", "publication_date", "doi")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized or any(ord(char) < 32 for char in normalized):
            raise ValueError("Import reference contains invalid text")
        return normalized

    @field_validator("source_kind")
    @classmethod
    def normalize_source_kind(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None


class ReviewedProviderImportRequest(GenericFactorSelector):
    model_config = ConfigDict(extra="forbid")
    disease_group_id: str = Field(min_length=1, max_length=100)
    sources: list[ReviewedProviderSourceReference] = Field(min_length=1, max_length=25)


class ReviewedProviderImportedSource(BaseModel):
    outcome: Literal[
        "ADDED",
        "ADDED_REFERENCE_ONLY",
        "ALREADY_EXISTS",
        "REJECTED_INVALID",
        "PROVIDER_ERROR",
    ]
    source_id: int | None
    provider_id: str
    external_id: str
    title: str | None
    created: bool
    topic_link_created: bool
    content_kind: str | None
    license_name: str | None
    license_url: str | None
    usable_for_draft: bool
    imported_at: datetime | None
    message: str | None = None


class ReviewedProviderImportResponse(BaseModel):
    topic_id: int | None
    count: int
    requested_count: int
    added_count: int
    reference_only_count: int
    already_exists_count: int
    failed_count: int
    sources: list[ReviewedProviderImportedSource]
