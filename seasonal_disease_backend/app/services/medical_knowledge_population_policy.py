from __future__ import annotations

from collections.abc import Iterable

from app.medical_knowledge_draft_schemas import SourceAssessment


PARENT_DISPLAYABLE_EVIDENCE = {"SUPPORTED", "LIMITED_OR_INDIRECT"}
PARENT_TIER2_EVIDENCE_LEVEL_REQUIRED = "PARENT_TIER2_EVIDENCE_LEVEL_NOT_DISPLAYABLE"
PARENT_TIER2_PEDIATRIC_SUPPORT_REQUIRED = "PARENT_TIER2_PEDIATRIC_SUPPORT_REQUIRED"
LEGACY_POPULATION_NOTE = "Legacy revision has no stored population assessment."


def stored_source_assessment(link) -> SourceAssessment | None:
    """Parse an immutable revision-source assessment, failing closed on corruption."""

    relevance_note = (link.relevance_note or "").strip()
    if ":" not in relevance_note:
        return None
    relevance, note = (part.strip() for part in relevance_note.split(":", 1))
    if (relevance == "DIRECT") != (link.source_role == "PRIMARY"):
        return None
    population_relevance = (link.population_relevance or "UNKNOWN").strip()
    population_note = (link.population_note or "").strip() or LEGACY_POPULATION_NOTE
    try:
        return SourceAssessment(
            source_id=link.source_id,
            relevance=relevance,
            note_vi=note,
            population_relevance=population_relevance,
            population_note=population_note,
        )
    except ValueError:
        return None


def has_pediatric_direct_support(assessments: Iterable[SourceAssessment]) -> bool:
    """Require one source that independently satisfies both safety dimensions."""

    return any(
        item.relevance == "DIRECT" and item.population_relevance == "PEDIATRIC_DIRECT"
        for item in assessments
    )


def parent_tier2_ineligibility_reasons(
    evidence_level: str, assessments: Iterable[SourceAssessment]
) -> list[str]:
    items = list(assessments)
    reasons: list[str] = []
    if evidence_level not in PARENT_DISPLAYABLE_EVIDENCE:
        reasons.append(PARENT_TIER2_EVIDENCE_LEVEL_REQUIRED)
    if not has_pediatric_direct_support(items):
        reasons.append(PARENT_TIER2_PEDIATRIC_SUPPORT_REQUIRED)
    return reasons
