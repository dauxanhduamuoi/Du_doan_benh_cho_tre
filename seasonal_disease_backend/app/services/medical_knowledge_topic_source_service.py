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

    @staticmethod
    def _usable_for_draft(source, content) -> bool:
        if content is None or not (content.evidence_text or "").strip():
            return False
        provider_id = (source.provider_id or source.source_type).upper()
        if provider_id == "PUBMED":
            return True
        if provider_id != "WHO":
            return False
        provenance = content.provenance_json if isinstance(content.provenance_json, dict) else {}
        return bool(
            content.content_kind == "OFFICIAL_SUMMARY_EXCERPT"
            and content.content_origin == "WHO_PUBLICATIONS_API"
            and content.license_url
            == "https://creativecommons.org/licenses/by-nc-sa/3.0/igo/"
            and provenance.get("license_allowlisted") is True
            and provenance.get("full_text_stored") is False
        )

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
                    provider_id=link.source.provider_id or link.source.source_type,
                    external_id=link.source.external_id or link.source.pmid,
                    source_kind=link.source.source_kind or "OTHER",
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
                    url=link.source.url,
                    license_name=content.license_name if content is not None else None,
                    license_url=content.license_url if content is not None else None,
                    usable_for_draft=self._usable_for_draft(link.source, content),
                    added_at=link.added_at,
                )
                for link in links
                for content in [content_by_source.get(link.source_id)]
            ],
        )
