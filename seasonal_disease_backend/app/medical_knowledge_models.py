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
    column,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .medical_knowledge_factors import FACTOR_TYPES, WEATHER_FACTORS


EVIDENCE_LEVELS = ("SUPPORTED", "LIMITED_OR_INDIRECT", "CONFLICTING", "INSUFFICIENT")
EVIDENCE_SCOPES = ("WHOLE_GROUP", "PARTIAL_GROUP")
REVISION_STATUSES = ("DRAFT", "APPROVED", "REJECTED")
SOURCE_TYPES = ("PUBMED", "WHO", "CDC", "OTHER")
EVIDENCE_SOURCE_KINDS = (
    "RESEARCH_ARTICLE",
    "SYSTEMATIC_REVIEW",
    "GUIDELINE",
    "TECHNICAL_REPORT",
    "HEALTH_GUIDANCE",
    "OTHER",
)
SOURCE_ROLES = ("PRIMARY", "SUPPORTING")
EVIDENCE_CONTENT_KINDS = ("ABSTRACT", "PMC_FULL_TEXT", "PMC_FULL_TEXT_EXCERPT")
EVIDENCE_CONTENT_ORIGINS = ("NCBI_PUBMED", "NCBI_PMC")
POPULATION_RELEVANCES = (
    "PEDIATRIC_DIRECT",
    "MIXED_AGE",
    "ADULT_ONLY",
    "ELDERLY_ONLY",
    "UNKNOWN",
)
PUBLICATION_ACTIONS = ("PUBLISH", "UNPUBLISH")
AUTO_JOB_STATUSES = (
    "QUEUED",
    "SEARCHING",
    "GENERATING",
    "READY",
    "INSUFFICIENT",
    "FAILED",
    "CANCELLED",
)
AUTO_REVISION_STATUSES = ("READY", "INSUFFICIENT")
AUTO_TRUST_CLASSES = (
    "PUBMED",
    "PMC",
    "WHO",
    "CDC",
    "OFFICIAL_HEALTH_AGENCY",
    "PROFESSIONAL_MEDICAL_ORG",
    "ACADEMIC",
)
AUTO_DISCOVERY_DECISIONS = ("SELECTED", "SKIPPED")
AUTO_DISPLAY_MODES = ("REVIEWED_ONLY", "REVIEWED_WITH_AUTO_FALLBACK")
AUTO_TOPIC_VISIBILITY_ACTIONS = ("HIDE_AUTO_TOPIC", "UNHIDE_AUTO_TOPIC")
AUTO_NUMERIC_CLAIM_KINDS = (
    "COUNT",
    "PERCENTAGE",
    "RATE",
    "RATIO_OR_EFFECT",
    "MEASUREMENT",
    "AGE",
    "DURATION",
    "TEMPORAL_PERIOD",
    "OTHER_NUMERIC",
)


