from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auto_medical_knowledge_schemas import (
    AutoActionResponse,
    AutoEnqueueRequest,
    AutoMedicalKnowledgeOverviewResponse,
    AutoMedicalKnowledgeSettingsPatch,
    AutoMedicalKnowledgeSettingsResponse,
    AutoTopicVisibilityRequest,
)
from app.config import (
    AUTO_MEDICAL_KNOWLEDGE_INSUFFICIENT_STALE_DAYS,
    AUTO_MEDICAL_KNOWLEDGE_MAX_RETRIES,
    MEDICAL_KNOWLEDGE_LLM_PROVIDER,
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


@router.post("/topics/visibility", response_model=AutoActionResponse)
def set_auto_topic_visibility(
    payload: AutoTopicVisibilityRequest,
    actor: User = Depends(require_staff_or_admin),
    service: AutoMedicalKnowledgeAdminService = Depends(get_auto_admin_service),
):
    try:
        topic, state = service.set_topic_visibility(
            disease_group_id=payload.disease_group_id,
            factor_type=str(payload.factor_type),
            factor_key=str(payload.factor_key),
            factor_value=payload.factor_value,
            weather_factor=payload.weather_factor,
            hidden=payload.hidden,
            actor_user_id=actor.id,
        )
        return AutoActionResponse(
            ok=True,
            topic_id=topic.id,
            message=(
                "Đã ẩn chủ đề Auto khỏi phụ huynh."
                if state.is_hidden_by_staff
                else "Đã hiển thị lại chủ đề Auto theo chính sách hiện hành."
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
        result = queue.regenerate_topic(
            payload, provider=MEDICAL_KNOWLEDGE_LLM_PROVIDER
        )
        messages = {
            "CREATED": "Đã tạo yêu cầu mới.",
            "ALREADY_ACTIVE": "Chủ đề đã có yêu cầu đang xử lý.",
            "WAITING_RETRY": "Chủ đề đang chờ đến thời điểm thử lại.",
            "PROVIDER_COOLDOWN": "Dịch vụ AI đang chờ hết thời gian giới hạn lượt gọi.",
        }
        return AutoActionResponse(
            ok=True,
            job_id=result.job_id,
            created=result.created,
            outcome=result.outcome,
            job_status=result.job_status,
            message=messages[result.outcome],
        )
    except Exception as exc:
        raise _map_error(exc) from exc
