from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import ValidationError
from datetime import datetime

from sqlalchemy import create_engine, event, inspect, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.medical_knowledge_draft_schemas import (
    DraftGenerationContext,
    DraftGenerationRequest,
    DraftRevisionPatch,
    MedicalKnowledgeDraftProposal,
    SourceAssessment,
)
from app.medical_knowledge_models import (
    MedicalEvidenceContent,
    MedicalEvidenceSource,
    MedicalKnowledgePublication,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalKnowledgeTopicSource,
    MedicalRevisionSource,
)
from app.models import User
from app.routers.medical_knowledge_drafts import (
    get_approval_service,
    get_draft_service,
    get_publication_service,
    router,
)
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.security import create_access_token
from app.services.medical_knowledge_draft_generator import (
    DraftGeneratorConfigurationError,
    DraftGeneratorOutputError,
    DraftGeneratorRateLimitError,
    DraftGeneratorRefusalError,
    DraftGeneratorUnavailableError,
    OpenAIMedicalKnowledgeDraftGenerator,
)
from app.services.medical_knowledge_draft_service import (
    DraftNotEditableError,
    DraftWorkflowNotFoundError,
    DraftWorkflowValidationError,
    MedicalKnowledgeDraftService,
    load_deployed_disease_contexts,
)
from app.services.medical_knowledge_approval_service import (
    ApprovalConflictError,
    ApprovalNotFoundError,
    ApprovalValidationError,
    MedicalKnowledgeApprovalService,
)
from app.services.medical_knowledge_publication_service import (
    MedicalKnowledgePublicationService,
    PublicationConflictError,
    PublicationNotFoundError,
    PublicationValidationError,
)
from app.published_medical_knowledge_schemas import PublishedMedicalKnowledgeBatchRequest
from app.services.published_medical_knowledge_read_service import (
    PublishedMedicalKnowledgeReadService,
)
from app.services.medical_knowledge_population_policy import has_pediatric_direct_support
from migrations.v003_medical_knowledge_publication import (
    downgrade as downgrade_publication,
    upgrade as upgrade_publication,
)
from migrations.v006_medical_knowledge_pediatric_population import (
    upgrade as upgrade_pediatric_population,
)


def proposal(**overrides) -> MedicalKnowledgeDraftProposal:
    values = {
        "evidence_level": "LIMITED_OR_INDIRECT",
        "evidence_scope": "PARTIAL_GROUP",
        "short_explanation_vi": "Các nghiên cứu ghi nhận một mối liên hệ ở mức quần thể.",
        "detailed_explanation_vi": "Tóm tắt cho thấy mối liên hệ quan sát, chưa chứng minh quan hệ nhân quả.",
        "limitations_vi": "Bằng chứng chỉ áp dụng cho một phần nhóm và không dự đoán nguy cơ cá nhân.",
        "source_assessments": [
            {
                "source_id": 1,
                "relevance": "DIRECT",
                "note_vi": "Đánh giá trực tiếp yếu tố mưa.",
                "population_relevance": "PEDIATRIC_DIRECT",
                "population_note": "Abstract mô tả trực tiếp trẻ em.",
            }
        ],
    }
    values.update(overrides)
    return MedicalKnowledgeDraftProposal(**values)


class FakeGenerator:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.contexts = []

    @property
    def model_name(self):
        return "openai-test-model"

    def generate(self, context):
        self.contexts.append(context)
        if self.error:
            raise self.error
        return self.result or proposal()


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def disease_files(tmp_path):
    manifest = tmp_path / "model_manifest.json"
    catalog = tmp_path / "disease_catalog.csv"
    manifest.write_text(
        json.dumps({"model_count": 2, "disease_order": ["1", "5"]}), encoding="utf-8"
    )
    catalog.write_text(
        "disease_group_id,disease_group_name,report_group_code\n"
        "1,Cholera,A00\n"
        "5,Infectious gastroenteritis,A09\n",
        encoding="utf-8",
    )
    load_deployed_disease_contexts.cache_clear()
    return manifest, catalog


def add_source(
    db: Session,
    *,
    source_id: int = 1,
    source_type: str = "PUBMED",
    abstract: str | None = "An observational abstract about rainfall and disease incidence.",
):
    source = MedicalEvidenceSource(
        id=source_id,
        source_type=source_type,
        pmid=str(10000000 + source_id),
        doi=f"10.1000/{source_id}",
        title=f"Weather evidence {source_id}",
        authors="Researcher A",
        journal="Journal",
        publication_year=2024,
        abstract_text=abstract,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{10000000 + source_id}/",
        raw_metadata_json={"publication_types": ["Observational Study"]},
    )
    db.add(source)
    topic = db.query(MedicalKnowledgeTopic).filter_by(
        disease_group_id="5", weather_factor="precipitation"
    ).one_or_none()
    if topic is None:
        topic = MedicalKnowledgeTopic(
            disease_group_id="5",
            weather_factor="precipitation",
        )
        db.add(topic)
        db.flush()
    content = MedicalEvidenceContent(
        source_id=source.id,
        content_kind="ABSTRACT",
        content_origin="NCBI_PUBMED",
        evidence_text=abstract or "",
        retrieved_at=datetime(2026, 8, 24, 8, 0, 0),
        is_truncated=False,
        content_sha256=f"{source_id:064x}",
    )
    db.add(content)
    db.add(MedicalKnowledgeTopicSource(topic_id=topic.id, source_id=source.id))
    db.commit()
    return source


def make_service(db, disease_files, generator=None, **kwargs):
    manifest, catalog = disease_files
    return MedicalKnowledgeDraftService(
        db,
        generator or FakeGenerator(),
        disease_manifest_path=manifest,
        disease_catalog_path=catalog,
        **kwargs,
    )


def generation_request(source_ids=None, **overrides):
    values = {
        "disease_group_id": "5",
        "weather_factor": "precipitation",
        "source_ids": source_ids or [1],
    }
    values.update(overrides)
    return DraftGenerationRequest(**values)


@pytest.mark.parametrize(
    "population_relevance",
    ["PEDIATRIC_DIRECT", "MIXED_AGE", "ADULT_ONLY", "ELDERLY_ONLY", "UNKNOWN"],
)
def test_source_assessment_accepts_bounded_population_categories(population_relevance):
    assessment = SourceAssessment(
        source_id=1,
        relevance="DIRECT",
        note_vi="Direct disease-weather assessment.",
        population_relevance=population_relevance,
        population_note="Population statement grounded in selected evidence text.",
    )
    assert assessment.population_relevance == population_relevance


def test_pediatric_not_supportive_source_does_not_satisfy_support_requirement():
    assessment = SourceAssessment(
        source_id=1,
        relevance="NOT_SUPPORTIVE",
        note_vi="The selected source does not support this disease-weather relationship.",
        population_relevance="PEDIATRIC_DIRECT",
        population_note="The abstract explicitly studies children.",
    )
    assert has_pediatric_direct_support([assessment]) is False


def test_v006_migration_preserves_legacy_rows_as_null_unknown(tmp_path):
    legacy_engine = create_engine(f"sqlite:///{(tmp_path / 'legacy_population.db').as_posix()}")
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE medical_revision_sources ("
            "revision_id INTEGER NOT NULL, source_id INTEGER NOT NULL, "
            "source_role VARCHAR(16) NOT NULL, sort_order INTEGER NOT NULL, "
            "relevance_note TEXT, evidence_content_id INTEGER, "
            "PRIMARY KEY (revision_id, source_id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO medical_revision_sources "
            "(revision_id, source_id, source_role, sort_order, relevance_note) "
            "VALUES (1, 2, 'PRIMARY', 0, 'DIRECT: legacy')"
        )

    upgrade_pediatric_population(legacy_engine)
    upgrade_pediatric_population(legacy_engine)

    columns = {item["name"] for item in inspect(legacy_engine).get_columns("medical_revision_sources")}
    with legacy_engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT population_relevance, population_note FROM medical_revision_sources"
        ).one()
    assert {"population_relevance", "population_note"} <= columns
    assert tuple(row) == (None, None)
    legacy_engine.dispose()


