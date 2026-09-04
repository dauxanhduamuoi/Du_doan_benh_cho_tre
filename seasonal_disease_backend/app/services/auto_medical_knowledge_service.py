from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auto_medical_knowledge_schemas import (
    AutoAttemptHistoryResponse,
    AutoFailureDiagnosticResponse,
    AutoDiscoveryDiagnosticsResponse,
    AutoDiscoverySourceDiagnostic,
    AutoMedicalKnowledgeJobResponse,
    AutoMedicalKnowledgeOverviewResponse,
    AutoProviderCooldownResponse,
    AutoMedicalKnowledgeRevisionResponse,
    AutoMedicalKnowledgeSettingsResponse,
    AutoMedicalKnowledgeSourceResponse,
    AutoMedicalKnowledgeDraftProposal,
)
from app.medical_knowledge_draft_schemas import (
    DraftGenerationContext,
    DraftSourceInput,
    SourceAssessment,
)
from app.medical_knowledge_factors import normalize_factor
from app.medical_knowledge_models import AutoMedicalKnowledgeRevision
from app.models import DiseaseCode
from app.medical_knowledge_schemas import (
    MedicalEvidenceContentCreate,
    MedicalEvidenceSourceCreate,
)
from app.repositories.auto_medical_knowledge_repository import (
    AutoMedicalKnowledgeRepository,
)
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.services.auto_evidence_discovery import (
    AutoEvidenceEnrichmentError,
    AutoEvidenceSearchError,
    AutoDiscoveryResult,
    AutoEvidenceCandidate,
    AutoEvidenceDiscoveryProvider,
)
from app.services.auto_evidence_relevance import build_disease_aliases
from app.services.auto_medical_numeric_validation import (
    NumericClaimContractViolation,
    NumericEvidenceSnapshot,
    NumericMetadata,
    VerifiedNumericClaim,
    validate_numeric_claim_contract,
)
from app.services.auto_medical_knowledge_safe_fallback import (
    AutoSafeFallbackRenderer,
    SafeFallbackEligibilitySnapshot,
    evaluate_safe_fallback_eligibility,
    is_safe_fallback_trigger,
    safe_fallback_reason_code,
)
from app.services.medical_knowledge_draft_generator import (
    DraftGeneratorConfigurationError,
    DraftGeneratorOutputError,
    DraftGeneratorProviderResponseError,
    DraftGeneratorRateLimitError,
    DraftGeneratorStructuredOutputError,
    DraftGeneratorUnavailableError,
    MedicalKnowledgeDraftGenerator,
)
from app.services.medical_knowledge_draft_service import load_deployed_disease_contexts
from app.config import (
    MEDICAL_KNOWLEDGE_LLM_PROVIDER,
    WEATHER_AI_V3_DISEASE_CATALOG,
    WEATHER_AI_V3_MODEL_MANIFEST,
)
from app.services.medical_knowledge_population_policy import (
    PARENT_DISPLAYABLE_EVIDENCE,
    has_pediatric_direct_support,
)


AUTO_PARENT_WARNING = "Giải thích tự động bởi AI — chưa được nhân viên y tế kiểm duyệt."
AUTO_SAFE_FALLBACK_PARENT_WARNING = (
    f"{AUTO_PARENT_WARNING} Nội dung tự động rút gọn từ các nguồn y khoa đã tìm được."
)

AUTO_PIPELINE_VERSION = "auto_medical_knowledge_v3_safe_fallback"
MAX_AUTO_CONTRACT_REPAIR_ATTEMPTS = 1
MAX_AUTO_GENERATION_CALLS = 2
AUTO_OUTPUT_REPAIRABLE_FAILURE_CODES = frozenset(
    {
        "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH",
        "AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED",
        "AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED",
        "AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE",
    }
)
_AUTO_CAUSAL_CLAIMS = (
    "gây ra", "làm phát sinh", "là nguyên nhân", "nguyên nhân trực tiếp"
)
_AUTO_PERSONALIZED_CLAIMS = (
    "con bạn", "trẻ của bạn", "bé nhà bạn", "con của bạn"
)
_AUTO_CERTAINTY_CLAIMS = ("chắc chắn", "sẽ mắc", "chắc chắn mắc")
_AUTO_MECHANISM_EVIDENCE_TERMS = {
    "miễn dịch": ("immun",),
    "hormone": ("hormon", "endocrin"),
    "di truyền": ("genetic", "genomic", "heredit"),
    "vệ sinh": ("hygiene", "sanitation"),
    "ăn uống": ("diet", "nutrition", "feeding"),
}
_AUTO_SOURCE_CLAIM_TERMS = {
    "thử nghiệm ngẫu nhiên": ("randomized", "randomised"),
    "tổng quan hệ thống": ("systematic review",),
    "phân tích gộp": ("meta-analysis", "meta analysis"),
}


class AutoMedicalKnowledgeError(RuntimeError):
    pass


class AutoMedicalKnowledgeNotFoundError(AutoMedicalKnowledgeError):
    pass


class AutoMedicalKnowledgeConflictError(AutoMedicalKnowledgeError):
    pass


class AutoMedicalKnowledgeValidationError(AutoMedicalKnowledgeError):
    pass


class AutoOutputSafetyError(AutoMedicalKnowledgeValidationError):
    """Provider-independent semantic rejection with persistable safe detail."""

    def __init__(
        self,
        code: str,
        safe_detail: str,
        *,
        field: str | None = None,
        source_id: int | None = None,
        numeric_value: str | None = None,
    ):
        super().__init__(safe_detail)
        self.code = code
        self.safe_detail = safe_detail
        self.field = field
        self.source_id = source_id
        self.numeric_value = numeric_value


def is_auto_output_repairable(failure_code: str) -> bool:
    """Return the single authoritative Auto contract-repair policy decision."""

    return failure_code in AUTO_OUTPUT_REPAIRABLE_FAILURE_CODES


@dataclass
class AutoGenerationCallBudget:
    """One shared budget for initial generation, structural retry, and repair."""

    max_calls: int = MAX_AUTO_GENERATION_CALLS
    calls: int = 0

    @property
    def remaining(self) -> int:
        return self.max_calls - self.calls

    def call(self, invoke):
        if self.remaining <= 0:
            raise AutoMedicalKnowledgeValidationError(
                "Auto generation call budget is exhausted"
            )
        self.calls += 1
        return invoke()


@dataclass
class AutoContractRepairTrace:
    attempted: bool = False
    reason: str | None = None
    calls: int = 0
    result: str = "NOT_REQUIRED"


@dataclass(frozen=True)
class AutoProposalValidationResult:
    proposal: AutoMedicalKnowledgeDraftProposal
    verified_numeric_claims: tuple[VerifiedNumericClaim, ...]
    insufficient_reason: str | None
    generation_mode: str = "AI_FULL"
    fallback_reason_code: str | None = None


def _attach_contract_repair_trace(
    exc: Exception,
    trace: AutoContractRepairTrace,
    budget: AutoGenerationCallBudget,
) -> Exception:
    exc.contract_repair_diagnostics = {
        "contract_repair_attempted": trace.attempted,
        "contract_repair_reason": trace.reason,
        "contract_repair_calls": trace.calls,
        "contract_repair_result": trace.result,
        "generation_calls": budget.calls,
        "max_generation_calls": budget.max_calls,
    }
    return exc


def _attach_generation_call_context(
    exc: Exception,
    *,
    call_purpose: str,
    generation_call_number: int,
) -> Exception:
    """Add orchestration-owned, non-content diagnostics to a provider error."""

    diagnostics = getattr(exc, "provider_diagnostics", {})
    safe_diagnostics = dict(diagnostics) if isinstance(diagnostics, dict) else {}
    safe_diagnostics.update(
        {
            "call_purpose": call_purpose,
            "generation_call_number": generation_call_number,
        }
    )
    exc.provider_diagnostics = safe_diagnostics
    return exc


_INSUFFICIENT_MESSAGES = {
    "NO_SEARCH_RESULTS": "PubMed chưa trả về kết quả cho các truy vấn có giới hạn đã chạy.",
    "NO_DISEASE_RELEVANT_SOURCE": "Chưa tìm được nguồn đủ liên quan đến đúng nhóm bệnh.",
    "NO_FACTOR_RELEVANT_SOURCE": "Chưa tìm được nguồn đánh giá trực tiếp yếu tố đã chọn.",
    "NO_PEDIATRIC_RELEVANT_SOURCE": "Chưa tìm được nguồn có phạm vi trẻ em phù hợp.",
    "NO_USABLE_EVIDENCE": "Các kết quả phù hợp chưa có nội dung bằng chứng mà hệ thống có thể đọc.",
    "NO_DIRECT_SUPPORT": "Các nguồn được đánh giá chưa hỗ trợ trực tiếp cho chủ đề.",
    "CONFLICTING_EVIDENCE": "Các nguồn được chọn cho kết quả không nhất quán.",
}


