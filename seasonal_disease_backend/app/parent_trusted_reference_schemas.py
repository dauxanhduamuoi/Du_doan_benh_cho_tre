from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.parent_trusted_reference_curation_service import CurationSelector
from app.services.trusted_reference_source_policy import TrustedReferenceDecision


class StaffReferenceDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StaffReferenceSelector(StaffReferenceDTO):
    disease_group_id: str = Field(pattern=r"^[0-9]{1,6}$", max_length=6)
    factor_type: Literal["WEATHER", "AGE", "SEX", "SEASONALITY"]
    factor_key: str = Field(min_length=1, max_length=32)
    factor_value: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_exact_selector(self):
        self.service_selector().canonical()
        return self

    def service_selector(self) -> CurationSelector:
        return CurationSelector(self.disease_group_id, self.factor_type, self.factor_key, self.factor_value)


class CreateStaffReferenceRequest(StaffReferenceSelector):
    source_id: int = Field(strict=True, gt=0)
    sort_order: int = Field(default=0, strict=True, ge=0)
    review_note: str | None = Field(default=None, max_length=1000)


class StaffReferenceVersionRequest(StaffReferenceDTO):
    expected_version: int = Field(strict=True, gt=0)
    review_note: str | None = Field(default=None, max_length=1000)


class ApproveStaffReferenceRequest(StaffReferenceSelector, StaffReferenceVersionRequest):
    evidence_content_id: int = Field(strict=True, gt=0)


class StaffReferenceMutationResponse(StaffReferenceDTO):
    approval_id: int
    status: Literal["DRAFT", "APPROVED", "REVOKED"]
    version: int
    evidence_content_id: int | None
    identity_sha256: str | None
    changed: bool
    policy_decision: TrustedReferenceDecision | None = None


class StaffReferenceSource(StaffReferenceDTO):
    source_id: int
    provider_id: str | None
    source_type: str
    external_id: str | None
    source_kind: str | None
    title: str
    journal: str | None
    publication_year: int | None
    original_url: str | None


class StaffReferenceState(StaffReferenceDTO):
    approval_id: int
    topic_id: int
    source_id: int
    selector: StaffReferenceSelector
    status: Literal["DRAFT", "APPROVED", "REVOKED"]
    version: int
    sort_order: int
    evidence_content_id: int | None
    identity_sha256: str | None
    policy_version: str | None
    policy_decision: TrustedReferenceDecision
    policy_reason_code: str
    source_in_library: bool
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    approved_by: int | None
    approved_at: datetime | None
    revoked_by: int | None
    revoked_at: datetime | None
    source: StaffReferenceSource


class StaffReferenceStateList(StaffReferenceDTO):
    topic_id: int
    selector: StaffReferenceSelector
    items: list[StaffReferenceState]


class StaffReferenceHistoryEvent(StaffReferenceDTO):
    id: int
    action: Literal["CREATE_DRAFT", "APPROVE", "REVOKE", "REOPEN_DRAFT", "UPDATE_DRAFT"]
    from_status: Literal["DRAFT", "APPROVED", "REVOKED"] | None
    to_status: Literal["DRAFT", "APPROVED", "REVOKED"]
    actor_user_id: int | None
    created_at: datetime
    resulting_version: int
    review_note: str | None
    policy_version: str | None
    identity_sha256: str | None


class StaffReferenceHistory(StaffReferenceDTO):
    approval_id: int
    events: list[StaffReferenceHistoryEvent]


class StaffReferenceProofQuery(StaffReferenceSelector):
    source_id: int = Field(gt=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=100)


class StaffReferenceProofCandidate(StaffReferenceDTO):
    evidence_content_id: int
    source_id: int
    content_kind: str
    content_origin: str
    external_identifier: str | None
    retrieved_at: datetime
    content_sha256: str
    policy_decision: TrustedReferenceDecision
    policy_reason_code: str


class StaffReferenceProofCandidates(StaffReferenceDTO):
    selector: StaffReferenceSelector
    topic_id: int
    source_id: int
    source: StaffReferenceSource
    candidates: list[StaffReferenceProofCandidate] = Field(max_length=100)
    next_offset: int | None
