from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
from typing import Callable, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

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
    GroqApiKeyMissingError,
    GroqAuthenticationError,
    GroqModelUnavailableError,
    build_generation_user_input,
    parse_medical_draft_output,
)
from app.services.medical_knowledge_prompt import SYSTEM_INSTRUCTIONS, build_generation_input


class _GroqConnectionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True]


# Groq strict mode documents a JSON Schema subset. These constraints/defaults
# are enforced again by the internal Pydantic model after the response and are
# removed only from the provider transport schema.
_VALIDATION_ONLY_SCHEMA_KEYWORDS = frozenset(
    {
        "default",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "multipleOf",
        "pattern",
        "uniqueItems",
    }
)
_SAFE_PROVIDER_ERROR_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,100}")


def parse_retry_after_seconds(
    value: str | None, *, now: datetime | None = None
) -> float | None:
    """Parse RFC Retry-After seconds or HTTP-date; reject malformed values."""

    if value is None or not value.strip():
        return None
    candidate = value.strip()
    try:
        seconds = float(candidate)
    except ValueError:
        seconds = None
    if seconds is not None:
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    try:
        retry_at = parsedate_to_datetime(candidate)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at.astimezone(timezone.utc) - reference.astimezone(timezone.utc)).total_seconds())


def normalize_groq_strict_schema(schema: dict) -> dict:
    """Build a Groq-strict transport schema without changing the core model."""

    normalized = deepcopy(schema)

    def visit(value):
        if isinstance(value, dict):
            for keyword in _VALIDATION_ONLY_SCHEMA_KEYWORDS:
                value.pop(keyword, None)
            properties = value.get("properties")
            if isinstance(properties, dict):
                # Strict mode requires every property at every object level to
                # be required. Nullable internal fields remain nullable through
                # their string/null union, but Groq must emit the key.
                value["required"] = list(properties)
                value["additionalProperties"] = False
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(normalized)
    return normalized


