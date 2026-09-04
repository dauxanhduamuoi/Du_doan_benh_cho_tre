from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.medical_knowledge_draft_schemas import (
    MedicalKnowledgeDraftProposal,
    RevisionApprovalResponse,
    SourceAssessment,
)
from app.models import User
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.services.medical_knowledge_population_policy import (
    has_pediatric_direct_support,
    stored_source_assessment,
)


class ApprovalWorkflowError(ValueError):
    pass


class ApprovalNotFoundError(ApprovalWorkflowError):
    pass


class ApprovalConflictError(ApprovalWorkflowError):
    pass


class ApprovalValidationError(ApprovalWorkflowError):
    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


class MedicalKnowledgeApprovalService:
    """Validate and atomically freeze one DRAFT revision as APPROVED."""

    def __init__(
        self,
        db: Session,
        *,
        clock: Callable[[], datetime] = datetime.utcnow,
    ):
        self.db = db
        self.repository = MedicalKnowledgeRepository(db)
        self.clock = clock

    def approve(self, revision_id: int, *, approved_by: int) -> RevisionApprovalResponse:
        revision = self.repository.get_revision_with_sources(revision_id)
        if revision is None:
            raise ApprovalNotFoundError("Medical knowledge revision was not found")
        if revision.status != "DRAFT":
            raise ApprovalConflictError("Only DRAFT revisions can be approved")

        reviewer = self.db.get(User, approved_by)
        if reviewer is None or not reviewer.is_active or reviewer.role not in {"staff", "admin"}:
            raise ApprovalValidationError("The authenticated reviewer is not eligible to approve")

        self._validate_revision(revision)
        published_revision_id = revision.topic.published_revision_id
        approved_at = self.clock()
        if not self.repository.approve_revision_if_draft(
            revision_id,
            approved_by=reviewer.id,
            approved_at=approved_at,
        ):
            self.db.rollback()
            raise ApprovalConflictError("Only DRAFT revisions can be approved")
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return RevisionApprovalResponse(
            revision_id=revision_id,
            status="APPROVED",
            approved_by=reviewer.id,
            approved_by_name=reviewer.full_name or reviewer.username,
            approved_at=approved_at,
            parent_display_allowed=False,
            published_revision_id=published_revision_id,
        )

    @staticmethod
    def _validate_revision(revision) -> None:
        if revision.topic is None:
            raise ApprovalValidationError("Revision topic is invalid")
        if revision.parent_display_allowed:
            raise ApprovalValidationError("DRAFT revision must not be parent-visible")
        if not revision.source_links:
            raise ApprovalValidationError("Revision must contain at least one evidence source")

        assessments: list[SourceAssessment] = []
        for link in revision.source_links:
            if link.source is None:
                raise ApprovalValidationError("Revision evidence links are incomplete")
            if (
                link.evidence_content is not None
                and link.evidence_content.source_id != link.source_id
            ):
                raise ApprovalValidationError(
                    "Revision evidence content belongs to a different source"
                )
            evidence_text = (
                link.evidence_content.evidence_text
                if link.evidence_content is not None
                else link.source.abstract_text or ""
            )
            if not evidence_text.strip():
                raise ApprovalValidationError("Revision evidence content is empty")
            assessment = stored_source_assessment(link)
            if assessment is None:
                raise ApprovalValidationError("Revision source assessment is invalid")
            assessments.append(assessment)

        try:
            MedicalKnowledgeDraftProposal(
                evidence_level=revision.evidence_level,
                evidence_scope=revision.evidence_scope,
                short_explanation_vi=revision.short_explanation_vi,
                detailed_explanation_vi=revision.detailed_explanation_vi,
                limitations_vi=revision.limitations_vi,
                source_assessments=assessments,
            )
        except ValidationError as exc:
            raise ApprovalValidationError("Revision structured content is invalid") from exc
        if revision.evidence_level == "SUPPORTED" and not has_pediatric_direct_support(
            assessments
        ):
            raise ApprovalValidationError(
                "SUPPORTED requires a directly supportive pediatric source before approval",
                code="APPROVAL_PEDIATRIC_SUPPORT_REQUIRED",
            )
