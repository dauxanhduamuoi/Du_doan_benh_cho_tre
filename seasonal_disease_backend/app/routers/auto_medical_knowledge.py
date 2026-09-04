from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auto_medical_knowledge_schemas import (
    AutoActionResponse,
    AutoEnqueueRequest,
    AutoMedicalKnowledgeOverviewResponse,
    AutoMedicalKnowledgeSettingsPatch,
    AutoMedicalKnowledgeSettingsResponse,
    AutoVisibilityRequest,
)
from app.config import (
    AUTO_MEDICAL_KNOWLEDGE_INSUFFICIENT_STALE_DAYS,
    AUTO_MEDICAL_KNOWLEDGE_MAX_RETRIES,
)
from app.database import get_db
from app.models import User
from app.security import require_admin, require_staff_or_admin
from app.services.auto_medical_knowledge_service import (
    AutoMedicalKnowledgeAdminService,
    AutoMedicalKnowledgeConflictError,
    AutoMedicalKnowledgeNotFoundError,
    AutoMedicalKnowledgeQueueService,
    AutoMedicalKnowledgeValidationError,
)


router = APIRouter(prefix="/api/medical-knowledge/auto", tags=["Auto Medical Knowledge"])


def get_auto_queue_service(db: Session = Depends(get_db)) -> AutoMedicalKnowledgeQueueService:
    return AutoMedicalKnowledgeQueueService(
        db,
        max_retries=AUTO_MEDICAL_KNOWLEDGE_MAX_RETRIES,
        insufficient_stale_days=AUTO_MEDICAL_KNOWLEDGE_INSUFFICIENT_STALE_DAYS,
    )


def get_auto_admin_service(
    db: Session = Depends(get_db),
    queue: AutoMedicalKnowledgeQueueService = Depends(get_auto_queue_service),
) -> AutoMedicalKnowledgeAdminService:
    return AutoMedicalKnowledgeAdminService(
        db,
        queue_service=queue,
    )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AutoMedicalKnowledgeNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AutoMedicalKnowledgeConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AutoMedicalKnowledgeValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="Auto Medical Knowledge operation failed")


@router.get("", response_model=AutoMedicalKnowledgeOverviewResponse)
def get_auto_overview(
    _user: User = Depends(require_staff_or_admin),
    service: AutoMedicalKnowledgeAdminService = Depends(get_auto_admin_service),
):
    return service.overview()


@router.patch("/settings", response_model=AutoMedicalKnowledgeSettingsResponse)
def update_auto_settings(
    payload: AutoMedicalKnowledgeSettingsPatch,
    _admin: User = Depends(require_admin),
    service: AutoMedicalKnowledgeAdminService = Depends(get_auto_admin_service),
):
    return service.update_settings(**payload.model_dump(exclude_unset=True))


@router.post("/revisions/{revision_id}/visibility", response_model=AutoActionResponse)
def set_auto_visibility(
    revision_id: int,
    payload: AutoVisibilityRequest,
    _admin: User = Depends(require_admin),
    service: AutoMedicalKnowledgeAdminService = Depends(get_auto_admin_service),
):
    try:
        revision = service.set_visibility(revision_id, is_visible=payload.is_visible)
        return AutoActionResponse(
            ok=True,
            revision_id=revision.id,
            message=(
                "Đã cho phép hiển thị nội dung Auto. Đây không phải phê duyệt y khoa."
                if revision.is_visible
                else "Đã ẩn nội dung Auto khỏi phụ huynh."
            ),
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/jobs/{job_id}/retry", response_model=AutoActionResponse)
def retry_auto_job(
    job_id: int,
    _admin: User = Depends(require_admin),
    service: AutoMedicalKnowledgeAdminService = Depends(get_auto_admin_service),
):
    try:
        retried = service.retry_job(job_id)
        return AutoActionResponse(ok=True, job_id=retried, message="Đã đưa job vào hàng đợi lại.")
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/regenerate", response_model=AutoActionResponse)
def regenerate_auto_topic(
    payload: AutoEnqueueRequest,
    _admin: User = Depends(require_admin),
    queue: AutoMedicalKnowledgeQueueService = Depends(get_auto_queue_service),
):
    try:
        job_ids = queue.enqueue_selectors([payload], trigger_type="ADMIN", force=True)
        if not job_ids:
            raise AutoMedicalKnowledgeConflictError(
                "Auto Medical Knowledge đang tắt hoặc topic đã có job đang xử lý"
            )
        return AutoActionResponse(ok=True, job_id=job_ids[0], message="Đã xếp hàng tạo lại Auto Knowledge.")
    except Exception as exc:
        raise _map_error(exc) from exc
