from __future__ import annotations

import json

import httpx
import pytest

from app.medical_knowledge_draft_schemas import (
    DraftGenerationContext,
    MedicalKnowledgeDraftProposal,
)
from app.services.medical_knowledge_draft_generator import (
    DraftGeneratorOutputError,
    DraftGeneratorTimeoutError,
    DraftGeneratorUnavailableError,
    OllamaLocalOnlyError,
    OllamaMedicalKnowledgeDraftGenerator,
    OllamaModelNotInstalledError,
    OllamaModelNotSelectedError,
    OpenAIMedicalKnowledgeDraftGenerator,
    UnknownDraftGeneratorProviderError,
    create_medical_knowledge_draft_generator,
    get_medical_knowledge_llm_configuration,
)
from app.services.medical_knowledge_prompt import SYSTEM_INSTRUCTIONS


MODEL = "qwen3:8b"
BASE_URL = "http://127.0.0.1:11434"


def context() -> DraftGenerationContext:
    return DraftGenerationContext(
        disease_group_id="5",
        disease_group_name="Infectious gastroenteritis",
        report_group_code="A09",
        weather_factor="precipitation",
        sources=[
            {
                "source_id": 7,
                "source_type": "PUBMED",
                "pmid": "12345678",
                "doi": "10.1000/local",
                "title": "Rainfall and gastroenteritis",
                "authors": "Researcher A",
                "journal": "Journal",
                "publication_year": 2024,
                "publication_types": ["Observational Study"],
                "abstract_text": "Selected local grounding abstract.",
            }
        ],
    )


def proposal_json() -> str:
    return json.dumps(
        {
            "evidence_level": "LIMITED_OR_INDIRECT",
            "evidence_scope": "PARTIAL_GROUP",
            "short_explanation_vi": "Nghiên cứu ghi nhận một mối liên hệ ở mức quần thể.",
            "detailed_explanation_vi": "Bằng chứng quan sát chưa chứng minh quan hệ nhân quả.",
            "limitations_vi": "Kết quả chỉ áp dụng cho một phần nhóm bệnh.",
            "source_assessments": [
                {
                    "source_id": 7,
                    "relevance": "DIRECT",
                    "note_vi": "Nguồn đánh giá trực tiếp lượng mưa.",
                }
            ],
        },
        ensure_ascii=False,
    )


def generator_with(handler, *, model: str | None = MODEL, base_url: str = BASE_URL):
    return OllamaMedicalKnowledgeDraftGenerator(
        base_url=base_url,
        model=model,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_ollama_generation_uses_local_chat_exact_schema_and_shared_grounding():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL, "model": MODEL}]})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": proposal_json()}})

    result = generator_with(handler).generate(context())

    assert result.evidence_level == "LIMITED_OR_INDIRECT"
    assert [request.url.path for request in requests] == ["/api/tags", "/api/chat"]
    assert all(request.url.host == "127.0.0.1" for request in requests)
    assert all("authorization" not in request.headers for request in requests)
    payload = json.loads(requests[1].content)
    assert payload["model"] == MODEL
    assert payload["stream"] is False
    assert payload["format"] == MedicalKnowledgeDraftProposal.model_json_schema()
    assert payload["options"] == {"temperature": 0}
    assert payload["messages"][0] == {"role": "system", "content": SYSTEM_INSTRUCTIONS}
    assert "Selected local grounding abstract." in payload["messages"][1]["content"]
    assert "tools" not in payload
    assert "store" not in payload


def test_ollama_connection_check_only_lists_models_and_sends_minimal_structured_chat():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL}]})
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": '{"ok":true}'}}
        )

    assert generator_with(handler).test_connection() is True
    payload = json.loads(requests[1].content)
    assert [request.url.path for request in requests] == ["/api/tags", "/api/chat"]
    assert payload["stream"] is False
    assert payload["format"]["properties"]["ok"]["const"] is True
    assert "pubmed" not in json.dumps(payload).lower()
    assert "patient" not in json.dumps(payload).lower()
    assert "tools" not in payload


