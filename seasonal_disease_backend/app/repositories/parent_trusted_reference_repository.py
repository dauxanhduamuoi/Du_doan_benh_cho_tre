from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.parent_trusted_reference_models import (
    ParentTrustedReferenceApproval,
    ParentTrustedReferenceApprovalEvent,
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
