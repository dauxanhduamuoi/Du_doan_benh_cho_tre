from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import re
import httpx

from app.services.medical_evidence_content_service import MedicalEvidenceContentService
from app.services.medical_evidence_provider import (
    MedicalEvidenceCapability,
    MedicalEvidenceProviderBadResponseError,
    MedicalEvidenceProviderConfigurationError,
    MedicalEvidenceProviderDescriptor,
    MedicalEvidenceProviderRateLimitedError,
    MedicalEvidenceProviderTimeoutError,
    MedicalEvidenceProviderUnavailableError,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQuery,
    ReviewedMedicalEvidenceQueryAttempt,
    deduplicate_normalized_evidence,
)
from app.services.pubmed_client import (
    PubMedArticleRecord,
    PubMedClient,
    PubMedConfigurationError,
    PubMedParseError,
    PubMedRateLimitError,
    PubMedUnavailableError,
)
from app.services.pubmed_query_builder import build_pubmed_query, build_pubmed_query_variant


PUBMED_DESCRIPTOR = MedicalEvidenceProviderDescriptor(
    provider_id="PUBMED",
    display_name="PubMed / PMC",
    capabilities=frozenset(
        {
            MedicalEvidenceCapability.SEARCH,
            MedicalEvidenceCapability.DIRECT_LOOKUP,
            MedicalEvidenceCapability.FULL_TEXT_ENRICHMENT,
        }
    ),
    description="Nghiên cứu PubMed và nội dung toàn văn được cấp phép từ PMC.",
    max_search_results=25,
    exact_identifier_types=("PMID",),
)


def _source_kind(record: PubMedArticleRecord) -> MedicalEvidenceSourceKind:
    raw = record.raw_metadata or {}
    values = raw.get("publication_types", [])
    normalized = {str(value).strip().casefold() for value in values} if isinstance(values, list) else set()
    if normalized.intersection({"systematic review", "meta-analysis"}):
        return MedicalEvidenceSourceKind.SYSTEMATIC_REVIEW
    return MedicalEvidenceSourceKind.RESEARCH_ARTICLE


def normalize_pubmed_record(record: PubMedArticleRecord) -> NormalizedMedicalEvidence:
    raw = dict(record.raw_metadata or {})
    languages = raw.get("languages", [])
    language = str(languages[0]) if isinstance(languages, list) and languages else None
    return NormalizedMedicalEvidence(
        provider_id="PUBMED",
        source_kind=_source_kind(record),
        external_id=record.pmid,
        title=record.title,
        canonical_url=record.pubmed_url,
        authors=record.authors,
        publisher_or_journal=record.journal,
        language=language,
        doi=record.doi,
        pmid=record.pmid,
        pmcid=record.pmcid,
        publication_year=record.publication_year,
        abstract_text=record.abstract_text,
        provider_metadata=raw,
        article_mesh_terms=_article_terms(raw.get("mesh_terms")),
        article_keywords=_article_terms(raw.get("author_keywords")),
        provenance={"provider": "NCBI PubMed", "pmid": record.pmid, "pmcid": record.pmcid},
    )


def _article_terms(value: object) -> tuple[str, ...]:
    # Only flat provider-owned strings; never recursively flatten metadata.
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item[:1000] for item in value[:128] if isinstance(item, str) and item.strip())


