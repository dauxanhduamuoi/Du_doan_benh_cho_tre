from __future__ import annotations

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
    MedicalRevisionSource,
)
from app.published_medical_knowledge_schemas import PublishedMedicalKnowledgeBatchRequest
from app.routers.public import router
from app.services.published_medical_knowledge_read_service import (
    PublishedMedicalKnowledgeReadService,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_topic(db: Session, disease_group_id="5", weather_factor="precipitation"):
    topic = MedicalKnowledgeTopic(
        disease_group_id=disease_group_id,
        weather_factor=weather_factor,
        created_by=None,
    )
    db.add(topic)
    db.commit()
    return topic


def add_revision(
    db: Session,
    topic: MedicalKnowledgeTopic,
    *,
    revision_number=1,
    status="APPROVED",
    evidence_level="SUPPORTED",
    evidence_scope="PARTIAL_GROUP",
    parent_display_allowed=False,
    short="Published short explanation.",
    source_id=None,
):
    source_id = source_id or 100 + revision_number + topic.id * 10
    source = MedicalEvidenceSource(
        id=source_id,
        source_type="PUBMED",
        pmid=str(12000000 + source_id),
        doi=f"10.1000/public-{source_id}",
        title=f"Public citation {source_id}",
        authors="Private author list is not part of the public DTO",
        journal="Safe Journal",
        publication_year=2024,
        abstract_text="RAW ABSTRACT MUST NEVER BE RETURNED",
        url="javascript:unsafe()",
        raw_metadata_json={"secret": "RAW DATABASE METADATA"},
    )
    revision = MedicalKnowledgeRevision(
        topic_id=topic.id,
        revision_number=revision_number,
        evidence_level=evidence_level,
        evidence_scope=evidence_scope,
        short_explanation_vi=short,
        detailed_explanation_vi="Published detailed explanation.",
        limitations_vi="Published limitations without causal certainty.",
        status=status,
        parent_display_allowed=parent_display_allowed,
        generated_by_llm=True,
        llm_model="PRIVATE_PROVIDER_MODEL",
        prompt_version="PRIVATE_PROMPT_VERSION",
        review_note="PRIVATE_REVIEW_NOTE",
    )
    db.add_all([source, revision])
    db.flush()
    db.add(
        MedicalRevisionSource(
            revision_id=revision.id,
            source_id=source.id,
            source_role="PRIMARY",
            sort_order=0,
            relevance_note="DIRECT: Internal source assessment must not be returned.",
            population_relevance="PEDIATRIC_DIRECT",
            population_note="The stored abstract explicitly describes children.",
        )
    )
    db.commit()
    return revision


def publish_pointer(db: Session, topic, revision):
    revision.parent_display_allowed = True
    topic.published_revision_id = revision.id
    db.commit()


def request_for(*pairs):
    return PublishedMedicalKnowledgeBatchRequest(
        items=[
            {"disease_group_id": disease_id, "weather_factor": factor}
            for disease_id, factor in pairs
        ]
    )


def test_current_published_approved_revision_returns_safe_public_view(db):
    topic = add_topic(db)
    revision = add_revision(db, topic)
    publish_pointer(db, topic, revision)

    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )

    assert len(result.items) == 1
    item = result.items[0]
    assert item.revision_id == revision.id
    assert item.disease_group_id == "5"
    assert item.weather_factor == "precipitation"
    assert item.evidence_level == "SUPPORTED"
    assert item.sources[0].pmid == str(12000000 + 111)
    assert item.sources[0].url == f"https://pubmed.ncbi.nlm.nih.gov/{12000000 + 111}/"


@pytest.mark.parametrize(
    ("status", "pointer", "flag"),
    [
        ("DRAFT", False, False),
        ("DRAFT", True, True),
        ("APPROVED", False, False),
        ("APPROVED", True, False),
    ],
)
def test_draft_unpublished_or_inconsistent_revision_is_not_returned(
    db, status, pointer, flag
):
    topic = add_topic(db)
    revision = add_revision(
        db, topic, status=status, parent_display_allowed=flag
    )
    if pointer:
        topic.published_revision_id = revision.id
        db.commit()
    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )
    assert result.items == []


def test_wrong_topic_pointer_fails_closed(db):
    requested_topic = add_topic(db, "5", "precipitation")
    other_topic = add_topic(db, "6", "precipitation")
    other_revision = add_revision(db, other_topic, parent_display_allowed=True)
    requested_topic.published_revision_id = other_revision.id
    db.commit()

    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )
    assert result.items == []


def test_replacement_returns_only_current_revision_immediately(db):
    topic = add_topic(db)
    old = add_revision(db, topic, revision_number=1, short="OLD REVISION")
    publish_pointer(db, topic, old)
    first_result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )
    assert [item.revision_id for item in first_result.items] == [old.id]
    assert [item.short_explanation_vi for item in first_result.items] == ["OLD REVISION"]

    new = add_revision(db, topic, revision_number=2, short="NEW REVISION")
    old.parent_display_allowed = False
    new.parent_display_allowed = True
    topic.published_revision_id = new.id
    db.commit()

    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )
    assert [item.revision_id for item in result.items] == [new.id]
    assert [item.short_explanation_vi for item in result.items] == ["NEW REVISION"]


def test_missing_topic_factor_and_noncanonical_text_are_normal_empty_results(db):
    topic = add_topic(db)
    revision = add_revision(db, topic)
    publish_pointer(db, topic, revision)
    service = PublishedMedicalKnowledgeReadService(db)

    result = service.read_batch(
        request_for(
            ("6", "precipitation"),
            ("5", "humidity"),
            ("005", "precipitation"),
        )
    )
    assert result.items == []


