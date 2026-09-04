"""Extend publication audit history with PUBLISH and UNPUBLISH actions."""

from sqlalchemy import Connection, Engine, inspect, text


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
    """Idempotently classify all existing audit rows as PUBLISH events."""

    with _connection(bind) as connection:
        inspector = inspect(connection)
        if "medical_knowledge_publications" not in inspector.get_table_names():
            return
        columns = {
            column["name"]
            for column in inspector.get_columns("medical_knowledge_publications")
        }
        if "action" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE medical_knowledge_publications "
                    "ADD COLUMN action VARCHAR(16) NOT NULL DEFAULT 'PUBLISH' "
                    "CHECK (action IN ('PUBLISH', 'UNPUBLISH'))"
                )
            )


def downgrade(bind: Engine | Connection) -> None:
    with _connection(bind) as connection:
        inspector = inspect(connection)
        if "medical_knowledge_publications" not in inspector.get_table_names():
            return
        columns = {
            column["name"]
            for column in inspector.get_columns("medical_knowledge_publications")
        }
        if "action" in columns:
            connection.execute(
                text("ALTER TABLE medical_knowledge_publications DROP COLUMN action")
            )