def test_legacy_revision_reads_population_as_unknown_without_rewrite(db, disease_files):
    add_source(db)
    service = make_service(db, disease_files)
    generated = service.generate(generation_request(), created_by=None)
    link = db.query(MedicalRevisionSource).filter_by(revision_id=generated.id).one()
    link.population_relevance = None
    link.population_note = None
    db.commit()

    readback = service.get_revision(generated.id)

    assert readback.sources[0].population_relevance == "UNKNOWN"
    assert readback.sources[0].population_note is None
    assert readback.parent_tier2_eligible is False
    db.refresh(link)
    assert link.population_relevance is None and link.population_note is None


def test_abstract_without_reported_age_can_persist_unknown_population(db, disease_files):
    add_source(db, abstract="Patients were enrolled and rainfall outcomes were observed.")
    unknown = proposal(source_assessments=[{
        "source_id": 1,
        "relevance": "DIRECT",
        "note_vi": "Direct observational disease-weather result.",
        "population_relevance": "UNKNOWN",
        "population_note": "The supplied abstract does not report participant ages.",
    }])
    generated = make_service(db, disease_files, FakeGenerator(unknown)).generate(
        generation_request(), created_by=None
    )
    assert generated.sources[0].population_relevance == "UNKNOWN"
    assert generated.sources[0].population_note == (
        "The supplied abstract does not report participant ages."
    )
    assert generated.parent_tier2_eligible is False


def openai_response(result: dict | None = None):
    return {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(result or proposal().model_dump()),
                    }
                ],
            }
        ]
    }


def provider_context() -> DraftGenerationContext:
    return DraftGenerationContext(
        disease_group_id="5",
        disease_group_name="Infectious gastroenteritis",
        report_group_code="A09",
        weather_factor="precipitation",
        sources=[
            {
                "source_id": 1,
                "source_type": "PUBMED",
                "pmid": "10000001",
                "doi": None,
                "title": "Rainfall evidence",
                "authors": None,
                "journal": "Journal",
                "publication_year": 2024,
                "publication_types": [],
                "evidence_content_id": 10,
                "content_kind": "ABSTRACT",
                "evidence_text": "Selected abstract only.",
                "content_origin": "NCBI_PUBMED",
            }
        ],
    )


def test_openai_provider_sends_only_bounded_selected_context_and_strict_schema():
    captured = {}

    def handler(request: httpx.Request):
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=openai_response())

    generator = OpenAIMedicalKnowledgeDraftGenerator(
        api_key="sk-fixture-secret",
        model="configured-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = generator.generate(provider_context())
    payload_text = captured["body"]["input"][1]["content"][0]["text"]
    assert result.evidence_level == "LIMITED_OR_INDIRECT"
    assert captured["body"]["store"] is False
    assert "tools" not in captured["body"]
    assert captured["body"]["text"]["format"]["strict"] is True
    assert "Selected abstract only." in payload_text
    assert "patient" not in payload_text.lower()
    assert "child_age" not in payload_text.lower()
    assert "sk-fixture-secret" not in json.dumps(captured["body"])


@pytest.mark.parametrize(
    "field,value",
    [("evidence_level", "STRONG"), ("evidence_scope", "ONE_DISEASE")],
)
def test_structured_output_rejects_invalid_enums(field, value):
    with pytest.raises(ValidationError):
        proposal(**{field: value})


def test_openai_provider_missing_config_is_safe():
    generator = OpenAIMedicalKnowledgeDraftGenerator(api_key=None, model=None)
    with pytest.raises(DraftGeneratorConfigurationError):
        generator.generate(provider_context())
    generator.close()


def test_openai_provider_timeout_is_safe():
    def handler(_request):
        raise httpx.ReadTimeout("timed out")

    generator = OpenAIMedicalKnowledgeDraftGenerator(
        api_key="secret", model="model", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(DraftGeneratorUnavailableError):
        generator.generate(provider_context())


def test_openai_provider_rate_limit_is_safe():
    generator = OpenAIMedicalKnowledgeDraftGenerator(
        api_key="secret",
        model="model",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429))),
    )
    with pytest.raises(DraftGeneratorRateLimitError):
        generator.generate(provider_context())


@pytest.mark.parametrize(
    "body,error",
    [
        ({"output": []}, DraftGeneratorOutputError),
        (
            {"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]},
            DraftGeneratorRefusalError,
        ),
        (
            {"output": [{"type": "message", "content": [{"type": "output_text", "text": "not-json"}]}]},
            DraftGeneratorOutputError,
        ),
    ],
)
def test_openai_provider_invalid_or_refused_output_is_safe(body, error):
    generator = OpenAIMedicalKnowledgeDraftGenerator(
        api_key="secret",
        model="model",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ),
    )
    with pytest.raises(error):
        generator.generate(provider_context())


def test_valid_deployed_disease_and_weather_reach_provider(db, disease_files):
    add_source(db)
    generator = FakeGenerator()
    make_service(db, disease_files, generator).generate(generation_request(), created_by=None)
    assert generator.contexts[0].disease_group_name == "Infectious gastroenteritis"
    assert generator.contexts[0].report_group_code == "A09"
    assert generator.contexts[0].weather_factor == "precipitation"


def test_invalid_deployed_disease_is_rejected_before_provider(db, disease_files):
    add_source(db)
    generator = FakeGenerator()
    with pytest.raises(DraftWorkflowNotFoundError):
        make_service(db, disease_files, generator).generate(
            generation_request(disease_group_id="999"), created_by=None
        )
    assert generator.contexts == []


def test_invalid_weather_and_duplicate_sources_are_rejected_by_schema():
    with pytest.raises(ValidationError):
        generation_request(weather_factor="pressure")
    with pytest.raises(ValidationError):
        generation_request(source_ids=[1, 1])


def test_source_not_found_is_rejected(db, disease_files):
    with pytest.raises(DraftWorkflowNotFoundError):
        make_service(db, disease_files).generate(generation_request(), created_by=None)


def test_non_pubmed_source_is_rejected(db, disease_files):
    add_source(db, source_type="WHO")
    with pytest.raises(DraftWorkflowValidationError, match="PubMed"):
        make_service(db, disease_files).generate(generation_request(), created_by=None)


def test_no_usable_abstract_is_rejected(db, disease_files):
    add_source(db, abstract="  ")
    with pytest.raises(DraftWorkflowValidationError, match="AI có thể đọc"):
        make_service(db, disease_files).generate(generation_request(), created_by=None)


def test_total_source_input_is_bounded_without_silent_truncation(db, disease_files):
    add_source(db, abstract="evidence " * 100)
    generator = FakeGenerator()
    with pytest.raises(DraftWorkflowValidationError, match="safe input limit"):
        make_service(db, disease_files, generator, max_input_chars=100).generate(
            generation_request(), created_by=None
        )
    assert generator.contexts == []


def _assessments_for(source_ids: list[int]) -> list[dict]:
    return [
        {
            "source_id": source_id,
            "relevance": "DIRECT" if source_id == source_ids[0] else "NOT_SUPPORTIVE",
            "note_vi": "Đánh giá đúng nguồn đã chọn.",
            "population_relevance": "PEDIATRIC_DIRECT",
            "population_note": "Nguồn fixture nghiên cứu trực tiếp trên trẻ em.",
        }
        for source_id in source_ids
    ]


