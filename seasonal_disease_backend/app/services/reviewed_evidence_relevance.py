from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Iterable
from app.services.disease_concept_matcher import DiseaseConceptMatcher, DiseaseMatchStrength
from app.services.disease_factor_relation_matcher import (
    DiseaseFactorRelationMatcher, DiseaseFactorRelationStatus,
)
from app.services.reviewed_factor_matcher import ReviewedFactorMatcher
from app.services.reviewed_semantic_evidence import (
    ReviewedSemanticEvidence, normalize_reviewed_text,
)

from app.services.auto_evidence_relevance import (
    PEDIATRIC_TERMS,
    build_disease_aliases,
    reviewed_factor_vocabulary,
)
from app.services.medical_evidence_provider import (
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQuery,
)


class ReviewedRelevanceClass(str, Enum):
    DIRECT = "DIRECT_TOPIC"
    RELATED = "RELATED_CONTEXT"
    REJECT = "REJECT"


class ReviewedPediatricMatch(str, Enum):
    PEDIATRIC_MATCH = "PEDIATRIC_MATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ReviewedRelevanceAssessment:
    classification: ReviewedRelevanceClass
    disease_match: bool
    factor_match: bool
    pediatric_match: ReviewedPediatricMatch
    matched_disease_alias: str | None = None
    matched_factor_term: str | None = None
    disease_strength: DiseaseMatchStrength = DiseaseMatchStrength.NONE
    factor_match_field: str | None = None
    relation_status: DiseaseFactorRelationStatus = DiseaseFactorRelationStatus.UNRESOLVED
    relation_reason: str = "FACTOR_NOT_PRESENT"

    @property
    def accepted(self) -> bool:
        return self.classification is not ReviewedRelevanceClass.REJECT


def _unique_phrases(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_reviewed_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(value)
    return tuple(result)


class ReviewedEvidenceRelevance:
    """Provider-neutral, deterministic final relevance for Reviewed search."""

    def __init__(self, context: ReviewedMedicalEvidenceQuery):
        catalog_aliases = build_disease_aliases(
            context.disease_terms[0], context.disease_terms[1:]
        )
        self.disease_aliases = _unique_phrases(
            (*context.disease_terms, *catalog_aliases.strict, *catalog_aliases.broad)
        )
        self.disease_matcher = DiseaseConceptMatcher(self.disease_aliases)
        topic = SimpleNamespace(
            factor_type=context.factor_type,
            factor_key=context.factor_key,
            factor_value=context.factor_value,
            weather_factor=context.weather_factor,
        )
        self.factor_terms = _unique_phrases(reviewed_factor_vocabulary(topic))
        self.factor_matcher = ReviewedFactorMatcher(self.factor_terms)
        self.relation_matcher = DiseaseFactorRelationMatcher()
        self.pediatric_terms = _unique_phrases(PEDIATRIC_TERMS)

    def classify(
        self,
        source: NormalizedMedicalEvidence,
        *,
        query_level: str | None = None,
    ) -> ReviewedRelevanceAssessment:
        # Query provenance is accepted for diagnostic call-site clarity only;
        # it can never override the evidence text's disease/factor signals.
        del query_level
        evidence = ReviewedSemanticEvidence.from_source(source)
        disease = self.disease_matcher.match(evidence)
        matched_disease = disease.alias
        strong_disease = disease.strength is DiseaseMatchStrength.STRONG
        factor = self.factor_matcher.match(evidence)
        matched_factor = factor.matched_term
        relation = self.relation_matcher.match(evidence, disease, factor)
        pediatric = any(
            evidence.contains(term) for term in self.pediatric_terms
        )
        if not strong_disease:
            classification = ReviewedRelevanceClass.REJECT
        elif factor.matched and relation.status is DiseaseFactorRelationStatus.RELATED_TO_TOPIC:
            classification = ReviewedRelevanceClass.DIRECT
        else:
            classification = ReviewedRelevanceClass.RELATED
        return ReviewedRelevanceAssessment(
            classification=classification,
            disease_match=strong_disease,
            factor_match=matched_factor is not None,
            pediatric_match=(
                ReviewedPediatricMatch.PEDIATRIC_MATCH
                if pediatric
                else ReviewedPediatricMatch.UNKNOWN
            ),
            matched_disease_alias=matched_disease,
            matched_factor_term=matched_factor,
            disease_strength=disease.strength,
            factor_match_field=factor.first_field,
            relation_status=relation.status,
            relation_reason=relation.reason,
        )
