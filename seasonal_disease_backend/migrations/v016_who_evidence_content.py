"""Extend generic evidence-content taxonomy for licensed WHO summaries.

SQLite cannot alter a CHECK constraint in place, so only the migration layer
uses a bounded table rebuild. Application code stays portable SQLAlchemy. The
SQL Server path drops/recreates the two named CHECK constraints in place.
"""

from __future__ import annotations

from sqlalchemy import Connection, Engine, inspect


KINDS_SQL = (
    "'ABSTRACT','PMC_FULL_TEXT','PMC_FULL_TEXT_EXCERPT',"
    "'OFFICIAL_SUMMARY_EXCERPT'"
)
ORIGINS_SQL = "'NCBI_PUBMED','NCBI_PMC','WHO_PUBLICATIONS_API'"


def _already_upgraded(connection: Connection) -> bool:
    tables = set(inspect(connection).get_table_names())
    if "medical_evidence_contents" not in tables:
        return True
    constraints = " ".join(
        str(item.get("sqltext") or "")
        for item in inspect(connection).get_check_constraints(
            "medical_evidence_contents"
        )
    )
    return (
        "OFFICIAL_SUMMARY_EXCERPT" in constraints
        and "WHO_PUBLICATIONS_API" in constraints
    )


def _sqlite_rebuild(connection: Connection) -> None:
    connection.exec_driver_sql(
        f"""
        CREATE TABLE medical_evidence_contents_v016 (
            id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            content_kind VARCHAR(32) NOT NULL,
            content_origin VARCHAR(32) NOT NULL,
            external_identifier VARCHAR(64),
            evidence_text TEXT NOT NULL,
            retrieved_at DATETIME NOT NULL,
            is_truncated BOOLEAN NOT NULL,
            license_name VARCHAR(255),
            license_url TEXT,
            provenance_json JSON,
            content_sha256 VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_medical_evidence_content_hash
                UNIQUE (source_id, content_sha256),
            CONSTRAINT ck_medical_evidence_content_kind
                CHECK (content_kind IN ({KINDS_SQL})),
            CONSTRAINT ck_medical_evidence_content_origin
                CHECK (content_origin IN ({ORIGINS_SQL})),
            CONSTRAINT ck_medical_evidence_content_truncated
                CHECK (is_truncated IN (0, 1)),
            FOREIGN KEY(source_id) REFERENCES medical_evidence_sources (id)
                ON DELETE CASCADE
        )
        """
    )
    connection.exec_driver_sql(
        "INSERT INTO medical_evidence_contents_v016 "
        "(id,source_id,content_kind,content_origin,external_identifier,"
        "evidence_text,retrieved_at,is_truncated,license_name,license_url,"
        "provenance_json,content_sha256,created_at) "
        "SELECT id,source_id,content_kind,content_origin,external_identifier,"
        "evidence_text,retrieved_at,is_truncated,license_name,license_url,"
        "provenance_json,content_sha256,created_at "
        "FROM medical_evidence_contents"
    )
    connection.exec_driver_sql("DROP TABLE medical_evidence_contents")
    connection.exec_driver_sql(
        "ALTER TABLE medical_evidence_contents_v016 "
        "RENAME TO medical_evidence_contents"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_medical_evidence_contents_source_id "
        "ON medical_evidence_contents (source_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_medical_evidence_contents_external_id "
        "ON medical_evidence_contents (external_identifier)"
    )


def _sql_server_upgrade(connection: Connection) -> None:
    connection.exec_driver_sql(
        "IF EXISTS (SELECT 1 FROM sys.check_constraints "
        "WHERE name = 'ck_medical_evidence_content_kind') "
        "ALTER TABLE medical_evidence_contents DROP CONSTRAINT "
        "ck_medical_evidence_content_kind"
    )
    connection.exec_driver_sql(
        "IF EXISTS (SELECT 1 FROM sys.check_constraints "
        "WHERE name = 'ck_medical_evidence_content_origin') "
        "ALTER TABLE medical_evidence_contents DROP CONSTRAINT "
        "ck_medical_evidence_content_origin"
    )
    connection.exec_driver_sql(
        "ALTER TABLE medical_evidence_contents ADD CONSTRAINT "
        "ck_medical_evidence_content_kind "
        f"CHECK (content_kind IN ({KINDS_SQL}))"
    )
    connection.exec_driver_sql(
        "ALTER TABLE medical_evidence_contents ADD CONSTRAINT "
        "ck_medical_evidence_content_origin "
        f"CHECK (content_origin IN ({ORIGINS_SQL}))"
    )


def _upgrade_connection(connection: Connection) -> None:
    if _already_upgraded(connection):
        return
    dialect = connection.dialect.name
    if dialect == "sqlite":
        _sqlite_rebuild(connection)
    elif dialect == "mssql":
        _sql_server_upgrade(connection)
    else:
        connection.exec_driver_sql(
            "ALTER TABLE medical_evidence_contents DROP CONSTRAINT "
            "ck_medical_evidence_content_kind"
        )
        connection.exec_driver_sql(
            "ALTER TABLE medical_evidence_contents DROP CONSTRAINT "
            "ck_medical_evidence_content_origin"
        )
        connection.exec_driver_sql(
            "ALTER TABLE medical_evidence_contents ADD CONSTRAINT "
            "ck_medical_evidence_content_kind "
            f"CHECK (content_kind IN ({KINDS_SQL}))"
        )
        connection.exec_driver_sql(
            "ALTER TABLE medical_evidence_contents ADD CONSTRAINT "
            "ck_medical_evidence_content_origin "
            f"CHECK (content_origin IN ({ORIGINS_SQL}))"
        )


def upgrade(bind: Engine | Connection) -> None:
    if isinstance(bind, Connection):
        if bind.dialect.name == "sqlite":
            enabled = bool(bind.connection.driver_connection.execute(
                "PRAGMA foreign_keys"
            ).fetchone()[0])
            if enabled:
                raise RuntimeError(
                    "SQLite V016 requires an Engine or a connection with foreign keys disabled"
                )
        _upgrade_connection(bind)
        return

    with bind.connect() as connection:
        if _already_upgraded(connection):
            connection.rollback()
            return
        connection.rollback()
        if connection.dialect.name == "sqlite":
            raw = connection.connection.driver_connection
            was_enabled = bool(raw.execute("PRAGMA foreign_keys").fetchone()[0])
            raw.execute("PRAGMA foreign_keys=OFF")
            try:
                with connection.begin():
                    _sqlite_rebuild(connection)
            finally:
                raw.execute(f"PRAGMA foreign_keys={'ON' if was_enabled else 'OFF'}")
        else:
            with connection.begin():
                _upgrade_connection(connection)


def downgrade(bind: Engine | Connection) -> None:
    # Content using the new taxonomy may exist; a destructive downgrade would
    # either lose evidence or violate constraints, so project convention keeps
    # this migration forward-only.
    return None