@pytest.mark.parametrize("source_count", [1, 8, 9])
def test_configured_source_capacity_accepts_one_through_nine_usable_sources(
    db, disease_files, source_count
):
    source_ids = list(range(1, source_count + 1))
    for source_id in source_ids:
        add_source(db, source_id=source_id)
    generator = FakeGenerator(proposal(source_assessments=_assessments_for(source_ids)))

    revision = make_service(db, disease_files, generator).generate(
        generation_request(source_ids=source_ids), created_by=None
    )

    assert [source.source_id for source in generator.contexts[0].sources] == source_ids
    assert len(revision.sources) == source_count


def test_ten_source_draft_e2e_persists_exact_provenance_and_remains_approvable(
    db, disease_files
):
    reviewer = User(
        username="ten-source-reviewer",
        password_hash="x",
        role="staff",
        is_active=True,
    )
    db.add(reviewer)
    db.flush()
    source_ids = list(range(1, 11))
    for source_id in source_ids:
        add_source(db, source_id=source_id)
    generator = FakeGenerator(proposal(source_assessments=_assessments_for(source_ids)))

    draft = make_service(db, disease_files, generator).generate(
        generation_request(source_ids=source_ids), created_by=reviewer.id
    )

    links = db.query(MedicalRevisionSource).filter_by(revision_id=draft.id).order_by(
        MedicalRevisionSource.sort_order
    ).all()
    assert [source.source_id for source in generator.contexts[0].sources] == source_ids
    assert [link.source_id for link in links] == source_ids
    assert [link.sort_order for link in links] == list(range(10))
    approval = MedicalKnowledgeApprovalService(db).approve(draft.id, approved_by=reviewer.id)
    assert approval.status == "APPROVED"


def test_eleven_sources_are_rejected_with_specific_code_without_persisting_revision(
    db, disease_files
):
    source_ids = list(range(1, 12))
    for source_id in source_ids:
        add_source(db, source_id=source_id)
    generator = FakeGenerator(proposal(source_assessments=_assessments_for(source_ids[:10])))

    with pytest.raises(DraftWorkflowValidationError) as captured:
        make_service(db, disease_files, generator).generate(
            generation_request(source_ids=source_ids), created_by=None
        )

    assert captured.value.code == "DRAFT_TOO_MANY_SOURCES"
    assert "tối đa 10 nguồn" in str(captured.value)
    assert generator.contexts == []
    assert db.query(MedicalKnowledgeRevision).count() == 0


def test_duplicate_source_ids_are_rejected_and_cannot_bypass_capacity():
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        generation_request(source_ids=[1] * 11)


def test_mixed_usable_and_unusable_explicit_request_is_rejected_fail_closed(
    db, disease_files
):
    add_source(db, source_id=1)
    add_source(db, source_id=2, abstract=None)
    generator = FakeGenerator()

    with pytest.raises(DraftWorkflowValidationError) as captured:
        make_service(db, disease_files, generator).generate(
            generation_request(source_ids=[1, 2]), created_by=None
        )

    assert captured.value.code == "DRAFT_SOURCE_NO_USABLE_EVIDENCE"
    assert "2" in str(captured.value)
    assert generator.contexts == []
    assert db.query(MedicalKnowledgeRevision).count() == 0


def test_preexisting_evidence_is_bounded_per_source_before_provider(
    db, disease_files
):
    add_source(db, abstract="x" * 200)
    generator = FakeGenerator()

    make_service(db, disease_files, generator, max_chars_per_source=37).generate(
        generation_request(), created_by=None
    )

    assert generator.contexts[0].sources[0].evidence_text == "x" * 37


def test_unknown_source_id_from_provider_is_rejected_without_revision(db, disease_files):
    add_source(db)
    generator = FakeGenerator(
        proposal(source_assessments=[{
            "source_id": 999,
            "relevance": "DIRECT",
            "note_vi": "Sai",
            "population_relevance": "PEDIATRIC_DIRECT",
            "population_note": "Abstract mô tả trẻ em.",
        }])
    )
    with pytest.raises(DraftWorkflowValidationError, match="not selected"):
        make_service(db, disease_files, generator).generate(generation_request(), created_by=None)
    assert db.query(MedicalKnowledgeRevision).count() == 0


@pytest.mark.parametrize(
    "error",
    [DraftGeneratorUnavailableError("down"), DraftGeneratorRefusalError("refused")],
)
def test_provider_failure_does_not_create_half_revision(db, disease_files, error):
    add_source(db)
    with pytest.raises(type(error)):
        make_service(db, disease_files, FakeGenerator(error=error)).generate(
            generation_request(), created_by=None
        )
    assert db.query(MedicalKnowledgeTopic).count() == 1
    assert db.query(MedicalKnowledgeRevision).count() == 0


def test_generation_creates_topic_draft_revision_and_source_audit(db, disease_files):
    add_source(db)
    user = User(username="reviewer", password_hash="x", role="staff", is_active=True)
    db.add(user)
    db.commit()
    result = make_service(db, disease_files).generate(generation_request(), created_by=user.id)
    topic = db.query(MedicalKnowledgeTopic).one()
    revision = db.query(MedicalKnowledgeRevision).one()
    link = db.query(MedicalRevisionSource).one()

    assert result.id == revision.id
    assert result.status == "DRAFT"
    assert result.parent_display_allowed is False
    assert result.generated_by_llm is True
    assert result.llm_model == "openai-test-model"
    assert result.prompt_version == "medical_knowledge_v4_general_factors"
    assert revision.created_by == user.id
    assert revision.reviewed_by is None and revision.reviewed_at is None
    assert topic.published_revision_id is None
    assert link.source_id == 1 and link.source_role == "PRIMARY"
    assert link.relevance_note == "DIRECT: Đánh giá trực tiếp yếu tố mưa."
    assert link.population_relevance == "PEDIATRIC_DIRECT"
    assert link.population_note == "Abstract mô tả trực tiếp trẻ em."
    assert result.sources[0].population_relevance == "PEDIATRIC_DIRECT"
    assert result.parent_tier2_eligible is True


def test_existing_topic_is_reused_and_revision_number_increments(db, disease_files):
    add_source(db)
    service = make_service(db, disease_files)
    first = service.generate(generation_request(), created_by=None)
    second = service.generate(generation_request(), created_by=None)
    assert db.query(MedicalKnowledgeTopic).count() == 1
    assert (first.revision_number, second.revision_number) == (1, 2)


def test_generation_preserves_existing_published_revision_pointer(db, disease_files):
    add_source(db)
    service = make_service(db, disease_files)
    first = service.generate(generation_request(), created_by=None)
    topic = db.query(MedicalKnowledgeTopic).one()
    topic.published_revision_id = first.id
    db.commit()
    service.generate(generation_request(), created_by=None)
    db.refresh(topic)
    assert topic.published_revision_id == first.id


def test_generation_rolls_back_all_db_writes_on_attachment_failure(db, disease_files, monkeypatch):
    add_source(db)
    service = make_service(db, disease_files)
    monkeypatch.setattr(
        service.repository, "attach_source", lambda _data: (_ for _ in ()).throw(RuntimeError("write failed"))
    )
    with pytest.raises(RuntimeError, match="write failed"):
        service.generate(generation_request(), created_by=None)
    assert db.query(MedicalKnowledgeTopic).count() == 1
    assert db.query(MedicalKnowledgeRevision).count() == 0


def test_revision_number_collision_retries_without_recalling_provider(db, disease_files, monkeypatch):
    add_source(db)
    generator = FakeGenerator()
    service = make_service(db, disease_files, generator)
    original_create = service.repository.create_revision
    attempts = 0

    def collide_once(data):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("insert", {}, RuntimeError("simulated revision race"))
        return original_create(data)

    monkeypatch.setattr(service.repository, "create_revision", collide_once)
    result = service.generate(generation_request(), created_by=None)
    assert result.revision_number == 1
    assert attempts == 2
    assert len(generator.contexts) == 1


