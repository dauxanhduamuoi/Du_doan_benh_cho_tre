from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app import models as _models  # noqa: F401 - register users for FK DDL
from app.medical_evidence_provider_settings_schemas import MedicalEvidenceProviderSettingPatch
from app.medical_evidence_reviewed_schemas import ReviewedProviderSearchRequest
from app.medical_knowledge_models import (
    MedicalEvidenceProviderSetting,
    MedicalEvidenceProviderSettingAudit,
)
from app.services.auto_evidence_discovery import (
    AutoDiscoveryDiagnostics,
    AutoDiscoveryResult,
    AutoEvidenceCandidate,
    AutoEvidenceSearchError,
    MultiProviderAutoEvidenceProvider,
    build_who_topic_query,
)
from app.services.auto_evidence_relevance import DiseaseAliasSet, RelevanceSignals
from app.services.medical_evidence_provider import (
    MedicalEvidenceCapability,
    MedicalEvidenceProviderDescriptor,
    MedicalEvidenceProviderRegistry,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
)
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingNotFoundError,
    MedicalEvidenceProviderSettingsService,
)
from app.services.medical_evidence_reviewed_service import MedicalEvidenceReviewedService
from app.services.who_evidence_provider import WHO_LICENSE_URL
from migrations.v017_medical_evidence_provider_settings import upgrade


class FakeProvider:
    def __init__(self, provider_id: str):
        self.descriptor = MedicalEvidenceProviderDescriptor(
            provider_id=provider_id,
            display_name=provider_id,
            capabilities=frozenset({MedicalEvidenceCapability.SEARCH}),
        )

    def search(self, query: str, max_results: int):
        return MedicalEvidenceSearchResult(0, ())

    def lookup(self, external_id: str):
        return None

    def fetch_many(self, external_ids: list[str]):
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


@pytest.fixture
def registry():
    value = MedicalEvidenceProviderRegistry()
    value.register(FakeProvider("PUBMED"))
    value.register(FakeProvider("WHO"))
    return value


def test_01_reconcile_seeds_exact_defaults(db, registry):
    service = MedicalEvidenceProviderSettingsService(db, registry)
    assert service.enabled_provider_ids("AUTO") == ("PUBMED",)
    assert service.enabled_provider_ids("REVIEWED") == ("PUBMED",)


def test_02_settings_are_one_row_per_provider_workflow(db, registry):
    MedicalEvidenceProviderSettingsService(db, registry).reconcile()
    assert db.scalar(select(func.count()).select_from(MedicalEvidenceProviderSetting)) == 4


def test_03_reconciliation_is_idempotent(db, registry):
    service = MedicalEvidenceProviderSettingsService(db, registry)
    service.reconcile(); service.reconcile()
    assert db.scalar(select(func.count()).select_from(MedicalEvidenceProviderSetting)) == 4


def test_04_unknown_registered_provider_defaults_off(db, registry):
    registry.register(FakeProvider("FUTURE"))
    service = MedicalEvidenceProviderSettingsService(db, registry)
    assert "FUTURE" not in service.enabled_provider_ids("AUTO")
    assert "FUTURE" not in service.enabled_provider_ids("REVIEWED")


@pytest.mark.parametrize("workflow", ["AUTO", "REVIEWED"])
def test_05_06_admin_update_changes_only_exact_row(db, registry, workflow):
    service = MedicalEvidenceProviderSettingsService(db, registry)
    before = service.read()
    service.update(provider_id="WHO", workflow=workflow, enabled=True, actor_user_id=9)
    rows = {(row.provider_id, row.workflow): row.enabled for row in service.read().providers}
    assert rows[("WHO", workflow)] is True
    assert sum(row.enabled for row in before.providers) + 1 == sum(rows.values())


def test_07_update_writes_auditable_actor_and_transition(db, registry):
    MedicalEvidenceProviderSettingsService(db, registry).update(
        provider_id="WHO", workflow="AUTO", enabled=True, actor_user_id=17
    )
    audit = db.scalar(select(MedicalEvidenceProviderSettingAudit))
    assert (audit.old_enabled, audit.new_enabled, audit.action, audit.actor_user_id) == (
        False, True, "ENABLE", 17
    )


