from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Literal, Protocol, TypeVar
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.medical_knowledge_draft_schemas import (
    DraftGenerationContext,
    MedicalKnowledgeDraftProposal,
)
from app.services.medical_knowledge_prompt import SYSTEM_INSTRUCTIONS, build_generation_input


class DraftGeneratorError(RuntimeError):
    pass


class DraftGeneratorConfigurationError(DraftGeneratorError):
    pass


class DraftGeneratorUnavailableError(DraftGeneratorError):
    pass


class DraftGeneratorRateLimitError(DraftGeneratorUnavailableError):
    def __init__(
        self, message: str, *, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class DraftGeneratorOutputError(DraftGeneratorError):
    pass


class DraftGeneratorStructuredOutputError(DraftGeneratorOutputError):
    """A safe, machine-readable failure in the model's output contract."""

    def __init__(
        self,
        code: str,
        safe_detail: str,
        *,
        field: str | None = None,
        source_id: int | None = None,
    ):
        super().__init__(safe_detail)
        self.code = code
        self.safe_detail = safe_detail
        self.field = field
        self.source_id = source_id


class DraftGeneratorProviderResponseError(DraftGeneratorOutputError):
    """A provider-boundary failure with only allow-listed, non-content diagnostics."""

    code = "AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID"

    def __init__(self, safe_detail: str, *, diagnostics: dict | None = None) -> None:
        super().__init__(safe_detail)
        self.safe_detail = safe_detail
        self.provider_diagnostics = diagnostics or {}


class DraftGeneratorProviderEnvelopeError(DraftGeneratorProviderResponseError):
    pass


class DraftGeneratorProviderRequestRejectedError(DraftGeneratorProviderResponseError):
    code = "AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED"


class DraftGeneratorProviderContentEmptyError(DraftGeneratorProviderResponseError):
    code = "AUTO_OUTPUT_PROVIDER_CONTENT_EMPTY"


class DraftGeneratorProviderIncompleteError(DraftGeneratorProviderResponseError):
    code = "AUTO_OUTPUT_PROVIDER_INCOMPLETE"


class DraftProposalWholeGroupRequiresDirectError(DraftGeneratorOutputError):
    pass


def raise_structured_draft_validation_error(
    provider: str, exc: ValidationError
) -> None:
    if "WHOLE_GROUP requires at least one DIRECT source assessment" in str(exc):
        raise DraftProposalWholeGroupRequiresDirectError(
            f"{provider} proposed WHOLE_GROUP without a DIRECT source"
        ) from exc
    raise DraftGeneratorOutputError(
        f"{provider} returned an invalid structured draft"
    ) from exc


ProposalT = TypeVar("ProposalT", bound=BaseModel)
_SAFE_ENUMS = {
    "result": {"SUPPORTED", "INSUFFICIENT"},
    "evidence_level": {
        "SUPPORTED", "LIMITED_OR_INDIRECT", "CONFLICTING", "INSUFFICIENT"
    },
    "evidence_scope": {"WHOLE_GROUP", "PARTIAL_GROUP"},
    "relevance": {"DIRECT", "INDIRECT", "NOT_SUPPORTIVE"},
    "population_relevance": {
        "PEDIATRIC_DIRECT", "MIXED_AGE", "ADULT_ONLY", "ELDERLY_ONLY", "UNKNOWN"
    },
    "claim_kind": {
        "COUNT", "PERCENTAGE", "RATE", "RATIO_OR_EFFECT", "MEASUREMENT",
        "AGE", "DURATION", "TEMPORAL_PERIOD", "OTHER_NUMERIC",
    },
}


def _raise_structural(
    code: str,
    detail: str,
    *,
    field: str | None = None,
    source_id: int | None = None,
    cause: Exception | None = None,
) -> None:
    error = DraftGeneratorStructuredOutputError(
        code, detail, field=field, source_id=source_id
    )
    if cause is not None:
        raise error from cause
    raise error


def _normalized_json_object(output_text: str) -> dict:
    text = output_text.strip().lstrip("\ufeff").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip().lstrip("\ufeff").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as direct_error:
        start = text.find("{")
        if start < 0:
            _raise_structural(
                "AUTO_OUTPUT_JSON_INVALID",
                "Provider output does not contain a valid JSON object.",
                cause=direct_error,
            )
        try:
            value, end = json.JSONDecoder().raw_decode(text, start)
        except json.JSONDecodeError as exc:
            _raise_structural(
                "AUTO_OUTPUT_JSON_INVALID",
                "Provider output does not contain a valid JSON object.",
                cause=exc,
            )
        # Plain prose around one object is harmless. Any other JSON value is
        # ambiguous and must fail closed.
        prefix = text[:start].strip()
        suffix = text[end:].strip()
        surrounding_json = False
        for surrounding in (prefix, suffix):
            if not surrounding:
                continue
            try:
                json.JSONDecoder().raw_decode(surrounding)
                surrounding_json = True
            except json.JSONDecodeError:
                pass
        if "}" in prefix or "{" in suffix or "}" in suffix or surrounding_json:
            _raise_structural(
                "AUTO_OUTPUT_JSON_INVALID",
                "Provider output contains multiple or ambiguous JSON objects.",
            )
    if not isinstance(value, dict):
        _raise_structural(
            "AUTO_OUTPUT_SCHEMA_INVALID",
            "Provider output must be one JSON object.",
        )
    return value


def _normalize_safe_enum(value, field: str):
    if not isinstance(value, str):
        return value
    canonical = value.strip().upper()
    return canonical if canonical in _SAFE_ENUMS[field] else value


def parse_medical_draft_output(
    output_text: str,
    context: DraftGenerationContext,
    proposal_model: type[ProposalT] = MedicalKnowledgeDraftProposal,
) -> ProposalT:
    """Normalize formatting only, then validate schema and exact provenance."""

    value = _normalized_json_object(output_text)
    for field in ("result", "evidence_level", "evidence_scope"):
        if field in value:
            value[field] = _normalize_safe_enum(value[field], field)
    assessments = value.get("source_assessments")
    if isinstance(assessments, list):
        for assessment in assessments:
            if not isinstance(assessment, dict):
                continue
            for field in ("relevance", "population_relevance"):
                if field in assessment:
                    assessment[field] = _normalize_safe_enum(assessment[field], field)
    numeric_claims = value.get("numeric_claims")
    if isinstance(numeric_claims, list):
        for claim in numeric_claims:
            if isinstance(claim, dict) and "claim_kind" in claim:
                claim["claim_kind"] = _normalize_safe_enum(
                    claim["claim_kind"], "claim_kind"
                )

    required = proposal_model.model_json_schema().get("required", [])
    missing = [field for field in required if field not in value]
    if missing:
        _raise_structural(
            "AUTO_OUTPUT_MISSING_REQUIRED_FIELD",
            "Provider output is missing a required field.",
            field=str(missing[0]),
        )

    selected_ids = [source.source_id for source in context.sources]
    if "source_assessments" in proposal_model.model_fields:
        if not isinstance(assessments, list):
            _raise_structural(
                "AUTO_OUTPUT_SCHEMA_INVALID",
                "source_assessments must be an array.",
                field="source_assessments",
            )
        returned_ids = [
            item.get("source_id") for item in assessments if isinstance(item, dict)
        ]
        if (
            len(returned_ids) != len(assessments)
            or len(returned_ids) != len(selected_ids)
            or len(set(returned_ids)) != len(returned_ids)
            or set(returned_ids) != set(selected_ids)
        ):
            unexpected = next(
                (item for item in returned_ids if isinstance(item, int) and item not in selected_ids),
                None,
            )
            _raise_structural(
                "AUTO_OUTPUT_SOURCE_SET_MISMATCH",
                "Provider output must assess every selected source ID exactly once.",
                field="source_assessments",
                source_id=unexpected,
            )

    try:
        return proposal_model.model_validate(value)
    except ValidationError as exc:
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = ".".join(str(item) for item in first.get("loc", ())) or None
        error_type = str(first.get("type") or "")
        if error_type == "missing":
            code = "AUTO_OUTPUT_MISSING_REQUIRED_FIELD"
        elif error_type in {"literal_error", "enum"}:
            code = "AUTO_OUTPUT_INVALID_ENUM"
        else:
            code = "AUTO_OUTPUT_SCHEMA_INVALID"
        _raise_structural(
            code,
            "Provider output does not satisfy the required structured schema.",
            field=field,
            cause=exc,
        )


class DraftGeneratorRefusalError(DraftGeneratorOutputError):
    pass


class DraftGeneratorTimeoutError(DraftGeneratorUnavailableError):
    pass


class OllamaModelNotSelectedError(DraftGeneratorConfigurationError):
    pass


class OllamaModelNotInstalledError(DraftGeneratorConfigurationError):
    pass


class OllamaLocalOnlyError(DraftGeneratorConfigurationError):
    pass


class GroqApiKeyMissingError(DraftGeneratorConfigurationError):
    pass


class GroqAuthenticationError(DraftGeneratorConfigurationError):
    pass


class GroqModelUnavailableError(DraftGeneratorConfigurationError):
    pass


class UnknownDraftGeneratorProviderError(DraftGeneratorConfigurationError):
    pass


class _ConnectionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True]


