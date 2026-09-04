"""Add immutable population assessments to revision-source evidence links."""

from sqlalchemy import Connection, Engine, inspect


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
    """Idempotently add nullable columns; existing revision rows remain untouched."""

    with _connection(bind) as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("medical_revision_sources")
        }
        if "population_relevance" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE medical_revision_sources "
                "ADD COLUMN population_relevance VARCHAR(24) NULL"
            )
        if "population_note" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE medical_revision_sources ADD COLUMN population_note TEXT NULL"
            )


def downgrade(bind: Engine | Connection) -> None:
    """Avoid a destructive SQLite table rebuild for optional legacy columns."""

    return None
