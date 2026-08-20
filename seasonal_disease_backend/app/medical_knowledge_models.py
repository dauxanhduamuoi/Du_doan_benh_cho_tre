from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


WEATHER_FACTORS = (
    "temperature",
    "humidity",
    "precipitation",
    "wind",
    "weather_condition",
)
EVIDENCE_LEVELS = ("SUPPORTED", "LIMITED_OR_INDIRECT", "CONFLICTING", "INSUFFICIENT")
EVIDENCE_SCOPES = ("WHOLE_GROUP", "PARTIAL_GROUP")
REVISION_STATUSES = ("DRAFT", "APPROVED", "REJECTED")
SOURCE_TYPES = ("PUBMED", "WHO", "CDC", "OTHER")
SOURCE_ROLES = ("PRIMARY", "SUPPORTING")


def _allowed(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class MedicalKnowledgeTopic(Base):
    __tablename__ = "medical_knowledge_topics"
    __table_args__ = (
        UniqueConstraint("disease_group_id", "weather_factor", name="uq_medical_topics_group_factor"),
        CheckConstraint(_allowed("weather_factor", WEATHER_FACTORS), name="ck_medical_topics_weather_factor"),
        Index("ix_medical_topics_disease_group_id", "disease_group_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disease_group_id: Mapped[str] = mapped_column(String(100), nullable=False)
    weather_factor: Mapped[str] = mapped_column(String(32), nullable=False)
    published_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("medical_knowledge_revisions.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    revisions: Mapped[list[MedicalKnowledgeRevision]] = relationship(
        back_populates="topic",
        foreign_keys="MedicalKnowledgeRevision.topic_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    published_revision: Mapped[MedicalKnowledgeRevision | None] = relationship(
        foreign_keys=[published_revision_id], post_update=True
    )


class MedicalKnowledgeRevision(Base):
    __tablename__ = "medical_knowledge_revisions"
    __table_args__ = (
        UniqueConstraint("topic_id", "revision_number", name="uq_medical_revisions_topic_number"),
        CheckConstraint("revision_number > 0", name="ck_medical_revisions_positive_number"),
        CheckConstraint(_allowed("evidence_level", EVIDENCE_LEVELS), name="ck_medical_revisions_evidence_level"),
        CheckConstraint(_allowed("evidence_scope", EVIDENCE_SCOPES), name="ck_medical_revisions_evidence_scope"),
        CheckConstraint(_allowed("status", REVISION_STATUSES), name="ck_medical_revisions_status"),
        CheckConstraint("parent_display_allowed IN (0, 1)", name="ck_medical_revisions_parent_display"),
        CheckConstraint("generated_by_llm IN (0, 1)", name="ck_medical_revisions_generated_by_llm"),
        Index("ix_medical_revisions_topic_id", "topic_id"),
        Index("ix_medical_revisions_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_topics.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    short_explanation_vi: Mapped[str] = mapped_column(Text, nullable=False)
    detailed_explanation_vi: Mapped[str] = mapped_column(Text, nullable=False)
    limitations_vi: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False)
    parent_display_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_by_llm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    topic: Mapped[MedicalKnowledgeTopic] = relationship(
        back_populates="revisions", foreign_keys=[topic_id]
    )
    source_links: Mapped[list[MedicalRevisionSource]] = relationship(
        back_populates="revision", cascade="all, delete-orphan", passive_deletes=True
    )


class MedicalEvidenceSource(Base):
    __tablename__ = "medical_evidence_sources"
    __table_args__ = (
        CheckConstraint(_allowed("source_type", SOURCE_TYPES), name="ck_medical_sources_type"),
        Index("ix_medical_sources_pmid", "pmid"),
        Index("ix_medical_sources_doi", "doi"),
        Index("ix_medical_sources_type", "source_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    pmid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    abstract_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_metadata_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    revision_links: Mapped[list[MedicalRevisionSource]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )


class MedicalRevisionSource(Base):
    __tablename__ = "medical_revision_sources"
    __table_args__ = (
        UniqueConstraint("revision_id", "source_id", name="uq_medical_revision_sources_pair"),
        CheckConstraint(_allowed("source_role", SOURCE_ROLES), name="ck_medical_revision_sources_role"),
        CheckConstraint("sort_order >= 0", name="ck_medical_revision_sources_sort_order"),
        Index("ix_medical_revision_sources_source_id", "source_id"),
    )

    revision_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_revisions.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("medical_evidence_sources.id", ondelete="CASCADE"), primary_key=True
    )
    source_role: Mapped[str] = mapped_column(String(16), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relevance_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    revision: Mapped[MedicalKnowledgeRevision] = relationship(back_populates="source_links")
    source: Mapped[MedicalEvidenceSource] = relationship(back_populates="revision_links")
