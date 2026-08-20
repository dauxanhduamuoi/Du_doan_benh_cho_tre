from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol
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
    pass


class DraftGeneratorOutputError(DraftGeneratorError):
    pass


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

    def generate(self, context: DraftGenerationContext) -> MedicalKnowledgeDraftProposal:
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
    ):
        self.api_key = api_key
        self._model_name = model
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_seconds)

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

    def generate(self, context: DraftGenerationContext) -> MedicalKnowledgeDraftProposal:

        payload = {
            "model": self._model_name,
            "store": False,
            "input": [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": SYSTEM_INSTRUCTIONS}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": build_generation_input(context)}],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "medical_knowledge_draft_v1",
                    "strict": True,
                    "schema": MedicalKnowledgeDraftProposal.model_json_schema(),
                }
            },
        }
        output_text = self._extract_output_text(self._post(payload))
        try:
            return MedicalKnowledgeDraftProposal.model_validate(json.loads(output_text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise DraftGeneratorOutputError("OpenAI returned an invalid structured draft") from exc

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
    ):
        self._base_url = base_url
        self._model_name = model
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_seconds)

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

    def generate(self, context: DraftGenerationContext) -> MedicalKnowledgeDraftProposal:
        output_text = self._chat(
            schema=MedicalKnowledgeDraftProposal.model_json_schema(),
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": build_generation_input(context)},
            ],
        )
        try:
            return MedicalKnowledgeDraftProposal.model_validate_json(output_text)
        except ValidationError as exc:
            raise DraftGeneratorOutputError(
                "Local Ollama returned an invalid structured draft"
            ) from exc

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
        )
    if normalized_provider == "ollama":
        return OllamaMedicalKnowledgeDraftGenerator(
            base_url=ollama_base_url,
            model=ollama_model,
            timeout_seconds=ollama_timeout_seconds,
            client=client,
        )
    if normalized_provider == "openai":
        return OpenAIMedicalKnowledgeDraftGenerator(
            api_key=openai_api_key,
            model=openai_model,
            timeout_seconds=openai_timeout_seconds,
            client=client,
        )
    raise UnknownDraftGeneratorProviderError(
        f"Unsupported Medical Knowledge LLM provider: {normalized_provider or '<empty>'}"
    )
