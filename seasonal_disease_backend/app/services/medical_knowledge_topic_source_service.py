from __future__ import annotations

from sqlalchemy.orm import Session

from app.medical_knowledge_schemas import MedicalTopicCreate
from app.pubmed_schemas import (
    MedicalKnowledgeTopicSourceItem,
    MedicalKnowledgeTopicSourceLibraryResponse,
)
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository


class MedicalKnowledgeTopicSourceService:
    """Persistent collection membership, distinct from revision source snapshots."""

    def __init__(self, db: Session):
        self.db = db
        self.repository = MedicalKnowledgeRepository(db)

    def get_or_create_topic(
        self,
        *,
        disease_group_id: str,
        factor_type: str,
        factor_key: str,
        factor_value: str | None,
        weather_factor: str | None,
        created_by: int | None,
    ):
        topic = self.repository.get_topic_by_selector(
            disease_group_id, factor_type, factor_key, factor_value
        )
        if topic is None:
            topic = self.repository.create_topic(
                MedicalTopicCreate(
                    disease_group_id=disease_group_id,
                    factor_type=factor_type,
                    factor_key=factor_key,
                    factor_value=factor_value,
                    weather_factor=weather_factor,
                    created_by=created_by,
                )
            )
        return topic

    def ensure_source(
        self, *, topic_id: int, source_id: int, added_by: int | None
    ) -> bool:
        if self.repository.get_topic_source(topic_id, source_id) is not None:
            return False
        self.repository.create_topic_source(
            topic_id=topic_id,
            source_id=source_id,
            added_by=added_by,
        )
        return True

    def read(
        self,
        *,
        disease_group_id: str,
        factor_type: str,
        factor_key: str,
        factor_value: str | None,
        weather_factor: str | None,
    ) -> MedicalKnowledgeTopicSourceLibraryResponse:
        topic = self.repository.get_topic_by_selector(
            disease_group_id, factor_type, factor_key, factor_value
        )
        if topic is None:
            return MedicalKnowledgeTopicSourceLibraryResponse(
                topic_id=None,
                disease_group_id=disease_group_id,
                factor_type=factor_type,
                factor_key=factor_key,
                factor_value=factor_value,
                weather_factor=weather_factor,
                sources=[],
            )
        links = self.repository.list_topic_sources(topic.id)
        content_by_source = self.repository.get_preferred_evidence_contents(
            [link.source_id for link in links]
        )
        return MedicalKnowledgeTopicSourceLibraryResponse(
            topic_id=topic.id,
            disease_group_id=disease_group_id,
            factor_type=factor_type,
            factor_key=factor_key,
            factor_value=factor_value,
            weather_factor=weather_factor,
            sources=[
                MedicalKnowledgeTopicSourceItem(
                    source_id=link.source_id,
                    pmid=link.source.pmid,
                    title=link.source.title,
                    journal=link.source.journal,
                    publication_year=link.source.publication_year,
                    doi=link.source.doi,
                    pmcid=(
                        content.external_identifier
                        if content is not None
                        and (content.external_identifier or "").startswith("PMC")
                        else None
                    ),
                    content_kind=content.content_kind if content is not None else None,
                    added_at=link.added_at,
                )
                for link in links
                for content in [content_by_source.get(link.source_id)]
            ],
        )
