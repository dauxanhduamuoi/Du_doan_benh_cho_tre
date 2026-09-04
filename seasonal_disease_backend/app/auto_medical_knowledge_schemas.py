from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.medical_knowledge_factor_schemas import GenericFactorSelector
from app.medical_knowledge_draft_schemas import (
    EvidenceLevel,
    EvidenceScope,
    SourceAssessment,
)
from app.config import MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES


AutoDisplayMode = Literal["REVIEWED_ONLY", "REVIEWED_WITH_AUTO_FALLBACK"]
AutoJobStatus = Literal[
    "QUEUED", "SEARCHING", "GENERATING", "READY", "INSUFFICIENT", "FAILED", "CANCELLED"
]
NumericClaimKind = Literal[
    "COUNT",
    "PERCENTAGE",
    "RATE",
    "RATIO_OR_EFFECT",
    "MEASUREMENT",
    "AGE",
    "DURATION",
    "TEMPORAL_PERIOD",
    "OTHER_NUMERIC",
]
MAX_NUMERIC_CLAIMS_PER_AUTO_REVISION = 10


class AutoNumericClaimProposal(BaseModel):
    """Internal-only declaration for one Parent-facing medical number."""

    model_config = ConfigDict(extra="forbid")

    value_text: str = Field(min_length=1, max_length=100)
    claim_kind: NumericClaimKind
    unit: str | None = Field(default=None, max_length=100)
    source_id: int = Field(gt=0)
    supporting_text: str = Field(min_length=1, max_length=1000)

    @field_validator("value_text", "unit", "supporting_text", mode="before")
    @classmethod
    def normalize_claim_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class AutoMedicalKnowledgeDraftProposal(BaseModel):
    """Auto-only output contract with a safe empty explanation path.

    Reviewed generation keeps its stricter, existing proposal schema. Auto may
    leave prose empty only when it explicitly reports insufficient or
    conflicting evidence; source-by-source assessment remains mandatory.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_level: EvidenceLevel
    evidence_scope: EvidenceScope
    short_explanation_vi: str | None = Field(max_length=2000)
    detailed_explanation_vi: str | None = Field(max_length=10000)
    limitations_vi: str | None = Field(max_length=5000)
    source_assessments: list[SourceAssessment] = Field(
        min_length=1,
        max_length=MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES,
    )
    numeric_claims: list[AutoNumericClaimProposal] = Field(
        max_length=MAX_NUMERIC_CLAIMS_PER_AUTO_REVISION,
    )

    @field_validator(
        "short_explanation_vi", "detailed_explanation_vi", "limitations_vi", mode="before"
    )
    @classmethod
    def normalize_optional_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("source_assessments")
    @classmethod
    def unique_assessment_sources(cls, values: list[SourceAssessment]):
        ids = [value.source_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("source_assessments must not contain duplicate source IDs")
        return values

    @model_validator(mode="after")
    def validate_auto_explanation_path(self):
        if self.evidence_level in {"SUPPORTED", "LIMITED_OR_INDIRECT"} and not all(
            (self.short_explanation_vi, self.detailed_explanation_vi, self.limitations_vi)
        ):
            raise ValueError("Displayable Auto evidence requires all explanation fields")
        if self.evidence_scope == "WHOLE_GROUP" and not any(
            item.relevance == "DIRECT" for item in self.source_assessments
        ):
            raise ValueError("WHOLE_GROUP requires at least one DIRECT source assessment")
        if self.evidence_level in {"INSUFFICIENT", "CONFLICTING"} and self.numeric_claims:
            raise ValueError("INSUFFICIENT or CONFLICTING output must not declare numeric claims")
        return self


class AutoMedicalKnowledgeSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    display_mode: AutoDisplayMode
    auto_visible_default: bool


class AutoMedicalKnowledgeSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    display_mode: AutoDisplayMode | None = None
    auto_visible_default: bool | None = None


class AutoProviderCooldownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    active: bool
    cooldown_until: datetime
    reason: str
    updated_at: datetime


class AutoDiscoverySourceDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pmid: str
    title: str
    decision: Literal["SELECTED", "SKIPPED"]
    reason_code: str
    stage: str | None = None


class AutoDiscoveryDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int
    queries_run: int
    raw_results: int
    deduplicated: int
    disease_relevant: int
    factor_relevant: int
    pediatric_relevant: int
    usable_evidence: int
    selected_for_generation: int
    insufficient_reason: str | None = None
    queries: list[str]
    sources: list[AutoDiscoverySourceDiagnostic]
    pipeline_version: str | None = None
    generation_calls: int | None = None
    max_generation_calls: int | None = None
    contract_repair_attempted: bool | None = None
    contract_repair_reason: str | None = None
    contract_repair_calls: int | None = None
    contract_repair_result: str | None = None
    failure: "AutoFailureDiagnosticResponse | None" = None


class AutoFailureDiagnosticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    field: str | None = None
    source_id: int | None = None
    numeric_value: str | None = None
    safe_detail: str
    provider_error_class: str | None = None
    provider: str | None = None
    http_status: int | None = None
    provider_stage: str | None = None
    finish_reason: str | None = None
    choices_count: int | None = None
    message_present: bool | None = None
    content_present: bool | None = None
    content_length: int | None = None
    refusal_present: bool | None = None
    incomplete: bool | None = None
    structured_field_detected: str | None = None
    call_purpose: str | None = None
    generation_call_number: int | None = None
    response_format_type: str | None = None
    provider_validation_stage: str | None = None
    provider_error_category: str | None = None
    provider_error_type: str | None = None
    request_body_bytes: int | None = None
    user_content_chars: int | None = None
    message_count: int | None = None
    generation_calls: int | None = None
    max_generation_calls: int | None = None
    contract_repair_attempted: bool | None = None
    contract_repair_reason: str | None = None
    contract_repair_calls: int | None = None
    contract_repair_result: str | None = None


class AutoAttemptHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int
    status: Literal["FAILED", "UNKNOWN"]
    failure_code: str | None = None
    legacy: bool
    pipeline_version: str | None = None
    created_at: datetime


class AutoMedicalKnowledgeJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    topic_id: int
    disease_group_id: str
    factor_type: str
    factor_key: str
    factor_value: str | None
    status: AutoJobStatus
    attempt_count: int
    trigger_type: Literal["PARENT", "ADMIN"]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    next_retry_at: datetime | None
    last_error_code: str | None
    is_current_attempt: bool
    legacy: bool
    pipeline_version: str | None = None
    history: list[AutoAttemptHistoryResponse] = Field(default_factory=list)
    diagnostics: AutoDiscoveryDiagnosticsResponse | None = None


class AutoMedicalKnowledgeSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: int
    title: str
    journal: str | None
    publication_year: int | None
    pmid: str | None
    doi: str | None
    url: str | None
    trust_class: str
    content_kind: str
    source_role: str
    relevance_note: str
    population_relevance: str
    population_note: str


class AutoMedicalKnowledgeRevisionResponse(GenericFactorSelector):
    model_config = ConfigDict(extra="forbid")

    id: int
    topic_id: int
    disease_group_id: str
    revision_number: int
    generation_status: Literal["READY", "INSUFFICIENT"]
    generation_mode: Literal["AI_FULL", "SAFE_FALLBACK"] | None = None
    fallback_reason_code: Literal[
        "CONTRACT_REPAIR_EXHAUSTED",
        "REPAIR_PROVIDER_FAILURE",
        "REPAIR_STRUCTURAL_FAILURE",
    ] | None = None
    evidence_level: str
    evidence_scope: str | None
    short_explanation_vi: str | None
    detailed_explanation_vi: str | None
    limitations_vi: str | None
    is_visible: bool
    llm_model: str | None
    prompt_version: str
    generated_at: datetime
    source_retrieved_at: datetime | None
    sources: list[AutoMedicalKnowledgeSourceResponse]
    diagnostics: AutoDiscoveryDiagnosticsResponse | None = None


class AutoMedicalKnowledgeOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: AutoMedicalKnowledgeSettingsResponse
    provider_cooldown: AutoProviderCooldownResponse | None = None
    jobs: list[AutoMedicalKnowledgeJobResponse]
    revisions: list[AutoMedicalKnowledgeRevisionResponse]


class AutoVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_visible: bool


class AutoEnqueueRequest(GenericFactorSelector):
    model_config = ConfigDict(extra="forbid")

    disease_group_id: str = Field(min_length=1, max_length=100)


class AutoActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    job_id: int | None = None
    revision_id: int | None = None
    message: str
