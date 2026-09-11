from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.database import Base
from app.medical_knowledge_models import MedicalEvidenceSource
from app.medical_knowledge_draft_schemas import DraftGenerationContext, DraftSourceInput
from app.medical_knowledge_schemas import MedicalEvidenceSourceCreate
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.services.medical_evidence_content_service import ResolvedEvidenceContent
from app.services.auto_evidence_qualification import qualify_auto_evidence
from app.services.auto_evidence_relevance import RelevanceSignals
from app.services.medical_evidence_provider import (
    DEFAULT_AUTO_EVIDENCE_TRUST_POLICY,
    MedicalEvidenceCapability,
    MedicalEvidenceProviderBadResponseError,
    MedicalEvidenceProviderConfigurationError,
    MedicalEvidenceProviderDescriptor,
    MedicalEvidenceProviderRateLimitedError,
    MedicalEvidenceProviderRegistry,
    MedicalEvidenceProviderTimeoutError,
    MedicalEvidenceProviderUnavailableError,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    MedicalEvidenceTrustPolicy,
    NormalizedMedicalEvidence,
    UnknownMedicalEvidenceProviderError,
    deduplicate_normalized_evidence,
)
from app.services.medical_evidence_provider_factory import (
    create_medical_evidence_provider_registry,
)
from app.services.pubmed_client import (
    PubMedArticleRecord,
    PubMedConfigurationError,
    PubMedParseError,
    PubMedRateLimitError,
    PubMedUnavailableError,
)
from app.services.pubmed_evidence_provider import PubMedMedicalEvidenceProvider
from migrations.v015_medical_evidence_providers import upgrade


NOW = datetime(2026, 9, 11, 8, 30)


def normalized(
    external_id: str = "FAKE-1", **overrides
) -> NormalizedMedicalEvidence:
    values = {
        "provider_id": "FAKE",
        "source_kind": MedicalEvidenceSourceKind.GUIDELINE,
        "external_id": external_id,
        "title": "Pediatric respiratory guidance",
        "canonical_url": f"https://example.test/guidance/{external_id}",
        "evidence_text": "Guidance for children.",
        "content_kind": "GUIDANCE_TEXT",
        "content_origin": "FAKE_DOCUMENT",
        "retrieved_at": NOW,
        "provenance": {"provider": "FAKE", "external_id": external_id},
    }
    values.update(overrides)
    return NormalizedMedicalEvidence(**values)


class FakeMedicalEvidenceProvider:
    descriptor = MedicalEvidenceProviderDescriptor(
        provider_id="FAKE",
        display_name="Offline fake provider",
        capabilities=frozenset(
            {MedicalEvidenceCapability.SEARCH, MedicalEvidenceCapability.DIRECT_LOOKUP}
        ),
    )

    def __init__(self):
        self.source = normalized()
        self.closed = False

    def search(self, query: str, max_results: int) -> MedicalEvidenceSearchResult:
        return MedicalEvidenceSearchResult(1, (self.source,))

    def lookup(self, external_id: str) -> NormalizedMedicalEvidence | None:
        return self.source if external_id == self.source.external_id else None

    def fetch_many(self, external_ids: list[str]):
        return tuple(self.source for value in external_ids if value == self.source.external_id)

    def enrich(self, source: NormalizedMedicalEvidence, *, retrieved_at=None):
        return source

    def close(self) -> None:
        self.closed = True


class FakePubMedClient:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.record = PubMedArticleRecord(
            pmid="12345678",
            title="Systematic review of influenza in children",
            authors="Nguyen A",
            journal="Pediatric Journal",
            publication_year=2025,
            doi="10.1000/pediatric-review",
            abstract_text="Influenza evidence in children.",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
            raw_metadata={
                "publication_types": ["Systematic Review"],
                "languages": ["eng"],
            },
        )
        self.calls: list[tuple[str, object]] = []

    def _raise(self):
        if self.error is not None:
            raise self.error

    def search(self, query: str, max_results: int):
        self.calls.append(("search", (query, max_results)))
        self._raise()
        return 1, [self.record]

    def get_article_by_pmid(self, pmid: str):
        self.calls.append(("lookup", pmid))
        self._raise()
        return self.record if pmid == self.record.pmid else None

    def fetch_records(self, pmids: list[str]):
        self.calls.append(("fetch", tuple(pmids)))
        self._raise()
        return [self.record] if self.record.pmid in pmids else []

    def close(self):
        self.calls.append(("close", None))


class FakeContentService:
    def __init__(self, content: ResolvedEvidenceContent | None):
        self.content = content
        self.calls = 0

    def resolve(self, *, pmid, abstract_text, retrieved_at=None):
        self.calls += 1
        return self.content


