"""Persist medical evidence provider enablement and its append-only audit."""

from __future__ import annotations

from sqlalchemy import Connection, Engine, inspect, select

from app.medical_knowledge_models import (
    MedicalEvidenceProviderSetting,
    MedicalEvidenceProviderSettingAudit,
)


DEFAULT_ROWS = (
    {"provider_id": "PUBMED", "workflow": "AUTO", "enabled": True},
    {"provider_id": "PUBMED", "workflow": "REVIEWED", "enabled": True},
    {"provider_id": "WHO", "workflow": "AUTO", "enabled": False},
    {"provider_id": "WHO", "workflow": "REVIEWED", "enabled": False},
)


def _upgrade(connection: Connection) -> None:
    MedicalEvidenceProviderSetting.__table__.create(connection, checkfirst=True)
    MedicalEvidenceProviderSettingAudit.__table__.create(connection, checkfirst=True)
    table = MedicalEvidenceProviderSetting.__table__
    existing = set(connection.execute(select(table.c.provider_id, table.c.workflow)))
    for row in DEFAULT_ROWS:
        key = (row["provider_id"], row["workflow"])
        if key not in existing:
            connection.execute(table.insert().values(**row))


def upgrade(bind: Engine | Connection) -> None:
    if isinstance(bind, Connection):
        _upgrade(bind)
        return
    with bind.begin() as connection:
        _upgrade(connection)


def downgrade(bind: Engine | Connection) -> None:
    connection = bind if isinstance(bind, Connection) else bind.connect()
    owns = not isinstance(bind, Connection)
    try:
        tables = set(inspect(connection).get_table_names())
        if "medical_evidence_provider_setting_audits" in tables:
            MedicalEvidenceProviderSettingAudit.__table__.drop(connection)
        if "medical_evidence_provider_settings" in tables:
            MedicalEvidenceProviderSetting.__table__.drop(connection)
        if owns:
            connection.commit()
    finally:
        if owns:
            connection.close()
