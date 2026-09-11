"""Add durable topic-level Auto visibility state and audit history.

The ALTER TABLE statements below are deliberately isolated in this migration.
Application code uses SQLAlchemy ORM/Core only, so a future SQL Server migration
can replace this DDL without changing the visibility policy.
"""

from sqlalchemy import Connection, Engine, inspect


def upgrade(bind: Engine | Connection) -> None:
    context = bind.begin() if isinstance(bind, Engine) else _Noop(bind)
    with context as connection:
        state_columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "auto_medical_knowledge_topic_states"
            )
        }
        if "is_hidden_by_staff" not in state_columns:
            # Legacy per-revision false values are ambiguous: they may mean an
            # explicit revoke or simply that nobody clicked the old allow button.
            # Defaulting every existing topic to unhidden is deterministic and
            # avoids incorrectly inventing staff decisions during migration.
            connection.exec_driver_sql(
                "ALTER TABLE auto_medical_knowledge_topic_states "
                "ADD COLUMN is_hidden_by_staff BOOLEAN NOT NULL DEFAULT 0"
            )
        if "hidden_at" not in state_columns:
            connection.exec_driver_sql(
                "ALTER TABLE auto_medical_knowledge_topic_states "
                "ADD COLUMN hidden_at DATETIME NULL"
            )

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS auto_medical_knowledge_visibility_audits (
                id INTEGER NOT NULL PRIMARY KEY,
                topic_id INTEGER NOT NULL,
                action VARCHAR(24) NOT NULL,
                actor_user_id INTEGER NULL,
                created_at DATETIME NOT NULL,
                CONSTRAINT ck_auto_mk_visibility_audit_action CHECK
                  (action IN ('HIDE_AUTO_TOPIC','UNHIDE_AUTO_TOPIC')),
                FOREIGN KEY(topic_id) REFERENCES medical_knowledge_topics(id) ON DELETE CASCADE,
                FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_auto_mk_visibility_audits_topic "
            "ON auto_medical_knowledge_visibility_audits(topic_id,created_at)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_auto_mk_visibility_audits_actor "
            "ON auto_medical_knowledge_visibility_audits(actor_user_id)"
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