class MedicalKnowledgeDraftGenerator(Protocol):
    @property
    def model_name(self) -> str:
        ...

    def generate(
        self,
        context: DraftGenerationContext,
        *,
        structural_retry: bool = False,
        user_input_override: str | None = None,
    ) -> BaseModel:
        ...

    def test_connection(self) -> bool:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class MedicalKnowledgeLlmConfiguration:
    provider: str
    mode: Literal["local", "remote", "cloud_api", "unknown"]
    model: str | None
    configured: bool
    api_key_configured: bool


_STRUCTURAL_RETRY_INSTRUCTION = (
    "Previous response failed the structured-output contract. Return a fresh "
    "complete response from the supplied evidence using the exact schema."
)


def build_generation_user_input(
    context: DraftGenerationContext,
    input_builder: Callable[[DraftGenerationContext], str],
    *,
    structural_retry: bool = False,
    user_input_override: str | None = None,
) -> str:
    """Compose provider-neutral generation input without provider business logic."""

    if user_input_override is not None:
        return user_input_override
    sections = [input_builder(context)]
    if structural_retry:
        sections.append(_STRUCTURAL_RETRY_INSTRUCTION)
    return "\n\n".join(sections)


_LOCAL_OLLAMA_HOSTS = frozenset({"localhost", "127.0.0.1"})
_CLOUD_MODEL_MARKER = re.compile(r"(?:^|[:/_-])cloud(?:$|[:/_-])", re.IGNORECASE)


