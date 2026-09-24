from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401 - register user FK targets
from app.database import Base
from app.medical_evidence_reviewed_schemas import ReviewedProviderSearchRequest
from app.services.medical_evidence_provider import (
    MedicalEvidenceCapability,
    MedicalEvidenceProviderDescriptor,
    MedicalEvidenceProviderRegistry,
    MedicalEvidenceProviderUnavailableError,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQueryAttempt,
)
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingsService,
)
from app.services.medical_evidence_reviewed_service import MedicalEvidenceReviewedService


NOW = datetime(2026, 9, 14, 11, 0, 0)


def record(provider_id: str, external_id: str, title: str):
    return NormalizedMedicalEvidence(
        provider_id=provider_id,
        source_kind=MedicalEvidenceSourceKind.RESEARCH_ARTICLE,
        external_id=external_id,
        title=title,
        canonical_url=f"https://example.test/{provider_id.lower()}/{external_id}",
        retrieved_at=NOW,
    )


class FixtureProvider:
    def __init__(self, provider_id: str, plan, responses, *, fail: bool = False):
        self.descriptor = MedicalEvidenceProviderDescriptor(
            provider_id=provider_id,
            display_name=provider_id,
            capabilities=frozenset({MedicalEvidenceCapability.SEARCH}),
            max_search_results=25,
        )
        self.plan = tuple(plan)
        self.responses = responses
        self.fail = fail
        self.calls: list[tuple[str, int]] = []

    def build_reviewed_query_plan(self, _context):
        return self.plan

    def build_reviewed_query(self, _context):
        return self.plan[0].query

    def search(self, query: str, limit: int):
        self.calls.append((query, limit))
        if self.fail:
            raise MedicalEvidenceProviderUnavailableError("offline")
        available = tuple(self.responses.get(query, ()))
        sources = available[:limit]
        return MedicalEvidenceSearchResult(
            total_count=len(available),
            sources=sources,
            fetched_count=len(sources),
            normalized_count=len(sources),
        )


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def request(*provider_ids: str, count: int = 10):
    return ReviewedProviderSearchRequest(
        disease_group_id="9",
        disease_terms=["Plague"],
        provider_ids=list(provider_ids),
        factor_type="WEATHER",
        factor_key="humidity",
        weather_factor="humidity",
        max_results=count,
    )


def service_with(db: Session, *providers):
    registry = MedicalEvidenceProviderRegistry()
    for provider in providers:
        registry.register(provider)
    settings = MedicalEvidenceProviderSettingsService(db, registry)
    for provider in providers:
        if provider.descriptor.provider_id != "PUBMED":
            settings.update(
                provider_id=provider.descriptor.provider_id,
                workflow="REVIEWED",
                enabled=True,
                actor_user_id=1,
            )
    service = MedicalEvidenceReviewedService(db, registry)
    service._validate_disease = lambda _value: None
    return service


def test_01_pubmed_candidates_use_shared_direct_related_reject_contract(db):
    plan = (
        ReviewedMedicalEvidenceQueryAttempt("DIRECT_DISEASE_FACTOR_PEDIATRIC", "q1", "DIRECT_TOPIC"),
        ReviewedMedicalEvidenceQueryAttempt("DIRECT_DISEASE_FACTOR", "q2", "DIRECT_TOPIC"),
        ReviewedMedicalEvidenceQueryAttempt("RELATED_DISEASE_PEDIATRIC", "q3", "RELATED_CONTEXT"),
    )
    provider = FixtureProvider("PUBMED", plan, {
        "q1": (
            record("PUBMED", "related", "Plague vaccination"),
            record("PUBMED", "direct-1", "Human plague and relative humidity"),
            record("PUBMED", "direct-2", "Human plague climate moisture association"),
            record("PUBMED", "wrong-virus", "SARS-CoV-2 temperature in children"),
            record("PUBMED", "agriculture", "Smart agriculture humidity sensors"),
        ),
        "q3": (record("PUBMED", "pediatric", "Pediatric plague surveillance"),),
    })
    group = service_with(db, provider).search(request("PUBMED")).providers[0]
    assert (group.direct_count, group.related_count, group.rejected_count) == (2, 2, 2)
    assert [item.external_id for item in group.results] == [
        "direct-1", "direct-2", "related", "pediatric"
    ]


def test_02_who_candidates_use_the_same_contract(db):
    plan = (ReviewedMedicalEvidenceQueryAttempt("DIRECT_DISEASE_FACTOR", "q", "DIRECT_TOPIC"),)
    provider = FixtureProvider("WHO", plan, {"q": (
        record("WHO", "d", "Human plague humidity technical guidance"),
        record("WHO", "r", "Plague vaccination guidance"),
        record("WHO", "factor", "Children and humidity"),
        record("WHO", "violence", "Preventing violence against children"),
        record("WHO", "dumpsites", "Children and digital dumpsites"),
    )})
    group = service_with(db, provider).search(request("WHO")).providers[0]
    assert (group.direct_count, group.related_count, group.rejected_count) == (1, 1, 3)
    assert [item.external_id for item in group.results] == ["d", "r"]


def test_03_fake_future_provider_needs_no_relevance_branch(db):
    plan = (ReviewedMedicalEvidenceQueryAttempt("CDC_DISCOVERY", "q", "DIRECT_TOPIC"),)
    provider = FixtureProvider("FAKE_CDC", plan, {"q": (
        record("FAKE_CDC", "direct", "Human plague humidity evidence"),
        record("FAKE_CDC", "related", "Plague vaccination"),
        record("FAKE_CDC", "reject", "Humidity monitoring for crops"),
    )})
    group = service_with(db, provider).search(request("FAKE_CDC")).providers[0]
    assert (group.direct_count, group.related_count, group.rejected_count) == (1, 1, 1)


def test_04_pubmed_and_who_keep_independent_visible_limits(db):
    plan = (ReviewedMedicalEvidenceQueryAttempt("DIRECT", "q", "DIRECT_TOPIC"),)
    pubmed = FixtureProvider("PUBMED", plan, {"q": tuple(
        record("PUBMED", str(index), f"Human plague humidity PubMed {index}") for index in range(4)
    )})
    who = FixtureProvider("WHO", plan, {"q": tuple(
        record("WHO", str(index), f"Human plague humidity WHO {index}") for index in range(4)
    )})
    result = service_with(db, pubmed, who).search(request("PUBMED", "WHO", count=3))
    assert [group.returned_count for group in result.providers] == [3, 3]


def test_05_provider_error_remains_distinct_and_other_results_survive(db):
    plan = (ReviewedMedicalEvidenceQueryAttempt("DIRECT", "q", "DIRECT_TOPIC"),)
    pubmed = FixtureProvider("PUBMED", plan, {"q": (
        record("PUBMED", "kept", "Human plague humidity evidence"),
    )})
    who = FixtureProvider("WHO", plan, {}, fail=True)
    result = service_with(db, pubmed, who).search(request("PUBMED", "WHO"))
    groups = {group.provider_id: group for group in result.providers}
    assert groups["PUBMED"].status == "SUCCESS"
    assert groups["WHO"].status == "PROVIDER_ERROR"
    assert groups["WHO"].status != "NO_RESULTS"
