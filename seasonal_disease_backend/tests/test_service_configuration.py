from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.config as config_module
from app.config import BACKEND_ENV_FILE, BACKEND_ROOT, load_backend_environment
from app.database import Base, get_db
from app.medical_knowledge_models import (
    MedicalEvidenceSource,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalRevisionSource,
)
from app.models import User
from app.routers import medical_knowledge_service_status as status_module
from app.routers.medical_knowledge_service_status import (
    get_status_llm_generator,
    get_status_pubmed_client,
    router,
)
from app.security import create_access_token
from app.services.medical_knowledge_draft_generator import (
    DraftGeneratorOutputError,
    DraftGeneratorTimeoutError,
    DraftGeneratorUnavailableError,
    DraftGeneratorRateLimitError,
    GroqApiKeyMissingError,
    GroqAuthenticationError,
    GroqModelUnavailableError,
    OllamaModelNotInstalledError,
    OllamaModelNotSelectedError,
    OpenAIMedicalKnowledgeDraftGenerator,
)
from app.services.pubmed_client import PubMedUnavailableError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class FakePubMedClient:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search_ids(self, query: str, max_results: int):
        self.calls.append((query, max_results))
        if self.error:
            raise self.error
        return 1, ["1"]


class FakeLlmGenerator:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    def test_connection(self):
        self.calls += 1
        if self.error:
            raise self.error
        return True


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

    pubmed = FakePubMedClient()
    llm = FakeLlmGenerator()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_status_pubmed_client] = lambda: pubmed
    app.dependency_overrides[get_status_llm_generator] = lambda: llm
    with TestClient(app) as client:
        yield client, app, db, pubmed, llm


def auth_header(username: str):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def test_canonical_env_path_is_backend_local():
    assert BACKEND_ENV_FILE == BACKEND_ROOT / ".env"


def test_real_environment_has_priority_over_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_MODEL=model-from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_MODEL", "model-from-os")

    load_backend_environment(env_file)

    assert os.getenv("OPENAI_MODEL") == "model-from-os"


def test_missing_env_file_is_safe(tmp_path):
    assert load_backend_environment(tmp_path / "missing.env") is False


@pytest.mark.parametrize("secret_key", ["", "too-short"])
def test_startup_security_configuration_rejects_missing_or_weak_jwt_key(
    monkeypatch, secret_key
):
    monkeypatch.setattr(config_module, "SECRET_KEY", secret_key)

    with pytest.raises(RuntimeError, match="SECRET_KEY must be configured"):
        config_module.validate_security_configuration()


def test_startup_security_configuration_accepts_strong_jwt_key(monkeypatch):
    monkeypatch.setattr(config_module, "SECRET_KEY", "x" * 32)

    config_module.validate_security_configuration()


def test_git_ignores_local_env_but_not_example():
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "seasonal_disease_backend/.env"],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    example = subprocess.run(
        ["git", "check-ignore", "-q", "seasonal_disease_backend/.env.example"],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    assert ignored.returncode == 0
    assert example.returncode == 1


def test_service_status_anonymous_and_unauthorized_roles_are_blocked(api_client):
    client, _app, _db, _pubmed, _llm = api_client
    assert client.get("/api/medical-knowledge/service-status").status_code == 401
    assert client.get(
        "/api/medical-knowledge/service-status", headers=auth_header("viewer")
    ).status_code == 403


@pytest.mark.parametrize("username", ["admin", "staff"])
def test_admin_and_staff_can_read_service_status(api_client, username):
    client, _app, _db, _pubmed, _llm = api_client
    response = client.get(
        "/api/medical-knowledge/service-status", headers=auth_header(username)
    )
    assert response.status_code == 200


def test_status_exposes_flags_and_model_but_never_secret_values(api_client, monkeypatch):
    client, _app, _db, _pubmed, _llm = api_client
    monkeypatch.setattr(status_module, "NCBI_EMAIL", "private@example.invalid")
    monkeypatch.setattr(status_module, "NCBI_API_KEY", "private-ncbi-key")
    monkeypatch.setattr(status_module, "OPENAI_API_KEY", "private-openai-key")
    monkeypatch.setattr(status_module, "OPENAI_MODEL", "configured-model")
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "openai")

    response = client.get(
        "/api/medical-knowledge/service-status", headers=auth_header("admin")
    )
    body = response.json()
    assert body == {
        "pubmed": {
            "configured": True,
            "email_configured": True,
            "api_key_configured": True,
        },
        "llm": {
            "configured": True,
            "provider": "openai",
            "model": "configured-model",
            "api_key_configured": True,
            "mode": "remote",
            "local": False,
        },
    }
    response_text = response.text
    for forbidden in (
        "private@example.invalid",
        "private-ncbi-key",
        "private-openai-key",
        "NCBI_EMAIL",
        "NCBI_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert forbidden not in response_text


def test_missing_external_configuration_is_reported_without_breaking_status(api_client, monkeypatch):
    client, _app, _db, _pubmed, _llm = api_client
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "openai")
    monkeypatch.setattr(status_module, "NCBI_EMAIL", None)
    monkeypatch.setattr(status_module, "NCBI_API_KEY", None)
    monkeypatch.setattr(status_module, "OPENAI_API_KEY", None)
    monkeypatch.setattr(status_module, "OPENAI_MODEL", None)
    response = client.get(
        "/api/medical-knowledge/service-status", headers=auth_header("staff")
    )
    assert response.status_code == 200
    assert response.json()["pubmed"]["configured"] is False
    assert response.json()["llm"]["configured"] is False


