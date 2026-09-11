from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select, tuple_, update
from sqlalchemy.orm import Session, selectinload

from app.medical_knowledge_models import (
    MedicalEvidenceSource,
    MedicalEvidenceContent,
    MedicalKnowledgePublication,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalKnowledgeTopicSource,
    MedicalRevisionSource,
)
from app.medical_knowledge_schemas import (
    MedicalEvidenceSourceCreate,
    MedicalEvidenceContentCreate,
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

    def get_topic_for_update(self, topic_id: int) -> MedicalKnowledgeTopic | None:
        return self.db.scalar(
            select(MedicalKnowledgeTopic)
            .where(MedicalKnowledgeTopic.id == topic_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def get_topic_by_group_factor(
        self, disease_group_id: str, weather_factor: str
    ) -> MedicalKnowledgeTopic | None:
        return self.get_topic_by_selector(
            disease_group_id, "WEATHER", weather_factor, None
        )

    def get_topic_by_selector(
        self,
        disease_group_id: str,
        factor_type: str,
        factor_key: str,
        factor_value: str | None,
    ) -> MedicalKnowledgeTopic | None:
        return self.db.scalar(
            select(MedicalKnowledgeTopic).where(
                MedicalKnowledgeTopic.disease_group_id == disease_group_id,
                MedicalKnowledgeTopic.factor_type == factor_type,
                MedicalKnowledgeTopic.factor_key == factor_key,
                MedicalKnowledgeTopic.factor_value.is_(None)
                if factor_value is None
                else MedicalKnowledgeTopic.factor_value == factor_value,
            )
        )

    def create_topic_source(
        self, *, topic_id: int, source_id: int, added_by: int | None
    ) -> MedicalKnowledgeTopicSource:
        link = MedicalKnowledgeTopicSource(
            topic_id=topic_id,
            source_id=source_id,
            added_by=added_by,
        )
        self.db.add(link)
        self.db.flush()
        return link

    def get_topic_source(
        self, topic_id: int, source_id: int
    ) -> MedicalKnowledgeTopicSource | None:
        return self.db.get(MedicalKnowledgeTopicSource, (topic_id, source_id))

    def get_topic_source_ids(self, topic_id: int) -> set[int]:
        return set(
            self.db.scalars(
                select(MedicalKnowledgeTopicSource.source_id).where(
                    MedicalKnowledgeTopicSource.topic_id == topic_id
                )
            )
        )

    def list_topic_sources(self, topic_id: int) -> list[MedicalKnowledgeTopicSource]:
        statement = (
            select(MedicalKnowledgeTopicSource)
            .options(selectinload(MedicalKnowledgeTopicSource.source))
            .where(MedicalKnowledgeTopicSource.topic_id == topic_id)
            .order_by(
                MedicalKnowledgeTopicSource.added_at,
                MedicalKnowledgeTopicSource.source_id,
            )
        )
        return list(self.db.scalars(statement))

    def list_topics(self, *, offset: int = 0, limit: int = 100) -> list[MedicalKnowledgeTopic]:
        statement = select(MedicalKnowledgeTopic).order_by(MedicalKnowledgeTopic.id).offset(offset).limit(limit)
        return list(self.db.scalars(statement))

    def get_parent_published_topics(
        self, selectors: list[tuple[str, str, str, str | None]]
    ) -> list[MedicalKnowledgeTopic]:
        """Load current eligible revisions and citation sources for a bounded selector batch."""

        if not selectors:
            return []
        normalized = [
            (disease, factor_type, factor_key, factor_value or "")
            for disease, factor_type, factor_key, factor_value in selectors
        ]
        statement = (
            select(MedicalKnowledgeTopic)
            .join(
                MedicalKnowledgeRevision,
                MedicalKnowledgeTopic.published_revision_id == MedicalKnowledgeRevision.id,
            )
            .options(
                selectinload(MedicalKnowledgeTopic.published_revision)
                .selectinload(MedicalKnowledgeRevision.source_links)
                .selectinload(MedicalRevisionSource.source),
                selectinload(MedicalKnowledgeTopic.published_revision)
                .selectinload(MedicalKnowledgeRevision.source_links)
                .selectinload(MedicalRevisionSource.evidence_content),
            )
            .where(
                tuple_(
                    MedicalKnowledgeTopic.disease_group_id,
                    MedicalKnowledgeTopic.factor_type,
                    MedicalKnowledgeTopic.factor_key,
                    func.coalesce(MedicalKnowledgeTopic.factor_value, ""),
                ).in_(normalized),
                MedicalKnowledgeRevision.topic_id == MedicalKnowledgeTopic.id,
                MedicalKnowledgeRevision.status == "APPROVED",
                MedicalKnowledgeRevision.parent_display_allowed.is_(True),
            )
        )
        return list(self.db.scalars(statement).unique())

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
                selectinload(MedicalKnowledgeRevision.source_links).selectinload(
                    MedicalRevisionSource.evidence_content
                ),
            )
            .where(MedicalKnowledgeRevision.id == revision_id)
        )
        return self.db.scalar(statement)

    def approve_revision_if_draft(
        self, revision_id: int, *, approved_by: int, approved_at: datetime
    ) -> bool:
        result = self.db.execute(
            update(MedicalKnowledgeRevision)
            .where(
                MedicalKnowledgeRevision.id == revision_id,
                MedicalKnowledgeRevision.status == "DRAFT",
            )
            .values(
                status="APPROVED",
                reviewed_by=approved_by,
                reviewed_at=approved_at,
                updated_at=approved_at,
            )
        )
        return result.rowcount == 1

    def update_draft_if_draft(self, revision_id: int, values: dict) -> bool:
        """Apply one exact DRAFT-only patch so stale writers cannot alter APPROVED content."""

        result = self.db.execute(
            update(MedicalKnowledgeRevision)
            .where(
                MedicalKnowledgeRevision.id == revision_id,
                MedicalKnowledgeRevision.status == "DRAFT",
            )
            .values(**values)
        )
        return result.rowcount == 1

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

    def replace_current_publication(
        self,
        *,
        topic_id: int,
        revision_id: int,
        published_at: datetime,
        expected_previous_revision_id: int | None,
    ) -> bool:
        """Update all visibility flags and the topic pointer in the current transaction."""

        expected_pointer = (
            MedicalKnowledgeTopic.published_revision_id.is_(None)
            if expected_previous_revision_id is None
            else MedicalKnowledgeTopic.published_revision_id == expected_previous_revision_id
        )
        pointer = self.db.execute(
            update(MedicalKnowledgeTopic)
            .where(MedicalKnowledgeTopic.id == topic_id, expected_pointer)
            .values(published_revision_id=revision_id, updated_at=published_at)
        )
        if pointer.rowcount != 1:
            return False
        target = self.db.execute(
            update(MedicalKnowledgeRevision)
            .where(
                MedicalKnowledgeRevision.id == revision_id,
                MedicalKnowledgeRevision.topic_id == topic_id,
                MedicalKnowledgeRevision.status == "APPROVED",
            )
            .values(
                parent_display_allowed=True,
                updated_at=MedicalKnowledgeRevision.updated_at,
            )
        )
        if target.rowcount != 1:
            return False
        self.db.execute(
            update(MedicalKnowledgeRevision)
            .where(
                MedicalKnowledgeRevision.topic_id == topic_id,
                MedicalKnowledgeRevision.id != revision_id,
            )
            .values(
                parent_display_allowed=False,
                updated_at=MedicalKnowledgeRevision.updated_at,
            )
        )
        return True

    def withdraw_current_publication(
        self,
        *,
        topic_id: int,
        revision_id: int,
        unpublished_at: datetime,
    ) -> bool:
        """Clear one exact current pointer and its visibility flag in this transaction."""

        pointer = self.db.execute(
            update(MedicalKnowledgeTopic)
            .where(
                MedicalKnowledgeTopic.id == topic_id,
                MedicalKnowledgeTopic.published_revision_id == revision_id,
            )
            .values(published_revision_id=None, updated_at=unpublished_at)
        )
        if pointer.rowcount != 1:
            return False
        revision = self.db.execute(
            update(MedicalKnowledgeRevision)
            .where(
                MedicalKnowledgeRevision.id == revision_id,
                MedicalKnowledgeRevision.topic_id == topic_id,
                MedicalKnowledgeRevision.status == "APPROVED",
                MedicalKnowledgeRevision.parent_display_allowed.is_(True),
            )
            .values(
                parent_display_allowed=False,
                updated_at=MedicalKnowledgeRevision.updated_at,
            )
        )
        return revision.rowcount == 1

    def count_parent_visible_revisions(self, topic_id: int) -> int:
        return int(
            self.db.scalar(
                select(func.count(MedicalKnowledgeRevision.id)).where(
                    MedicalKnowledgeRevision.topic_id == topic_id,
                    MedicalKnowledgeRevision.parent_display_allowed.is_(True),
                )
            )
            or 0
        )

    def create_publication(
        self,
        *,
        topic_id: int,
        revision_id: int,
        published_by: int,
        published_at: datetime,
        action: str = "PUBLISH",
    ) -> MedicalKnowledgePublication:
        publication = MedicalKnowledgePublication(
            topic_id=topic_id,
            revision_id=revision_id,
            published_by=published_by,
            published_at=published_at,
            action=action,
        )
        self.db.add(publication)
        self.db.flush()
        return publication

    def get_latest_publication_for_revision(
        self, revision_id: int
    ) -> MedicalKnowledgePublication | None:
        return self.db.scalar(
            select(MedicalKnowledgePublication)
            .where(MedicalKnowledgePublication.revision_id == revision_id)
            .order_by(
                MedicalKnowledgePublication.published_at.desc(),
                MedicalKnowledgePublication.id.desc(),
            )
            .limit(1)
        )

    def count_publications_for_revision(self, revision_id: int) -> int:
        return int(
            self.db.scalar(
                select(func.count(MedicalKnowledgePublication.id)).where(
                    MedicalKnowledgePublication.revision_id == revision_id
                )
            )
            or 0
        )

    def create_source(self, data: MedicalEvidenceSourceCreate) -> MedicalEvidenceSource:
        values = data.model_dump()
        values["provider_id"] = (
            values["provider_id"] or data.source_type
        ).strip().upper()
        values["external_id"] = (
            (values["external_id"] or data.pmid or "").strip() or None
        )
        values["source_kind"] = values["source_kind"] or (
            "RESEARCH_ARTICLE" if data.source_type == "PUBMED" else "OTHER"
        )
        source = MedicalEvidenceSource(**values)
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

    def get_source_by_provider_external_id(
        self, provider_id: str, external_id: str
    ) -> MedicalEvidenceSource | None:
        return self.db.scalar(
            select(MedicalEvidenceSource).where(
                MedicalEvidenceSource.provider_id == provider_id.strip().upper(),
                MedicalEvidenceSource.external_id == external_id,
            )
        )

    def get_sources_by_provider_external_ids(
        self, provider_id: str, external_ids: list[str]
    ) -> list[MedicalEvidenceSource]:
        if not external_ids:
            return []
        sources = list(
            self.db.scalars(
                select(MedicalEvidenceSource).where(
                    MedicalEvidenceSource.provider_id == provider_id.strip().upper(),
                    MedicalEvidenceSource.external_id.in_(external_ids),
                )
            )
        )
        by_external_id = {source.external_id: source for source in sources}
        return [by_external_id[value] for value in external_ids if value in by_external_id]

    def get_sources_by_pmids(self, pmids: list[str]) -> list[MedicalEvidenceSource]:
        if not pmids:
            return []
        sources = list(
            self.db.scalars(
                select(MedicalEvidenceSource).where(
                    MedicalEvidenceSource.source_type == "PUBMED",
                    MedicalEvidenceSource.pmid.in_(pmids),
                )
            )
        )
        by_pmid = {source.pmid: source for source in sources}
        return [by_pmid[pmid] for pmid in pmids if pmid in by_pmid]

    def create_evidence_content(
        self, data: MedicalEvidenceContentCreate
    ) -> MedicalEvidenceContent:
        content = MedicalEvidenceContent(**data.model_dump())
        self.db.add(content)
        self.db.flush()
        return content

    def get_evidence_content_by_hash(
        self, source_id: int, content_sha256: str
    ) -> MedicalEvidenceContent | None:
        return self.db.scalar(
            select(MedicalEvidenceContent).where(
                MedicalEvidenceContent.source_id == source_id,
                MedicalEvidenceContent.content_sha256 == content_sha256,
            )
        )

    def get_preferred_evidence_contents(
        self, source_ids: list[int]
    ) -> dict[int, MedicalEvidenceContent]:
        if not source_ids:
            return {}
        kind_priority = case(
            (MedicalEvidenceContent.content_kind == "PMC_FULL_TEXT", 3),
            (MedicalEvidenceContent.content_kind == "PMC_FULL_TEXT_EXCERPT", 2),
            else_=1,
        )
        contents = list(
            self.db.scalars(
                select(MedicalEvidenceContent)
                .where(MedicalEvidenceContent.source_id.in_(source_ids))
                .order_by(
                    MedicalEvidenceContent.source_id,
                    kind_priority.desc(),
                    MedicalEvidenceContent.retrieved_at.desc(),
                    MedicalEvidenceContent.id.desc(),
                )
            )
        )
        preferred: dict[int, MedicalEvidenceContent] = {}
        for content in contents:
            if (content.evidence_text or "").strip():
                preferred.setdefault(content.source_id, content)
        return preferred

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
