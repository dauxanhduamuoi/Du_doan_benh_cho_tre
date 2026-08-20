from __future__ import annotations

import logging
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import NCBI_API_KEY, NCBI_EMAIL, NCBI_TOOL
from app.database import get_db
from app.models import User
from app.pubmed_schemas import (
    MedicalKnowledgeOptionsResponse,
    PubMedImportRequest,
    PubMedImportResponse,
    PubMedSearchRequest,
    PubMedSearchResponse,
)
from app.security import require_staff_or_admin
from app.services.medical_knowledge_pubmed_service import (
    DiseaseGroupNotFoundError,
    DiseaseUniverseConfigurationError,
    MedicalKnowledgePubMedService,
    get_medical_knowledge_options,
)
from app.services.pubmed_client import (
    PubMedClient,
    PubMedConfigurationError,
    PubMedRateLimitError,
    PubMedUnavailableError,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/medical-knowledge/pubmed", tags=["Medical Knowledge PubMed"])
options_router = APIRouter(prefix="/api/medical-knowledge", tags=["Medical Knowledge"])


def get_pubmed_service(db: Session = Depends(get_db)) -> Generator[MedicalKnowledgePubMedService, None, None]:
    client = PubMedClient(tool=NCBI_TOOL, email=NCBI_EMAIL, api_key=NCBI_API_KEY)
    try:
        yield MedicalKnowledgePubMedService(db, client)
    finally:
        client.close()


def _map_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DiseaseGroupNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (PubMedConfigurationError, DiseaseUniverseConfigurationError)):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, PubMedRateLimitError):
        return HTTPException(status_code=503, detail="PubMed rate limit is temporarily unavailable")
    if isinstance(exc, PubMedUnavailableError):
        return HTTPException(status_code=502, detail=str(exc))
    logger.exception("Medical Knowledge PubMed operation failed")
    return HTTPException(status_code=500, detail="Medical Knowledge PubMed operation failed")


@options_router.get("/options", response_model=MedicalKnowledgeOptionsResponse)
def medical_knowledge_options(_current_user: User = Depends(require_staff_or_admin)):
    try:
        return get_medical_knowledge_options()
    except DiseaseUniverseConfigurationError as exc:
        raise _map_service_error(exc) from exc


@router.post("/search", response_model=PubMedSearchResponse)
def search_pubmed(
    payload: PubMedSearchRequest,
    _current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgePubMedService = Depends(get_pubmed_service),
):
    try:
        return service.search(payload)
    except Exception as exc:
        raise _map_service_error(exc) from exc


@router.post("/import", response_model=PubMedImportResponse)
def import_pubmed_sources(
    payload: PubMedImportRequest,
    _current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgePubMedService = Depends(get_pubmed_service),
):
    try:
        return service.import_pmids(payload)
    except Exception as exc:
        raise _map_service_error(exc) from exc
