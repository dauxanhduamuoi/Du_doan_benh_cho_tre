from __future__ import annotations

import socket
import urllib.request
from contextlib import contextmanager
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.medical_knowledge_models import (
    MedicalEvidenceContent,
    MedicalEvidenceSource,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalKnowledgeTopicSource,
    MedicalRevisionSource,
)
from app.repositories.auto_medical_knowledge_repository import AutoMedicalKnowledgeRepository
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.repositories.parent_trusted_reference_repository import ParentTrustedReferenceRepository
from app.parent_trusted_reference_models import ParentTrustedReferenceApproval
from app.models import User
from app.services.parent_trusted_reference_curation_service import CurationSelector, ParentTrustedReferenceCurationService
from app.routers.public import router
from app.services.auto_medical_knowledge_service import AutoMedicalKnowledgeQueueService
from app.services.medical_evidence_provider_settings_service import MedicalEvidenceProviderSettingsService
from app.services.medical_knowledge_draft_generator import (
    OllamaMedicalKnowledgeDraftGenerator,
    OpenAIMedicalKnowledgeDraftGenerator,
)
from app.services.medical_knowledge_groq_generator import GroqMedicalKnowledgeDraftGenerator
from app.services.published_medical_knowledge_read_service import PublishedMedicalKnowledgeReadService
from app.services.pubmed_evidence_provider import PubMedMedicalEvidenceProvider
from app.services.trusted_reference_read_service import TrustedReferenceReadService
from app.services.who_evidence_provider import WhoMedicalEvidenceProvider
from app.trusted_reference_schemas import TrustedReferenceBatchRequest


def forbidden(*_args, **_kwargs):
    pytest.fail("Trusted References must not call a write, Auto, generator or network path")


@pytest.fixture(autouse=True)
def isolate_external_and_legacy_paths(monkeypatch):
    original_connect = socket.socket.connect

    def loopback_only(connection, address):
        # Windows asyncio implements its internal socketpair on loopback.
        # Actual outbound HTTP (including local Ollama) is blocked below.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(connection, address)
        forbidden()

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    for target, name in [
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
        (urllib.request, "urlopen"),
        (httpx.HTTPTransport, "handle_request"),
        (httpx.AsyncHTTPTransport, "handle_async_request"),
        (PublishedMedicalKnowledgeReadService, "__init__"),
        (MedicalKnowledgeRepository, "get_published_reference_metadata"),
        (AutoMedicalKnowledgeQueueService, "__init__"),
        (AutoMedicalKnowledgeQueueService, "enqueue_selectors"),
        (AutoMedicalKnowledgeRepository, "get_settings"),
        (AutoMedicalKnowledgeRepository, "get_or_create_topic"),
        (MedicalEvidenceProviderSettingsService, "reconcile"),
        (OpenAIMedicalKnowledgeDraftGenerator, "generate"),
        (OllamaMedicalKnowledgeDraftGenerator, "generate"),
        (GroqMedicalKnowledgeDraftGenerator, "generate"),
        (PubMedMedicalEvidenceProvider, "__init__"),
        (WhoMedicalEvidenceProvider, "__init__"),
    ]:
        monkeypatch.setattr(target, name, forbidden)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@contextmanager
def read_guard(db):
    statements = []

    def select_only(_conn, _cursor, statement, _parameters, _context, _many):
        assert statement.lstrip().upper().startswith("SELECT"), statement
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", select_only)
    try:
        with pytest.MonkeyPatch.context() as patch:
            for name in ("add", "add_all", "delete", "flush", "commit", "merge"):
                patch.setattr(db, name, forbidden)
            yield statements
        assert not db.new and not db.deleted
    finally:
        event.remove(db.bind, "before_cursor_execute", select_only)


def selector(disease="5", factor_type="WEATHER", key="humidity", value=None):
    return dict(disease_group_id=disease, factor_type=factor_type, factor_key=key, factor_value=value)