def test_localhost_endpoint_is_accepted():
    hosts: list[str] = []

    def handler(request: httpx.Request):
        hosts.append(request.url.host or "")
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL}]})
        return httpx.Response(200, json={"message": {"content": '{"ok":true}'}})

    assert generator_with(handler, base_url="http://localhost:11434").test_connection()
    assert hosts == ["localhost", "localhost"]


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:11434",
        "http://192.168.1.10:11434",
        "http://ollama.example.com:11434",
        "http://[::1]:11434",
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1:11434/proxy",
    ],
)
def test_ollama_rejects_every_noncanonical_or_nonlocal_endpoint_before_network(base_url):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    with pytest.raises(OllamaLocalOnlyError):
        generator_with(handler, base_url=base_url).test_connection()
    assert calls == 0


@pytest.mark.parametrize("model", ["gpt-oss:120b-cloud", "cloud/model", "model_cloud"])
def test_ollama_rejects_cloud_model_identifiers_without_fallback(model):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    with pytest.raises(OllamaLocalOnlyError):
        generator_with(handler, model=model).test_connection()
    assert calls == 0


def test_ollama_missing_model_is_distinct_and_performs_no_request():
    with pytest.raises(OllamaModelNotSelectedError):
        generator_with(lambda _: pytest.fail("network must not be called"), model=None).test_connection()


def test_ollama_model_not_installed_is_distinct_and_does_not_call_chat():
    paths: list[str] = []

    def handler(request: httpx.Request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"models": [{"name": "another-model:latest"}]})

    with pytest.raises(OllamaModelNotInstalledError):
        generator_with(handler).generate(context())
    assert paths == ["/api/tags"]


def test_ollama_unavailable_timeout_and_invalid_output_are_distinct():
    def unavailable(_request):
        raise httpx.ConnectError("connection refused")

    def timeout(_request):
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(DraftGeneratorUnavailableError):
        generator_with(unavailable).test_connection()
    with pytest.raises(DraftGeneratorTimeoutError):
        generator_with(timeout).test_connection()

    def invalid(request: httpx.Request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL}]})
        return httpx.Response(200, json={"message": {"content": "not-json"}})

    with pytest.raises(DraftGeneratorOutputError):
        generator_with(invalid).generate(context())


def factory(provider: str, *, client: httpx.Client | None = None):
    return create_medical_knowledge_draft_generator(
        provider=provider,
        openai_api_key="openai-secret",
        openai_model="openai-model",
        openai_timeout_seconds=45,
        ollama_base_url=BASE_URL,
        ollama_model=MODEL,
        ollama_timeout_seconds=120,
        client=client,
    )


def test_factory_selects_only_requested_provider_and_rejects_unknown_provider():
    ollama = factory("ollama")
    openai = factory("openai")
    assert isinstance(ollama, OllamaMedicalKnowledgeDraftGenerator)
    assert isinstance(openai, OpenAIMedicalKnowledgeDraftGenerator)
    with pytest.raises(UnknownDraftGeneratorProviderError):
        factory("automatic-fallback")
    ollama.close()
    openai.close()


def test_configuration_status_is_provider_aware_and_never_requires_ollama_api_key():
    local = get_medical_knowledge_llm_configuration(
        provider="ollama",
        openai_api_key=None,
        openai_model=None,
        ollama_base_url=BASE_URL,
        ollama_model=MODEL,
    )
    assert local.provider == "ollama"
    assert local.mode == "local"
    assert local.configured is True
    assert local.api_key_configured is False

    selected_without_openai = create_medical_knowledge_draft_generator(
        provider="ollama",
        openai_api_key=None,
        openai_model=None,
        openai_timeout_seconds=45,
        ollama_base_url=BASE_URL,
        ollama_model=MODEL,
        ollama_timeout_seconds=120,
    )
    assert isinstance(selected_without_openai, OllamaMedicalKnowledgeDraftGenerator)
    selected_without_openai.close()

    unknown = get_medical_knowledge_llm_configuration(
        provider="unknown",
        openai_api_key="secret",
        openai_model="model",
        ollama_base_url=BASE_URL,
        ollama_model=MODEL,
    )
    assert unknown.configured is False
    assert unknown.mode == "unknown"
