from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.medical_knowledge_draft_schemas import (
    DraftGenerationContext,
    DraftGenerationRequest,
    DraftRevisionPatch,
    MedicalKnowledgeDraftProposal,
)
from app.medical_knowledge_models import (
    MedicalEvidenceSource,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalRevisionSource,
)
from app.models import User
from app.routers.medical_knowledge_drafts import get_draft_service, router
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


def proposal(**overrides) -> MedicalKnowledgeDraftProposal:
    values = {
        "evidence_level": "LIMITED_OR_INDIRECT",
        "evidence_scope": "PARTIAL_GROUP",
        "short_explanation_vi": "Các nghiên cứu ghi nhận một mối liên hệ ở mức quần thể.",
        "detailed_explanation_vi": "Tóm tắt cho thấy mối liên hệ quan sát, chưa chứng minh quan hệ nhân quả.",
        "limitations_vi": "Bằng chứng chỉ áp dụng cho một phần nhóm và không dự đoán nguy cơ cá nhân.",
        "source_assessments": [
            {"source_id": 1, "relevance": "DIRECT", "note_vi": "Đánh giá trực tiếp yếu tố mưa."}
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
                "abstract_text": "Selected abstract only.",
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


def test_invalid_weather_and_missing_or_duplicate_sources_are_rejected_by_schema():
    with pytest.raises(ValidationError):
        generation_request(weather_factor="pressure")
    with pytest.raises(ValidationError):
        DraftGenerationRequest(
            disease_group_id="5", weather_factor="humidity", source_ids=[]
        )
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
    with pytest.raises(DraftWorkflowValidationError, match="usable abstract"):
        make_service(db, disease_files).generate(generation_request(), created_by=None)


def test_total_source_input_is_bounded_without_silent_truncation(db, disease_files):
    add_source(db, abstract="evidence " * 100)
    generator = FakeGenerator()
    with pytest.raises(DraftWorkflowValidationError, match="safe input limit"):
        make_service(db, disease_files, generator, max_input_chars=100).generate(
            generation_request(), created_by=None
        )
    assert generator.contexts == []


def test_unknown_source_id_from_provider_is_rejected_without_revision(db, disease_files):
    add_source(db)
    generator = FakeGenerator(
        proposal(source_assessments=[{"source_id": 999, "relevance": "DIRECT", "note_vi": "Sai"}])
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
    assert db.query(MedicalKnowledgeTopic).count() == 0
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
    assert result.prompt_version == "medical_knowledge_v1"
    assert revision.created_by == user.id
    assert revision.reviewed_by is None and revision.reviewed_at is None
    assert topic.published_revision_id is None
    assert link.source_id == 1 and link.source_role == "PRIMARY"
    assert link.relevance_note == "DIRECT: Đánh giá trực tiếp yếu tố mưa."


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
    assert db.query(MedicalKnowledgeTopic).count() == 0
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
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_draft_service] = lambda: service
    with TestClient(app) as client:
        yield client, app, service


def auth_header(username):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def api_payload():
    return {"disease_group_id": "5", "weather_factor": "precipitation", "source_ids": [1]}


def test_anonymous_and_unauthorized_generation_are_blocked(api_client):
    client, _app, _service = api_client
    assert client.post("/api/medical-knowledge/drafts/generate", json=api_payload()).status_code == 401
    assert client.post(
        "/api/medical-knowledge/drafts/generate",
        json=api_payload(),
        headers=auth_header("viewer"),
    ).status_code == 403


@pytest.mark.parametrize("username", ["admin", "staff"])
def test_admin_and_staff_can_generate(api_client, username):
    client, _app, service = api_client
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
    client, _app, _service = api_client
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
    client, app, _service = api_client
    app.dependency_overrides[get_draft_service] = lambda: EndpointDraftService(error)
    response = client.post(
        "/api/medical-knowledge/drafts/generate",
        json=api_payload(),
        headers=auth_header("admin"),
    )
    assert response.status_code == status
    assert "sk-secret" not in response.text
    assert "traceback" not in response.text.lower()
