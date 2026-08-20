from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from .medical_knowledge_models import WEATHER_FACTORS


class PubMedSearchRequest(BaseModel):
    disease_group_id: str = Field(min_length=1, max_length=100)
    weather_factor: str
    disease_terms: list[str] = Field(min_length=1, max_length=8)
    max_results: int = Field(default=10, ge=1, le=25)
    year_from: int | None = Field(default=None, ge=1800, le=2100)
    year_to: int | None = Field(default=None, ge=1800, le=2100)

    @field_validator("weather_factor")
    @classmethod
    def validate_weather_factor(cls, value: str) -> str:
        if value not in WEATHER_FACTORS:
            raise ValueError(f"weather_factor must be one of: {', '.join(WEATHER_FACTORS)}")
        return value

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
        if not normalized:
            raise ValueError("At least one disease term is required")
        return normalized

    @model_validator(mode="after")
    def validate_year_range(self):
        if self.year_from is not None and self.year_to is not None and self.year_from > self.year_to:
            raise ValueError("year_from must be less than or equal to year_to")
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


class PubMedSearchResponse(BaseModel):
    disease_group_id: str
    weather_factor: str
    query: str
    count: int
    results: list[PubMedRecord]


class PubMedImportRequest(BaseModel):
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


class PubMedImportResponse(BaseModel):
    count: int
    created_count: int
    reused_count: int
    sources: list[PubMedImportedSource]


class MedicalKnowledgeDiseaseGroupOption(BaseModel):
    id: str
    name: str


class MedicalKnowledgeWeatherFactorOption(BaseModel):
    value: str
    label_vi: str


class MedicalKnowledgeOptionsResponse(BaseModel):
    disease_groups: list[MedicalKnowledgeDiseaseGroupOption]
    weather_factors: list[MedicalKnowledgeWeatherFactorOption]
    llm_draft_generation_available: bool
