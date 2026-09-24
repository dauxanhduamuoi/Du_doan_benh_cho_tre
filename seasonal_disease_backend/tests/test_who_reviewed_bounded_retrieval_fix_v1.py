from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401 - register user FK targets
from app.database import Base
from app.medical_evidence_reviewed_schemas import ReviewedProviderSearchRequest
from app.services.auto_evidence_discovery import WhoAutoEvidenceProvider
from app.services.medical_evidence_provider import (
    MedicalEvidenceCapability,
    MedicalEvidenceProviderDescriptor,
    MedicalEvidenceProviderRegistry,
    MedicalEvidenceProviderTimeoutError,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQueryAttempt,
    ReviewedMedicalEvidenceRetrievalPolicy,
)
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingsService,
)
from app.services.medical_evidence_reviewed_service import (
    MAX_REVIEWED_PAGE_REQUESTS,
    MAX_REVIEWED_RAW_CANDIDATES,
    MedicalEvidenceReviewedService,
)
from app.services.who_evidence_provider import (
    WHO_CONTENT_KIND,
    WHO_CONTENT_ORIGIN,
    WHO_LICENSE_URL,
    WhoMedicalEvidenceProvider,
    who_trust_class,
)


NOW = datetime(2026, 9, 14, 8, 0, 0)
PLAN = (
    ReviewedMedicalEvidenceQueryAttempt(
        "DIRECT_DISEASE_FACTOR",
        "plague humidity moisture children",
        "DIRECT_TOPIC",
    ),
)


def evidence(provider_id: str, external_id: str, title: str) -> NormalizedMedicalEvidence:
    return NormalizedMedicalEvidence(
        provider_id=provider_id,
        source_kind=MedicalEvidenceSourceKind.HEALTH_GUIDANCE,
        external_id=external_id,
        title=title,
        canonical_url=f"https://example.test/{provider_id.lower()}/{external_id}",
        retrieved_at=NOW,
    )


def relevant(provider_id: str, external_id: str) -> NormalizedMedicalEvidence:
    return evidence(provider_id, external_id, f"Human plague moisture guidance {external_id}")


def irrelevant(external_id: str) -> NormalizedMedicalEvidence:
    return evidence("WHO", external_id, f"General child health publication {external_id}")


class PagedWhoProvider:
    descriptor = MedicalEvidenceProviderDescriptor(
        provider_id="WHO",
        display_name="World Health Organization",
        capabilities=frozenset({MedicalEvidenceCapability.SEARCH}),
        max_search_results=25,
    )

    def __init__(
        self,
        pages: dict[int, tuple[NormalizedMedicalEvidence, ...]],
        *,
        total: int,
        pages_count: int,
        policy: ReviewedMedicalEvidenceRetrievalPolicy | None = None,
        fail_pages: set[int] | None = None,
    ):
        self.pages = pages
        self.total = total
        self.pages_count = pages_count
        self.policy = policy or ReviewedMedicalEvidenceRetrievalPolicy(10, 4, 40)
        self.fail_pages = fail_pages or set()
        self.page_calls: list[tuple[str, int, int]] = []
        self.search_calls: list[tuple[str, int]] = []

    def build_reviewed_query_plan(self, _context):
        return PLAN

    def build_reviewed_query(self, _context):
        return PLAN[0].query

    def build_reviewed_retrieval_policy(self, _target):
        return self.policy

    def search_page(self, query: str, page_size: int, page_number: int):
        self.page_calls.append((query, page_size, page_number))
        if page_number in self.fail_pages:
            error = MedicalEvidenceProviderTimeoutError("offline timeout")
            error.code = "WHO_SEARCH_TIMEOUT"
            raise error
        records = self.pages.get(page_number, ())[:page_size]
        return MedicalEvidenceSearchResult(
            total_count=self.total,
            sources=records,
            fetched_count=len(records),
            normalized_count=len(records),
            page_number=page_number,
            pages_count=self.pages_count,
        )

    def search(self, query: str, limit: int):
        self.search_calls.append((query, limit))
        return MedicalEvidenceSearchResult(0, ())


class LegacyProvider:
    def __init__(self, provider_id: str, records: tuple[NormalizedMedicalEvidence, ...]):
        self.descriptor = MedicalEvidenceProviderDescriptor(
            provider_id=provider_id,
            display_name=provider_id,
            capabilities=frozenset({MedicalEvidenceCapability.SEARCH}),
            max_search_results=25,
        )
        self.records = records
        self.calls: list[tuple[str, int]] = []

    def build_reviewed_query_plan(self, _context):
        return (
            ReviewedMedicalEvidenceQueryAttempt("DIRECT", "legacy query", "DIRECT_TOPIC"),
        )

    def build_reviewed_query(self, _context):
        return "legacy query"

    def search(self, query: str, limit: int):
        self.calls.append((query, limit))
        records = self.records[:limit]
        return MedicalEvidenceSearchResult(
            total_count=len(self.records),
            sources=records,
            fetched_count=len(records),
            normalized_count=len(records),
        )


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def reviewed_request(*provider_ids: str, count: int = 10):
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


