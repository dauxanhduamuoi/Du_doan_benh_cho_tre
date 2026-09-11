"""Add compatible Auto tier/method metadata and the Basic runtime control."""

from sqlalchemy import Connection, Engine, inspect


def upgrade(bind: Engine | Connection) -> None:
    context = bind.begin() if isinstance(bind, Engine) else _Noop(bind)
    with context as connection:
        revision_columns = {
            column["name"]
            for column in inspect(connection).get_columns("auto_medical_knowledge_revisions")
        }
        additions = {
            "auto_tier": "VARCHAR(12) NULL",
            "generation_method": "VARCHAR(20) NULL",
            "strict_failure_code": "VARCHAR(100) NULL",
            "strict_failure_stage": "VARCHAR(40) NULL",
        }
        for name, sql_type in additions.items():
            if name not in revision_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE auto_medical_knowledge_revisions ADD COLUMN {name} {sql_type}"
                )

        setting_columns = {
            column["name"]
            for column in inspect(connection).get_columns("auto_medical_knowledge_settings")
        }
        if "basic_fallback_enabled" not in setting_columns:
            # Existing Safe Fallback behavior was enabled implicitly. Defaulting
            # this additive control on preserves that production behavior.
            connection.exec_driver_sql(
                "ALTER TABLE auto_medical_knowledge_settings "
                "ADD COLUMN basic_fallback_enabled BOOLEAN NOT NULL DEFAULT 1"
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