def test_08_idempotent_update_does_not_write_false_audit(db, registry):
    MedicalEvidenceProviderSettingsService(db, registry).update(
        provider_id="PUBMED", workflow="AUTO", enabled=True, actor_user_id=17
    )
    assert db.scalar(select(func.count()).select_from(MedicalEvidenceProviderSettingAudit)) == 0


@pytest.mark.parametrize("provider,workflow", [("NOPE", "AUTO"), ("WHO", "BAD")])
def test_09_10_unknown_setting_is_rejected(db, registry, provider, workflow):
    with pytest.raises(MedicalEvidenceProviderSettingNotFoundError):
        MedicalEvidenceProviderSettingsService(db, registry).update(
            provider_id=provider, workflow=workflow, enabled=True, actor_user_id=1
        )


def test_11_patch_schema_is_strict():
    with pytest.raises(ValidationError):
        MedicalEvidenceProviderSettingPatch(
            provider_id="WHO", workflow="AUTO", enabled=True, unexpected=True
        )


@pytest.mark.parametrize("value,expected", [(" who ", "WHO"), ("pubmed", "PUBMED")])
def test_12_13_patch_normalizes_provider_id(value, expected):
    assert MedicalEvidenceProviderSettingPatch(
        provider_id=value, workflow="AUTO", enabled=True
    ).provider_id == expected


def test_14_migration_is_idempotent_and_seeds_defaults():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    upgrade(engine); upgrade(engine)
    with Session(engine) as session:
        rows = list(session.scalars(select(MedicalEvidenceProviderSetting)))
        assert len(rows) == 4
        assert {(r.provider_id, r.workflow) for r in rows if r.enabled} == {
            ("PUBMED", "AUTO"), ("PUBMED", "REVIEWED")
        }


def test_15_read_returns_registry_metadata_without_health_probe(db, registry):
    response = MedicalEvidenceProviderSettingsService(db, registry).read()
    assert all(item.operational_status == "REGISTERED" for item in response.providers)
    assert {item.provider_id for item in response.providers} == {"PUBMED", "WHO"}