def test_01_relevant_results_on_later_page_are_returned(db):
    provider = PagedWhoProvider(
        {0: tuple(irrelevant(str(i)) for i in range(10)), 1: (relevant("WHO", "10"),)},
        total=11,
        pages_count=2,
    )
    group = service_with(db, provider).search(reviewed_request("WHO")).providers[0]
    assert group.returned_count == 1
    assert [call[2] for call in provider.page_calls] == [0, 1]


def test_02_pages_accumulate_until_the_relevant_target(db):
    provider = PagedWhoProvider(
        {
            0: tuple(irrelevant(f"a{i}") for i in range(10)),
            1: tuple(relevant("WHO", f"r{i}") for i in range(5))
            + tuple(irrelevant(f"b{i}") for i in range(5)),
            2: tuple(relevant("WHO", f"r{i}") for i in range(5, 10))
            + tuple(irrelevant(f"c{i}") for i in range(5)),
        },
        total=30,
        pages_count=3,
    )
    group = service_with(db, provider).search(reviewed_request("WHO", count=10)).providers[0]
    assert group.returned_count == 10
    assert group.pages_fetched == 3
    assert group.stop_reason == "TARGET_REACHED"


def test_03_target_reached_stops_before_another_page(db):
    provider = PagedWhoProvider(
        {0: tuple(relevant("WHO", str(i)) for i in range(10)), 1: (relevant("WHO", "later"),)},
        total=11,
        pages_count=2,
    )
    group = service_with(db, provider).search(reviewed_request("WHO", count=2)).providers[0]
    assert group.pages_fetched == 1
    assert [call[2] for call in provider.page_calls] == [0]


def test_04_provider_exhaustion_returns_fewer_than_target(db):
    provider = PagedWhoProvider({0: (relevant("WHO", "1"),)}, total=1, pages_count=1)
    group = service_with(db, provider).search(reviewed_request("WHO")).providers[0]
    assert group.returned_count == 1
    assert group.provider_exhausted and group.stop_reason == "PROVIDER_EXHAUSTED"


def test_05_successful_zero_examines_all_available_pages(db):
    provider = PagedWhoProvider(
        {0: tuple(irrelevant(str(i)) for i in range(10)), 1: (irrelevant("10"),)},
        total=11,
        pages_count=2,
    )
    group = service_with(db, provider).search(reviewed_request("WHO")).providers[0]
    assert group.status == "NO_RESULTS"
    assert (group.raw_candidates_examined, group.pages_fetched) == (11, 2)


def test_06_raw_candidate_budget_is_enforced(db):
    provider = PagedWhoProvider(
        {page: tuple(irrelevant(f"{page}-{i}") for i in range(3)) for page in range(5)},
        total=99,
        pages_count=33,
        policy=ReviewedMedicalEvidenceRetrievalPolicy(3, 10, 6),
    )
    group = service_with(db, provider).search(reviewed_request("WHO")).providers[0]
    assert (group.pages_fetched, group.raw_candidates_examined) == (2, 6)
    assert group.budget_exhausted and group.stop_reason == "CANDIDATE_BUDGET_REACHED"


def test_07_page_budget_is_enforced(db):
    provider = PagedWhoProvider(
        {page: tuple(irrelevant(f"{page}-{i}") for i in range(5)) for page in range(4)},
        total=100,
        pages_count=20,
        policy=ReviewedMedicalEvidenceRetrievalPolicy(5, 2, 100),
    )
    group = service_with(db, provider).search(reviewed_request("WHO")).providers[0]
    assert group.pages_fetched == 2 and group.budget_exhausted


def test_08_untrusted_provider_policy_is_clamped_to_global_bounds(db):
    provider = PagedWhoProvider(
        {page: tuple(irrelevant(f"{page}-{i}") for i in range(25)) for page in range(8)},
        total=1000,
        pages_count=100,
        policy=ReviewedMedicalEvidenceRetrievalPolicy(1000, 1000, 10000),
    )
    group = service_with(db, provider).search(reviewed_request("WHO")).providers[0]
    assert group.pages_fetched == MAX_REVIEWED_PAGE_REQUESTS == 4
    assert group.raw_candidates_examined == MAX_REVIEWED_RAW_CANDIDATES == 100


