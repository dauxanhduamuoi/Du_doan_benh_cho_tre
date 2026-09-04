"""Add append-only publication audit events to Medical Knowledge V1."""

from sqlalchemy import Connection, Engine

from app.medical_knowledge_models import MedicalKnowledgePublication


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
    """Idempotently add the audit table without changing existing publication state."""

    with _connection(bind) as connection:
        MedicalKnowledgePublication.__table__.create(connection, checkfirst=True)


def downgrade(bind: Engine | Connection) -> None:
    with _connection(bind) as connection:
        MedicalKnowledgePublication.__table__.drop(connection, checkfirst=True)
