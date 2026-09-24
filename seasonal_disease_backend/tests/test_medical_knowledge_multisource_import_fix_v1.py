from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401 - register users table for FK DDL
from app.database import Base
from app.medical_evidence_reviewed_schemas import (
    ReviewedProviderImportRequest,
    ReviewedProviderSourceReference,
)
from app.medical_knowledge_models import MedicalEvidenceSource, MedicalKnowledgeTopicSource
from app.services.medical_evidence_provider import (
    MedicalEvidenceCapability,
    MedicalEvidenceProviderDescriptor,
    MedicalEvidenceProviderRegistry,
    MedicalEvidenceProviderUnavailableError,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
)
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingsService,
)
from app.services.medical_evidence_reviewed_service import MedicalEvidenceReviewedService
from app.services.who_evidence_provider import WHO_LICENSE_URL


NOW = datetime(2026, 9, 12, 10, 0, 0)
WHO_UUID = "69e416c8-c71b-4e2b-839b-c6f44d59cc2f"


class FakeProvider:
    def __init__(self, provider_id: str, records=(), *, fail_ids=()):
        self.descriptor = MedicalEvidenceProviderDescriptor(
            provider_id=provider_id,
            display_name=provider_id,
            capabilities=frozenset(
                {MedicalEvidenceCapability.SEARCH, MedicalEvidenceCapability.DIRECT_LOOKUP}
            ),
        )
        self.records = {item.external_id: item for item in records}
        self.fail_ids = set(fail_ids)
        self.lookup_calls: list[str] = []

    def search(self, _query: str, max_results: int):
        sources = tuple(self.records.values())[:max_results]
        return MedicalEvidenceSearchResult(len(sources), sources)

    def lookup(self, external_id: str):
        self.lookup_calls.append(external_id)
        if external_id in self.fail_ids:
            raise MedicalEvidenceProviderUnavailableError("private provider failure")
        return self.records.get(external_id)

    def fetch_many(self, external_ids: list[str]):
        return tuple(self.records[item] for item in external_ids if item in self.records)

    def enrich(self, source, *, retrieved_at=None):
        return source

    def close(self):
        return None


def pubmed_record(
    pmid: str = "12345678", *, url: str | None = None, doi: str | None = None
) -> NormalizedMedicalEvidence:
    return NormalizedMedicalEvidence(
        provider_id="PUBMED",
        source_kind=MedicalEvidenceSourceKind.RESEARCH_ARTICLE,
        external_id=pmid,
        title=f"Pediatric influenza evidence {pmid}",
        canonical_url=url or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        publisher_or_journal="Fixture Journal",
        publication_year=2025,
        doi=doi or f"10.1000/{pmid}",
        pmid=pmid,
        abstract_text="Influenza evidence for children and humidity.",
        content_kind="ABSTRACT",
        content_origin="NCBI_PUBMED",
        evidence_text="Influenza evidence for children and humidity.",
        retrieved_at=NOW,
        provenance={"provider": "NCBI PubMed", "pmid": pmid},
    )


def who_trusted_record() -> NormalizedMedicalEvidence:
    return NormalizedMedicalEvidence(
        provider_id="WHO",
        source_kind=MedicalEvidenceSourceKind.GUIDELINE,
        external_id=WHO_UUID,
        title="WHO pediatric influenza guidance",
        canonical_url="https://www.who.int/publications/i/item/9789240099999",
        publisher_or_journal="World Health Organization",
        publication_year=2025,
        evidence_text="Licensed WHO guidance for influenza in children.",
        content_kind="OFFICIAL_SUMMARY_EXCERPT",
        content_origin="WHO_PUBLICATIONS_API",
        license_name="CC BY-NC-SA 3.0 IGO",
        license_url=WHO_LICENSE_URL,
        retrieved_at=NOW,
        provenance={"license_allowlisted": True, "full_text_stored": False},
    )


def pubmed_reference(pmid: str = "12345678") -> ReviewedProviderSourceReference:
    return ReviewedProviderSourceReference(
        provider_id="PUBMED",
        external_id=pmid,
        canonical_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        source_kind="RESEARCH_ARTICLE",
        title=f"Pediatric influenza evidence {pmid}",
        authors=None,
        publisher_or_journal="Fixture Journal",
        publication_date=None,
        publication_year=2025,
        doi=f"10.1000/{pmid}",
    )


def who_metadata_reference(
    external_id: str = "73164", *, url: str | None = None
) -> ReviewedProviderSourceReference:
    return ReviewedProviderSourceReference(
        provider_id="WHO",
        external_id=external_id,
        canonical_url=url or f"https://www.who.int/publications/b/{external_id}",
        source_kind="OTHER",
        title="WHO influenza metadata record",
        authors=None,
        publisher_or_journal="World Health Organization",
        publication_date="2025-01-02",
        publication_year=2025,
        doi=None,
    )


