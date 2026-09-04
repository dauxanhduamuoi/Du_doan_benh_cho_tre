from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from app.auto_medical_knowledge_schemas import AutoMedicalKnowledgeDraftProposal
from app.medical_knowledge_draft_schemas import DraftGenerationContext, SourceAssessment
from app.medical_knowledge_factors import FACTOR_LABELS_VI, normalize_factor
from app.services.medical_knowledge_population_policy import (
    PARENT_DISPLAYABLE_EVIDENCE,
    has_pediatric_direct_support,
)


AutoGenerationMode = Literal["AI_FULL", "SAFE_FALLBACK"]
SafeFallbackStage = Literal["INITIAL_VALIDATION", "CONTRACT_REPAIR"]

SAFE_FALLBACK_INITIAL_CONTRACT_CODES = frozenset(
    {
        "AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED",
        "AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED",
        "AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE",
    }
)
SAFE_FALLBACK_REPAIR_TRIGGER_CODES = frozenset(
    {
        *SAFE_FALLBACK_INITIAL_CONTRACT_CODES,
        "AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED",
        "AUTO_OUTPUT_PROVIDER_CONTENT_EMPTY",
        "AUTO_OUTPUT_PROVIDER_INCOMPLETE",
        "AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID",
        "AUTO_OUTPUT_JSON_INVALID",
        "AUTO_OUTPUT_SCHEMA_INVALID",
    }
)

_FORBIDDEN_CAUSAL_PHRASES = (
    "gây ra",
    "làm phát sinh",
    "là nguyên nhân",
    "làm trẻ mắc",
)
_FORBIDDEN_PERSONALIZED_PHRASES = (
    "con bạn",
    "trẻ của bạn",
    "bé nhà bạn",
    "con của bạn",
)


@dataclass(frozen=True)
class SafeFallbackSourceSnapshot:
    source_id: int
    evidence_content_id: int
    trust_class: str
    relevance: str
    population_relevance: str


@dataclass(frozen=True)
class SafeFallbackEligibilitySnapshot:
    """Only validated structured facts; failed model prose is never retained."""

    topic_id: int
    disease_group_id: str
    disease_name: str
    factor_type: str
    factor_key: str
    factor_value: str | None
    evidence_level: str
    evidence_scope: str
    sources: tuple[SafeFallbackSourceSnapshot, ...]

    @property
    def validated_source_ids(self) -> tuple[int, ...]:
        return tuple(item.source_id for item in self.sources)


@dataclass(frozen=True)
class SafeFallbackEligibility:
    eligible: bool
    reason_code: str
    snapshot: SafeFallbackEligibilitySnapshot | None = None


def is_safe_fallback_trigger(failure_code: str, stage: SafeFallbackStage) -> bool:
    """Central fail-closed allow-list for snapshot creation and fallback use."""

    if stage == "INITIAL_VALIDATION":
        return failure_code in SAFE_FALLBACK_INITIAL_CONTRACT_CODES
    return failure_code in SAFE_FALLBACK_REPAIR_TRIGGER_CODES


def safe_fallback_reason_code(failure_code: str) -> str:
    if failure_code in SAFE_FALLBACK_INITIAL_CONTRACT_CODES:
        return "CONTRACT_REPAIR_EXHAUSTED"
    if failure_code in {"AUTO_OUTPUT_JSON_INVALID", "AUTO_OUTPUT_SCHEMA_INVALID"}:
        return "REPAIR_STRUCTURAL_FAILURE"
    return "REPAIR_PROVIDER_FAILURE"