def classify_auto_failure(exc: Exception, *, new_pipeline: bool = False) -> str:
    if isinstance(exc, AutoEvidenceSearchError):
        return "PUBMED_SEARCH_FAILED"
    if isinstance(exc, AutoEvidenceEnrichmentError):
        return "PMC_ENRICHMENT_FAILED"
    if isinstance(exc, DraftGeneratorStructuredOutputError):
        return exc.code
    if isinstance(exc, DraftGeneratorProviderResponseError):
        return exc.code
    if isinstance(exc, DraftGeneratorRateLimitError):
        return "LLM_RATE_LIMITED"
    if isinstance(exc, DraftGeneratorOutputError):
        # Historical providers raised one untyped output exception for several
        # envelope failures. Keep that code readable for stored legacy rows,
        # while every newly processed attempt receives a stable, non-guessed
        # provider-response classification.
        return (
            "AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID"
            if new_pipeline
            else "LLM_INVALID_RESPONSE"
        )
    if isinstance(exc, (DraftGeneratorUnavailableError, DraftGeneratorConfigurationError)):
        return "LLM_PROVIDER_FAILED"
    if isinstance(exc, AutoOutputSafetyError):
        return exc.code
    if isinstance(exc, AutoMedicalKnowledgeValidationError):
        return "AUTO_OUTPUT_VALIDATION_FAILED"
    if isinstance(exc, SQLAlchemyError):
        return "PERSISTENCE_FAILED"
    return "UNKNOWN_INTERNAL_ERROR"


def _safe_failure_detail(exc: Exception, code: str) -> dict:
    detail = {
        "code": code,
        "field": getattr(exc, "field", None),
        "source_id": getattr(exc, "source_id", None),
        "numeric_value": getattr(exc, "numeric_value", None),
        "safe_detail": getattr(exc, "safe_detail", "The pipeline rejected this output safely."),
        "provider_error_class": type(exc).__name__,
    }
    provider_diagnostics = getattr(exc, "provider_diagnostics", {})
    if isinstance(provider_diagnostics, dict):
        for key in (
            "provider",
            "http_status",
            "provider_stage",
            "finish_reason",
            "choices_count",
            "message_present",
            "content_present",
            "content_length",
            "refusal_present",
            "incomplete",
            "structured_field_detected",
            "call_purpose",
            "generation_call_number",
            "response_format_type",
            "provider_validation_stage",
            "provider_error_category",
            "provider_error_type",
            "request_body_bytes",
            "user_content_chars",
            "message_count",
        ):
            value = provider_diagnostics.get(key)
            if value is not None:
                detail[key] = value
    repair_diagnostics = getattr(exc, "contract_repair_diagnostics", {})
    if isinstance(repair_diagnostics, dict):
        for key in (
            "contract_repair_attempted",
            "contract_repair_reason",
            "contract_repair_calls",
            "contract_repair_result",
            "generation_calls",
            "max_generation_calls",
        ):
            value = repair_diagnostics.get(key)
            if value is not None:
                detail[key] = value
    return {key: value for key, value in detail.items() if value is not None}


def validate_auto_proposal_claims(
    proposal: AutoMedicalKnowledgeDraftProposal,
    selected,
    *,
    allowed_context_text: str = "",
    metadata_disease_group_ids: tuple[str, ...] = (),
) -> tuple[VerifiedNumericClaim, ...]:
    """Reject deterministic high-risk claims that cannot be grounded in evidence."""
    fields = {
        "short_explanation_vi": proposal.short_explanation_vi or "",
        "detailed_explanation_vi": proposal.detailed_explanation_vi or "",
        "limitations_vi": proposal.limitations_vi or "",
    }
    fields.update(
        {
            f"source_assessments.{index}.note_vi": assessment.note_vi
            for index, assessment in enumerate(proposal.source_assessments)
        }
    )
    fields.update(
        {
            f"source_assessments.{index}.population_note": assessment.population_note
            for index, assessment in enumerate(proposal.source_assessments)
        }
    )
    evidence = " ".join(item[2].evidence_text for item in selected).lower()
    for field, text in fields.items():
        normalized = text.lower()
        if any(phrase in normalized for phrase in _AUTO_PERSONALIZED_CLAIMS):
            raise AutoOutputSafetyError(
                "AUTO_OUTPUT_PERSONALIZED_LANGUAGE",
                "Generated text addresses or diagnoses an individual child.",
                field=field,
            )
        if any(phrase in normalized for phrase in _AUTO_CAUSAL_CLAIMS):
            raise AutoOutputSafetyError(
                "AUTO_OUTPUT_CAUSAL_OVERCLAIM",
                "Generated text makes a causal claim not supported by the selected evidence policy.",
                field=field,
            )
        if any(phrase in normalized for phrase in _AUTO_CERTAINTY_CLAIMS):
            raise AutoOutputSafetyError(
                "AUTO_OUTPUT_EVIDENCE_LEVEL_INCONSISTENT",
                "Generated certainty is inconsistent with the evidence synthesis policy.",
                field=field,
            )
        for claim, support_terms in _AUTO_MECHANISM_EVIDENCE_TERMS.items():
            if claim in normalized and not any(term in evidence for term in support_terms):
                raise AutoOutputSafetyError(
                    "AUTO_OUTPUT_UNSUPPORTED_MECHANISM",
                    "Generated text contains a mechanism absent from selected evidence.",
                    field=field,
                )

    if proposal.evidence_level in {"SUPPORTED", "LIMITED_OR_INDIRECT"} and all(
        item.relevance == "NOT_SUPPORTIVE" for item in proposal.source_assessments
    ):
        raise AutoOutputSafetyError(
            "AUTO_OUTPUT_EVIDENCE_LEVEL_INCONSISTENT",
            "Evidence level is inconsistent with all source assessments.",
            field="evidence_level",
        )
    if proposal.evidence_level == "SUPPORTED" and not any(
        item.relevance == "DIRECT" for item in proposal.source_assessments
    ):
        raise AutoOutputSafetyError(
            "AUTO_OUTPUT_EVIDENCE_LEVEL_INCONSISTENT",
            "SUPPORTED requires at least one directly supportive source.",
            field="evidence_level",
        )

    evidence_by_source = {item[0].id: item[2].evidence_text.lower() for item in selected}
    pediatric_terms = (
        "pediatric", "paediatric", "child", "infant", "adolesc", "trẻ em", "nhi khoa", "thiếu nhi"
    )
    for assessment in proposal.source_assessments:
        source_evidence = evidence_by_source.get(assessment.source_id, "")
        if (
            assessment.population_relevance == "PEDIATRIC_DIRECT"
            and not any(
                term in source_evidence for term in pediatric_terms
            )
        ):
            raise AutoOutputSafetyError(
                "AUTO_OUTPUT_PEDIATRIC_CLAIM_INVALID",
                "A source was labeled pediatric-direct without pediatric evidence text.",
                field="source_assessments.population_relevance",
                source_id=assessment.source_id,
            )
        normalized_note = assessment.note_vi.lower()
        for claim, support_terms in _AUTO_SOURCE_CLAIM_TERMS.items():
            if claim in normalized_note and not any(
                term in source_evidence for term in support_terms
            ):
                raise AutoOutputSafetyError(
                    "AUTO_OUTPUT_UNSUPPORTED_SOURCE_CLAIM",
                    "A source assessment attributes a study design absent from that source.",
                    field="source_assessments.note_vi",
                    source_id=assessment.source_id,
                )

    metadata = NumericMetadata(
        pmids=tuple(item[2].pmid for item in selected if item[2].pmid),
        publication_years=tuple(
            item[2].publication_year
            for item in selected
            if item[2].publication_year is not None
        ),
        source_ids=tuple(item[0].id for item in selected),
        dois=tuple(item[2].doi for item in selected if item[2].doi),
        disease_group_ids=metadata_disease_group_ids,
    )
    parent_fields = {
        "short_explanation_vi": proposal.short_explanation_vi or "",
        "detailed_explanation_vi": proposal.detailed_explanation_vi or "",
        "limitations_vi": proposal.limitations_vi or "",
    }
    try:
        return validate_numeric_claim_contract(
            parent_fields,
            proposal.numeric_claims,
            (
                NumericEvidenceSnapshot(
                    source_id=item[0].id,
                    evidence_content_id=item[1].id,
                    evidence_text=item[2].evidence_text,
                )
                for item in selected
            ),
            context_text=allowed_context_text,
            metadata=metadata,
        )
    except NumericClaimContractViolation as exc:
        raise AutoOutputSafetyError(
            exc.code,
            exc.safe_detail,
            field=exc.field,
            source_id=exc.source_id,
            numeric_value=exc.numeric_value,
        ) from exc


