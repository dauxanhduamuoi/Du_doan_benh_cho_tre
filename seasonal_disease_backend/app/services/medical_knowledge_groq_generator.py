from __future__ import annotations

from copy import deepcopy
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

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
)
from app.services.medical_knowledge_prompt import SYSTEM_INSTRUCTIONS, build_generation_input


class _GroqConnectionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True]


# Groq strict mode documents a JSON Schema subset. These Pydantic validation
# constraints are enforced again after the response and are removed only from
# the provider schema to keep constrained decoding within the documented subset.
_VALIDATION_ONLY_SCHEMA_KEYWORDS = frozenset(
    {"minLength", "maxLength", "minItems", "maxItems"}
)


def normalize_groq_strict_schema(schema: dict) -> dict:
    """Preserve schema shape/enums while removing undocumented strict keywords."""

    normalized = deepcopy(schema)

    def visit(value):
        if isinstance(value, dict):
            for keyword in _VALIDATION_ONLY_SCHEMA_KEYWORDS:
                value.pop(keyword, None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(normalized)
    return normalized


class GroqMedicalKnowledgeDraftGenerator:
    """Groq Chat Completions provider with strict structured output and no tools."""

    endpoint = "https://api.groq.com/openai/v1/chat/completions"

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
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
        )

    @property
    def model_name(self) -> str:
        return self._model_name or ""

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _require_configuration(self) -> str:
        if not self.api_key:
            raise GroqApiKeyMissingError("GROQ_API_KEY is not configured")
        if not self._model_name:
            raise GroqModelUnavailableError("GROQ_MODEL is not configured")
        return self._model_name

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
                follow_redirects=False,
            )
        except httpx.TimeoutException as exc:
            raise DraftGeneratorTimeoutError("Groq request timed out") from exc
        except httpx.RequestError as exc:
            raise DraftGeneratorUnavailableError("Groq is temporarily unavailable") from exc

        if response.status_code in (401, 403):
            raise GroqAuthenticationError("Groq authentication failed")
        if response.status_code == 404:
            raise GroqModelUnavailableError("Configured Groq model is unavailable")
        if response.status_code == 429:
            raise DraftGeneratorRateLimitError("Groq rate limit was reached")
        if response.status_code in (408, 504):
            raise DraftGeneratorTimeoutError("Groq request timed out")
        if 300 <= response.status_code < 400:
            raise DraftGeneratorUnavailableError("Groq redirect was refused")
        if response.status_code >= 500 or response.status_code == 498:
            raise DraftGeneratorUnavailableError("Groq is temporarily unavailable")
        if response.status_code >= 400:
            raise DraftGeneratorOutputError("Groq could not produce structured output")

        try:
            body = response.json()
        except ValueError as exc:
            raise DraftGeneratorOutputError("Groq returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise DraftGeneratorOutputError("Groq returned invalid JSON")
        return body

    @staticmethod
    def _extract_content(body: dict) -> str:
        choices = body.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise DraftGeneratorOutputError("Groq returned no structured output")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise DraftGeneratorOutputError("Groq returned no structured output")
        return content

    def _chat(
        self,
        *,
        schema_name: str,
        schema: dict,
        messages: list[dict[str, str]],
    ) -> str:
        payload = {
            "model": self._model_name,
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "citation_options": "disabled",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": normalize_groq_strict_schema(schema),
                },
            },
        }
        return self._extract_content(self._post(payload))

    def generate(self, context: DraftGenerationContext) -> MedicalKnowledgeDraftProposal:
        output_text = self._chat(
            schema_name="medical_knowledge_draft_v1",
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
                "Groq returned an invalid structured draft"
            ) from exc

    def test_connection(self) -> bool:
        output_text = self._chat(
            schema_name="service_connection_check_v1",
            schema=_GroqConnectionCheck.model_json_schema(),
            messages=[
                {
                    "role": "user",
                    "content": "Return the requested connection-check object with ok set to true.",
                }
            ],
        )
        try:
            return _GroqConnectionCheck.model_validate_json(output_text).ok
        except ValidationError as exc:
            raise DraftGeneratorOutputError(
                "Groq returned an invalid connection-check response"
            ) from exc