def test_ollama_status_reports_local_mode_model_and_no_api_key(api_client, monkeypatch):
    client, _app, _db, _pubmed, _llm = api_client
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(status_module, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(status_module, "OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setattr(status_module, "OPENAI_API_KEY", "unused-private-key")
    response = client.get(
        "/api/medical-knowledge/service-status", headers=auth_header("admin")
    )
    assert response.status_code == 200
    assert response.json()["llm"] == {
        "configured": True,
        "provider": "ollama",
        "model": "qwen3:8b",
        "api_key_configured": False,
        "mode": "local",
        "local": True,
    }
    assert "unused-private-key" not in response.text
    assert "127.0.0.1" not in response.text


def test_groq_status_reports_cloud_api_model_and_boolean_key_only(api_client, monkeypatch):
    client, _app, _db, _pubmed, _llm = api_client
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "groq")
    monkeypatch.setattr(status_module, "GROQ_API_KEY", "private-groq-key")
    monkeypatch.setattr(status_module, "GROQ_MODEL", "openai/gpt-oss-20b")
    response = client.get(
        "/api/medical-knowledge/service-status", headers=auth_header("admin")
    )
    assert response.status_code == 200
    assert response.json()["llm"] == {
        "configured": True,
        "provider": "groq",
        "model": "openai/gpt-oss-20b",
        "api_key_configured": True,
        "mode": "cloud_api",
        "local": False,
    }
    assert "private-groq-key" not in response.text
    assert "GROQ_API_KEY" not in response.text


@pytest.mark.parametrize(
    "path,dependency_name",
    [
        ("/api/medical-knowledge/service-status/pubmed/test", "pubmed"),
        ("/api/medical-knowledge/service-status/llm/test", "llm"),
    ],
)
@pytest.mark.parametrize("username", ["admin", "staff"])
def test_admin_and_staff_can_run_explicit_connection_tests(
    api_client, path, dependency_name, username
):
    client, _app, _db, pubmed, llm = api_client
    response = client.post(path, headers=auth_header(username))
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert (pubmed.calls if dependency_name == "pubmed" else llm.calls)


def test_connection_tests_are_small_and_do_not_mutate_database(api_client, monkeypatch):
    client, _app, db, pubmed, llm = api_client
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "ollama")
    user_count_before = db.query(User).count()
    medical_counts_before = tuple(
        db.query(model).count()
        for model in (
            MedicalEvidenceSource,
            MedicalKnowledgeTopic,
            MedicalKnowledgeRevision,
            MedicalRevisionSource,
        )
    )

    pubmed_response = client.post(
        "/api/medical-knowledge/service-status/pubmed/test",
        headers=auth_header("admin"),
    )
    llm_response = client.post(
        "/api/medical-knowledge/service-status/llm/test",
        headers=auth_header("admin"),
    )

    assert pubmed_response.json() == {"ok": True, "message": "Kết nối PubMed thành công."}
    assert llm_response.json() == {"ok": True, "message": "Kết nối AI cục bộ Ollama thành công."}
    assert pubmed.calls == [('"public health"[Title/Abstract]', 1)]
    assert llm.calls == 1
    assert db.query(User).count() == user_count_before
    assert tuple(
        db.query(model).count()
        for model in (
            MedicalEvidenceSource,
            MedicalKnowledgeTopic,
            MedicalKnowledgeRevision,
            MedicalRevisionSource,
        )
    ) == medical_counts_before


def test_connection_failures_return_safe_messages(api_client):
    client, app, _db, _pubmed, _llm = api_client
    app.dependency_overrides[get_status_pubmed_client] = lambda: FakePubMedClient(
        PubMedUnavailableError("private-ncbi-key")
    )
    app.dependency_overrides[get_status_llm_generator] = lambda: FakeLlmGenerator(
        DraftGeneratorOutputError("private-openai-key")
    )

    pubmed = client.post(
        "/api/medical-knowledge/service-status/pubmed/test", headers=auth_header("admin")
    )
    llm = client.post(
        "/api/medical-knowledge/service-status/llm/test", headers=auth_header("admin")
    )
    assert pubmed.status_code == 502
    assert llm.status_code == 502
    assert "private" not in pubmed.text
    assert "private" not in llm.text


