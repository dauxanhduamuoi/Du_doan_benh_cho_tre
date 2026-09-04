"""Persist provider-level cooldown for the durable Auto queue."""

from sqlalchemy import Connection, Engine


def upgrade(bind: Engine | Connection) -> None:
    context = bind.begin() if isinstance(bind, Engine) else _Noop(bind)
    with context as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS auto_medical_knowledge_provider_cooldowns (
                provider VARCHAR(40) NOT NULL PRIMARY KEY,
                cooldown_until DATETIME NOT NULL,
                reason VARCHAR(100) NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
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