def normalize_local_ollama_base_url(base_url: str | None) -> str:
    """Return a canonical loopback HTTP URL or reject non-local Ollama endpoints."""

    raw_url = (base_url or "").strip()
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as exc:
        raise OllamaLocalOnlyError("Ollama base URL is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _LOCAL_OLLAMA_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise OllamaLocalOnlyError("Ollama must use a local loopback HTTP endpoint")
    netloc = parsed.hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit(("http", netloc, "", "", ""))


def _validate_local_model_name(model: str | None) -> str:
    normalized = (model or "").strip()
    if not normalized:
        raise OllamaModelNotSelectedError("No local Ollama model is selected")
    if _CLOUD_MODEL_MARKER.search(normalized):
        raise OllamaLocalOnlyError("Cloud-backed Ollama models are not allowed")
    return normalized


def get_medical_knowledge_llm_configuration(
    *,
    provider: str | None,
    openai_api_key: str | None,
    openai_model: str | None,
    ollama_base_url: str | None,
    ollama_model: str | None,
    groq_api_key: str | None = None,
    groq_model: str | None = None,
) -> MedicalKnowledgeLlmConfiguration:
    normalized_provider = (provider or "").strip().lower()
    if normalized_provider == "groq":
        return MedicalKnowledgeLlmConfiguration(
            provider="groq",
            mode="cloud_api",
            model=groq_model,
            configured=bool(groq_api_key and groq_model),
            api_key_configured=bool(groq_api_key),
        )
    if normalized_provider == "openai":
        return MedicalKnowledgeLlmConfiguration(
            provider="openai",
            mode="remote",
            model=openai_model,
            configured=bool(openai_api_key and openai_model),
            api_key_configured=bool(openai_api_key),
        )
    if normalized_provider == "ollama":
        configured = bool(ollama_model)
        if configured:
            try:
                normalize_local_ollama_base_url(ollama_base_url)
                _validate_local_model_name(ollama_model)
            except DraftGeneratorConfigurationError:
                configured = False
        return MedicalKnowledgeLlmConfiguration(
            provider="ollama",
            mode="local",
            model=ollama_model,
            configured=configured,
            api_key_configured=False,
        )
    return MedicalKnowledgeLlmConfiguration(
        provider=normalized_provider,
        mode="unknown",
        model=None,
        configured=False,
        api_key_configured=False,
    )


class OpenAIMedicalKnowledgeDraftGenerator:
    """OpenAI Responses API provider with strict structured output and no tools."""

    endpoint = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None,
        timeout_seconds: float = 45.0,
        client: httpx.Client | None = None,
        system_instructions: str = SYSTEM_INSTRUCTIONS,
        input_builder: Callable[[DraftGenerationContext], str] = build_generation_input,
        proposal_model: type[BaseModel] = MedicalKnowledgeDraftProposal,
    ):
        self.api_key = api_key
        self._model_name = model
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.system_instructions = system_instructions
        self.input_builder = input_builder
        self.proposal_model = proposal_model

    @property
    def model_name(self) -> str:
        return self._model_name or ""

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _require_configuration(self) -> None:
        if not self.api_key or not self._model_name:
            raise DraftGeneratorConfigurationError(
                "AI draft generation is not configured on the server"
            )

    def _post(self, payload: dict) -> dict:
        self._require_configuration()
        try:
            response = self.client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.RequestError as exc:
            raise DraftGeneratorUnavailableError(
                "OpenAI draft generation is temporarily unavailable"
            ) from exc

        if response.status_code == 429:
            raise DraftGeneratorRateLimitError("OpenAI draft generation rate limit was reached")
        if response.status_code >= 500:
            raise DraftGeneratorUnavailableError("OpenAI draft generation is temporarily unavailable")
        if response.status_code >= 400:
            raise DraftGeneratorOutputError("OpenAI could not generate a medical draft")

        try:
            return response.json()
        except ValueError as exc:
            raise DraftGeneratorOutputError("OpenAI returned an invalid structured response") from exc

    @staticmethod
    def _extract_output_text(body: dict) -> str:
        for output in body.get("output", []):
            if output.get("type") != "message":
                continue
            for content in output.get("content", []):
                if content.get("type") == "refusal":
                    raise DraftGeneratorRefusalError("OpenAI declined to generate this draft")
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
        raise DraftGeneratorOutputError("OpenAI returned no structured output")

    def generate(
        self,
        context: DraftGenerationContext,
        *,
        structural_retry: bool = False,
        user_input_override: str | None = None,
    ):

        payload = {
            "model": self._model_name,
            "store": False,
            "input": [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": self.system_instructions}],
                },
                {
                    "role": "user",
                    "content": [{
                        "type": "input_text",
                        "text": build_generation_user_input(
                            context,
                            self.input_builder,
                            structural_retry=structural_retry,
                            user_input_override=user_input_override,
                        ),
                    }],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "medical_knowledge_draft_v1",
                    "strict": True,
                    "schema": self.proposal_model.model_json_schema(),
                }
            },
        }
        output_text = self._extract_output_text(self._post(payload))
        return parse_medical_draft_output(output_text, context, self.proposal_model)

    def test_connection(self) -> bool:
        """Send one minimal, non-medical structured request without tools or persistence."""

        payload = {
            "model": self._model_name,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Return the requested connection-check object with ok set to true.",
                        }
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "service_connection_check_v1",
                    "strict": True,
                    "schema": _ConnectionCheck.model_json_schema(),
                }
            },
        }
        output_text = self._extract_output_text(self._post(payload))
        try:
            return _ConnectionCheck.model_validate(json.loads(output_text)).ok
        except (json.JSONDecodeError, ValidationError) as exc:
            raise DraftGeneratorOutputError(
                "OpenAI returned an invalid connection-check response"
            ) from exc