def _allowed(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class MedicalKnowledgeTopic(Base):
    __tablename__ = "medical_knowledge_topics"
    __table_args__ = (
        CheckConstraint(_allowed("factor_type", FACTOR_TYPES), name="ck_medical_topics_factor_type"),
        CheckConstraint(
            "(factor_type = 'WEATHER' AND weather_factor = factor_key AND factor_value IS NULL) "
            "OR (factor_type <> 'WEATHER' AND weather_factor IS NULL)",
            name="ck_medical_topics_legacy_weather",
        ),
        Index(
            "uq_medical_topics_generic_selector",
            "disease_group_id",
            "factor_type",
            "factor_key",
            func.coalesce(column("factor_value"), ""),
            unique=True,
        ),
        Index("ix_medical_topics_disease_group_id", "disease_group_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disease_group_id: Mapped[str] = mapped_column(String(100), nullable=False)
    weather_factor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    factor_type: Mapped[str] = mapped_column(String(16), nullable=False, default="WEATHER")
    factor_key: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=lambda context: context.get_current_parameters().get("weather_factor"),
    )
    factor_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
    source_library: Mapped[list[MedicalKnowledgeTopicSource]] = relationship(
        back_populates="topic", cascade="all, delete-orphan", passive_deletes=True
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


class MedicalKnowledgePublication(Base):
    """Append-only audit event for Parent publication state changes."""

    __tablename__ = "medical_knowledge_publications"
    __table_args__ = (
        CheckConstraint(
            _allowed("action", PUBLICATION_ACTIONS),
            name="ck_medical_publications_action",
        ),
        Index("ix_medical_publications_topic_id", "topic_id"),
        Index("ix_medical_publications_revision_id", "revision_id"),
        Index("ix_medical_publications_published_by", "published_by"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_topics.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_revisions.id", ondelete="CASCADE"), nullable=False
    )
    published_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    action: Mapped[str] = mapped_column(
        String(16), default="PUBLISH", server_default="PUBLISH", nullable=False
    )


class MedicalEvidenceSource(Base):
    __tablename__ = "medical_evidence_sources"
    __table_args__ = (
        CheckConstraint(_allowed("source_type", SOURCE_TYPES), name="ck_medical_sources_type"),
        Index("ix_medical_sources_pmid", "pmid"),
        Index("ix_medical_sources_doi", "doi"),
        Index("ix_medical_sources_type", "source_type"),
        Index("ix_medical_sources_provider_external", "provider_id", "external_id"),
        Index("ix_medical_sources_kind", "source_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Additive V1 provider identity. source_type remains for API/backward
    # compatibility; new provider-neutral code uses these three fields.
    provider_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
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
    evidence_contents: Mapped[list[MedicalEvidenceContent]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )
    topic_links: Mapped[list[MedicalKnowledgeTopicSource]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )


class MedicalKnowledgeTopicSource(Base):
    """A source deliberately collected for one disease/factor topic."""

    __tablename__ = "medical_knowledge_topic_sources"
    __table_args__ = (
        UniqueConstraint(
            "topic_id", "source_id", name="uq_medical_topic_sources_pair"
        ),
        Index("ix_medical_topic_sources_topic_id", "topic_id"),
        Index("ix_medical_topic_sources_source_id", "source_id"),
    )

    topic_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_topics.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("medical_evidence_sources.id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    topic: Mapped[MedicalKnowledgeTopic] = relationship(back_populates="source_library")
    source: Mapped[MedicalEvidenceSource] = relationship(back_populates="topic_links")


class MedicalEvidenceContent(Base):
    """Immutable, normalized evidence snapshots retrieved for one source."""

    __tablename__ = "medical_evidence_contents"
    __table_args__ = (
        UniqueConstraint("source_id", "content_sha256", name="uq_medical_evidence_content_hash"),
        CheckConstraint(
            _allowed("content_kind", EVIDENCE_CONTENT_KINDS),
            name="ck_medical_evidence_content_kind",
        ),
        CheckConstraint(
            _allowed("content_origin", EVIDENCE_CONTENT_ORIGINS),
            name="ck_medical_evidence_content_origin",
        ),
        CheckConstraint("is_truncated IN (0, 1)", name="ck_medical_evidence_content_truncated"),
        Index("ix_medical_evidence_contents_source_id", "source_id"),
        Index("ix_medical_evidence_contents_external_id", "external_identifier"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("medical_evidence_sources.id", ondelete="CASCADE"), nullable=False
    )
    content_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_origin: Mapped[str] = mapped_column(String(32), nullable=False)
    external_identifier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    license_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    license_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    source: Mapped[MedicalEvidenceSource] = relationship(back_populates="evidence_contents")
    revision_links: Mapped[list[MedicalRevisionSource]] = relationship(
        back_populates="evidence_content"
    )


class MedicalRevisionSource(Base):
    __tablename__ = "medical_revision_sources"
    __table_args__ = (
        UniqueConstraint("revision_id", "source_id", name="uq_medical_revision_sources_pair"),
        CheckConstraint(_allowed("source_role", SOURCE_ROLES), name="ck_medical_revision_sources_role"),
        CheckConstraint(
            _allowed("population_relevance", POPULATION_RELEVANCES),
            name="ck_medical_revision_sources_population_relevance",
        ),
        CheckConstraint("sort_order >= 0", name="ck_medical_revision_sources_sort_order"),
        Index("ix_medical_revision_sources_source_id", "source_id"),
        Index("ix_medical_revision_sources_content_id", "evidence_content_id"),
    )

    revision_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_revisions.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("medical_evidence_sources.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_content_id: Mapped[int | None] = mapped_column(
        ForeignKey("medical_evidence_contents.id", ondelete="SET NULL"), nullable=True
    )
    source_role: Mapped[str] = mapped_column(String(16), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relevance_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    population_relevance: Mapped[str | None] = mapped_column(String(24), nullable=True)
    population_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    revision: Mapped[MedicalKnowledgeRevision] = relationship(back_populates="source_links")
    source: Mapped[MedicalEvidenceSource] = relationship(back_populates="revision_links")
    evidence_content: Mapped[MedicalEvidenceContent | None] = relationship(
        back_populates="revision_links"
    )


class AutoMedicalKnowledgeJob(Base):
    """Durable, topic-scoped work item; never represents clinical approval."""

    __tablename__ = "auto_medical_knowledge_jobs"
    __table_args__ = (
        CheckConstraint(_allowed("status", AUTO_JOB_STATUSES), name="ck_auto_mk_jobs_status"),
        CheckConstraint("attempt_count >= 0", name="ck_auto_mk_jobs_attempt_count"),
        CheckConstraint("trigger_type IN ('PARENT','ADMIN')", name="ck_auto_mk_jobs_trigger"),
        Index("ix_auto_mk_jobs_status_retry", "status", "next_retry_at"),
        Index("ix_auto_mk_jobs_topic_id", "topic_id"),
        Index(
            "uq_auto_mk_jobs_one_active_topic",
            "topic_id",
            unique=True,
            sqlite_where=text("status IN ('QUEUED','SEARCHING','GENERATING')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_topics.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(16), default="PARENT", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class AutoMedicalKnowledgeRevision(Base):
    """Immutable automated generation, separate from reviewed revisions."""

    __tablename__ = "auto_medical_knowledge_revisions"
    __table_args__ = (
        UniqueConstraint("topic_id", "revision_number", name="uq_auto_mk_revision_number"),
        UniqueConstraint("job_id", name="uq_auto_mk_revision_job"),
        CheckConstraint("revision_number > 0", name="ck_auto_mk_revision_number"),
        CheckConstraint(
            _allowed("generation_status", AUTO_REVISION_STATUSES),
            name="ck_auto_mk_revision_status",
        ),
        CheckConstraint(_allowed("evidence_level", EVIDENCE_LEVELS), name="ck_auto_mk_evidence"),
        CheckConstraint("is_visible IN (0,1)", name="ck_auto_mk_visible"),
        CheckConstraint(
            "generation_mode IS NULL OR generation_mode IN ('AI_FULL','SAFE_FALLBACK')",
            name="ck_auto_mk_generation_mode",
        ),
        CheckConstraint(
            "auto_tier IS NULL OR auto_tier IN ('STRICT','BASIC')",
            name="ck_auto_mk_auto_tier",
        ),
        CheckConstraint(
            "generation_method IS NULL OR generation_method IN ('AI','SAFE_TEMPLATE')",
            name="ck_auto_mk_generation_method",
        ),
        CheckConstraint(
            "fallback_reason_code IS NULL OR fallback_reason_code IN "
            "('CONTRACT_REPAIR_EXHAUSTED','REPAIR_PROVIDER_FAILURE','REPAIR_STRUCTURAL_FAILURE')",
            name="ck_auto_mk_fallback_reason",
        ),
        CheckConstraint(
            "(generation_mode = 'SAFE_FALLBACK' AND fallback_reason_code IS NOT NULL) "
            "OR (generation_mode IS NULL AND fallback_reason_code IS NULL) "
            "OR (generation_mode = 'AI_FULL' AND fallback_reason_code IS NULL)",
            name="ck_auto_mk_fallback_mode_reason",
        ),
        Index("ix_auto_mk_revisions_topic_id", "topic_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_topics.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("auto_medical_knowledge_jobs.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    short_explanation_vi: Mapped[str | None] = mapped_column(Text, nullable=True)
    detailed_explanation_vi: Mapped[str | None] = mapped_column(Text, nullable=True)
    limitations_vi: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    generation_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fallback_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    auto_tier: Mapped[str | None] = mapped_column(String(12), nullable=True)
    generation_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    strict_failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    strict_failure_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AutoMedicalKnowledgeTopicState(Base):
    __tablename__ = "auto_medical_knowledge_topic_states"
    __table_args__ = (
        CheckConstraint("request_count >= 0", name="ck_auto_mk_state_request_count"),
        Index("ix_auto_mk_states_last_requested", "last_requested_at"),
    )

    topic_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_topics.id", ondelete="CASCADE"), primary_key=True
    )
    current_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("auto_medical_knowledge_revisions.id", ondelete="SET NULL"), nullable=True
    )
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_hidden_by_staff: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class AutoMedicalKnowledgeVisibilityAudit(Base):
    __tablename__ = "auto_medical_knowledge_visibility_audits"
    __table_args__ = (
        CheckConstraint(
            _allowed("action", AUTO_TOPIC_VISIBILITY_ACTIONS),
            name="ck_auto_mk_visibility_audit_action",
        ),
        Index("ix_auto_mk_visibility_audits_topic", "topic_id", "created_at"),
        Index("ix_auto_mk_visibility_audits_actor", "actor_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("medical_knowledge_topics.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AutoMedicalKnowledgeRevisionSource(Base):
    __tablename__ = "auto_medical_knowledge_revision_sources"
    __table_args__ = (
        CheckConstraint(_allowed("trust_class", AUTO_TRUST_CLASSES), name="ck_auto_mk_source_trust"),
        CheckConstraint(_allowed("source_role", SOURCE_ROLES), name="ck_auto_mk_source_role"),
        CheckConstraint(
            _allowed("population_relevance", POPULATION_RELEVANCES),
            name="ck_auto_mk_source_population",
        ),
        CheckConstraint("sort_order >= 0", name="ck_auto_mk_source_sort"),
        Index("ix_auto_mk_revision_sources_source", "source_id"),
        Index("ix_auto_mk_revision_sources_content", "evidence_content_id"),
    )

    revision_id: Mapped[int] = mapped_column(
        ForeignKey("auto_medical_knowledge_revisions.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("medical_evidence_sources.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_content_id: Mapped[int] = mapped_column(
        ForeignKey("medical_evidence_contents.id", ondelete="RESTRICT"), nullable=False
    )
    trust_class: Mapped[str] = mapped_column(String(40), nullable=False)
    source_role: Mapped[str] = mapped_column(String(16), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    relevance_note: Mapped[str] = mapped_column(Text, nullable=False)
    population_relevance: Mapped[str] = mapped_column(String(24), nullable=False)
    population_note: Mapped[str] = mapped_column(Text, nullable=False)


class AutoMedicalKnowledgeNumericClaim(Base):
    """Verified compact provenance; raw model quotes are intentionally not stored."""

    __tablename__ = "auto_medical_knowledge_numeric_claims"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "claim_order", name="uq_auto_mk_numeric_claim_order"
        ),
        CheckConstraint(
            _allowed("claim_kind", AUTO_NUMERIC_CLAIM_KINDS),
            name="ck_auto_mk_numeric_claim_kind",
        ),
        CheckConstraint(
            "claim_order >= 0 AND claim_order < 10",
            name="ck_auto_mk_numeric_claim_order",
        ),
        CheckConstraint(
            "support_start >= 0 AND support_end > support_start",
            name="ck_auto_mk_numeric_claim_offsets",
        ),
        Index("ix_auto_mk_numeric_claim_revision", "revision_id"),
        Index("ix_auto_mk_numeric_claim_source", "source_id"),
        Index("ix_auto_mk_numeric_claim_content", "evidence_content_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey("auto_medical_knowledge_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_order: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value_text: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("medical_evidence_sources.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_content_id: Mapped[int] = mapped_column(
        ForeignKey("medical_evidence_contents.id", ondelete="RESTRICT"), nullable=False
    )
    support_start: Mapped[int] = mapped_column(Integer, nullable=False)
    support_end: Mapped[int] = mapped_column(Integer, nullable=False)
    support_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class AutoMedicalKnowledgeDiscovery(Base):
    __tablename__ = "auto_medical_knowledge_discoveries"
    __table_args__ = (
        CheckConstraint(_allowed("trust_class", AUTO_TRUST_CLASSES), name="ck_auto_mk_discovery_trust"),
        CheckConstraint(
            _allowed("decision", AUTO_DISCOVERY_DECISIONS),
            name="ck_auto_mk_discovery_decision",
        ),
        Index("ix_auto_mk_discoveries_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("auto_medical_knowledge_jobs.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("medical_evidence_sources.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    trust_class: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AutoMedicalKnowledgeSetting(Base):
    __tablename__ = "auto_medical_knowledge_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_auto_mk_settings_singleton"),
        CheckConstraint(
            _allowed("display_mode", AUTO_DISPLAY_MODES),
            name="ck_auto_mk_settings_display_mode",
        ),
        CheckConstraint("auto_visible_default IN (0,1)", name="ck_auto_mk_settings_visible"),
        CheckConstraint("enabled IN (0,1)", name="ck_auto_mk_settings_enabled"),
        CheckConstraint(
            "basic_fallback_enabled IN (0,1)",
            name="ck_auto_mk_settings_basic_fallback_enabled",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_mode: Mapped[str] = mapped_column(
        String(40), default="REVIEWED_ONLY", nullable=False
    )
    auto_visible_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    basic_fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class AutoMedicalKnowledgeProviderCooldown(Base):
    """Persisted provider lane state shared by all Auto workers."""

    __tablename__ = "auto_medical_knowledge_provider_cooldowns"

    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    cooldown_until: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
