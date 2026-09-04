"""Persist the Auto Medical Knowledge runtime operational switch."""

from sqlalchemy import Connection, Engine


def upgrade(bind: Engine | Connection) -> None:
    context = bind.begin() if isinstance(bind, Engine) else _Noop(bind)
    with context as connection:
        columns = {
            str(row[1])
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(auto_medical_knowledge_settings)"
            ).fetchall()
        }
        if "enabled" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE auto_medical_knowledge_settings "
                "ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT 0"
            )
        connection.exec_driver_sql(
            "UPDATE auto_medical_knowledge_settings SET enabled = 0 "
            "WHERE enabled IS NULL"
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
