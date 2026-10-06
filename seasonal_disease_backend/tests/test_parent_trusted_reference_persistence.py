from __future__ import annotations

import socket
import urllib.request
from datetime import datetime

import httpx
import pytest
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.database import Base
from app.medical_knowledge_models import MedicalEvidenceContent, MedicalEvidenceSource, MedicalKnowledgeTopic
from app.models import User
from app.parent_trusted_reference_models import (
    PARENT_REFERENCE_ACTIONS, PARENT_REFERENCE_STATUSES,
    ParentTrustedReferenceApproval as Approval,
    ParentTrustedReferenceApprovalEvent as ApprovalEvent,
)
from app.repositories.parent_trusted_reference_repository import ParentTrustedReferenceRepository


@pytest.fixture(autouse=True)
def offline_boundaries(monkeypatch):
    original_connect = socket.socket.connect

    def forbidden(*_args, **_kwargs):
        pytest.fail("Persistence/migration tests must not call external network")

    def loopback_only(connection, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(connection, address)  # Windows asyncio socketpair only
        forbidden()

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    for target, name in [
        (socket, "create_connection"), (socket.socket, "connect_ex"),
        (urllib.request, "urlopen"), (httpx.HTTPTransport, "handle_request"),
        (httpx.AsyncHTTPTransport, "handle_async_request"),
    ]:
        monkeypatch.setattr(target, name, forbidden)


def make_engine(url="sqlite://", **kwargs):
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture
def db():
    engine = make_engine()
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(username="curator", password_hash="fixture-only", role="staff", full_name="Người duyệt")
        topic = MedicalKnowledgeTopic(disease_group_id="5", weather_factor="humidity", factor_type="WEATHER", factor_key="humidity")
        source = MedicalEvidenceSource(source_type="OTHER", title="Tài liệu thử nghiệm")
        session.add_all([user, topic, source])
        session.flush()
        proof = MedicalEvidenceContent(
            source_id=source.id, content_kind="ABSTRACT", content_origin="NCBI_PUBMED",
            evidence_text="Test fixture evidence", retrieved_at=datetime(2025, 1, 1), content_sha256="a" * 64,
        )
        session.add(proof)
        session.commit()
        session.info["fixture_ids"] = dict(topic_id=topic.id, source_id=source.id, actor_id=user.id, proof_id=proof.id)
        yield session
    engine.dispose()


def draft(db, **overrides):
    ids = db.info["fixture_ids"]
    values = dict(topic_id=ids["topic_id"], source_id=ids["source_id"], created_by=ids["actor_id"])
    values.update(overrides)
    return ParentTrustedReferenceRepository(db).create_draft(**values)


def append_event(db, parent_id, **overrides):
    values = dict(approval_id=parent_id, action="CREATE_DRAFT", from_status=None, to_status="DRAFT",
                  resulting_version=1, actor_user_id=db.info["fixture_ids"]["actor_id"])
    values.update(overrides)
    return ParentTrustedReferenceRepository(db).append_event(**values)


def test_draft_defaults_optional_proof_and_no_implicit_approval_or_event(db):
    row = draft(db)
    assert (row.status, row.version, row.sort_order) == ("DRAFT", 1, 0)
    assert row.created_at and row.updated_at
    assert row.approved_at is None and row.revoked_at is None
    assert row.evidence_content_id is None and row.identity_snapshot_json is None
    assert db.scalar(select(Approval.identity_snapshot_json.is_(None)).where(Approval.id == row.id))
    assert ParentTrustedReferenceRepository(db).list_events(row.id) == []
    # OTHER/no proof is permitted as a draft; no source trust is inferred here.


def test_unique_topic_source_pair(db):
    draft(db)
    with pytest.raises(IntegrityError):
        draft(db)
    db.rollback()


@pytest.mark.parametrize("status", PARENT_REFERENCE_STATUSES)
def test_storage_vocabulary_is_separate_from_legacy_publication(db, status):
    row = draft(db)
    row.status = status  # Storage only, not a Phase B approval operation.
    db.flush()
    assert row.status == status


@pytest.mark.parametrize("field,value", [
    ("status", "PUBLISHED"), ("status", "UNKNOWN"), ("status", None),
    ("sort_order", -1), ("version", 0), ("version", -1),
    ("identity_sha256", "a" * 63), ("identity_sha256", "a" * 65),
])
def test_approval_constraints_reject_invalid_storage(db, field, value):
    row = draft(db)
    setattr(row, field, value)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_snapshot_hash_proof_and_unicode_event_roundtrip(db):
    snapshot = {"selector": {"disease_group_id": "5", "factor_value": None}, "title": "Hướng dẫn cho trẻ"}
    row = draft(db, evidence_content_id=db.info["fixture_ids"]["proof_id"],
                identity_snapshot_json=snapshot, identity_sha256="b" * 64, policy_version="v1")
    history = append_event(db, row.id, review_note="Đọc thêm cho phụ huynh — không thay xếp hạng",
                           identity_snapshot_json=snapshot, identity_sha256="b" * 64, policy_version="v1")
    db.commit()
    db.expunge_all()
    loaded = ParentTrustedReferenceRepository(db).get_by_id(row.id)
    assert loaded.identity_snapshot_json == snapshot
    assert loaded.identity_sha256 == "b" * 64
    assert ParentTrustedReferenceRepository(db).list_events(row.id)[0].review_note == history.review_note


@pytest.mark.parametrize("field", ["topic_id", "source_id", "evidence_content_id", "created_by", "approved_by", "revoked_by"])
def test_approval_foreign_keys(db, field):
    row = draft(db)
    setattr(row, field, 999999)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize("field,value", [
    ("approval_id", 999999), ("actor_user_id", 999999), ("action", "PUBLISH"),
    ("from_status", "PUBLISHED"), ("to_status", "PUBLISHED"),
    ("resulting_version", 0), ("resulting_version", -1),
    ("identity_sha256", "a" * 63), ("identity_sha256", "a" * 65),
    ("review_note", "x" * 1001),
])
def test_event_constraints(db, field, value):
    row = draft(db)
    with pytest.raises(IntegrityError):
        append_event(db, row.id, **{field: value})
    db.rollback()


@pytest.mark.parametrize("action", PARENT_REFERENCE_ACTIONS)
def test_event_action_vocabulary(db, action):
    row = draft(db)
    assert append_event(db, row.id, action=action).action == action


def test_event_version_is_unique_within_approval(db):
    row = draft(db)
    append_event(db, row.id)
    with pytest.raises(IntegrityError):
        append_event(db, row.id)
    db.rollback()


@pytest.mark.parametrize("target", ["topic", "source", "proof", "actor", "approval"])
def test_no_cascade_can_erase_reference_state_or_history(db, target):
    ids = db.info["fixture_ids"]
    row = draft(db, evidence_content_id=ids["proof_id"])
    append_event(db, row.id)
    db.commit()
    model, key = {
        "topic": (MedicalKnowledgeTopic, ids["topic_id"]),
        "source": (MedicalEvidenceSource, ids["source_id"]),
        "proof": (MedicalEvidenceContent, ids["proof_id"]), "actor": (User, ids["actor_id"]),
        "approval": (Approval, row.id),
    }[target]
    with pytest.raises(IntegrityError):
        db.execute(delete(model).where(model.id == key))
        db.commit()
    db.rollback()
    assert ParentTrustedReferenceRepository(db).get_by_id(row.id)
    assert len(ParentTrustedReferenceRepository(db).list_events(row.id)) == 1


def test_repository_reads_order_by_topic_source_and_event_version(db):
    ids = db.info["fixture_ids"]
    repository = ParentTrustedReferenceRepository(db)
    first = draft(db, sort_order=2)
    second_source = MedicalEvidenceSource(source_type="OTHER", title="Nguồn thứ hai")
    other_topic = MedicalKnowledgeTopic(disease_group_id="6", weather_factor="humidity", factor_type="WEATHER", factor_key="humidity")
    db.add_all([second_source, other_topic])
    db.flush()
    second = repository.create_draft(topic_id=ids["topic_id"], source_id=second_source.id, sort_order=0)
    repository.create_draft(topic_id=other_topic.id, source_id=ids["source_id"])
    append_event(db, first.id, resulting_version=2)
    append_event(db, first.id, resulting_version=1)
    assert repository.get_by_topic_source(ids["topic_id"], ids["source_id"]).id == first.id
    assert [row.id for row in repository.list_for_topic(ids["topic_id"])] == [second.id, first.id]
    assert [row.resulting_version for row in repository.list_events(first.id)] == [1, 2]
    assert repository.get_by_id(999999) is None
    assert repository.get_by_topic_source(999999, ids["source_id"]) is None
    assert repository.list_for_topic(999999) == []
    assert repository.list_events(999999) == []


def test_repository_writes_do_not_commit_and_caller_can_rollback_atomically(db, monkeypatch):
    monkeypatch.setattr(db, "commit", lambda: pytest.fail("Repository must not commit"))
    row = draft(db)
    append_event(db, row.id)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Approval)) == 0
    assert db.scalar(select(func.count()).select_from(ApprovalEvent)) == 0


