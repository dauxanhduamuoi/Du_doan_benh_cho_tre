from __future__ import annotations

from datetime import datetime, timezone
import json

import httpx
import pytest

from app.auto_medical_knowledge_schemas import AutoMedicalKnowledgeDraftProposal

from app.medical_knowledge_draft_schemas import (
    DraftGenerationContext,
    MedicalKnowledgeDraftProposal,
)
from app.services.medical_knowledge_draft_generator import (
    DraftGeneratorOutputError,
    DraftGeneratorProviderContentEmptyError,
    DraftGeneratorProviderEnvelopeError,
    DraftGeneratorProviderIncompleteError,
    DraftGeneratorProviderRequestRejectedError,
    DraftGeneratorRateLimitError,
    DraftGeneratorTimeoutError,
    DraftGeneratorUnavailableError,
    DraftGeneratorStructuredOutputError,
    GroqApiKeyMissingError,
    GroqAuthenticationError,
    GroqModelUnavailableError,
    OllamaMedicalKnowledgeDraftGenerator,
    OpenAIMedicalKnowledgeDraftGenerator,
    UnknownDraftGeneratorProviderError,
    create_medical_knowledge_draft_generator,
    get_medical_knowledge_llm_configuration,
    parse_medical_draft_output,
)
from app.services.medical_knowledge_groq_generator import (
    GroqMedicalKnowledgeDraftGenerator,
    normalize_groq_strict_schema,
    parse_retry_after_seconds,
)
from app.services.medical_knowledge_prompt import SYSTEM_INSTRUCTIONS
from app.services.auto_medical_knowledge_prompt import (
    AUTO_SYSTEM_INSTRUCTIONS,
    build_auto_contract_repair_input,
    build_auto_generation_input,
)


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
                    "evidence_content_id": 10,
                    "content_kind": "ABSTRACT",
                    "evidence_text": "Only this selected PubMed abstract may ground the draft.",
                    "content_origin": "NCBI_PUBMED",
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
                "population_relevance": "PEDIATRIC_DIRECT",
                "population_note": "Abstract mô tả trực tiếp trẻ em.",
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
                "finish_reason": "stop",
            }
        ]
    }


def generator_with(
    handler,
    *,
    api_key: str | None = "groq-fixture-secret",
    model=MODEL,
    **kwargs,
):
    return GroqMedicalKnowledgeDraftGenerator(
        api_key=api_key,
        model=model,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
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


def test_actual_auto_v2_request_uses_provider_compatible_strict_transport_schema():
    captured: dict = {}
    value = proposal(numeric_claims=[])
    core_schema = AutoMedicalKnowledgeDraftProposal.model_json_schema()

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion(json.dumps(value)))

    result = generator_with(
        handler,
        system_instructions=AUTO_SYSTEM_INSTRUCTIONS,
        input_builder=build_auto_generation_input,
        proposal_model=AutoMedicalKnowledgeDraftProposal,
    ).generate(context())
    payload = captured["body"]
    schema = payload["response_format"]["json_schema"]["schema"]

    assert payload["model"] == MODEL
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert "numeric_claims" in schema["properties"]
    assert "source_assessments" in schema["properties"]
    assert set(schema["required"]) == set(schema["properties"])
    claim_schema = schema["$defs"]["AutoNumericClaimProposal"]
    core_claim_schema = core_schema["$defs"]["AutoNumericClaimProposal"]
    assert "unit" not in core_claim_schema["required"]
    assert core_claim_schema["properties"]["unit"]["default"] is None
    assert set(claim_schema["required"]) == set(claim_schema["properties"])
    assert claim_schema["properties"]["unit"]["anyOf"] == [
        {"type": "string"}, {"type": "null"}
    ]
    assert "default" not in claim_schema["properties"]["unit"]
    assert "exclusiveMinimum" not in claim_schema["properties"]["source_id"]
    assert result.numeric_claims == []


