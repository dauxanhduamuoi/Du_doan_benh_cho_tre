from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    PrimaryKeyConstraint, String, Unicode, UniqueConstraint, column, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app import medical_knowledge_models, models  # noqa: F401 - register referenced tables


PARENT_REFERENCE_STATUSES = ("DRAFT", "APPROVED", "REVOKED")
PARENT_REFERENCE_ACTIONS = (
    "CREATE_DRAFT", "APPROVE", "REVOKE", "REOPEN_DRAFT", "UPDATE_DRAFT",
)


def _choices(name: str, values: tuple[str, ...]) -> str:
    return f"{name} IN ({', '.join(repr(value) for value in values)})"


def _hash_constraint(name: str) -> CheckConstraint:
    # SQLAlchemy compiles length() as SQLite length() / MSSQL LEN().
    value = column("identity_sha256")
    return CheckConstraint(value.is_(None) | (func.length(value) == 64), name=name)


class ParentTrustedReferenceApproval(Base):
    """Selector-scoped reference curation, independent of prose publication.

    APPROVED will mean approve-and-show once the curation service/read path exists.
    Phase A stores state only; it does not authorize or infer source trust.
    """

    __tablename__ = "parent_trusted_reference_approvals"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_parent_ref_approval"),
        UniqueConstraint("topic_id", "source_id", name="uq_parent_ref_approval_topic_source"),
        CheckConstraint(_choices("status", PARENT_REFERENCE_STATUSES), name="ck_parent_ref_approval_status"),
        CheckConstraint("sort_order >= 0", name="ck_parent_ref_approval_sort_order"),
        CheckConstraint("version > 0", name="ck_parent_ref_approval_version"),
        _hash_constraint("ck_parent_ref_approval_identity_hash_length"),
        Index("ix_parent_ref_approval_topic_status_order", "topic_id", "status", "sort_order", "source_id"),
        Index("ix_parent_ref_approval_source", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_topics.id", name="fk_parent_ref_approval_topic", ondelete="NO ACTION"), nullable=False,
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("medical_evidence_sources.id", name="fk_parent_ref_approval_source", ondelete="NO ACTION"), nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", server_default="DRAFT", nullable=False)
    evidence_content_id: Mapped[int | None] = mapped_column(
        ForeignKey("medical_evidence_contents.id", name="fk_parent_ref_approval_proof", ondelete="NO ACTION"), nullable=True,
    )
    identity_snapshot_json: Mapped[dict | list | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    identity_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_parent_ref_approval_creator", ondelete="NO ACTION"), nullable=True,
    )
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_parent_ref_approval_approver", ondelete="NO ACTION"), nullable=True,
    )
    revoked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_parent_ref_approval_revoker", ondelete="NO ACTION"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ParentTrustedReferenceApprovalEvent(Base):
    """Append-only by repository convention; transition orchestration is Phase B."""

    __tablename__ = "parent_trusted_reference_approval_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_parent_ref_event"),
        UniqueConstraint("approval_id", "resulting_version", name="uq_parent_ref_event_approval_version"),
        CheckConstraint(_choices("action", PARENT_REFERENCE_ACTIONS), name="ck_parent_ref_event_action"),
        CheckConstraint("from_status IS NULL OR " + _choices("from_status", PARENT_REFERENCE_STATUSES), name="ck_parent_ref_event_from_status"),
        CheckConstraint(_choices("to_status", PARENT_REFERENCE_STATUSES), name="ck_parent_ref_event_to_status"),
        CheckConstraint("resulting_version > 0", name="ck_parent_ref_event_version"),
        _hash_constraint("ck_parent_ref_event_identity_hash_length"),
        CheckConstraint(func.length(column("review_note")) <= 1000, name="ck_parent_ref_event_review_note_length"),
        Index("ix_parent_ref_event_actor_time", "actor_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[int] = mapped_column(
        ForeignKey("parent_trusted_reference_approvals.id", name="fk_parent_ref_event_approval", ondelete="NO ACTION"), nullable=False,
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_parent_ref_event_actor", ondelete="NO ACTION"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Unicode(1000), nullable=True)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    identity_snapshot_json: Mapped[dict | list | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    identity_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