def test_history_and_revision_detail_include_sources(db, disease_files):
    add_source(db)
    service = make_service(db, disease_files)
    generated = service.generate(generation_request(), created_by=None)
    history = service.get_history("5", "precipitation")
    detail = service.get_revision(generated.id)
    assert history.topic is not None
    assert history.topic.published_revision_id is None
    assert [item.id for item in history.revisions] == [generated.id]
    assert detail.sources[0].pmid == "10000001"
    assert detail.sources[0].relevance_note.startswith("DIRECT:")


def test_empty_history_is_structured(db, disease_files):
    history = make_service(db, disease_files).get_history("5", "humidity")
    assert history.topic is None and history.revisions == []


def test_draft_edit_changes_only_allowed_content_and_preserves_status(db, disease_files):
    add_source(db)
    service = make_service(db, disease_files)
    generated = service.generate(generation_request(), created_by=None)
    updated = service.update_draft(
        generated.id,
        DraftRevisionPatch(
            evidence_level="SUPPORTED",
            evidence_scope="WHOLE_GROUP",
            short_explanation_vi="Nội dung đã được nhân viên chỉnh sửa.",
            detailed_explanation_vi="Chi tiết sau khi kiểm tra nguồn.",
            limitations_vi="Giới hạn đã được cập nhật.",
        ),
    )
    assert updated.status == "DRAFT"
    assert updated.parent_display_allowed is False
    assert updated.generated_by_llm is True
    assert updated.short_explanation_vi == "Nội dung đã được nhân viên chỉnh sửa."


@pytest.mark.parametrize("forbidden", ["status", "parent_display_allowed", "published_revision_id", "llm_model"])
def test_draft_patch_rejects_publish_or_provenance_fields(forbidden):
    with pytest.raises(ValidationError):
        DraftRevisionPatch(**{forbidden: "APPROVED"})


def test_non_draft_revision_cannot_be_edited(db, disease_files):
    add_source(db)
    service = make_service(db, disease_files)
    generated = service.generate(generation_request(), created_by=None)
    revision = db.get(MedicalKnowledgeRevision, generated.id)
    revision.status = "APPROVED"
    db.commit()
    with pytest.raises(DraftNotEditableError):
        service.update_draft(
            generated.id, DraftRevisionPatch(short_explanation_vi="Không được sửa")
        )


@pytest.mark.parametrize(
    "field",
    [
        "evidence_level",
        "evidence_scope",
        "short_explanation_vi",
        "detailed_explanation_vi",
        "limitations_vi",
    ],
)
def test_draft_patch_rejects_explicit_null_for_non_nullable_fields(field):
    with pytest.raises(ValidationError):
        DraftRevisionPatch(**{field: None})


