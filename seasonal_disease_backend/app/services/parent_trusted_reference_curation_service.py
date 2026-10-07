from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.medical_knowledge_factors import normalize_factor
from app.medical_knowledge_models import (
    MedicalEvidenceContent as Content, MedicalEvidenceSource as Source,
    MedicalKnowledgeTopic as Topic, MedicalKnowledgeTopicSource as Membership,
)
from app.models import User
from app.repositories.parent_trusted_reference_repository import ParentTrustedReferenceRepository
from app.services.parent_trusted_reference_identity import CURATION_POLICY_VERSION, build_parent_reference_identity
from app.services.trusted_reference_source_policy import (
    TrustedReferenceDecision, TrustedReferenceSourceMetadata,
    evaluate_trusted_reference_source,
)


class CurationValidationError(ValueError):
    pass


class CurationConflictError(CurationValidationError):
    pass


@dataclass(frozen=True)
class CurationSelector:
    disease_group_id: str
    factor_type: str
    factor_key: str
    factor_value: str | None = None

    def canonical(self) -> dict:
        if not isinstance(self.disease_group_id, str) or not re.fullmatch(r"[0-9]{1,6}", self.disease_group_id):
            raise CurationValidationError("Invalid disease_group_id")
        try:
            factor = normalize_factor(factor_type=self.factor_type, factor_key=self.factor_key,
                                      factor_value=self.factor_value)
        except ValueError as exc:
            raise CurationValidationError(str(exc)) from exc
        # Normalization validates vocabulary, but cannot weaken exact identity.
        if (self.factor_type, self.factor_key, self.factor_value) != (
            factor.factor_type, factor.factor_key, factor.factor_value,
        ):
            raise CurationValidationError("Selector must already be canonical, including NULL")
        return dict(disease_group_id=self.disease_group_id, factor_type=self.factor_type,
                    factor_key=self.factor_key, factor_value=self.factor_value)


@dataclass(frozen=True)
class CurationResult:
    approval_id: int
    status: str
    version: int
    evidence_content_id: int | None
    identity_sha256: str | None
    changed: bool
    policy_decision: str | None = None


