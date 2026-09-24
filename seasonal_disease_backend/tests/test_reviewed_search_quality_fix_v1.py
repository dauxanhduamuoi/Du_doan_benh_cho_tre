from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401 - register user FK targets
from app.database import Base
from app.medical_evidence_reviewed_schemas import ReviewedProviderSearchRequest
from app.pubmed_schemas import PubMedSearchRequest
from app.services.medical_evidence_provider import (
    MedicalEvidenceCapability,
    MedicalEvidenceProviderDescriptor,
    MedicalEvidenceProviderRegistry,
    MedicalEvidenceProviderUnavailableError,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQuery,
    ReviewedMedicalEvidenceQueryAttempt,
)
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingsService,
)
from app.services.medical_evidence_reviewed_service import (
    MAX_REVIEWED_QUERY_ATTEMPTS,
    MedicalEvidenceReviewedService,
)
from app.services.medical_knowledge_pubmed_service import MedicalKnowledgePubMedService
from app.services.pubmed_client import PubMedArticleRecord
from app.services.pubmed_evidence_provider import PubMedMedicalEvidenceProvider
from app.services.pubmed_query_builder import build_pubmed_query
from app.services.who_evidence_provider import WhoMedicalEvidenceProvider


NOW = datetime(2026, 9, 13, 12, 0, 0)


def context() -> ReviewedMedicalEvidenceQuery:
    return ReviewedMedicalEvidenceQuery(
        disease_terms=("Plague",), factor_type="WEATHER", factor_key="humidity",
        factor_value=None, weather_factor="humidity", year_from=None, year_to=None,
    )


def request(*provider_ids: str, count: int = 10) -> ReviewedProviderSearchRequest:
    return ReviewedProviderSearchRequest(
        disease_group_id="9", disease_terms=["Plague"], provider_ids=list(provider_ids),
        factor_type="WEATHER", factor_key="humidity", factor_value=None,
        weather_factor="humidity", max_results=count,
    )


def source(provider_id: str, external_id: str, title: str, summary: str = ""):
    return NormalizedMedicalEvidence(
        provider_id=provider_id,
        source_kind=MedicalEvidenceSourceKind.RESEARCH_ARTICLE,
        external_id=external_id,
        title=title,
        canonical_url=f"https://example.test/{provider_id.lower()}/{external_id}",
        abstract_text=summary,
        retrieved_at=NOW,
    )


class ScriptedProvider:
    def __init__(self, provider_id: str, plan, responses, *, fail: bool = False):
        self.descriptor = MedicalEvidenceProviderDescriptor(
            provider_id=provider_id,
            display_name="PubMed / PMC" if provider_id == "PUBMED" else "World Health Organization",
            capabilities=frozenset({MedicalEvidenceCapability.SEARCH}),
            max_search_results=25,
        )
        self.plan = tuple(plan)
        self.responses = responses
        self.fail = fail
        self.calls: list[tuple[str, int]] = []

    def build_reviewed_query(self, _context):
        return self.plan[0].query

    def build_reviewed_query_plan(self, _context):
        return self.plan

    def search(self, query: str, limit: int):
        self.calls.append((query, limit))
        if self.fail:
            raise MedicalEvidenceProviderUnavailableError("offline")
        records = tuple(self.responses.get(query, ()))[:limit]
        return MedicalEvidenceSearchResult(
            total_count=len(self.responses.get(query, ())),
            sources=records,
            fetched_count=len(records),
            normalized_count=len(records),
        )

    def lookup(self, _external_id):
        return None

    def fetch_many(self, _external_ids):
        return ()

    def enrich(self, record, *, retrieved_at=None):
        return record

    def close(self):
        return None


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def service_with(db, *providers):
    registry = MedicalEvidenceProviderRegistry()
    for provider in providers:
        registry.register(provider)
    settings = MedicalEvidenceProviderSettingsService(db, registry)
    for provider in providers:
        if provider.descriptor.provider_id != "PUBMED":
            settings.update(
                provider_id=provider.descriptor.provider_id,
                workflow="REVIEWED", enabled=True, actor_user_id=1,
            )
    service = MedicalEvidenceReviewedService(db, registry)
    service._validate_disease = lambda _value: None
    return service


def pubmed_plan():
    return PubMedMedicalEvidenceProvider.__new__(PubMedMedicalEvidenceProvider).build_reviewed_query_plan(context())


def who_plan():
    return WhoMedicalEvidenceProvider.__new__(WhoMedicalEvidenceProvider).build_reviewed_query_plan(context())


def test_01_plague_humidity_pubmed_query_generation_is_exact_and_progressive():
    plan = pubmed_plan()
    assert len(plan) == 3
    assert '"Plague"[Title/Abstract]' in plan[0].query
    assert '"humidity"[Title/Abstract]' in plan[0].query
    assert '"Child"[MeSH Terms]' in plan[0].query
    assert '"humidity"[Title/Abstract]' in plan[1].query and "MeSH Terms" not in plan[1].query
    assert '"humidity"[Title/Abstract]' not in plan[2].query and '"Child"[MeSH Terms]' in plan[2].query


