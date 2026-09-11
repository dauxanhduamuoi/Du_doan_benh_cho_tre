from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, or_, select, text, true, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.medical_knowledge_models import (
    AutoMedicalKnowledgeDiscovery,
    AutoMedicalKnowledgeJob,
    AutoMedicalKnowledgeNumericClaim,
    AutoMedicalKnowledgeProviderCooldown,
    AutoMedicalKnowledgeRevision,
    AutoMedicalKnowledgeRevisionSource,
    AutoMedicalKnowledgeSetting,
    AutoMedicalKnowledgeTopicState,
    AutoMedicalKnowledgeVisibilityAudit,
    MedicalEvidenceContent,
    MedicalEvidenceSource,
    MedicalKnowledgeTopic,
)


ACTIVE_JOB_STATUSES = ("QUEUED", "SEARCHING", "GENERATING")


class AutoMedicalKnowledgeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_topic(
        self,
        *,
        disease_group_id: str,
        factor_type: str,
        factor_key: str,
        factor_value: str | None,
        weather_factor: str | None,
    ) -> MedicalKnowledgeTopic:
        statement = sqlite_insert(MedicalKnowledgeTopic).values(
            disease_group_id=disease_group_id,
            factor_type=factor_type,
            factor_key=factor_key,
            factor_value=factor_value,
            weather_factor=weather_factor,
            created_by=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ).prefix_with("OR IGNORE")
        self.db.execute(statement)
        topic = self.db.scalar(
            select(MedicalKnowledgeTopic).where(
                MedicalKnowledgeTopic.disease_group_id == disease_group_id,
                MedicalKnowledgeTopic.factor_type == factor_type,
                MedicalKnowledgeTopic.factor_key == factor_key,
                func.coalesce(MedicalKnowledgeTopic.factor_value, "") == (factor_value or ""),
            )
        )
        if topic is None:
            raise RuntimeError("Canonical Medical Knowledge topic could not be created")
        return topic

    def get_topic(self, topic_id: int) -> MedicalKnowledgeTopic | None:
        return self.db.get(MedicalKnowledgeTopic, topic_id)

    def get_topic_by_selector(
        self,
        *,
        disease_group_id: str,
        factor_type: str,
        factor_key: str,
        factor_value: str | None,
    ) -> MedicalKnowledgeTopic | None:
        return self.db.scalar(
            select(MedicalKnowledgeTopic).where(
                MedicalKnowledgeTopic.disease_group_id == disease_group_id,
                MedicalKnowledgeTopic.factor_type == factor_type,
                MedicalKnowledgeTopic.factor_key == factor_key,
                func.coalesce(MedicalKnowledgeTopic.factor_value, "")
                == (factor_value or ""),
            )
        )

    def get_state(self, topic_id: int) -> AutoMedicalKnowledgeTopicState | None:
        return self.db.get(AutoMedicalKnowledgeTopicState, topic_id)

    def ensure_state(self, topic_id: int, *, now: datetime) -> AutoMedicalKnowledgeTopicState:
        self.db.execute(
            sqlite_insert(AutoMedicalKnowledgeTopicState)
            .values(
                topic_id=topic_id,
                current_revision_id=None,
                request_count=0,
                first_requested_at=None,
                last_requested_at=None,
                created_at=now,
                updated_at=now,
            )
            .prefix_with("OR IGNORE")
        )
        state = self.db.get(AutoMedicalKnowledgeTopicState, topic_id)
        if state is None:
            raise RuntimeError("Auto Medical Knowledge topic state could not be created")
        return state

    def record_demand(self, topic_id: int, *, now: datetime) -> AutoMedicalKnowledgeTopicState:
        state = self.ensure_state(topic_id, now=now)
        self.db.execute(
            update(AutoMedicalKnowledgeTopicState)
            .where(AutoMedicalKnowledgeTopicState.topic_id == topic_id)
            .values(
                request_count=AutoMedicalKnowledgeTopicState.request_count + 1,
                first_requested_at=func.coalesce(
                    AutoMedicalKnowledgeTopicState.first_requested_at, now
                ),
                last_requested_at=now,
                updated_at=now,
            )
        )
        self.db.flush()
        return self.db.get(AutoMedicalKnowledgeTopicState, topic_id)

    def set_topic_hidden(
        self,
        topic_id: int,
        *,
        hidden: bool,
        actor_user_id: int,
        now: datetime,
    ) -> AutoMedicalKnowledgeTopicState:
        """Persist the topic policy and audit event in the caller's transaction."""
        state = self.ensure_state(topic_id, now=now)
        state.is_hidden_by_staff = hidden
        state.hidden_at = now if hidden else None
        state.updated_at = now
        self.db.add(
            AutoMedicalKnowledgeVisibilityAudit(
                topic_id=topic_id,
                action="HIDE_AUTO_TOPIC" if hidden else "UNHIDE_AUTO_TOPIC",
                actor_user_id=actor_user_id,
                created_at=now,
            )
        )
        self.db.flush()
        return state

    def list_visibility_audits(
        self, topic_id: int
    ) -> list[AutoMedicalKnowledgeVisibilityAudit]:
        return list(
            self.db.scalars(
                select(AutoMedicalKnowledgeVisibilityAudit)
                .where(AutoMedicalKnowledgeVisibilityAudit.topic_id == topic_id)
                .order_by(AutoMedicalKnowledgeVisibilityAudit.id)
            )
        )

    def get_active_job(self, topic_id: int) -> AutoMedicalKnowledgeJob | None:
        return self.db.scalar(
            select(AutoMedicalKnowledgeJob)
            .where(
                AutoMedicalKnowledgeJob.topic_id == topic_id,
                AutoMedicalKnowledgeJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .order_by(AutoMedicalKnowledgeJob.id.desc())
        )

    def get_latest_job(self, topic_id: int) -> AutoMedicalKnowledgeJob | None:
        return self.db.scalar(
            select(AutoMedicalKnowledgeJob)
            .where(AutoMedicalKnowledgeJob.topic_id == topic_id)
            .order_by(AutoMedicalKnowledgeJob.id.desc())
        )

    def create_job_if_runtime_enabled(
        self, topic_id: int, *, trigger_type: str, now: datetime
    ) -> AutoMedicalKnowledgeJob | None:
        job_id = self.db.scalar(
            text(
                "INSERT INTO auto_medical_knowledge_jobs "
                "(topic_id,status,attempt_count,trigger_type,created_at) "
                "SELECT :topic_id,'QUEUED',0,:trigger_type,:created_at "
                "WHERE EXISTS (SELECT 1 FROM auto_medical_knowledge_settings "
                "WHERE id=1 AND enabled=1) RETURNING id"
            ),
            {
                "topic_id": topic_id,
                "trigger_type": trigger_type,
                "created_at": now,
            },
        )
        return self.db.get(AutoMedicalKnowledgeJob, job_id) if job_id is not None else None

    def requeue_job(self, job_id: int, *, now: datetime) -> bool:
        result = self.db.execute(
            update(AutoMedicalKnowledgeJob)
            .where(
                AutoMedicalKnowledgeJob.id == job_id,
                AutoMedicalKnowledgeJob.status.in_(("FAILED", "CANCELLED")),
            )
            .values(
                status="QUEUED",
                next_retry_at=None,
                finished_at=None,
                last_error_code=None,
                created_at=now,
            )
        )
        return result.rowcount == 1

    def claim_next_job(
        self,
        *,
        now: datetime,
        max_retries: int,
        provider: str | None = None,
    ) -> int | None:
        runtime_enabled = (
            select(AutoMedicalKnowledgeSetting.id)
            .where(
                AutoMedicalKnowledgeSetting.id == 1,
                AutoMedicalKnowledgeSetting.enabled.is_(True),
            )
            .exists()
        )
        provider_key = provider.strip().upper() if provider else None
        cooldown_inactive = true()
        if provider_key:
            cooldown_inactive = ~(
                select(AutoMedicalKnowledgeProviderCooldown.provider)
                .where(
                    AutoMedicalKnowledgeProviderCooldown.provider == provider_key,
                    AutoMedicalKnowledgeProviderCooldown.cooldown_until > now,
                )
                .exists()
            )
        candidate = self.db.scalar(
            select(AutoMedicalKnowledgeJob.id)
            .join(
                AutoMedicalKnowledgeTopicState,
                AutoMedicalKnowledgeTopicState.topic_id == AutoMedicalKnowledgeJob.topic_id,
            )
            .where(
                runtime_enabled,
                cooldown_inactive,
                AutoMedicalKnowledgeJob.attempt_count < max_retries,
                or_(
                    AutoMedicalKnowledgeJob.status == "QUEUED",
                    (
                        (AutoMedicalKnowledgeJob.status == "FAILED")
                        & (AutoMedicalKnowledgeJob.next_retry_at.is_not(None))
                        & (AutoMedicalKnowledgeJob.next_retry_at <= now)
                    ),
                ),
            )
            .order_by(
                AutoMedicalKnowledgeTopicState.request_count.desc(),
                AutoMedicalKnowledgeJob.created_at,
                AutoMedicalKnowledgeJob.id,
            )
            .limit(1)
        )
        if candidate is None:
            return None
        result = self.db.execute(
            update(AutoMedicalKnowledgeJob)
            .where(
                AutoMedicalKnowledgeJob.id == candidate,
                AutoMedicalKnowledgeJob.status.in_(("QUEUED", "FAILED")),
                runtime_enabled,
                cooldown_inactive,
            )
            .values(
                status="SEARCHING",
                attempt_count=AutoMedicalKnowledgeJob.attempt_count + 1,
                started_at=now,
                finished_at=None,
                next_retry_at=None,
                last_error_code=None,
            )
        )
        self.db.commit()
        return candidate if result.rowcount == 1 else None

    def get_provider_cooldown(
        self, provider: str
    ) -> AutoMedicalKnowledgeProviderCooldown | None:
        return self.db.get(
            AutoMedicalKnowledgeProviderCooldown, provider.strip().upper()
        )

    def get_active_provider_cooldown(
        self, provider: str, *, now: datetime
    ) -> AutoMedicalKnowledgeProviderCooldown | None:
        return self.db.scalar(
            select(AutoMedicalKnowledgeProviderCooldown).where(
                AutoMedicalKnowledgeProviderCooldown.provider
                == provider.strip().upper(),
                AutoMedicalKnowledgeProviderCooldown.cooldown_until > now,
            )
        )

    def set_provider_cooldown(
        self,
        provider: str,
        *,
        cooldown_until: datetime,
        reason: str,
        now: datetime,
    ) -> None:
        provider_key = provider.strip().upper()
        statement = sqlite_insert(AutoMedicalKnowledgeProviderCooldown).values(
            provider=provider_key,
            cooldown_until=cooldown_until,
            reason=reason,
            updated_at=now,
        )
        self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[AutoMedicalKnowledgeProviderCooldown.provider],
                set_={
                    "cooldown_until": case(
                        (
                            AutoMedicalKnowledgeProviderCooldown.cooldown_until
                            > statement.excluded.cooldown_until,
                            AutoMedicalKnowledgeProviderCooldown.cooldown_until,
                        ),
                        else_=statement.excluded.cooldown_until,
                    ),
                    "reason": statement.excluded.reason,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )

    def recover_interrupted_jobs(self, *, now: datetime) -> int:
        """Make process-owned states retryable after a backend restart."""
        result = self.db.execute(
            update(AutoMedicalKnowledgeJob)
            .where(AutoMedicalKnowledgeJob.status.in_(("SEARCHING", "GENERATING")))
            .values(
                status="FAILED",
                finished_at=now,
                next_retry_at=now,
                last_error_code="WORKER_RESTART_RECOVERY",
            )
        )
        return result.rowcount

    def set_job_status(self, job_id: int, status: str, **values) -> None:
        self.db.execute(
            update(AutoMedicalKnowledgeJob)
            .where(AutoMedicalKnowledgeJob.id == job_id)
            .values(status=status, **values)
        )

    def get_job(self, job_id: int) -> AutoMedicalKnowledgeJob | None:
        return self.db.get(AutoMedicalKnowledgeJob, job_id)

    def next_revision_number(self, topic_id: int) -> int:
        current = self.db.scalar(
            select(func.max(AutoMedicalKnowledgeRevision.revision_number)).where(
                AutoMedicalKnowledgeRevision.topic_id == topic_id
            )
        )
        return int(current or 0) + 1

    def get_current_revision(self, topic_id: int) -> AutoMedicalKnowledgeRevision | None:
        state = self.db.get(AutoMedicalKnowledgeTopicState, topic_id)
        return (
            self.db.get(AutoMedicalKnowledgeRevision, state.current_revision_id)
            if state is not None and state.current_revision_id is not None
            else None
        )

    def create_revision(self, **values) -> AutoMedicalKnowledgeRevision:
        revision = AutoMedicalKnowledgeRevision(**values)
        self.db.add(revision)
        self.db.flush()
        return revision

    def set_current_revision(self, topic_id: int, revision_id: int, *, now: datetime) -> None:
        self.ensure_state(topic_id, now=now)
        self.db.execute(
            update(AutoMedicalKnowledgeTopicState)
            .where(AutoMedicalKnowledgeTopicState.topic_id == topic_id)
            .values(current_revision_id=revision_id, updated_at=now)
        )

    @staticmethod
    def resolved_auto_tier(revision: AutoMedicalKnowledgeRevision) -> str | None:
        if revision.generation_status != "READY":
            return None
        if revision.auto_tier in {"STRICT", "BASIC"}:
            return revision.auto_tier
        return "BASIC" if revision.generation_mode == "SAFE_FALLBACK" else "STRICT"

    @staticmethod
    def resolved_generation_method(
        revision: AutoMedicalKnowledgeRevision,
    ) -> str | None:
        if revision.generation_status != "READY":
            return None
        if revision.generation_method in {"AI", "SAFE_TEMPLATE"}:
            return revision.generation_method
        return "SAFE_TEMPLATE" if revision.generation_mode == "SAFE_FALLBACK" else "AI"

    def set_current_revision_if_preferred(
        self, topic_id: int, revision_id: int, *, now: datetime
    ) -> bool:
        """Preserve READY Strict > READY Basic > Insufficient centrally."""

        candidate = self.db.get(AutoMedicalKnowledgeRevision, revision_id)
        if candidate is None or candidate.topic_id != topic_id:
            raise RuntimeError("Auto revision does not belong to the canonical topic")
        current = self.get_current_revision(topic_id)

        def priority(revision: AutoMedicalKnowledgeRevision | None) -> int:
            if revision is None:
                return 0
            if revision.generation_status != "READY":
                return 10
            return 30 if self.resolved_auto_tier(revision) == "STRICT" else 20

        if priority(candidate) < priority(current):
            return False
        self.set_current_revision(topic_id, revision_id, now=now)
        return True

    def add_revision_source(self, **values) -> AutoMedicalKnowledgeRevisionSource:
        link = AutoMedicalKnowledgeRevisionSource(**values)
        self.db.add(link)
        self.db.flush()
        return link

    def add_numeric_claim(self, **values) -> AutoMedicalKnowledgeNumericClaim:
        claim = AutoMedicalKnowledgeNumericClaim(**values)
        self.db.add(claim)
        self.db.flush()
        return claim

    def get_revision_numeric_claims(
        self, revision_id: int
    ) -> list[AutoMedicalKnowledgeNumericClaim]:
        return list(
            self.db.scalars(
                select(AutoMedicalKnowledgeNumericClaim)
                .where(AutoMedicalKnowledgeNumericClaim.revision_id == revision_id)
                .order_by(AutoMedicalKnowledgeNumericClaim.claim_order)
            )
        )

    def add_discovery(self, **values) -> AutoMedicalKnowledgeDiscovery:
        row = AutoMedicalKnowledgeDiscovery(**values)
        self.db.add(row)
        self.db.flush()
        return row

    def get_discoveries(self, job_id: int) -> list[AutoMedicalKnowledgeDiscovery]:
        return list(
            self.db.scalars(
                select(AutoMedicalKnowledgeDiscovery)
                .where(AutoMedicalKnowledgeDiscovery.job_id == job_id)
                .order_by(AutoMedicalKnowledgeDiscovery.id)
            )
        )

    def get_revision_sources(
        self, revision_id: int
    ) -> list[tuple[AutoMedicalKnowledgeRevisionSource, MedicalEvidenceSource, MedicalEvidenceContent]]:
        return list(
            self.db.execute(
                select(
                    AutoMedicalKnowledgeRevisionSource,
                    MedicalEvidenceSource,
                    MedicalEvidenceContent,
                )
                .join(
                    MedicalEvidenceSource,
                    MedicalEvidenceSource.id == AutoMedicalKnowledgeRevisionSource.source_id,
                )
                .join(
                    MedicalEvidenceContent,
                    MedicalEvidenceContent.id
                    == AutoMedicalKnowledgeRevisionSource.evidence_content_id,
                )
                .where(AutoMedicalKnowledgeRevisionSource.revision_id == revision_id)
                .order_by(
                    AutoMedicalKnowledgeRevisionSource.sort_order,
                    AutoMedicalKnowledgeRevisionSource.source_id,
                )
            )
        )

    def current_revisions_for_selectors(
        self, selectors: list[tuple[str, str, str, str | None]]
    ) -> dict[
        tuple[str, str, str, str | None],
        tuple[
            MedicalKnowledgeTopic,
            AutoMedicalKnowledgeRevision,
            AutoMedicalKnowledgeTopicState,
        ],
    ]:
        if not selectors:
            return {}
        normalized = {(a, b, c, d or "") for a, b, c, d in selectors}
        rows = self.db.execute(
            select(
                MedicalKnowledgeTopic,
                AutoMedicalKnowledgeRevision,
                AutoMedicalKnowledgeTopicState,
            )
            .join(
                AutoMedicalKnowledgeTopicState,
                AutoMedicalKnowledgeTopicState.topic_id == MedicalKnowledgeTopic.id,
            )
            .join(
                AutoMedicalKnowledgeRevision,
                AutoMedicalKnowledgeRevision.id
                == AutoMedicalKnowledgeTopicState.current_revision_id,
            )
        )
        result = {}
        for topic, revision, state in rows:
            key = (
                topic.disease_group_id,
                topic.factor_type,
                topic.factor_key,
                topic.factor_value or "",
            )
            if key in normalized:
                result[(key[0], key[1], key[2], topic.factor_value)] = (
                    topic,
                    revision,
                    state,
                )
        return result

    def get_settings(self) -> AutoMedicalKnowledgeSetting:
        settings = self.db.get(AutoMedicalKnowledgeSetting, 1)
        if settings is None:
            settings = AutoMedicalKnowledgeSetting(
                id=1,
                enabled=False,
                display_mode="REVIEWED_ONLY",
                auto_visible_default=False,
                basic_fallback_enabled=True,
                updated_at=datetime.utcnow(),
            )
            self.db.add(settings)
            self.db.flush()
        return settings

    def is_runtime_enabled(self) -> bool:
        return bool(
            self.db.scalar(
                select(AutoMedicalKnowledgeSetting.enabled).where(
                    AutoMedicalKnowledgeSetting.id == 1
                )
            )
        )

    def list_jobs(self, *, limit: int = 100) -> list[tuple[AutoMedicalKnowledgeJob, MedicalKnowledgeTopic]]:
        return list(
            self.db.execute(
                select(AutoMedicalKnowledgeJob, MedicalKnowledgeTopic)
                .join(MedicalKnowledgeTopic, MedicalKnowledgeTopic.id == AutoMedicalKnowledgeJob.topic_id)
                .order_by(AutoMedicalKnowledgeJob.id.desc())
                .limit(limit)
            )
        )

    def list_current_revisions(
        self, *, limit: int = 100
    ) -> list[
        tuple[
            AutoMedicalKnowledgeRevision,
            MedicalKnowledgeTopic,
            AutoMedicalKnowledgeTopicState,
        ]
    ]:
        return list(
            self.db.execute(
                select(
                    AutoMedicalKnowledgeRevision,
                    MedicalKnowledgeTopic,
                    AutoMedicalKnowledgeTopicState,
                )
                .join(
                    AutoMedicalKnowledgeTopicState,
                    AutoMedicalKnowledgeTopicState.current_revision_id
                    == AutoMedicalKnowledgeRevision.id,
                )
                .join(MedicalKnowledgeTopic, MedicalKnowledgeTopic.id == AutoMedicalKnowledgeRevision.topic_id)
                .order_by(AutoMedicalKnowledgeRevision.generated_at.desc())
                .limit(limit)
            )
        )
