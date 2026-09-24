from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit
import hashlib
import json


class MedicalEvidenceProviderError(RuntimeError):
    """Safe base error for failures crossing a provider boundary."""


class MedicalEvidenceProviderConfigurationError(MedicalEvidenceProviderError):
    pass


class MedicalEvidenceProviderUnavailableError(MedicalEvidenceProviderError):
    pass


class MedicalEvidenceProviderTimeoutError(MedicalEvidenceProviderUnavailableError):
    pass


class MedicalEvidenceProviderRateLimitedError(MedicalEvidenceProviderUnavailableError):
    pass


class MedicalEvidenceProviderBadResponseError(MedicalEvidenceProviderUnavailableError):
    pass


class UnknownMedicalEvidenceProviderError(LookupError):
    pass


class MedicalEvidenceCapability(str, Enum):
    SEARCH = "SEARCH"
    DIRECT_LOOKUP = "DIRECT_LOOKUP"
    FULL_TEXT_ENRICHMENT = "FULL_TEXT_ENRICHMENT"


class MedicalEvidenceSourceKind(str, Enum):
    RESEARCH_ARTICLE = "RESEARCH_ARTICLE"
    SYSTEMATIC_REVIEW = "SYSTEMATIC_REVIEW"
    GUIDELINE = "GUIDELINE"
    TECHNICAL_REPORT = "TECHNICAL_REPORT"
    HEALTH_GUIDANCE = "HEALTH_GUIDANCE"
    OTHER = "OTHER"