def test_reads_never_flush_pending_changes(db, monkeypatch):
    row = draft(db)
    append_event(db, row.id)
    db.commit()
    db.expunge_all()
    pending = MedicalEvidenceSource(source_type="OTHER", title="Pending unrelated change")
    db.add(pending)
    monkeypatch.setattr(db, "flush", lambda *_a, **_k: pytest.fail("Pure read must not flush"))
    repository = ParentTrustedReferenceRepository(db)
    assert repository.get_by_id(row.id)
    assert repository.get_by_topic_source(row.topic_id, row.source_id)
    assert repository.list_for_topic(row.topic_id)
    assert repository.list_events(row.id)
    assert pending in db.new
    db.rollback()


def test_schema_and_indexes_compile_portably_for_mssql():
    for model in (Approval, ApprovalEvent):
        table = model.__table__
        ddl = str(CreateTable(table).compile(dialect=mssql.dialect()))
        assert "IDENTITY" in ddl and "NVARCHAR(max)" in ddl  # JSON abstraction
        assert "LEN(identity_sha256) = 64" in ddl
        assert "CASCADE" not in ddl and "ON DELETE NO ACTION" in ddl
        assert all(constraint.name for constraint in table.constraints)
        assert all(fk.ondelete == "NO ACTION" for fk in table.foreign_key_constraints)
        for index in table.indexes:
            index_ddl = str(CreateIndex(index).compile(dialect=mssql.dialect()))
            assert "WHERE" not in index_ddl and "coalesce" not in index_ddl.lower()
    event_ddl = str(CreateTable(ApprovalEvent.__table__).compile(dialect=mssql.dialect()))
    assert "NVARCHAR(1000)" in event_ddl
    assert "ROWVERSION" not in event_ddl.upper()
