from __future__ import annotations

from dataclasses import dataclass

from app.medical_knowledge_draft_schemas import DraftGenerationContext, SourceAssessment
from app.medical_knowledge_factors import normalize_factor
from app.services.auto_evidence_relevance import pediatric_relevance


TRUSTED_AUTO_SOURCE_CLASSES = frozenset({"PUBMED", "PMC"})
EVIDENCE_GATE_FAILURES = frozenset(
    {
        "NO_SEARCH_RESULTS",
        "NO_DISEASE_RELEVANT_SOURCE",
        "NO_FACTOR_RELEVANT_SOURCE",
        "NO_PEDIATRIC_RELEVANT_SOURCE",
        "NO_USABLE_EVIDENCE",
        "CONFLICTING_EVIDENCE",
        "TRUSTED_SOURCE_REQUIRED",
        "SOURCE_PROVENANCE_MISMATCH",
    }
)


@dataclass(frozen=True)
class AutoQualifiedEvidenceSource:
    source_id: int
    evidence_content_id: int
    trust_class: str
    relevance: str
    relevance_note: str
    population_relevance: str
    population_note: str

    def assessment(self) -> SourceAssessment:
        return SourceAssessment(
            source_id=self.source_id,
            relevance=self.relevance,
            note_vi=self.relevance_note,
            population_relevance=self.population_relevance,
            population_note=self.population_note,
        )


@dataclass(frozen=True)
class AutoEvidenceQualificationSnapshot:
    """Provider-independent canonical evidence facts shared by every tier."""

    topic_id: int
    disease_group_id: str
    disease_name: str
    factor_type: str
    factor_key: str
    factor_value: str | None
    evidence_level: str
    evidence_scope: str
    sources: tuple[AutoQualifiedEvidenceSource, ...]

    @property
    def validated_source_ids(self) -> tuple[int, ...]:
        return tuple(item.source_id for item in self.sources)

    @property
    def validated_evidence_content_ids(self) -> tuple[int, ...]:
        return tuple(item.evidence_content_id for item in self.sources)

    @property
    def pediatric_support(self) -> bool:
        return any(
            item.population_relevance == "PEDIATRIC_DIRECT" for item in self.sources
        )


@dataclass(frozen=True)
class AutoEvidenceQualificationResult:
    eligible: bool
    reason_code: str
    snapshot: AutoEvidenceQualificationSnapshot | None = None


def qualify_auto_evidence(
    *,
    topic_id: int,
    context: DraftGenerationContext,
    selected,
    discovery_reason: str | None = None,
) -> AutoEvidenceQualificationResult:
    """Apply the existing deterministic discovery/provenance safety policy.

    No provider output is accepted by this boundary. A failed Strict proposal
    therefore cannot make evidence eligible and cannot contaminate Basic.
    """

    if discovery_reason in EVIDENCE_GATE_FAILURES:
        return AutoEvidenceQualificationResult(False, discovery_reason)
    try:
        factor = normalize_factor(
            factor_type=context.factor_type,
            factor_key=context.factor_key,
            factor_value=context.factor_value,
            weather_factor=context.weather_factor,
        )
    except ValueError:
        return AutoEvidenceQualificationResult(False, "CANONICAL_FACTOR_INVALID")
    if topic_id <= 0 or not context.disease_group_id or not context.disease_group_name.strip():
        return AutoEvidenceQualificationResult(False, "CANONICAL_DISEASE_INVALID")
    if not selected:
        return AutoEvidenceQualificationResult(False, "NO_USABLE_EVIDENCE")

    source_ids = [item[0].id for item in selected]
    content_ids = [item[1].id for item in selected]
    if (
        any(value <= 0 for value in source_ids + content_ids)
        or len(source_ids) != len(set(source_ids))
        or len(content_ids) != len(set(content_ids))
    ):
        return AutoEvidenceQualificationResult(False, "SOURCE_PROVENANCE_MISMATCH")

    snapshots: list[AutoQualifiedEvidenceSource] = []
    pediatric_found = False
    for source, content, source_input, trust_class, signals in selected:
        if trust_class not in TRUSTED_AUTO_SOURCE_CLASSES:
            return AutoEvidenceQualificationResult(False, "TRUSTED_SOURCE_REQUIRED")
        if signals.disease <= 0:
            return AutoEvidenceQualificationResult(False, "NO_DISEASE_RELEVANT_SOURCE")
        if signals.factor <= 0:
            return AutoEvidenceQualificationResult(False, "NO_FACTOR_RELEVANT_SOURCE")
        evidence_text = (source_input.evidence_text or "").strip()
        if (
            content.source_id != source.id
            or source_input.source_id != source.id
            or source_input.evidence_content_id != content.id
            or not evidence_text
        ):
            return AutoEvidenceQualificationResult(False, "SOURCE_PROVENANCE_MISMATCH")
        pediatric_direct = signals.pediatric > 0 and pediatric_relevance(evidence_text) > 0
        pediatric_found = pediatric_found or pediatric_direct
        snapshots.append(
            AutoQualifiedEvidenceSource(
                source_id=source.id,
                evidence_content_id=content.id,
                trust_class=trust_class,
                relevance="DIRECT",
                relevance_note="Nguồn trực tiếp đánh giá yếu tố và nhóm bệnh đã chọn.",
                population_relevance=(
                    "PEDIATRIC_DIRECT" if pediatric_direct else "MIXED_AGE"
                ),
                population_note=(
                    "Nguồn có bằng chứng trực tiếp cho quần thể trẻ em."
                    if pediatric_direct
                    else "Nguồn hỗ trợ chủ đề nhưng không phải nguồn nhi khoa trực tiếp."
                ),
            )
        )
    if not pediatric_found:
        return AutoEvidenceQualificationResult(False, "NO_PEDIATRIC_RELEVANT_SOURCE")

    return AutoEvidenceQualificationResult(
        True,
        "ELIGIBLE",
        AutoEvidenceQualificationSnapshot(
            topic_id=topic_id,
            disease_group_id=context.disease_group_id,
            disease_name=context.disease_group_name.strip(),
            factor_type=factor.factor_type,
            factor_key=factor.factor_key,
            factor_value=factor.factor_value,
            # The deterministic gate establishes a cautious displayable floor;
            # Strict may still produce a stronger, independently validated level.
            evidence_level="LIMITED_OR_INDIRECT",
            evidence_scope="PARTIAL_GROUP",
            sources=tuple(snapshots),
        ),
    )
