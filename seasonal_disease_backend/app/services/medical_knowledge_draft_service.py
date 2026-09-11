from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import (
    MEDICAL_KNOWLEDGE_EVIDENCE_MAX_CHARS_PER_SOURCE,
    MEDICAL_KNOWLEDGE_LLM_MAX_INPUT_CHARS,
    MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES,
    MEDICAL_KNOWLEDGE_PROMPT_VERSION,
    WEATHER_AI_V3_DISEASE_CATALOG,
    WEATHER_AI_V3_MODEL_MANIFEST,
)
from app.medical_knowledge_draft_schemas import (
    DraftGenerationContext,
    DraftGenerationRequest,
    DraftRevisionPatch,
    DraftRevisionResponse,
    DraftRevisionSummary,
    DraftSourceInput,
    DraftSourceResponse,
    DraftTopicHistoryResponse,
    DraftTopicResponse,
    MedicalKnowledgeDraftProposal,
)
from app.medical_knowledge_models import (
    MedicalEvidenceContent,
    MedicalEvidenceSource,
)
from app.medical_knowledge_factors import normalize_factor
from app.models import User
from app.medical_knowledge_schemas import (
    MedicalRevisionCreate,
    MedicalRevisionSourceCreate,
)
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.services.medical_knowledge_draft_generator import MedicalKnowledgeDraftGenerator
from app.services.medical_knowledge_pubmed_service import DiseaseUniverseConfigurationError
from app.services.medical_knowledge_population_policy import (
    has_pediatric_direct_support,
    parent_tier2_ineligibility_reasons,
    stored_source_assessment,
)
from app.services.medical_knowledge_prompt import build_generation_input
from app.services.medical_evidence_provider import (
    DEFAULT_AUTO_EVIDENCE_TRUST_POLICY,
    MedicalEvidenceTrustPolicy,
)


class DraftWorkflowValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "DRAFT_PROPOSAL_INVALID"):
        super().__init__(message)
        self.code = code


class DraftWorkflowNotFoundError(DraftWorkflowValidationError):
    def __init__(self, message: str, *, code: str = "DRAFT_SOURCE_NOT_FOUND"):
        super().__init__(message, code=code)


class DraftNotEditableError(DraftWorkflowValidationError):
    pass


class DraftPersistenceError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def load_deployed_disease_contexts(
    manifest_path: str, catalog_path: str
) -> dict[str, tuple[str, str | None]]:
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        disease_order = [str(value) for value in manifest["disease_order"]]
        if manifest.get("model_count") != len(disease_order) or len(set(disease_order)) != len(disease_order):
            raise DiseaseUniverseConfigurationError("Deployed disease manifest is inconsistent")
        with Path(catalog_path).open(encoding="utf-8-sig", newline="") as stream:
            rows = csv.DictReader(stream)
            catalog = {
                str(row["disease_group_id"]): (
                    str(row["disease_group_name"]).strip(),
                    str(row.get("report_group_code") or "").strip() or None,
                )
                for row in rows
                if row.get("disease_group_id") and row.get("disease_group_name")
            }
    except DiseaseUniverseConfigurationError:
        raise
    except (OSError, KeyError, TypeError, json.JSONDecodeError, csv.Error) as exc:
        raise DiseaseUniverseConfigurationError("Disease catalog metadata is unavailable") from exc
    missing = [disease_id for disease_id in disease_order if disease_id not in catalog]
    if missing:
        raise DiseaseUniverseConfigurationError("Disease catalog does not cover the deployed universe")
    return {disease_id: catalog[disease_id] for disease_id in disease_order}