def pubmed_provider(*, content=None, error=None):
    client = FakePubMedClient(error)
    return PubMedMedicalEvidenceProvider(client, FakeContentService(content)), client


def test_production_registry_contains_only_real_pubmed_provider():
    registry = create_medical_evidence_provider_registry()
    try:
        assert [item.provider_id for item in registry.list_descriptors()] == ["PUBMED"]
        assert MedicalEvidenceCapability.FULL_TEXT_ENRICHMENT in registry.get(
            "pubmed"
        ).descriptor.capabilities
    finally:
        registry.close()


def test_registry_supports_fake_provider_and_unknown_id_fails_cleanly():
    registry = MedicalEvidenceProviderRegistry()
    fake = FakeMedicalEvidenceProvider()
    registry.register(fake)
    assert registry.get("fake").search("children", 1).sources[0].pmid is None
    with pytest.raises(UnknownMedicalEvidenceProviderError):
        registry.get("WHO")
    registry.close()
    assert fake.closed is True


def test_registered_provider_is_not_automatically_trusted():
    registry = MedicalEvidenceProviderRegistry()
    registry.register(FakeMedicalEvidenceProvider())
    assert registry.get("FAKE") is not None
    assert not DEFAULT_AUTO_EVIDENCE_TRUST_POLICY.is_trusted(
        provider_id="FAKE", trust_class="FAKE"
    )


def test_fake_provider_evidence_fails_qualification_until_policy_allows_it():
    context = DraftGenerationContext(
        disease_group_id="1",
        disease_group_name="Influenza",
        factor_type="WEATHER",
        factor_key="humidity",
        weather_factor="humidity",
        sources=[
            DraftSourceInput(
                source_id=1,
                source_type="OTHER",
                title="Pediatric respiratory guidance",
                evidence_content_id=2,
                content_kind="ABSTRACT",
                evidence_text="Children with influenza and humidity exposure.",
                content_origin="FAKE_DOCUMENT",
            )
        ],
    )
    selected = [
        (
            SimpleNamespace(id=1, provider_id="FAKE", source_type="OTHER"),
            SimpleNamespace(id=2, source_id=1),
            context.sources[0],
            "FAKE",
            RelevanceSignals(disease=1, factor=1, pediatric=1),
        )
    ]
    result = qualify_auto_evidence(topic_id=1, context=context, selected=selected)
    assert result.eligible is False
    assert result.reason_code == "TRUSTED_SOURCE_REQUIRED"
    explicitly_allowed = qualify_auto_evidence(
        topic_id=1,
        context=context,
        selected=selected,
        trust_policy=MedicalEvidenceTrustPolicy(
            {"FAKE": frozenset({"FAKE"})}
        ),
    )
    assert explicitly_allowed.eligible is True


def test_normalized_contract_does_not_require_pubmed_fields():
    source = normalized()
    assert source.provider_id == "FAKE"
    assert source.source_kind == MedicalEvidenceSourceKind.GUIDELINE
    assert source.pmid is source.pmcid is source.journal is source.abstract_text is None


@pytest.mark.parametrize(
    "duplicate",
    [
        normalized("OTHER", pmid="123"),
        normalized("OTHER", doi="10.1/same"),
        normalized("SAME"),
        normalized("OTHER", canonical_url="https://EXAMPLE.test/guidance/SAME/"),
    ],
)
def test_provider_agnostic_dedup_identifiers(duplicate):
    if duplicate.pmid:
        first = normalized("ONE", pmid="123")
    elif duplicate.doi:
        first = normalized("ONE", doi="10.1/SAME")
    elif duplicate.external_id == "SAME":
        first = normalized("SAME")
    else:
        first = normalized(
            "ONE", canonical_url="https://example.test/guidance/SAME"
        )
    assert deduplicate_normalized_evidence((first, duplicate)) == (first,)


def test_pubmed_search_and_lookup_normalize_without_extra_calls():
    provider, client = pubmed_provider()
    result = provider.search("influenza", 5)
    looked_up = provider.lookup("12345678")
    assert result.total_count == 1
    assert result.sources[0].provider_id == "PUBMED"
    assert result.sources[0].source_kind == MedicalEvidenceSourceKind.SYSTEMATIC_REVIEW
    assert result.sources[0].language == "eng"
    assert looked_up == result.sources[0]
    assert [call[0] for call in client.calls] == ["search", "lookup"]