def test_stale_draft_patch_cannot_mutate_a_concurrently_approved_revision(
    db, disease_files, monkeypatch
):
    add_source(db)
    reviewer = User(
        username="race-reviewer",
        password_hash="x",
        role="staff",
        is_active=True,
    )
    db.add(reviewer)
    db.commit()
    service = make_service(db, disease_files)
    generated = service.generate(generation_request(), created_by=reviewer.id)
    original_short = generated.short_explanation_vi

    original_update = getattr(service.repository, "update_draft_if_draft", None)

    def approve_before_compare_and_swap(revision_id, values):
        db.execute(
            update(MedicalKnowledgeRevision)
            .where(MedicalKnowledgeRevision.id == revision_id)
            .values(
                status="APPROVED",
                reviewed_by=reviewer.id,
                reviewed_at=FIXED_APPROVED_AT,
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return original_update(revision_id, values)

    monkeypatch.setattr(
        service.repository,
        "update_draft_if_draft",
        approve_before_compare_and_swap,
        raising=False,
    )
    with pytest.raises(DraftNotEditableError):
        service.update_draft(
            generated.id,
            DraftRevisionPatch(short_explanation_vi="STALE PATCH MUST NOT WIN"),
        )

    db.expire_all()
    revision = db.get(MedicalKnowledgeRevision, generated.id)
    assert revision.status == "APPROVED"
    assert revision.short_explanation_vi == original_short


FIXED_APPROVED_AT = datetime(2026, 8, 23, 9, 30, 0)


def approval_service(db):
    return MedicalKnowledgeApprovalService(db, clock=lambda: FIXED_APPROVED_AT)


def test_approval_e2e_freezes_edited_draft_and_preserves_audit_and_side_effects(
    db, disease_files
):
    source = add_source(db)
    evidence = MedicalEvidenceContent(
        source_id=source.id,
        content_kind="ABSTRACT",
        content_origin="NCBI_PUBMED",
        external_identifier=None,
        evidence_text=source.abstract_text,
        retrieved_at=FIXED_APPROVED_AT,
        is_truncated=False,
        license_name=None,
        license_url=None,
        provenance_json={"provider": "test fixture"},
        content_sha256="a" * 64,
    )
    db.add(evidence)
    reviewer = User(
        username="medical-reviewer",
        full_name="Bác sĩ kiểm duyệt",
        password_hash="x",
        role="staff",
        is_active=True,
    )
    db.add(reviewer)
    db.commit()
    generator = FakeGenerator()
    drafts = make_service(db, disease_files, generator)
    generated = drafts.generate(generation_request(), created_by=reviewer.id)
    drafts.update_draft(
        generated.id,
        DraftRevisionPatch(short_explanation_vi="Nội dung đã được nhân viên y tế kiểm tra."),
    )
    link_before = db.query(MedicalRevisionSource).one()
    link_snapshot = (
        link_before.source_id,
        link_before.evidence_content_id,
        link_before.source_role,
        link_before.sort_order,
        link_before.relevance_note,
        link_before.population_relevance,
        link_before.population_note,
    )
    source_snapshot = (source.abstract_text, source.raw_metadata_json)
    evidence_snapshot = (
        evidence.content_kind,
        evidence.content_origin,
        evidence.evidence_text,
        evidence.content_sha256,
        evidence.provenance_json,
    )

    approved = approval_service(db).approve(generated.id, approved_by=reviewer.id)
    readback = drafts.get_revision(generated.id)

    assert approved.status == "APPROVED"
    assert approved.approved_by == reviewer.id
    assert approved.approved_by_name == "Bác sĩ kiểm duyệt"
    assert approved.approved_at == FIXED_APPROVED_AT
    assert approved.parent_display_allowed is False
    assert approved.published_revision_id is None
    assert readback.status == "APPROVED"
    assert readback.reviewed_by == reviewer.id
    assert readback.reviewed_by_name == "Bác sĩ kiểm duyệt"
    assert readback.reviewed_at == FIXED_APPROVED_AT
    assert readback.parent_display_allowed is False
    assert len(generator.contexts) == 1
    link_after = db.query(MedicalRevisionSource).one()
    assert (
        link_after.source_id,
        link_after.evidence_content_id,
        link_after.source_role,
        link_after.sort_order,
        link_after.relevance_note,
        link_after.population_relevance,
        link_after.population_note,
    ) == link_snapshot
    db.refresh(source)
    assert (source.abstract_text, source.raw_metadata_json) == source_snapshot
    db.refresh(evidence)
    assert (
        evidence.content_kind,
        evidence.content_origin,
        evidence.evidence_text,
        evidence.content_sha256,
        evidence.provenance_json,
    ) == evidence_snapshot
    with pytest.raises(DraftNotEditableError):
        drafts.update_draft(
            generated.id,
            DraftRevisionPatch(short_explanation_vi="Không được phép sửa bản đã duyệt"),
        )


def test_insufficient_evidence_draft_can_be_approved(db, disease_files):
    add_source(db)
    reviewer = User(username="reviewer", password_hash="x", role="staff", is_active=True)
    db.add(reviewer)
    db.commit()
    generator = FakeGenerator(proposal(evidence_level="INSUFFICIENT"))
    generated = make_service(db, disease_files, generator).generate(
        generation_request(), created_by=reviewer.id
    )
    result = approval_service(db).approve(generated.id, approved_by=reviewer.id)
    assert result.status == "APPROVED"


def test_double_approval_is_conflict_and_keeps_single_audit_values(db, disease_files):
    add_source(db)
    reviewer = User(username="reviewer", password_hash="x", role="admin", is_active=True)
    db.add(reviewer)
    db.commit()
    generated = make_service(db, disease_files).generate(generation_request(), created_by=None)
    service = approval_service(db)
    service.approve(generated.id, approved_by=reviewer.id)

    with pytest.raises(ApprovalConflictError):
        service.approve(generated.id, approved_by=reviewer.id)

    revision = db.get(MedicalKnowledgeRevision, generated.id)
    assert revision.status == "APPROVED"
    assert revision.reviewed_by == reviewer.id
    assert revision.reviewed_at == FIXED_APPROVED_AT


def test_missing_and_non_draft_revision_cannot_be_approved(db, disease_files):
    reviewer = User(username="reviewer", password_hash="x", role="staff", is_active=True)
    db.add(reviewer)
    db.commit()
    with pytest.raises(ApprovalNotFoundError):
        approval_service(db).approve(9999, approved_by=reviewer.id)

    add_source(db)
    generated = make_service(db, disease_files).generate(generation_request(), created_by=None)
    revision = db.get(MedicalKnowledgeRevision, generated.id)
    revision.status = "REJECTED"
    db.commit()
    with pytest.raises(ApprovalConflictError):
        approval_service(db).approve(generated.id, approved_by=reviewer.id)


@pytest.mark.parametrize("invalid_case", ["blank_content", "bad_assessment", "whole_group_without_direct"])
def test_invalid_revision_content_cannot_be_approved(db, disease_files, invalid_case):
    add_source(db)
    reviewer = User(username="reviewer", password_hash="x", role="staff", is_active=True)
    db.add(reviewer)
    db.commit()
    generated = make_service(db, disease_files).generate(generation_request(), created_by=None)
    revision = db.get(MedicalKnowledgeRevision, generated.id)
    link = db.query(MedicalRevisionSource).one()
    if invalid_case == "blank_content":
        revision.short_explanation_vi = ""
    elif invalid_case == "bad_assessment":
        link.relevance_note = "missing relevance prefix"
    else:
        revision.evidence_scope = "WHOLE_GROUP"
        link.source_role = "SUPPORTING"
        link.relevance_note = "INDIRECT: Chỉ hỗ trợ gián tiếp."
    db.commit()

    with pytest.raises(ApprovalValidationError):
        approval_service(db).approve(generated.id, approved_by=reviewer.id)
    db.refresh(revision)
    assert revision.status == "DRAFT"


def test_approval_rejects_evidence_snapshot_owned_by_another_source(db, disease_files):
    add_source(db, source_id=1)
    second_source = add_source(db, source_id=2)
    reviewer = User(username="reviewer", password_hash="x", role="staff", is_active=True)
    db.add(reviewer)
    db.flush()
    mismatched_content = MedicalEvidenceContent(
        source_id=second_source.id,
        content_kind="ABSTRACT",
        content_origin="NCBI_PUBMED",
        evidence_text="Evidence belonging only to source 2.",
        retrieved_at=FIXED_APPROVED_AT,
        is_truncated=False,
        content_sha256="b" * 64,
    )
    db.add(mismatched_content)
    db.commit()

    generated = make_service(db, disease_files).generate(
        generation_request(source_ids=[1]), created_by=reviewer.id
    )
    link = db.query(MedicalRevisionSource).filter_by(revision_id=generated.id).one()
    link.evidence_content_id = mismatched_content.id
    db.commit()

    with pytest.raises(ApprovalValidationError, match="evidence content"):
        approval_service(db).approve(generated.id, approved_by=reviewer.id)
    db.refresh(db.get(MedicalKnowledgeRevision, generated.id))
    assert db.get(MedicalKnowledgeRevision, generated.id).status == "DRAFT"


def test_new_draft_can_be_generated_after_approved_revision(db, disease_files):
    add_source(db)
    reviewer = User(username="reviewer", password_hash="x", role="staff", is_active=True)
    db.add(reviewer)
    db.commit()
    drafts = make_service(db, disease_files)
    first = drafts.generate(generation_request(), created_by=reviewer.id)
    approval_service(db).approve(first.id, approved_by=reviewer.id)
    second = drafts.generate(generation_request(), created_by=reviewer.id)

    assert drafts.get_revision(first.id).status == "APPROVED"
    assert second.status == "DRAFT"
    assert second.revision_number == first.revision_number + 1


def test_approval_preserves_existing_published_pointer(db, disease_files):
    add_source(db)
    reviewer = User(username="reviewer", password_hash="x", role="admin", is_active=True)
    db.add(reviewer)
    db.commit()
    drafts = make_service(db, disease_files)
    published = drafts.generate(generation_request(), created_by=None)
    candidate = drafts.generate(generation_request(), created_by=None)
    topic = db.query(MedicalKnowledgeTopic).one()
    topic.published_revision_id = published.id
    db.commit()

    result = approval_service(db).approve(candidate.id, approved_by=reviewer.id)
    db.refresh(topic)
    assert result.published_revision_id == published.id
    assert topic.published_revision_id == published.id


class EndpointDraftService:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def _result(self):
        return {
            "id": 9,
            "revision_number": 1,
            "status": "DRAFT",
            "evidence_level": "INSUFFICIENT",
            "evidence_scope": "PARTIAL_GROUP",
            "generated_by_llm": True,
            "created_at": "2026-08-18T00:00:00",
            "updated_at": "2026-08-18T00:00:00",
            "topic_id": 3,
            "disease_group_id": "5",
            "disease_group_name": "Disease group",
            "weather_factor": "precipitation",
            "short_explanation_vi": "Ngắn",
            "detailed_explanation_vi": "Chi tiết",
            "limitations_vi": "Giới hạn",
            "parent_display_allowed": False,
            "llm_model": "model",
            "prompt_version": "medical_knowledge_v1",
            "created_by": 1,
            "reviewed_by": None,
            "reviewed_at": None,
            "sources": [],
        }

    def generate(self, payload, *, created_by):
        self.calls.append(("generate", payload, created_by))
        if self.error:
            raise self.error
        return self._result()

    def get_history(self, disease_group_id, weather_factor):
        self.calls.append(("history", disease_group_id, weather_factor))
        return {"topic": None, "revisions": []}

    def get_revision(self, revision_id):
        self.calls.append(("get", revision_id))
        return self._result()

    def update_draft(self, revision_id, payload):
        self.calls.append(("patch", revision_id, payload))
        return self._result()


class EndpointApprovalService:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def approve(self, revision_id, *, approved_by):
        self.calls.append((revision_id, approved_by))
        if self.error:
            raise self.error
        return {
            "revision_id": revision_id,
            "status": "APPROVED",
            "approved_by": approved_by,
            "approved_by_name": "Authenticated reviewer",
            "approved_at": "2026-08-23T09:30:00",
            "parent_display_allowed": False,
            "published_revision_id": None,
        }


@pytest.fixture
def api_client(db):
    db.add_all(
        [
            User(username="admin", password_hash="x", role="admin", is_active=True),
            User(username="staff", password_hash="x", role="staff", is_active=True),
            User(username="viewer", password_hash="x", role="viewer", is_active=True),
        ]
    )
    db.commit()
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    service = EndpointDraftService()
    approval = EndpointApprovalService()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_draft_service] = lambda: service
    app.dependency_overrides[get_approval_service] = lambda: approval
    with TestClient(app) as client:
        yield client, app, service, approval


def auth_header(username):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def api_payload():
    return {"disease_group_id": "5", "weather_factor": "precipitation", "source_ids": [1]}


def test_anonymous_and_unauthorized_generation_are_blocked(api_client):
    client, _app, _service, _approval = api_client
    assert client.post("/api/medical-knowledge/drafts/generate", json=api_payload()).status_code == 401
    assert client.post(
        "/api/medical-knowledge/drafts/generate",
        json=api_payload(),
        headers=auth_header("viewer"),
    ).status_code == 403


@pytest.mark.parametrize("username", ["admin", "staff"])
def test_admin_and_staff_can_generate(api_client, username):
    client, _app, service, _approval = api_client
    response = client.post(
        "/api/medical-knowledge/drafts/generate",
        json=api_payload(),
        headers=auth_header(username),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "DRAFT"
    assert service.calls[-1][2] is not None


@pytest.mark.parametrize(
    "method,path,json_body",
    [
        ("get", "/api/medical-knowledge/topics?disease_group_id=5&weather_factor=humidity", None),
        ("get", "/api/medical-knowledge/revisions/9", None),
        ("patch", "/api/medical-knowledge/revisions/9", {"short_explanation_vi": "Sửa"}),
    ],
)
def test_draft_read_and_edit_endpoints_are_protected(api_client, method, path, json_body):
    client, _app, _service, _approval = api_client
    response = client.request(method, path, json=json_body)
    assert response.status_code == 401
    response = client.request(method, path, json=json_body, headers=auth_header("viewer"))
    assert response.status_code == 403
    response = client.request(method, path, json=json_body, headers=auth_header("staff"))
    assert response.status_code == 200


@pytest.mark.parametrize(
    "error,status",
    [
        (DraftGeneratorConfigurationError("contains sk-secret"), 503),
        (DraftGeneratorUnavailableError("contains sk-secret"), 502),
        (DraftGeneratorOutputError("contains sk-secret"), 502),
    ],
)
def test_provider_errors_are_mapped_without_secret_or_trace(api_client, error, status):
    client, app, _service, _approval = api_client
    app.dependency_overrides[get_draft_service] = lambda: EndpointDraftService(error)
    response = client.post(
        "/api/medical-knowledge/drafts/generate",
        json=api_payload(),
        headers=auth_header("admin"),
    )
    assert response.status_code == status
    assert "sk-secret" not in response.text
    assert "traceback" not in response.text.lower()


def test_draft_domain_validation_returns_a_structured_actionable_code(api_client):
    client, app, _service, _approval = api_client
    app.dependency_overrides[get_draft_service] = lambda: EndpointDraftService(
        DraftWorkflowValidationError(
            "Selected source is outside the exact topic",
            code="DRAFT_SOURCE_NOT_IN_TOPIC",
        )
    )
    response = client.post(
        "/api/medical-knowledge/drafts/generate",
        json=api_payload(),
        headers=auth_header("admin"),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "DRAFT_SOURCE_NOT_IN_TOPIC",
        "message": "Selected source is outside the exact topic",
    }


def test_too_many_sources_api_error_is_specific_and_actionable(api_client):
    client, app, _service, _approval = api_client
    app.dependency_overrides[get_draft_service] = lambda: EndpointDraftService(
        DraftWorkflowValidationError(
            "Một bản nháp hiện hỗ trợ tối đa 10 nguồn.",
            code="DRAFT_TOO_MANY_SOURCES",
        )
    )
    response = client.post(
        "/api/medical-knowledge/drafts/generate",
        json=api_payload(),
        headers=auth_header("admin"),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "DRAFT_TOO_MANY_SOURCES",
        "message": "Một bản nháp hiện hỗ trợ tối đa 10 nguồn.",
    }


def test_approval_endpoint_blocks_anonymous_and_non_medical_role(api_client):
    client, _app, _draft, approval = api_client
    path = "/api/medical-knowledge/revisions/9/approve"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=auth_header("viewer")).status_code == 403
    assert approval.calls == []


@pytest.mark.parametrize("username", ["staff", "admin"])
def test_staff_and_admin_can_approve_with_identity_from_auth_context(api_client, username):
    client, _app, _draft, approval = api_client
    response = client.post(
        "/api/medical-knowledge/revisions/9/approve",
        headers=auth_header(username),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert response.json()["parent_display_allowed"] is False
    assert approval.calls[-1][0] == 9
    assert approval.calls[-1][1] is not None


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ApprovalNotFoundError("missing"), 404),
        (ApprovalConflictError("already approved"), 409),
        (ApprovalValidationError("invalid content"), 422),
    ],
)
def test_approval_errors_are_mapped_safely(api_client, error, status):
    client, app, _draft, _approval = api_client
    app.dependency_overrides[get_approval_service] = lambda: EndpointApprovalService(error)
    response = client.post(
        "/api/medical-knowledge/revisions/9/approve",
        headers=auth_header("staff"),
    )
    assert response.status_code == status
    assert "traceback" not in response.text.lower()