def test_02_plague_humidity_who_query_retains_the_one_word_disease_anchor():
    attempt = who_plan()[0]
    assert attempt.query == "Plague humidity relative humidity absolute humidity moisture children pediatric"
    assert attempt.level == "DIRECT_DISEASE_FACTOR"


def test_03_pubmed_direct_zero_is_recorded_as_successful_zero_not_error(db):
    plan = pubmed_plan()
    provider = ScriptedProvider("PUBMED", plan, {plan[2].query: [source("PUBMED", "3", "Pediatric plague review")]})
    group = service_with(db, provider).search(request("PUBMED")).providers[0]
    assert group.query_attempts[0].status == "SUCCESS"
    assert group.query_attempts[0].provider_match_count == 0
    assert group.status == "SUCCESS" and group.contextual_count == 1


def test_04_pubmed_fallback_runs_only_when_direct_is_insufficient(db):
    plan = pubmed_plan()
    direct = [source("PUBMED", str(i), f"Human plague humidity pediatric {i}") for i in range(10)]
    provider = ScriptedProvider("PUBMED", plan, {plan[0].query: direct})
    service_with(db, provider).search(request("PUBMED"))
    assert [query for query, _ in provider.calls] == [plan[0].query]


def test_05_pubmed_fallback_stops_as_soon_as_n_is_filled(db):
    plan = pubmed_plan()
    provider = ScriptedProvider("PUBMED", plan, {
        plan[0].query: [source("PUBMED", "1", "Human plague humidity pediatric")],
        plan[1].query: [source("PUBMED", str(i), f"Human plague humidity {i}") for i in range(2, 12)],
        plan[2].query: [source("PUBMED", "99", "Pediatric plague context")],
    })
    group = service_with(db, provider).search(request("PUBMED", count=3)).providers[0]
    assert group.returned_count == 3
    assert [query for query, _ in provider.calls] == [plan[0].query, plan[1].query]


def test_06_query_attempt_count_is_hard_bounded(db):
    plan = tuple(
        ReviewedMedicalEvidenceQueryAttempt(f"LEVEL_{i}", f"q{i}", "DIRECT_TOPIC")
        for i in range(10)
    )
    provider = ScriptedProvider("PUBMED", plan, {})
    group = service_with(db, provider).search(request("PUBMED")).providers[0]
    assert MAX_REVIEWED_QUERY_ATTEMPTS == 3
    assert len(provider.calls) == len(group.query_attempts) == 3


def test_07_duplicate_articles_are_not_repeated_across_fallback_attempts(db):
    plan = pubmed_plan()
    duplicate = source("PUBMED", "1", "Human plague humidity pediatric")
    provider = ScriptedProvider("PUBMED", plan, {
        plan[0].query: [duplicate],
        plan[1].query: [duplicate, source("PUBMED", "2", "Human plague humidity adults")],
    })
    group = service_with(db, provider).search(request("PUBMED", count=2)).providers[0]
    assert [item.external_id for item in group.results] == ["1", "2"]


def test_08_direct_results_rank_before_contextual_results(db):
    plan = pubmed_plan()
    provider = ScriptedProvider("PUBMED", plan, {
        plan[0].query: [source("PUBMED", "direct", "Human plague humidity pediatric")],
        plan[2].query: [source("PUBMED", "context", "Pediatric plague context")],
    })
    group = service_with(db, provider).search(request("PUBMED", count=2)).providers[0]
    assert [(item.external_id, item.relevance) for item in group.results] == [
        ("direct", "DIRECT_TOPIC"), ("context", "RELATED_CONTEXT")
    ]


def test_09_who_irrelevant_pediatric_only_results_are_rejected(db):
    plan = who_plan()
    bad = [
        source("WHO", "1", "Children and digital dumpsites"),
        source("WHO", "2", "Preventing violence against children"),
        source("WHO", "3", "School health guidance for children"),
    ]
    group = service_with(db, ScriptedProvider("WHO", plan, {plan[0].query: bad})).search(request("WHO")).providers[0]
    assert group.status == "NO_RESULTS" and group.returned_count == 0
    assert group.raw_result_count == 3 and group.relevant_count == 0


def test_10_who_local_filter_requires_the_disease_anchor(db):
    plan = who_plan()
    record = source("WHO", "1", "Humidity and climate guidance for children")
    group = service_with(db, ScriptedProvider("WHO", plan, {plan[0].query: [record]})).search(request("WHO")).providers[0]
    assert group.returned_count == 0


