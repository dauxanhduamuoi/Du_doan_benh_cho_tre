from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import (
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
from app.medical_knowledge_models import MedicalEvidenceSource, WEATHER_FACTORS
from app.medical_knowledge_schemas import (
    MedicalRevisionCreate,
    MedicalRevisionSourceCreate,
    MedicalTopicCreate,
)
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.services.medical_knowledge_draft_generator import MedicalKnowledgeDraftGenerator
from app.services.medical_knowledge_pubmed_service import DiseaseUniverseConfigurationError


class DraftWorkflowValidationError(ValueError):
    pass


class DraftWorkflowNotFoundError(DraftWorkflowValidationError):
    pass


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
        persistence_attempts: int = 3,
    ):
        self.db = db
        self.generator = generator
        self.repository = MedicalKnowledgeRepository(db)
        self.disease_manifest_path = str(Path(disease_manifest_path).resolve())
        self.disease_catalog_path = str(Path(disease_catalog_path).resolve())
        self.prompt_version = prompt_version
        self.max_sources = min(max_sources, 8)
        self.max_input_chars = max_input_chars
        self.persistence_attempts = max(1, persistence_attempts)

    def generate(self, request: DraftGenerationRequest, *, created_by: int | None) -> DraftRevisionResponse:
        context = self._generation_context(request)
        # End the read-only transaction before waiting on the network provider.
        self.db.rollback()
        proposal = self.generator.generate(context)
        self._validate_provider_source_ids(proposal, request.source_ids)
        revision_id = self._persist_generated_draft(request, proposal, created_by=created_by)
        return self.get_revision(revision_id)

    def get_history(self, disease_group_id: str, weather_factor: str) -> DraftTopicHistoryResponse:
        disease_name, _ = self._disease_context(disease_group_id)
        if weather_factor not in WEATHER_FACTORS:
            raise DraftWorkflowValidationError("Weather factor is not supported")
        topic = self.repository.get_topic_by_group_factor(disease_group_id, weather_factor)
        if topic is None:
            return DraftTopicHistoryResponse(topic=None, revisions=[])
        revisions = self.repository.list_revisions_desc(topic.id)
        return DraftTopicHistoryResponse(
            topic=DraftTopicResponse(
                id=topic.id,
                disease_group_id=topic.disease_group_id,
                disease_group_name=disease_name,
                weather_factor=topic.weather_factor,
                published_revision_id=topic.published_revision_id,
            ),
            revisions=[self._summary(revision) for revision in revisions],
        )

    def get_revision(self, revision_id: int) -> DraftRevisionResponse:
        revision = self.repository.get_revision_with_sources(revision_id)
        if revision is None:
            raise DraftWorkflowNotFoundError("Medical knowledge revision was not found")
        disease_name, _ = self._disease_context(revision.topic.disease_group_id)
        source_links = sorted(
            revision.source_links, key=lambda link: (link.sort_order, link.source_id)
        )
        return DraftRevisionResponse(
            **self._summary(revision).model_dump(),
            topic_id=revision.topic_id,
            disease_group_id=revision.topic.disease_group_id,
            disease_group_name=disease_name,
            weather_factor=revision.topic.weather_factor,
            short_explanation_vi=revision.short_explanation_vi,
            detailed_explanation_vi=revision.detailed_explanation_vi,
            limitations_vi=revision.limitations_vi,
            parent_display_allowed=revision.parent_display_allowed,
            llm_model=revision.llm_model,
            prompt_version=revision.prompt_version,
            created_by=revision.created_by,
            reviewed_by=revision.reviewed_by,
            reviewed_at=revision.reviewed_at,
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
                    source_role=link.source_role,
                    sort_order=link.sort_order,
                    relevance_note=link.relevance_note,
                )
                for link in source_links
            ],
        )

    def update_draft(self, revision_id: int, patch: DraftRevisionPatch) -> DraftRevisionResponse:
        revision = self.repository.get_revision(revision_id)
        if revision is None:
            raise DraftWorkflowNotFoundError("Medical knowledge revision was not found")
        if revision.status != "DRAFT":
            raise DraftNotEditableError("Only DRAFT revisions can be edited")
        for field, value in patch.model_dump(exclude_unset=True).items():
            setattr(revision, field, value)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.get_revision(revision_id)

    def _generation_context(self, request: DraftGenerationRequest) -> DraftGenerationContext:
        disease_name, report_group_code = self._disease_context(request.disease_group_id)
        if len(request.source_ids) > self.max_sources:
            raise DraftWorkflowValidationError(
                f"At most {self.max_sources} sources can be used for one draft"
            )
        sources = self.repository.get_sources_by_ids(request.source_ids)
        found_ids = {source.id for source in sources}
        missing = [source_id for source_id in request.source_ids if source_id not in found_ids]
        if missing:
            raise DraftWorkflowNotFoundError(f"Evidence sources were not found: {missing}")
        if any(source.source_type != "PUBMED" for source in sources):
            raise DraftWorkflowValidationError("V1 draft generation accepts PubMed sources only")
        if not any((source.abstract_text or "").strip() for source in sources):
            raise DraftWorkflowValidationError(
                "At least one selected PubMed source must have a usable abstract"
            )
        context = DraftGenerationContext(
            disease_group_id=request.disease_group_id,
            disease_group_name=disease_name,
            report_group_code=report_group_code,
            weather_factor=request.weather_factor,
            sources=[self._source_input(source) for source in sources],
        )
        input_size = len(context.model_dump_json())
        if input_size > self.max_input_chars:
            raise DraftWorkflowValidationError(
                f"Selected source text exceeds the safe input limit of {self.max_input_chars} characters"
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

    @staticmethod
    def _source_input(source: MedicalEvidenceSource) -> DraftSourceInput:
        raw = source.raw_metadata_json if isinstance(source.raw_metadata_json, dict) else {}
        publication_types = raw.get("publication_types", [])
        if not isinstance(publication_types, list):
            publication_types = []
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
            abstract_text=source.abstract_text,
        )

    @staticmethod
    def _validate_provider_source_ids(
        proposal: MedicalKnowledgeDraftProposal, selected_source_ids: list[int]
    ) -> None:
        selected = set(selected_source_ids)
        unknown = [
            assessment.source_id
            for assessment in proposal.source_assessments
            if assessment.source_id not in selected
        ]
        if unknown:
            raise DraftWorkflowValidationError(
                "The AI response referenced evidence sources that were not selected"
            )

    def _persist_generated_draft(
        self,
        request: DraftGenerationRequest,
        proposal: MedicalKnowledgeDraftProposal,
        *,
        created_by: int | None,
    ) -> int:
        assessments = {item.source_id: item for item in proposal.source_assessments}
        for attempt in range(self.persistence_attempts):
            try:
                topic = self.repository.get_topic_by_group_factor(
                    request.disease_group_id, request.weather_factor
                )
                if topic is None:
                    topic = self.repository.create_topic(
                        MedicalTopicCreate(
                            disease_group_id=request.disease_group_id,
                            weather_factor=request.weather_factor,
                            created_by=created_by,
                        )
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
    def _summary(revision) -> DraftRevisionSummary:
        return DraftRevisionSummary(
            id=revision.id,
            revision_number=revision.revision_number,
            status=revision.status,
            evidence_level=revision.evidence_level,
            evidence_scope=revision.evidence_scope,
            generated_by_llm=revision.generated_by_llm,
            created_at=revision.created_at,
            updated_at=revision.updated_at,
        )
