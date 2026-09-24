from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401 - register users for FK DDL
from app.database import Base
from app.medical_evidence_reviewed_schemas import ReviewedProviderSearchRequest
from app.services.auto_evidence_discovery import (
    AutoDiscoveryDiagnostics,
    AutoDiscoveryResult,
    AutoEvidenceCandidate,
    MultiProviderAutoEvidenceProvider,
)
from app.services.auto_evidence_relevance import RelevanceSignals
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


NOW = datetime(2026, 9, 13, 9, 0, 0)


def evidence(provider_id: str, external_id: str, *, doi: str | None = None):
    return NormalizedMedicalEvidence(
        provider_id=provider_id,
        source_kind=MedicalEvidenceSourceKind.RESEARCH_ARTICLE,
        external_id=external_id,
        title=f"{provider_id} pediatric humidity evidence {external_id}",
        canonical_url=f"https://example.test/{provider_id.lower()}/{external_id}",
        doi=doi,
        publication_year=2026,
        abstract_text="Influenza humidity evidence in children.",
        retrieved_at=NOW,
    )


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        records=(),
        *,
        fail: bool = False,
        total_available: int | None = None,
        max_search_results: int = 25,
    ):
        self.descriptor = MedicalEvidenceProviderDescriptor(
            provider_id=provider_id,
            display_name={
                "PUBMED": "PubMed / PMC",
                "WHO": "World Health Organization (WHO)",
            }.get(provider_id, f"{provider_id} Evidence"),
            capabilities=frozenset({MedicalEvidenceCapability.SEARCH}),
            max_search_results=max_search_results,
        )
        self.records = tuple(records)
        self.fail = fail
        self.total_available = total_available
        self.search_limits: list[int] = []
        self.query_contexts = []

    def build_reviewed_query(self, context):
        self.query_contexts.append(context)
        return f"{self.descriptor.provider_id}:{context.disease_terms[0]}:{context.factor_key}"

    def search(self, _query: str, max_results: int):
        self.search_limits.append(max_results)
        if self.fail:
            raise MedicalEvidenceProviderUnavailableError("offline fixture")
        records = self.records[:max_results]
        return MedicalEvidenceSearchResult(
            self.total_available if self.total_available is not None else len(records),
            records,
        )

    def lookup(self, _external_id: str):
        return None

    def fetch_many(self, _external_ids: list[str]):
        return ()

    def enrich(self, source, *, retrieved_at=None):
        return source

    def close(self):
        return None


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def request(*provider_ids: str, count: int = 10):
    return ReviewedProviderSearchRequest(
        disease_group_id="168",
        disease_terms=["Influenza"],
        provider_ids=list(provider_ids),
        factor_type="WEATHER",
        factor_key="humidity",
        factor_value=None,
        weather_factor="humidity",
        max_results=count,
    )


def service_with(db, *providers: FakeProvider):
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


def records(provider_id: str, count: int):
    return tuple(evidence(provider_id, f"{provider_id.lower()}-{index}") for index in range(count))


def test_01_one_provider_receives_requested_n(db):
    pubmed = FakeProvider("PUBMED", records("PUBMED", 12))
    result = service_with(db, pubmed).search(request("PUBMED", count=10))
    assert pubmed.search_limits == [10]
    assert result.providers[0].returned_count == 10


def test_02_two_providers_each_receive_n(db):
    pubmed = FakeProvider("PUBMED", records("PUBMED", 10))
    who = FakeProvider("WHO", records("WHO", 10))
    service_with(db, pubmed, who).search(request("PUBMED", "WHO", count=10))
    assert pubmed.search_limits == [10]
    assert who.search_limits == [10]


def test_03_n_is_not_divided_and_max_candidates_is_sum(db):
    result = service_with(
        db,
        FakeProvider("PUBMED", records("PUBMED", 20)),
        FakeProvider("WHO", records("WHO", 20)),
    ).search(request("PUBMED", "WHO", count=20))
    assert (result.requested_count, result.max_candidates, result.count) == (20, 40, 40)


def test_04_provider_results_remain_separate(db):
    result = service_with(
        db,
        FakeProvider("PUBMED", records("PUBMED", 2)),
        FakeProvider("WHO", records("WHO", 1)),
    ).search(request("PUBMED", "WHO"))
    assert [[item.provider_id for item in group.results] for group in result.providers] == [
        ["PUBMED", "PUBMED"], ["WHO"]
    ]


def test_05_pubmed_ten_who_five_counts_are_exact(db):
    result = service_with(
        db,
        FakeProvider("PUBMED", records("PUBMED", 10), total_available=100),
        FakeProvider("WHO", records("WHO", 5), total_available=5),
    ).search(request("PUBMED", "WHO"))
    assert [(group.returned_count, group.total_available) for group in result.providers] == [
        (10, 100), (5, 5)
    ]