def test_actual_initial_and_contract_repair_payloads_have_strict_schema_parity():
    captured: list[dict] = []
    value = proposal(numeric_claims=[])

    def handler(request: httpx.Request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=completion(json.dumps(value)))

    generator = generator_with(
        handler,
        system_instructions=AUTO_SYSTEM_INSTRUCTIONS,
        input_builder=build_auto_generation_input,
        proposal_model=AutoMedicalKnowledgeDraftProposal,
    )
    previous = AutoMedicalKnowledgeDraftProposal.model_validate(value)
    repair_input = build_auto_contract_repair_input(
        context(),
        previous,
        failure_code="AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED",
        field="detailed_explanation_vi",
        numeric_value="3",
    )
    generator.generate(context())
    generator.generate(context(), user_input_override=repair_input)

    assert len(captured) == 2
    initial, repair = captured
    assert initial["model"] == repair["model"] == MODEL
    assert initial["response_format"] == repair["response_format"]
    assert initial["response_format"]["type"] == "json_schema"
    assert initial["response_format"]["json_schema"]["strict"] is True
    assert {
        key: value for key, value in initial.items() if key != "messages"
    } == {
        key: value for key, value in repair.items() if key != "messages"
    }
    for payload in captured:
        assert [message["role"] for message in payload["messages"]] == [
            "system", "user"
        ]
        assert all(
            isinstance(message["content"], str) for message in payload["messages"]
        )
    repair_message = json.loads(repair["messages"][1]["content"])
    assert repair_message["task"] == (
        "AUTO_MEDICAL_KNOWLEDGE_V2_COMPLETE_CONTRACT_REPAIR"
    )
    assert len(repair_message["trusted_selected_evidence"]) == 1
    previous_json = repair_message["contract_repair"]["previous_proposal_json"]
    assert json.loads(previous_json) == previous.model_dump(mode="json")
    assert len(repair["messages"][1]["content"]) < 60_000


@pytest.mark.parametrize(
    "value",
    [
        proposal(
            evidence_level="INSUFFICIENT",
            short_explanation_vi=None,
            detailed_explanation_vi=None,
            limitations_vi=None,
            numeric_claims=[],
        ),
        proposal(
            short_explanation_vi="Giải thích nhi khoa – còn giới hạn.",
            numeric_claims=[{
                "value_text": "3",
                "claim_kind": "COUNT",
                "unit": None,
                "source_id": 7,
                "supporting_text": "participants were divided into 3 groups",
            }],
        ),
    ],
)
def test_contract_repair_previous_proposal_is_deterministic_json_text(value):
    previous = AutoMedicalKnowledgeDraftProposal.model_validate(value)
    first = build_auto_contract_repair_input(
        context(),
        previous,
        failure_code="AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED",
        field="numeric_claims.0",
        numeric_value="3",
    )
    second = build_auto_contract_repair_input(
        context(),
        previous,
        failure_code="AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED",
        field="numeric_claims.0",
        numeric_value="3",
    )
    assert first == second
    envelope = json.loads(first)
    assert isinstance(envelope["contract_repair"]["previous_proposal_json"], str)
    assert json.loads(
        envelope["contract_repair"]["previous_proposal_json"]
    ) == previous.model_dump(mode="json")
    assert len(envelope["trusted_selected_evidence"]) == len(context().sources)


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
    "wrapper",
    [
        lambda value: value,
        lambda value: f"```json\n{value}\n```",
        lambda value: f" \ufeff  {value} \n",
        lambda value: f"Result follows: {value}",
    ],
)
def test_safe_structural_normalization_accepts_one_unambiguous_object(wrapper):
    value = proposal(evidence_level="limited_or_indirect")
    parsed = parse_medical_draft_output(
        wrapper(json.dumps(value)), context(), MedicalKnowledgeDraftProposal
    )
    assert parsed.evidence_level == "LIMITED_OR_INDIRECT"


@pytest.mark.parametrize("extra", [lambda value: value + " " + value, lambda value: "[] " + value])
def test_multiple_json_values_are_rejected_as_ambiguous(extra):
    with pytest.raises(DraftGeneratorStructuredOutputError) as caught:
        parse_medical_draft_output(
            extra(json.dumps(proposal())), context()
        )
    assert caught.value.code == "AUTO_OUTPUT_JSON_INVALID"