def who_trusted_reference() -> ReviewedProviderSourceReference:
    source = who_trusted_record()
    return ReviewedProviderSourceReference(
        provider_id="WHO",
        external_id=source.external_id,
        canonical_url=source.canonical_url,
        source_kind=source.source_kind.value,
        title=source.title,
        authors=None,
        publisher_or_journal=source.publisher_or_journal,
        publication_date=None,
        publication_year=source.publication_year,
        doi=None,
    )


def import_request(*references, factor_key="humidity"):
    return ReviewedProviderImportRequest(
        disease_group_id="168",
        factor_type="WEATHER",
        factor_key=factor_key,
        factor_value=None,
        weather_factor=factor_key,
        sources=list(references),
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def setup(db):
    pubmed = FakeProvider("PUBMED", [pubmed_record(), pubmed_record("87654321")])
    who = FakeProvider("WHO", [who_trusted_record()])
    registry = MedicalEvidenceProviderRegistry()
    registry.register(pubmed)
    registry.register(who)
    MedicalEvidenceProviderSettingsService(db, registry).update(
        provider_id="WHO", workflow="REVIEWED", enabled=True, actor_user_id=None
    )
    service = MedicalEvidenceReviewedService(db, registry)
    service._validate_disease = lambda _value: None
    return service, pubmed, who


# 1
def test_01_pubmed_single_source_add_works(setup):
    service, _pubmed, _who = setup
    result = service.import_sources(import_request(pubmed_reference()), added_by=None)
    assert (result.added_count, result.sources[0].outcome) == (1, "ADDED")


# 2
def test_02_who_metadata_only_single_source_add_works(setup):
    service, _pubmed, who = setup
    result = service.import_sources(import_request(who_metadata_reference()), added_by=None)
    assert result.sources[0].outcome == "ADDED_REFERENCE_ONLY"
    assert who.lookup_calls == []


# 3
def test_03_who_metadata_only_persists_with_null_pmid(db, setup):
    service, _pubmed, _who = setup
    imported = service.import_sources(import_request(who_metadata_reference()), added_by=None)
    source = db.get(MedicalEvidenceSource, imported.sources[0].source_id)
    assert source.provider_id == "WHO" and source.external_id == "73164" and source.pmid is None


# 4
def test_04_who_metadata_only_is_draft_ineligible(setup):
    service, _pubmed, _who = setup
    service.import_sources(import_request(who_metadata_reference()), added_by=None)
    library = service.topic_sources.read(
        disease_group_id="168", factor_type="WEATHER", factor_key="humidity",
        factor_value=None, weather_factor="humidity",
    )
    assert library.sources[0].content_kind is None and library.sources[0].usable_for_draft is False


# 5
def test_05_who_trusted_licensed_evidence_add_works(setup):
    service, _pubmed, _who = setup
    result = service.import_sources(import_request(who_trusted_reference()), added_by=None)
    assert result.sources[0].outcome == "ADDED"
    assert result.sources[0].content_kind == "OFFICIAL_SUMMARY_EXCERPT"


# 6
def test_06_who_trusted_usable_source_may_be_draft_eligible(setup):
    service, _pubmed, _who = setup
    result = service.import_sources(import_request(who_trusted_reference()), added_by=None)
    assert result.sources[0].usable_for_draft is True


# 7
def test_07_mixed_pubmed_who_batch_works(setup):
    service, _pubmed, _who = setup
    result = service.import_sources(
        import_request(pubmed_reference(), who_metadata_reference()), added_by=None
    )
    assert [item.outcome for item in result.sources] == ["ADDED", "ADDED_REFERENCE_ONLY"]
    assert result.added_count == 2


# 8
def test_08_metadata_only_who_does_not_block_pubmed(setup):
    service, _pubmed, _who = setup
    bad_who = who_metadata_reference(url="https://evil.example/publications/b/73164")
    result = service.import_sources(import_request(pubmed_reference(), bad_who), added_by=None)
    assert result.sources[0].outcome == "ADDED"
    assert result.sources[1].outcome == "REJECTED_INVALID"
    assert (result.added_count, result.failed_count) == (1, 1)


# 9
def test_09_mixed_batch_preserves_provider_attribution(db, setup):
    service, _pubmed, _who = setup
    service.import_sources(
        import_request(pubmed_reference(), who_metadata_reference()), added_by=None
    )
    assert set(db.scalars(select(MedicalEvidenceSource.provider_id))) == {"PUBMED", "WHO"}


# 10
def test_10_existing_pubmed_import_is_idempotent(db, setup):
    service, _pubmed, _who = setup
    first = service.import_sources(import_request(pubmed_reference()), added_by=None)
    second = service.import_sources(import_request(pubmed_reference()), added_by=None)
    assert second.sources[0].outcome == "ALREADY_EXISTS"
    assert second.sources[0].source_id == first.sources[0].source_id
    assert db.scalar(select(func.count()).select_from(MedicalEvidenceSource)) == 1


# 11
def test_11_existing_who_import_is_idempotent(db, setup):
    service, _pubmed, _who = setup
    first = service.import_sources(import_request(who_metadata_reference()), added_by=None)
    second = service.import_sources(import_request(who_metadata_reference()), added_by=None)
    assert second.sources[0].outcome == "ALREADY_EXISTS"
    assert second.sources[0].source_id == first.sources[0].source_id
    assert db.scalar(select(func.count()).select_from(MedicalEvidenceSource)) == 1


# 12
def test_12_provider_external_id_dedup_works(db, setup):
    service, _pubmed, _who = setup
    result = service.import_sources(
        import_request(who_metadata_reference(), who_metadata_reference()), added_by=None
    )
    assert [item.outcome for item in result.sources] == ["ADDED_REFERENCE_ONLY", "ALREADY_EXISTS"]
    assert db.scalar(select(func.count()).select_from(MedicalEvidenceSource)) == 1


# 13
def test_13_canonical_url_dedup_works(db):
    shared_url = "https://pubmed.ncbi.nlm.nih.gov/shared/"
    first = pubmed_record("11111111", url=shared_url, doi="10.1000/a")
    second = pubmed_record("22222222", url=shared_url, doi="10.1000/b")
    provider = FakeProvider("PUBMED", [first, second])
    registry = MedicalEvidenceProviderRegistry(); registry.register(provider)
    service = MedicalEvidenceReviewedService(db, registry); service._validate_disease = lambda _v: None
    refs = [
        pubmed_reference("11111111").model_copy(update={"canonical_url": shared_url, "doi": "10.1000/a"}),
        pubmed_reference("22222222").model_copy(update={"canonical_url": shared_url, "doi": "10.1000/b"}),
    ]
    result = service.import_sources(import_request(*refs), added_by=None)
    assert result.sources[1].outcome == "ALREADY_EXISTS"
    assert db.scalar(select(func.count()).select_from(MedicalEvidenceSource)) == 1


# 14
def test_14_malformed_who_identity_is_rejected_per_item(setup):
    service, _pubmed, _who = setup
    malformed = who_metadata_reference("not-a-stable-id", url="https://www.who.int/publications/b/73164")
    result = service.import_sources(import_request(malformed), added_by=None)
    assert result.sources[0].outcome == "REJECTED_INVALID" and result.topic_id is None


# 15
def test_15_non_who_url_is_rejected_without_fetch(setup):
    service, _pubmed, who = setup
    invalid = who_metadata_reference(url="https://127.0.0.1/publications/b/73164")
    result = service.import_sources(import_request(invalid), added_by=None)
    assert result.sources[0].outcome == "REJECTED_INVALID"
    assert who.lookup_calls == []


# 16
def test_16_forged_frontend_trust_and_license_fields_are_rejected():
    with pytest.raises(ValidationError):
        ReviewedProviderSourceReference(
            **who_metadata_reference().model_dump(),
            trust_class="WHO",
            license_allowlisted=True,
            evidence_text="forged",
        )


# 17
def test_17_who_provider_lookup_failure_is_typed_per_item(db):
    registry = MedicalEvidenceProviderRegistry()
    registry.register(FakeProvider("PUBMED", [pubmed_record()]))
    registry.register(FakeProvider("WHO", fail_ids=[WHO_UUID]))
    MedicalEvidenceProviderSettingsService(db, registry).update(
        provider_id="WHO", workflow="REVIEWED", enabled=True, actor_user_id=None
    )
    service = MedicalEvidenceReviewedService(db, registry); service._validate_disease = lambda _v: None
    result = service.import_sources(import_request(who_trusted_reference()), added_by=None)
    assert result.sources[0].outcome == "PROVIDER_ERROR"
    assert result.sources[0].message == "WHO tạm thời không khả dụng."


# 18
def test_18_existing_pubmed_identity_contract_is_unchanged(db, setup):
    service, _pubmed, _who = setup
    imported = service.import_sources(import_request(pubmed_reference()), added_by=None)
    source = db.get(MedicalEvidenceSource, imported.sources[0].source_id)
    assert source.source_type == "PUBMED" and source.pmid == "12345678"


# 19
def test_19_source_library_exact_topic_ownership_is_preserved(db, setup):
    service, _pubmed, _who = setup
    service.import_sources(import_request(pubmed_reference(), factor_key="humidity"), added_by=None)
    other = service.topic_sources.read(
        disease_group_id="168", factor_type="WEATHER", factor_key="temperature",
        factor_value=None, weather_factor="temperature",
    )
    assert other.sources == []


# 20
def test_20_no_source_leakage_across_canonical_topics(db, setup):
    service, _pubmed, _who = setup
    first = service.import_sources(
        import_request(pubmed_reference(), factor_key="humidity"), added_by=None
    )
    second = service.import_sources(
        import_request(pubmed_reference(), factor_key="temperature"), added_by=None
    )
    assert first.topic_id != second.topic_id
    assert db.scalar(select(func.count()).select_from(MedicalKnowledgeTopicSource)) == 2
    assert db.scalar(select(func.count()).select_from(MedicalEvidenceSource)) == 1
