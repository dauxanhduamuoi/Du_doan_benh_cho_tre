"""Add immutable evidence-content snapshots to Medical Knowledge V1."""

from sqlalchemy import Connection, Engine, inspect, text

from app.medical_knowledge_models import MedicalEvidenceContent


def _connection(bind: Engine | Connection):
    return bind.begin() if isinstance(bind, Engine) else _ExistingConnection(bind)


class _ExistingConnection:
    def __init__(self, connection: Connection):
        self.connection = connection

    def __enter__(self) -> Connection:
        return self.connection

    def __exit__(self, *_args) -> None:
        return None


def upgrade(bind: Engine | Connection) -> None:
    """Idempotently extend an existing create_all-based database without data loss."""

    with _connection(bind) as connection:
        MedicalEvidenceContent.__table__.create(connection, checkfirst=True)
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        if "medical_revision_sources" not in table_names:
            return
        columns = {column["name"] for column in inspector.get_columns("medical_revision_sources")}
        if "evidence_content_id" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE medical_revision_sources "
                    "ADD COLUMN evidence_content_id INTEGER NULL "
                    "REFERENCES medical_evidence_contents(id) ON DELETE SET NULL"
                )
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_medical_revision_sources_content_id "
                "ON medical_revision_sources (evidence_content_id)"
            )
        )


def downgrade(bind: Engine | Connection) -> None:
    with _connection(bind) as connection:
        inspector = inspect(connection)
        if "medical_revision_sources" in inspector.get_table_names():
            columns = {
                column["name"] for column in inspector.get_columns("medical_revision_sources")
            }
            if "evidence_content_id" in columns:
                connection.execute(
                    text("DROP INDEX IF EXISTS ix_medical_revision_sources_content_id")
                )
                connection.execute(
                    text("ALTER TABLE medical_revision_sources DROP COLUMN evidence_content_id")
                )
        MedicalEvidenceContent.__table__.drop(connection, checkfirst=True)