PUBLISHED_AT_1 = datetime(2026, 8, 23, 10, 0, 0)
PUBLISHED_AT_2 = datetime(2026, 8, 23, 11, 0, 0)


def test_publish_e2e_replaces_atomically_and_preserves_content_approval_and_history(
    db, disease_files
):
    source = add_source(db)
    reviewer = User(
        username="publish-reviewer",
        full_name="Bác sĩ duyệt",
        password_hash="x",
        role="staff",
        is_active=True,
    )
    publisher = User(
        username="publisher",
        full_name="Điều phối xuất bản",
        password_hash="x",
        role="admin",
        is_active=True,
    )
    db.add_all([reviewer, publisher])
    db.commit()
    generator = FakeGenerator()
    drafts = make_service(db, disease_files, generator)

    first = drafts.generate(generation_request(), created_by=reviewer.id)
    approval_service(db).approve(first.id, approved_by=reviewer.id)
    first_revision = db.get(MedicalKnowledgeRevision, first.id)
    first_snapshot = (
        first_revision.status,
        first_revision.evidence_level,
        first_revision.evidence_scope,
        first_revision.short_explanation_vi,
        first_revision.detailed_explanation_vi,
        first_revision.limitations_vi,
        first_revision.llm_model,
        first_revision.prompt_version,
        first_revision.reviewed_by,
        first_revision.reviewed_at,
        first_revision.updated_at,
    )
    source_snapshot = (source.abstract_text, dict(source.raw_metadata_json))
    link_snapshot = [
        (
            link.revision_id,
            link.source_id,
            link.evidence_content_id,
            link.source_role,
            link.sort_order,
            link.relevance_note,
            link.population_relevance,
            link.population_note,
        )
        for link in db.query(MedicalRevisionSource).filter_by(revision_id=first.id).all()
    ]
    evidence_snapshot = [
        (row.id, row.evidence_text, row.content_sha256, row.provenance_json)
        for row in db.query(MedicalEvidenceContent).all()
    ]

    times = iter([PUBLISHED_AT_1, PUBLISHED_AT_2])
    publications = MedicalKnowledgePublicationService(db, clock=lambda: next(times))
    llm_calls_before_publish = len(generator.contexts)
    first_result = publications.publish(first.id, published_by=publisher.id)
    assert len(generator.contexts) == llm_calls_before_publish
    assert first_result.status == "APPROVED"
    assert first_result.is_published is True
    assert first_result.parent_display_allowed is True
    assert first_result.published_by == publisher.id
    assert first_result.published_by_name == "Điều phối xuất bản"
    assert first_result.published_at == PUBLISHED_AT_1
    assert first_result.previous_published_revision_id is None

    second = drafts.generate(generation_request(), created_by=reviewer.id)
    topic = db.query(MedicalKnowledgeTopic).one()
    db.refresh(topic)
    assert topic.published_revision_id == first.id
    assert db.get(MedicalKnowledgeRevision, first.id).parent_display_allowed is True
    assert second.parent_display_allowed is False
    drafts.update_draft(
        second.id,
        DraftRevisionPatch(short_explanation_vi="Bản thay thế đã được chỉnh sửa."),
    )
    assert topic.published_revision_id == first.id
    approval_service(db).approve(second.id, approved_by=reviewer.id)
    db.refresh(topic)
    assert topic.published_revision_id == first.id
    assert db.get(MedicalKnowledgeRevision, second.id).parent_display_allowed is False

    second_result = publications.publish(second.id, published_by=publisher.id)
    db.refresh(topic)
    db.refresh(first_revision)
    second_revision = db.get(MedicalKnowledgeRevision, second.id)
    assert second_result.previous_published_revision_id == first.id
    assert second_result.published_at == PUBLISHED_AT_2
    assert topic.published_revision_id == second.id
    assert first_revision.parent_display_allowed is False
    assert second_revision.parent_display_allowed is True
    assert first_revision.status == second_revision.status == "APPROVED"
    assert (
        first_revision.status,
        first_revision.evidence_level,
        first_revision.evidence_scope,
        first_revision.short_explanation_vi,
        first_revision.detailed_explanation_vi,
        first_revision.limitations_vi,
        first_revision.llm_model,
        first_revision.prompt_version,
        first_revision.reviewed_by,
        first_revision.reviewed_at,
        first_revision.updated_at,
    ) == first_snapshot
    db.refresh(source)
    assert (source.abstract_text, source.raw_metadata_json) == source_snapshot
    assert [
        (
            link.revision_id,
            link.source_id,
            link.evidence_content_id,
            link.source_role,
            link.sort_order,
            link.relevance_note,
            link.population_relevance,
            link.population_note,
        )
        for link in db.query(MedicalRevisionSource).filter_by(revision_id=first.id).all()
    ] == link_snapshot
    assert [
        (row.id, row.evidence_text, row.content_sha256, row.provenance_json)
        for row in db.query(MedicalEvidenceContent).all()
        if row.id in {item[0] for item in evidence_snapshot}
    ] == evidence_snapshot
    assert db.query(MedicalKnowledgePublication).count() == 2
    assert [event.revision_id for event in db.query(MedicalKnowledgePublication).order_by(
        MedicalKnowledgePublication.id
    )] == [first.id, second.id]
    assert len(generator.contexts) == 2

    readback = drafts.get_revision(second.id)
    assert readback.is_published is True
    assert readback.published_by == publisher.id
    assert readback.published_by_name == "Điều phối xuất bản"
    assert readback.published_at == PUBLISHED_AT_2
    assert drafts.get_revision(first.id).is_published is False
    history = drafts.get_history("5", "precipitation")
    assert [item.id for item in history.revisions if item.is_published] == [second.id]


