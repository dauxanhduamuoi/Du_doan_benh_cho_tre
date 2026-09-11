"""Add provider-neutral identity and source taxonomy to evidence sources.

DDL is isolated here because SQLite and a future SQL Server deployment use
different idempotent ALTER/filtered-index syntax. Application code remains
portable SQLAlchemy ORM/Core.
"""

from sqlalchemy import Connection, Engine, inspect, text


def upgrade(bind: Engine | Connection) -> None:
    context = bind.begin() if isinstance(bind, Engine) else _Noop(bind)
    with context as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("medical_evidence_sources")
        }
        additions = {
            "provider_id": "VARCHAR(40) NULL",
            "external_id": "VARCHAR(255) NULL",
            "source_kind": "VARCHAR(40) NULL",
        }
        for name, sql_type in additions.items():
            if name not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE medical_evidence_sources ADD COLUMN {name} {sql_type}"
                )

        # Historical source_type values were provider identities. Preserve them
        # deterministically; do not guess a provider for OTHER legacy rows.
        connection.execute(
            text(
                "UPDATE medical_evidence_sources "
                "SET provider_id = source_type "
                "WHERE provider_id IS NULL AND source_type IN ('PUBMED','WHO','CDC')"
            )
        )
        connection.execute(
            text(
                "UPDATE medical_evidence_sources "
                "SET external_id = pmid "
                "WHERE external_id IS NULL AND source_type = 'PUBMED' AND pmid IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE medical_evidence_sources "
                "SET source_kind = 'RESEARCH_ARTICLE' "
                "WHERE source_kind IS NULL AND source_type = 'PUBMED'"
            )
        )

        index_names = {
            index["name"]
            for index in inspect(connection).get_indexes("medical_evidence_sources")
        }
        if "ix_medical_sources_provider_external" not in index_names:
            connection.exec_driver_sql(
                "CREATE INDEX ix_medical_sources_provider_external "
                "ON medical_evidence_sources(provider_id,external_id)"
            )
        if "ix_medical_sources_kind" not in index_names:
            connection.exec_driver_sql(
                "CREATE INDEX ix_medical_sources_kind ON medical_evidence_sources(source_kind)"
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
