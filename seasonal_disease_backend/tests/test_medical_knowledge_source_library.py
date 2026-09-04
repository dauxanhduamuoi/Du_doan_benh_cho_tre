from __future__ import annotations

from datetime import datetime
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.medical_knowledge_draft_schemas import (
    DraftGenerationRequest,
    MedicalKnowledgeDraftProposal,
)
from app.medical_knowledge_models import (
    MedicalEvidenceContent,
    MedicalEvidenceSource,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalKnowledgeTopicSource,
    MedicalRevisionSource,
)
from app.pubmed_schemas import PubMedImportRequest, PubMedLookupRequest, PubMedSearchRequest
from app.services.medical_knowledge_draft_service import (
    DraftWorkflowValidationError,
    MedicalKnowledgeDraftService,
    load_deployed_disease_contexts,
)
from app.services.medical_knowledge_pubmed_service import (
    MedicalKnowledgePubMedService,
    load_deployed_disease_ids,
)
from app.services.pubmed_client import PubMedArticleRecord
from migrations.v005_medical_knowledge_topic_sources import downgrade, upgrade


def article(pmid: str, title: str) -> PubMedArticleRecord:
    return PubMedArticleRecord(
        pmid=pmid,
        title=title,
        authors="Fixture Author",
        journal="Fixture Journal",
        publication_year=2025,
        doi=f"10.1000/{pmid}",
        abstract_text=f"Controlled evidence abstract for {title}.",
        pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        raw_metadata={"publication_types": ["Observational Study"]},
    )


class FakePubMedClient:
    def __init__(self, records: list[PubMedArticleRecord]):
        self.records = {record.pmid: record for record in records}

    def search(self, _query: str, max_results: int):
        records = list(self.records.values())[:max_results]
        return len(records), records

    def fetch_records(self, pmids: list[str]):
        return [self.records[pmid] for pmid in pmids if pmid in self.records]

    def get_article_by_pmid(self, pmid: str):
        return self.records.get(pmid)


class ContextAwareGenerator:
    model_name = "fixture-model"

    def __init__(self, *, all_not_supportive: bool = False):
        self.contexts = []
        self.all_not_supportive = all_not_supportive

    def generate(self, context):
        self.contexts.append(context)
        assessments = [
            {
                "source_id": source.source_id,
                "relevance": (
                    "NOT_SUPPORTIVE"
                    if self.all_not_supportive or index > 0
                    else "DIRECT"
                ),
                "note_vi": "Đánh giá đúng nguồn staff đã chọn.",
                "population_relevance": "PEDIATRIC_DIRECT",
                "population_note": "Abstract nêu rõ đối tượng trẻ em.",
            }
            for index, source in enumerate(context.sources)
        ]
        return MedicalKnowledgeDraftProposal(
            evidence_level="LIMITED_OR_INDIRECT",
            evidence_scope="PARTIAL_GROUP",
            short_explanation_vi="Giải thích fixture có giới hạn.",
            detailed_explanation_vi="Bằng chứng quan sát không chứng minh nhân quả.",
            limitations_vi="Không áp dụng cho nguy cơ cá nhân.",
            source_assessments=assessments,
        )