def test_publish_is_idempotent_without_duplicate_audit_or_timestamp(db, disease_files):
    add_source(db)
    user = User(username="publisher", password_hash="x", role="staff", is_active=True)
    db.add(user)
    db.commit()
    drafts = make_service(db, disease_files)
    revision = drafts.generate(generation_request(), created_by=user.id)
    approval_service(db).approve(revision.id, approved_by=user.id)
    service = MedicalKnowledgePublicationService(db, clock=lambda: PUBLISHED_AT_1)

    first = service.publish(revision.id, published_by=user.id)
    second = service.publish(revision.id, published_by=user.id)

    assert second.published_at == first.published_at == PUBLISHED_AT_1
    assert second.published_by == first.published_by == user.id
    assert db.query(MedicalKnowledgePublication).count() == 1
    assert MedicalKnowledgeRepository(db).count_parent_visible_revisions(revision.topic_id) == 1


def test_only_approved_revision_and_eligible_publisher_can_publish(db, disease_files):
    add_source(db)
    staff = User(username="staff-publisher", password_hash="x", role="staff", is_active=True)
    viewer = User(username="viewer-publisher", password_hash="x", role="viewer", is_active=True)
    db.add_all([staff, viewer])
    db.commit()
    draft = make_service(db, disease_files).generate(generation_request(), created_by=staff.id)
    service = MedicalKnowledgePublicationService(db, clock=lambda: PUBLISHED_AT_1)

    with pytest.raises(PublicationConflictError):
        service.publish(draft.id, published_by=staff.id)
    with pytest.raises(PublicationNotFoundError):
        service.publish(9999, published_by=staff.id)
    with pytest.raises(PublicationValidationError):
        service.publish(draft.id, published_by=viewer.id)
    topic = db.query(MedicalKnowledgeTopic).one()
    assert topic.published_revision_id is None
    assert db.query(MedicalKnowledgePublication).count() == 0


def test_stale_publish_compare_and_swap_cannot_corrupt_pointer_or_flags(db, disease_files):
    add_source(db)
    user = User(username="race-publisher", password_hash="x", role="admin", is_active=True)
    db.add(user)
    db.commit()
    drafts = make_service(db, disease_files)
    first = drafts.generate(generation_request(), created_by=user.id)
    second = drafts.generate(generation_request(), created_by=user.id)
    approval_service(db).approve(first.id, approved_by=user.id)
    approval_service(db).approve(second.id, approved_by=user.id)
    MedicalKnowledgePublicationService(db, clock=lambda: PUBLISHED_AT_1).publish(
        first.id, published_by=user.id
    )

    repository = MedicalKnowledgeRepository(db)
    changed = repository.replace_current_publication(
        topic_id=first.topic_id,
        revision_id=second.id,
        published_at=PUBLISHED_AT_2,
        expected_previous_revision_id=None,
    )
    assert changed is False
    db.rollback()
    topic = db.get(MedicalKnowledgeTopic, first.topic_id)
    first_row = db.get(MedicalKnowledgeRevision, first.id)
    second_row = db.get(MedicalKnowledgeRevision, second.id)
    assert topic.published_revision_id == first.id
    assert first_row.parent_display_allowed is True
    assert second_row.parent_display_allowed is False
    assert repository.count_parent_visible_revisions(topic.id) == 1


class EndpointPublicationService:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def publish(self, revision_id, *, published_by):
        self.calls.append((revision_id, published_by))
        if self.error:
            raise self.error
        return {
            "revision_id": revision_id,
            "topic_id": 3,
            "status": "APPROVED",
            "is_published": True,
            "parent_display_allowed": True,
            "published_by": published_by,
            "published_by_name": "Authenticated publisher",
            "published_at": "2026-08-23T10:00:00",
            "previous_published_revision_id": None,
        }


@pytest.fixture
def publish_api_client(db):
    db.add_all(
        [
            User(username="publish-admin", password_hash="x", role="admin", is_active=True),
            User(username="publish-staff", password_hash="x", role="staff", is_active=True),
            User(username="publish-viewer", password_hash="x", role="viewer", is_active=True),
        ]
    )
    db.commit()
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    publication = EndpointPublicationService()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_publication_service] = lambda: publication
    with TestClient(app) as client:
        yield client, app, publication


