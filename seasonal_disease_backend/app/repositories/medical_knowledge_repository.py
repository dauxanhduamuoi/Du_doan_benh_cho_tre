from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.medical_knowledge_models import (
    MedicalEvidenceSource,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalRevisionSource,
)
from app.medical_knowledge_schemas import (
    MedicalEvidenceSourceCreate,
    MedicalRevisionCreate,
    MedicalRevisionSourceCreate,
    MedicalTopicCreate,
)


class MedicalKnowledgeRepository:
    """Transaction-neutral persistence primitives for Medical Knowledge V1."""

    def __init__(self, db: Session):
        self.db = db

    def create_topic(self, data: MedicalTopicCreate) -> MedicalKnowledgeTopic:
        topic = MedicalKnowledgeTopic(**data.model_dump())
        self.db.add(topic)
        self.db.flush()
        return topic

    def get_topic(self, topic_id: int) -> MedicalKnowledgeTopic | None:
        return self.db.get(MedicalKnowledgeTopic, topic_id)

    def get_topic_by_group_factor(
        self, disease_group_id: str, weather_factor: str
    ) -> MedicalKnowledgeTopic | None:
        return self.db.scalar(
            select(MedicalKnowledgeTopic).where(
                MedicalKnowledgeTopic.disease_group_id == disease_group_id,
                MedicalKnowledgeTopic.weather_factor == weather_factor,
            )
        )

    def list_topics(self, *, offset: int = 0, limit: int = 100) -> list[MedicalKnowledgeTopic]:
        statement = select(MedicalKnowledgeTopic).order_by(MedicalKnowledgeTopic.id).offset(offset).limit(limit)
        return list(self.db.scalars(statement))

    def create_revision(self, data: MedicalRevisionCreate) -> MedicalKnowledgeRevision:
        revision = MedicalKnowledgeRevision(**data.model_dump())
        self.db.add(revision)
        self.db.flush()
        return revision

    def get_revision(self, revision_id: int) -> MedicalKnowledgeRevision | None:
        return self.db.get(MedicalKnowledgeRevision, revision_id)

    def get_revision_with_sources(self, revision_id: int) -> MedicalKnowledgeRevision | None:
        statement = (
            select(MedicalKnowledgeRevision)
            .options(
                selectinload(MedicalKnowledgeRevision.topic),
                selectinload(MedicalKnowledgeRevision.source_links).selectinload(
                    MedicalRevisionSource.source
                ),
            )
            .where(MedicalKnowledgeRevision.id == revision_id)
        )
        return self.db.scalar(statement)

    def list_revisions(self, topic_id: int) -> list[MedicalKnowledgeRevision]:
        statement = (
            select(MedicalKnowledgeRevision)
            .where(MedicalKnowledgeRevision.topic_id == topic_id)
            .order_by(MedicalKnowledgeRevision.revision_number)
        )
        return list(self.db.scalars(statement))

    def list_revisions_desc(self, topic_id: int) -> list[MedicalKnowledgeRevision]:
        statement = (
            select(MedicalKnowledgeRevision)
            .where(MedicalKnowledgeRevision.topic_id == topic_id)
            .order_by(MedicalKnowledgeRevision.revision_number.desc())
        )
        return list(self.db.scalars(statement))

    def next_revision_number(self, topic_id: int) -> int:
        current = self.db.scalar(
            select(func.max(MedicalKnowledgeRevision.revision_number)).where(
                MedicalKnowledgeRevision.topic_id == topic_id
            )
        )
        return int(current or 0) + 1

    def set_published_revision(self, topic_id: int, revision_id: int | None) -> MedicalKnowledgeTopic:
        topic = self.get_topic(topic_id)
        if topic is None:
            raise ValueError("Topic does not exist")
        if revision_id is not None:
            revision = self.get_revision(revision_id)
            if revision is None or revision.topic_id != topic_id:
                raise ValueError("Published revision must belong to the same topic")
        topic.published_revision_id = revision_id
        self.db.flush()
        return topic

    def create_source(self, data: MedicalEvidenceSourceCreate) -> MedicalEvidenceSource:
        source = MedicalEvidenceSource(**data.model_dump())
        self.db.add(source)
        self.db.flush()
        return source

    def get_source(self, source_id: int) -> MedicalEvidenceSource | None:
        return self.db.get(MedicalEvidenceSource, source_id)

    def get_sources_by_ids(self, source_ids: list[int]) -> list[MedicalEvidenceSource]:
        if not source_ids:
            return []
        sources = list(
            self.db.scalars(
                select(MedicalEvidenceSource).where(MedicalEvidenceSource.id.in_(source_ids))
            )
        )
        by_id = {source.id: source for source in sources}
        return [by_id[source_id] for source_id in source_ids if source_id in by_id]

    def get_source_by_pmid(self, pmid: str) -> MedicalEvidenceSource | None:
        return self.db.scalar(
            select(MedicalEvidenceSource).where(
                MedicalEvidenceSource.source_type == "PUBMED",
                MedicalEvidenceSource.pmid == pmid,
            )
        )

    def list_sources(
        self, *, query: str | None = None, offset: int = 0, limit: int = 100
    ) -> list[MedicalEvidenceSource]:
        statement = select(MedicalEvidenceSource)
        if query:
            statement = statement.where(MedicalEvidenceSource.title.ilike(f"%{query}%"))
        statement = statement.order_by(MedicalEvidenceSource.id).offset(offset).limit(limit)
        return list(self.db.scalars(statement))

    def attach_source(self, data: MedicalRevisionSourceCreate) -> MedicalRevisionSource:
        link = MedicalRevisionSource(**data.model_dump())
        self.db.add(link)
        self.db.flush()
        return link

    def list_sources_for_revision(self, revision_id: int) -> list[MedicalRevisionSource]:
        statement = (
            select(MedicalRevisionSource)
            .options(selectinload(MedicalRevisionSource.source))
            .where(MedicalRevisionSource.revision_id == revision_id)
            .order_by(MedicalRevisionSource.sort_order, MedicalRevisionSource.source_id)
        )
        return list(self.db.scalars(statement))