def source(db, source_id=10, **overrides):
    values = dict(
        id=source_id, source_type="WHO", provider_id="WHO", external_id=f"{source_id}",
        source_kind="GUIDELINE", title=f"Stored source {source_id}", journal="Stored publisher",
        publication_year=2025, url=f"https://www.who.int/publications/b/{source_id}",
        abstract_text=None, raw_metadata_json={"private": "MUST NOT RETURN"},
    )
    values.update(overrides)
    result = MedicalEvidenceSource(**values)
    db.add(result)
    db.flush()
    if result.provider_id == "WHO":
        db.add(MedicalEvidenceContent(
            source_id=result.id, content_kind="OFFICIAL_SUMMARY_EXCERPT",
            content_origin="WHO_PUBLICATIONS_API", external_identifier=result.external_id,
            evidence_text="PRIVATE EVIDENCE BODY MUST NOT RETURN", retrieved_at=datetime(2025, 1, 1),
            content_sha256=f"{source_id:064x}",
            provenance_json={
                "provider_id": "WHO", "external_id": result.external_id,
                "canonical_url": result.url, "retrieval_surface": "WHO_BIBLIO_SEARCH",
                "metadata_storage_allowed": True, "full_text_stored": False,
            },
        ))
    db.commit()
    return result


def topic(db, selected=None):
    values = selected or selector()
    result = MedicalKnowledgeTopic(
        **values, weather_factor=values["factor_key"] if values["factor_type"] == "WEATHER" else None
    )
    db.add(result)
    db.commit()
    return result


def revision(db, selected_topic, sources=(), *, number=1, status="APPROVED", published=True):
    result = MedicalKnowledgeRevision(
        topic_id=selected_topic.id, revision_number=number, status=status,
        parent_display_allowed=published, evidence_level="INSUFFICIENT", evidence_scope="PARTIAL_GROUP",
        short_explanation_vi="", detailed_explanation_vi="", limitations_vi="",
        generated_by_llm=True, llm_model="PRIVATE MODEL", prompt_version="PRIVATE PROMPT",
    )
    db.add(result)
    db.flush()
    for stored_source, order in sources:
        content = db.query(MedicalEvidenceContent).filter_by(source_id=stored_source.id).first()
        db.add(MedicalRevisionSource(
            revision_id=result.id, source_id=stored_source.id, sort_order=order, source_role="PRIMARY",
            evidence_content_id=content.id if content else None,
        ))
    if published:
        selected_topic.published_revision_id = result.id
    db.commit()
    return result


def curate(db, selected_topic, sources, *, approved=True):
    """Explicit test-only curation, independent of the legacy revision fixture."""
    if db.get(User, 9990) is None:
        db.add(User(id=9990, username="reference-curator", role="staff", password_hash="fixture"))
        db.commit()
    selected = CurationSelector(selected_topic.disease_group_id, selected_topic.factor_type,
                                selected_topic.factor_key, selected_topic.factor_value)
    rows = []
    for stored_source, order in sources:
        if db.get(MedicalKnowledgeTopicSource, (selected_topic.id, stored_source.id)) is None:
            db.add(MedicalKnowledgeTopicSource(topic_id=selected_topic.id, source_id=stored_source.id))
            db.commit()
        service = ParentTrustedReferenceCurationService(db)
        row = service.create_draft(topic_id=selected_topic.id, source_id=stored_source.id,
                                   selector=selected, actor_id=9990, sort_order=order)
        if approved:
            content = db.query(MedicalEvidenceContent).filter_by(source_id=stored_source.id).first()
            row = service.approve(row.approval_id, expected_version=1, selector=selected,
                                  evidence_content_id=content.id, actor_id=9990)
        rows.append(row)
    return rows


def read(db, *selectors):
    request = TrustedReferenceBatchRequest(items=list(selectors) or [selector()])
    with read_guard(db):
        return TrustedReferenceReadService(db).read_batch(request)


@pytest.fixture
def client(db):
    # Test the actual public router, without main's DB/worker/model startup lifecycle.
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client


def test_approved_curation_metadata_without_revision_prose_or_evidence_body(db):
    stored = source(db)
    curate(db, topic(db), [(stored, 0)])
    with read_guard(db) as statements:
        result = TrustedReferenceReadService(db).read_batch(TrustedReferenceBatchRequest(items=[selector()]))
    assert result.items[0].references[0].model_dump(mode="json") == {
        "source_id": 10, "provider_id": "WHO", "external_id": "10", "source_type": "WHO",
        "source_kind": "GUIDELINE", "title": "Stored source 10", "journal": "Stored publisher",
        "publication_year": 2025, "original_url": "https://www.who.int/publications/b/10",
    }
    assert len(statements) == 1
    for private in ("explanation", "limitations", "abstract_text", "evidence_text", "raw_metadata", "llm_model", "prompt_version", "auto_medical", "provider_settings", "medical_knowledge_revisions", "medical_revision_sources"):
        assert private not in statements[0]
        assert private not in result.model_dump_json()
    assert "provenance" in statements[0]
    assert "provenance" not in result.model_dump_json()
    assert "medical_knowledge_topic_sources" in statements[0]


