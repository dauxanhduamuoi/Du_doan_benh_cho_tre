from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401 - register user FK targets
from app.database import Base
from app.medical_evidence_reviewed_schemas import (
    ReviewedProviderExactLookupRequest,
    ReviewedProviderSearchRequest,
)
from app.services.medical_evidence_provider import MedicalEvidenceProviderRegistry
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingsService,
)
from app.services.medical_evidence_reviewed_service import MedicalEvidenceReviewedService
from app.services.pubmed_client import PubMedArticleRecord, parse_pubmed_records
from app.services.pubmed_evidence_provider import PubMedMedicalEvidenceProvider
from app.services.reviewed_evidence_relevance import ReviewedEvidenceRelevance


FIXTURES = Path(__file__).with_name("fixtures")


def archived_record(pmid: str) -> PubMedArticleRecord:
    records = parse_pubmed_records(
        FIXTURES.joinpath(f"pubmed_{pmid}_efetch.xml").read_bytes()
    )
    return next(record for record in records if record.pmid == pmid)


class RuntimeShapedPubMedClient:
    """Return parsed EFetch records through the production provider normalizer."""

    def __init__(self):
        self.records = [
            archived_record("32517609"),
            archived_record("30017148"),
            PubMedArticleRecord(
                pmid="99900001",
                title="The temperature-dependent conformational ensemble of SARS-CoV-2 main protease.",
                authors=None,
                journal="Fixture Journal",
                publication_year=2024,
                doi=None,
                abstract_text=(
                    "COVID-19 continues to plague the globe. Mpro structures were examined "
                    "at high humidity."
                ),
                pubmed_url="https://pubmed.ncbi.nlm.nih.gov/99900001/",
                raw_metadata={"publication_types": ["Journal Article"], "languages": ["eng"]},
            ),
            archived_record("38257588"),
        ]
        self.search_calls: list[tuple[str, int]] = []

    def search(self, query: str, max_results: int):
        self.search_calls.append((query, max_results))
        return len(self.records), self.records[:max_results]

    def get_article_by_pmid(self, pmid: str):
        return next((record for record in self.records if record.pmid == pmid), None)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def request() -> ReviewedProviderSearchRequest:
    return ReviewedProviderSearchRequest(
        disease_group_id="9",
        disease_terms=["Plague"],
        provider_ids=["PUBMED"],
        factor_type="WEATHER",
        factor_key="humidity",
        factor_value=None,
        weather_factor="humidity",
        max_results=4,
    )


def runtime_service(db: Session):
    client = RuntimeShapedPubMedClient()
    provider = PubMedMedicalEvidenceProvider(client, content_service=None)
    registry = MedicalEvidenceProviderRegistry()
    registry.register(provider)
    MedicalEvidenceProviderSettingsService(db, registry).reconcile()
    service = MedicalEvidenceReviewedService(db, registry)
    service._validate_disease = lambda _value: None
    return service, provider, client


def test_real_pubmed_shapes_keep_runtime_and_semantic_classification_in_parity(db):
    service, provider, client = runtime_service(db)
    response = service.search(request())
    group = response.providers[0]
    results = {item.external_id: item for item in group.results}

    climate = provider.lookup("32517609")
    assert climate is not None
    assert climate.abstract_text
    assert climate.article_mesh_terms
    assert climate.article_keywords
    assessment = ReviewedEvidenceRelevance(
        service._query_context(request())
    ).classify(climate)

    assert assessment.disease_match
    assert assessment.factor_match
    assert assessment.factor_match_field == "abstract"
    assert assessment.relation_status.value == "RELATED_TO_TOPIC"
    assert assessment.relation_reason == "EPIDEMIOLOGY_CONTEXT"
    assert assessment.classification.value == "DIRECT_TOPIC"
    assert results["32517609"].relevance == "DIRECT_TOPIC"
    assert results["32517609"].abstract_text
    assert results["32517609"].usability == "METADATA_ONLY"

    assert results["30017148"].relevance == "RELATED_CONTEXT"
    assert "99900001" not in results
    assert "38257588" not in results
    assert group.direct_count == 1
    assert group.related_count == 1
    assert group.rejected_count >= 2
    assert len(client.search_calls) == 3


def test_exact_lookup_identity_remains_independent_of_guided_relevance(db):
    service, _provider, _client = runtime_service(db)

    def exact(identifier: str):
        return ReviewedProviderExactLookupRequest(
            disease_group_id="9",
            provider_id="PUBMED",
            identifier=identifier,
            factor_type="WEATHER",
            factor_key="humidity",
            factor_value=None,
            weather_factor="humidity",
        )

    vaccine = service.lookup_exact(exact("30017148"))
    agriculture = service.lookup_exact(exact("38257588"))

    assert vaccine.result.external_id == "30017148"
    assert vaccine.result.relevance == "EXACT_LOOKUP"
    assert agriculture.result.external_id == "38257588"
    assert agriculture.result.relevance == "EXACT_LOOKUP"