def auto_revision_parent_eligible(
    revision: AutoMedicalKnowledgeRevision,
    source_rows,
) -> bool:
    if (
        revision.generation_status != "READY"
        or revision.is_visible is not True
        or revision.evidence_level not in PARENT_DISPLAYABLE_EVIDENCE
        or not revision.short_explanation_vi
        or not revision.detailed_explanation_vi
        or not revision.limitations_vi
        or (revision.generation_mode or "AI_FULL") not in {"AI_FULL", "SAFE_FALLBACK"}
        or (
            revision.generation_mode == "SAFE_FALLBACK"
            and revision.fallback_reason_code
            not in {
                "CONTRACT_REPAIR_EXHAUSTED",
                "REPAIR_PROVIDER_FAILURE",
                "REPAIR_STRUCTURAL_FAILURE",
            }
        )
    ):
        return False
    assessments: list[SourceAssessment] = []
    for link, source, content in source_rows:
        if (
            source is None
            or content is None
            or content.source_id != source.id
            or not (content.evidence_text or "").strip()
            or link.trust_class not in {"PUBMED", "PMC"}
        ):
            return False
        relevance_note = (link.relevance_note or "").strip()
        if ":" not in relevance_note:
            return False
        relevance, note = [part.strip() for part in relevance_note.split(":", 1)]
        try:
            assessments.append(
                SourceAssessment(
                    source_id=source.id,
                    relevance=relevance,
                    note_vi=note,
                    population_relevance=link.population_relevance,
                    population_note=link.population_note,
                )
            )
        except ValueError:
            return False
    return bool(assessments) and has_pediatric_direct_support(assessments)


class AutoMedicalKnowledgeQueueService:
    """Record anonymous topic demand and enqueue durable, deduplicated work."""

    def __init__(
        self,
        db: Session,
        *,
        max_retries: int,
        insufficient_stale_days: int,
        allowed_disease_group_ids: set[str] | None = None,
        clock: Callable[[], datetime] = datetime.utcnow,
    ):
        self.db = db
        self.repository = AutoMedicalKnowledgeRepository(db)
        self.max_retries = max_retries
        self.insufficient_stale_days = insufficient_stale_days
        self.clock = clock
        if allowed_disease_group_ids is not None:
            self.allowed_disease_group_ids = allowed_disease_group_ids
        else:
            try:
                self.allowed_disease_group_ids = set(
                    load_deployed_disease_contexts(
                        str(WEATHER_AI_V3_MODEL_MANIFEST),
                        str(WEATHER_AI_V3_DISEASE_CATALOG),
                    )
                )
            except Exception:
                # Public reads must remain available; only Auto enqueue fails closed.
                self.allowed_disease_group_ids = set()

    def enqueue_selectors(
        self,
        selectors: Iterable,
        *,
        trigger_type: str = "PARENT",
        force: bool = False,
    ) -> list[int]:
        try:
            runtime_enabled = self.repository.is_runtime_enabled()
        except Exception:
            self.db.rollback()
            return []
        if not runtime_enabled:
            return []
        job_ids: list[int] = []
        for selector in selectors:
            if selector.disease_group_id not in self.allowed_disease_group_ids:
                continue
            factor = normalize_factor(
                factor_type=selector.factor_type,
                factor_key=selector.factor_key,
                factor_value=selector.factor_value,
                weather_factor=getattr(selector, "weather_factor", None),
            )
            now = self.clock()
            try:
                topic = self.repository.get_or_create_topic(
                    disease_group_id=selector.disease_group_id,
                    factor_type=factor.factor_type,
                    factor_key=factor.factor_key,
                    factor_value=factor.factor_value,
                    weather_factor=factor.weather_factor,
                )
                if trigger_type == "PARENT":
                    self.repository.record_demand(topic.id, now=now)
                else:
                    self.repository.ensure_state(topic.id, now=now)

                active = self.repository.get_active_job(topic.id)
                if active is not None:
                    self.db.commit()
                    job_ids.append(active.id)
                    continue
                current = self.repository.get_current_revision(topic.id)
                if current is not None and not force:
                    if current.generation_status == "READY":
                        self.db.commit()
                        continue
                    if (
                        current.generation_status == "INSUFFICIENT"
                        and current.generated_at
                        > now - timedelta(days=self.insufficient_stale_days)
                    ):
                        self.db.commit()
                        continue
                latest = self.repository.get_latest_job(topic.id)
                if latest is not None and latest.status == "FAILED" and not force:
                    if (
                        latest.attempt_count >= self.max_retries
                        or latest.next_retry_at is None
                        or latest.next_retry_at > now
                    ):
                        self.db.commit()
                        continue
                    self.repository.requeue_job(latest.id, now=now)
                    self.db.commit()
                    job_ids.append(latest.id)
                    continue
                job = self.repository.create_job_if_runtime_enabled(
                    topic.id, trigger_type=trigger_type, now=now
                )
                if job is None:
                    self.db.rollback()
                    continue
                self.repository.add_discovery(
                    job_id=job.id,
                    source_id=None,
                    provider="AUTO_PIPELINE",
                    trust_class="PUBMED",
                    decision="SKIPPED",
                    reason_code="PIPELINE_ENQUEUED",
                    metadata_json={"pipeline_version": AUTO_PIPELINE_VERSION},
                    discovered_at=now,
                )
                self.db.commit()
                job_ids.append(job.id)
            except IntegrityError:
                self.db.rollback()
                topic = self.repository.get_or_create_topic(
                    disease_group_id=selector.disease_group_id,
                    factor_type=factor.factor_type,
                    factor_key=factor.factor_key,
                    factor_value=factor.factor_value,
                    weather_factor=factor.weather_factor,
                )
                active = self.repository.get_active_job(topic.id)
                self.db.commit()
                if active is not None:
                    job_ids.append(active.id)
        return list(dict.fromkeys(job_ids))


