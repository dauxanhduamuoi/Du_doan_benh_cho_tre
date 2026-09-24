"""Locate selected factors in explicit article-owned semantic units."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.reviewed_semantic_evidence import (
    ReviewedSemanticEvidence, ReviewedSemanticMatchSpan,
)


@dataclass(frozen=True)
class ReviewedFactorMatch:
    matched: bool
    matched_term: str | None = None
    spans: tuple[ReviewedSemanticMatchSpan, ...] = ()

    @property
    def first_field(self) -> str | None:
        return self.spans[0].field if self.spans else None


class ReviewedFactorMatcher:
    def __init__(self, factor_terms: tuple[str, ...]):
        self.factor_terms = factor_terms

    def match(self, evidence: ReviewedSemanticEvidence) -> ReviewedFactorMatch:
        for term in self.factor_terms:
            spans = evidence.matching_spans(term)
            if spans:
                return ReviewedFactorMatch(True, term, spans)
        return ReviewedFactorMatch(False)
