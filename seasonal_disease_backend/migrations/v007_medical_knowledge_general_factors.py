"""Generalize Medical Knowledge topics while preserving legacy weather rows."""

from sqlalchemy import Connection, Engine, inspect


def _raw_connection(bind: Engine | Connection):
    if isinstance(bind, Engine):
        return bind.raw_connection(), True
    return bind.connection, False


def upgrade(bind: Engine | Connection) -> None:
    inspector = inspect(bind)
    if "medical_knowledge_topics" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("medical_knowledge_topics")}
    if {"factor_type", "factor_key", "factor_value"}.issubset(columns):
        with bind.begin() if isinstance(bind, Engine) else _Noop(bind) as connection:
            connection.exec_driver_sql(
                "UPDATE medical_knowledge_topics SET factor_type='WEATHER', "
                "factor_key=weather_factor, factor_value=NULL WHERE factor_type IS NULL"
            )
        return

    raw, owned = _raw_connection(bind)
    cursor = raw.cursor()
    try:
        raw.commit()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            CREATE TABLE medical_knowledge_topics_v007 (
                id INTEGER NOT NULL PRIMARY KEY,
                disease_group_id VARCHAR(100) NOT NULL,
                weather_factor VARCHAR(32) NULL,
                factor_type VARCHAR(16) NOT NULL,
                factor_key VARCHAR(32) NOT NULL,
                factor_value VARCHAR(100) NULL,
                published_revision_id INTEGER NULL,
                created_by INTEGER NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT ck_medical_topics_factor_type CHECK
                    (factor_type IN ('WEATHER','AGE','SEX','SEASONALITY')),
                CONSTRAINT ck_medical_topics_legacy_weather CHECK
                    ((factor_type='WEATHER' AND weather_factor=factor_key AND factor_value IS NULL)
                     OR (factor_type<>'WEATHER' AND weather_factor IS NULL)),
                FOREIGN KEY(published_revision_id) REFERENCES medical_knowledge_revisions(id) ON DELETE SET NULL,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO medical_knowledge_topics_v007
                (id,disease_group_id,weather_factor,factor_type,factor_key,factor_value,
                 published_revision_id,created_by,created_at,updated_at)
            SELECT id,disease_group_id,weather_factor,'WEATHER',weather_factor,NULL,
                   published_revision_id,created_by,created_at,updated_at
            FROM medical_knowledge_topics
            """
        )
        cursor.execute("DROP TABLE medical_knowledge_topics")
        cursor.execute("ALTER TABLE medical_knowledge_topics_v007 RENAME TO medical_knowledge_topics")
        cursor.execute(
            "CREATE INDEX ix_medical_topics_disease_group_id "
            "ON medical_knowledge_topics(disease_group_id)"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX uq_medical_topics_generic_selector "
            "ON medical_knowledge_topics"
            "(disease_group_id,factor_type,factor_key,COALESCE(factor_value,''))"
        )
        raw.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
    except Exception:
        raw.rollback()
        cursor.execute("PRAGMA foreign_keys=ON")
        raise
    finally:
        cursor.close()
        if owned:
            raw.close()


class _Noop:
    def __init__(self, connection: Connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return None


def downgrade(bind: Engine | Connection) -> None:
    return None