def test_multiple_sources_order_by_sort_order_then_source_id_and_selector_order(db):
    a, b, c = source(db, 30), source(db, 20), source(db, 10)
    curate(db, topic(db), [(a, 2), (b, 0), (c, 0)])
    result = read(db, selector("99"), selector(), selector())
    assert [item.selector.disease_group_id for item in result.items] == ["99", "5"]
    assert result.items[0].references == []
    assert [reference.source_id for reference in result.items[1].references] == [10, 20, 30]


def test_duplicate_source_identity_retains_first_repository_occurrence(db, monkeypatch):
    stored = source(db)
    curate(db, topic(db), [(stored, 0)])
    rows = ParentTrustedReferenceRepository(db).get_approved_reference_metadata([("5", "WEATHER", "humidity", None)])
    monkeypatch.setattr(ParentTrustedReferenceRepository, "get_approved_reference_metadata", lambda _self, _selectors: rows * 3)
    assert [reference.source_id for reference in read(db).items[0].references] == [10]


@pytest.mark.parametrize("state", ["missing", "topic_only", "no_source", "library_only"])
def test_missing_reference_states_are_empty(db, state):
    if state != "missing":
        selected_topic = topic(db)
        if state == "no_source":
            revision(db, selected_topic)
        elif state == "library_only":
            stored = source(db)
            db.add(MedicalKnowledgeTopicSource(topic_id=selected_topic.id, source_id=stored.id))
            db.commit()
            revision(db, selected_topic)
    assert read(db).items[0].references == []


@pytest.mark.parametrize("status,pointer,flag", [
    ("DRAFT", False, False), ("APPROVED", False, False), ("DRAFT", True, True),
    ("REJECTED", True, True), ("APPROVED", True, False), ("APPROVED", False, True),
])
def test_legacy_publication_states_without_curation_are_empty(db, status, pointer, flag):
    selected_topic = topic(db)
    stored = source(db)
    current = revision(db, selected_topic, [(stored, 0)], status=status, published=False)
    current.parent_display_allowed = flag
    selected_topic.published_revision_id = current.id if pointer else None
    db.commit()
    assert read(db).items[0].references == []


def test_wrong_topic_pointer_does_not_leak_source(db):
    requested = topic(db)
    other = topic(db, selector("6"))
    current = revision(db, other, [(source(db), 0)])
    requested.published_revision_id = current.id
    db.commit()
    assert read(db).items[0].references == []


def test_legacy_replacement_and_withdrawal_do_not_control_curated_visibility(db):
    selected_topic = topic(db)
    stored = source(db, 10)
    revision(db, selected_topic, [(stored, 0)])
    curate(db, selected_topic, [(stored, 0)])
    revision(db, selected_topic, [(source(db, 20), 0)], number=2)
    assert [reference.source_id for reference in read(db).items[0].references] == [10]
    selected_topic.published_revision_id = None
    db.commit()
    assert [reference.source_id for reference in read(db).items[0].references] == [10]


@pytest.mark.parametrize("selected,wrong", [
    (selector(factor_type="AGE", key="age_group", value="1-5 tuổi"), selector(factor_type="AGE", key="age_group", value="6-10 tuổi")),
    (selector(factor_type="SEX", key="gender", value="Nam"), selector(factor_type="SEX", key="gender", value="Nữ")),
    (selector(), selector(key="temperature")),
    (selector(), selector("6")),
    (selector(), selector("005")),
    (selector(factor_type="SEASONALITY", key="time_of_year"), selector()),
])
def test_full_canonical_selector_matching_does_not_leak_sources(db, selected, wrong):
    curate(db, topic(db, selected), [(source(db), 0)])
    result = read(db, selected, wrong)
    assert [reference.source_id for reference in result.items[0].references] == [10]
    assert result.items[1].references == []


def test_null_selector_does_not_match_malformed_empty_value(db):
    # Such a legacy row is invalid under today's contract and must not match NULL.
    selected_topic = topic(db, selector(factor_type="SEASONALITY", key="time_of_year", value=""))
    revision(db, selected_topic, [(source(db), 0)])
    assert read(db, selector(factor_type="SEASONALITY", key="time_of_year")).items[0].references == []