class MedicalKnowledgeDraftService:
    def __init__(
        self,
        db: Session,
        generator: MedicalKnowledgeDraftGenerator,
        *,
        disease_manifest_path: Path = WEATHER_AI_V3_MODEL_MANIFEST,
        disease_catalog_path: Path = WEATHER_AI_V3_DISEASE_CATALOG,
        prompt_version: str = MEDICAL_KNOWLEDGE_PROMPT_VERSION,
        max_sources: int = MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES,
        max_input_chars: int = MEDICAL_KNOWLEDGE_LLM_MAX_INPUT_CHARS,
        max_chars_per_source: int = MEDICAL_KNOWLEDGE_EVIDENCE_MAX_CHARS_PER_SOURCE,
        persistence_attempts: int = 3,
        source_trust_policy: MedicalEvidenceTrustPolicy = DEFAULT_AUTO_EVIDENCE_TRUST_POLICY,
    ):
        self.db = db
        self.generator = generator
        self.repository = MedicalKnowledgeRepository(db)
        self.disease_manifest_path = str(Path(disease_manifest_path).resolve())
        self.disease_catalog_path = str(Path(disease_catalog_path).resolve())
        self.prompt_version = prompt_version
        self.max_sources = min(max(1, max_sources), 10)
        self.max_input_chars = max_input_chars
        self.max_chars_per_source = max(1, max_chars_per_source)
        self.persistence_attempts = max(1, persistence_attempts)
        self.source_trust_policy = source_trust_policy

    def generate(self, request: DraftGenerationRequest, *, created_by: int | None) -> DraftRevisionResponse:
        context = self._generation_context(request)
        # End the read-only transaction before waiting on the network provider.
        self.db.rollback()
        proposal = self.generator.generate(context)
        self._validate_provider_source_ids(proposal, request.source_ids)
        self._validate_supported_population(proposal)
        revision_id = self._persist_generated_draft(
            request, context, proposal, created_by=created_by
        )
        return self.get_revision(revision_id)

    def get_history(
        self,
        disease_group_id: str,
        weather_factor: str | None = None,
        *,
        factor_type: str | None = None,
        factor_key: str | None = None,
        factor_value: str | None = None,
    ) -> DraftTopicHistoryResponse:
        disease_name, _ = self._disease_context(disease_group_id)
        try:
            factor = normalize_factor(
                factor_type=factor_type,
                factor_key=factor_key,
                factor_value=factor_value,
                weather_factor=weather_factor,
            )
        except ValueError as exc:
            raise DraftWorkflowValidationError(str(exc), code="DRAFT_FACTOR_INVALID") from exc
        topic = self.repository.get_topic_by_selector(
            disease_group_id, factor.factor_type, factor.factor_key, factor.factor_value
        )
        if topic is None:
            return DraftTopicHistoryResponse(topic=None, revisions=[])
        revisions = self.repository.list_revisions_desc(topic.id)
        return DraftTopicHistoryResponse(
            topic=DraftTopicResponse(
                id=topic.id,
                disease_group_id=topic.disease_group_id,
                disease_group_name=disease_name,
                factor_type=topic.factor_type,
                factor_key=topic.factor_key,
                factor_value=topic.factor_value,
                weather_factor=topic.weather_factor,
                published_revision_id=topic.published_revision_id,
            ),
            revisions=[
                self._summary(revision, published_revision_id=topic.published_revision_id)
                for revision in revisions
            ],
        )

    def get_revision(self, revision_id: int) -> DraftRevisionResponse:
        revision = self.repository.get_revision_with_sources(revision_id)
        if revision is None:
            raise DraftWorkflowNotFoundError("Medical knowledge revision was not found")
        disease_name, _ = self._disease_context(revision.topic.disease_group_id)
        source_links = sorted(
            revision.source_links, key=lambda link: (link.sort_order, link.source_id)
        )
        assessments = [stored_source_assessment(link) for link in source_links]
        valid_assessments = [item for item in assessments if item is not None]
        eligibility_reasons = parent_tier2_ineligibility_reasons(
            revision.evidence_level, valid_assessments
        )
        if len(valid_assessments) != len(source_links):
            eligibility_reasons.append("PARENT_TIER2_SOURCE_ASSESSMENT_INVALID")
        reviewer = self.db.get(User, revision.reviewed_by) if revision.reviewed_by else None
        is_published = revision.topic.published_revision_id == revision.id
        publication = (
            self.repository.get_latest_publication_for_revision(revision.id)
            if is_published
            else None
        )
        publisher = (
            self.db.get(User, publication.published_by)
            if publication is not None and publication.published_by is not None
            else None
        )
        return DraftRevisionResponse(
            **self._summary(
                revision,
                published_revision_id=revision.topic.published_revision_id,
            ).model_dump(),
            topic_id=revision.topic_id,
            disease_group_id=revision.topic.disease_group_id,
            disease_group_name=disease_name,
            factor_type=revision.topic.factor_type,
            factor_key=revision.topic.factor_key,
            factor_value=revision.topic.factor_value,
            weather_factor=revision.topic.weather_factor,
            short_explanation_vi=revision.short_explanation_vi,
            detailed_explanation_vi=revision.detailed_explanation_vi,
            limitations_vi=revision.limitations_vi,
            parent_display_allowed=revision.parent_display_allowed,
            llm_model=revision.llm_model,
            prompt_version=revision.prompt_version,
            created_by=revision.created_by,
            reviewed_by=revision.reviewed_by,
            reviewed_by_name=(reviewer.full_name or reviewer.username) if reviewer else None,
            reviewed_at=revision.reviewed_at,
            published_by=publication.published_by if publication else None,
            published_by_name=(publisher.full_name or publisher.username) if publisher else None,
            published_at=publication.published_at if publication else None,
            sources=[
                DraftSourceResponse(
                    id=link.source.id,
                    source_type=link.source.source_type,
                    pmid=link.source.pmid,
                    doi=link.source.doi,
                    title=link.source.title,
                    authors=link.source.authors,
                    journal=link.source.journal,
                    publication_year=link.source.publication_year,
                    abstract_text=link.source.abstract_text,
                    url=link.source.url,
                    content_kind=(
                        link.evidence_content.content_kind
                        if link.evidence_content
                        else "ABSTRACT"
                        if (link.source.abstract_text or "").strip()
                        else None
                    ),
                    pmcid=(
                        link.evidence_content.external_identifier
                        if link.evidence_content
                        and (link.evidence_content.external_identifier or "").startswith("PMC")
                        else None
                    ),
                    content_origin=(
                        link.evidence_content.content_origin
                        if link.evidence_content
                        else "NCBI_PUBMED"
                    ),
                    source_role=link.source_role,
                    sort_order=link.sort_order,
                    relevance_note=link.relevance_note,
                    population_relevance=link.population_relevance or "UNKNOWN",
                    population_note=link.population_note,
                )
                for link in source_links
            ],
            parent_tier2_eligible=not eligibility_reasons,
            parent_tier2_ineligibility_reasons=eligibility_reasons,
        )

    def update_draft(self, revision_id: int, patch: DraftRevisionPatch) -> DraftRevisionResponse:
        revision = self.repository.get_revision_with_sources(revision_id)
        if revision is None:
            raise DraftWorkflowNotFoundError("Medical knowledge revision was not found")
        if revision.status != "DRAFT":
            raise DraftNotEditableError("Only DRAFT revisions can be edited")
        requested_scope = patch.evidence_scope or revision.evidence_scope
        if requested_scope == "WHOLE_GROUP" and not any(
            link.source_role == "PRIMARY"
            and (link.relevance_note or "").startswith("DIRECT:")
            for link in revision.source_links
        ):
            raise DraftWorkflowValidationError(
                "WHOLE_GROUP requires at least one DIRECT source assessment",
                code="DRAFT_SCOPE_WHOLE_GROUP_REQUIRES_DIRECT",
            )
        requested_level = patch.evidence_level or revision.evidence_level
        stored_assessments = [stored_source_assessment(link) for link in revision.source_links]
        if requested_level == "SUPPORTED" and not has_pediatric_direct_support(
            item for item in stored_assessments if item is not None
        ):
            raise DraftWorkflowValidationError(
                "SUPPORTED requires at least one directly supportive pediatric source",
                code="DRAFT_SUPPORTED_REQUIRES_PEDIATRIC_SOURCE",
            )
        values = patch.model_dump(exclude_unset=True)
        if not self.repository.update_draft_if_draft(revision_id, values):
            self.db.rollback()
            raise DraftNotEditableError("Only DRAFT revisions can be edited")
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.get_revision(revision_id)

    def _generation_context(self, request: DraftGenerationRequest) -> DraftGenerationContext:
        disease_name, report_group_code = self._disease_context(request.disease_group_id)
        if not request.source_ids:
            raise DraftWorkflowValidationError(
                "At least one source must be explicitly selected",
                code="DRAFT_NO_SOURCES_SELECTED",
            )
        if len(request.source_ids) > self.max_sources:
            raise DraftWorkflowValidationError(
                f"Một bản nháp hiện hỗ trợ tối đa {self.max_sources} nguồn.",
                code="DRAFT_TOO_MANY_SOURCES",
            )
        sources = self.repository.get_sources_by_ids(request.source_ids)
        found_ids = {source.id for source in sources}
        missing = [source_id for source_id in request.source_ids if source_id not in found_ids]
        if missing:
            raise DraftWorkflowNotFoundError(
                f"Evidence sources were not found: {missing}",
                code="DRAFT_SOURCE_NOT_FOUND",
            )
        topic = self.repository.get_topic_by_selector(
            request.disease_group_id,
            request.factor_type,
            request.factor_key,
            request.factor_value,
        )
        if topic is None:
            raise DraftWorkflowValidationError(
                "The requested disease and factor topic has no source library",
                code="DRAFT_TOPIC_MISMATCH",
            )
        linked_ids = self.repository.get_topic_source_ids(topic.id)
        outside_topic = [
            source_id for source_id in request.source_ids if source_id not in linked_ids
        ]
        if outside_topic:
            raise DraftWorkflowValidationError(
                f"Selected sources are not in the current topic library: {outside_topic}",
                code="DRAFT_SOURCE_NOT_IN_TOPIC",
            )
        if any(
            not self.source_trust_policy.is_provider_trusted(
                source.provider_id or source.source_type
            )
            for source in sources
        ):
            raise DraftWorkflowValidationError(
                "V1 draft generation accepts PubMed sources only",
                code="DRAFT_PROPOSAL_INVALID",
            )
        preferred_content = self.repository.get_preferred_evidence_contents(
            [source.id for source in sources]
        )
        unusable = [
            source.id
            for source in sources
            if preferred_content.get(source.id) is None
            or not preferred_content[source.id].evidence_text.strip()
        ]
        if unusable:
            raise DraftWorkflowValidationError(
                "Một hoặc nhiều tài liệu đã chọn chưa có nội dung mà AI có thể đọc. "
                f"Source IDs: {unusable}",
                code="DRAFT_SOURCE_NO_USABLE_EVIDENCE",
            )
        mismatched = [
            source.id
            for source in sources
            if preferred_content[source.id].source_id != source.id
        ]
        if mismatched:
            raise DraftWorkflowValidationError(
                f"Selected evidence snapshots do not belong to their sources: {mismatched}",
                code="DRAFT_SOURCE_EVIDENCE_MISMATCH",
            )
        context = DraftGenerationContext(
            disease_group_id=request.disease_group_id,
            disease_group_name=disease_name,
            report_group_code=report_group_code,
            factor_type=request.factor_type,
            factor_key=request.factor_key,
            factor_value=request.factor_value,
            weather_factor=request.weather_factor,
            sources=[
                self._source_input(source, preferred_content.get(source.id))
                for source in sources
            ],
        )
        input_size = len(build_generation_input(context))
        if input_size > self.max_input_chars:
            raise DraftWorkflowValidationError(
                f"Selected source text exceeds the safe input limit of {self.max_input_chars} characters",
                code="DRAFT_PROPOSAL_INVALID",
            )
        return context

    def _disease_context(self, disease_group_id: str) -> tuple[str, str | None]:
        catalog = load_deployed_disease_contexts(
            self.disease_manifest_path, self.disease_catalog_path
        )
        context = catalog.get(disease_group_id)
        if context is None:
            raise DraftWorkflowNotFoundError(
                f"Disease group {disease_group_id!r} is not in the deployed Weather AI universe"
            )
        return context

    def _source_input(
        self,
        source: MedicalEvidenceSource, content: MedicalEvidenceContent | None
    ) -> DraftSourceInput:
        raw = source.raw_metadata_json if isinstance(source.raw_metadata_json, dict) else {}
        publication_types = raw.get("publication_types", [])
        if not isinstance(publication_types, list):
            publication_types = []
        evidence_text = (
            content.evidence_text if content is not None else (source.abstract_text or "").strip()
        )[: self.max_chars_per_source]
        return DraftSourceInput(
            source_id=source.id,
            source_type=source.source_type,
            pmid=source.pmid,
            doi=source.doi,
            title=source.title,
            authors=source.authors,
            journal=source.journal,
            publication_year=source.publication_year,
            publication_types=[str(value) for value in publication_types[:20]],
            evidence_content_id=content.id if content else None,
            content_kind=content.content_kind if content else "ABSTRACT",
            evidence_text=evidence_text,
            content_origin=content.content_origin if content else "NCBI_PUBMED",
            pmcid=(
                content.external_identifier
                if content and (content.external_identifier or "").startswith("PMC")
                else None
            ),
            license_name=content.license_name if content else None,
            license_url=content.license_url if content else None,
        )

    @staticmethod
    def _validate_provider_source_ids(
        proposal: MedicalKnowledgeDraftProposal, selected_source_ids: list[int]
    ) -> None:
        selected = set(selected_source_ids)
        assessed = {assessment.source_id for assessment in proposal.source_assessments}
        if assessed - selected:
            raise DraftWorkflowValidationError(
                "The AI response referenced evidence sources that were not selected",
                code="DRAFT_PROPOSAL_INVALID",
            )
        if selected - assessed:
            raise DraftWorkflowValidationError(
                "The AI response must assess every selected evidence source",
                code="DRAFT_PROPOSAL_INVALID",
            )

    @staticmethod
    def _validate_supported_population(proposal: MedicalKnowledgeDraftProposal) -> None:
        if proposal.evidence_level == "SUPPORTED" and not has_pediatric_direct_support(
            proposal.source_assessments
        ):
            raise DraftWorkflowValidationError(
                "SUPPORTED requires at least one directly supportive pediatric source",
                code="DRAFT_SUPPORTED_REQUIRES_PEDIATRIC_SOURCE",
            )

    def _persist_generated_draft(
        self,
        request: DraftGenerationRequest,
        context: DraftGenerationContext,
        proposal: MedicalKnowledgeDraftProposal,
        *,
        created_by: int | None,
    ) -> int:
        assessments = {item.source_id: item for item in proposal.source_assessments}
        content_ids = {
            source.source_id: source.evidence_content_id for source in context.sources
        }
        for attempt in range(self.persistence_attempts):
            try:
                topic = self.repository.get_topic_by_selector(
                    request.disease_group_id,
                    request.factor_type,
                    request.factor_key,
                    request.factor_value,
                )
                if topic is None:
                    raise DraftWorkflowValidationError(
                        "The requested disease and factor topic no longer exists",
                        code="DRAFT_TOPIC_MISMATCH",
                    )
                linked_ids = self.repository.get_topic_source_ids(topic.id)
                if any(source_id not in linked_ids for source_id in request.source_ids):
                    raise DraftWorkflowValidationError(
                        "The selected source set no longer belongs to the current topic",
                        code="DRAFT_SOURCE_NOT_IN_TOPIC",
                    )
                revision = self.repository.create_revision(
                    MedicalRevisionCreate(
                        topic_id=topic.id,
                        revision_number=self.repository.next_revision_number(topic.id),
                        evidence_level=proposal.evidence_level,
                        evidence_scope=proposal.evidence_scope,
                        short_explanation_vi=proposal.short_explanation_vi,
                        detailed_explanation_vi=proposal.detailed_explanation_vi,
                        limitations_vi=proposal.limitations_vi,
                        status="DRAFT",
                        parent_display_allowed=False,
                        generated_by_llm=True,
                        llm_model=self.generator.model_name,
                        prompt_version=self.prompt_version,
                        created_by=created_by,
                        reviewed_by=None,
                        reviewed_at=None,
                    )
                )
                for sort_order, source_id in enumerate(request.source_ids):
                    assessment = assessments.get(source_id)
                    self.repository.attach_source(
                        MedicalRevisionSourceCreate(
                            revision_id=revision.id,
                            source_id=source_id,
                            evidence_content_id=content_ids.get(source_id),
                            source_role=(
                                "PRIMARY"
                                if assessment and assessment.relevance == "DIRECT"
                                else "SUPPORTING"
                            ),
                            sort_order=sort_order,
                            relevance_note=(
                                f"{assessment.relevance}: {assessment.note_vi}"
                                if assessment
                                else None
                            ),
                            population_relevance=assessment.population_relevance,
                            population_note=assessment.population_note,
                        )
                    )
                self.db.commit()
                return revision.id
            except IntegrityError as exc:
                self.db.rollback()
                if attempt + 1 == self.persistence_attempts:
                    raise DraftPersistenceError("Could not allocate a draft revision number") from exc
            except Exception:
                self.db.rollback()
                raise
        raise DraftPersistenceError("Could not persist the generated draft")

    @staticmethod
    def _summary(
        revision, *, published_revision_id: int | None = None
    ) -> DraftRevisionSummary:
        return DraftRevisionSummary(
            id=revision.id,
            revision_number=revision.revision_number,
            status=revision.status,
            evidence_level=revision.evidence_level,
            evidence_scope=revision.evidence_scope,
            generated_by_llm=revision.generated_by_llm,
            created_at=revision.created_at,
            updated_at=revision.updated_at,
            is_published=revision.id == published_revision_id,
        )