def test_06_pubmed_success_who_failure_keeps_both_groups(db):
    result = service_with(
        db,
        FakeProvider("PUBMED", records("PUBMED", 3)),
        FakeProvider("WHO", fail=True),
    ).search(request("PUBMED", "WHO"))
    assert [group.status for group in result.providers] == ["SUCCESS", "PROVIDER_ERROR"]
    assert result.count == 3 and result.providers[1].warning is not None


def test_07_who_success_pubmed_failure_keeps_both_groups(db):
    result = service_with(
        db,
        FakeProvider("PUBMED", fail=True),
        FakeProvider("WHO", records("WHO", 2)),
    ).search(request("PUBMED", "WHO"))
    assert [group.status for group in result.providers] == ["PROVIDER_ERROR", "SUCCESS"]
    assert [item.provider_id for item in result.results] == ["WHO", "WHO"]


def test_08_zero_results_is_not_provider_error(db):
    result = service_with(db, FakeProvider("PUBMED")).search(request("PUBMED"))
    assert (result.providers[0].status, result.providers[0].returned_count) == (
        "NO_RESULTS", 0
    )
    assert result.providers[0].warning is None


def test_09_provider_order_uses_deterministic_registry_order(db):
    result = service_with(
        db, FakeProvider("WHO"), FakeProvider("PUBMED"), FakeProvider("CDC")
    ).search(request("WHO", "CDC", "PUBMED"))
    assert [group.provider_id for group in result.providers] == ["CDC", "PUBMED", "WHO"]


def test_10_provider_specific_maximum_is_reported_and_respected(db):
    who = FakeProvider("WHO", records("WHO", 10), max_search_results=4)
    result = service_with(db, who).search(request("WHO", count=10))
    group = result.providers[0]
    assert who.search_limits == [4]
    assert (group.requested_count, group.effective_limit, group.returned_count) == (10, 4, 4)


def test_11_requested_effective_returned_counts_are_independent(db):
    provider = FakeProvider(
        "PUBMED", records("PUBMED", 3), total_available=81, max_search_results=7
    )
    group = service_with(db, provider).search(request("PUBMED", count=10)).providers[0]
    assert (group.requested_count, group.effective_limit, group.returned_count, group.total_available) == (
        10, 7, 3, 81
    )


def test_12_fake_third_provider_owns_its_query_syntax(db):
    future = FakeProvider("FUTURE", records("FUTURE", 1))
    result = service_with(db, future).search(request("FUTURE"))
    assert result.queries["FUTURE"] == "FUTURE:Influenza:humidity"
    assert future.query_contexts[0].disease_terms == ("Influenza",)


def test_13_cross_provider_duplicate_context_is_visible_but_unique_count_is_deduped(db):
    pubmed = FakeProvider("PUBMED", [evidence("PUBMED", "1", doi="10.1/shared")])
    who = FakeProvider("WHO", [evidence("WHO", "2", doi="10.1/shared")])
    result = service_with(db, pubmed, who).search(request("PUBMED", "WHO"))
    assert result.count == 2
    assert result.unique_count == 1
    assert [group.returned_count for group in result.providers] == [1, 1]


def test_14_mixed_provider_identities_are_preserved(db):
    result = service_with(
        db,
        FakeProvider("PUBMED", [evidence("PUBMED", "73164")]),
        FakeProvider("WHO", [evidence("WHO", "73164")]),
    ).search(request("PUBMED", "WHO"))
    assert [(item.provider_id, item.external_id) for item in result.results] == [
        ("PUBMED", "73164"), ("WHO", "73164")
    ]


def test_15_auto_global_selected_source_budget_is_unchanged():
    class AutoProvider:
        def __init__(self, provider_id):
            self.provider_name = provider_id
            self.received: list[int] = []

        def discover(self, **kwargs):
            self.received.append(kwargs["max_sources"])
            candidates = tuple(
                AutoEvidenceCandidate(
                    record,
                    record,
                    "PUBMED",
                    10,
                    RelevanceSignals(1, 1, 1),
                )
                for record in records(self.provider_name, 5)
            )
            return AutoDiscoveryResult(
                candidates,
                (),
                (),
                AutoDiscoveryDiagnostics(selected_for_generation=len(candidates)),
            )

    pubmed = AutoProvider("PUBMED")
    who = AutoProvider("WHO")
    result = MultiProviderAutoEvidenceProvider((pubmed, who)).discover(
        topic=SimpleNamespace(), disease_name="Influenza", max_sources=3
    )
    assert pubmed.received == [3] and who.received == [3]
    assert len(result.selected) <= 3
