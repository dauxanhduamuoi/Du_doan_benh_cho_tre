"""Add the isolated Auto Medical Knowledge lifecycle and durable queue."""

from sqlalchemy import Connection, Engine

from app.config import (
    AUTO_MEDICAL_KNOWLEDGE_AUTO_VISIBLE,
    AUTO_MEDICAL_KNOWLEDGE_DISPLAY_MODE,
)


def upgrade(bind: Engine | Connection) -> None:
    mode = (
        AUTO_MEDICAL_KNOWLEDGE_DISPLAY_MODE
        if AUTO_MEDICAL_KNOWLEDGE_DISPLAY_MODE
        in {"REVIEWED_ONLY", "REVIEWED_WITH_AUTO_FALLBACK"}
        else "REVIEWED_ONLY"
    )
    statements = [
        """
        CREATE TABLE IF NOT EXISTS auto_medical_knowledge_jobs (
            id INTEGER NOT NULL PRIMARY KEY,
            topic_id INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'QUEUED',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            trigger_type VARCHAR(16) NOT NULL DEFAULT 'PARENT',
            created_at DATETIME NOT NULL,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            next_retry_at DATETIME NULL,
            last_error_code VARCHAR(100) NULL,
            CONSTRAINT ck_auto_mk_jobs_status CHECK
              (status IN ('QUEUED','SEARCHING','GENERATING','READY','INSUFFICIENT','FAILED','CANCELLED')),
            CONSTRAINT ck_auto_mk_jobs_attempt_count CHECK (attempt_count >= 0),
            CONSTRAINT ck_auto_mk_jobs_trigger CHECK (trigger_type IN ('PARENT','ADMIN')),
            FOREIGN KEY(topic_id) REFERENCES medical_knowledge_topics(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS auto_medical_knowledge_revisions (
            id INTEGER NOT NULL PRIMARY KEY,
            topic_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            revision_number INTEGER NOT NULL,
            generation_status VARCHAR(20) NOT NULL,
            evidence_level VARCHAR(32) NOT NULL,
            evidence_scope VARCHAR(20) NULL,
            short_explanation_vi TEXT NULL,
            detailed_explanation_vi TEXT NULL,
            limitations_vi TEXT NULL,
            is_visible BOOLEAN NOT NULL DEFAULT 0,
            llm_model VARCHAR(100) NULL,
            prompt_version VARCHAR(100) NOT NULL,
            generated_at DATETIME NOT NULL,
            source_retrieved_at DATETIME NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT uq_auto_mk_revision_number UNIQUE(topic_id,revision_number),
            CONSTRAINT uq_auto_mk_revision_job UNIQUE(job_id),
            CONSTRAINT ck_auto_mk_revision_number CHECK (revision_number > 0),
            CONSTRAINT ck_auto_mk_revision_status CHECK (generation_status IN ('READY','INSUFFICIENT')),
            CONSTRAINT ck_auto_mk_evidence CHECK
              (evidence_level IN ('SUPPORTED','LIMITED_OR_INDIRECT','CONFLICTING','INSUFFICIENT')),
            CONSTRAINT ck_auto_mk_visible CHECK (is_visible IN (0,1)),
            FOREIGN KEY(topic_id) REFERENCES medical_knowledge_topics(id) ON DELETE CASCADE,
            FOREIGN KEY(job_id) REFERENCES auto_medical_knowledge_jobs(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS auto_medical_knowledge_topic_states (
            topic_id INTEGER NOT NULL PRIMARY KEY,
            current_revision_id INTEGER NULL,
            request_count INTEGER NOT NULL DEFAULT 0,
            first_requested_at DATETIME NULL,
            last_requested_at DATETIME NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT ck_auto_mk_state_request_count CHECK (request_count >= 0),
            FOREIGN KEY(topic_id) REFERENCES medical_knowledge_topics(id) ON DELETE CASCADE,
            FOREIGN KEY(current_revision_id) REFERENCES auto_medical_knowledge_revisions(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS auto_medical_knowledge_revision_sources (
            revision_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            evidence_content_id INTEGER NOT NULL,
            trust_class VARCHAR(40) NOT NULL,
            source_role VARCHAR(16) NOT NULL,
            sort_order INTEGER NOT NULL,
            relevance_note TEXT NOT NULL,
            population_relevance VARCHAR(24) NOT NULL,
            population_note TEXT NOT NULL,
            PRIMARY KEY(revision_id,source_id),
            CONSTRAINT ck_auto_mk_source_trust CHECK
              (trust_class IN ('PUBMED','PMC','WHO','CDC','OFFICIAL_HEALTH_AGENCY','PROFESSIONAL_MEDICAL_ORG','ACADEMIC')),
            CONSTRAINT ck_auto_mk_source_role CHECK (source_role IN ('PRIMARY','SUPPORTING')),
            CONSTRAINT ck_auto_mk_source_population CHECK
              (population_relevance IN ('PEDIATRIC_DIRECT','MIXED_AGE','ADULT_ONLY','ELDERLY_ONLY','UNKNOWN')),
            CONSTRAINT ck_auto_mk_source_sort CHECK (sort_order >= 0),
            FOREIGN KEY(revision_id) REFERENCES auto_medical_knowledge_revisions(id) ON DELETE CASCADE,
            FOREIGN KEY(source_id) REFERENCES medical_evidence_sources(id) ON DELETE CASCADE,
            FOREIGN KEY(evidence_content_id) REFERENCES medical_evidence_contents(id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS auto_medical_knowledge_discoveries (
            id INTEGER NOT NULL PRIMARY KEY,
            job_id INTEGER NOT NULL,
            source_id INTEGER NULL,
            provider VARCHAR(40) NOT NULL,
            trust_class VARCHAR(40) NOT NULL,
            decision VARCHAR(16) NOT NULL,
            reason_code VARCHAR(100) NOT NULL,
            metadata_json JSON NULL,
            discovered_at DATETIME NOT NULL,
            CONSTRAINT ck_auto_mk_discovery_trust CHECK
              (trust_class IN ('PUBMED','PMC','WHO','CDC','OFFICIAL_HEALTH_AGENCY','PROFESSIONAL_MEDICAL_ORG','ACADEMIC')),
            CONSTRAINT ck_auto_mk_discovery_decision CHECK (decision IN ('SELECTED','SKIPPED')),
            FOREIGN KEY(job_id) REFERENCES auto_medical_knowledge_jobs(id) ON DELETE CASCADE,
            FOREIGN KEY(source_id) REFERENCES medical_evidence_sources(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS auto_medical_knowledge_settings (
            id INTEGER NOT NULL PRIMARY KEY,
            display_mode VARCHAR(40) NOT NULL,
            auto_visible_default BOOLEAN NOT NULL DEFAULT 0,
            updated_at DATETIME NOT NULL,
            CONSTRAINT ck_auto_mk_settings_singleton CHECK (id = 1),
            CONSTRAINT ck_auto_mk_settings_display_mode CHECK
              (display_mode IN ('REVIEWED_ONLY','REVIEWED_WITH_AUTO_FALLBACK')),
            CONSTRAINT ck_auto_mk_settings_visible CHECK (auto_visible_default IN (0,1))
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_jobs_status_retry ON auto_medical_knowledge_jobs(status,next_retry_at)",
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_jobs_topic_id ON auto_medical_knowledge_jobs(topic_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_auto_mk_jobs_one_active_topic ON auto_medical_knowledge_jobs(topic_id) WHERE status IN ('QUEUED','SEARCHING','GENERATING')",
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_revisions_topic_id ON auto_medical_knowledge_revisions(topic_id)",
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_states_last_requested ON auto_medical_knowledge_topic_states(last_requested_at)",
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_revision_sources_source ON auto_medical_knowledge_revision_sources(source_id)",
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_revision_sources_content ON auto_medical_knowledge_revision_sources(evidence_content_id)",
        "CREATE INDEX IF NOT EXISTS ix_auto_mk_discoveries_job ON auto_medical_knowledge_discoveries(job_id)",
    ]
    context = bind.begin() if isinstance(bind, Engine) else _Noop(bind)
    with context as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO auto_medical_knowledge_settings "
            "(id,display_mode,auto_visible_default,updated_at) VALUES (1,?,?,CURRENT_TIMESTAMP)",
            (mode, int(AUTO_MEDICAL_KNOWLEDGE_AUTO_VISIBLE)),
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
