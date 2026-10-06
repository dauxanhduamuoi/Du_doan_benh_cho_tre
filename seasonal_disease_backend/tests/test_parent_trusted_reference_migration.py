from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.medical_knowledge_models import (
    MedicalEvidenceSource, MedicalKnowledgePublication, MedicalKnowledgeRevision,
    MedicalKnowledgeTopic, MedicalKnowledgeTopicSource, MedicalRevisionSource,
)
from app.models import User
from app.parent_trusted_reference_models import (
    ParentTrustedReferenceApproval as Approval,
    ParentTrustedReferenceApprovalEvent as ApprovalEvent,
)
from app.repositories.parent_trusted_reference_repository import ParentTrustedReferenceRepository
from app.services.area_service import ensure_area_schema
from migrations.v018_parent_trusted_reference_curation import downgrade, upgrade
from test_parent_trusted_reference_persistence import make_engine, offline_boundaries  # noqa: F401 - autouse offline fixture


NEW_TABLES = {Approval.__tablename__, ApprovalEvent.__tablename__}


def legacy_schema(engine):
    # Reproduce the registered pre-v018 schema without copying any local DB.
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.tables.values() if table.name not in NEW_TABLES])
    ensure_area_schema(engine)
    assert len(inspect(engine).get_table_names()) == 31


def legacy_rows(engine):
    snapshot = {}
    with engine.connect() as connection:
        for name in sorted(set(inspect(engine).get_table_names()) - NEW_TABLES):
            table = Base.metadata.tables[name]
            snapshot[name] = connection.execute(select(table).order_by(*table.primary_key.columns)).all()
    return snapshot


def assert_empty_curation(engine):
    assert NEW_TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Approval)) == 0
        assert connection.scalar(select(func.count()).select_from(ApprovalEvent)) == 0


def column_signature(engine, name):
    # Inspector type instances are distinct objects on each call; compare DDL
    # properties rather than Python object identity.
    return [(item["name"], str(item["type"]), item["nullable"], item["default"], item["primary_key"])
            for item in inspect(engine).get_columns(name)]


def test_fresh_sqlite_database_full_existing_migration_chain_then_v018():
    engine = make_engine()
    assert inspect(engine).get_table_names() == []
    legacy_schema(engine)
    directory = Path(__file__).resolve().parents[1] / "migrations"
    for path in sorted(directory.glob("v[0-9][0-9][0-9]_*.py")):
        if int(path.name[1:4]) < 18:
            importlib.import_module(f"migrations.{path.stem}").upgrade(engine)
    before = legacy_rows(engine)
    upgrade(engine)
    assert len(inspect(engine).get_table_names()) == 33
    assert legacy_rows(engine) == before
    assert_empty_curation(engine)
    upgrade(engine)
    assert legacy_rows(engine) == before
    assert_empty_curation(engine)
    engine.dispose()


def test_current_31_table_database_preserves_published_legacy_data_without_backfill():
    engine = make_engine()
    legacy_schema(engine)
    with Session(engine) as db:
        user = User(username="legacy-staff", password_hash="fixture-only", role="staff")
        topic = MedicalKnowledgeTopic(disease_group_id="5", weather_factor="humidity", factor_type="WEATHER", factor_key="humidity")
        source = MedicalEvidenceSource(source_type="PUBMED", provider_id="PUBMED", external_id="12345", title="Legacy published source")
        db.add_all([user, topic, source])
        db.flush()
        revision = MedicalKnowledgeRevision(
            topic_id=topic.id, revision_number=1, evidence_level="INSUFFICIENT", evidence_scope="PARTIAL_GROUP",
            short_explanation_vi="Nội dung legacy ngắn", detailed_explanation_vi="Nội dung legacy chi tiết",
            limitations_vi="Giới hạn legacy", status="APPROVED", parent_display_allowed=True, reviewed_by=user.id,
        )
        db.add(revision)
        db.flush()
        topic.published_revision_id = revision.id
        db.add_all([
            MedicalKnowledgeTopicSource(topic_id=topic.id, source_id=source.id, added_by=user.id),
            MedicalRevisionSource(revision_id=revision.id, source_id=source.id, source_role="PRIMARY"),
            MedicalKnowledgePublication(topic_id=topic.id, revision_id=revision.id, action="PUBLISH", published_by=user.id, published_at=revision.created_at),
        ])
        db.commit()
    before = legacy_rows(engine)
    original_tables = set(inspect(engine).get_table_names())
    original_columns = {name: column_signature(engine, name) for name in original_tables}
    upgrade(engine)
    upgrade(engine)
    assert set(inspect(engine).get_table_names()) == original_tables | NEW_TABLES
    assert {name: column_signature(engine, name) for name in original_tables} == original_columns
    assert legacy_rows(engine) == before
    assert_empty_curation(engine)
    downgrade(engine)
    downgrade(engine)
    assert set(inspect(engine).get_table_names()) == original_tables
    assert legacy_rows(engine) == before
    upgrade(engine)
    assert_empty_curation(engine)
    engine.dispose()


def test_connection_upgrade_leaves_caller_transaction_open():
    engine = make_engine()
    legacy_schema(engine)
    with engine.begin() as connection:
        upgrade(connection)
        assert connection.in_transaction()
        upgrade(connection)
        assert connection.in_transaction()
    assert_empty_curation(engine)
    engine.dispose()


def test_isolated_actual_startup_registers_v018_and_repeats_without_changing_curation(tmp_path, monkeypatch):
    import app.database as database_module
    import app.main as main_module

    engine = make_engine(f"sqlite:///{(tmp_path / 'curation-startup.db').as_posix()}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "SessionLocal", sessions)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "SessionLocal", sessions)
    monkeypatch.setattr(main_module, "WEATHER_AI_V3_PRELOAD", False)
    monkeypatch.setattr(main_module, "recover_interrupted_auto_medical_knowledge_jobs", lambda: None)

    async def idle_worker(stop_event):
        await stop_event.wait()  # No actual Auto worker/provider work in this test.

    monkeypatch.setattr(main_module, "run_auto_medical_knowledge_worker", idle_worker)
    calls = []

    def record_upgrade(bind):
        assert bind is engine
        calls.append(True)
        upgrade(bind)

    monkeypatch.setattr(main_module, "upgrade_parent_trusted_reference_curation", record_upgrade)
    with TestClient(main_module.app) as client:
        assert client.get("/").status_code == 200
        assert_empty_curation(engine)
    with sessions() as db:
        topic = MedicalKnowledgeTopic(disease_group_id="5", weather_factor="humidity", factor_type="WEATHER", factor_key="humidity")
        source = MedicalEvidenceSource(source_type="OTHER", title="Startup retention fixture")
        db.add_all([topic, source])
        db.flush()
        repository = ParentTrustedReferenceRepository(db)
        row = repository.create_draft(topic_id=topic.id, source_id=source.id)
        repository.append_event(approval_id=row.id, action="CREATE_DRAFT", from_status=None, to_status="DRAFT", resulting_version=1)
        db.commit()
    with TestClient(main_module.app) as client:
        assert client.get("/").status_code == 200
    assert len(calls) == 2
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Approval)) == 1
        assert db.scalar(select(func.count()).select_from(ApprovalEvent)) == 1
    engine.dispose()
