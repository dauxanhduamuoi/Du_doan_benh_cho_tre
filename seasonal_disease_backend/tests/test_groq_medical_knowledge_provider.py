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
    DraftGeneratorRateLimitError,
    DraftGeneratorTimeoutError,
    DraftGeneratorUnavailableError,
    GroqApiKeyMissingError,
    GroqAuthenticationError,
    GroqModelUnavailableError,
    OllamaMedicalKnowledgeDraftGenerator,
    OpenAIMedicalKnowledgeDraftGenerator,
    UnknownDraftGeneratorProviderError,
    create_medical_knowledge_draft_generator,
    get_medical_knowledge_llm_configuration,
)
from app.services.medical_knowledge_groq_generator import (
    GroqMedicalKnowledgeDraftGenerator,
    normalize_groq_strict_schema,
)
from app.services.medical_knowledge_prompt import SYSTEM_INSTRUCTIONS


MODEL = "openai/gpt-oss-20b"
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


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
                "doi": "10.1000/selected",
                "title": "Selected rainfall paper",
                "authors": "Selected Author",
                "journal": "Selected Journal",
                "publication_year": 2024,
                "publication_types": ["Observational Study"],
                "abstract_text": "Only this selected PubMed abstract may ground the draft.",
            }
        ],
    )


def proposal(**overrides) -> dict:
    value = {
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
    }
    value.update(overrides)
    return value


def completion(content: str | None = None) -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content if content is not None else json.dumps(proposal()),
                },
            }
        ]
    }


def generator_with(handler, *, api_key: str | None = "groq-fixture-secret", model=MODEL):
    return GroqMedicalKnowledgeDraftGenerator(
        api_key=api_key,
        model=model,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_groq_generation_uses_canonical_host_strict_schema_and_selected_grounding_only():
    captured: dict = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion())

    result = generator_with(handler).generate(context())
    payload = captured["body"]
    payload_text = json.dumps(payload).lower()

    assert result.evidence_level == "LIMITED_OR_INDIRECT"
    assert captured["url"] == ENDPOINT
    assert captured["headers"]["authorization"] == "Bearer groq-fixture-secret"
    assert payload["model"] == MODEL
    assert payload["stream"] is False
    assert payload["temperature"] == 0
    assert payload["citation_options"] == "disabled"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["messages"][0] == {"role": "system", "content": SYSTEM_INSTRUCTIONS}
    assert "Only this selected PubMed abstract" in payload["messages"][1]["content"]
    assert "12345678" in payload["messages"][1]["content"]
    assert "groq-fixture-secret" not in json.dumps(payload)
    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert "browser_search" not in payload_text
    assert "code_interpreter" not in payload_text
    assert "child_age" not in payload_text
    assert "jwt" not in payload_text
    assert "user email" not in payload_text


def test_groq_schema_normalization_preserves_shared_shape_and_strict_requirements():
    original = MedicalKnowledgeDraftProposal.model_json_schema()
    normalized = normalize_groq_strict_schema(original)

    assert normalized is not original
    assert original["properties"]["short_explanation_vi"]["maxLength"] == 2000
    assert "maxLength" not in normalized["properties"]["short_explanation_vi"]
    assert "maxItems" not in normalized["properties"]["source_assessments"]
    assert normalized["additionalProperties"] is False
    assert set(normalized["required"]) == set(normalized["properties"])
    assessment = normalized["$defs"]["SourceAssessment"]
    assert assessment["additionalProperties"] is False
    assert set(assessment["required"]) == set(assessment["properties"])
    assert normalized["properties"]["evidence_level"]["enum"] == [
        "SUPPORTED",
        "LIMITED_OR_INDIRECT",
        "CONFLICTING",
        "INSUFFICIENT",
    ]


def test_groq_connection_check_is_minimal_structured_and_non_medical():
    captured: dict = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion('{"ok":true}'))

    assert generator_with(handler).test_connection() is True
    payload = captured["body"]
    text = json.dumps(payload).lower()
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["ok"]
    assert "pubmed" not in text
    assert "patient" not in text
    assert "tools" not in payload


@pytest.mark.parametrize(
    "field,value",
    [("evidence_level", "STRONG"), ("evidence_scope", "ONE_DISEASE")],
)
def test_groq_revalidates_invalid_medical_enums(field, value):
    def handler(_request):
        return httpx.Response(200, json=completion(json.dumps(proposal(**{field: value}))))

    with pytest.raises(DraftGeneratorOutputError):
        generator_with(handler).generate(context())


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": None}}]},
        completion("not-json"),
        ["not-an-object"],
    ],
)
def test_groq_invalid_or_malformed_output_fails_safely(body):
    with pytest.raises(DraftGeneratorOutputError):
        generator_with(lambda _: httpx.Response(200, json=body)).generate(context())