@dataclass(frozen=True)
class MedicalEvidenceProviderDescriptor:
    provider_id: str
    display_name: str
    capabilities: frozenset[MedicalEvidenceCapability]
    description: str = "Nguồn bằng chứng y khoa đã đăng ký."
    settings_display_name: str | None = None
    max_search_results: int = 25
    exact_identifier_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedMedicalEvidence:
    """Provider-neutral source and immutable evidence snapshot contract.

    PMID, PMCID, journal and abstract are deliberately optional PubMed metadata.
    Generic providers need only a stable provider/external identity, title and URL.
    """

    provider_id: str
    source_kind: MedicalEvidenceSourceKind
    external_id: str
    title: str
    canonical_url: str | None = None
    authors: str | None = None
    publication_date: str | None = None
    publisher_or_journal: str | None = None
    language: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    publication_year: int | None = None
    abstract_text: str | None = None
    content_kind: str | None = None
    content_origin: str | None = None
    evidence_text: str | None = None
    retrieved_at: datetime | None = None
    is_truncated: bool = False
    license_name: str | None = None
    license_url: str | None = None
    provenance: Mapping[str, object] = field(default_factory=dict)
    provider_metadata: Mapping[str, object] = field(default_factory=dict)
    # Populated by the provider normalizer from article-owned fields only.
    article_mesh_terms: tuple[str, ...] = ()
    article_subject_terms: tuple[str, ...] = ()
    article_keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider_id = self.provider_id.strip().upper()
        external_id = self.external_id.strip()
        if not provider_id or not external_id or not self.title.strip():
            raise ValueError("Normalized evidence requires provider, external ID, and title")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "external_id", external_id)

    @property
    def journal(self) -> str | None:
        return self.publisher_or_journal

    @property
    def pubmed_url(self) -> str | None:
        return self.canonical_url

    @property
    def raw_metadata(self) -> dict[str, object]:
        return dict(self.provider_metadata)

    @property
    def external_identifier(self) -> str | None:
        return self.pmcid

    @property
    def content_sha256(self) -> str | None:
        if not self.content_kind or not self.content_origin or not self.evidence_text:
            return None
        canonical = json.dumps(
            {
                "kind": self.content_kind,
                "origin": self.content_origin,
                "external_identifier": self.pmcid,
                "text": self.evidence_text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MedicalEvidenceSearchResult:
    total_count: int
    sources: tuple[NormalizedMedicalEvidence, ...]
    fetched_count: int | None = None
    normalized_count: int | None = None
    page_number: int | None = None
    pages_count: int | None = None


@dataclass(frozen=True)
class ReviewedMedicalEvidenceRetrievalPolicy:
    batch_size: int
    max_pages: int
    max_raw_candidates: int


@dataclass(frozen=True)
class ReviewedMedicalEvidenceQuery:
    disease_terms: tuple[str, ...]
    factor_type: str
    factor_key: str
    factor_value: str | None
    weather_factor: str | None
    year_from: int | None
    year_to: int | None


@dataclass(frozen=True)
class ReviewedMedicalEvidenceQueryAttempt:
    level: str
    query: str
    relevance: str


@runtime_checkable
class MedicalEvidenceProvider(Protocol):
    descriptor: MedicalEvidenceProviderDescriptor

    def search(self, query: str, max_results: int) -> MedicalEvidenceSearchResult:
        ...

    def build_reviewed_query(self, context: ReviewedMedicalEvidenceQuery) -> str:
        ...

    def lookup(self, external_id: str) -> NormalizedMedicalEvidence | None:
        ...

    def fetch_many(self, external_ids: list[str]) -> tuple[NormalizedMedicalEvidence, ...]:
        ...

    def enrich(
        self, source: NormalizedMedicalEvidence, *, retrieved_at: datetime | None = None
    ) -> NormalizedMedicalEvidence:
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class ExactMedicalEvidenceProvider(Protocol):
    """Optional capability, independently implemented from Guided search."""
    descriptor: MedicalEvidenceProviderDescriptor

    def lookup_exact(self, identifier: str) -> NormalizedMedicalEvidence | None:
        ...


class MedicalEvidenceProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, MedicalEvidenceProvider] = {}

    def register(self, provider: MedicalEvidenceProvider) -> None:
        provider_id = provider.descriptor.provider_id.strip().upper()
        if not provider_id:
            raise ValueError("Provider ID must not be blank")
        if provider_id in self._providers:
            raise ValueError(f"Medical evidence provider is already registered: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> MedicalEvidenceProvider:
        normalized = provider_id.strip().upper()
        try:
            return self._providers[normalized]
        except KeyError as exc:
            raise UnknownMedicalEvidenceProviderError(
                f"Unknown medical evidence provider: {normalized or '<blank>'}"
            ) from exc

    def list_descriptors(self) -> tuple[MedicalEvidenceProviderDescriptor, ...]:
        return tuple(
            self._providers[key].descriptor for key in sorted(self._providers)
        )

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()


@dataclass(frozen=True)
class MedicalEvidenceTrustPolicy:
    trusted_classes_by_provider: Mapping[str, frozenset[str]]

    def is_provider_trusted(self, provider_id: str) -> bool:
        return provider_id.strip().upper() in self.trusted_classes_by_provider

    def is_trusted(self, *, provider_id: str, trust_class: str) -> bool:
        allowed = self.trusted_classes_by_provider.get(provider_id.strip().upper())
        return allowed is not None and trust_class.strip().upper() in allowed


DEFAULT_AUTO_EVIDENCE_TRUST_POLICY = MedicalEvidenceTrustPolicy(
    {
        "PUBMED": frozenset({"PUBMED", "PMC"}),
        # WHO content is trusted only when the adapter assigns the WHO class
        # after its exact official-origin and license checks succeed.
        "WHO": frozenset({"WHO"}),
    }
)

DEFAULT_REVIEWED_EVIDENCE_TRUST_POLICY = MedicalEvidenceTrustPolicy(
    {"PUBMED": frozenset({"PUBMED", "PMC"})}
)


def _canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, "")
    )


def normalized_evidence_identity_keys(source: NormalizedMedicalEvidence) -> frozenset[str]:
    keys = {f"PROVIDER:{source.provider_id}:{source.external_id.casefold()}"}
    if source.pmid:
        keys.add(f"PMID:{source.pmid.strip()}")
    if source.pmcid:
        keys.add(f"PMCID:{source.pmcid.strip().upper()}")
    if source.doi:
        keys.add(f"DOI:{source.doi.strip().casefold()}")
    if source.canonical_url:
        keys.add(f"URL:{_canonical_url(source.canonical_url)}")
    return frozenset(keys)


def deduplicate_normalized_evidence(
    sources: list[NormalizedMedicalEvidence] | tuple[NormalizedMedicalEvidence, ...],
) -> tuple[NormalizedMedicalEvidence, ...]:
    seen: set[str] = set()
    unique: list[NormalizedMedicalEvidence] = []
    for source in sources:
        keys = normalized_evidence_identity_keys(source)
        if seen.intersection(keys):
            # Retain all identifiers from a duplicate so later transitive
            # matches (for example PMID -> DOI -> canonical URL) also collapse.
            seen.update(keys)
            continue
        unique.append(source)
        seen.update(keys)
    return tuple(unique)
