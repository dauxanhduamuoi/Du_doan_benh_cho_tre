from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.medical_evidence_provider_settings_schemas import (
    MedicalEvidenceProviderSettingItem,
    MedicalEvidenceProviderSettingsResponse,
)
from app.medical_knowledge_models import (
    MEDICAL_EVIDENCE_WORKFLOWS,
    MedicalEvidenceProviderSetting,
    MedicalEvidenceProviderSettingAudit,
)
from app.services.medical_evidence_provider import MedicalEvidenceProviderRegistry


DEFAULT_PROVIDER_ENABLEMENT = {
    ("PUBMED", "AUTO"): True,
    ("PUBMED", "REVIEWED"): True,
    ("WHO", "AUTO"): False,
    ("WHO", "REVIEWED"): False,
}


class MedicalEvidenceProviderSettingNotFoundError(LookupError):
    pass


class MedicalEvidenceProviderSettingsService:
    def __init__(self, db: Session, registry: MedicalEvidenceProviderRegistry):
        self.db = db
        self.registry = registry

    def reconcile(self) -> dict[tuple[str, str], MedicalEvidenceProviderSetting]:
        """Add missing registered-provider rows only; never rewrite operator choices."""

        descriptors = self.registry.list_descriptors()
        registered_ids = {item.provider_id for item in descriptors}
        rows = list(
            self.db.scalars(
                select(MedicalEvidenceProviderSetting).where(
                    MedicalEvidenceProviderSetting.provider_id.in_(registered_ids)
                )
            )
        ) if registered_ids else []
        by_key = {(row.provider_id, row.workflow): row for row in rows}
        now = datetime.utcnow()
        for descriptor in descriptors:
            for workflow in MEDICAL_EVIDENCE_WORKFLOWS:
                key = (descriptor.provider_id, workflow)
                if key in by_key:
                    continue
                row = MedicalEvidenceProviderSetting(
                    provider_id=descriptor.provider_id,
                    workflow=workflow,
                    enabled=DEFAULT_PROVIDER_ENABLEMENT.get(key, False),
                    updated_at=now,
                    updated_by=None,
                )
                self.db.add(row)
                by_key[key] = row
        self.db.flush()
        return by_key

    def read(self) -> MedicalEvidenceProviderSettingsResponse:
        by_key = self.reconcile()
        items: list[MedicalEvidenceProviderSettingItem] = []
        for descriptor in self.registry.list_descriptors():
            for workflow in MEDICAL_EVIDENCE_WORKFLOWS:
                row = by_key[(descriptor.provider_id, workflow)]
                items.append(
                    MedicalEvidenceProviderSettingItem(
                        provider_id=descriptor.provider_id,
                        display_name=descriptor.settings_display_name or descriptor.display_name,
                        description=descriptor.description,
                        workflow=workflow,
                        enabled=row.enabled,
                        capabilities=sorted(item.value for item in descriptor.capabilities),
                        updated_at=row.updated_at,
                        updated_by=row.updated_by,
                    )
                )
        return MedicalEvidenceProviderSettingsResponse(providers=items)

    def enabled_provider_ids(self, workflow: str) -> tuple[str, ...]:
        if workflow not in MEDICAL_EVIDENCE_WORKFLOWS:
            raise ValueError("Unknown medical evidence workflow")
        by_key = self.reconcile()
        # Registry order is the deterministic orchestration order.
        return tuple(
            descriptor.provider_id
            for descriptor in self.registry.list_descriptors()
            if by_key[(descriptor.provider_id, workflow)].enabled
        )

    def update(
        self, *, provider_id: str, workflow: str, enabled: bool, actor_user_id: int
    ) -> MedicalEvidenceProviderSettingsResponse:
        normalized = provider_id.strip().upper()
        registered = {item.provider_id for item in self.registry.list_descriptors()}
        if normalized not in registered or workflow not in MEDICAL_EVIDENCE_WORKFLOWS:
            raise MedicalEvidenceProviderSettingNotFoundError(
                "Unknown provider or workflow"
            )
        by_key = self.reconcile()
        row = by_key[(normalized, workflow)]
        previous = bool(row.enabled)
        if previous != enabled:
            now = datetime.utcnow()
            row.enabled = enabled
            row.updated_at = now
            row.updated_by = actor_user_id
            self.db.add(
                MedicalEvidenceProviderSettingAudit(
                    provider_id=normalized,
                    workflow=workflow,
                    old_enabled=previous,
                    new_enabled=enabled,
                    action="ENABLE" if enabled else "DISABLE",
                    actor_user_id=actor_user_id,
                    created_at=now,
                )
            )
        self.db.commit()
        return self.read()