def evaluate_safe_fallback_eligibility(
    *,
    topic_id: int,
    context: DraftGenerationContext,
    selected,
    proposal: AutoMedicalKnowledgeDraftProposal,
    failure_code: str,
) -> SafeFallbackEligibility:
    """Build a bounded snapshot only after independent safety gates passed.

    The caller invokes this only after full semantic validation reached the
    final Numeric Claim V2 check and raised an allow-listed mechanical error.
    This function independently rechecks the evidence/status/provenance gates
    needed by Parent-safe Auto content.
    """

    if not is_safe_fallback_trigger(failure_code, "INITIAL_VALIDATION"):
        return SafeFallbackEligibility(False, "INITIAL_FAILURE_NOT_ALLOW_LISTED")
    if proposal.evidence_level not in PARENT_DISPLAYABLE_EVIDENCE:
        return SafeFallbackEligibility(False, "EVIDENCE_LEVEL_NOT_PARENT_DISPLAYABLE")
    if proposal.evidence_level in {"INSUFFICIENT", "CONFLICTING"}:
        return SafeFallbackEligibility(False, "EVIDENCE_STATUS_NOT_ELIGIBLE")
    try:
        factor = normalize_factor(
            factor_type=context.factor_type,
            factor_key=context.factor_key,
            factor_value=context.factor_value,
            weather_factor=context.weather_factor,
        )
    except ValueError:
        return SafeFallbackEligibility(False, "CANONICAL_FACTOR_INVALID")
    if not context.disease_group_id or not context.disease_group_name.strip():
        return SafeFallbackEligibility(False, "CANONICAL_DISEASE_INVALID")

    assessments = tuple(proposal.source_assessments)
    selected_ids = tuple(item[0].id for item in selected)
    assessed_ids = tuple(item.source_id for item in assessments)
    if not selected_ids or len(selected_ids) != len(set(selected_ids)):
        return SafeFallbackEligibility(False, "SELECTED_SOURCE_SET_INVALID")
    if set(selected_ids) != set(assessed_ids) or len(assessed_ids) != len(set(assessed_ids)):
        return SafeFallbackEligibility(False, "SOURCE_PROVENANCE_MISMATCH")
    if not any(item.relevance == "DIRECT" for item in assessments):
        return SafeFallbackEligibility(False, "DIRECT_EVIDENCE_REQUIRED")
    if not has_pediatric_direct_support(assessments):
        return SafeFallbackEligibility(False, "PEDIATRIC_DIRECT_SUPPORT_REQUIRED")
    if not any(item[4].pediatric > 0 for item in selected):
        return SafeFallbackEligibility(False, "PEDIATRIC_RELEVANCE_REQUIRED")

    assessment_by_source = {item.source_id: item for item in assessments}
    source_snapshots: list[SafeFallbackSourceSnapshot] = []
    for source, content, source_input, trust_class, signals in selected:
        assessment = assessment_by_source[source.id]
        if trust_class not in {"PUBMED", "PMC"}:
            return SafeFallbackEligibility(False, "TRUSTED_SOURCE_REQUIRED")
        if signals.disease <= 0:
            return SafeFallbackEligibility(False, "DISEASE_RELEVANCE_REQUIRED")
        if signals.factor <= 0:
            return SafeFallbackEligibility(False, "FACTOR_RELEVANCE_REQUIRED")
        if (
            source.id <= 0
            or content.id <= 0
            or content.source_id != source.id
            or source_input.source_id != source.id
            or not (source_input.evidence_text or "").strip()
        ):
            return SafeFallbackEligibility(False, "SOURCE_PROVENANCE_MISMATCH")
        source_snapshots.append(
            SafeFallbackSourceSnapshot(
                source_id=source.id,
                evidence_content_id=content.id,
                trust_class=trust_class,
                relevance=assessment.relevance,
                population_relevance=assessment.population_relevance,
            )
        )

    return SafeFallbackEligibility(
        True,
        "ELIGIBLE",
        SafeFallbackEligibilitySnapshot(
            topic_id=topic_id,
            disease_group_id=context.disease_group_id,
            disease_name=context.disease_group_name.strip(),
            factor_type=factor.factor_type,
            factor_key=factor.factor_key,
            factor_value=factor.factor_value,
            evidence_level=proposal.evidence_level,
            evidence_scope=proposal.evidence_scope,
            sources=tuple(source_snapshots),
        ),
    )


