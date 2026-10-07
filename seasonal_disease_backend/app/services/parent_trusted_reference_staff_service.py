from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.medical_knowledge_models import (
    MedicalEvidenceContent as Content, MedicalEvidenceSource as Source,
    MedicalKnowledgeTopic as Topic, MedicalKnowledgeTopicSource as Membership,
)
from app.parent_trusted_reference_models import (
    ParentTrustedReferenceApproval as Approval, ParentTrustedReferenceApprovalEvent as Event,
)
from app.parent_trusted_reference_schemas import (
    ApproveStaffReferenceRequest, CreateStaffReferenceRequest, StaffReferenceHistory,
    StaffReferenceHistoryEvent, StaffReferenceSelector, StaffReferenceSource,
    StaffReferenceState, StaffReferenceStateList, StaffReferenceVersionRequest,
)
from app.services.parent_trusted_reference_curation_service import (
    CurationValidationError, ParentTrustedReferenceCurationService,
)
from app.services.trusted_reference_source_policy import (
    TrustedReferenceDecision, TrustedReferencePolicyResult, TrustedReferenceSourceMetadata,
    _https_identity, evaluate_trusted_reference_source,
)


class StaffReferenceNotFoundError(ValueError):
    pass


class ParentTrustedReferenceStaffService:
    """Safe staff metadata projection and API adapter, without mutation rules.

    All writes/transactions belong to the Phase B service. Reads use persisted
    column projections without autoflush, commits, snapshots or prose. A draft
    with no selected proof reports its unbound policy decision (usually UNCERTAIN).
    This API does not implement the future Parent eligibility predicate.
    """

    def __init__(self, db: Session):
        self.db = db
        self.curation = ParentTrustedReferenceCurationService(db)

    def _one(self, statement, resource: str) -> dict:
        with self.db.no_autoflush:
            row = self.db.execute(statement).mappings().first()
        if row is None:
            raise StaffReferenceNotFoundError(f"{resource} does not exist")
        return dict(row)

    def _topic_id(self, selector: StaffReferenceSelector) -> int:
        selected = selector.service_selector().canonical()
        row = self._one(select(Topic.id).where(*[
            getattr(Topic, key).is_(None) if value is None else getattr(Topic, key) == value
            for key, value in selected.items()
        ]), "Topic for exact selector")
        return row["id"]

    def _approval(self, approval_id: int) -> dict:
        return self._one(select(*[
            column for column in Approval.__table__.c if column.name != "identity_snapshot_json"
        ]).where(Approval.id == approval_id), "Approval")

    def _selector(self, topic_id: int) -> StaffReferenceSelector:
        topic = self._one(select(Topic.disease_group_id, Topic.factor_type, Topic.factor_key,
                                 Topic.factor_value).where(Topic.id == topic_id), "Topic")
        try:
            return StaffReferenceSelector(**topic)
        except ValidationError as exc:
            raise CurationValidationError("Persisted topic selector is not canonical") from exc

    def _source(self, source_id: int) -> dict:
        return self._one(select(Source.id, Source.provider_id, Source.source_type, Source.external_id,
                                Source.source_kind, Source.url, Source.title, Source.journal,
                                Source.publication_year).where(Source.id == source_id), "Source")

    def create(self, payload: CreateStaffReferenceRequest, actor_id: int):
        topic_id = self._topic_id(payload)
        self._source(payload.source_id)
        return self.curation.create_draft(topic_id=topic_id, source_id=payload.source_id,
            selector=payload.service_selector(), actor_id=actor_id,
            sort_order=payload.sort_order, review_note=payload.review_note)

    def approve(self, approval_id: int, payload: ApproveStaffReferenceRequest, actor_id: int):
        self._approval(approval_id)
        self._one(select(Content.id).where(Content.id == payload.evidence_content_id), "Proof")
        return self.curation.approve(approval_id, expected_version=payload.expected_version,
            selector=payload.service_selector(), evidence_content_id=payload.evidence_content_id,
            actor_id=actor_id, review_note=payload.review_note)

    def revoke(self, approval_id: int, payload: StaffReferenceVersionRequest, actor_id: int):
        self._approval(approval_id)
        return self.curation.revoke(approval_id, expected_version=payload.expected_version,
                                   actor_id=actor_id, review_note=payload.review_note)

    def reopen(self, approval_id: int, payload: StaffReferenceVersionRequest, actor_id: int):
        row = self._approval(approval_id)
        selected = self._selector(row["topic_id"])
        return self.curation.reopen(approval_id, expected_version=payload.expected_version,
            selector=selected.service_selector(), actor_id=actor_id, review_note=payload.review_note)

    def _state(self, row: dict, selector: StaffReferenceSelector) -> StaffReferenceState:
        source = self._source(row["source_id"])
        proof = None
        with self.db.no_autoflush:
            if row["evidence_content_id"] is not None:
                proof = self.db.execute(select(Content.source_id, Content.content_origin,
                    Content.external_identifier, Content.provenance_json
                ).where(Content.id == row["evidence_content_id"])).mappings().first()
            in_library = self.db.execute(select(Membership.source_id).where(
                Membership.topic_id == row["topic_id"], Membership.source_id == row["source_id"],
            )).first() is not None
        if proof is not None and proof["source_id"] != row["source_id"]:
            policy = TrustedReferencePolicyResult(TrustedReferenceDecision.UNCERTAIN, "PROOF_SOURCE_MISMATCH")
        else:
            proof = proof or {}
            policy = evaluate_trusted_reference_source(TrustedReferenceSourceMetadata(
                provider_id=source["provider_id"], source_type=source["source_type"],
                external_id=source["external_id"], source_kind=source["source_kind"], original_url=source["url"],
                content_origin=proof.get("content_origin"), content_external_id=proof.get("external_identifier"),
                provenance=proof.get("provenance_json"),
            ))
        fields = {key: row[key] for key in StaffReferenceState.model_fields if key in row}
        display_url = _https_identity(source["url"])
        if display_url is not None and urlsplit(display_url).query:
            # Query strings can contain credentials. They are not display metadata;
            # policy still evaluates the unchanged persisted identity above.
            display_url = None
        return StaffReferenceState(**fields, approval_id=row["id"], selector=selector,
            policy_decision=policy.decision, policy_reason_code=policy.reason_code, source_in_library=in_library,
            source=StaffReferenceSource(source_id=source["id"], original_url=display_url,
                **{key: source[key] for key in StaffReferenceSource.model_fields if key in source}))

    def read_current(self, approval_id: int) -> StaffReferenceState:
        row = self._approval(approval_id)
        return self._state(row, self._selector(row["topic_id"]))

    def list_current(self, selector: StaffReferenceSelector) -> StaffReferenceStateList:
        topic_id = self._topic_id(selector)
        with self.db.no_autoflush:
            rows = self.db.execute(select(*[
                column for column in Approval.__table__.c if column.name != "identity_snapshot_json"
            ]).where(Approval.topic_id == topic_id).order_by(Approval.sort_order, Approval.source_id)).mappings().all()
        return StaffReferenceStateList(topic_id=topic_id, selector=StaffReferenceSelector(
            **selector.service_selector().canonical()), items=[self._state(dict(row), selector) for row in rows])

    def history(self, approval_id: int) -> StaffReferenceHistory:
        self._approval(approval_id)
        with self.db.no_autoflush:
            rows = self.db.execute(select(*[
                getattr(Event, key) for key in StaffReferenceHistoryEvent.model_fields
            ]).where(Event.approval_id == approval_id).order_by(Event.resulting_version, Event.id)).mappings().all()
        return StaffReferenceHistory(approval_id=approval_id,
                                    events=[StaffReferenceHistoryEvent(**dict(row)) for row in rows])
