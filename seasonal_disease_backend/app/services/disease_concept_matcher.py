"""Small provider-neutral concept gate for Reviewed discovery, never Auto."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
import json
from pathlib import Path

from app.services.reviewed_semantic_evidence import (
    ReviewedSemanticEvidence, ReviewedSemanticMatchSpan, normalize_reviewed_text,
)


class DiseaseMatchStrength(str, Enum):
    STRONG = "STRONG"
    WEAK = "WEAK"
    NONE = "NONE"


@dataclass(frozen=True)
class DiseaseConceptMatch:
    strength: DiseaseMatchStrength
    alias: str | None = None
    reason: str = "NO_ARTICLE_EVIDENCE"
    spans: tuple[ReviewedSemanticMatchSpan, ...] = ()


@lru_cache(maxsize=1)
def _configuration() -> dict:
    return json.loads(Path(__file__).with_name("reviewed_disease_concepts.json").read_text(encoding="utf-8"))


class DiseaseConceptMatcher:
    def __init__(self, aliases: tuple[str, ...], *, configuration: dict | None = None):
        config = configuration if configuration is not None else _configuration()
        self.aliases = tuple(dict.fromkeys(alias for alias in aliases if normalize_reviewed_text(alias)))
        self.ambiguous = frozenset(
            normalize_reviewed_text(alias)
            for concept in config["concepts"] for alias in concept["ambiguous_aliases"]
        )
        self.prefixes = tuple(config["clinical_prefixes"])
        self.suffixes = tuple(config["clinical_suffixes"])

    def match(self, evidence: ReviewedSemanticEvidence) -> DiseaseConceptMatch:
        weak_alias = None
        for alias in self.aliases:
            normalized = normalize_reviewed_text(alias)
            # An exact ARTICLE-owned medical heading disambiguates a concept.
            # Request-builder MeSH and arbitrary provider metadata never enter here.
            if normalized in evidence.medical_headings:
                return DiseaseConceptMatch(
                    DiseaseMatchStrength.STRONG, alias, "ARTICLE_MEDICAL_HEADING",
                    # The controlled heading establishes concept strength, but
                    # relation analysis still needs every article-owned text
                    # occurrence to locate the disease beside a factor.
                    evidence.matching_spans(alias),
                )
            if not evidence.contains(alias):
                continue
            if normalized not in self.ambiguous:
                return DiseaseConceptMatch(
                    DiseaseMatchStrength.STRONG, alias, "DISEASE_PHRASE",
                    evidence.matching_spans(alias),
                )
            # Require a tight clinical phrase, not medical words elsewhere in
            # the same COVID/agriculture abstract. No disease/provider branches.
            phrases = (
                *(f"{prefix} {alias}" for prefix in self.prefixes),
                *(f"{alias} {suffix}" for suffix in self.suffixes),
            )
            if any(evidence.contains(phrase) for phrase in phrases):
                return DiseaseConceptMatch(
                    DiseaseMatchStrength.STRONG, alias, "CLINICAL_DISEASE_PHRASE",
                    evidence.matching_spans(alias),
                )
            weak_alias = weak_alias or alias
        return DiseaseConceptMatch(
            DiseaseMatchStrength.WEAK if weak_alias else DiseaseMatchStrength.NONE,
            weak_alias,
            "AMBIGUOUS_ALIAS_ONLY" if weak_alias else "NO_ARTICLE_EVIDENCE",
            evidence.matching_spans(weak_alias) if weak_alias else (),
        )
