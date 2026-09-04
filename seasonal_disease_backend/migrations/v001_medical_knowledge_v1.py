"""Create the Medical Knowledge V1 foundation tables.

The project has no external migration framework. These explicit upgrade/downgrade
functions therefore follow its SQLAlchemy metadata convention without introducing
a new dependency.
"""

from sqlalchemy import Connection, Engine, text

from app.medical_knowledge_models import (
    MedicalEvidenceContent,
    MedicalEvidenceSource,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalRevisionSource,
)


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
    with _connection(bind) as connection:
        MedicalEvidenceSource.__table__.create(connection, checkfirst=True)
        MedicalKnowledgeTopic.__table__.create(connection, checkfirst=True)
        MedicalKnowledgeRevision.__table__.create(connection, checkfirst=True)
        # v001 follows the project's current-model/checkfirst convention rather
        # than frozen DDL, so create the table referenced by the current link model.
        MedicalEvidenceContent.__table__.create(connection, checkfirst=True)
        MedicalRevisionSource.__table__.create(connection, checkfirst=True)


def downgrade(bind: Engine | Connection) -> None:
    with _connection(bind) as connection:
        MedicalRevisionSource.__table__.drop(connection, checkfirst=True)
        # Break the circular topic -> published revision reference before dropping.
        connection.execute(text("UPDATE medical_knowledge_topics SET published_revision_id = NULL"))
        MedicalKnowledgeTopic.__table__.drop(connection, checkfirst=True)
        MedicalKnowledgeRevision.__table__.drop(connection, checkfirst=True)
        MedicalEvidenceContent.__table__.drop(connection, checkfirst=True)
        MedicalEvidenceSource.__table__.drop(connection, checkfirst=True)