class AutoMedicalKnowledgeProcessor:
    def __init__(
        self,
        db: Session,
        discovery: AutoEvidenceDiscoveryProvider,
        generator: MedicalKnowledgeDraftGenerator,
        *,
        disease_manifest_path,
        disease_catalog_path,
        max_sources: int,
        max_retries: int,
        max_structural_retries: int = 1,
        retry_delay_seconds: int,
        provider_name: str | None = None,
        rate_limit_cooldown_seconds: int = 300,
        prompt_version: str,
        auto_visible_default: bool,
        max_input_chars: int,
        clock: Callable[[], datetime] = datetime.utcnow,
    ):
        self.db = db
        self.repository = AutoMedicalKnowledgeRepository(db)
        self.medical_repository = MedicalKnowledgeRepository(db)
        self.discovery = discovery
        self.generator = generator
        self.disease_manifest_path = str(disease_manifest_path)
        self.disease_catalog_path = str(disease_catalog_path)
        self.max_sources = min(10, max(1, max_sources))
        self.max_retries = max_retries
        self.max_structural_retries = min(1, max(0, max_structural_retries))
        self.retry_delay_seconds = retry_delay_seconds
        self.provider_name = provider_name.strip().upper() if provider_name else None
        self.rate_limit_cooldown_seconds = max(1, rate_limit_cooldown_seconds)
        self.prompt_version = prompt_version
        self.auto_visible_default = auto_visible_default
        self.max_input_chars = max_input_chars
        self.clock = clock

    def process_next(self) -> int | None:
        job_id = self.repository.claim_next_job(
            now=self.clock(),
            max_retries=self.max_retries,
            provider=self.provider_name,
        )
        if job_id is None:
            return None
        try:
            self._process(job_id)
        except Exception as exc:
            self.db.rollback()
            job = self.repository.get_job(job_id)
            if job is not None:
                finished = self.clock()
                retryable = isinstance(
                    exc,
                    (
                        AutoEvidenceSearchError,
                        AutoEvidenceEnrichmentError,
                        DraftGeneratorUnavailableError,
                        SQLAlchemyError,
                    ),
                )
                retry_at = (
                    finished + timedelta(seconds=self.retry_delay_seconds)
                    if retryable and job.attempt_count < self.max_retries
                    else None
                )
                code = classify_auto_failure(exc, new_pipeline=True)
                if isinstance(exc, DraftGeneratorRateLimitError) and self.provider_name:
                    retry_after = getattr(exc, "retry_after_seconds", None)
                    cooldown_seconds = (
                        retry_after
                        if retry_after is not None and retry_after >= 0
                        else self.rate_limit_cooldown_seconds
                    )
                    cooldown_until = finished + timedelta(seconds=cooldown_seconds)
                    self.repository.set_provider_cooldown(
                        self.provider_name,
                        cooldown_until=cooldown_until,
                        reason="LLM_RATE_LIMITED",
                        now=finished,
                    )
                    if retry_at is not None:
                        retry_at = max(retry_at, cooldown_until)
                self._persist_failure_detail(job_id, exc, code, now=finished)
                self.repository.set_job_status(
                    job_id,
                    "FAILED",
                    finished_at=finished,
                    next_retry_at=retry_at,
                    last_error_code=code,
                )
                self.db.commit()
        return job_id

    def _process(self, job_id: int) -> None:
        job = self.repository.get_job(job_id)
        if job is None or job.status != "SEARCHING":
            raise AutoMedicalKnowledgeConflictError("Auto job is not claimable")
        self._persist_attempt_marker(job_id)
        job = self.repository.get_job(job_id)
        topic = self.repository.get_topic(job.topic_id)
        if topic is None:
            raise AutoMedicalKnowledgeNotFoundError("Canonical topic is missing")
        disease_contexts = load_deployed_disease_contexts(
            self.disease_manifest_path, self.disease_catalog_path
        )
        disease_context = disease_contexts.get(topic.disease_group_id)
        if disease_context is None:
            raise AutoMedicalKnowledgeNotFoundError("Disease group is not deployed")
        disease_name, report_group_code = disease_context
        child_english_names = list(
            self.db.scalars(
                select(DiseaseCode.english_name)
                .where(
                    DiseaseCode.group_id == topic.disease_group_id,
                    DiseaseCode.english_name.is_not(None),
                )
                .order_by(DiseaseCode.icd_code)
            )
        )
        disease_aliases = build_disease_aliases(
            disease_name,
            tuple(value for value in child_english_names if value),
        )
        # External providers run after the short database claim transaction. Keep
        # a scalar snapshot so no expired ORM object is touched while I/O runs.
        topic_snapshot = type(
            "AutoTopicSnapshot",
            (),
            {
                "id": topic.id,
                "disease_group_id": topic.disease_group_id,
                "factor_type": topic.factor_type,
                "factor_key": topic.factor_key,
                "factor_value": topic.factor_value,
                "weather_factor": topic.weather_factor,
            },
        )()
        self.db.rollback()

        result = self.discovery.discover(
            topic=topic_snapshot,
            disease_name=disease_name,
            max_sources=self.max_sources,
            disease_aliases=disease_aliases,
        )
        selected = self._persist_discovery(job_id, result)
        if not selected:
            insufficient_reason = (
                result.diagnostics.insufficient_reason or "NO_USABLE_EVIDENCE"
            )
            self._persist_insufficient(
                job_id,
                topic_snapshot.id,
                reason_code=insufficient_reason,
                reason=_INSUFFICIENT_MESSAGES[insufficient_reason],
            )
            return

        context = DraftGenerationContext(
            disease_group_id=topic_snapshot.disease_group_id,
            disease_group_name=disease_name,
            report_group_code=report_group_code,
            factor_type=topic_snapshot.factor_type,
            factor_key=topic_snapshot.factor_key,
            factor_value=topic_snapshot.factor_value,
            weather_factor=topic_snapshot.weather_factor,
            sources=[item[2] for item in selected],
        )
        from app.services.auto_medical_knowledge_prompt import build_auto_generation_input

        if len(build_auto_generation_input(context)) > self.max_input_chars:
            raise AutoMedicalKnowledgeValidationError("Auto evidence exceeds total input bound")
        self.repository.set_job_status(job_id, "GENERATING")
        self.db.commit()
        validation, budget, repair_trace = self._generate_and_validate_proposal(
            context,
            selected,
            topic_id=topic_snapshot.id,
            allowed_context_text=topic_snapshot.factor_value or "",
            metadata_disease_group_ids=(topic_snapshot.disease_group_id,),
        )
        self._persist_generation_diagnostic(job_id, budget, repair_trace)
        proposal = validation.proposal
        verified_numeric_claims = validation.verified_numeric_claims
        insufficient_reason = validation.insufficient_reason
        if insufficient_reason:
            self._persist_proposal(
                job_id,
                topic_snapshot.id,
                proposal,
                selected,
                generation_status="INSUFFICIENT",
                visible=False,
                insufficient_reason=insufficient_reason,
                verified_numeric_claims=verified_numeric_claims,
            )
            return
        # The persisted admin setting is authoritative; the environment value
        # only seeds this singleton during migration.
        visible = (
            self.repository.get_settings().auto_visible_default
            and proposal.evidence_level in PARENT_DISPLAYABLE_EVIDENCE
        )
        self._persist_proposal(
            job_id,
            topic_snapshot.id,
            proposal,
            selected,
            generation_status="READY",
            visible=visible,
            verified_numeric_claims=verified_numeric_claims,
            generation_mode=validation.generation_mode,
            fallback_reason_code=validation.fallback_reason_code,
        )

    def _validate_generated_proposal(
        self,
        proposal,
        selected,
        *,
        allowed_context_text: str,
        metadata_disease_group_ids: tuple[str, ...],
    ) -> AutoProposalValidationResult:
        """Run the complete provider-independent validation from its first step."""

        if not isinstance(proposal, AutoMedicalKnowledgeDraftProposal):
            raise DraftGeneratorStructuredOutputError(
                "AUTO_OUTPUT_SCHEMA_INVALID",
                "Auto generation must satisfy Numeric Claim Contract V2.",
                field="numeric_claims",
            )
        selected_ids = {item[0].id for item in selected}
        assessment_list = [item.source_id for item in proposal.source_assessments]
        assessment_ids = {item.source_id for item in proposal.source_assessments}
        if selected_ids != assessment_ids or len(assessment_list) != len(selected_ids):
            raise DraftGeneratorStructuredOutputError(
                "AUTO_OUTPUT_SOURCE_SET_MISMATCH",
                "Provider output must assess every selected source ID exactly once.",
                field="source_assessments",
            )
        verified_numeric_claims = validate_auto_proposal_claims(
            proposal,
            selected,
            # Only the canonical factor value is medical topic context. Group
            # IDs/report codes are metadata and must not whitelist statistics.
            allowed_context_text=allowed_context_text,
            metadata_disease_group_ids=metadata_disease_group_ids,
        )
        all_not_supportive = all(
            item.relevance == "NOT_SUPPORTIVE" for item in proposal.source_assessments
        )
        insufficient_reason = None
        if proposal.evidence_level == "CONFLICTING":
            insufficient_reason = "CONFLICTING_EVIDENCE"
        elif proposal.evidence_level == "INSUFFICIENT" or all_not_supportive:
            insufficient_reason = "NO_DIRECT_SUPPORT"
        elif not has_pediatric_direct_support(proposal.source_assessments):
            insufficient_reason = "NO_PEDIATRIC_RELEVANT_SOURCE"
        return AutoProposalValidationResult(
            proposal=proposal,
            verified_numeric_claims=verified_numeric_claims,
            insufficient_reason=insufficient_reason,
        )

    def _generate_and_validate_proposal(
        self,
        context: DraftGenerationContext,
        selected,
        *,
        topic_id: int,
        allowed_context_text: str,
        metadata_disease_group_ids: tuple[str, ...],
    ) -> tuple[
        AutoProposalValidationResult,
        AutoGenerationCallBudget,
        AutoContractRepairTrace,
    ]:
        """Generate, classify a typed failure, and run at most one repair."""

        from app.services.auto_medical_knowledge_prompt import (
            build_auto_contract_repair_input,
        )

        budget = AutoGenerationCallBudget()
        trace = AutoContractRepairTrace()
        safe_snapshot: SafeFallbackEligibilitySnapshot | None = None
        try:
            proposal = self._generate_with_structural_retry(context, budget)
        except Exception as exc:
            trace.result = (
                "RATE_LIMITED"
                if isinstance(exc, DraftGeneratorRateLimitError)
                else "NOT_ELIGIBLE"
            )
            raise _attach_contract_repair_trace(exc, trace, budget)

        try:
            validation = self._validate_generated_proposal(
                proposal,
                selected,
                allowed_context_text=allowed_context_text,
                metadata_disease_group_ids=metadata_disease_group_ids,
            )
        except AutoOutputSafetyError as exc:
            if not is_auto_output_repairable(exc.code):
                trace.result = "NOT_ELIGIBLE"
                raise _attach_contract_repair_trace(exc, trace, budget)
            eligibility = evaluate_safe_fallback_eligibility(
                topic_id=topic_id,
                context=context,
                selected=selected,
                proposal=proposal,
                failure_code=exc.code,
            )
            safe_snapshot = eligibility.snapshot if eligibility.eligible else None
            trace.attempted = True
            trace.reason = exc.code
            if budget.remaining <= 0:
                if safe_snapshot is not None:
                    fallback = self._render_and_validate_safe_fallback(
                        safe_snapshot,
                        selected,
                        allowed_context_text=allowed_context_text,
                        metadata_disease_group_ids=metadata_disease_group_ids,
                        reason_code="CONTRACT_REPAIR_EXHAUSTED",
                    )
                    trace.result = "SAFE_FALLBACK"
                    return fallback, budget, trace
                trace.result = "FAILED"
                raise _attach_contract_repair_trace(exc, trace, budget)

            try:
                self._assert_repair_provider_available()
                repair_input = build_auto_contract_repair_input(
                    context,
                    proposal,
                    failure_code=exc.code,
                    field=exc.field,
                    numeric_value=exc.numeric_value,
                )
                if (
                    len(repair_input) > self.max_input_chars
                ):
                    raise AutoMedicalKnowledgeValidationError(
                        "Auto contract repair exceeds total input bound"
                    )
                trace.calls += 1
                repaired_proposal = self._call_generator(
                    context,
                    budget,
                    call_purpose="CONTRACT_REPAIR",
                    user_input_override=repair_input,
                )
                repaired_validation = self._validate_generated_proposal(
                    repaired_proposal,
                    selected,
                    allowed_context_text=allowed_context_text,
                    metadata_disease_group_ids=metadata_disease_group_ids,
                )
            except Exception as repair_exc:
                repair_code = classify_auto_failure(repair_exc, new_pipeline=True)
                if safe_snapshot is not None and is_safe_fallback_trigger(
                    repair_code, "CONTRACT_REPAIR"
                ):
                    fallback = self._render_and_validate_safe_fallback(
                        safe_snapshot,
                        selected,
                        allowed_context_text=allowed_context_text,
                        metadata_disease_group_ids=metadata_disease_group_ids,
                        reason_code=safe_fallback_reason_code(repair_code),
                    )
                    trace.result = "SAFE_FALLBACK"
                    return fallback, budget, trace
                trace.result = (
                    "RATE_LIMITED"
                    if isinstance(repair_exc, DraftGeneratorRateLimitError)
                    else "FAILED"
                )
                raise _attach_contract_repair_trace(repair_exc, trace, budget)
            trace.result = "SUCCESS"
            return repaired_validation, budget, trace
        except Exception as exc:
            trace.result = "NOT_ELIGIBLE"
            raise _attach_contract_repair_trace(exc, trace, budget)
        return validation, budget, trace

    def _render_and_validate_safe_fallback(
        self,
        snapshot: SafeFallbackEligibilitySnapshot,
        selected,
        *,
        allowed_context_text: str,
        metadata_disease_group_ids: tuple[str, ...],
        reason_code: str,
    ) -> AutoProposalValidationResult:
        proposal = AutoSafeFallbackRenderer().render(snapshot)
        validation = self._validate_generated_proposal(
            proposal,
            selected,
            allowed_context_text=allowed_context_text,
            metadata_disease_group_ids=metadata_disease_group_ids,
        )
        if validation.insufficient_reason is not None:
            raise AutoMedicalKnowledgeValidationError(
                "Safe fallback failed its evidence eligibility assertion"
            )
        return AutoProposalValidationResult(
            proposal=validation.proposal,
            verified_numeric_claims=(),
            insufficient_reason=None,
            generation_mode="SAFE_FALLBACK",
            fallback_reason_code=reason_code,
        )

    def _assert_repair_provider_available(self) -> None:
        if not self.provider_name:
            return
        now = self.clock()
        cooldown = self.repository.get_active_provider_cooldown(
            self.provider_name, now=now
        )
        if cooldown is None:
            return
        retry_after = max(0.0, (cooldown.cooldown_until - now).total_seconds())
        raise DraftGeneratorRateLimitError(
            "The configured LLM provider is in an active cooldown.",
            retry_after_seconds=retry_after,
        )

    def _generate_with_structural_retry(
        self,
        context: DraftGenerationContext,
        budget: AutoGenerationCallBudget,
    ):
        attempts = 0
        while True:
            try:
                if attempts == 0:
                    return self._call_generator(
                        context,
                        budget,
                        call_purpose="INITIAL",
                    )
                return self._call_generator(
                    context,
                    budget,
                    call_purpose="STRUCTURAL_RETRY",
                    structural_retry=True,
                )
            except DraftGeneratorStructuredOutputError:
                if (
                    attempts >= self.max_structural_retries
                    or budget.remaining <= 0
                ):
                    raise
                attempts += 1

    def _call_generator(
        self,
        context: DraftGenerationContext,
        budget: AutoGenerationCallBudget,
        *,
        call_purpose: str,
        structural_retry: bool = False,
        user_input_override: str | None = None,
    ):
        call_number = budget.calls + 1
        generation_options = {}
        if structural_retry:
            generation_options["structural_retry"] = True
        if user_input_override is not None:
            generation_options["user_input_override"] = user_input_override
        try:
            return budget.call(
                lambda: self.generator.generate(
                    context,
                    **generation_options,
                )
            )
        except Exception as exc:
            raise _attach_generation_call_context(
                exc,
                call_purpose=call_purpose,
                generation_call_number=call_number,
            )

    def _persist_generation_diagnostic(
        self,
        job_id: int,
        budget: AutoGenerationCallBudget,
        trace: AutoContractRepairTrace,
    ) -> None:
        attempt, attempt_key, pipeline_version = self._attempt_metadata(job_id)
        self.repository.add_discovery(
            job_id=job_id,
            source_id=None,
            provider="AUTO_PIPELINE",
            trust_class="PUBMED",
            decision="SKIPPED",
            reason_code="GENERATION_DIAGNOSTIC",
            metadata_json={
                "attempt": attempt,
                "attempt_key": attempt_key,
                "pipeline_version": pipeline_version or AUTO_PIPELINE_VERSION,
                "initial_provider_call_occurred": budget.calls >= 1,
                "generation_calls": budget.calls,
                "max_generation_calls": budget.max_calls,
                "contract_repair_attempted": trace.attempted,
                "contract_repair_reason": trace.reason,
                "contract_repair_calls": trace.calls,
                "contract_repair_result": trace.result,
            },
            discovered_at=self.clock(),
        )

    def _persist_attempt_marker(self, job_id: int) -> None:
        now = self.clock()
        job = self.repository.get_job(job_id)
        attempt = job.attempt_count if job is not None else 0
        attempt_key = f"{job_id}:{attempt}:{now.isoformat(timespec='microseconds')}"
        self.repository.add_discovery(
            job_id=job_id,
            source_id=None,
            provider="AUTO_PIPELINE",
            trust_class="PUBMED",
            decision="SKIPPED",
            reason_code="PIPELINE_ATTEMPT",
            metadata_json={
                "attempt": attempt,
                "attempt_key": attempt_key,
                "pipeline_version": AUTO_PIPELINE_VERSION,
            },
            discovered_at=now,
        )
        self.db.commit()

    def _attempt_metadata(self, job_id: int) -> tuple[int, str | None, str | None]:
        job = self.repository.get_job(job_id)
        attempt = job.attempt_count if job is not None else 0
        markers = [
            row for row in self.repository.get_discoveries(job_id)
            if row.reason_code == "PIPELINE_ATTEMPT" and isinstance(row.metadata_json, dict)
        ]
        if not markers:
            return attempt, None, None
        metadata = markers[-1].metadata_json
        return (
            int(metadata.get("attempt") or attempt),
            metadata.get("attempt_key"),
            metadata.get("pipeline_version"),
        )

    def _persist_failure_detail(
        self, job_id: int, exc: Exception, code: str, *, now: datetime
    ) -> None:
        attempt, attempt_key, pipeline_version = self._attempt_metadata(job_id)
        metadata = _safe_failure_detail(exc, code)
        metadata.update(
            {
                "attempt": attempt,
                "attempt_key": attempt_key,
                "pipeline_version": pipeline_version or AUTO_PIPELINE_VERSION,
            }
        )
        self.repository.add_discovery(
            job_id=job_id,
            source_id=None,
            provider="AUTO_PIPELINE",
            trust_class="PUBMED",
            decision="SKIPPED",
            reason_code="FAILURE_DETAIL",
            metadata_json=metadata,
            discovered_at=now,
        )

    def _persist_discovery(
        self, job_id: int, result: AutoDiscoveryResult
    ) -> list[tuple[object, object, DraftSourceInput, str, object]]:
        selected_by_pmid: dict[
            str, tuple[object, object, DraftSourceInput, str, object]
        ] = {}
        now = self.clock()
        attempt, attempt_key, pipeline_version = self._attempt_metadata(job_id)
        for candidate in result.selected:
            if candidate.trust_class not in {"PUBMED", "PMC"}:
                raise AutoMedicalKnowledgeValidationError(
                    "Auto source provider is not implemented or trusted"
                )
            record = candidate.record
            source = self.medical_repository.get_source_by_pmid(record.pmid)
            if source is None:
                source = self.medical_repository.create_source(
                    MedicalEvidenceSourceCreate(
                        source_type="PUBMED",
                        pmid=record.pmid,
                        doi=record.doi,
                        title=record.title,
                        authors=record.authors,
                        journal=record.journal,
                        publication_year=record.publication_year,
                        abstract_text=record.abstract_text,
                        url=record.pubmed_url,
                        retrieved_at=candidate.evidence.retrieved_at,
                        raw_metadata_json=record.raw_metadata,
                    )
                )
            content = self.medical_repository.get_evidence_content_by_hash(
                source.id, candidate.evidence.content_sha256
            )
            if content is None:
                content = self.medical_repository.create_evidence_content(
                    MedicalEvidenceContentCreate(
                        source_id=source.id,
                        content_kind=candidate.evidence.content_kind,
                        content_origin=candidate.evidence.content_origin,
                        external_identifier=candidate.evidence.external_identifier,
                        evidence_text=candidate.evidence.evidence_text,
                        retrieved_at=candidate.evidence.retrieved_at,
                        is_truncated=candidate.evidence.is_truncated,
                        license_name=candidate.evidence.license_name,
                        license_url=candidate.evidence.license_url,
                        provenance_json=candidate.evidence.provenance,
                        content_sha256=candidate.evidence.content_sha256,
                    )
                )
            publication_types = record.raw_metadata.get("publication_types", [])
            selected_by_pmid[record.pmid] = (
                source,
                content,
                DraftSourceInput(
                    source_id=source.id,
                    source_type=source.source_type,
                    pmid=source.pmid,
                    doi=source.doi,
                    title=source.title,
                    authors=source.authors,
                    journal=source.journal,
                    publication_year=source.publication_year,
                    publication_types=(
                        [str(value) for value in publication_types[:20]]
                        if isinstance(publication_types, list)
                        else []
                    ),
                    evidence_content_id=content.id,
                    content_kind=content.content_kind,
                    evidence_text=content.evidence_text,
                    content_origin=content.content_origin,
                    pmcid=(
                        content.external_identifier
                        if (content.external_identifier or "").startswith("PMC")
                        else None
                    ),
                    license_name=content.license_name,
                    license_url=content.license_url,
                ),
                candidate.trust_class,
                candidate.signals,
            )
        for audit in result.audit:
            selected_row = selected_by_pmid.get(audit.pmid)
            self.repository.add_discovery(
                job_id=job_id,
                source_id=selected_row[0].id if selected_row else None,
                provider=audit.provider,
                trust_class=(selected_row[3] if selected_row else audit.trust_class),
                decision=audit.decision,
                reason_code=audit.reason_code,
                metadata_json={
                    "attempt": attempt,
                    "attempt_key": attempt_key,
                    "pipeline_version": pipeline_version or AUTO_PIPELINE_VERSION,
                    "pmid": audit.pmid,
                    "title": audit.title,
                    "stage": audit.stage,
                },
                discovered_at=now,
            )
        for query in result.diagnostics.query_details:
            self.repository.add_discovery(
                job_id=job_id,
                source_id=None,
                provider=self.discovery.provider_name,
                trust_class="PUBMED",
                decision="SKIPPED",
                reason_code="QUERY_EXECUTED",
                metadata_json={
                    "attempt": attempt,
                    "attempt_key": attempt_key,
                    "pipeline_version": pipeline_version or AUTO_PIPELINE_VERSION,
                    "stage": query.stage,
                    "query": query.query,
                    "returned_results": query.returned_results,
                },
                discovered_at=now,
            )
        diagnostics = result.diagnostics
        self.repository.add_discovery(
            job_id=job_id,
            source_id=None,
            provider=self.discovery.provider_name,
            trust_class="PUBMED",
            decision="SKIPPED",
            reason_code="PIPELINE_SUMMARY",
            metadata_json={
                "attempt": attempt,
                "attempt_key": attempt_key,
                "pipeline_version": pipeline_version or AUTO_PIPELINE_VERSION,
                "queries_run": diagnostics.queries_run,
                "raw_results": diagnostics.raw_results,
                "deduplicated": diagnostics.deduplicated,
                "disease_relevant": diagnostics.disease_relevant,
                "factor_relevant": diagnostics.factor_relevant,
                "pediatric_relevant": diagnostics.pediatric_relevant,
                "usable_evidence": diagnostics.usable_evidence,
                "selected_for_generation": diagnostics.selected_for_generation,
                "insufficient_reason": diagnostics.insufficient_reason,
            },
            discovered_at=now,
        )
        self.db.commit()
        return [selected_by_pmid[item.record.pmid] for item in result.selected]

    def _persist_insufficient(
        self, job_id: int, topic_id: int, *, reason_code: str, reason: str
    ) -> None:
        now = self.clock()
        revision = self.repository.create_revision(
            topic_id=topic_id,
            job_id=job_id,
            revision_number=self.repository.next_revision_number(topic_id),
            generation_status="INSUFFICIENT",
            evidence_level="INSUFFICIENT",
            evidence_scope=None,
            short_explanation_vi=None,
            detailed_explanation_vi=None,
            limitations_vi=reason,
            is_visible=False,
            llm_model=None,
            prompt_version=self.prompt_version,
            generation_mode=None,
            fallback_reason_code=None,
            generated_at=now,
            source_retrieved_at=None,
            created_at=now,
        )
        self.repository.set_current_revision(topic_id, revision.id, now=now)
        self.repository.set_job_status(
            job_id, "INSUFFICIENT", finished_at=now, last_error_code=None
        )
        self._persist_discovery_outcome(job_id, reason_code, now=now)
        self.db.commit()

    def _persist_discovery_outcome(
        self, job_id: int, insufficient_reason: str, *, now: datetime
    ) -> None:
        job = self.repository.get_job(job_id)
        summaries = [
            row
            for row in self.repository.get_discoveries(job_id)
            if row.reason_code == "PIPELINE_SUMMARY"
            and isinstance(row.metadata_json, dict)
        ]
        attempt_key = (
            summaries[-1].metadata_json.get("attempt_key") if summaries else None
        )
        self.repository.add_discovery(
            job_id=job_id,
            source_id=None,
            provider=self.discovery.provider_name,
            trust_class="PUBMED",
            decision="SKIPPED",
            reason_code="PIPELINE_OUTCOME",
            metadata_json={
                "attempt": job.attempt_count if job is not None else 0,
                "attempt_key": attempt_key,
                "pipeline_version": AUTO_PIPELINE_VERSION,
                "insufficient_reason": insufficient_reason,
            },
            discovered_at=now,
        )

    def _persist_proposal(
        self,
        job_id: int,
        topic_id: int,
        proposal: AutoMedicalKnowledgeDraftProposal,
        selected,
        *,
        generation_status: str,
        visible: bool,
        insufficient_reason: str | None = None,
        verified_numeric_claims: tuple[VerifiedNumericClaim, ...] = (),
        generation_mode: str | None = "AI_FULL",
        fallback_reason_code: str | None = None,
    ) -> None:
        now = self.clock()
        retrieved = max(item[1].retrieved_at for item in selected)
        revision = self.repository.create_revision(
            topic_id=topic_id,
            job_id=job_id,
            revision_number=self.repository.next_revision_number(topic_id),
            generation_status=generation_status,
            evidence_level=(
                proposal.evidence_level
                if generation_status == "READY"
                else "INSUFFICIENT"
            ),
            evidence_scope=proposal.evidence_scope,
            short_explanation_vi=(
                proposal.short_explanation_vi if generation_status == "READY" else None
            ),
            detailed_explanation_vi=(
                proposal.detailed_explanation_vi if generation_status == "READY" else None
            ),
            limitations_vi=proposal.limitations_vi,
            is_visible=visible,
            llm_model=self.generator.model_name,
            prompt_version=self.prompt_version,
            generation_mode=generation_mode,
            fallback_reason_code=fallback_reason_code,
            generated_at=now,
            source_retrieved_at=retrieved,
            created_at=now,
        )
        assessments = {item.source_id: item for item in proposal.source_assessments}
        for sort_order, (source, content, _input, trust_class, _signals) in enumerate(selected):
            assessment = assessments[source.id]
            self.repository.add_revision_source(
                revision_id=revision.id,
                source_id=source.id,
                evidence_content_id=content.id,
                trust_class=trust_class,
                source_role="PRIMARY" if assessment.relevance == "DIRECT" else "SUPPORTING",
                sort_order=sort_order,
                relevance_note=f"{assessment.relevance}: {assessment.note_vi}",
                population_relevance=assessment.population_relevance,
                population_note=assessment.population_note,
            )
        for claim in verified_numeric_claims:
            self.repository.add_numeric_claim(
                revision_id=revision.id,
                claim_order=claim.claim_order,
                claim_kind=claim.claim_kind,
                value_text=claim.value_text,
                unit=claim.unit,
                source_id=claim.source_id,
                evidence_content_id=claim.evidence_content_id,
                support_start=claim.support_start,
                support_end=claim.support_end,
                support_sha256=claim.support_sha256,
            )
        self.repository.set_current_revision(topic_id, revision.id, now=now)
        self.repository.set_job_status(
            job_id,
            "READY" if generation_status == "READY" else "INSUFFICIENT",
            finished_at=now,
            last_error_code=None,
        )
        if insufficient_reason:
            self._persist_discovery_outcome(job_id, insufficient_reason, now=now)
        self.db.commit()


