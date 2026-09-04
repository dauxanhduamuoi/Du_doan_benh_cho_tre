from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.medical_knowledge_models import (
    MedicalEvidenceContent,
    MedicalEvidenceSource,
    MedicalKnowledgePublication,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalRevisionSource,
)
from app.models import User
from app.published_medical_knowledge_schemas import PublishedMedicalKnowledgeBatchRequest
from app.medical_knowledge_draft_schemas import DraftRevisionPatch
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.routers.medical_knowledge_drafts import router
from app.security import create_access_token
from app.services.medical_knowledge_approval_service import MedicalKnowledgeApprovalService
from app.services.medical_knowledge_draft_service import MedicalKnowledgeDraftService
from app.services.medical_knowledge_publication_service import (
    MedicalKnowledgePublicationService,
    PublicationConflictError,
    PublicationValidationError,
)
from app.services.published_medical_knowledge_read_service import (
    PublishedMedicalKnowledgeReadService,
)
from migrations.v004_medical_knowledge_unpublish import downgrade, upgrade


BASE_TIME = datetime(2026, 8, 24, 8, 0, 0)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_user(db: Session, username: str, role: str) -> User:
    user = User(
        username=username,
        full_name=f"Actor {username}",
        password_hash="x",
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def add_topic(db: Session, disease_group_id: str, factor: str) -> MedicalKnowledgeTopic:
    topic = MedicalKnowledgeTopic(
        disease_group_id=disease_group_id,
        weather_factor=factor,
    )
    db.add(topic)
    db.commit()
    return topic


def add_draft(
    db: Session,
    topic: MedicalKnowledgeTopic,
    revision_number: int,
    *,
    short: str | None = None,
) -> MedicalKnowledgeRevision:
    source = MedicalEvidenceSource(
        source_type="PUBMED",
        pmid=str(30000000 + topic.id * 100 + revision_number),
        doi=f"10.1000/unpublish-{topic.id}-{revision_number}",
        title=f"Evidence {topic.id}-{revision_number}",
        authors="Authors stay immutable",
        journal="Audit Journal",
        publication_year=2025,
        abstract_text="A non-empty persisted abstract used for approval validation.",
        url="https://pubmed.ncbi.nlm.nih.gov/30000001/",
        raw_metadata_json={"immutable": True},
    )
    revision = MedicalKnowledgeRevision(
        topic_id=topic.id,
        revision_number=revision_number,
        evidence_level="SUPPORTED",
        evidence_scope="PARTIAL_GROUP",
        short_explanation_vi=short or f"Short explanation revision {revision_number}.",
        detailed_explanation_vi="Detailed explanation remains unchanged.",
        limitations_vi="Observational evidence does not prove causality.",
        status="DRAFT",
        parent_display_allowed=False,
        generated_by_llm=True,
        llm_model="immutable-private-model",
        prompt_version="immutable-prompt-version",
    )
    db.add_all([source, revision])
    db.flush()
    evidence_content = MedicalEvidenceContent(
        source_id=source.id,
        content_kind="ABSTRACT",
        content_origin="NCBI_PUBMED",
        evidence_text="A bounded immutable evidence snapshot used by this revision.",
        retrieved_at=BASE_TIME,
        is_truncated=False,
        provenance_json={"fixture": "controlled PubMed source"},
        content_sha256=f"{topic.id * 100 + revision_number:064x}",
    )
    db.add(evidence_content)
    db.flush()
    db.add(
        MedicalRevisionSource(
            revision_id=revision.id,
            source_id=source.id,
            evidence_content_id=evidence_content.id,
            source_role="PRIMARY",
            sort_order=0,
            relevance_note="DIRECT: Persisted assessment remains unchanged.",
            population_relevance="PEDIATRIC_DIRECT",
            population_note="The controlled fixture directly represents children.",
        )
    )
    db.commit()
    return revision


def approve(db: Session, revision: MedicalKnowledgeRevision, actor: User) -> None:
    MedicalKnowledgeApprovalService(db, clock=lambda: BASE_TIME).approve(
        revision.id, approved_by=actor.id
    )


def parent_read(db: Session, topic: MedicalKnowledgeTopic):
    return PublishedMedicalKnowledgeReadService(db).read_batch(
        PublishedMedicalKnowledgeBatchRequest(
            items=[
                {
                    "disease_group_id": topic.disease_group_id,
                    "weather_factor": topic.weather_factor,
                }
            ]
        )
    )


def revision_snapshot(db: Session, revision_id: int):
    revision = db.get(MedicalKnowledgeRevision, revision_id)
    links = db.query(MedicalRevisionSource).filter_by(revision_id=revision_id).all()
    return {
        "status": revision.status,
        "content": (
            revision.evidence_level,
            revision.evidence_scope,
            revision.short_explanation_vi,
            revision.detailed_explanation_vi,
            revision.limitations_vi,
            revision.generated_by_llm,
            revision.llm_model,
            revision.prompt_version,
        ),
        "approval": (revision.reviewed_by, revision.reviewed_at, revision.review_note),
        "links": [
            (
                link.source_id,
                link.evidence_content_id,
                link.source_role,
                link.sort_order,
                link.relevance_note,
            )
            for link in links
        ],
        "sources": [
            (
                link.source.pmid,
                link.source.abstract_text,
                link.source.raw_metadata_json,
            )
            for link in links
        ],
    }


def test_unpublish_e2e_parent_withdrawal_republish_and_replacement(db):
    staff = add_user(db, "medical-staff", "staff")
    admin = add_user(db, "medical-admin", "admin")
    topic = add_topic(db, "5", "precipitation")
    other_topic = add_topic(db, "6", "humidity")
    other = add_draft(db, other_topic, 1, short="OTHER TOPIC")
    approve(db, other, staff)
    MedicalKnowledgePublicationService(db, clock=lambda: BASE_TIME).publish(
        other.id, published_by=admin.id
    )

    revision1 = add_draft(db, topic, 1, short="REVISION ONE")
    assert revision1.status == "DRAFT"
    updated = MedicalKnowledgeDraftService(db, generator=object()).update_draft(
        revision1.id,
        DraftRevisionPatch(short_explanation_vi="REVISION ONE EDITED"),
    )
    assert updated.short_explanation_vi == "REVISION ONE EDITED"
    assert updated.sources[0].content_kind == "ABSTRACT"
    approve(db, revision1, staff)
    immutable = revision_snapshot(db, revision1.id)
    service = MedicalKnowledgePublicationService(
        db,
        clock=iter(
            [
                BASE_TIME + timedelta(minutes=1),
                BASE_TIME + timedelta(minutes=2),
                BASE_TIME + timedelta(minutes=3),
                BASE_TIME + timedelta(minutes=4),
                BASE_TIME + timedelta(minutes=5),
            ]
        ).__next__,
    )

    service.publish(revision1.id, published_by=admin.id)
    assert [item.revision_id for item in parent_read(db, topic).items] == [revision1.id]

    withdrawn = service.unpublish(revision1.id, unpublished_by=staff.id)
    db.expire_all()
    assert withdrawn.status == "APPROVED"
    assert withdrawn.is_published is False
    assert withdrawn.parent_display_allowed is False
    assert withdrawn.unpublished_by == staff.id
    assert withdrawn.unpublished_by_name == "Actor medical-staff"
    assert db.get(MedicalKnowledgeTopic, topic.id).published_revision_id is None
    assert db.get(MedicalKnowledgeRevision, revision1.id).parent_display_allowed is False
    assert revision_snapshot(db, revision1.id) == immutable
    assert parent_read(db, topic).items == []
    assert [item.revision_id for item in parent_read(db, other_topic).items] == [other.id]

    event_count = db.query(MedicalKnowledgePublication).count()
    with pytest.raises(PublicationConflictError):
        service.unpublish(revision1.id, unpublished_by=staff.id)
    assert db.query(MedicalKnowledgePublication).count() == event_count

    service.publish(revision1.id, published_by=admin.id)
    assert [item.revision_id for item in parent_read(db, topic).items] == [revision1.id]

    revision2 = add_draft(db, topic, 2, short="REVISION TWO")
    approve(db, revision2, staff)
    service.publish(revision2.id, published_by=admin.id)
    with pytest.raises(PublicationConflictError):
        service.unpublish(revision1.id, unpublished_by=staff.id)
    db.expire_all()
    assert db.get(MedicalKnowledgeTopic, topic.id).published_revision_id == revision2.id
    assert db.get(MedicalKnowledgeRevision, revision2.id).parent_display_allowed is True
    assert db.get(MedicalKnowledgeRevision, revision1.id).parent_display_allowed is False

    service.unpublish(revision2.id, unpublished_by=admin.id)
    assert parent_read(db, topic).items == []
    assert db.get(MedicalKnowledgeRevision, revision2.id).status == "APPROVED"
    assert [event.action for event in db.query(MedicalKnowledgePublication).filter_by(
        topic_id=topic.id
    ).order_by(MedicalKnowledgePublication.id)] == [
        "PUBLISH",
        "UNPUBLISH",
        "PUBLISH",
        "PUBLISH",
        "UNPUBLISH",
    ]


def test_only_current_approved_consistent_publication_can_be_unpublished(db):
    staff = add_user(db, "staff", "staff")
    viewer = add_user(db, "viewer", "viewer")
    topic = add_topic(db, "5", "precipitation")
    draft = add_draft(db, topic, 1)
    service = MedicalKnowledgePublicationService(db, clock=lambda: BASE_TIME)

    with pytest.raises(PublicationConflictError):
        service.unpublish(draft.id, unpublished_by=staff.id)
    approve(db, draft, staff)
    with pytest.raises(PublicationConflictError):
        service.unpublish(draft.id, unpublished_by=staff.id)
    with pytest.raises(PublicationValidationError):
        service.unpublish(draft.id, unpublished_by=viewer.id)

    service.publish(draft.id, published_by=staff.id)
    draft.parent_display_allowed = False
    db.commit()
    with pytest.raises(PublicationConflictError):
        service.unpublish(draft.id, unpublished_by=staff.id)
    db.rollback()


def test_wrong_topic_pointer_fails_without_changing_either_topic(db):
    staff = add_user(db, "staff", "staff")
    first_topic = add_topic(db, "5", "precipitation")
    second_topic = add_topic(db, "6", "humidity")
    first = add_draft(db, first_topic, 1)
    approve(db, first, staff)
    second_topic.published_revision_id = first.id
    first.parent_display_allowed = True
    db.commit()

    with pytest.raises(PublicationConflictError):
        MedicalKnowledgePublicationService(db).unpublish(first.id, unpublished_by=staff.id)
    db.expire_all()
    assert db.get(MedicalKnowledgeTopic, first_topic.id).published_revision_id is None
    assert db.get(MedicalKnowledgeTopic, second_topic.id).published_revision_id == first.id
    assert db.get(MedicalKnowledgeRevision, first.id).parent_display_allowed is True
    assert db.query(MedicalKnowledgePublication).count() == 0


def test_unpublish_rolls_back_pointer_flag_and_audit_on_failure(db, monkeypatch):
    staff = add_user(db, "staff", "staff")
    topic = add_topic(db, "5", "precipitation")
    revision = add_draft(db, topic, 1)
    approve(db, revision, staff)
    service = MedicalKnowledgePublicationService(db, clock=lambda: BASE_TIME)
    service.publish(revision.id, published_by=staff.id)

    def fail_audit(**_kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(service.repository, "create_publication", fail_audit)
    with pytest.raises(RuntimeError):
        service.unpublish(revision.id, unpublished_by=staff.id)
    db.expire_all()
    assert db.get(MedicalKnowledgeTopic, topic.id).published_revision_id == revision.id
    assert db.get(MedicalKnowledgeRevision, revision.id).parent_display_allowed is True
    assert [event.action for event in db.query(MedicalKnowledgePublication).all()] == ["PUBLISH"]


def test_publish_unpublish_race_interleavings_remain_consistent(db):
    admin = add_user(db, "admin", "admin")

    topic_a = add_topic(db, "5", "precipitation")
    a1, a2 = add_draft(db, topic_a, 1), add_draft(db, topic_a, 2)
    approve(db, a1, admin)
    approve(db, a2, admin)
    service = MedicalKnowledgePublicationService(db, clock=lambda: BASE_TIME)
    service.publish(a1.id, published_by=admin.id)
    service.publish(a2.id, published_by=admin.id)
    changed = MedicalKnowledgeRepository(db).withdraw_current_publication(
        topic_id=topic_a.id,
        revision_id=a1.id,
        unpublished_at=BASE_TIME,
    )
    assert changed is False
    db.rollback()
    db.expire_all()
    assert db.get(MedicalKnowledgeTopic, topic_a.id).published_revision_id == a2.id
    assert db.get(MedicalKnowledgeRevision, a1.id).parent_display_allowed is False
    assert db.get(MedicalKnowledgeRevision, a2.id).parent_display_allowed is True

    topic_b = add_topic(db, "6", "humidity")
    b1, b2 = add_draft(db, topic_b, 1), add_draft(db, topic_b, 2)
    approve(db, b1, admin)
    approve(db, b2, admin)
    service.publish(b1.id, published_by=admin.id)
    service.unpublish(b1.id, unpublished_by=admin.id)
    service.publish(b2.id, published_by=admin.id)
    db.expire_all()
    assert db.get(MedicalKnowledgeTopic, topic_b.id).published_revision_id == b2.id
    assert db.get(MedicalKnowledgeRevision, b1.id).parent_display_allowed is False
    assert db.get(MedicalKnowledgeRevision, b2.id).parent_display_allowed is True
    assert MedicalKnowledgeRepository(db).count_parent_visible_revisions(topic_b.id) == 1


def test_unpublish_is_database_only_and_calls_no_external_service(db, monkeypatch):
    staff = add_user(db, "staff", "staff")
    topic = add_topic(db, "5", "precipitation")
    revision = add_draft(db, topic, 1)
    approve(db, revision, staff)
    service = MedicalKnowledgePublicationService(db, clock=lambda: BASE_TIME)
    service.publish(revision.id, published_by=staff.id)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Unpublish must not call any external HTTP service")

    monkeypatch.setattr(httpx.Client, "request", forbidden)
    service.unpublish(revision.id, unpublished_by=staff.id)
    assert parent_read(db, topic).items == []


@pytest.fixture
def endpoint_setup(db):
    users = {
        role: add_user(db, f"unpublish-{role}", role)
        for role in ("admin", "staff", "viewer")
    }
    topic = add_topic(db, "5", "precipitation")
    revision = add_draft(db, topic, 1)
    approve(db, revision, users["staff"])
    MedicalKnowledgePublicationService(db, clock=lambda: BASE_TIME).publish(
        revision.id, published_by=users["admin"].id
    )
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, db, users, topic, revision


def auth_header(username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def test_unpublish_endpoint_blocks_anonymous_and_viewer(endpoint_setup):
    client, db, users, topic, revision = endpoint_setup
    path = f"/api/medical-knowledge/revisions/{revision.id}/unpublish"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=auth_header(users["viewer"].username)).status_code == 403
    db.refresh(topic)
    assert topic.published_revision_id == revision.id


@pytest.mark.parametrize("role", ["staff", "admin"])
def test_staff_and_admin_unpublish_with_actor_from_auth_context(endpoint_setup, role):
    client, db, users, topic, revision = endpoint_setup
    response = client.post(
        f"/api/medical-knowledge/revisions/{revision.id}/unpublish",
        headers=auth_header(users[role].username),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert response.json()["is_published"] is False
    assert response.json()["parent_display_allowed"] is False
    assert response.json()["unpublished_by"] == users[role].id
    assert response.json()["unpublished_by_name"] == f"Actor unpublish-{role}"
    db.refresh(topic)
    db.refresh(revision)
    assert topic.published_revision_id is None
    assert revision.status == "APPROVED"
    assert revision.parent_display_allowed is False
    event = db.query(MedicalKnowledgePublication).order_by(
        MedicalKnowledgePublication.id.desc()
    ).first()
    assert event.action == "UNPUBLISH"
    assert event.published_by == users[role].id


def test_unpublish_migration_upgrade_twice_and_downgrade_preserve_history():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE medical_knowledge_publications ("
            "id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL, revision_id INTEGER NOT NULL, "
            "published_by INTEGER NULL, published_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO medical_knowledge_publications "
            "(id, topic_id, revision_id, published_by, published_at) "
            "VALUES (1, 7, 21, 3, '2026-08-23 10:00:00')"
        )

    upgrade(engine)
    upgrade(engine)
    assert "action" in {
        column["name"] for column in inspect(engine).get_columns("medical_knowledge_publications")
    }
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT action FROM medical_knowledge_publications WHERE id=1"
        ).scalar_one() == "PUBLISH"

    downgrade(engine)
    assert "action" not in {
        column["name"] for column in inspect(engine).get_columns("medical_knowledge_publications")
    }
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT revision_id FROM medical_knowledge_publications WHERE id=1"
        ).scalar_one() == 21
    engine.dispose()