@pytest.mark.parametrize(
    "mutator,code,field",
    [
        (lambda value: value.pop("short_explanation_vi"), "AUTO_OUTPUT_MISSING_REQUIRED_FIELD", "short_explanation_vi"),
        (lambda value: value.update(evidence_level="STRONG"), "AUTO_OUTPUT_INVALID_ENUM", "evidence_level"),
        (lambda value: value["source_assessments"].clear(), "AUTO_OUTPUT_SOURCE_SET_MISMATCH", "source_assessments"),
        (lambda value: value["source_assessments"].append(dict(value["source_assessments"][0])), "AUTO_OUTPUT_SOURCE_SET_MISMATCH", "source_assessments"),
        (lambda value: value["source_assessments"][0].update(source_id=999), "AUTO_OUTPUT_SOURCE_SET_MISMATCH", "source_assessments"),
    ],
)
def test_structural_failures_have_precise_codes(mutator, code, field):
    value = proposal()
    mutator(value)
    with pytest.raises(DraftGeneratorStructuredOutputError) as caught:
        parse_medical_draft_output(json.dumps(value), context())
    assert caught.value.code == code
    assert caught.value.field == field


def test_source_order_is_irrelevant_but_exact_set_is_required():
    ctx = context().model_copy(
        update={"sources": [
            context().sources[0],
            context().sources[0].model_copy(update={"source_id": 8, "pmid": "87654321"}),
        ]}
    )
    value = proposal()
    second = dict(value["source_assessments"][0])
    second["source_id"] = 8
    value["source_assessments"] = [second, value["source_assessments"][0]]
    parsed = parse_medical_draft_output(json.dumps(value), ctx)
    assert [item.source_id for item in parsed.source_assessments] == [8, 7]


@pytest.mark.parametrize("level", ["INSUFFICIENT", "CONFLICTING"])
def test_auto_schema_allows_safe_empty_explanations(level):
    value = proposal(
        evidence_level=level,
        evidence_scope="PARTIAL_GROUP",
        short_explanation_vi=None,
        detailed_explanation_vi=None,
        limitations_vi=None,
        numeric_claims=[],
    )
    parsed = parse_medical_draft_output(
        json.dumps(value), context(), AutoMedicalKnowledgeDraftProposal
    )
    assert parsed.evidence_level == level
    assert parsed.short_explanation_vi is None


def test_auto_v2_schema_requires_numeric_claims_and_normalizes_bounded_kind():
    missing = proposal()
    with pytest.raises(DraftGeneratorStructuredOutputError) as caught:
        parse_medical_draft_output(
            json.dumps(missing), context(), AutoMedicalKnowledgeDraftProposal
        )
    assert caught.value.code == "AUTO_OUTPUT_MISSING_REQUIRED_FIELD"
    assert caught.value.field == "numeric_claims"

    value = proposal(numeric_claims=[{
        "value_text": "27%",
        "claim_kind": "percentage",
        "unit": "percent",
        "source_id": 7,
        "supporting_text": "Risk increased by 27%",
    }])
    parsed = parse_medical_draft_output(
        json.dumps(value), context(), AutoMedicalKnowledgeDraftProposal
    )
    assert parsed.numeric_claims[0].claim_kind == "PERCENTAGE"


@pytest.mark.parametrize(
    ("body", "error_type", "stage"),
    [
        ({}, DraftGeneratorProviderEnvelopeError, "choices_missing"),
        ({"choices": []}, DraftGeneratorProviderEnvelopeError, "choices_empty"),
        (
            {"choices": [{"finish_reason": "stop"}]},
            DraftGeneratorProviderEnvelopeError,
            "message_missing",
        ),
        (
            {"choices": [{"message": {"content": json.dumps(proposal())}}]},
            DraftGeneratorProviderEnvelopeError,
            "finish_reason_missing",
        ),
        (
            {"choices": [{"finish_reason": "stop", "message": {"content": None}}]},
            DraftGeneratorProviderContentEmptyError,
            "content_empty",
        ),
        (
            {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]},
            DraftGeneratorProviderContentEmptyError,
            "content_empty",
        ),
        (
            {"choices": [{"finish_reason": "stop", "message": {"content": "  \n"}}]},
            DraftGeneratorProviderContentEmptyError,
            "content_empty",
        ),
    ],
)
def test_groq_provider_envelope_failures_are_typed_and_safely_described(
    body, error_type, stage
):
    with pytest.raises(error_type) as caught:
        generator_with(lambda _: httpx.Response(200, json=body)).generate(context())
    assert caught.value.code.startswith("AUTO_OUTPUT_PROVIDER_")
    assert caught.value.provider_diagnostics["provider_stage"] == stage
    assert "content" not in caught.value.provider_diagnostics