@pytest.mark.parametrize("metadata", [
    {"title": "  "}, {"url": None}, {"url": ""}, {"url": "javascript:alert(1)"},
    {"url": "https://"}, {"url": "not a URL"}, {"url": "ftp://example.org/source"},
    {"url": "https:example.org/source"}, {"url": "https://example.org/bad path"},
    {"url": "https://user:password@example.org/source"}, {"publication_year": 9999},
])
def test_invalid_metadata_skips_source_without_failure_or_generated_fallback(db, metadata):
    stored = source(db)
    curate(db, topic(db), [(stored, 0)])
    for key, value in metadata.items():
        setattr(stored, key, value)
    db.commit()
    assert read(db).items[0].references == []


def test_legacy_who_label_without_identity_is_hidden_without_inventing_provenance(db):
    bad = source(db, 10, url=None, pmid="12345")
    good = source(db, 20, provider_id=None, external_id=None, source_kind=None,
                  source_type="WHO", title="  Historical publication  ", journal=None,
                  url="https://example.org/original-reference")
    revision(db, topic(db), [(bad, 0), (good, 1)])
    assert read(db).items[0].references == []


def test_reader_does_not_autoflush_pending_unrelated_changes(db, monkeypatch):
    selected_topic = topic(db)
    curate(db, selected_topic, [(source(db), 0)])
    selected_topic.disease_group_id = "6"  # Unflushed pending ORM write.
    monkeypatch.setattr(db, "flush", forbidden)
    with read_guard(db):
        result = TrustedReferenceReadService(db).read_batch(TrustedReferenceBatchRequest(items=[selector()]))
    assert len(result.items[0].references) == 1  # Persisted "5", not dirty in-memory "6".
    assert selected_topic in db.dirty
    db.rollback()


def test_public_endpoint_is_anonymous_metadata_only_and_read_only(db, client):
    curate(db, topic(db), [(source(db), 0)])
    with read_guard(db):
        response = client.post("/api/public/trusted-references", json={"items": [selector()]})
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"items"}
    assert set(payload["items"][0]) == {"selector", "references"}
    assert payload["items"][0]["selector"] == {**selector(), "weather_factor": "humidity"}
    assert payload["items"][0]["references"][0]["source_id"] == 10
    assert "PRIVATE" not in response.text and "MUST NOT RETURN" not in response.text


def test_empty_public_endpoint_does_not_create_topic_settings_or_jobs(db, client):
    with read_guard(db):
        response = client.post("/api/public/trusted-references", json={"items": [selector()]})
    assert response.status_code == 200
    assert response.json()["items"][0]["references"] == []


def test_legacy_weather_bridge_and_maximum_batch_are_supported(db, client):
    with read_guard(db):
        response = client.post("/api/public/trusted-references", json={
            "items": [{"disease_group_id": str(value), "weather_factor": "humidity"} for value in range(100)]
        })
    assert response.status_code == 200
    assert len(response.json()["items"]) == 100


@pytest.mark.parametrize("body", [
    {"items": []}, {"items": [selector()] * 101},
    {"items": [selector("not-a-disease-id")]},
    {"items": [selector(key="unknown")]},
    {"items": [selector(value="72%")]},
    {"items": [selector(factor_type="AGE", key="age_group")]},
    {"items": [selector(factor_type="SEX", key="gender", value="unknown")]},
    {"items": [selector(factor_type="SEASONALITY", key="time_of_year", value="summer")]},
    {"items": [{**selector(), "extra": True}]},
    {"items": [{**selector(), "weather_factor": "temperature"}]},
])
def test_invalid_public_selectors_are_422_without_reads_or_writes(db, client, body):
    with read_guard(db) as statements:
        response = client.post("/api/public/trusted-references", json=body)
    assert response.status_code == 422
    assert statements == []


@pytest.mark.parametrize("provider,kind", [
    ("PUBMED", "RESEARCH_ARTICLE"), ("PUBMED", "SYSTEMATIC_REVIEW"), ("PMC", "RESEARCH_ARTICLE"),
])
def test_published_research_with_valid_https_is_not_parent_visible(db, client, provider, kind):
    stored = source(db, provider_id=provider, source_type="PUBMED", source_kind=kind,
                    url="https://pubmed.ncbi.nlm.nih.gov/10/", pmid="10")
    revision(db, topic(db), [(stored, 0)])
    with read_guard(db):
        response = client.post("/api/public/trusted-references", json={"items": [selector()]})
    assert response.status_code == 200
    assert response.json()["items"][0]["references"] == []


