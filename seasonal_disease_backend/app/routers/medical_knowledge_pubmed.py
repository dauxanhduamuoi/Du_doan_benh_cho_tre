from __future__ import annotations

import logging
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.medical_knowledge_factors import normalize_factor
from app.pubmed_schemas import (
    MedicalKnowledgeOptionsResponse,
    MedicalKnowledgeTopicSourceLibraryResponse,
    PubMedImportRequest,
    PubMedImportResponse,
    PubMedLookupRequest,
    PubMedLookupResponse,
    PubMedSearchRequest,
    PubMedSearchResponse,
)
from app.security import require_staff_or_admin
from app.services.medical_knowledge_pubmed_service import (
    DiseaseGroupNotFoundError,
    DiseaseUniverseConfigurationError,
    MedicalKnowledgePubMedService,
    PubMedArticleNotFoundError,
    get_medical_knowledge_options,
)
from app.services.medical_evidence_provider import (
    MedicalEvidenceProviderBadResponseError,
    MedicalEvidenceProviderConfigurationError,
    MedicalEvidenceProviderRateLimitedError,
    MedicalEvidenceProviderTimeoutError,
    MedicalEvidenceProviderUnavailableError,
)
from app.services.medical_evidence_provider_factory import (
    create_medical_evidence_provider_registry,
)
from app.services.pubmed_client import PubMedRateLimitError, PubMedUnavailableError


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/medical-knowledge/pubmed", tags=["Medical Knowledge PubMed"])
options_router = APIRouter(prefix="/api/medical-knowledge", tags=["Medical Knowledge"])


def get_pubmed_service(db: Session = Depends(get_db)) -> Generator[MedicalKnowledgePubMedService, None, None]:
    registry = create_medical_evidence_provider_registry()
    try:
        yield MedicalKnowledgePubMedService(db, registry.get("PUBMED"))
    finally:
        registry.close()


def _map_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PubMedArticleNotFoundError):
        return HTTPException(status_code=404, detail="PubMed article was not found")
    if isinstance(exc, DiseaseGroupNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (MedicalEvidenceProviderConfigurationError, DiseaseUniverseConfigurationError)):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, (MedicalEvidenceProviderRateLimitedError, PubMedRateLimitError)):
        return HTTPException(status_code=503, detail="PubMed rate limit is temporarily unavailable")
    if isinstance(
        exc,
        (
            MedicalEvidenceProviderTimeoutError,
            MedicalEvidenceProviderBadResponseError,
            MedicalEvidenceProviderUnavailableError,
            PubMedUnavailableError,
        ),
    ):
        return HTTPException(status_code=502, detail=str(exc))
    logger.exception("Medical Knowledge PubMed operation failed")
    return HTTPException(status_code=500, detail="Medical Knowledge PubMed operation failed")


@options_router.get("/options", response_model=MedicalKnowledgeOptionsResponse)
def medical_knowledge_options(_current_user: User = Depends(require_staff_or_admin)):
    try:
        return get_medical_knowledge_options()
    except DiseaseUniverseConfigurationError as exc:
        raise _map_service_error(exc) from exc


@options_router.get(
    "/topic-sources", response_model=MedicalKnowledgeTopicSourceLibraryResponse
)
def get_topic_source_library(
    disease_group_id: str = Query(min_length=1, max_length=100),
    factor_type: str | None = Query(default=None, max_length=16),
    factor_key: str | None = Query(default=None, max_length=32),
    factor_value: str | None = Query(default=None, max_length=100),
    weather_factor: str | None = Query(default=None, max_length=32),
    _current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgePubMedService = Depends(get_pubmed_service),
):
    try:
        factor = normalize_factor(
            factor_type=factor_type,
            factor_key=factor_key,
            factor_value=factor_value,
            weather_factor=weather_factor,
        )
        if factor.factor_type == "WEATHER" and factor_type is None and factor_key is None:
            return service.get_topic_source_library(
                disease_group_id=disease_group_id,
                weather_factor=factor.weather_factor,
            )
        return service.get_topic_source_library(
            disease_group_id=disease_group_id,
            factor_type=factor.factor_type,
            factor_key=factor.factor_key,
            factor_value=factor.factor_value,
            weather_factor=factor.weather_factor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
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


@router.post("/lookup", response_model=PubMedLookupResponse)
def lookup_pubmed_article(
    payload: PubMedLookupRequest,
    _current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgePubMedService = Depends(get_pubmed_service),
):
    try:
        return service.lookup_pmid(payload)
    except Exception as exc:
        raise _map_service_error(exc) from exc


@router.post("/import", response_model=PubMedImportResponse)
def import_pubmed_sources(
    payload: PubMedImportRequest,
    current_user: User = Depends(require_staff_or_admin),
    service: MedicalKnowledgePubMedService = Depends(get_pubmed_service),
):
    try:
        return service.import_pmids(payload, added_by=current_user.id)
    except Exception as exc:
        raise _map_service_error(exc) from exc