def test_groq_valid_and_fenced_json_content_reaches_the_existing_parser():
    value = json.dumps(proposal())
    for content in (value, f"```json\n{value}\n```"):
        result = generator_with(
            lambda _, content=content: httpx.Response(200, json=completion(content))
        ).generate(context())
        assert result.evidence_level == "LIMITED_OR_INDIRECT"


def test_groq_non_json_content_is_json_invalid_not_provider_response_invalid():
    with pytest.raises(DraftGeneratorStructuredOutputError) as caught:
        generator_with(
            lambda _: httpx.Response(200, json=completion("not-json"))
        ).generate(context())
    assert caught.value.code == "AUTO_OUTPUT_JSON_INVALID"


def test_groq_valid_json_wrong_schema_is_schema_invalid():
    value = proposal(short_explanation_vi=17)
    with pytest.raises(DraftGeneratorStructuredOutputError) as caught:
        generator_with(
            lambda _: httpx.Response(200, json=completion(json.dumps(value)))
        ).generate(context())
    assert caught.value.code == "AUTO_OUTPUT_SCHEMA_INVALID"


def test_groq_auto_v2_missing_numeric_claims_has_precise_missing_field_code():
    with pytest.raises(DraftGeneratorStructuredOutputError) as caught:
        generator_with(
            lambda _: httpx.Response(200, json=completion(json.dumps(proposal()))),
            system_instructions=AUTO_SYSTEM_INSTRUCTIONS,
            input_builder=build_auto_generation_input,
            proposal_model=AutoMedicalKnowledgeDraftProposal,
        ).generate(context())
    assert caught.value.code == "AUTO_OUTPUT_MISSING_REQUIRED_FIELD"
    assert caught.value.field == "numeric_claims"


def test_groq_auto_v2_empty_numeric_claims_is_valid_for_qualitative_output():
    result = generator_with(
        lambda _: httpx.Response(
            200, json=completion(json.dumps(proposal(numeric_claims=[])))
        ),
        system_instructions=AUTO_SYSTEM_INSTRUCTIONS,
        input_builder=build_auto_generation_input,
        proposal_model=AutoMedicalKnowledgeDraftProposal,
    ).generate(context())
    assert result.numeric_claims == []


@pytest.mark.parametrize("finish_reason", ["length", "tool_calls", "function_call"])
def test_groq_non_success_finish_reason_is_incomplete(finish_reason):
    body = completion()
    body["choices"][0]["finish_reason"] = finish_reason
    with pytest.raises(DraftGeneratorProviderIncompleteError) as caught:
        generator_with(lambda _: httpx.Response(200, json=body)).generate(context())
    assert caught.value.code == "AUTO_OUTPUT_PROVIDER_INCOMPLETE"
    assert caught.value.provider_diagnostics["finish_reason"] == finish_reason


def test_groq_http_400_request_rejection_is_not_misclassified_as_content_json():
    with pytest.raises(DraftGeneratorProviderRequestRejectedError) as caught:
        generator_with(lambda _: httpx.Response(400, json={"error": {
            "code": "json_validate_failed",
            "type": "invalid_request_error",
            "message": "must not be persisted",
            "failed_generation": "raw provider output must not be persisted",
        }})).generate(context())
    assert caught.value.code == "AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED"
    assert caught.value.provider_diagnostics["http_status"] == 400
    assert caught.value.provider_diagnostics["provider_stage"] == "http_request_rejected"
    assert caught.value.provider_diagnostics["provider_error_category"] == (
        "json_validate_failed"
    )
    assert caught.value.provider_diagnostics["provider_error_type"] == (
        "invalid_request_error"
    )
    assert caught.value.provider_diagnostics["response_format_type"] == "json_schema"
    assert caught.value.provider_diagnostics["request_body_bytes"] > 0
    assert "message" not in caught.value.provider_diagnostics
    assert "failed_generation" not in caught.value.provider_diagnostics


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

    with pytest.raises(DraftGeneratorRateLimitError) as caught:
        generator_with(handler).generate(context())
    assert calls == [ENDPOINT]
    assert caught.value.retry_after_seconds == 30


def test_groq_retry_after_http_date_and_invalid_value_are_parsed_safely():
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    assert parse_retry_after_seconds(
        "Sun, 30 Aug 2026 12:02:05 GMT", now=now
    ) == 125
    assert parse_retry_after_seconds("not-a-delay", now=now) is None
    assert parse_retry_after_seconds("-1", now=now) is None


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