def factor_phrase_vi(snapshot: SafeFallbackEligibilitySnapshot) -> str:
    if snapshot.factor_type == "AGE":
        return f"nhóm tuổi {snapshot.factor_value}"
    if snapshot.factor_type == "SEX":
        return f"giới tính {str(snapshot.factor_value).lower()}"
    if snapshot.factor_type == "SEASONALITY":
        return "thời điểm trong năm"
    return FACTOR_LABELS_VI[(snapshot.factor_type, snapshot.factor_key)].lower()


class AutoSafeFallbackRenderer:
    """Render intentionally minimal Vietnamese content without a provider call."""

    def render(
        self, snapshot: SafeFallbackEligibilitySnapshot
    ) -> AutoMedicalKnowledgeDraftProposal:
        factor_phrase = factor_phrase_vi(snapshot)
        short = (
            "Các nguồn y khoa được chọn ghi nhận mối liên hệ giữa "
            f"{factor_phrase} và {snapshot.disease_name} ở trẻ em."
        )
        detail = (
            "Bằng chứng đã được kiểm tra cho chủ đề này cho thấy "
            f"{factor_phrase} có liên quan đến {snapshot.disease_name} trong phạm vi "
            "quần thể nghiên cứu. Thông tin được dùng để giải thích ở mức nhóm "
            "và không phải là chẩn đoán cho từng trẻ."
        )
        limitations = (
            "Mối liên hệ được ghi nhận không chứng minh quan hệ nhân quả. "
            "Đây là bản giải thích tự động rút gọn vì bản giải thích đầy đủ "
            "không vượt qua kiểm tra kỹ thuật đầu ra."
        )
        assessments = [
            SourceAssessment(
                source_id=item.source_id,
                relevance=item.relevance,
                note_vi=(
                    "Nguồn được chọn đáp ứng tiêu chí liên quan trực tiếp với chủ đề."
                    if item.relevance == "DIRECT"
                    else "Nguồn được chọn hỗ trợ phạm vi bằng chứng của chủ đề."
                ),
                population_relevance=item.population_relevance,
                population_note=(
                    "Nguồn được chọn đáp ứng tiêu chí hỗ trợ trực tiếp cho trẻ em."
                    if item.population_relevance == "PEDIATRIC_DIRECT"
                    else "Nguồn hỗ trợ phạm vi quần thể của chủ đề."
                ),
            )
            for item in snapshot.sources
        ]
        proposal = AutoMedicalKnowledgeDraftProposal(
            evidence_level=snapshot.evidence_level,
            evidence_scope=snapshot.evidence_scope,
            short_explanation_vi=short,
            detailed_explanation_vi=detail,
            limitations_vi=limitations,
            source_assessments=assessments,
            numeric_claims=[],
        )
        self._assert_safe(proposal, snapshot, factor_phrase)
        return proposal

    @staticmethod
    def _assert_safe(
        proposal: AutoMedicalKnowledgeDraftProposal,
        snapshot: SafeFallbackEligibilitySnapshot,
        factor_phrase: str,
    ) -> None:
        if proposal.numeric_claims:
            raise ValueError("Safe fallback must not contain numeric claims")
        if {item.source_id for item in proposal.source_assessments} != set(
            snapshot.validated_source_ids
        ):
            raise ValueError("Safe fallback source set changed")
        combined = " ".join(
            (
                proposal.short_explanation_vi or "",
                proposal.detailed_explanation_vi or "",
                proposal.limitations_vi or "",
            )
        ).lower()
        if any(value in combined for value in _FORBIDDEN_CAUSAL_PHRASES):
            raise ValueError("Safe fallback contains causal wording")
        if any(value in combined for value in _FORBIDDEN_PERSONALIZED_PHRASES):
            raise ValueError("Safe fallback contains personalized wording")
        noncanonical = combined.replace(snapshot.disease_name.lower(), "").replace(
            factor_phrase.lower(), ""
        )
        if re.search(r"\d", noncanonical):
            raise ValueError("Safe fallback contains a non-context numeric token")
