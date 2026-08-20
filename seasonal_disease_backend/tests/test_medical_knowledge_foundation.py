from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import User
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.medical_knowledge_schemas import (
    MedicalEvidenceSourceCreate,
    MedicalRevisionCreate,
    MedicalRevisionSourceCreate,
    MedicalTopicCreate,
)
from migrations.v001_medical_knowledge_v1 import downgrade, upgrade


TABLES = {
    "medical_knowledge_topics",
    "medical_knowledge_revisions",
    "medical_evidence_sources",
    "medical_revision_sources",
}


def make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture
def db():
    engine = make_engine()
    User.__table__.create(engine)
    upgrade(engine)
    with Session(engine) as session:
        yield session
    downgrade(engine)
    User.__table__.drop(engine)
    engine.dispose()


def revision_data(topic_id: int, revision_number: int = 1, **overrides):
    values = {
        "topic_id": topic_id,
        "revision_number": revision_number,
        "evidence_level": "SUPPORTED",
        "evidence_scope": "WHOLE_GROUP",
        "short_explanation_vi": "Giải thích ngắn",
        "detailed_explanation_vi": "Giải thích chi tiết",
        "limitations_vi": "Còn giới hạn bằng chứng",
    }
    values.update(overrides)
    return MedicalRevisionCreate(**values)


def test_migration_upgrade_downgrade_reupgrade():
    engine = make_engine()
    User.__table__.create(engine)

    upgrade(engine)
    assert TABLES <= set(inspect(engine).get_table_names())
    downgrade(engine)
    assert TABLES.isdisjoint(inspect(engine).get_table_names())
    upgrade(engine)
    assert TABLES <= set(inspect(engine).get_table_names())

    downgrade(engine)
    User.__table__.drop(engine)
    engine.dispose()


def test_create_and_find_topic_with_nullable_published_revision(db):
    repository = MedicalKnowledgeRepository(db)
    topic = repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="precipitation"))
    db.commit()

    loaded = repository.get_topic_by_group_factor("A09", "precipitation")
    assert loaded is not None
    assert loaded.id == topic.id
    assert loaded.published_revision_id is None
    assert repository.get_topic(topic.id) is not None
    assert repository.list_topics() == [loaded]


def test_duplicate_topic_group_and_factor_is_rejected(db):
    repository = MedicalKnowledgeRepository(db)
    repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="humidity"))
    db.commit()

    with pytest.raises(IntegrityError):
        repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="humidity"))
    db.rollback()


def test_one_group_can_have_multiple_weather_factor_topics(db):
    repository = MedicalKnowledgeRepository(db)
    for factor in ("precipitation", "temperature", "humidity"):
        repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor=factor))
    db.commit()

    assert {topic.weather_factor for topic in repository.list_topics()} == {
        "precipitation",
        "temperature",
        "humidity",
    }


def test_multiple_revisions_and_relationship_loading(db):
    repository = MedicalKnowledgeRepository(db)
    topic = repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="temperature"))
    first = repository.create_revision(revision_data(topic.id, 1))
    second = repository.create_revision(revision_data(topic.id, 2, status="APPROVED"))
    db.commit()
    db.expire_all()

    loaded = repository.list_revisions(topic.id)
    assert [revision.revision_number for revision in loaded] == [1, 2]
    assert first.topic.id == topic.id
    assert second.topic.id == topic.id


def test_duplicate_revision_number_is_rejected(db):
    repository = MedicalKnowledgeRepository(db)
    topic = repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="wind"))
    repository.create_revision(revision_data(topic.id, 1))
    db.commit()

    with pytest.raises(IntegrityError):
        repository.create_revision(revision_data(topic.id, 1))
    db.rollback()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("evidence_level", "UNKNOWN"), ("evidence_scope", "ONE_DISEASE"), ("status", "PUBLISHED")],
)
def test_invalid_revision_vocabulary_is_rejected(field, invalid_value):
    with pytest.raises(ValidationError):
        revision_data(1, **{field: invalid_value})


def test_create_get_and_search_source(db):
    repository = MedicalKnowledgeRepository(db)
    source = repository.create_source(
        MedicalEvidenceSourceCreate(
            source_type="PUBMED",
            pmid="12345",
            title="Weather and pediatric disease groups",
            raw_metadata_json={"provider": "fixture"},
        )
    )
    db.commit()

    assert repository.get_source(source.id).pmid == "12345"
    assert repository.list_sources(query="pediatric") == [source]


def test_many_to_many_sources_and_duplicate_link_constraint(db):
    repository = MedicalKnowledgeRepository(db)
    topic = repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="humidity"))
    revision_one = repository.create_revision(revision_data(topic.id, 1))
    revision_two = repository.create_revision(revision_data(topic.id, 2))
    source_one = repository.create_source(MedicalEvidenceSourceCreate(source_type="WHO", title="WHO source"))
    source_two = repository.create_source(MedicalEvidenceSourceCreate(source_type="CDC", title="CDC source"))
    repository.attach_source(
        MedicalRevisionSourceCreate(revision_id=revision_one.id, source_id=source_one.id, source_role="PRIMARY")
    )
    repository.attach_source(
        MedicalRevisionSourceCreate(
            revision_id=revision_one.id, source_id=source_two.id, source_role="SUPPORTING", sort_order=1
        )
    )
    repository.attach_source(
        MedicalRevisionSourceCreate(revision_id=revision_two.id, source_id=source_one.id, source_role="SUPPORTING")
    )
    db.commit()

    links = repository.list_sources_for_revision(revision_one.id)
    assert [link.source.title for link in links] == ["WHO source", "CDC source"]
    assert len(source_one.revision_links) == 2
    db.expunge_all()

    with pytest.raises(IntegrityError):
        repository.attach_source(
            MedicalRevisionSourceCreate(revision_id=revision_one.id, source_id=source_one.id, source_role="PRIMARY")
        )
    db.rollback()


def test_published_revision_must_belong_to_same_topic(db):
    repository = MedicalKnowledgeRepository(db)
    first_topic = repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="temperature"))
    second_topic = repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="humidity"))
    revision = repository.create_revision(revision_data(first_topic.id))
    db.commit()

    assert repository.set_published_revision(first_topic.id, revision.id).published_revision_id == revision.id
    with pytest.raises(ValueError, match="same topic"):
        repository.set_published_revision(second_topic.id, revision.id)


def test_foreign_keys_are_enforced_and_published_pointer_is_set_null(db):
    repository = MedicalKnowledgeRepository(db)
    with pytest.raises(IntegrityError):
        repository.create_revision(revision_data(9999))
    db.rollback()

    topic = repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="temperature"))
    revision = repository.create_revision(revision_data(topic.id))
    db.commit()
    repository.set_published_revision(topic.id, revision.id)
    db.commit()

    db.delete(revision)
    db.commit()
    db.refresh(topic)
    assert topic.published_revision_id is None


def test_deleting_topic_does_not_delete_shared_evidence_source(db):
    repository = MedicalKnowledgeRepository(db)
    topic = repository.create_topic(MedicalTopicCreate(disease_group_id="A09", weather_factor="wind"))
    revision = repository.create_revision(revision_data(topic.id))
    source = repository.create_source(MedicalEvidenceSourceCreate(source_type="OTHER", title="Shared source"))
    repository.attach_source(
        MedicalRevisionSourceCreate(revision_id=revision.id, source_id=source.id, source_role="PRIMARY")
    )
    db.commit()
    source_id = source.id

    db.delete(topic)
    db.commit()

    assert repository.get_source(source_id) is not None