def test_09_duplicates_across_pages_are_examined_and_returned_once(db):
    duplicate = relevant("WHO", "same")
    provider = PagedWhoProvider(
        {0: (duplicate, irrelevant("other")), 1: (duplicate, relevant("WHO", "new"))},
        total=4,
        pages_count=2,
        policy=ReviewedMedicalEvidenceRetrievalPolicy(2, 4, 8),
    )
    group = service_with(db, provider).search(reviewed_request("WHO", count=3)).providers[0]
    assert [item.external_id for item in group.results] == ["same", "new"]
    assert group.normalized_count == 3


def test_10_who_page_contract_sends_page_number_and_parses_counts():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(
            200,
            json={"Total": 31, "PagesCount": 4, "Results": []},
            headers={"content-type": "application/json"},
            request=request,
        )

    provider = WhoMedicalEvidenceProvider(
        httpx.Client(transport=httpx.MockTransport(handler)), clock=lambda: NOW
    )
    result = provider.search_page("plague humidity", 10, 2)
    assert (result.total_count, result.pages_count, result.page_number) == (31, 4, 2)
    assert seen[0].url.params["pageSize"] == "10"
    assert seen[0].url.params["pageNumber"] == "2"


def test_11_who_only_search_does_not_invoke_pubmed(db):
    who = PagedWhoProvider({0: (relevant("WHO", "1"),)}, total=1, pages_count=1)
    pubmed = LegacyProvider("PUBMED", (relevant("PUBMED", "p1"),))
    result = service_with(db, pubmed, who).search(reviewed_request("WHO", count=1))
    assert result.provider_count == 1 and result.providers[0].provider_id == "WHO"
    assert pubmed.calls == []


def test_12_mixed_search_keeps_an_independent_target_per_provider(db):
    pubmed = LegacyProvider("PUBMED", tuple(relevant("PUBMED", str(i)) for i in range(3)))
    who = PagedWhoProvider(
        {0: tuple(relevant("WHO", str(i)) for i in range(3))},
        total=3,
        pages_count=1,
        policy=ReviewedMedicalEvidenceRetrievalPolicy(3, 4, 12),
    )
    result = service_with(db, pubmed, who).search(reviewed_request("PUBMED", "WHO", count=3))
    assert [group.returned_count for group in result.providers] == [3, 3]


def test_13_first_page_timeout_is_provider_error(db):
    provider = PagedWhoProvider({}, total=10, pages_count=1, fail_pages={0})
    group = service_with(db, provider).search(reviewed_request("WHO")).providers[0]
    assert group.status == "PROVIDER_ERROR" and group.returned_count == 0
    assert group.stop_reason == "PROVIDER_ERROR"


def test_14_later_page_timeout_preserves_prior_relevant_results(db):
    provider = PagedWhoProvider(
        {0: (relevant("WHO", "kept"),) + tuple(irrelevant(str(i)) for i in range(9))},
        total=20,
        pages_count=2,
        fail_pages={1},
    )
    group = service_with(db, provider).search(reviewed_request("WHO")).providers[0]
    assert group.status == "SUCCESS" and [item.external_id for item in group.results] == ["kept"]
    assert group.provider_status == "PROVIDER_ERROR" and group.warning is not None


def test_15_auto_who_still_uses_one_legacy_search_call():
    provider = LegacyProvider("WHO", ())
    topic = SimpleNamespace(factor_type="WEATHER", factor_key="humidity", factor_value=None)
    WhoAutoEvidenceProvider(provider, candidate_budget=15).discover(
        topic=topic, disease_name="Plague", max_sources=5
    )
    assert len(provider.calls) == 1 and provider.calls[0][1] == 15


def test_16_pubmed_reviewed_behavior_remains_one_search_call(db):
    pubmed = LegacyProvider("PUBMED", tuple(relevant("PUBMED", str(i)) for i in range(20)))
    group = service_with(db, pubmed).search(reviewed_request("PUBMED", count=10)).providers[0]
    assert group.returned_count == 10
    assert pubmed.calls == [("legacy query", 10)] and group.pages_fetched == 1


def test_17_who_metadata_only_source_remains_draft_ineligible():
    assert MedicalEvidenceReviewedService._usable(relevant("WHO", "metadata-only")) is False


def test_18_who_trust_and_license_gate_is_unchanged():
    trusted = NormalizedMedicalEvidence(
        provider_id="WHO",
        source_kind=MedicalEvidenceSourceKind.HEALTH_GUIDANCE,
        external_id="trusted",
        title="Plague moisture guidance",
        canonical_url="https://www.who.int/publications/i/item/trusted",
        evidence_text="Official excerpt",
        content_kind=WHO_CONTENT_KIND,
        content_origin=WHO_CONTENT_ORIGIN,
        license_url=WHO_LICENSE_URL,
        provenance={"license_allowlisted": True, "full_text_stored": False},
        retrieved_at=NOW,
    )
    assert who_trust_class(trusted) == "WHO"
    assert who_trust_class(trusted.__class__(**{**trusted.__dict__, "license_url": None})) == "UNTRUSTED"
