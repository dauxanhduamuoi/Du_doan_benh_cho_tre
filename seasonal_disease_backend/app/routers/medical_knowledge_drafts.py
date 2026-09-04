from __future__ import annotations

import logging
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_TIMEOUT_SECONDS,
    MEDICAL_KNOWLEDGE_LLM_PROVIDER,
    MEDICAL_KNOWLEDGE_LLM_TIMEOUT_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from app.database import get_db
from app.medical_knowledge_draft_schemas import (
    DraftGenerationRequest,
    DraftRevisionPatch,
    DraftRevisionResponse,
    DraftTopicHistoryResponse,
    RevisionApprovalResponse,
    RevisionPublicationResponse,
    RevisionUnpublicationResponse,
)
from app.models import User
from app.security import require_staff_or_admin
from app.services.medical_knowledge_draft_generator import (
    DraftGeneratorConfigurationError,
    DraftGeneratorOutputError,
    DraftProposalWholeGroupRequiresDirectError,
    DraftGeneratorRateLimitError,
    DraftGeneratorTimeoutError,
    DraftGeneratorUnavailableError,
    OllamaModelNotInstalledError,
    OllamaModelNotSelectedError,
    create_medical_knowledge_draft_generator,
)
from app.services.medical_knowledge_draft_service import (
    DraftNotEditableError,
    DraftPersistenceError,
    DraftWorkflowNotFoundError,
    DraftWorkflowValidationError,
    MedicalKnowledgeDraftService,
)
from app.services.medical_knowledge_pubmed_service import DiseaseUniverseConfigurationError
from app.services.medical_knowledge_approval_service import (
    ApprovalConflictError,
    ApprovalNotFoundError,
    ApprovalValidationError,
    MedicalKnowledgeApprovalService,
)
from app.services.medical_knowledge_publication_service import (
    MedicalKnowledgePublicationService,
    PublicationConflictError,
    PublicationNotFoundError,
    PublicationValidationError,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/medical-knowledge", tags=["Medical Knowledge Drafts"])


def get_draft_service(db: Session = Depends(get_db)) -> Generator[MedicalKnowledgeDraftService, None, None]:
    try:
        generator = create_medical_knowledge_draft_generator(
            provider=MEDICAL_KNOWLEDGE_LLM_PROVIDER,
            openai_api_key=OPENAI_API_KEY,
            openai_model=OPENAI_MODEL,
            openai_timeout_seconds=MEDICAL_KNOWLEDGE_LLM_TIMEOUT_SECONDS,
            ollama_base_url=OLLAMA_BASE_URL,
            ollama_model=OLLAMA_MODEL,
            ollama_timeout_seconds=OLLAMA_TIMEOUT_SECONDS,
            groq_api_key=GROQ_API_KEY,
            groq_model=GROQ_MODEL,
            groq_timeout_seconds=GROQ_TIMEOUT_SECONDS,
        )
    except DraftGeneratorConfigurationError as exc:
        raise HTTPException(
            status_code=503, detail="AI draft generation provider is not configured correctly"
        ) from exc
    try:
        yield MedicalKnowledgeDraftService(db, generator)
    finally:
        generator.close()


def get_approval_service(
    db: Session = Depends(get_db),
) -> MedicalKnowledgeApprovalService:
    return MedicalKnowledgeApprovalService(db)


def get_publication_service(
    db: Session = Depends(get_db),
) -> MedicalKnowledgePublicationService:
    return MedicalKnowledgePublicationService(db)


def _map_draft_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PublicationConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, PublicationNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PublicationValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ApprovalConflictError):
        return HTTPException(status_code=409, detail="Only DRAFT revisions can be approved")
    if isinstance(exc, ApprovalNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ApprovalValidationError):
        detail = {"code": exc.code, "message": str(exc)} if exc.code else str(exc)
        return HTTPException(status_code=422, detail=detail)
    if isinstance(exc, DraftNotEditableError):
        return HTTPException(status_code=409, detail="Only DRAFT revisions can be edited")
    if isinstance(exc, DraftWorkflowNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, DraftWorkflowValidationError):
        return HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, OllamaModelNotSelectedError):
        return HTTPException(status_code=503, detail="No local Ollama model is selected")
    if isinstance(exc, OllamaModelNotInstalledError):
        return HTTPException(status_code=503, detail="The selected Ollama model is not installed")
    if isinstance(exc, DraftGeneratorTimeoutError):
        return HTTPException(status_code=504, detail="Local AI response timed out")
    if isinstance(exc, DraftGeneratorRateLimitError):
        return HTTPException(
            status_code=429,
            detail="Đã đạt giới hạn sử dụng nhà cung cấp AI. Hãy thử lại sau.",
        )
    if isinstance(exc, (DraftGeneratorConfigurationError, DiseaseUniverseConfigurationError)):
        return HTTPException(
            status_code=503,
            detail="AI draft generation is not configured on the server",
        )
    if isinstance(exc, DraftGeneratorUnavailableError):
        return HTTPException(
            status_code=502,
            detail="AI draft generation is temporarily unavailable",
        )
    if isinstance(exc, DraftProposalWholeGroupRequiresDirectError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "DRAFT_SCOPE_WHOLE_GROUP_REQUIRES_DIRECT",
                "message": "WHOLE_GROUP requires at least one DIRECT source assessment",
            },
        )
    if isinstance(exc, DraftGeneratorOutputError):
        return HTTPException(
            status_code=502,
            detail={
                "code": "DRAFT_PROPOSAL_INVALID",
                "message": "AI could not produce a valid structured medical draft",
            },
        )
    if isinstance(exc, DraftPersistenceError):
        logger.exception("Medical Knowledge draft persistence failed")
        return HTTPException(status_code=500, detail="Medical Knowledge draft could not be saved")
    logger.exception("Medical Knowledge draft operation failed")
    return HTTPException(status_code=500, detail="Medical Knowledge draft operation failed")