@pytest.fixture
def engine():
    value = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(value, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(value)
    yield value
    value.dispose()


@pytest.fixture
def disease_files(tmp_path):
    manifest = tmp_path / "model_manifest.json"
    catalog = tmp_path / "disease_catalog.csv"
    manifest.write_text(
        json.dumps({"model_count": 2, "disease_order": ["5", "168"]}),
        encoding="utf-8",
    )
    catalog.write_text(
        "disease_group_id,disease_group_name,report_group_code\n"
        "5,Pneumonia,J12-J18\n"
        "168,Influenza,J09-J11\n",
        encoding="utf-8",
    )
    load_deployed_disease_ids.cache_clear()
    load_deployed_disease_contexts.cache_clear()
    return manifest, catalog


def import_request(disease_id: str, factor: str, *pmids: str):
    return PubMedImportRequest(
        disease_group_id=disease_id,
        weather_factor=factor,
        pmids=list(pmids),
    )


def pubmed_service(db: Session, manifest, records):
    return MedicalKnowledgePubMedService(
        db,
        FakePubMedClient(records),
        disease_manifest_path=manifest,
    )


def draft_service(db: Session, disease_files, generator):
    manifest, catalog = disease_files
    return MedicalKnowledgeDraftService(
        db,
        generator,
        disease_manifest_path=manifest,
        disease_catalog_path=catalog,
    )


def test_global_source_reused_and_topic_membership_is_unique_per_topic(
    engine, disease_files
):
    manifest, _catalog = disease_files
    record = article("34201085", "Climate and pneumonia")
    with Session(engine) as db:
        service = pubmed_service(db, manifest, [record])
        first = service.import_pmids(
            import_request("5", "humidity", record.pmid), added_by=None
        )
        repeated = service.import_pmids(
            import_request("5", "humidity", record.pmid), added_by=None
        )
        other_topic = service.import_pmids(
            import_request("168", "humidity", record.pmid), added_by=None
        )

        assert first.sources[0].topic_link_created is True
        assert repeated.sources[0].already_in_topic_library is True
        assert other_topic.sources[0].topic_link_created is True
        assert db.query(MedicalEvidenceSource).count() == 1
        assert db.query(MedicalKnowledgeTopicSource).count() == 2
        assert first.topic_id != other_topic.topic_id


def test_search_and_direct_lookup_distinguish_global_from_current_topic(
    engine, disease_files
):
    manifest, _catalog = disease_files
    record = article("34201085", "Climate and pneumonia")
    with Session(engine) as db:
        service = pubmed_service(db, manifest, [record])
        service.import_pmids(
            import_request("5", "humidity", record.pmid), added_by=None
        )
        pneumonia = service.search(
            PubMedSearchRequest(
                disease_group_id="5",
                weather_factor="humidity",
                disease_terms=["pneumonia"],
            )
        ).results[0]
        influenza = service.lookup_pmid(
            PubMedLookupRequest(
                pmid=record.pmid,
                disease_group_id="168",
                weather_factor="humidity",
            )
        )

        assert pneumonia.stored_globally is True
        assert pneumonia.in_topic_library is True
        assert influenza.result.stored_globally is True
        assert influenza.result.in_topic_library is False


def test_draft_uses_only_explicit_selected_sources_and_records_not_supportive(
    engine, disease_files
):
    manifest, _catalog = disease_files
    records = [article("34201085", "Source A"), article("22884022", "Source B")]
    with Session(engine) as db:
        imports = pubmed_service(db, manifest, records).import_pmids(
            import_request("5", "humidity", *(record.pmid for record in records)),
            added_by=None,
        )
        selected_id = imports.sources[1].id
        generator = ContextAwareGenerator(all_not_supportive=True)
        revision = draft_service(db, disease_files, generator).generate(
            DraftGenerationRequest(
                disease_group_id="5",
                weather_factor="humidity",
                source_ids=[selected_id],
            ),
            created_by=None,
        )

        links = db.query(MedicalRevisionSource).filter_by(revision_id=revision.id).all()
        assert [source.source_id for source in generator.contexts[0].sources] == [selected_id]
        assert [link.source_id for link in links] == [selected_id]
        assert links[0].relevance_note.startswith("NOT_SUPPORTIVE:")


@pytest.mark.parametrize(
    "source_ids,code",
    [([], "DRAFT_NO_SOURCES_SELECTED"), ([9999], "DRAFT_SOURCE_NOT_FOUND")],
)
def test_draft_rejects_empty_or_missing_explicit_selection_before_llm(
    engine, disease_files, source_ids, code
):
    generator = ContextAwareGenerator()
    with Session(engine) as db:
        with pytest.raises(DraftWorkflowValidationError) as captured:
            draft_service(db, disease_files, generator).generate(
                DraftGenerationRequest(
                    disease_group_id="168",
                    weather_factor="humidity",
                    source_ids=source_ids,
                ),
                created_by=None,
            )
        assert captured.value.code == code
        assert generator.contexts == []


def test_influenza_rejects_stale_pneumonia_selection_with_specific_code(
    engine, disease_files
):
    manifest, _catalog = disease_files
    record = article("34201085", "Pneumonia only source")
    generator = ContextAwareGenerator()
    with Session(engine) as db:
        source = pubmed_service(db, manifest, [record]).import_pmids(
            import_request("5", "humidity", record.pmid), added_by=None
        ).sources[0]
        with pytest.raises(DraftWorkflowValidationError) as captured:
            draft_service(db, disease_files, generator).generate(
                DraftGenerationRequest(
                    disease_group_id="168",
                    weather_factor="humidity",
                    source_ids=[source.id],
                ),
                created_by=None,
            )

        assert captured.value.code == "DRAFT_TOPIC_MISMATCH"
        assert generator.contexts == []
        assert db.query(MedicalKnowledgeRevision).count() == 0


def test_draft_rejects_evidence_snapshot_owned_by_another_source(
    engine, disease_files
):
    manifest, _catalog = disease_files
    records = [article("34201085", "Source A"), article("22884022", "Source B")]
    generator = ContextAwareGenerator()
    with Session(engine) as db:
        imported = pubmed_service(db, manifest, records).import_pmids(
            import_request("5", "humidity", *(record.pmid for record in records)),
            added_by=None,
        )
        first_id, selected_id = [source.id for source in imported.sources]
        service = draft_service(db, disease_files, generator)
        first_content = service.repository.get_preferred_evidence_contents([first_id])[first_id]
        service.repository.get_preferred_evidence_contents = lambda _ids: {
            selected_id: first_content
        }

        with pytest.raises(DraftWorkflowValidationError) as captured:
            service.generate(
                DraftGenerationRequest(
                    disease_group_id="5",
                    weather_factor="humidity",
                    source_ids=[selected_id],
                ),
                created_by=None,
            )

        assert captured.value.code == "DRAFT_SOURCE_EVIDENCE_MISMATCH"
        assert generator.contexts == []


def test_source_library_survives_file_database_restart(tmp_path, disease_files):
    manifest, _catalog = disease_files
    db_path = tmp_path / "restart.db"
    first_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(first_engine)
    record = article("34201085", "Persistent source")
    with Session(first_engine) as db:
        pubmed_service(db, manifest, [record]).import_pmids(
            import_request("5", "humidity", record.pmid), added_by=None
        )
    first_engine.dispose()

    second_engine = create_engine(f"sqlite:///{db_path}")
    with Session(second_engine) as db:
        library = pubmed_service(db, manifest, []).get_topic_source_library(
            disease_group_id="5", weather_factor="humidity"
        )
        assert [source.pmid for source in library.sources] == [record.pmid]
    second_engine.dispose()


def test_source_library_draft_selection_cross_flow_e2e(tmp_path, disease_files):
    manifest, _catalog = disease_files
    db_path = tmp_path / "source-library-draft-e2e.db"
    pneumonia_a = article("34201085", "Pneumonia source A")
    pneumonia_b = article("22884022", "Pneumonia source B")
    influenza_c = article("35964674", "Influenza source C")

    first_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(first_engine)
    with Session(first_engine) as db:
        imported = pubmed_service(
            db, manifest, [pneumonia_a, pneumonia_b]
        ).import_pmids(
            import_request("5", "humidity", pneumonia_a.pmid, pneumonia_b.pmid),
            added_by=None,
        )
        pneumonia_ids = {source.pmid: source.id for source in imported.sources}
    first_engine.dispose()

    restarted_engine = create_engine(f"sqlite:///{db_path}")
    with Session(restarted_engine) as db:
        service = pubmed_service(db, manifest, [influenza_c])
        pneumonia_library = service.get_topic_source_library(
            disease_group_id="5", weather_factor="humidity"
        )
        assert {source.pmid for source in pneumonia_library.sources} == {
            pneumonia_a.pmid,
            pneumonia_b.pmid,
        }

        pneumonia_generator = ContextAwareGenerator()
        pneumonia_revision = draft_service(
            db, disease_files, pneumonia_generator
        ).generate(
            DraftGenerationRequest(
                disease_group_id="5",
                weather_factor="humidity",
                source_ids=[pneumonia_ids[pneumonia_a.pmid]],
            ),
            created_by=None,
        )
        assert {
            link.source_id
            for link in db.query(MedicalRevisionSource).filter_by(
                revision_id=pneumonia_revision.id
            )
        } == {pneumonia_ids[pneumonia_a.pmid]}

        influenza_library_before = service.get_topic_source_library(
            disease_group_id="168", weather_factor="humidity"
        )
        assert influenza_library_before.sources == []
        influenza_import = service.import_pmids(
            import_request("168", "humidity", influenza_c.pmid), added_by=None
        )
        influenza_source_id = influenza_import.sources[0].id
        influenza_generator = ContextAwareGenerator()
        influenza_revision = draft_service(
            db, disease_files, influenza_generator
        ).generate(
            DraftGenerationRequest(
                disease_group_id="168",
                weather_factor="humidity",
                source_ids=[influenza_source_id],
            ),
            created_by=None,
        )
        assert {
            link.source_id
            for link in db.query(MedicalRevisionSource).filter_by(
                revision_id=influenza_revision.id
            )
        } == {influenza_source_id}
        assert pneumonia_ids[pneumonia_a.pmid] not in {
            source.source_id for source in influenza_generator.contexts[0].sources
        }
        assert pneumonia_ids[pneumonia_b.pmid] not in {
            source.source_id for source in influenza_generator.contexts[0].sources
        }
    restarted_engine.dispose()


def test_v005_migration_clean_repeat_and_downgrade():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    downgrade(engine)
    assert "medical_knowledge_topic_sources" not in inspect(engine).get_table_names()
    upgrade(engine)
    upgrade(engine)
    assert "medical_knowledge_topic_sources" in inspect(engine).get_table_names()
    downgrade(engine)
    assert "medical_knowledge_topic_sources" not in inspect(engine).get_table_names()
    engine.dispose()


def test_v005_upgrade_existing_v004_preserves_revision_rows_without_backfill():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    downgrade(engine)
    with Session(engine) as db:
        topic = MedicalKnowledgeTopic(
            disease_group_id="5", weather_factor="humidity"
        )
        source = MedicalEvidenceSource(
            source_type="PUBMED", pmid="34201085", title="Historical source"
        )
        db.add_all([topic, source])
        db.flush()
        revision = MedicalKnowledgeRevision(
            topic_id=topic.id,
            revision_number=1,
            evidence_level="LIMITED_OR_INDIRECT",
            evidence_scope="PARTIAL_GROUP",
            short_explanation_vi="Historical short explanation.",
            detailed_explanation_vi="Historical detailed explanation.",
            limitations_vi="Historical limitations.",
            status="DRAFT",
            parent_display_allowed=False,
            generated_by_llm=True,
        )
        db.add(revision)
        db.flush()
        db.add(
            MedicalRevisionSource(
                revision_id=revision.id,
                source_id=source.id,
                source_role="PRIMARY",
                sort_order=0,
                relevance_note="DIRECT: Historical assessment.",
            )
        )
        db.commit()

    upgrade(engine)
    upgrade(engine)
    with Session(engine) as db:
        assert db.query(MedicalKnowledgeRevision).count() == 1
        assert db.query(MedicalRevisionSource).count() == 1
        assert db.query(MedicalKnowledgeTopicSource).count() == 0
    engine.dispose()


def test_isolated_app_startup_runs_v005_lifespan_and_root_smoke(
    tmp_path, monkeypatch
):
    import app.database as app_database
    import app.main as main_module

    db_path = tmp_path / "startup-smoke.db"
    startup_engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    startup_sessions = sessionmaker(
        autocommit=False, autoflush=False, bind=startup_engine
    )
    monkeypatch.setattr(app_database, "engine", startup_engine)
    monkeypatch.setattr(app_database, "SessionLocal", startup_sessions)
    monkeypatch.setattr(main_module, "engine", startup_engine)
    monkeypatch.setattr(main_module, "SessionLocal", startup_sessions)
    monkeypatch.setattr(main_module, "WEATHER_AI_V3_PRELOAD", False)

    with TestClient(main_module.app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["message"] == "Seasonal Disease Forecast API is running."
        assert "medical_knowledge_topic_sources" in inspect(
            startup_engine
        ).get_table_names()

    startup_engine.dispose()