def test_11_who_disease_and_factor_result_is_retained(db):
    plan = who_plan()
    record = source("WHO", "1", "Human plague and humidity technical guidance")
    group = service_with(db, ScriptedProvider("WHO", plan, {plan[0].query: [record]})).search(request("WHO")).providers[0]
    assert group.returned_count == group.relevant_count == 1


def test_12_who_raw_ten_relevant_two_reports_post_filter_count(db):
    plan = who_plan()
    records = [source("WHO", str(i), f"Generic child health document {i}") for i in range(8)] + [
        source("WHO", "8", "Human plague humidity guidance"),
        source("WHO", "9", "Humidity response for human plague"),
    ]
    group = service_with(db, ScriptedProvider("WHO", plan, {plan[0].query: records})).search(request("WHO")).providers[0]
    assert (group.raw_result_count, group.normalized_count, group.relevant_count, group.returned_count) == (10, 10, 2, 2)


def test_13_no_results_remains_distinct_from_provider_error(db):
    plan = who_plan()
    empty = ScriptedProvider("WHO", plan, {})
    failed = ScriptedProvider("PUBMED", pubmed_plan(), {}, fail=True)
    result = service_with(db, empty, failed).search(request("WHO", "PUBMED"))
    by_id = {group.provider_id: group for group in result.providers}
    assert by_id["WHO"].status == "NO_RESULTS" and by_id["WHO"].warning is None
    assert by_id["PUBMED"].status == "PROVIDER_ERROR" and by_id["PUBMED"].warning is not None


def test_14_n_remains_an_independent_per_provider_maximum(db):
    plan = (ReviewedMedicalEvidenceQueryAttempt("DIRECT", "q", "DIRECT_TOPIC"),)
    pubmed = ScriptedProvider("PUBMED", plan, {"q": [source("PUBMED", str(i), f"Human plague humidity PubMed {i}") for i in range(12)]})
    who = ScriptedProvider("WHO", plan, {"q": [source("WHO", str(i), f"Human plague humidity WHO {i}") for i in range(12)]})
    result = service_with(db, pubmed, who).search(request("PUBMED", "WHO", count=10))
    assert [group.returned_count for group in result.providers] == [10, 10]
    assert pubmed.calls == [("q", 10)] and who.calls == [("q", 10)]


def test_15_contextual_discovery_label_does_not_make_content_draft_usable():
    record = source("PUBMED", "1", "Pediatric plague context")
    response = MedicalEvidenceReviewedService._response(
        record, relevance="RELATED_CONTEXT", query_level="RELATED_DISEASE_PEDIATRIC"
    )
    assert response.relevance == "RELATED_CONTEXT" and response.usable_for_draft is False


def test_16_who_metadata_only_semantics_remain_draft_ineligible():
    record = source("WHO", "1", "Human plague humidity guidance")
    assert MedicalEvidenceReviewedService._usable(record) is False


def test_17_pubmed_free_search_passes_the_user_query_without_guided_fallback(db):
    query = build_pubmed_query(["Plague"], weather_factor="humidity")
    assert query == pubmed_plan()[0].query
    free_query = '(plague[Title]) AND humidity'
    provider = ScriptedProvider(
        "PUBMED",
        (ReviewedMedicalEvidenceQueryAttempt("DIRECT", "unused", "DIRECT_TOPIC"),),
        {free_query: ()},
    )
    service = MedicalKnowledgePubMedService(db, provider)
    service._validate_disease_group = lambda _value: None
    response = service.search(PubMedSearchRequest(
        disease_group_id="9", search_mode="FREE", free_query=free_query,
        disease_terms=[], factor_type="WEATHER", factor_key="humidity",
        factor_value=None, weather_factor="humidity", max_results=10,
    ))
    assert response.query == free_query
    assert provider.calls == [(free_query, 10)]


def test_18_direct_pmid_lookup_still_calls_exact_lookup_once():
    article = PubMedArticleRecord(
        pmid="123", title="Plague article", authors=None, journal=None,
        publication_year=2020, doi=None, abstract_text=None,
        pubmed_url="https://pubmed.ncbi.nlm.nih.gov/123/",
    )

    class Client:
        def __init__(self):
            self.calls = []

        def get_article_by_pmid(self, pmid):
            self.calls.append(pmid)
            return article

    client = Client()
    provider = PubMedMedicalEvidenceProvider(client, content_service=None)
    assert provider.lookup("123").external_id == "123"
    assert client.calls == ["123"]


def test_19_auto_query_builder_and_budget_constants_are_not_changed_by_reviewed_plan():
    from app.services.pubmed_query_builder import build_auto_pubmed_query

    auto_query = build_auto_pubmed_query(["Plague"], ["humidity"])
    assert auto_query == build_pubmed_query(["Plague"], weather_factor="humidity")
    assert MAX_REVIEWED_QUERY_ATTEMPTS == 3