def test_publish_endpoint_blocks_anonymous_and_viewer(publish_api_client):
    client, _app, publication = publish_api_client
    path = "/api/medical-knowledge/revisions/9/publish"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=auth_header("publish-viewer")).status_code == 403
    assert publication.calls == []


@pytest.mark.parametrize("username", ["publish-staff", "publish-admin"])
def test_staff_and_admin_publish_with_identity_from_auth_context(
    publish_api_client, username
):
    client, _app, publication = publish_api_client
    response = client.post(
        "/api/medical-knowledge/revisions/9/publish",
        headers=auth_header(username),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert response.json()["is_published"] is True
    assert response.json()["parent_display_allowed"] is True
    assert publication.calls[-1][0] == 9
    assert publication.calls[-1][1] is not None


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PublicationNotFoundError("missing"), 404),
        (PublicationConflictError("only approved"), 409),
        (PublicationValidationError("invalid publisher"), 422),
    ],
)
def test_publish_errors_are_mapped_safely(publish_api_client, error, status):
    client, app, _publication = publish_api_client
    app.dependency_overrides[get_publication_service] = lambda: EndpointPublicationService(error)
    response = client.post(
        "/api/medical-knowledge/revisions/9/publish",
        headers=auth_header("publish-staff"),
    )
    assert response.status_code == status
    assert "traceback" not in response.text.lower()


def test_publication_migration_is_idempotent_and_preserves_existing_tables():
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    MedicalKnowledgeTopic.__table__.create(engine)
    MedicalKnowledgeRevision.__table__.create(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (id, username, password_hash, role, is_active, created_at) "
            "VALUES (1, 'migration-user', 'x', 'staff', 1, '2026-08-23 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO medical_knowledge_topics "
            "(id, disease_group_id, weather_factor, factor_type, factor_key, factor_value, "
            "published_revision_id, created_by, created_at, updated_at) "
            "VALUES (1, '5', 'precipitation', 'WEATHER', 'precipitation', NULL, "
            "NULL, 1, '2026-08-23 00:00:00', '2026-08-23 00:00:00')"
        )

    upgrade_publication(engine)
    upgrade_publication(engine)
    assert "medical_knowledge_publications" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT disease_group_id FROM medical_knowledge_topics WHERE id=1"
        ).scalar_one() == "5"
    downgrade_publication(engine)
    assert "medical_knowledge_publications" not in inspect(engine).get_table_names()
    assert "medical_knowledge_topics" in inspect(engine).get_table_names()
    engine.dispose()


def test_supported_generation_rejects_adult_direct_plus_pediatric_indirect(
    db, disease_files
):
    add_source(db, source_id=1)
    add_source(db, source_id=2)
    inconsistent = proposal(
        evidence_level="SUPPORTED",
        source_assessments=[
            {
                "source_id": 1,
                "relevance": "DIRECT",
                "note_vi": "Direct relationship in adults.",
                "population_relevance": "ADULT_ONLY",
                "population_note": "Abstract explicitly limits participants to adults.",
            },
            {
                "source_id": 2,
                "relevance": "INDIRECT",
                "note_vi": "Only indirect disease-group support in children.",
                "population_relevance": "PEDIATRIC_DIRECT",
                "population_note": "Abstract explicitly describes children.",
            },
        ],
    )
    service = make_service(db, disease_files, FakeGenerator(inconsistent))

    with pytest.raises(DraftWorkflowValidationError) as raised:
        service.generate(generation_request(source_ids=[1, 2]), created_by=None)

    assert raised.value.code == "DRAFT_SUPPORTED_REQUIRES_PEDIATRIC_SOURCE"
    assert db.query(MedicalKnowledgeRevision).count() == 0


def test_approval_revalidates_manually_changed_supported_level_for_pediatric_support(
    db, disease_files
):
    add_source(db)
    reviewer = User(
        username="pediatric-reviewer",
        password_hash="x",
        role="staff",
        is_active=True,
    )
    db.add(reviewer)
    db.commit()
    adult = proposal(
        source_assessments=[{
            "source_id": 1,
            "relevance": "DIRECT",
            "note_vi": "Direct relationship in adults.",
            "population_relevance": "ADULT_ONLY",
            "population_note": "Abstract explicitly limits participants to adults.",
        }],
    )
    generated = make_service(db, disease_files, FakeGenerator(adult)).generate(
        generation_request(), created_by=reviewer.id
    )
    revision = db.get(MedicalKnowledgeRevision, generated.id)
    revision.evidence_level = "SUPPORTED"
    db.commit()

    with pytest.raises(ApprovalValidationError) as raised:
        approval_service(db).approve(generated.id, approved_by=reviewer.id)

    assert raised.value.code == "APPROVAL_PEDIATRIC_SUPPORT_REQUIRED"
    assert db.get(MedicalKnowledgeRevision, generated.id).status == "DRAFT"


def test_population_safety_e2e_adult_elderly_hidden_then_pediatric_visible(
    db, disease_files
):
    add_source(db, source_id=1, abstract="Adults with direct rainfall outcome.")
    add_source(db, source_id=2, abstract="Elderly adults with direct rainfall outcome.")
    reviewer = User(
        username="population-reviewer", password_hash="x", role="staff", is_active=True
    )
    publisher = User(
        username="population-publisher", password_hash="x", role="admin", is_active=True
    )
    db.add_all([reviewer, publisher])
    db.commit()

    adult_elderly = proposal(source_assessments=[
        {
            "source_id": 1,
            "relevance": "DIRECT",
            "note_vi": "Direct adult disease-weather relationship.",
            "population_relevance": "ADULT_ONLY",
            "population_note": "Abstract explicitly restricts the study to adults.",
        },
        {
            "source_id": 2,
            "relevance": "DIRECT",
            "note_vi": "Direct elderly disease-weather relationship.",
            "population_relevance": "ELDERLY_ONLY",
            "population_note": "Abstract explicitly restricts the study to elderly adults.",
        },
    ])
    first_generator = FakeGenerator(adult_elderly)
    first_service = make_service(db, disease_files, first_generator)
    first = first_service.generate(
        generation_request(source_ids=[1, 2]), created_by=reviewer.id
    )
    assert [source.population_relevance for source in first.sources] == [
        "ADULT_ONLY", "ELDERLY_ONLY"
    ]
    assert first.parent_tier2_eligible is False
    approval_service(db).approve(first.id, approved_by=reviewer.id)
    MedicalKnowledgePublicationService(db).publish(first.id, published_by=publisher.id)
    request = PublishedMedicalKnowledgeBatchRequest(items=[{
        "disease_group_id": "5", "weather_factor": "precipitation"
    }])
    assert PublishedMedicalKnowledgeReadService(db).read_batch(request).items == []

    add_source(db, source_id=3, abstract="Children with direct rainfall outcome.")
    pediatric = proposal(source_assessments=[{
        "source_id": 3,
        "relevance": "DIRECT",
        "note_vi": "Direct pediatric disease-weather relationship.",
        "population_relevance": "PEDIATRIC_DIRECT",
        "population_note": "Abstract explicitly studies children.",
    }])
    second_generator = FakeGenerator(pediatric)
    second_service = make_service(db, disease_files, second_generator)
    second = second_service.generate(
        generation_request(source_ids=[3]), created_by=reviewer.id
    )
    assert second.parent_tier2_eligible is True
    approval_service(db).approve(second.id, approved_by=reviewer.id)
    MedicalKnowledgePublicationService(db).publish(second.id, published_by=publisher.id)

    visible = PublishedMedicalKnowledgeReadService(db).read_batch(request)
    assert [item.revision_id for item in visible.items] == [second.id]
    assert db.get(MedicalKnowledgeTopic, second.topic_id).published_revision_id == second.id
    assert len(first_generator.contexts) == len(second_generator.contexts) == 1