def _transaction(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        # This service owns commit/rollback, like the legacy approval service.
        # Refuse pending caller work instead of flushing/committing it implicitly.
        if self.db.new or self.db.dirty or self.db.deleted:
            raise CurationValidationError("Curation requires a session without pending caller writes")
        try:
            with self.db.no_autoflush:
                result = method(self, *args, **kwargs)
            self.db.commit()
            self.db.expire_all()  # CAS uses columns, so cached ORM rows must not stay stale.
            return result
        except IntegrityError as exc:
            self.db.rollback()
            raise CurationConflictError("Curation persistence constraint conflict") from exc
        except Exception:
            self.db.rollback()
            raise
    return run


class ParentTrustedReferenceCurationService:
    """Reference-only state machine. No publication, provider, worker or prose path.

    actor_id comes from the authenticated caller, never a curation request DTO.
    A clean dedicated session is recommended: successful calls own its commit;
    failed calls roll it back. Current-version retries can be no-ops; stale retries
    conflict. APPROVED alone does not implement Parent visibility in Phase B.
    """

    def __init__(self, db: Session, *, clock: Callable[[], datetime] | None = None):
        self.db = db
        self.repository = ParentTrustedReferenceRepository(db)
        self.clock = clock or (lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def _actor(self, actor_id: int, review_note: str | None) -> None:
        if type(actor_id) is not int or actor_id <= 0:
            raise CurationValidationError("Authenticated staff actor is required")
        actor = self.db.execute(select(User.role, User.is_active).where(User.id == actor_id)).first()
        if actor is None or not actor.is_active or actor.role not in {"staff", "admin"}:
            raise CurationValidationError("Actor must be active staff/admin")
        if review_note is not None and (not isinstance(review_note, str) or len(review_note) > 1000):
            raise CurationValidationError("Review note must be at most 1000 characters")

    def _context(self, topic_id: int, source_id: int, selector: CurationSelector, *, membership: bool = True):
        selected = selector.canonical()
        topic = self.db.execute(select(
            Topic.disease_group_id, Topic.factor_type, Topic.factor_key, Topic.factor_value,
        ).where(Topic.id == topic_id)).mappings().first()
        if topic is None or dict(topic) != selected:
            raise CurationValidationError("Topic missing or exact selector mismatch")
        source = self.db.execute(select(
            Source.id, Source.source_type, Source.provider_id, Source.external_id,
            Source.source_kind, Source.url, Source.title, Source.journal, Source.publication_year,
        ).where(Source.id == source_id)).mappings().first()
        if source is None:
            raise CurationValidationError("Source does not exist")
        if membership and self.db.execute(select(Membership.source_id).where(
            Membership.topic_id == topic_id, Membership.source_id == source_id,
        )).first() is None:
            raise CurationValidationError("Source is not in this topic library")
        return selected, dict(source)

    def _state(self, approval_id: int, expected_version: int) -> dict:
        if type(expected_version) is not int or expected_version < 1:
            raise CurationValidationError("Positive integer expected_version is required")
        row = self.repository.get_persisted_state(approval_id)
        if row is None:
            raise CurationValidationError("Approval does not exist")
        if row["version"] != expected_version:
            raise CurationConflictError("Stale expected_version")
        return row

    @staticmethod
    def _policy(source: dict, proof: dict | None = None):
        proof = proof or {}
        return evaluate_trusted_reference_source(TrustedReferenceSourceMetadata(
            provider_id=source["provider_id"], source_type=source["source_type"],
            external_id=source["external_id"], source_kind=source["source_kind"], original_url=source["url"],
            content_origin=proof.get("content_origin"), content_external_id=proof.get("external_identifier"),
            provenance=proof.get("provenance_json"),
        ))

    def _identity(self, selected: dict, source: dict, proof_id: int):
        if type(proof_id) is not int or proof_id <= 0:
            raise CurationValidationError("Positive integer proof ID is required")
        proof = self.db.execute(select(
            Content.id, Content.source_id, Content.content_kind, Content.content_origin,
            Content.external_identifier, Content.provenance_json, Content.content_sha256,
        ).where(Content.id == proof_id)).mappings().first()
        if proof is None or proof["source_id"] != source["id"]:
            raise CurationValidationError("Proof missing or belongs to a different source")
        proof = dict(proof)
        policy = self._policy(source, proof)
        if policy.decision != TrustedReferenceDecision.ALLOW_PARENT_REFERENCE:
            raise CurationValidationError(f"Source Policy: {policy.decision.value}/{policy.reason_code}")
        return build_parent_reference_identity(selected, source, proof)

    @staticmethod
    def _result(row: dict, changed: bool, policy_decision: str | None = None) -> CurationResult:
        return CurationResult(row["id"], row["status"], row["version"], row["evidence_content_id"],
                              row["identity_sha256"], changed, policy_decision)

    def _event(self, row: dict, action: str, from_status: str | None, actor_id: int,
               review_note: str | None, now: datetime) -> None:
        self.repository.append_event(
            approval_id=row["id"], action=action, from_status=from_status, to_status=row["status"],
            resulting_version=row["version"], actor_user_id=actor_id, review_note=review_note, created_at=now,
            identity_snapshot_json=row["identity_snapshot_json"], identity_sha256=row["identity_sha256"],
            policy_version=row["policy_version"],
        )

    def _mutate(self, row: dict, values: dict, action: str, actor_id: int, review_note: str | None):
        now = self.clock()
        values["updated_at"] = now
        if action == "APPROVE":
            values["approved_at"] = now
        elif action == "REVOKE":
            values["revoked_at"] = now
        if not self.repository.compare_and_swap(row["id"], row["version"], values):
            raise CurationConflictError("Concurrent curation mutation")
        new = {**row, **values, "version": row["version"] + 1}
        self._event(new, action, row["status"], actor_id, review_note, now)
        return self._result(new, True)

    @_transaction
    def create_draft(self, *, topic_id: int, source_id: int, selector: CurationSelector,
                     actor_id: int, review_note: str | None = None, sort_order: int = 0) -> CurationResult:
        self._actor(actor_id, review_note)
        _, source = self._context(topic_id, source_id, selector)
        if type(sort_order) is not int or sort_order < 0:
            raise CurationValidationError("sort_order must be a nonnegative integer")
        if self.repository.get_by_topic_source(topic_id, source_id) is not None:
            raise CurationConflictError("Approval already exists for this topic/source")
        now = self.clock()
        record = self.repository.create_draft(topic_id=topic_id, source_id=source_id,
                                              created_by=actor_id, sort_order=sort_order, created_at=now)
        row = self.repository.get_persisted_state(record.id)
        self._event(row, "CREATE_DRAFT", None, actor_id, review_note, now)
        return self._result(row, True, self._policy(source).decision.value)

    @_transaction
    def approve(self, approval_id: int, *, expected_version: int, selector: CurationSelector,
                evidence_content_id: int, actor_id: int, review_note: str | None = None) -> CurationResult:
        self._actor(actor_id, review_note)
        row = self._state(approval_id, expected_version)
        if row["status"] not in {"DRAFT", "APPROVED"}:
            raise CurationValidationError("Only DRAFT can transition to APPROVED")
        selected, source = self._context(row["topic_id"], row["source_id"], selector)
        snapshot, digest = self._identity(selected, source, evidence_content_id)
        if row["status"] == "APPROVED":
            if (row["identity_sha256"] != digest or row["identity_snapshot_json"] != snapshot
                    or row["evidence_content_id"] != evidence_content_id
                    or row["policy_version"] != CURATION_POLICY_VERSION):
                raise CurationConflictError("Approved identity drift: revoke and reopen before reapproval")
            return self._result(row, False, TrustedReferenceDecision.ALLOW_PARENT_REFERENCE.value)
        return self._mutate(row, dict(status="APPROVED", evidence_content_id=evidence_content_id,
            identity_snapshot_json=snapshot, identity_sha256=digest, policy_version=CURATION_POLICY_VERSION,
            approved_by=actor_id, revoked_by=None, revoked_at=None), "APPROVE", actor_id, review_note)

    @_transaction
    def revoke(self, approval_id: int, *, expected_version: int, actor_id: int,
               review_note: str | None = None) -> CurationResult:
        self._actor(actor_id, review_note)
        row = self._state(approval_id, expected_version)
        # Revocation must remain possible even when selector/membership/policy drifts.
        if row["status"] == "REVOKED":
            return self._result(row, False)
        if row["status"] != "APPROVED":
            raise CurationValidationError("Only APPROVED can transition to REVOKED")
        return self._mutate(row, dict(status="REVOKED", revoked_by=actor_id), "REVOKE", actor_id, review_note)

    @_transaction
    def reopen(self, approval_id: int, *, expected_version: int, selector: CurationSelector,
               actor_id: int, review_note: str | None = None) -> CurationResult:
        self._actor(actor_id, review_note)
        row = self._state(approval_id, expected_version)
        self._context(row["topic_id"], row["source_id"], selector)
        if row["status"] == "DRAFT":
            return self._result(row, False)
        if row["status"] != "REVOKED":
            raise CurationValidationError("Only REVOKED can transition to DRAFT")
        return self._mutate(row, dict(status="DRAFT", evidence_content_id=None, identity_snapshot_json=None,
            identity_sha256=None, policy_version=None, approved_by=None, approved_at=None,
            revoked_by=None, revoked_at=None), "REOPEN_DRAFT", actor_id, review_note)
