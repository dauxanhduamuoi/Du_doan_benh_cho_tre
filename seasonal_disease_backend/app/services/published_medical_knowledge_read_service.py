from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.medical_knowledge_draft_schemas import (
    MedicalKnowledgeDraftProposal,
    SourceAssessment,
)
from app.published_medical_knowledge_schemas import (
    ParentMedicalKnowledgeCitation,
    PublishedMedicalKnowledgeBatchRequest,
    PublishedMedicalKnowledgeBatchResponse,
    PublishedMedicalKnowledgeItem,
)
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.repositories.auto_medical_knowledge_repository import AutoMedicalKnowledgeRepository
from app.services.auto_medical_knowledge_service import (
    AUTO_BASIC_PARENT_WARNING,
    AUTO_STRICT_PARENT_WARNING,
    AutoMedicalKnowledgeQueueService,
    auto_revision_parent_eligible,
)
from app.services.medical_knowledge_population_policy import (
    PARENT_DISPLAYABLE_EVIDENCE,
    parent_tier2_ineligibility_reasons,
    stored_source_assessment,
)


class PublishedMedicalKnowledgeReadService:
    """Read only the current, consistent, parent-safe publication for bounded pairs."""

    def __init__(
        self,
        db: Session,
        *,
        auto_queue: AutoMedicalKnowledgeQueueService | None = None,
    ):
        self.db = db
        self.repository = MedicalKnowledgeRepository(db)
        self.auto_repository = AutoMedicalKnowledgeRepository(db)
        self.auto_queue = auto_queue

    def read_batch(
        self, request: PublishedMedicalKnowledgeBatchRequest
    ) -> PublishedMedicalKnowledgeBatchResponse:
        requested_selectors = list(
            dict.fromkeys(
                (
                    item.disease_group_id,
                    item.factor_type,
                    item.factor_key,
                    item.factor_value,
                )
                for item in request.items
            )
        )
        topics = self.repository.get_parent_published_topics(requested_selectors)
        by_selector = {
            (
                topic.disease_group_id,
                topic.factor_type,
                topic.factor_key,
                topic.factor_value,
            ): topic
            for topic in topics
        }
        items: list[PublishedMedicalKnowledgeItem] = []
        resolved: set[tuple[str, str, str, str | None]] = set()
        for selector in requested_selectors:
            topic = by_selector.get(selector)
            item = self._safe_item(topic) if topic is not None else None
            if item is not None:
                items.append(item)
                resolved.add(selector)
        missing = [selector for selector in requested_selectors if selector not in resolved]
        if missing:
            try:
                settings = self.auto_repository.get_settings()
            except SQLAlchemyError:
                self.db.rollback()
                return PublishedMedicalKnowledgeBatchResponse(items=items)
            if settings.display_mode == "REVIEWED_WITH_AUTO_FALLBACK":
                auto_by_selector = self.auto_repository.current_revisions_for_selectors(missing)
                for selector in missing:
                    row = auto_by_selector.get(selector)
                    if row is None:
                        continue
                    auto_item = self._safe_auto_item(*row)
                    if auto_item is not None:
                        items.append(auto_item)
            if self.auto_queue is not None:
                selector_models = [
                    item for item in request.items
                    if (
                        item.disease_group_id,
                        item.factor_type,
                        item.factor_key,
                        item.factor_value,
                    ) in missing
                ]
                # DB-only enqueue. External discovery/generation happens in the worker.
                self.auto_queue.enqueue_selectors(selector_models)
        return PublishedMedicalKnowledgeBatchResponse(items=items)

    @staticmethod
    def _safe_item(topic) -> PublishedMedicalKnowledgeItem | None:
        revision = topic.published_revision
        if (
            revision is None
            or topic.published_revision_id != revision.id
            or revision.topic_id != topic.id
            or revision.status != "APPROVED"
            or revision.parent_display_allowed is not True
            or revision.evidence_level not in PARENT_DISPLAYABLE_EVIDENCE
        ):
            return None

        links = sorted(revision.source_links, key=lambda link: (link.sort_order, link.source_id))
        assessments: list[SourceAssessment] = []
        citations: list[ParentMedicalKnowledgeCitation] = []
        for link in links:
            source = link.source
            if source is None:
                return None
            if (
                link.evidence_content is not None
                and link.evidence_content.source_id != source.id
            ):
                return None
            evidence_text = (
                link.evidence_content.evidence_text
                if link.evidence_content is not None
                else source.abstract_text or ""
            )
            if not evidence_text.strip():
                return None
            assessment = stored_source_assessment(link)
            if assessment is None:
                return None
            try:
                assessments.append(assessment)
                citations.append(
                    ParentMedicalKnowledgeCitation(
                        title=source.title.strip(),
                        journal=source.journal,
                        publication_year=source.publication_year,
                        pmid=source.pmid if (source.pmid or "").isdigit() else None,
                        doi=source.doi,
                        pmcid=None,
                        url=PublishedMedicalKnowledgeReadService._safe_citation_url(source),
                    )
                )
            except ValidationError:
                return None

        if (
            not assessments
            or not citations
            or parent_tier2_ineligibility_reasons(revision.evidence_level, assessments)
        ):
            return None
        try:
            MedicalKnowledgeDraftProposal(
                evidence_level=revision.evidence_level,
                evidence_scope=revision.evidence_scope,
                short_explanation_vi=revision.short_explanation_vi,
                detailed_explanation_vi=revision.detailed_explanation_vi,
                limitations_vi=revision.limitations_vi,
                source_assessments=assessments,
            )
            return PublishedMedicalKnowledgeItem(
                disease_group_id=topic.disease_group_id,
                knowledge_type="REVIEWED",
                auto_tier=None,
                warning=None,
                factor_type=topic.factor_type,
                factor_key=topic.factor_key,
                factor_value=topic.factor_value,
                weather_factor=topic.weather_factor,
                revision_id=revision.id,
                evidence_level=revision.evidence_level,
                evidence_scope=revision.evidence_scope,
                short_explanation_vi=revision.short_explanation_vi,
                detailed_explanation_vi=revision.detailed_explanation_vi,
                limitations_vi=revision.limitations_vi,
                sources=citations,
            )
        except ValidationError:
            return None

    def _safe_auto_item(
        self, topic, revision, state
    ) -> PublishedMedicalKnowledgeItem | None:
        if state.is_hidden_by_staff is True:
            return None
        source_rows = self.auto_repository.get_revision_sources(revision.id)
        if not auto_revision_parent_eligible(revision, source_rows):
            return None
        citations = []
        for _link, source, _content in source_rows:
            try:
                citations.append(
                    ParentMedicalKnowledgeCitation(
                        title=source.title.strip(),
                        journal=source.journal,
                        publication_year=source.publication_year,
                        pmid=source.pmid if (source.pmid or "").isdigit() else None,
                        doi=source.doi,
                        pmcid=None,
                        url=self._safe_citation_url(source),
                    )
                )
            except ValidationError:
                return None
        try:
            auto_tier = self.auto_repository.resolved_auto_tier(revision)
            return PublishedMedicalKnowledgeItem(
                disease_group_id=topic.disease_group_id,
                knowledge_type="AUTO",
                auto_tier=auto_tier,
                warning=(
                    AUTO_BASIC_PARENT_WARNING
                    if auto_tier == "BASIC"
                    else AUTO_STRICT_PARENT_WARNING
                ),
                factor_type=topic.factor_type,
                factor_key=topic.factor_key,
                factor_value=topic.factor_value,
                weather_factor=topic.weather_factor,
                revision_id=revision.id,
                evidence_level=revision.evidence_level,
                evidence_scope=revision.evidence_scope,
                short_explanation_vi=revision.short_explanation_vi,
                detailed_explanation_vi=revision.detailed_explanation_vi,
                limitations_vi=revision.limitations_vi,
                sources=citations,
            )
        except ValidationError:
            return None

    @staticmethod
    def _safe_citation_url(source) -> str | None:
        if (source.pmid or "").isdigit():
            return f"https://pubmed.ncbi.nlm.nih.gov/{source.pmid}/"
        url = (source.url or "").strip()
        return url if url.startswith("https://") else None
