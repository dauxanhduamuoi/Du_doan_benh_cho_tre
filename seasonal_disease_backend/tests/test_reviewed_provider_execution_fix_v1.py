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
    MedicalEvidenceProviderTimeoutError,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQueryAttempt,
)
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingsService,
)
from app.services.medical_evidence_reviewed_service import (
    MedicalEvidenceReviewedService,
    ReviewedProviderSelectionError,
)


NOW = datetime(2026, 9, 14, 9, 0, 0)


def request(*provider_ids: str, count: int = 10) -> ReviewedProviderSearchRequest:
    return ReviewedProviderSearchRequest(
        disease_group_id="9",
        disease_terms=["Plague"],
        provider_ids=list(provider_ids),
        factor_type="WEATHER",
        factor_key="humidity",
        factor_value=None,
        weather_factor="humidity",
        max_results=count,
    )


def source(
    provider_id: str,
    external_id: str,
    title: str,
    summary: str = "",
    *,
    metadata: dict[str, object] | None = None,
) -> NormalizedMedicalEvidence:
    return NormalizedMedicalEvidence(
        provider_id=provider_id,
        source_kind=MedicalEvidenceSourceKind.OTHER,
        external_id=external_id,
        title=title,
        canonical_url=f"https://example.test/{provider_id.lower()}/{external_id}",
        abstract_text=summary,
        provider_metadata=metadata or {},
        retrieved_at=NOW,
    )