class OllamaMedicalKnowledgeDraftGenerator:
    """Local-only Ollama provider using the official non-streaming chat API."""

    def __init__(
        self,
        *,
        base_url: str | None,
        model: str | None,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
        system_instructions: str = SYSTEM_INSTRUCTIONS,
        input_builder: Callable[[DraftGenerationContext], str] = build_generation_input,
        proposal_model: type[BaseModel] = MedicalKnowledgeDraftProposal,
    ):
        self._base_url = base_url
        self._model_name = model
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.system_instructions = system_instructions
        self.input_builder = input_builder
        self.proposal_model = proposal_model

    @property
    def model_name(self) -> str:
        return self._model_name or ""

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _require_configuration(self) -> tuple[str, str]:
        return (
            normalize_local_ollama_base_url(self._base_url),
            _validate_local_model_name(self._model_name),
        )

    def _request(self, method: str, url: str, *, payload: dict | None = None) -> dict:
        try:
            response = self.client.request(method, url, json=payload)
        except httpx.TimeoutException as exc:
            raise DraftGeneratorTimeoutError("Local Ollama request timed out") from exc
        except httpx.RequestError as exc:
            raise DraftGeneratorUnavailableError("Local Ollama is unavailable") from exc
        if response.status_code in (408, 504):
            raise DraftGeneratorTimeoutError("Local Ollama request timed out")
        if response.status_code >= 500:
            raise DraftGeneratorUnavailableError("Local Ollama is unavailable")
        if response.status_code >= 400:
            raise DraftGeneratorOutputError("Local Ollama request failed")
        try:
            body = response.json()
        except ValueError as exc:
            raise DraftGeneratorOutputError("Local Ollama returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise DraftGeneratorOutputError("Local Ollama returned invalid JSON")
        return body

    def _ensure_model_installed(self, base_url: str, model: str) -> None:
        body = self._request("GET", f"{base_url}/api/tags")
        models = body.get("models")
        if not isinstance(models, list):
            raise DraftGeneratorOutputError("Local Ollama returned an invalid model list")
        installed_names = {
            value
            for item in models
            if isinstance(item, dict)
            for value in (item.get("name"), item.get("model"))
            if isinstance(value, str)
        }
        if model not in installed_names:
            raise OllamaModelNotInstalledError("Selected model is not installed in local Ollama")

    def _chat(self, *, schema: dict, messages: list[dict[str, str]]) -> str:
        base_url, model = self._require_configuration()
        self._ensure_model_installed(base_url, model)
        body = self._request(
            "POST",
            f"{base_url}/api/chat",
            payload={
                "model": model,
                "messages": messages,
                "stream": False,
                "format": schema,
                "options": {"temperature": 0},
            },
        )
        message = body.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise DraftGeneratorOutputError("Local Ollama returned no structured output")
        return content

    def generate(
        self,
        context: DraftGenerationContext,
        *,
        structural_retry: bool = False,
        user_input_override: str | None = None,
    ):
        output_text = self._chat(
            schema=self.proposal_model.model_json_schema(),
            messages=[
                {"role": "system", "content": self.system_instructions},
                {
                    "role": "user",
                    "content": build_generation_user_input(
                        context,
                        self.input_builder,
                        structural_retry=structural_retry,
                        user_input_override=user_input_override,
                    ),
                },
            ],
        )
        return parse_medical_draft_output(output_text, context, self.proposal_model)

    def test_connection(self) -> bool:
        output_text = self._chat(
            schema=_ConnectionCheck.model_json_schema(),
            messages=[
                {
                    "role": "user",
                    "content": "Return the requested connection-check object with ok set to true.",
                }
            ],
        )
        try:
            return _ConnectionCheck.model_validate_json(output_text).ok
        except ValidationError as exc:
            raise DraftGeneratorOutputError(
                "Local Ollama returned an invalid connection-check response"
            ) from exc


def create_medical_knowledge_draft_generator(
    *,
    provider: str | None,
    openai_api_key: str | None,
    openai_model: str | None,
    openai_timeout_seconds: float,
    ollama_base_url: str | None,
    ollama_model: str | None,
    ollama_timeout_seconds: float,
    client: httpx.Client | None = None,
    groq_api_key: str | None = None,
    groq_model: str | None = None,
    groq_timeout_seconds: float = 45.0,
    system_instructions: str = SYSTEM_INSTRUCTIONS,
    input_builder: Callable[[DraftGenerationContext], str] = build_generation_input,
    proposal_model: type[BaseModel] = MedicalKnowledgeDraftProposal,
) -> MedicalKnowledgeDraftGenerator:
    """Create exactly the selected provider. No provider fallback is permitted."""

    normalized_provider = (provider or "").strip().lower()
    if normalized_provider == "groq":
        from app.services.medical_knowledge_groq_generator import (
            GroqMedicalKnowledgeDraftGenerator,
        )

        return GroqMedicalKnowledgeDraftGenerator(
            api_key=groq_api_key,
            model=groq_model,
            timeout_seconds=groq_timeout_seconds,
            client=client,
            system_instructions=system_instructions,
            input_builder=input_builder,
            proposal_model=proposal_model,
        )
    if normalized_provider == "ollama":
        return OllamaMedicalKnowledgeDraftGenerator(
            base_url=ollama_base_url,
            model=ollama_model,
            timeout_seconds=ollama_timeout_seconds,
            client=client,
            system_instructions=system_instructions,
            input_builder=input_builder,
            proposal_model=proposal_model,
        )
    if normalized_provider == "openai":
        return OpenAIMedicalKnowledgeDraftGenerator(
            api_key=openai_api_key,
            model=openai_model,
            timeout_seconds=openai_timeout_seconds,
            client=client,
            system_instructions=system_instructions,
            input_builder=input_builder,
            proposal_model=proposal_model,
        )
    raise UnknownDraftGeneratorProviderError(
        f"Unsupported Medical Knowledge LLM provider: {normalized_provider or '<empty>'}"
    )
