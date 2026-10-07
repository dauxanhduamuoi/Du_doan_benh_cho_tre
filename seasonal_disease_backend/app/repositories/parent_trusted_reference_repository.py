from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.parent_trusted_reference_models import (
    ParentTrustedReferenceApproval,
    ParentTrustedReferenceApprovalEvent,
)
from app.medical_knowledge_models import (
    MedicalKnowledgeTopic as Topic, MedicalEvidenceSource as Source,
    MedicalEvidenceContent as Content, MedicalKnowledgeTopicSource as Membership,
)


class ParentTrustedReferenceRepository:
    """Transaction-neutral persistence only; no policy or state-transition service.

    Writes flush for generated IDs/constraints but never commit. Pure reads do not
    flush unrelated pending ORM changes. Membership, proof ownership, auth,
    fingerprinting and atomic versioned transitions belong to Phase B.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, approval_id: int) -> ParentTrustedReferenceApproval | None:
        with self.db.no_autoflush:
            return self.db.get(ParentTrustedReferenceApproval, approval_id)

    def get_approved_reference_metadata(self, selectors: list[tuple[str, str, str, str | None]]):
        """One batch SELECT rooted in curation, with exact membership/selected proof.

        No publication pointers, revisions, prose, evidence body or write path.
        Snapshot/hash/policy validation remains in the response service.
        """
        if not selectors:
            return []
        approval = ParentTrustedReferenceApproval
        matches = [and_(
            Topic.disease_group_id == disease, Topic.factor_type == factor_type,
            Topic.factor_key == key, Topic.factor_value.is_(None) if value is None else Topic.factor_value == value,
        ) for disease, factor_type, key, value in selectors]
        statement = select(
            Topic.disease_group_id, Topic.factor_type, Topic.factor_key, Topic.factor_value,
            approval.identity_snapshot_json, approval.identity_sha256, approval.policy_version,
            Source.id.label("source_id"), Source.provider_id, Source.external_id, Source.source_type,
            Source.source_kind, Source.title, Source.journal, Source.publication_year, Source.url.label("original_url"),
            Content.id.label("proof_id"), Content.source_id.label("proof_source_id"), Content.content_kind,
            Content.content_origin, Content.external_identifier.label("content_external_id"),
            Content.provenance_json.label("provenance"), Content.content_sha256,
        ).select_from(approval).join(Topic, Topic.id == approval.topic_id).join(
            Source, Source.id == approval.source_id,
        ).join(Membership, and_(Membership.topic_id == approval.topic_id, Membership.source_id == approval.source_id)).join(
            Content, and_(Content.id == approval.evidence_content_id, Content.source_id == approval.source_id),
        ).where(
            approval.status == "APPROVED", approval.revoked_at.is_(None), approval.revoked_by.is_(None), or_(*matches),
        ).order_by(Topic.id, approval.sort_order, Source.id)
        with self.db.no_autoflush:
            return list(self.db.execute(statement).mappings())

    def get_persisted_state(self, approval_id: int) -> dict | None:
        """Read database columns, independently of cached ORM instances."""
        with self.db.no_autoflush:
            row = self.db.execute(select(*ParentTrustedReferenceApproval.__table__.c).where(
                ParentTrustedReferenceApproval.id == approval_id,
            )).mappings().first()
            return dict(row) if row is not None else None

    def compare_and_swap(self, approval_id: int, expected_version: int, values: dict) -> bool:
        """Conditional persistence primitive; the service supplies transition values."""
        with self.db.no_autoflush:
            result = self.db.execute(update(ParentTrustedReferenceApproval).where(
                ParentTrustedReferenceApproval.id == approval_id,
                ParentTrustedReferenceApproval.version == expected_version,
            ).values(**values, version=expected_version + 1).execution_options(synchronize_session=False))
            return result.rowcount == 1

    def get_by_topic_source(self, topic_id: int, source_id: int) -> ParentTrustedReferenceApproval | None:
        with self.db.no_autoflush:
            return self.db.scalar(select(ParentTrustedReferenceApproval).where(
                ParentTrustedReferenceApproval.topic_id == topic_id,
                ParentTrustedReferenceApproval.source_id == source_id,
            ))

    def list_for_topic(self, topic_id: int) -> list[ParentTrustedReferenceApproval]:
        with self.db.no_autoflush:
            return list(self.db.scalars(select(ParentTrustedReferenceApproval).where(
                ParentTrustedReferenceApproval.topic_id == topic_id,
            ).order_by(
                ParentTrustedReferenceApproval.sort_order,
                ParentTrustedReferenceApproval.source_id,
            )))

    def create_draft(
        self, *, topic_id: int, source_id: int, created_by: int | None = None,
        evidence_content_id: int | None = None, identity_snapshot_json: dict | list | None = None,
        identity_sha256: str | None = None, policy_version: str | None = None, sort_order: int = 0,
        created_at: datetime | None = None,
    ) -> ParentTrustedReferenceApproval:
        record = ParentTrustedReferenceApproval(
            topic_id=topic_id, source_id=source_id, status="DRAFT", version=1,
            created_by=created_by, evidence_content_id=evidence_content_id,
            identity_snapshot_json=identity_snapshot_json, identity_sha256=identity_sha256,
            policy_version=policy_version, sort_order=sort_order,
        )
        if created_at is not None:
            record.created_at = record.updated_at = created_at
        self.db.add(record)
        self.db.flush()
        return record

    def append_event(
        self, *, approval_id: int, action: str, from_status: str | None,
        to_status: str, resulting_version: int, actor_user_id: int | None = None,
        review_note: str | None = None, identity_snapshot_json: dict | list | None = None,
        identity_sha256: str | None = None, policy_version: str | None = None,
        created_at: datetime | None = None,
    ) -> ParentTrustedReferenceApprovalEvent:
        record = ParentTrustedReferenceApprovalEvent(
            approval_id=approval_id, action=action, from_status=from_status, to_status=to_status,
            resulting_version=resulting_version, actor_user_id=actor_user_id, review_note=review_note,
            identity_snapshot_json=identity_snapshot_json, identity_sha256=identity_sha256,
            policy_version=policy_version,
        )
        if created_at is not None:
            record.created_at = created_at
        self.db.add(record)
        self.db.flush()
        return record

    def list_events(self, approval_id: int) -> list[ParentTrustedReferenceApprovalEvent]:
        with self.db.no_autoflush:
            return list(self.db.scalars(select(ParentTrustedReferenceApprovalEvent).where(
                ParentTrustedReferenceApprovalEvent.approval_id == approval_id,
            ).order_by(ParentTrustedReferenceApprovalEvent.resulting_version)))
