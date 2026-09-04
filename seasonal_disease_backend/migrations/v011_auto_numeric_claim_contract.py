"""Persist verified Auto Numeric Claim Contract V2 provenance additively."""

from sqlalchemy import Connection, Engine


def upgrade(bind: Engine | Connection) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS auto_medical_knowledge_numeric_claims (
            id INTEGER NOT NULL PRIMARY KEY,
            revision_id INTEGER NOT NULL,
            claim_order INTEGER NOT NULL,
            claim_kind VARCHAR(32) NOT NULL,
            value_text VARCHAR(100) NOT NULL,
            unit VARCHAR(100) NULL,
            source_id INTEGER NOT NULL,
            evidence_content_id INTEGER NOT NULL,
            support_start INTEGER NOT NULL,
            support_end INTEGER NOT NULL,
            support_sha256 VARCHAR(64) NOT NULL,
            CONSTRAINT uq_auto_mk_numeric_claim_order UNIQUE(revision_id,claim_order),
            CONSTRAINT ck_auto_mk_numeric_claim_kind CHECK
              (claim_kind IN ('COUNT','PERCENTAGE','RATE','RATIO_OR_EFFECT','MEASUREMENT','AGE','DURATION','TEMPORAL_PERIOD','OTHER_NUMERIC')),
            CONSTRAINT ck_auto_mk_numeric_claim_order CHECK
              (claim_order >= 0 AND claim_order < 10),
            CONSTRAINT ck_auto_mk_numeric_claim_offsets CHECK
              (support_start >= 0 AND support_end > support_start),
            FOREIGN KEY(revision_id) REFERENCES auto_medical_knowledge_revisions(id) ON DELETE CASCADE,
            FOREIGN KEY(source_id) REFERENCES medical_evidence_sources(id) ON DELETE RESTRICT,
            FOREIGN KEY(evidence_content_id) REFERENCES medical_evidence_contents(id) ON DELETE RESTRICT
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_numeric_claim_revision ON auto_medical_knowledge_numeric_claims(revision_id)",
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_numeric_claim_source ON auto_medical_knowledge_numeric_claims(source_id)",
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_numeric_claim_content ON auto_medical_knowledge_numeric_claims(evidence_content_id)",
    ]
    context = bind.begin() if isinstance(bind, Engine) else _Noop(bind)
    with context as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


class _Noop:
    def __init__(self, connection: Connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return None


def downgrade(bind: Engine | Connection) -> None:
    return None