def test_batch_matching_and_order_follow_first_canonical_selector_order(db):
    topic_rain = add_topic(db, "5", "precipitation")
    rain = add_revision(db, topic_rain, short="RAIN")
    publish_pointer(db, topic_rain, rain)
    topic_humidity = add_topic(db, "6", "humidity")
    humidity = add_revision(db, topic_humidity, short="HUMIDITY")
    publish_pointer(db, topic_humidity, humidity)

    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(
            ("6", "humidity"),
            ("999", "wind"),
            ("5", "precipitation"),
            ("6", "humidity"),
        )
    )
    assert [(item.disease_group_id, item.weather_factor) for item in result.items] == [
        ("6", "humidity"),
        ("5", "precipitation"),
    ]


@pytest.mark.parametrize("evidence_level", ["INSUFFICIENT", "CONFLICTING"])
def test_non_displayable_evidence_is_hidden_conservatively(db, evidence_level):
    topic = add_topic(db)
    revision = add_revision(db, topic, evidence_level=evidence_level)
    publish_pointer(db, topic, revision)
    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )
    assert result.items == []


@pytest.mark.parametrize("evidence_level", ["SUPPORTED", "LIMITED_OR_INDIRECT"])
def test_legacy_displayable_evidence_policy_is_reused(db, evidence_level):
    topic = add_topic(db)
    revision = add_revision(db, topic, evidence_level=evidence_level)
    publish_pointer(db, topic, revision)
    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )
    assert [item.evidence_level for item in result.items] == [evidence_level]


def test_legacy_publication_without_population_assessment_fails_closed(db):
    topic = add_topic(db)
    revision = add_revision(db, topic)
    link = db.query(MedicalRevisionSource).filter_by(revision_id=revision.id).one()
    link.population_relevance = None
    link.population_note = None
    publish_pointer(db, topic, revision)

    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )

    assert result.items == []


def test_malformed_structured_content_fails_closed(db):
    topic = add_topic(db)
    revision = add_revision(db, topic)
    publish_pointer(db, topic, revision)
    link = db.query(MedicalRevisionSource).filter_by(revision_id=revision.id).one()
    link.relevance_note = "MALFORMED INTERNAL ASSESSMENT"
    db.commit()
    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )
    assert result.items == []


def test_inconsistent_source_role_and_assessment_fails_closed(db):
    topic = add_topic(db)
    revision = add_revision(db, topic)
    publish_pointer(db, topic, revision)
    link = db.query(MedicalRevisionSource).filter_by(revision_id=revision.id).one()
    link.source_role = "SUPPORTING"
    db.commit()

    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )
    assert result.items == []


def test_evidence_snapshot_owned_by_another_source_fails_closed(db):
    topic = add_topic(db)
    revision = add_revision(db, topic)
    other_source = MedicalEvidenceSource(
        source_type="PUBMED",
        pmid="39999999",
        title="Different source owner",
        abstract_text="Different source abstract.",
    )
    db.add(other_source)
    db.flush()
    mismatched_content = MedicalEvidenceContent(
        source_id=other_source.id,
        content_kind="ABSTRACT",
        content_origin="NCBI_PUBMED",
        evidence_text="Evidence that belongs to the different source.",
        retrieved_at=datetime(2026, 8, 24, 8, 0, 0),
        is_truncated=False,
        content_sha256="a" * 64,
    )
    db.add(mismatched_content)
    db.flush()
    link = db.query(MedicalRevisionSource).filter_by(revision_id=revision.id).one()
    link.evidence_content_id = mismatched_content.id
    publish_pointer(db, topic, revision)

    result = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    )

    assert result.items == []


def test_public_read_does_not_call_network_or_expose_private_fields(db, monkeypatch):
    topic = add_topic(db)
    revision = add_revision(db, topic)
    publish_pointer(db, topic, revision)

    def network_forbidden(*_args, **_kwargs):
        raise AssertionError("Parent Tier 2 read path must not call external services")

    monkeypatch.setattr(httpx.Client, "request", network_forbidden)
    payload = PublishedMedicalKnowledgeReadService(db).read_batch(
        request_for(("5", "precipitation"))
    ).model_dump()
    serialized = str(payload)
    for forbidden in [
        "RAW ABSTRACT MUST NEVER BE RETURNED",
        "RAW DATABASE METADATA",
        "PRIVATE_PROVIDER_MODEL",
        "PRIVATE_PROMPT_VERSION",
        "PRIVATE_REVIEW_NOTE",
        "Internal source assessment",
        "reviewed_by",
        "published_by",
        "abstract_text",
        "raw_metadata_json",
        "evidence_text",
    ]:
        assert forbidden not in serialized


@pytest.fixture
def public_client(db):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client


def test_public_endpoint_allows_anonymous_parent_and_returns_empty_normally(
    public_client
):
    response = public_client.post(
        "/api/public/medical-knowledge/published",
        json={"items": [{"disease_group_id": "5", "weather_factor": "humidity"}]},
    )
    assert response.status_code == 200
    assert response.json() == {"items": []}


@pytest.mark.parametrize(
    "body",
    [
        {"items": []},
        {"items": [{"disease_group_id": "pneumonia", "weather_factor": "humidity"}]},
        {"items": [{"disease_group_id": "5", "weather_factor": "Độ ẩm"}]},
        {"items": [{"disease_group_id": "5", "weather_factor": "humidity", "extra": True}]},
        {"items": [{"disease_group_id": "5", "weather_factor": "humidity"}] * 101},
    ],
)
def test_public_selector_validation_is_bounded_and_canonical(public_client, body):
    assert public_client.post(
        "/api/public/medical-knowledge/published", json=body
    ).status_code == 422