@pytest.mark.parametrize("status", [401, 403])
def test_groq_authentication_failures_are_distinct(status):
    with pytest.raises(GroqAuthenticationError):
        generator_with(lambda _: httpx.Response(status)).test_connection()


def test_groq_missing_key_performs_no_network_request():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    with pytest.raises(GroqApiKeyMissingError):
        generator_with(handler, api_key=None).test_connection()
    assert calls == 0


def test_groq_secret_is_not_logged_on_provider_failure(caplog):
    generator = generator_with(lambda _: httpx.Response(401), api_key="never-log-this-key")
    with pytest.raises(GroqAuthenticationError):
        generator.test_connection()
    assert "never-log-this-key" not in caplog.text


def test_groq_missing_or_unavailable_model_is_distinct():
    with pytest.raises(GroqModelUnavailableError):
        generator_with(lambda _: pytest.fail("network must not run"), model=None).test_connection()
    with pytest.raises(GroqModelUnavailableError):
        generator_with(lambda _: httpx.Response(404)).test_connection()


def test_groq_rate_limit_has_no_retry_or_provider_fallback():
    calls: list[str] = []

    def handler(request: httpx.Request):
        calls.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": "30"})

    with pytest.raises(DraftGeneratorRateLimitError):
        generator_with(handler).generate(context())
    assert calls == [ENDPOINT]


@pytest.mark.parametrize("status", [408, 504])
def test_groq_http_timeout_status_is_distinct(status):
    with pytest.raises(DraftGeneratorTimeoutError):
        generator_with(lambda _: httpx.Response(status)).test_connection()


def test_groq_network_timeout_is_distinct():
    def handler(_request):
        raise httpx.ReadTimeout("secret provider timeout")

    with pytest.raises(DraftGeneratorTimeoutError):
        generator_with(handler).test_connection()


@pytest.mark.parametrize("status", [498, 500, 502, 503])
def test_groq_provider_unavailable_status_is_safe(status):
    with pytest.raises(DraftGeneratorUnavailableError):
        generator_with(lambda _: httpx.Response(status)).test_connection()


def test_groq_refuses_redirect_without_leaking_key_to_redirect_host():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://attacker.invalid/collect"})

    redirecting_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    generator = GroqMedicalKnowledgeDraftGenerator(
        api_key="redirect-secret",
        model=MODEL,
        client=redirecting_client,
    )
    with pytest.raises(DraftGeneratorUnavailableError):
        generator.test_connection()
    assert len(requests) == 1
    assert requests[0].url.host == "api.groq.com"
    assert requests[0].headers["authorization"] == "Bearer redirect-secret"


def factory(provider: str):
    return create_medical_knowledge_draft_generator(
        provider=provider,
        openai_api_key="openai-secret",
        openai_model="openai-model",
        openai_timeout_seconds=45,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="local-model",
        ollama_timeout_seconds=120,
        groq_api_key="groq-secret",
        groq_model=MODEL,
        groq_timeout_seconds=45,
    )


def test_factory_selects_all_three_providers_and_rejects_unknown_without_fallback():
    groq = factory("groq")
    ollama = factory("ollama")
    openai = factory("openai")
    assert isinstance(groq, GroqMedicalKnowledgeDraftGenerator)
    assert isinstance(ollama, OllamaMedicalKnowledgeDraftGenerator)
    assert isinstance(openai, OpenAIMedicalKnowledgeDraftGenerator)
    with pytest.raises(UnknownDraftGeneratorProviderError):
        factory("groq-then-openai")
    groq.close()
    ollama.close()
    openai.close()


def test_groq_selection_requires_neither_openai_nor_ollama_configuration():
    generator = create_medical_knowledge_draft_generator(
        provider="groq",
        openai_api_key=None,
        openai_model=None,
        openai_timeout_seconds=45,
        ollama_base_url=None,
        ollama_model=None,
        ollama_timeout_seconds=120,
        groq_api_key="groq-secret",
        groq_model=MODEL,
        groq_timeout_seconds=45,
    )
    assert isinstance(generator, GroqMedicalKnowledgeDraftGenerator)
    generator.close()


def test_groq_configuration_status_is_cloud_api_and_key_value_is_not_retained():
    status = get_medical_knowledge_llm_configuration(
        provider="groq",
        openai_api_key=None,
        openai_model=None,
        ollama_base_url=None,
        ollama_model=None,
        groq_api_key="private-groq-key",
        groq_model=MODEL,
    )
    assert status.provider == "groq"
    assert status.mode == "cloud_api"
    assert status.model == MODEL
    assert status.configured is True
    assert status.api_key_configured is True
    assert "private-groq-key" not in repr(status)