@pytest.mark.parametrize("changes", [
    {"url": "https://who.int.evil.example/publications/b/10"},
    {"url": "http://www.who.int/publications/b/10"},
    {"url": "https://www.who.int/publications/b/20"},
    {"provider_id": "UNKNOWN", "source_type": "OTHER"},
    {"provider_id": None}, {"external_id": None},
    {"source_kind": "OTHER"}, {"source_kind": "SYSTEMATIC_REVIEW"},
])
def test_untrusted_published_metadata_is_filtered_without_side_effects(db, client, changes):
    stored = source(db)
    selected_topic = topic(db)
    revision(db, selected_topic, [(stored, 0)])
    curate(db, selected_topic, [(stored, 0)])
    for key, value in changes.items():
        setattr(stored, key, value)
    db.commit()
    with read_guard(db):
        response = client.post("/api/public/trusted-references", json={"items": [selector()]})
    assert response.status_code == 200
    assert response.json()["items"][0]["references"] == []


@pytest.mark.parametrize("proof_changes", [
    {"external_id": "different-id"}, {"provider_id": "PUBMED"},
    {"canonical_url": "https://www.who.int/publications/b/20"},
    {"retrieval_surface": "WHO_BIBLIO_SEARCH_REFERENCE"},
])
def test_persisted_provenance_mismatch_or_unverified_import_is_hidden(db, proof_changes):
    stored = source(db)
    curate(db, topic(db), [(stored, 0)])
    content = db.query(MedicalEvidenceContent).filter_by(source_id=stored.id).one()
    content.provenance_json = {**content.provenance_json, **proof_changes}
    db.commit()
    assert read(db).items[0].references == []


def test_mixed_sources_keep_only_allowed_in_existing_deterministic_order(db, client):
    allowed_a = source(db, 30, source_kind="TECHNICAL_REPORT")
    staff = source(db, 10, provider_id="PUBMED", source_type="PUBMED", source_kind="RESEARCH_ARTICLE",
                   url="https://pubmed.ncbi.nlm.nih.gov/10/")
    allowed_b = source(db, 20, source_kind="HEALTH_GUIDANCE")
    rejected = source(db, 40, url="https://example.org/WHO")
    selected_topic = topic(db)
    revision(db, selected_topic, [(allowed_a, 1), (staff, 0), (allowed_b, 1), (rejected, 0)])
    curate(db, selected_topic, [(allowed_a, 1), (allowed_b, 1)])
    curate(db, selected_topic, [(staff, 0), (rejected, 0)], approved=False)
    with read_guard(db) as statements:
        response = client.post("/api/public/trusted-references", json={"items": [selector()]})
    assert response.status_code == 200
    assert [item["source_id"] for item in response.json()["items"][0]["references"]] == [20, 30]
    assert len(statements) == 1
    assert "reason_code" not in response.text and "provenance" not in response.text


@pytest.mark.parametrize("mode", ["unlinked", "other_source", "missing_provenance"])
def test_only_curation_selected_snapshot_of_same_source_can_supply_proof(db, mode):
    stored = source(db, 10)
    other = source(db, 20)
    row = curate(db, topic(db), [(stored, 0)])[0]
    link = db.get(ParentTrustedReferenceApproval, row.approval_id)
    if mode == "unlinked":
        link.evidence_content_id = None
    elif mode == "other_source":
        link.evidence_content_id = db.query(MedicalEvidenceContent).filter_by(source_id=other.id).one().id
    else:
        db.get(MedicalEvidenceContent, link.evidence_content_id).provenance_json = None
    db.commit()
    assert read(db).items[0].references == []


def test_policy_uses_provenance_without_loading_or_requiring_evidence_body(db):
    stored = source(db)
    content = db.query(MedicalEvidenceContent).filter_by(source_id=stored.id).one()
    content.evidence_text = ""
    db.commit()
    curate(db, topic(db), [(stored, 0)])
    with read_guard(db) as statements:
        result = TrustedReferenceReadService(db).read_batch(TrustedReferenceBatchRequest(items=[selector()]))
    assert [item.source_id for item in result.items[0].references] == [10]
    assert "evidence_text" not in statements[0]