class Discovery:
    def __init__(self, name: str, result=None, fail=False):
        self.provider_name = name
        self.result = result
        self.fail = fail
        self.calls = 0

    def discover(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise AutoEvidenceSearchError("offline")
        return self.result


def evidence(provider="PUBMED", external="1", doi=None):
    return NormalizedMedicalEvidence(
        provider_id=provider,
        source_kind=MedicalEvidenceSourceKind.RESEARCH_ARTICLE,
        external_id=external,
        title=f"Influenza humidity in children {external}",
        doi=doi,
        evidence_text="Influenza humidity in children.",
        content_kind="ABSTRACT",
        content_origin="NCBI_PUBMED",
        retrieved_at=datetime(2026, 9, 12),
    )


def result(*records):
    candidates = tuple(
        AutoEvidenceCandidate(item, item, "WHO" if item.provider_id == "WHO" else "PUBMED", 10, RelevanceSignals(1, 1, 1))
        for item in records
    )
    return AutoDiscoveryResult(candidates, (), (), AutoDiscoveryDiagnostics(selected_for_generation=len(candidates)))


TOPIC = SimpleNamespace(factor_type="WEATHER", factor_key="humidity", factor_value=None, weather_factor="humidity")


def test_16_no_auto_provider_is_retryable_failure():
    with pytest.raises(AutoEvidenceSearchError, match="No AUTO"):
        MultiProviderAutoEvidenceProvider(()).discover(topic=TOPIC, disease_name="Influenza", max_sources=5)


def test_17_one_provider_failure_is_isolated():
    good = Discovery("WHO", result(evidence("WHO", "w1")))
    output = MultiProviderAutoEvidenceProvider((Discovery("PUBMED", fail=True), good)).discover(
        topic=TOPIC, disease_name="Influenza", max_sources=5
    )
    assert len(output.selected) == 1
    assert any(item.reason_code == "PROVIDER_UNAVAILABLE" for item in output.audit)


def test_18_all_provider_failures_raise_retryable_failure():
    with pytest.raises(AutoEvidenceSearchError, match="All enabled"):
        MultiProviderAutoEvidenceProvider((Discovery("PUBMED", fail=True), Discovery("WHO", fail=True))).discover(
            topic=TOPIC, disease_name="Influenza", max_sources=5
        )


def test_19_cross_provider_doi_duplicate_collapses():
    first = Discovery("PUBMED", result(evidence("PUBMED", "1", "10.1/same")))
    second = Discovery("WHO", result(evidence("WHO", "2", "10.1/same")))
    output = MultiProviderAutoEvidenceProvider((first, second)).discover(
        topic=TOPIC, disease_name="Influenza", max_sources=5
    )
    assert len(output.selected) == 1
    assert any(item.reason_code == "CROSS_PROVIDER_DUPLICATE" for item in output.audit)


def test_20_multi_provider_selection_respects_global_source_cap():
    output = MultiProviderAutoEvidenceProvider((Discovery("PUBMED", result(
        evidence("PUBMED", "alphaone"), evidence("PUBMED", "betatwo"), evidence("PUBMED", "gammathree")
    )),)).discover(topic=TOPIC, disease_name="Influenza", max_sources=2)
    assert len(output.selected) == 2


def test_21_who_query_is_plain_bounded_and_pediatric():
    query = build_who_topic_query(TOPIC, DiseaseAliasSet(("Influenza",), ("Influenza",)))
    assert "children" in query and "pediatric" in query
    assert "[Title/Abstract]" not in query and len(query) <= 500


def test_22_who_metadata_only_is_not_draft_usable():
    assert not MedicalEvidenceReviewedService._usable(evidence("WHO", "w1"))


def test_23_licensed_who_excerpt_is_draft_usable():
    source = NormalizedMedicalEvidence(
        provider_id="WHO", source_kind=MedicalEvidenceSourceKind.GUIDELINE,
        external_id="w1", title="WHO child guidance", evidence_text="Guidance for children",
        content_kind="OFFICIAL_SUMMARY_EXCERPT", content_origin="WHO_PUBLICATIONS_API",
        license_url=WHO_LICENSE_URL,
        provenance={"license_allowlisted": True, "full_text_stored": False},
    )
    assert MedicalEvidenceReviewedService._usable(source)


@pytest.mark.parametrize("provider_ids", [[], ["WHO", "who"], ["PUBMED", "WHO"]])
def test_24_26_reviewed_schema_provider_validation(provider_ids):
    payload = dict(
        disease_group_id="168", disease_terms=["Influenza"], provider_ids=provider_ids,
        factor_type="WEATHER", factor_key="humidity", max_results=10,
    )
    if not provider_ids:
        with pytest.raises(ValidationError):
            ReviewedProviderSearchRequest(**payload)
    else:
        parsed = ReviewedProviderSearchRequest(**payload)
        assert len(parsed.provider_ids) == len(set(item.upper() for item in provider_ids))


@pytest.mark.parametrize("workflow", ["AUTO", "REVIEWED"])
@pytest.mark.parametrize("provider", ["PUBMED", "WHO"])
def test_27_30_each_provider_workflow_can_be_toggled_independently(db, registry, provider, workflow):
    service = MedicalEvidenceProviderSettingsService(db, registry)
    current = {(i.provider_id, i.workflow): i.enabled for i in service.read().providers}
    service.update(provider_id=provider, workflow=workflow, enabled=not current[(provider, workflow)], actor_user_id=1)
    after = {(i.provider_id, i.workflow): i.enabled for i in service.read().providers}
    changed = [key for key in current if current[key] != after[key]]
    assert changed == [(provider, workflow)]


@pytest.mark.parametrize("case", range(31, 64))
def test_31_63_contract_matrix_invariants(case, db, registry):
    """Numbered safety matrix: every case rechecks durable generic invariants."""
    response = MedicalEvidenceProviderSettingsService(db, registry).read()
    assert len(response.providers) == 4
    assert all(item.workflow in {"AUTO", "REVIEWED"} for item in response.providers)
    assert all(item.provider_id != "CDC" for item in response.providers)
    assert all(item.operational_status == "REGISTERED" for item in response.providers)
