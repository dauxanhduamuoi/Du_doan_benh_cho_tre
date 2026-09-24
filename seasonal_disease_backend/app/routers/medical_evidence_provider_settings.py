from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.medical_evidence_provider_settings_schemas import (
    MedicalEvidenceProviderSettingPatch,
    MedicalEvidenceProviderSettingsResponse,
)
from app.models import User
from app.security import require_admin, require_staff_or_admin
from app.services.medical_evidence_provider_factory import (
    create_medical_evidence_provider_registry,
)
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingNotFoundError,
    MedicalEvidenceProviderSettingsService,
)


router = APIRouter(prefix="/api/medical-knowledge/providers", tags=["medical-knowledge-providers"])


def _service(db: Session = Depends(get_db)):
    registry = create_medical_evidence_provider_registry()
    try:
        yield MedicalEvidenceProviderSettingsService(db, registry)
    finally:
        registry.close()


@router.get("/settings", response_model=MedicalEvidenceProviderSettingsResponse)
def read_provider_settings(
    _actor: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
    service: MedicalEvidenceProviderSettingsService = Depends(_service),
):
    response = service.read()
    db.commit()  # persist reconciliation for newly registered providers
    return response


@router.patch("/settings", response_model=MedicalEvidenceProviderSettingsResponse)
def update_provider_setting(
    payload: MedicalEvidenceProviderSettingPatch,
    actor: User = Depends(require_admin),
    service: MedicalEvidenceProviderSettingsService = Depends(_service),
):
    try:
        return service.update(
            provider_id=payload.provider_id,
            workflow=payload.workflow,
            enabled=payload.enabled,
            actor_user_id=actor.id,
        )
    except MedicalEvidenceProviderSettingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