def build_groq_chat_completion_payload(
    *,
    model: str | None,
    schema_name: str,
    schema: dict,
    messages: list[dict[str, str]],
) -> dict:
    """Build the one production payload shape used by initial and repair calls."""

    return {
        "model": model,
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


def _safe_provider_error_metadata(response: httpx.Response) -> dict:
    """Extract only bounded Groq error identifiers, never body text/details."""

    try:
        body = response.json()
    except ValueError:
        return {}
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return {}
    result = {}
    for source_key, target_key in (
        ("code", "provider_error_category"),
        ("type", "provider_error_type"),
    ):
        value = error.get(source_key)
        if isinstance(value, str) and _SAFE_PROVIDER_ERROR_TOKEN.fullmatch(value):
            result[target_key] = value
    return result


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
        system_instructions: str = SYSTEM_INSTRUCTIONS,
        input_builder: Callable[[DraftGenerationContext], str] = build_generation_input,
        proposal_model: type[BaseModel] = MedicalKnowledgeDraftProposal,
    ):
        self.api_key = api_key
        self._model_name = model
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        self.system_instructions = system_instructions
        self.input_builder = input_builder
        self.proposal_model = proposal_model

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

    @staticmethod
    def _diagnostics(
        *,
        http_status: int,
        body: dict | None = None,
        provider_stage: str,
        finish_reason: str | None = None,
        message: dict | None = None,
        request_diagnostics: dict | None = None,
    ) -> dict:
        choices = body.get("choices") if isinstance(body, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        content_is_text = isinstance(content, str)
        diagnostics = {
            "provider": "groq",
            "http_status": http_status,
            "provider_stage": provider_stage,
            "finish_reason": finish_reason,
            "choices_count": len(choices) if isinstance(choices, list) else None,
            "message_present": isinstance(message, dict),
            "content_present": content_is_text and bool(content.strip()),
            "content_length": len(content) if content_is_text else 0,
            "refusal_present": False,
            "incomplete": finish_reason not in (None, "stop"),
            "structured_field_detected": (
                "message.content" if content_is_text and bool(content.strip()) else None
            ),
        }
        if isinstance(request_diagnostics, dict):
            diagnostics.update(request_diagnostics)
        return diagnostics

    def _post(
        self, payload: dict, *, request_diagnostics: dict | None = None
    ) -> tuple[dict, int]:
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
            raise DraftGeneratorRateLimitError(
                "Groq rate limit was reached",
                retry_after_seconds=parse_retry_after_seconds(
                    response.headers.get("Retry-After")
                ),
            )
        if response.status_code in (408, 504):
            raise DraftGeneratorTimeoutError("Groq request timed out")
        if 300 <= response.status_code < 400:
            raise DraftGeneratorUnavailableError("Groq redirect was refused")
        if response.status_code >= 500 or response.status_code == 498:
            raise DraftGeneratorUnavailableError("Groq is temporarily unavailable")
        if response.status_code >= 400:
            rejection_diagnostics = {
                **(request_diagnostics or {}),
                **_safe_provider_error_metadata(response),
            }
            raise DraftGeneratorProviderRequestRejectedError(
                "Groq rejected the structured-output request.",
                diagnostics=self._diagnostics(
                    http_status=response.status_code,
                    provider_stage="http_request_rejected",
                    request_diagnostics=rejection_diagnostics,
                ),
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise DraftGeneratorProviderEnvelopeError(
                "Groq returned a non-JSON response envelope.",
                diagnostics=self._diagnostics(
                    http_status=response.status_code,
                    provider_stage="response_body_not_json",
                ),
            ) from exc
        if not isinstance(body, dict):
            raise DraftGeneratorProviderEnvelopeError(
                "Groq returned an invalid response envelope.",
                diagnostics=self._diagnostics(
                    http_status=response.status_code,
                    provider_stage="response_body_not_object",
                ),
            )
        return body, response.status_code

    @staticmethod
    def _extract_content(body: dict, *, http_status: int = 200) -> str:
        choices = body.get("choices")
        if not isinstance(choices, list):
            raise DraftGeneratorProviderEnvelopeError(
                "Groq response is missing the choices array.",
                diagnostics=GroqMedicalKnowledgeDraftGenerator._diagnostics(
                    http_status=http_status,
                    body=body,
                    provider_stage="choices_missing",
                ),
            )
        if len(choices) != 1:
            raise DraftGeneratorProviderEnvelopeError(
                "Groq response does not contain exactly one usable choice.",
                diagnostics=GroqMedicalKnowledgeDraftGenerator._diagnostics(
                    http_status=http_status,
                    body=body,
                    provider_stage="choices_empty" if not choices else "choices_multiple",
                ),
            )
        choice = choices[0]
        if not isinstance(choice, dict):
            raise DraftGeneratorProviderEnvelopeError(
                "Groq returned an invalid choice envelope.",
                diagnostics=GroqMedicalKnowledgeDraftGenerator._diagnostics(
                    http_status=http_status,
                    body=body,
                    provider_stage="choice_invalid",
                ),
            )
        message = choice.get("message")
        finish_reason = choice.get("finish_reason")
        if not isinstance(message, dict):
            raise DraftGeneratorProviderEnvelopeError(
                "Groq response choice is missing its message.",
                diagnostics=GroqMedicalKnowledgeDraftGenerator._diagnostics(
                    http_status=http_status,
                    body=body,
                    provider_stage="message_missing",
                    finish_reason=finish_reason if isinstance(finish_reason, str) else None,
                ),
            )
        if not isinstance(finish_reason, str):
            raise DraftGeneratorProviderEnvelopeError(
                "Groq response choice is missing its finish reason.",
                diagnostics=GroqMedicalKnowledgeDraftGenerator._diagnostics(
                    http_status=http_status,
                    body=body,
                    provider_stage="finish_reason_missing",
                    message=message,
                ),
            )
        if (
            finish_reason != "stop"
            or message.get("tool_calls")
            or message.get("function_call")
        ):
            raise DraftGeneratorProviderIncompleteError(
                "Groq did not complete a final structured response.",
                diagnostics=GroqMedicalKnowledgeDraftGenerator._diagnostics(
                    http_status=http_status,
                    body=body,
                    provider_stage="generation_incomplete",
                    finish_reason=finish_reason,
                    message=message,
                ),
            )
        content = message.get("content") if isinstance(message, dict) else None
        if content is None or (isinstance(content, str) and not content.strip()):
            raise DraftGeneratorProviderContentEmptyError(
                "Groq completed without structured response content.",
                diagnostics=GroqMedicalKnowledgeDraftGenerator._diagnostics(
                    http_status=http_status,
                    body=body,
                    provider_stage="content_empty",
                    finish_reason=finish_reason,
                    message=message,
                ),
            )
        if not isinstance(content, str):
            raise DraftGeneratorProviderEnvelopeError(
                "Groq response content has an unsupported type.",
                diagnostics=GroqMedicalKnowledgeDraftGenerator._diagnostics(
                    http_status=http_status,
                    body=body,
                    provider_stage="content_type_invalid",
                    finish_reason=finish_reason,
                    message=message,
                ),
            )
        return content

    def _chat(
        self,
        *,
        schema_name: str,
        schema: dict,
        messages: list[dict[str, str]],
    ) -> str:
        payload = build_groq_chat_completion_payload(
            model=self._model_name,
            schema_name=schema_name,
            schema=schema,
            messages=messages,
        )
        request_body_bytes = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        user_content_chars = sum(
            len(message["content"])
            for message in messages
            if message.get("role") == "user"
            and isinstance(message.get("content"), str)
        )
        body, http_status = self._post(
            payload,
            request_diagnostics={
                "response_format_type": "json_schema",
                "provider_validation_stage": "provider_http_request",
                "request_body_bytes": request_body_bytes,
                "user_content_chars": user_content_chars,
                "message_count": len(messages),
            },
        )
        return self._extract_content(body, http_status=http_status)

    def generate(
        self,
        context: DraftGenerationContext,
        *,
        structural_retry: bool = False,
        user_input_override: str | None = None,
    ):
        output_text = self._chat(
            schema_name="medical_knowledge_draft_v1",
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