@router.post("/drafts/generate", response_model=DraftRevisionResponse)
def generate_medical_knowledge_draft(
    payload: DraftGenerationRequest,
    current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgeDraftService = Depends(get_draft_service),
):
    try:
        return service.generate(payload, created_by=current_user.id)
    except Exception as exc:
        raise _map_draft_error(exc) from exc


@router.get("/topics", response_model=DraftTopicHistoryResponse)
def get_medical_knowledge_topic_history(
    disease_group_id: str = Query(min_length=1, max_length=100),
    factor_type: str | None = Query(default=None, max_length=16),
    factor_key: str | None = Query(default=None, max_length=32),
    factor_value: str | None = Query(default=None, max_length=100),
    weather_factor: str | None = Query(default=None, max_length=32),
    _current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgeDraftService = Depends(get_draft_service),
):
    try:
        if factor_type is None and factor_key is None:
            return service.get_history(disease_group_id, weather_factor)
        return service.get_history(
            disease_group_id,
            factor_type=factor_type,
            factor_key=factor_key,
            factor_value=factor_value,
            weather_factor=weather_factor,
        )
    except Exception as exc:
        raise _map_draft_error(exc) from exc


@router.get("/revisions/{revision_id}", response_model=DraftRevisionResponse)
def get_medical_knowledge_revision(
    revision_id: int,
    _current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgeDraftService = Depends(get_draft_service),
):
    try:
        return service.get_revision(revision_id)
    except Exception as exc:
        raise _map_draft_error(exc) from exc


@router.patch("/revisions/{revision_id}", response_model=DraftRevisionResponse)
def update_medical_knowledge_draft(
    revision_id: int,
    payload: DraftRevisionPatch,
    _current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgeDraftService = Depends(get_draft_service),
):
    try:
        return service.update_draft(revision_id, payload)
    except Exception as exc:
        raise _map_draft_error(exc) from exc


@router.post("/revisions/{revision_id}/approve", response_model=RevisionApprovalResponse)
def approve_medical_knowledge_revision(
    revision_id: int,
    current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgeApprovalService = Depends(get_approval_service),
):
    try:
        return service.approve(revision_id, approved_by=current_user.id)
    except Exception as exc:
        raise _map_draft_error(exc) from exc


@router.post("/revisions/{revision_id}/publish", response_model=RevisionPublicationResponse)
def publish_medical_knowledge_revision(
    revision_id: int,
    current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgePublicationService = Depends(get_publication_service),
):
    try:
        return service.publish(revision_id, published_by=current_user.id)
    except Exception as exc:
        raise _map_draft_error(exc) from exc


@router.post(
    "/revisions/{revision_id}/unpublish",
    response_model=RevisionUnpublicationResponse,
)
def unpublish_medical_knowledge_revision(
    revision_id: int,
    current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgePublicationService = Depends(get_publication_service),
):
    try:
        return service.unpublish(revision_id, unpublished_by=current_user.id)
    except Exception as exc:
        raise _map_draft_error(exc) from exc