class AutoMedicalKnowledgeAdminService:
    def __init__(
        self,
        db: Session,
        *,
        queue_service: AutoMedicalKnowledgeQueueService,
    ):
        self.db = db
        self.repository = AutoMedicalKnowledgeRepository(db)
        self.queue_service = queue_service

    def overview(self) -> AutoMedicalKnowledgeOverviewResponse:
        settings = self.repository.get_settings()
        cooldown = self.repository.get_provider_cooldown(
            MEDICAL_KNOWLEDGE_LLM_PROVIDER
        )
        now = datetime.utcnow()
        job_rows = self.repository.list_jobs()
        latest_by_topic: dict[int, int] = {}
        for job, topic in job_rows:
            latest_by_topic.setdefault(topic.id, job.id)
        jobs = [
            AutoMedicalKnowledgeJobResponse(
                id=job.id,
                topic_id=topic.id,
                disease_group_id=topic.disease_group_id,
                factor_type=topic.factor_type,
                factor_key=topic.factor_key,
                factor_value=topic.factor_value,
                status=job.status,
                attempt_count=job.attempt_count,
                trigger_type=job.trigger_type,
                created_at=job.created_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
                next_retry_at=job.next_retry_at,
                last_error_code=job.last_error_code,
                is_current_attempt=latest_by_topic[topic.id] == job.id,
                legacy=(
                    self._job_pipeline_version(job.id) is None
                    or job.last_error_code == "LLM_INVALID_RESPONSE"
                ),
                pipeline_version=self._job_pipeline_version(job.id),
                history=self._attempt_history_response(job),
                diagnostics=self._diagnostics_response(job.id),
            )
            for job, topic in job_rows
        ]
        revisions = [self._revision_response(revision, topic) for revision, topic in self.repository.list_current_revisions()]
        self.db.commit()
        return AutoMedicalKnowledgeOverviewResponse(
            settings=AutoMedicalKnowledgeSettingsResponse(
                enabled=settings.enabled,
                display_mode=settings.display_mode,
                auto_visible_default=settings.auto_visible_default,
            ),
            provider_cooldown=(
                AutoProviderCooldownResponse(
                    provider=cooldown.provider,
                    active=cooldown.cooldown_until > now,
                    cooldown_until=cooldown.cooldown_until,
                    reason=cooldown.reason,
                    updated_at=cooldown.updated_at,
                )
                if cooldown is not None
                else None
            ),
            jobs=jobs,
            revisions=revisions,
        )

    def _revision_response(self, revision, topic) -> AutoMedicalKnowledgeRevisionResponse:
        source_rows = self.repository.get_revision_sources(revision.id)
        return AutoMedicalKnowledgeRevisionResponse(
            id=revision.id,
            topic_id=topic.id,
            disease_group_id=topic.disease_group_id,
            factor_type=topic.factor_type,
            factor_key=topic.factor_key,
            factor_value=topic.factor_value,
            weather_factor=topic.weather_factor,
            revision_number=revision.revision_number,
            generation_status=revision.generation_status,
            generation_mode=(
                revision.generation_mode or "AI_FULL"
                if revision.generation_status == "READY"
                else None
            ),
            fallback_reason_code=revision.fallback_reason_code,
            evidence_level=revision.evidence_level,
            evidence_scope=revision.evidence_scope,
            short_explanation_vi=revision.short_explanation_vi,
            detailed_explanation_vi=revision.detailed_explanation_vi,
            limitations_vi=revision.limitations_vi,
            is_visible=revision.is_visible,
            llm_model=revision.llm_model,
            prompt_version=revision.prompt_version,
            generated_at=revision.generated_at,
            source_retrieved_at=revision.source_retrieved_at,
            sources=[
                AutoMedicalKnowledgeSourceResponse(
                    source_id=source.id,
                    title=source.title,
                    journal=source.journal,
                    publication_year=source.publication_year,
                    pmid=source.pmid,
                    doi=source.doi,
                    url=(
                        f"https://pubmed.ncbi.nlm.nih.gov/{source.pmid}/"
                        if (source.pmid or "").isdigit()
                        else None
                    ),
                    trust_class=link.trust_class,
                    content_kind=content.content_kind,
                    source_role=link.source_role,
                    relevance_note=link.relevance_note,
                    population_relevance=link.population_relevance,
                    population_note=link.population_note,
                )
                for link, source, content in source_rows
            ],
            diagnostics=self._diagnostics_response(revision.job_id),
        )

    def _diagnostics_response(
        self, job_id: int
    ) -> AutoDiscoveryDiagnosticsResponse | None:
        rows = self.repository.get_discoveries(job_id)
        summaries = [row for row in rows if row.reason_code == "PIPELINE_SUMMARY"]
        markers = [row for row in rows if row.reason_code == "PIPELINE_ATTEMPT"]
        failures = [row for row in rows if row.reason_code == "FAILURE_DETAIL"]
        if not summaries and not markers and not failures:
            return None
        anchor = max((*summaries, *markers, *failures), key=lambda row: row.id)
        metadata = anchor.metadata_json if isinstance(anchor.metadata_json, dict) else {}
        attempt = int(metadata.get("attempt") or 0)
        attempt_key = metadata.get("attempt_key")
        current_rows = [
            row
            for row in rows
            if isinstance(row.metadata_json, dict)
            and (
                row.metadata_json.get("attempt_key") == attempt_key
                if attempt_key
                else int(row.metadata_json.get("attempt") or 0) == attempt
            )
        ]
        queries = [
            str(row.metadata_json.get("query"))
            for row in current_rows
            if row.reason_code == "QUERY_EXECUTED"
            and row.metadata_json.get("query")
        ]
        outcome_rows = [
            row for row in current_rows if row.reason_code == "PIPELINE_OUTCOME"
        ]
        failure_rows = [
            row for row in current_rows if row.reason_code == "FAILURE_DETAIL"
        ]
        generation_rows = [
            row for row in current_rows if row.reason_code == "GENERATION_DIAGNOSTIC"
        ]
        repair_metadata = (
            generation_rows[-1].metadata_json
            if generation_rows
            else (failure_rows[-1].metadata_json if failure_rows else {})
        )
        insufficient_reason = metadata.get("insufficient_reason")
        if outcome_rows:
            insufficient_reason = outcome_rows[-1].metadata_json.get(
                "insufficient_reason"
            )
        source_rows = [
            row
            for row in current_rows
            if row.reason_code
            not in {"PIPELINE_SUMMARY", "PIPELINE_OUTCOME", "QUERY_EXECUTED"}
            and row.metadata_json.get("pmid")
        ]
        return AutoDiscoveryDiagnosticsResponse(
            attempt=attempt,
            queries_run=int(metadata.get("queries_run") or 0),
            raw_results=int(metadata.get("raw_results") or 0),
            deduplicated=int(metadata.get("deduplicated") or 0),
            disease_relevant=int(metadata.get("disease_relevant") or 0),
            factor_relevant=int(metadata.get("factor_relevant") or 0),
            pediatric_relevant=int(metadata.get("pediatric_relevant") or 0),
            usable_evidence=int(metadata.get("usable_evidence") or 0),
            selected_for_generation=int(metadata.get("selected_for_generation") or 0),
            insufficient_reason=(
                str(insufficient_reason) if insufficient_reason else None
            ),
            queries=queries,
            sources=[
                AutoDiscoverySourceDiagnostic(
                    pmid=str(row.metadata_json.get("pmid")),
                    title=str(row.metadata_json.get("title") or ""),
                    decision=row.decision,
                    reason_code=row.reason_code,
                    stage=(
                        str(row.metadata_json.get("stage"))
                        if row.metadata_json.get("stage")
                        else None
                    ),
                )
                for row in source_rows[-30:]
            ],
            pipeline_version=(
                str(metadata.get("pipeline_version"))
                if metadata.get("pipeline_version") else self._job_pipeline_version(job_id)
            ),
            generation_calls=repair_metadata.get("generation_calls"),
            max_generation_calls=repair_metadata.get("max_generation_calls"),
            contract_repair_attempted=repair_metadata.get(
                "contract_repair_attempted"
            ),
            contract_repair_reason=repair_metadata.get("contract_repair_reason"),
            contract_repair_calls=repair_metadata.get("contract_repair_calls"),
            contract_repair_result=repair_metadata.get("contract_repair_result"),
            failure=(
                AutoFailureDiagnosticResponse(
                    code=str(failure_rows[-1].metadata_json.get("code")),
                    field=failure_rows[-1].metadata_json.get("field"),
                    source_id=failure_rows[-1].metadata_json.get("source_id"),
                    numeric_value=(
                        str(failure_rows[-1].metadata_json.get("numeric_value"))
                        if failure_rows[-1].metadata_json.get("numeric_value") is not None
                        else None
                    ),
                    safe_detail=str(
                        failure_rows[-1].metadata_json.get("safe_detail")
                        or "The pipeline rejected this output safely."
                    ),
                    provider_error_class=failure_rows[-1].metadata_json.get(
                        "provider_error_class"
                    ),
                    provider=failure_rows[-1].metadata_json.get("provider"),
                    http_status=failure_rows[-1].metadata_json.get("http_status"),
                    provider_stage=failure_rows[-1].metadata_json.get("provider_stage"),
                    finish_reason=failure_rows[-1].metadata_json.get("finish_reason"),
                    choices_count=failure_rows[-1].metadata_json.get("choices_count"),
                    message_present=failure_rows[-1].metadata_json.get("message_present"),
                    content_present=failure_rows[-1].metadata_json.get("content_present"),
                    content_length=failure_rows[-1].metadata_json.get("content_length"),
                    refusal_present=failure_rows[-1].metadata_json.get("refusal_present"),
                    incomplete=failure_rows[-1].metadata_json.get("incomplete"),
                    structured_field_detected=failure_rows[-1].metadata_json.get(
                        "structured_field_detected"
                    ),
                    call_purpose=failure_rows[-1].metadata_json.get(
                        "call_purpose"
                    ),
                    generation_call_number=failure_rows[-1].metadata_json.get(
                        "generation_call_number"
                    ),
                    response_format_type=failure_rows[-1].metadata_json.get(
                        "response_format_type"
                    ),
                    provider_validation_stage=failure_rows[-1].metadata_json.get(
                        "provider_validation_stage"
                    ),
                    provider_error_category=failure_rows[-1].metadata_json.get(
                        "provider_error_category"
                    ),
                    provider_error_type=failure_rows[-1].metadata_json.get(
                        "provider_error_type"
                    ),
                    request_body_bytes=failure_rows[-1].metadata_json.get(
                        "request_body_bytes"
                    ),
                    user_content_chars=failure_rows[-1].metadata_json.get(
                        "user_content_chars"
                    ),
                    message_count=failure_rows[-1].metadata_json.get(
                        "message_count"
                    ),
                    generation_calls=failure_rows[-1].metadata_json.get(
                        "generation_calls"
                    ),
                    max_generation_calls=failure_rows[-1].metadata_json.get(
                        "max_generation_calls"
                    ),
                    contract_repair_attempted=failure_rows[-1].metadata_json.get(
                        "contract_repair_attempted"
                    ),
                    contract_repair_reason=failure_rows[-1].metadata_json.get(
                        "contract_repair_reason"
                    ),
                    contract_repair_calls=failure_rows[-1].metadata_json.get(
                        "contract_repair_calls"
                    ),
                    contract_repair_result=failure_rows[-1].metadata_json.get(
                        "contract_repair_result"
                    ),
                )
                if failure_rows else None
            ),
        )

    def _job_pipeline_version(self, job_id: int) -> str | None:
        versions = [
            row.metadata_json.get("pipeline_version")
            for row in self.repository.get_discoveries(job_id)
            if isinstance(row.metadata_json, dict)
            and row.metadata_json.get("pipeline_version")
        ]
        return str(versions[-1]) if versions else None

    def _attempt_history_response(self, job) -> list[AutoAttemptHistoryResponse]:
        rows = self.repository.get_discoveries(job.id)
        markers = [
            row for row in rows
            if row.reason_code == "PIPELINE_ATTEMPT" and isinstance(row.metadata_json, dict)
        ]
        current_key = (
            markers[-1].metadata_json.get("attempt_key") if markers else None
        )
        entries: dict[tuple[int, str | None], AutoAttemptHistoryResponse] = {}
        for row in rows:
            if row.reason_code not in {"FAILURE_HISTORY", "FAILURE_DETAIL"}:
                continue
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            if (
                row.reason_code == "FAILURE_DETAIL"
                and job.status == "FAILED"
                and metadata.get("attempt_key") == current_key
            ):
                continue
            attempt = int(metadata.get("attempt") or 0)
            code = metadata.get("failure_code") or metadata.get("code")
            version = metadata.get("pipeline_version")
            entries[(attempt, str(code) if code else None)] = AutoAttemptHistoryResponse(
                attempt=attempt,
                status="FAILED" if code else "UNKNOWN",
                failure_code=str(code) if code else None,
                legacy=(not bool(version) or code == "LLM_INVALID_RESPONSE"),
                pipeline_version=str(version) if version else None,
                created_at=row.discovered_at,
            )
        return sorted(entries.values(), key=lambda item: item.created_at, reverse=True)

    def update_settings(
        self, *, enabled=None, display_mode=None, auto_visible_default=None
    ):
        settings = self.repository.get_settings()
        if enabled is not None:
            settings.enabled = enabled
        if display_mode is not None:
            settings.display_mode = display_mode
        if auto_visible_default is not None:
            settings.auto_visible_default = auto_visible_default
        settings.updated_at = datetime.utcnow()
        self.db.commit()
        return AutoMedicalKnowledgeSettingsResponse(
            enabled=settings.enabled,
            display_mode=settings.display_mode,
            auto_visible_default=settings.auto_visible_default,
        )

    def set_visibility(self, revision_id: int, *, is_visible: bool):
        revision = self.db.get(AutoMedicalKnowledgeRevision, revision_id)
        if revision is None:
            raise AutoMedicalKnowledgeNotFoundError("Auto revision was not found")
        rows = self.repository.get_revision_sources(revision.id)
        if is_visible and not auto_revision_parent_eligible(
            revision, rows
        ):
            # Eligibility helper expects visibility true; evaluate a temporary flip.
            revision.is_visible = True
            eligible = auto_revision_parent_eligible(revision, rows)
            revision.is_visible = False
            if not eligible:
                raise AutoMedicalKnowledgeValidationError(
                    "Auto revision is not eligible for Parent display"
                )
        revision.is_visible = is_visible
        self.db.commit()
        return revision

    def retry_job(self, job_id: int) -> int:
        job = self.repository.get_job(job_id)
        if job is None:
            raise AutoMedicalKnowledgeNotFoundError("Auto job was not found")
        if self.repository.get_active_job(job.topic_id) is not None:
            raise AutoMedicalKnowledgeConflictError("Topic already has an active Auto job")
        if job.status != "FAILED":
            raise AutoMedicalKnowledgeConflictError("Only failed Auto jobs can be retried")
        now = datetime.utcnow()
        self.repository.add_discovery(
            job_id=job.id,
            source_id=None,
            provider="AUTO_PIPELINE",
            trust_class="PUBMED",
            decision="SKIPPED",
            reason_code="FAILURE_HISTORY",
            metadata_json={
                "attempt": job.attempt_count,
                "failure_code": job.last_error_code,
                "pipeline_version": self._job_pipeline_version(job.id),
                "retried_at": now.isoformat(timespec="seconds"),
            },
            discovered_at=now,
        )
        job.attempt_count = 0
        if not self.repository.requeue_job(job.id, now=now):
            raise AutoMedicalKnowledgeConflictError("Auto job could not be retried")
        self.db.commit()
        return job.id
