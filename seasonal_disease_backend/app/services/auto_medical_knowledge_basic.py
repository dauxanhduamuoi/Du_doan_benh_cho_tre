from __future__ import annotations

import re

from app.auto_medical_knowledge_schemas import (
    AutoBasicMedicalKnowledgeProposal,
    AutoMedicalKnowledgeDraftProposal,
)
from app.medical_knowledge_draft_schemas import SourceAssessment
from app.medical_knowledge_factors import FACTOR_LABELS_VI
from app.services.auto_evidence_qualification import AutoEvidenceQualificationSnapshot


BASIC_MAX_SUMMARY_CHARS = 600
_FORBIDDEN_TOKENS = re.compile(
    r"\d|%|\b(?:odds\s+ratio|relative\s+risk|hazard\s+ratio|confidence\s+interval|ci|or|rr|hr|p\s*[=<])\b",
    re.IGNORECASE,
)
_FORBIDDEN_PHRASES = (
    "gây ra",
    "là nguyên nhân",
    "dẫn đến",
    "chắc chắn",
    "cơ chế",
    "miễn dịch",
    "hormone",
    "chẩn đoán",
    "con bạn",
    "bé nhà bạn",
    "điều trị",
    "dùng thuốc",
    "nên cho trẻ",
    "khuyến nghị",
)


class AutoBasicValidationError(RuntimeError):
    def __init__(self, code: str, safe_detail: str, *, field: str | None = None):
        super().__init__(safe_detail)
        self.code = code
        self.safe_detail = safe_detail
        self.field = field


def validate_basic_proposal(
    proposal: AutoBasicMedicalKnowledgeProposal,
    snapshot: AutoEvidenceQualificationSnapshot,
) -> tuple[int, ...]:
    if not isinstance(proposal, AutoBasicMedicalKnowledgeProposal):
        raise AutoBasicValidationError(
            "AUTO_BASIC_SCHEMA_INVALID", "Basic output does not satisfy its schema."
        )
    if proposal.result == "INSUFFICIENT":
        return ()
    summary = (proposal.summary_vi or "").strip()
    if not summary or len(summary) > BASIC_MAX_SUMMARY_CHARS:
        raise AutoBasicValidationError(
            "AUTO_BASIC_SUMMARY_INVALID",
            "Basic summary is empty or exceeds its bounded length.",
            field="summary_vi",
        )
    if sum(summary.count(mark) for mark in ".!?") > 3:
        raise AutoBasicValidationError(
            "AUTO_BASIC_SUMMARY_INVALID",
            "Basic summary must contain at most three short sentences.",
            field="summary_vi",
        )
    if _FORBIDDEN_TOKENS.search(summary):
        raise AutoBasicValidationError(
            "AUTO_BASIC_NUMERIC_OR_STATISTICAL_LANGUAGE",
            "Basic summary contains numeric or statistical language.",
            field="summary_vi",
        )
    lowered = summary.casefold()
    if any(phrase in lowered for phrase in _FORBIDDEN_PHRASES):
        raise AutoBasicValidationError(
            "AUTO_BASIC_UNSAFE_LANGUAGE",
            "Basic summary contains causal, mechanism, diagnostic, or treatment language.",
            field="summary_vi",
        )
    allowed_ids = set(snapshot.validated_source_ids)
    returned_ids = tuple(proposal.source_ids)
    if not returned_ids or not set(returned_ids).issubset(allowed_ids):
        raise AutoBasicValidationError(
            "AUTO_BASIC_SOURCE_SET_MISMATCH",
            "Basic output references a source outside the qualified snapshot.",
            field="source_ids",
        )
    by_id = {item.source_id: item for item in snapshot.sources}
    if not any(
        by_id[source_id].population_relevance == "PEDIATRIC_DIRECT"
        for source_id in returned_ids
    ):
        raise AutoBasicValidationError(
            "AUTO_BASIC_PEDIATRIC_SOURCE_REQUIRED",
            "Basic output must retain qualified pediatric provenance.",
            field="source_ids",
        )
    return returned_ids


def basic_factor_phrase_vi(snapshot: AutoEvidenceQualificationSnapshot) -> str:
    if snapshot.factor_type == "AGE":
        return "nhóm tuổi đã chọn"
    if snapshot.factor_type == "SEX":
        return "nhóm giới tính đã chọn"
    if snapshot.factor_type == "SEASONALITY":
        return "thời điểm trong năm"
    return FACTOR_LABELS_VI[(snapshot.factor_type, snapshot.factor_key)].lower()


def _assessments(
    snapshot: AutoEvidenceQualificationSnapshot, source_ids: tuple[int, ...]
) -> list[SourceAssessment]:
    allowed = set(source_ids)
    return [item.assessment() for item in snapshot.sources if item.source_id in allowed]


def render_basic_supported(
    proposal: AutoBasicMedicalKnowledgeProposal,
    snapshot: AutoEvidenceQualificationSnapshot,
    source_ids: tuple[int, ...],
) -> AutoMedicalKnowledgeDraftProposal:
    factor = basic_factor_phrase_vi(snapshot)
    return AutoMedicalKnowledgeDraftProposal(
        evidence_level=snapshot.evidence_level,
        evidence_scope=snapshot.evidence_scope,
        short_explanation_vi=(
            "Các nguồn y khoa được hệ thống tìm thấy ghi nhận mối liên hệ giữa "
            f"{factor} và {snapshot.disease_name} ở trẻ em."
        ),
        detailed_explanation_vi=proposal.summary_vi,
        limitations_vi=(
            "Thông tin này phản ánh mối liên hệ được ghi nhận trong phạm vi các "
            "nghiên cứu được tìm thấy và không chứng minh yếu tố này trực tiếp "
            "gây bệnh. Đây không phải là chẩn đoán cho từng trẻ."
        ),
        source_assessments=_assessments(snapshot, source_ids),
        numeric_claims=[],
    )


def render_basic_insufficient(
    snapshot: AutoEvidenceQualificationSnapshot,
) -> AutoMedicalKnowledgeDraftProposal:
    return AutoMedicalKnowledgeDraftProposal(
        evidence_level="INSUFFICIENT",
        evidence_scope=snapshot.evidence_scope,
        short_explanation_vi=None,
        detailed_explanation_vi=None,
        limitations_vi="Basic AI did not support a cautious qualitative explanation.",
        source_assessments=[item.assessment() for item in snapshot.sources],
        numeric_claims=[],
    )
