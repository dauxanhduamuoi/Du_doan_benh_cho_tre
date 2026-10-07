from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.parent_trusted_reference_schemas import (
    ApproveStaffReferenceRequest, CreateStaffReferenceRequest, StaffReferenceHistory,
    StaffReferenceMutationResponse, StaffReferenceSelector, StaffReferenceState,
    StaffReferenceStateList, StaffReferenceVersionRequest,
)
from app.security import require_staff_or_admin
from app.services.parent_trusted_reference_curation_service import CurationConflictError, CurationValidationError
from app.services.parent_trusted_reference_staff_service import (
    ParentTrustedReferenceStaffService, StaffReferenceNotFoundError,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/medical-knowledge/parent-references", tags=["Parent Reference Curation"])


def get_staff_reference_service(db: Session = Depends(get_db)) -> ParentTrustedReferenceStaffService:
    return ParentTrustedReferenceStaffService(db)


Actor = Annotated[User, Depends(require_staff_or_admin)]
Service = Annotated[ParentTrustedReferenceStaffService, Depends(get_staff_reference_service)]
ApprovalID = Annotated[int, Path(gt=0)]


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, StaffReferenceNotFoundError):
        return HTTPException(404, detail={"code": "CURATION_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, CurationConflictError):
        return HTTPException(409, detail={"code": "CURATION_CONFLICT", "message": str(exc)})
    if isinstance(exc, CurationValidationError):
        # Phase B represents these three state errors as validation errors.
        # Map their fixed contract messages to the existing workflow conflict convention.
        if str(exc) in {
            "Only DRAFT can transition to APPROVED", "Only APPROVED can transition to REVOKED",
            "Only REVOKED can transition to DRAFT",
        }:
            return HTTPException(409, detail={"code": "CURATION_STATE_CONFLICT", "message": str(exc)})
        return HTTPException(422, detail={"code": "CURATION_VALIDATION", "message": str(exc)})
    logger.exception("Parent reference curation operation failed")
    return HTTPException(500, detail={"code": "CURATION_OPERATION_FAILED", "message": "Curation operation failed"})


@router.post("", response_model=StaffReferenceMutationResponse, status_code=201)
def create_reference(payload: CreateStaffReferenceRequest, actor: Actor, service: Service):
    try:
        return service.create(payload, actor.id)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("", response_model=StaffReferenceStateList)
def list_references(selector: Annotated[StaffReferenceSelector, Query()], _actor: Actor, service: Service):
    try:
        return service.list_current(selector)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/{approval_id}", response_model=StaffReferenceState)
def read_reference(approval_id: ApprovalID, _actor: Actor, service: Service):
    try:
        return service.read_current(approval_id)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/{approval_id}/history", response_model=StaffReferenceHistory)
def reference_history(approval_id: ApprovalID, _actor: Actor, service: Service):
    try:
        return service.history(approval_id)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/{approval_id}/approve", response_model=StaffReferenceMutationResponse)
def approve_reference(approval_id: ApprovalID, payload: ApproveStaffReferenceRequest, actor: Actor, service: Service):
    try:
        return service.approve(approval_id, payload, actor.id)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/{approval_id}/revoke", response_model=StaffReferenceMutationResponse)
def revoke_reference(approval_id: ApprovalID, payload: StaffReferenceVersionRequest, actor: Actor, service: Service):
    try:
        return service.revoke(approval_id, payload, actor.id)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/{approval_id}/reopen", response_model=StaffReferenceMutationResponse)
def reopen_reference(approval_id: ApprovalID, payload: StaffReferenceVersionRequest, actor: Actor, service: Service):
    try:
        return service.reopen(approval_id, payload, actor.id)
    except Exception as exc:
        raise _map_error(exc) from exc
