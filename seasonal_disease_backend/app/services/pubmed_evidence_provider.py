from __future__ import annotations

from dataclasses import replace
from datetime import datetime
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
        provenance={"provider": "NCBI PubMed", "pmid": record.pmid, "pmcid": record.pmcid},
    )


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
        return MedicalEvidenceSearchResult(total_count=total, sources=normalized)

    def lookup(self, external_id: str) -> NormalizedMedicalEvidence | None:
        try:
            record = self.client.get_article_by_pmid(external_id)
        except Exception as exc:
            raise self._translate(exc) from exc
        return normalize_pubmed_record(record) if record is not None else None

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
