"""Provider- and disease-independent relation semantics for Reviewed search."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.services.disease_concept_matcher import DiseaseConceptMatch
from app.services.reviewed_factor_matcher import ReviewedFactorMatch
from app.services.reviewed_semantic_evidence import (
    ReviewedSemanticEvidence, reviewed_phrase_present,
)


class DiseaseFactorRelationStatus(str, Enum):
    RELATED_TO_TOPIC = "RELATED_TO_TOPIC"
    INCIDENTAL = "INCIDENTAL"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class DiseaseFactorRelationMatch:
    status: DiseaseFactorRelationStatus
    reason: str
    field: str | None = None
    unit_index: int | None = None


# Semantic-role policy, shared by every provider and disease. Terms describe
# outcomes/pathways rather than a disease-specific vocabulary.
_EPIDEMIOLOGY_ROLES = (
    "incidence", "outbreak", "outbreaks", "occurrence", "prevalence", "risk",
    "transmission", "epidemiology", "infection", "infections", "severity",
    "timing", "seasonality", "mortality", "case counts", "disease burden",
)
_VECTOR_ROLES = (
    "vector", "vectors", "flea", "fleas", "vector survival", "vector development",
    "vector activity", "vector abundance",
)
_ECOLOGY_ROLES = (
    "pathogen", "pathogens", "bacterium", "bacteria", "host", "hosts",
    "reservoir", "reservoirs", "ecology", "survival", "growth",
)
_ANCILLARY_STORAGE_ROLES = (
    "storage", "stored", "formulation", "stability", "stable", "shelf life",
    "cold chain", "vial", "vials", "manufacturing", "thermostressed",
)
_ANCILLARY_PROCEDURAL_ROLES = (
    "assay", "calibration", "calibrated", "sample storage", "samples were stored",
    "incubated", "incubation", "laboratory condition", "test chamber",
)


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(reviewed_phrase_present(text, phrase) for phrase in phrases)


class DiseaseFactorRelationMatcher:
    """Decide whether a factor occurrence belongs to the disease topic."""

    def match(
        self,
        evidence: ReviewedSemanticEvidence,
        disease: DiseaseConceptMatch,
        factor: ReviewedFactorMatch,
    ) -> DiseaseFactorRelationMatch:
        if not factor.matched:
            return DiseaseFactorRelationMatch(
                DiseaseFactorRelationStatus.UNRESOLVED, "FACTOR_NOT_PRESENT"
            )

        disease_units = {(span.field, span.unit_index) for span in disease.spans}
        disease_controlled = any(
            span.field in {"article_mesh", "article_subject"} for span in disease.spans
        )
        factor_controlled = any(
            span.field in {"article_mesh", "article_subject"} for span in factor.spans
        )
        if disease_controlled and factor_controlled:
            return DiseaseFactorRelationMatch(
                DiseaseFactorRelationStatus.RELATED_TO_TOPIC,
                "ARTICLE_CONTROLLED_TOPIC_TERMS",
            )

        title_topic = any(
            unit.field == "title"
            and (unit.field, unit.unit_index) in disease_units
            and _contains_any(
                unit.text, (*_EPIDEMIOLOGY_ROLES, *_VECTOR_ROLES, *_ECOLOGY_ROLES)
            )
            for unit in evidence.units
        )
        units_by_key = {
            (unit.field, unit.unit_index): unit for unit in evidence.units
        }
        incidental: DiseaseFactorRelationMatch | None = None
        for span in factor.spans:
            text = span.unit_text
            previous = units_by_key.get((span.field, span.unit_index - 1))
            ancillary_window = f"{previous.text} {text}" if previous is not None else text
            same_unit_disease = (span.field, span.unit_index) in disease_units
            ancillary_storage = _contains_any(ancillary_window, _ANCILLARY_STORAGE_ROLES)
            ancillary_procedure = _contains_any(ancillary_window, _ANCILLARY_PROCEDURAL_ROLES)
            if (
                span.field == "title"
                and same_unit_disease
                and not (ancillary_storage or ancillary_procedure)
            ):
                return DiseaseFactorRelationMatch(
                    DiseaseFactorRelationStatus.RELATED_TO_TOPIC,
                    "TITLE_DISEASE_FACTOR_TOPIC",
                    span.field,
                    span.unit_index,
                )
            epidemiology = _contains_any(text, _EPIDEMIOLOGY_ROLES)
            vector = _contains_any(text, _VECTOR_ROLES)
            ecology = _contains_any(text, _ECOLOGY_ROLES)
            pathogen_or_host = _contains_any(
                text, ("pathogen", "pathogens", "bacterium", "bacteria", "host", "hosts",
                       "reservoir", "reservoirs")
            )
            local_topic_entity = same_unit_disease or vector or pathogen_or_host

            biology_pathway = vector or (ecology and pathogen_or_host)
            topic_relation = biology_pathway or (
                epidemiology
                and (local_topic_entity or title_topic)
                and not (ancillary_storage or ancillary_procedure)
            )
            if topic_relation:
                reason = (
                    "VECTOR_ECOLOGY_CONTEXT" if vector
                    else "PATHOGEN_HOST_ECOLOGY_CONTEXT" if biology_pathway
                    else "EPIDEMIOLOGY_CONTEXT"
                )
                return DiseaseFactorRelationMatch(
                    DiseaseFactorRelationStatus.RELATED_TO_TOPIC,
                    reason,
                    span.field,
                    span.unit_index,
                )
            if ancillary_storage or ancillary_procedure:
                incidental = DiseaseFactorRelationMatch(
                    DiseaseFactorRelationStatus.INCIDENTAL,
                    "STORAGE_FORMULATION_CONTEXT" if ancillary_storage
                    else "PROCEDURAL_LAB_CONTEXT",
                    span.field,
                    span.unit_index,
                )

        return incidental or DiseaseFactorRelationMatch(
            DiseaseFactorRelationStatus.UNRESOLVED,
            "INSUFFICIENT_LOCAL_TOPIC_CONTEXT",
            factor.spans[0].field,
            factor.spans[0].unit_index,
        )