class PubMedMedicalEvidenceProvider:
    descriptor = PUBMED_DESCRIPTOR

    def __init__(self, client: PubMedClient, content_service: MedicalEvidenceContentService):
        self.client = client
        self.content_service = content_service

    @staticmethod
    def _translate(exc: Exception) -> Exception:
        if isinstance(exc, PubMedConfigurationError):
            return MedicalEvidenceProviderConfigurationError(str(exc))
        if isinstance(exc, PubMedRateLimitError):
            return MedicalEvidenceProviderRateLimitedError("PubMed rate limit exceeded")
        if isinstance(exc, PubMedParseError):
            return MedicalEvidenceProviderBadResponseError("PubMed returned a malformed response")
        if isinstance(exc, PubMedUnavailableError):
            if isinstance(exc.__cause__, httpx.TimeoutException):
                return MedicalEvidenceProviderTimeoutError("PubMed request timed out")
            return MedicalEvidenceProviderUnavailableError(str(exc))
        return exc

    def search(self, query: str, max_results: int) -> MedicalEvidenceSearchResult:
        try:
            total, records = self.client.search(query, max_results)
        except Exception as exc:
            raise self._translate(exc) from exc
        normalized = deduplicate_normalized_evidence(
            tuple(normalize_pubmed_record(record) for record in records)
        )
        return MedicalEvidenceSearchResult(
            total_count=total,
            sources=normalized,
            fetched_count=len(records),
            normalized_count=len(normalized),
        )

    def build_reviewed_query(self, context: ReviewedMedicalEvidenceQuery) -> str:
        return build_pubmed_query(
            list(context.disease_terms),
            factor_type=context.factor_type,
            factor_key=context.factor_key,
            factor_value=context.factor_value,
            weather_factor=context.weather_factor,
            year_from=context.year_from,
            year_to=context.year_to,
        )

    def build_reviewed_query_plan(
        self, context: ReviewedMedicalEvidenceQuery
    ) -> tuple[ReviewedMedicalEvidenceQueryAttempt, ...]:
        common = {
            "factor_type": context.factor_type,
            "factor_key": context.factor_key,
            "factor_value": context.factor_value,
            "weather_factor": context.weather_factor,
            "year_from": context.year_from,
            "year_to": context.year_to,
        }
        disease_terms = list(context.disease_terms)
        return (
            ReviewedMedicalEvidenceQueryAttempt(
                level="DIRECT_DISEASE_FACTOR_PEDIATRIC",
                query=build_pubmed_query_variant(
                    disease_terms, include_factor=True, include_pediatric=True, **common
                ),
                relevance="DIRECT_TOPIC",
            ),
            ReviewedMedicalEvidenceQueryAttempt(
                level="DIRECT_DISEASE_FACTOR",
                query=build_pubmed_query_variant(
                    disease_terms, include_factor=True, include_pediatric=False, **common
                ),
                relevance="DIRECT_TOPIC",
            ),
            ReviewedMedicalEvidenceQueryAttempt(
                level="RELATED_DISEASE_PEDIATRIC",
                query=build_pubmed_query_variant(
                    disease_terms, include_factor=False, include_pediatric=True, **common
                ),
                relevance="RELATED_CONTEXT",
            ),
        )

    def lookup(self, external_id: str) -> NormalizedMedicalEvidence | None:
        try:
            record = self.client.get_article_by_pmid(external_id)
        except Exception as exc:
            raise self._translate(exc) from exc
        return normalize_pubmed_record(record) if record is not None else None

    def lookup_exact(self, identifier: str) -> NormalizedMedicalEvidence | None:
        value = identifier.strip()
        if not re.fullmatch(r"[0-9]{1,16}", value):
            raise ValueError("INVALID_IDENTIFIER: expected PMID digits")
        source = self.lookup(value)
        if source is not None and (
            source.provider_id != "PUBMED" or source.pmid != value or source.external_id != value
        ):
            raise MedicalEvidenceProviderBadResponseError("PubMed exact lookup identity mismatch")
        return source

    def fetch_many(self, external_ids: list[str]) -> tuple[NormalizedMedicalEvidence, ...]:
        try:
            records = self.client.fetch_records(external_ids)
        except Exception as exc:
            raise self._translate(exc) from exc
        return deduplicate_normalized_evidence(
            tuple(normalize_pubmed_record(record) for record in records)
        )

    def enrich(
        self, source: NormalizedMedicalEvidence, *, retrieved_at: datetime | None = None
    ) -> NormalizedMedicalEvidence:
        if source.provider_id != "PUBMED" or not source.pmid:
            raise ValueError("PubMed provider can only enrich a normalized PubMed source")
        try:
            resolve_kwargs = {
                "pmid": source.pmid,
                "abstract_text": source.abstract_text,
            }
            if retrieved_at is not None:
                resolve_kwargs["retrieved_at"] = retrieved_at
            content = self.content_service.resolve(**resolve_kwargs)
        except Exception as exc:
            raise self._translate(exc) from exc
        if content is None:
            return source
        pmcid = (
            content.external_identifier
            if (content.external_identifier or "").startswith("PMC")
            else source.pmcid
        )
        return replace(
            source,
            pmcid=pmcid,
            content_kind=content.content_kind,
            content_origin=content.content_origin,
            evidence_text=content.evidence_text,
            retrieved_at=content.retrieved_at,
            is_truncated=content.is_truncated,
            license_name=content.license_name,
            license_url=content.license_url,
            provenance=dict(content.provenance),
        )

    def close(self) -> None:
        self.client.close()