def test_pubmed_pmc_enrichment_preserves_identity_provenance_and_license():
    content = ResolvedEvidenceContent(
        content_kind="PMC_FULL_TEXT",
        content_origin="NCBI_PMC",
        external_identifier="PMC9988",
        evidence_text="Licensed full text for children.",
        retrieved_at=NOW,
        is_truncated=False,
        license_name="CC BY",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        provenance={
            "provider": "NCBI PMC",
            "pmid": "12345678",
            "pmcid": "PMC9988",
            "license_allowlisted": True,
        },
    )
    provider, _client = pubmed_provider(content=content)
    enriched = provider.enrich(provider.lookup("12345678"), retrieved_at=NOW)
    assert enriched.provider_id == "PUBMED"
    assert enriched.pmcid == "PMC9988"
    assert enriched.content_origin == "NCBI_PMC"
    assert enriched.license_name == "CC BY"
    assert enriched.provenance["license_allowlisted"] is True
    assert enriched.content_sha256 == content.content_sha256


def test_pubmed_abstract_fallback_preserves_fallback_provenance():
    content = ResolvedEvidenceContent(
        content_kind="ABSTRACT",
        content_origin="NCBI_PUBMED",
        external_identifier=None,
        evidence_text="Influenza evidence in children.",
        retrieved_at=NOW,
        is_truncated=False,
        license_name=None,
        license_url=None,
        provenance={
            "provider": "NCBI PubMed",
            "pmid": "12345678",
            "fallback_reason": "license_not_allowlisted",
            "license_allowlisted": False,
        },
    )
    provider, _client = pubmed_provider(content=content)
    enriched = provider.enrich(provider.lookup("12345678"))
    assert enriched.content_kind == "ABSTRACT"
    assert enriched.content_origin == "NCBI_PUBMED"
    assert enriched.license_url is None
    assert enriched.provenance["fallback_reason"] == "license_not_allowlisted"


@pytest.mark.parametrize(
    ("legacy_error", "provider_error"),
    [
        (PubMedConfigurationError("missing config"), MedicalEvidenceProviderConfigurationError),
        (PubMedRateLimitError("limited"), MedicalEvidenceProviderRateLimitedError),
        (PubMedParseError("bad xml"), MedicalEvidenceProviderBadResponseError),
        (PubMedUnavailableError("offline"), MedicalEvidenceProviderUnavailableError),
    ],
)
def test_pubmed_provider_translates_typed_failures(legacy_error, provider_error):
    provider, _client = pubmed_provider(error=legacy_error)
    with pytest.raises(provider_error):
        provider.search("influenza", 1)


def test_pubmed_provider_translates_timeout_separately():
    legacy = PubMedUnavailableError("timed out")
    legacy.__cause__ = httpx.ReadTimeout("timeout")
    provider, _client = pubmed_provider(error=legacy)
    with pytest.raises(MedicalEvidenceProviderTimeoutError):
        provider.search("influenza", 1)


def test_fake_source_without_pmid_can_be_persisted_and_reloaded():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = normalized()
        stored = MedicalKnowledgeRepository(db).create_source(
            MedicalEvidenceSourceCreate(
                source_type="OTHER",
                provider_id=source.provider_id,
                external_id=source.external_id,
                source_kind=source.source_kind.value,
                title=source.title,
                url=source.canonical_url,
                retrieved_at=source.retrieved_at,
                raw_metadata_json=dict(source.provider_metadata),
            )
        )
        db.commit()
        db.expire_all()
        loaded = db.scalar(select(MedicalEvidenceSource))
        assert loaded.id == stored.id
        assert loaded.provider_id == "FAKE"
        assert loaded.external_id == "FAKE-1"
        assert loaded.source_kind == "GUIDELINE"
        assert loaded.pmid is None
    engine.dispose()


def test_v015_is_idempotent_and_backfills_only_deterministic_legacy_rows():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE medical_evidence_sources ("
            "id INTEGER PRIMARY KEY, source_type VARCHAR(16) NOT NULL, "
            "pmid VARCHAR(32) NULL, title TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO medical_evidence_sources(id,source_type,pmid,title) VALUES "
            "(1,'PUBMED','12345678','PubMed row'),(2,'OTHER',NULL,'Unknown row')"
        )
    upgrade(engine)
    upgrade(engine)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT id,provider_id,external_id,source_kind "
            "FROM medical_evidence_sources ORDER BY id"
        ).fetchall()
        assert rows == [
            (1, "PUBMED", "12345678", "RESEARCH_ARTICLE"),
            (2, None, None, None),
        ]
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    indexes = {item["name"] for item in inspect(engine).get_indexes("medical_evidence_sources")}
    assert {"ix_medical_sources_provider_external", "ix_medical_sources_kind"} <= indexes
    engine.dispose()
