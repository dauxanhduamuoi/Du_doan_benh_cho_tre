"""Explicit article-owned semantic projection; retrieval metadata is never text."""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from app.services.medical_evidence_provider import NormalizedMedicalEvidence


def normalize_reviewed_text(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join("".join(
        char if unicodedata.category(char)[0] in {"L", "N"} else " "
        for char in value
    ).split())


def reviewed_phrase_present(normalized_text: str, phrase: str) -> bool:
    phrase = normalize_reviewed_text(phrase)
    return bool(phrase and f" {phrase} " in f" {normalized_text} ")


@dataclass(frozen=True)
class ReviewedSemanticUnit:
    field: str
    unit_index: int
    text: str
    controlled_term: bool = False


@dataclass(frozen=True)
class ReviewedSemanticMatchSpan:
    field: str
    unit_index: int
    matched_term: str
    unit_text: str


_SENTENCE_OR_CLAUSE_BOUNDARY = re.compile(
    r"(?:[.!?;]+|,\s+(?:and|but|which|meaning|whereas|while)\s+|"
    r"\s+(?:but|whereas|however|and is supported further by)\s+)",
    re.IGNORECASE,
)


def _text_units(field: str, value: str) -> tuple[ReviewedSemanticUnit, ...]:
    parts = _SENTENCE_OR_CLAUSE_BOUNDARY.split(value[:50_000])
    result: list[ReviewedSemanticUnit] = []
    for part in parts:
        normalized = normalize_reviewed_text(part)
        if normalized:
            result.append(ReviewedSemanticUnit(field, len(result), normalized))
    return tuple(result)


@dataclass(frozen=True)
class ReviewedSemanticEvidence:
    # Keep field boundaries: the end of a title must not form a phrase with
    # the beginning of an abstract (or a heading from another list entry).
    text_fields: tuple[str, ...]
    medical_headings: tuple[str, ...]
    units: tuple[ReviewedSemanticUnit, ...] = ()

    @classmethod
    def from_source(cls, source: NormalizedMedicalEvidence) -> ReviewedSemanticEvidence:
        units: list[ReviewedSemanticUnit] = []
        for field, value in (
            ("title", source.title),
            ("abstract", source.abstract_text),
            ("evidence_excerpt", source.evidence_text),
        ):
            if value:
                units.extend(_text_units(field, value))
        for field, values, controlled in (
            ("article_keyword", source.article_keywords, False),
            ("article_mesh", source.article_mesh_terms, True),
            ("article_subject", source.article_subject_terms, True),
        ):
            units.extend(
                ReviewedSemanticUnit(field, index, normalize_reviewed_text(value[:1000]), controlled)
                for index, value in enumerate(values)
                if normalize_reviewed_text(value[:1000])
            )
        return cls(
            text_fields=tuple(normalize_reviewed_text(value[:50_000]) for value in (
                source.title, source.abstract_text, source.evidence_text,
                *source.article_keywords,
            ) if value),
            medical_headings=tuple(normalize_reviewed_text(value[:1000]) for value in (
                *source.article_mesh_terms, *source.article_subject_terms,
            ) if value),
            units=tuple(units),
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return (*self.text_fields, *self.medical_headings)

    def contains(self, phrase: str) -> bool:
        return any(reviewed_phrase_present(value, phrase) for value in self.fields)

    def matching_spans(self, phrase: str) -> tuple[ReviewedSemanticMatchSpan, ...]:
        return tuple(
            ReviewedSemanticMatchSpan(unit.field, unit.unit_index, phrase, unit.text)
            for unit in self.units
            if reviewed_phrase_present(unit.text, phrase)
        )
