from __future__ import annotations

from datetime import datetime
import re

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .medical_knowledge_factor_schemas import GenericFactorSelector


class PubMedSearchRequest(GenericFactorSelector):
    disease_group_id: str = Field(min_length=1, max_length=100)
    search_mode: Literal["GUIDED", "FREE"] = "GUIDED"
    disease_terms: list[str] = Field(default_factory=list, max_length=8)
    free_query: str | None = Field(default=None, max_length=1000)
    max_results: int = Field(default=10, ge=1, le=25)
    year_from: int | None = Field(default=None, ge=1800, le=2100)
    year_to: int | None = Field(default=None, ge=1800, le=2100)

    @field_validator("disease_terms")
    @classmethod
    def validate_disease_terms(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            term = value.strip()
            if not 2 <= len(term) <= 120:
                raise ValueError("Each disease term must contain 2 to 120 characters")
            if any(character in term for character in ('"', "[", "]", "\r", "\n")):
                raise ValueError("Disease terms contain unsupported PubMed query syntax")
            key = term.casefold()
            if key not in seen:
                seen.add(key)
                normalized.append(term)
        return normalized

    @model_validator(mode="after")
    def validate_year_range(self):
        if self.year_from is not None and self.year_to is not None and self.year_from > self.year_to:
            raise ValueError("year_from must be less than or equal to year_to")
        if self.search_mode == "GUIDED" and not self.disease_terms:
            raise ValueError("At least one disease term is required for guided search")
        if self.search_mode == "FREE":
            query = (self.free_query or "").strip()
            if not query:
                raise ValueError("Vui lòng nhập truy vấn PubMed tự do.")
            if any(ord(character) < 32 for character in query):
                raise ValueError("Free PubMed query contains control characters")
            self.free_query = query
        elif self.free_query is not None:
            raise ValueError("free_query is only accepted in FREE search mode")
        return self


class PubMedRecord(BaseModel):
    pmid: str
    title: str
    authors: str | None = None
    journal: str | None = None
    publication_year: int | None = None
    doi: str | None = None
    abstract_text: str | None = None
    pubmed_url: str
    pmcid: str | None = None
    source_id: int | None = None
    stored_globally: bool = False
    in_topic_library: bool = False
    content_kind: str | None = None


class PubMedLookupRequest(GenericFactorSelector):
    pmid: str
    disease_group_id: str = Field(min_length=1, max_length=100)

    @field_validator("pmid", mode="before")
    @classmethod
    def validate_pmid(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("PMID must be provided as text containing digits only")
        pmid = value.strip()
        if not re.fullmatch(r"[0-9]{1,16}", pmid):
            raise ValueError("PMID must contain 1 to 16 ASCII digits")
        return pmid

class PubMedSearchResponse(GenericFactorSelector):
    disease_group_id: str
    search_mode: Literal["GUIDED", "FREE"] = "GUIDED"
    query: str
    count: int
    results: list[PubMedRecord]


class PubMedImportRequest(GenericFactorSelector):
    disease_group_id: str = Field(min_length=1, max_length=100)
    pmids: list[str] = Field(min_length=1, max_length=25)

    @field_validator("pmids")
    @classmethod
    def validate_pmids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            pmid = value.strip()
            if not pmid.isdigit() or not 1 <= len(pmid) <= 16:
                raise ValueError("Each PMID must contain 1 to 16 digits")
            if pmid not in seen:
                seen.add(pmid)
                normalized.append(pmid)
        return normalized


class PubMedImportedSource(BaseModel):
    id: int
    pmid: str
    created: bool
    title: str
    retrieved_at: datetime | None = None
    content_kind: str | None = None
    pmcid: str | None = None
    source_reused: bool = False
    topic_link_created: bool = False
    already_in_topic_library: bool = False


class PubMedLookupResponse(BaseModel):
    pmid: str
    result: PubMedRecord
    existing_source: PubMedImportedSource | None = None


class PubMedImportResponse(BaseModel):
    topic_id: int
    count: int
    created_count: int
    reused_count: int
    sources: list[PubMedImportedSource]


class MedicalKnowledgeTopicSourceItem(BaseModel):
    source_id: int
    provider_id: str = "PUBMED"
    external_id: str | None = None
    source_kind: str = "RESEARCH_ARTICLE"
    pmid: str | None
    title: str
    journal: str | None
    publication_year: int | None
    doi: str | None
    pmcid: str | None
    content_kind: str | None
    url: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    usable_for_draft: bool = False
    added_at: datetime


class MedicalKnowledgeTopicSourceLibraryResponse(GenericFactorSelector):
    topic_id: int | None
    disease_group_id: str
    sources: list[MedicalKnowledgeTopicSourceItem]


class MedicalKnowledgeDiseaseGroupOption(BaseModel):
    id: str
    name: str


class MedicalKnowledgeWeatherFactorOption(BaseModel):
    value: str
    label_vi: str


class MedicalKnowledgeFactorOption(BaseModel):
    type: str
    key: str
    label_vi: str
    values: list[str]


class MedicalKnowledgeOptionsResponse(BaseModel):
    disease_groups: list[MedicalKnowledgeDiseaseGroupOption]
    weather_factors: list[MedicalKnowledgeWeatherFactorOption]
    explanation_factors: list[MedicalKnowledgeFactorOption]
    llm_draft_generation_available: bool