class CountingProvider:
    def __init__(
        self,
        provider_id: str,
        records=(),
        *,
        failure: Exception | None = None,
        plan=...,
    ):
        self.descriptor = MedicalEvidenceProviderDescriptor(
            provider_id=provider_id,
            display_name=provider_id,
            capabilities=frozenset({MedicalEvidenceCapability.SEARCH}),
            max_search_results=25,
        )
        self.records = tuple(records)
        self.failure = failure
        self.calls: list[tuple[str, int]] = []
        self._plan = plan

    def build_reviewed_query(self, context):
        return f"{self.descriptor.provider_id}:{context.disease_terms[0]}:{context.factor_key}"

    def build_reviewed_query_plan(self, context):
        if self._plan is not ...:
            return self._plan
        return (
            ReviewedMedicalEvidenceQueryAttempt(
                level="DIRECT_DISEASE_FACTOR",
                query=self.build_reviewed_query(context),
                relevance="DIRECT_TOPIC",
            ),
        )

    def search(self, query: str, limit: int):
        self.calls.append((query, limit))
        if self.failure is not None:
            raise self.failure
        records = self.records[:limit]
        return MedicalEvidenceSearchResult(
            total_count=len(self.records),
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


def service_with(db, *providers: CountingProvider, enable=True):
    registry = MedicalEvidenceProviderRegistry()
    for provider in providers:
        registry.register(provider)
    settings = MedicalEvidenceProviderSettingsService(db, registry)
    if enable:
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


def relevant_records(provider_id: str, count: int):
    return tuple(
        source(provider_id, str(index), f"Human plague humidity evidence {index}")
        for index in range(count)
    )


def test_01_request_dto_preserves_selected_provider_ids_without_pubmed_substitution():
    payload = request("who", "PUBMED", "who")
    assert payload.provider_ids == ["WHO", "PUBMED"]


def test_02_who_only_invokes_who_once_and_never_pubmed(db):
    pubmed = CountingProvider("PUBMED", relevant_records("PUBMED", 5))
    who = CountingProvider("WHO", relevant_records("WHO", 5))
    result = service_with(db, pubmed, who).search(request("WHO"))
    assert pubmed.calls == []
    assert len(who.calls) == 1
    assert [(group.provider_id, group.returned_count) for group in result.providers] == [("WHO", 5)]


def test_03_pubmed_only_invokes_pubmed_once_and_never_who(db):
    pubmed = CountingProvider("PUBMED", relevant_records("PUBMED", 5))
    who = CountingProvider("WHO", relevant_records("WHO", 5))
    result = service_with(db, pubmed, who).search(request("PUBMED"))
    assert len(pubmed.calls) == 1
    assert who.calls == []
    assert [group.provider_id for group in result.providers] == ["PUBMED"]


def test_04_pubmed_and_who_are_each_invoked_once(db):
    pubmed = CountingProvider("PUBMED", relevant_records("PUBMED", 10))
    who = CountingProvider("WHO", relevant_records("WHO", 3))
    result = service_with(db, pubmed, who).search(request("PUBMED", "WHO"))
    assert len(pubmed.calls) == len(who.calls) == 1
    assert [(group.provider_id, group.returned_count) for group in result.providers] == [
        ("PUBMED", 10),
        ("WHO", 3),
    ]


def test_05_fake_third_provider_is_routed_generically(db):
    providers = [CountingProvider(name, relevant_records(name, 1)) for name in ("PUBMED", "WHO", "FUTURE")]
    result = service_with(db, *providers).search(request("PUBMED", "WHO", "FUTURE"))
    assert all(len(provider.calls) == 1 for provider in providers)
    assert [group.provider_id for group in result.providers] == ["FUTURE", "PUBMED", "WHO"]


def test_06_successful_who_raw_zero_disease_relevance_is_diagnosable_no_results(db):
    records = [source("WHO", str(index), f"Generic child health {index}") for index in range(8)]
    records.extend((source("WHO", "8", "Humidity surveillance"), source("WHO", "9", "Moisture control")))
    who = CountingProvider("WHO", records)
    group = service_with(db, who).search(request("WHO")).providers[0]
    assert group.provider_invoked is True
    assert group.provider_status == "SUCCESS" and group.status == "NO_RESULTS"
    assert (
        group.raw_result_count,
        group.normalized_count,
        group.disease_match_count,
        group.factor_match_count,
        group.relevant_count,
        group.returned_count,
    ) == (10, 10, 0, 2, 0, 0)
    assert group.rejected_count == 10


def test_07_who_timeout_is_provider_error_not_zero_relevance(db):
    error = MedicalEvidenceProviderTimeoutError("fixture timeout")
    error.code = "WHO_SEARCH_TIMEOUT"
    who = CountingProvider("WHO", failure=error)
    group = service_with(db, who).search(request("WHO")).providers[0]
    assert group.provider_invoked is True
    assert group.provider_status == group.status == "PROVIDER_ERROR"
    assert group.warning is not None and group.warning.code == "WHO_SEARCH_TIMEOUT"


def test_08_pubmed_results_survive_who_timeout_and_both_groups_remain(db):
    error = MedicalEvidenceProviderTimeoutError("fixture timeout")
    error.code = "WHO_SEARCH_TIMEOUT"
    pubmed = CountingProvider("PUBMED", relevant_records("PUBMED", 10))
    who = CountingProvider("WHO", failure=error)
    result = service_with(db, pubmed, who).search(request("PUBMED", "WHO"))
    assert [(group.provider_id, group.status, group.returned_count) for group in result.providers] == [
        ("PUBMED", "SUCCESS", 10),
        ("WHO", "PROVIDER_ERROR", 0),
    ]


def test_09_pubmed_zero_does_not_hide_successful_who_group(db):
    pubmed = CountingProvider("PUBMED")
    who = CountingProvider("WHO", relevant_records("WHO", 4))
    result = service_with(db, pubmed, who).search(request("PUBMED", "WHO"))
    assert [(group.provider_id, group.status, group.returned_count) for group in result.providers] == [
        ("PUBMED", "NO_RESULTS", 0),
        ("WHO", "SUCCESS", 4),
    ]


def test_10_who_matcher_normalizes_case_punctuation_summary_and_reviewed_moisture_alias(db):
    record = source("WHO", "1", "HUMAN PLAGUE—technical update", "Environmental moisture was measured.")
    who = CountingProvider("WHO", [record])
    group = service_with(db, who).search(request("WHO")).providers[0]
    assert (group.disease_match_count, group.factor_match_count, group.relevant_count) == (1, 1, 1)


def test_11_title_only_record_cannot_infer_an_unavailable_factor_summary(db):
    who = CountingProvider(
        "WHO",
        [source("WHO", "1", "Plague management update")],
    )
    group = service_with(db, who).search(request("WHO")).providers[0]
    assert (group.disease_match_count, group.factor_match_count, group.relevant_count) == (1, 0, 1)
    assert group.status == "SUCCESS" and group.related_count == 1


def test_12_arbitrary_metadata_cannot_supply_relevance_terms(db):
    record = source(
        "WHO",
        "1",
        "Technical publication",
        metadata={"Tag": ["Plague", "relative humidity"]},
    )
    who = CountingProvider("WHO", [record])
    group = service_with(db, who).search(request("WHO")).providers[0]
    assert (group.disease_match_count, group.factor_match_count, group.relevant_count) == (0, 0, 0)


def test_13_disabled_who_setting_rejects_selection_without_invoking_any_provider(db):
    pubmed = CountingProvider("PUBMED")
    who = CountingProvider("WHO")
    service = service_with(db, pubmed, who, enable=False)
    with pytest.raises(ReviewedProviderSelectionError):
        service.search(request("WHO"))
    assert pubmed.calls == who.calls == []


def test_14_per_provider_n_and_invocation_trace_are_preserved(db):
    pubmed = CountingProvider("PUBMED", relevant_records("PUBMED", 12))
    who = CountingProvider("WHO", relevant_records("WHO", 12))
    result = service_with(db, pubmed, who).search(request("PUBMED", "WHO", count=4))
    assert [group.returned_count for group in result.providers] == [4, 4]
    assert all(group.provider_invoked for group in result.providers)
    assert pubmed.calls == [("PUBMED:Plague:humidity", 4)]
    assert who.calls == [("WHO:Plague:humidity", 4)]


def test_15_empty_provider_plan_fails_as_internal_orchestration_error(db):
    who = CountingProvider("WHO", plan=())
    with pytest.raises(ValueError, match="invalid query plan"):
        service_with(db, who).search(request("WHO"))
    assert who.calls == []
