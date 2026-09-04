from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from app.medical_knowledge_draft_schemas import (
    RevisionPublicationResponse,
    RevisionUnpublicationResponse,
)
from app.models import User
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository


class PublicationWorkflowError(ValueError):
    pass


class PublicationNotFoundError(PublicationWorkflowError):
    pass


class PublicationConflictError(PublicationWorkflowError):
    pass


class PublicationValidationError(PublicationWorkflowError):
    pass


class MedicalKnowledgePublicationService:
    """Atomically select one APPROVED revision as a topic's current publication."""

    def __init__(
        self,
        db: Session,
        *,
        clock: Callable[[], datetime] = datetime.utcnow,
        race_attempts: int = 3,
    ):
        self.db = db
        self.repository = MedicalKnowledgeRepository(db)
        self.clock = clock
        self.race_attempts = max(1, race_attempts)

    def publish(self, revision_id: int, *, published_by: int) -> RevisionPublicationResponse:
        publisher = self.db.get(User, published_by)
        if publisher is None or not publisher.is_active or publisher.role not in {"staff", "admin"}:
            raise PublicationValidationError("The authenticated publisher is not eligible to publish")
        publisher_id = publisher.id
        publisher_name = publisher.full_name or publisher.username

        for attempt in range(self.race_attempts):
            revision = self.repository.get_revision(revision_id)
            if revision is None:
                raise PublicationNotFoundError("Medical knowledge revision was not found")
            if revision.status != "APPROVED":
                raise PublicationConflictError("Only APPROVED revisions can be published")

            topic = self.repository.get_topic_for_update(revision.topic_id)
            if topic is None:
                raise PublicationValidationError("Revision topic is invalid")
            self.db.refresh(revision)
            if revision.topic_id != topic.id or revision.status != "APPROVED":
                raise PublicationConflictError("Only APPROVED revisions can be published")

            previous_revision_id = topic.published_revision_id
            if previous_revision_id == revision.id:
                publication = self.repository.get_latest_publication_for_revision(revision.id)
                if (
                    publication is not None
                    and publication.action == "PUBLISH"
                    and revision.parent_display_allowed
                    and self.repository.count_parent_visible_revisions(topic.id) == 1
                ):
                    existing_publisher = (
                        self.db.get(User, publication.published_by)
                        if publication.published_by is not None
                        else None
                    )
                    self.db.rollback()
                    return RevisionPublicationResponse(
                        revision_id=revision.id,
                        topic_id=topic.id,
                        status="APPROVED",
                        is_published=True,
                        parent_display_allowed=True,
                        published_by=publication.published_by or publisher_id,
                        published_by_name=(
                            existing_publisher.full_name or existing_publisher.username
                            if existing_publisher
                            else publisher_name
                        ),
                        published_at=publication.published_at,
                        previous_published_revision_id=revision.id,
                    )
                if publication is not None:
                    self.db.rollback()
                    raise PublicationConflictError("Current publication state is inconsistent")

            published_at = self.clock()
            if not self.repository.replace_current_publication(
                topic_id=topic.id,
                revision_id=revision.id,
                published_at=published_at,
                expected_previous_revision_id=previous_revision_id,
            ):
                self.db.rollback()
                if attempt + 1 < self.race_attempts:
                    continue
                raise PublicationConflictError("Publication changed concurrently; retry the request")

            self.repository.create_publication(
                topic_id=topic.id,
                revision_id=revision.id,
                published_by=publisher_id,
                published_at=published_at,
            )
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

            return RevisionPublicationResponse(
                revision_id=revision.id,
                topic_id=topic.id,
                status="APPROVED",
                is_published=True,
                parent_display_allowed=True,
                published_by=publisher_id,
                published_by_name=publisher_name,
                published_at=published_at,
                previous_published_revision_id=previous_revision_id,
            )

        raise PublicationConflictError("Publication changed concurrently; retry the request")

    def unpublish(
        self, revision_id: int, *, unpublished_by: int
    ) -> RevisionUnpublicationResponse:
        actor = self.db.get(User, unpublished_by)
        if actor is None or not actor.is_active or actor.role not in {"staff", "admin"}:
            raise PublicationValidationError(
                "The authenticated user is not eligible to unpublish"
            )
        actor_id = actor.id
        actor_name = actor.full_name or actor.username

        for attempt in range(self.race_attempts):
            revision = self.repository.get_revision(revision_id)
            if revision is None:
                raise PublicationNotFoundError("Medical knowledge revision was not found")
            if revision.status != "APPROVED":
                raise PublicationConflictError(
                    "Only the current published APPROVED revision can be unpublished"
                )

            topic = self.repository.get_topic_for_update(revision.topic_id)
            if topic is None or revision.topic_id != topic.id:
                raise PublicationValidationError("Revision topic is invalid")
            self.db.refresh(revision)
            if revision.status != "APPROVED" or topic.published_revision_id != revision.id:
                self.db.rollback()
                raise PublicationConflictError(
                    "Only the current published APPROVED revision can be unpublished"
                )

            latest_event = self.repository.get_latest_publication_for_revision(revision.id)
            if (
                not revision.parent_display_allowed
                or self.repository.count_parent_visible_revisions(topic.id) != 1
                or latest_event is None
                or latest_event.action != "PUBLISH"
            ):
                self.db.rollback()
                raise PublicationConflictError("Current publication state is inconsistent")

            unpublished_at = self.clock()
            if not self.repository.withdraw_current_publication(
                topic_id=topic.id,
                revision_id=revision.id,
                unpublished_at=unpublished_at,
            ):
                self.db.rollback()
                if attempt + 1 < self.race_attempts:
                    continue
                raise PublicationConflictError(
                    "Publication changed concurrently; retry the request"
                )

            try:
                self.repository.create_publication(
                    topic_id=topic.id,
                    revision_id=revision.id,
                    published_by=actor_id,
                    published_at=unpublished_at,
                    action="UNPUBLISH",
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

            return RevisionUnpublicationResponse(
                revision_id=revision.id,
                topic_id=topic.id,
                status="APPROVED",
                is_published=False,
                parent_display_allowed=False,
                unpublished_by=actor_id,
                unpublished_by_name=actor_name,
                unpublished_at=unpublished_at,
            )

        raise PublicationConflictError("Publication changed concurrently; retry the request")
