from __future__ import annotations

import socket
import urllib.request
from contextlib import contextmanager

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.medical_knowledge_models import (
    MedicalEvidenceSource,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalKnowledgeTopicSource,
    MedicalRevisionSource,
)
from app.repositories.auto_medical_knowledge_repository import AutoMedicalKnowledgeRepository
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
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
        id=source_id, source_type="PUBMED", provider_id="PUBMED", external_id=f"{source_id}",
        source_kind="RESEARCH_ARTICLE", title=f"Stored source {source_id}", journal="Stored journal",
        publication_year=2025, url=f"https://pubmed.ncbi.nlm.nih.gov/{source_id}/",
        abstract_text=None, raw_metadata_json={"private": "MUST NOT RETURN"},
    )
    values.update(overrides)
    result = MedicalEvidenceSource(**values)
    db.add(result)
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
        db.add(MedicalRevisionSource(
            revision_id=result.id, source_id=stored_source.id, sort_order=order, source_role="PRIMARY"
        ))
    if published:
        selected_topic.published_revision_id = result.id
    db.commit()
    return result


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


def test_published_reviewed_metadata_without_generated_prose_or_evidence(db):
    stored = source(db)
    revision(db, topic(db), [(stored, 0)])
    with read_guard(db) as statements:
        result = TrustedReferenceReadService(db).read_batch(TrustedReferenceBatchRequest(items=[selector()]))
    assert result.items[0].references[0].model_dump(mode="json") == {
        "source_id": 10, "provider_id": "PUBMED", "external_id": "10", "source_type": "PUBMED",
        "source_kind": "RESEARCH_ARTICLE", "title": "Stored source 10", "journal": "Stored journal",
        "publication_year": 2025, "original_url": "https://pubmed.ncbi.nlm.nih.gov/10/",
    }
    assert len(statements) == 1
    for private in ("explanation", "limitations", "abstract_text", "evidence_text", "raw_metadata", "llm_model", "prompt_version", "auto_medical", "provider_settings", "medical_knowledge_topic_sources"):
        assert private not in statements[0]
        assert private not in result.model_dump_json()


def test_multiple_sources_order_by_sort_order_then_source_id_and_selector_order(db):
    a, b, c = source(db, 30), source(db, 20), source(db, 10)
    revision(db, topic(db), [(a, 2), (b, 0), (c, 0)])
    result = read(db, selector("99"), selector(), selector())
    assert [item.selector.disease_group_id for item in result.items] == ["99", "5"]
    assert result.items[0].references == []
    assert [reference.source_id for reference in result.items[1].references] == [10, 20, 30]


def test_duplicate_source_identity_retains_first_repository_occurrence(db, monkeypatch):
    stored = source(db)
    revision(db, topic(db), [(stored, 0)])
    rows = MedicalKnowledgeRepository(db).get_published_reference_metadata([("5", "WEATHER", "humidity", None)])
    monkeypatch.setattr(MedicalKnowledgeRepository, "get_published_reference_metadata", lambda _self, _selectors: rows * 3)
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
def test_only_current_approved_parent_published_revision(db, status, pointer, flag):
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


def test_replacement_and_withdrawal_read_only_current_pointer(db):
    selected_topic = topic(db)
    revision(db, selected_topic, [(source(db, 10), 0)])
    revision(db, selected_topic, [(source(db, 20), 0)], number=2)
    # Even a stale old visibility flag cannot expose the old revision.
    assert [reference.source_id for reference in read(db).items[0].references] == [20]
    selected_topic.published_revision_id = None
    db.commit()
    assert read(db).items[0].references == []


@pytest.mark.parametrize("selected,wrong", [
    (selector(factor_type="AGE", key="age_group", value="1-5 tuổi"), selector(factor_type="AGE", key="age_group", value="6-10 tuổi")),
    (selector(factor_type="SEX", key="gender", value="Nam"), selector(factor_type="SEX", key="gender", value="Nữ")),
    (selector(), selector(key="temperature")),
    (selector(), selector("6")),
    (selector(), selector("005")),
    (selector(factor_type="SEASONALITY", key="time_of_year"), selector()),
])
def test_full_canonical_selector_matching_does_not_leak_sources(db, selected, wrong):
    revision(db, topic(db, selected), [(source(db), 0)])
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
    revision(db, topic(db), [(source(db, **metadata), 0)])
    assert read(db).items[0].references == []


def test_skip_bad_metadata_keep_valid_and_preserve_legacy_provider(db):
    bad = source(db, 10, url=None, pmid="12345")
    good = source(db, 20, provider_id=None, external_id=None, source_kind=None,
                  source_type="WHO", title="  Historical publication  ", journal=None,
                  url="https://example.org/original-reference")
    revision(db, topic(db), [(bad, 0), (good, 1)])
    reference = read(db).items[0].references[0]
    assert reference.source_id == 20
    assert reference.provider_id is None  # Do not invent provenance or a PubMed URL.
    assert reference.source_type == "WHO"
    assert reference.title == "Historical publication"
    assert str(reference.original_url) == "https://example.org/original-reference"


def test_reader_does_not_autoflush_pending_unrelated_changes(db, monkeypatch):
    selected_topic = topic(db)
    revision(db, selected_topic, [(source(db), 0)])
    selected_topic.disease_group_id = "6"  # Unflushed pending ORM write.
    monkeypatch.setattr(db, "flush", forbidden)
    with read_guard(db):
        result = TrustedReferenceReadService(db).read_batch(TrustedReferenceBatchRequest(items=[selector()]))
    assert len(result.items[0].references) == 1  # Persisted "5", not dirty in-memory "6".
    assert selected_topic in db.dirty
    db.rollback()


def test_public_endpoint_is_anonymous_metadata_only_and_read_only(db, client):
    revision(db, topic(db), [(source(db), 0)])
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
