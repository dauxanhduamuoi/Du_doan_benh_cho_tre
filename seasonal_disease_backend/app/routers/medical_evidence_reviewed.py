from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.medical_evidence_reviewed_schemas import (
    ReviewedProviderExactLookupRequest,
    ReviewedProviderExactLookupResponse,
    ReviewedProviderImportRequest,
    ReviewedProviderImportResponse,
    ReviewedProviderSearchRequest,
    ReviewedProviderSearchResponse,
)
from app.models import User
from app.security import require_staff_or_admin
from app.services.medical_evidence_provider import MedicalEvidenceProviderError
from app.services.medical_evidence_provider_factory import create_medical_evidence_provider_registry
from app.services.medical_evidence_reviewed_service import (
    MedicalEvidenceReviewedService,
    ReviewedProviderSelectionError,
    ReviewedProvidersUnavailableError,
    ReviewedSourceNotFoundError,
)


router = APIRouter(prefix="/api/medical-knowledge/providers", tags=["medical-knowledge-providers"])


def _service(db: Session = Depends(get_db)):
    registry = create_medical_evidence_provider_registry()
    try:
        yield MedicalEvidenceReviewedService(db, registry)
    finally:
        registry.close()


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, ReviewedProviderSelectionError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ReviewedSourceNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ReviewedProvidersUnavailableError, MedicalEvidenceProviderError)):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="Medical evidence provider operation failed")


@router.post("/search", response_model=ReviewedProviderSearchResponse)
def search_providers(
    payload: ReviewedProviderSearchRequest,
    _actor: User = Depends(require_staff_or_admin),
    service: MedicalEvidenceReviewedService = Depends(_service),
):
    try:
        return service.search(payload)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/lookup", response_model=ReviewedProviderExactLookupResponse)
def lookup_exact_provider(
    payload: ReviewedProviderExactLookupRequest,
    _actor: User = Depends(require_staff_or_admin),
    service: MedicalEvidenceReviewedService = Depends(_service),
):
    try:
        return service.lookup_exact(payload)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/import", response_model=ReviewedProviderImportResponse)
def import_provider_sources(
    payload: ReviewedProviderImportRequest,
    actor: User = Depends(require_staff_or_admin),
    service: MedicalEvidenceReviewedService = Depends(_service),
):
    try:
        return service.import_sources(payload, added_by=actor.id)
    except Exception as exc:
        raise _error(exc) from exc
