"""Add bounded generation provenance for deterministic Auto safe fallback."""

from sqlalchemy import Connection, Engine, inspect


def upgrade(bind: Engine | Connection) -> None:
    context = bind.begin() if isinstance(bind, Engine) else _Noop(bind)
    with context as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "auto_medical_knowledge_revisions"
            )
        }
        if "generation_mode" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE auto_medical_knowledge_revisions "
                "ADD COLUMN generation_mode VARCHAR(20) NULL"
            )
        if "fallback_reason_code" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE auto_medical_knowledge_revisions "
                "ADD COLUMN fallback_reason_code VARCHAR(40) NULL"
            )


class _Noop:
    def __init__(self, connection: Connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return None


def downgrade(bind: Engine | Connection) -> None:
    return None