@pytest.mark.parametrize(
    "error,status_code,detail",
    [
        (OllamaModelNotSelectedError("secret"), 503, "Chưa chọn model AI cục bộ."),
        (
            OllamaModelNotInstalledError("secret"),
            503,
            "Model AI cục bộ chưa được cài đặt trong Ollama.",
        ),
        (DraftGeneratorTimeoutError("secret"), 504, "AI cục bộ phản hồi quá lâu."),
        (
            DraftGeneratorUnavailableError("secret"),
            502,
            "Không kết nối được AI cục bộ Ollama. Hãy mở Ollama trên máy và thử lại.",
        ),
        (
            DraftGeneratorOutputError("secret"),
            502,
            "AI cục bộ trả dữ liệu không đúng định dạng.",
        ),
    ],
)
def test_ollama_connection_failures_are_distinct_and_safe(
    api_client, monkeypatch, error, status_code, detail
):
    client, app, _db, _pubmed, _llm = api_client
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "ollama")
    app.dependency_overrides[get_status_llm_generator] = lambda: FakeLlmGenerator(error)
    response = client.post(
        "/api/medical-knowledge/service-status/llm/test", headers=auth_header("admin")
    )
    assert response.status_code == status_code
    assert response.json()["detail"] == detail
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "error,status_code,detail",
    [
        (GroqApiKeyMissingError("secret"), 503, "Chưa cấu hình GROQ_API_KEY."),
        (GroqAuthenticationError("secret"), 502, "Không thể xác thực với Groq."),
        (
            GroqModelUnavailableError("secret"),
            503,
            "Model Groq đã cấu hình không khả dụng.",
        ),
        (
            DraftGeneratorRateLimitError("secret"),
            429,
            "Đã đạt giới hạn sử dụng Groq. Hãy thử lại sau.",
        ),
        (DraftGeneratorTimeoutError("secret"), 504, "Groq phản hồi quá lâu."),
        (DraftGeneratorOutputError("secret"), 502, "Groq trả dữ liệu không đúng định dạng."),
        (DraftGeneratorUnavailableError("secret"), 502, "Hiện không thể kết nối Groq."),
    ],
)
def test_groq_connection_failures_are_distinct_and_safe(
    api_client, monkeypatch, error, status_code, detail
):
    client, app, _db, _pubmed, _llm = api_client
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "groq")
    app.dependency_overrides[get_status_llm_generator] = lambda: FakeLlmGenerator(error)
    response = client.post(
        "/api/medical-knowledge/service-status/llm/test", headers=auth_header("admin")
    )
    assert response.status_code == status_code
    assert response.json()["detail"] == detail
    assert "secret" not in response.text


def test_groq_connection_success_is_manual_and_provider_aware(api_client, monkeypatch):
    client, _app, _db, _pubmed, llm = api_client
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "groq")
    assert llm.calls == 0
    response = client.post(
        "/api/medical-knowledge/service-status/llm/test", headers=auth_header("staff")
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "Kết nối Groq thành công."}
    assert llm.calls == 1


def test_real_groq_dependency_reports_missing_key_without_network(api_client, monkeypatch):
    client, app, _db, _pubmed, _llm = api_client
    app.dependency_overrides.pop(get_status_llm_generator)
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "groq")
    monkeypatch.setattr(status_module, "GROQ_API_KEY", None)
    monkeypatch.setattr(status_module, "GROQ_MODEL", "openai/gpt-oss-20b")
    response = client.post(
        "/api/medical-knowledge/service-status/llm/test", headers=auth_header("admin")
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Chưa cấu hình GROQ_API_KEY."


def test_missing_configuration_connection_tests_return_503(api_client, monkeypatch):
    client, app, _db, _pubmed, _llm = api_client
    app.dependency_overrides.pop(get_status_pubmed_client)
    app.dependency_overrides.pop(get_status_llm_generator)
    monkeypatch.setattr(status_module, "NCBI_EMAIL", None)
    monkeypatch.setattr(status_module, "NCBI_API_KEY", None)
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "openai")
    monkeypatch.setattr(status_module, "OPENAI_API_KEY", None)
    monkeypatch.setattr(status_module, "OPENAI_MODEL", None)

    pubmed = client.post(
        "/api/medical-knowledge/service-status/pubmed/test", headers=auth_header("admin")
    )
    llm = client.post(
        "/api/medical-knowledge/service-status/llm/test", headers=auth_header("admin")
    )
    assert pubmed.status_code == 503
    assert llm.status_code == 503


def test_unknown_llm_provider_is_rejected_with_safe_configuration_error(api_client, monkeypatch):
    client, app, _db, _pubmed, _llm = api_client
    app.dependency_overrides.pop(get_status_llm_generator)
    monkeypatch.setattr(status_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "provider-typo")
    response = client.post(
        "/api/medical-knowledge/service-status/llm/test", headers=auth_header("admin")
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Cấu hình nhà cung cấp AI không hợp lệ."


def test_openai_connection_check_is_structured_stateless_and_non_medical():
    captured: dict = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps({"ok": True})}
                        ],
                    }
                ]
            },
        )

    generator = OpenAIMedicalKnowledgeDraftGenerator(
        api_key="fixture-secret",
        model="configured-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert generator.test_connection() is True
    payload = captured["body"]
    payload_text = json.dumps(payload).lower()
    assert payload["store"] is False
    assert "tools" not in payload
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert "patient" not in payload_text
    assert "pubmed" not in payload_text
    assert "fixture-secret" not in payload_text
