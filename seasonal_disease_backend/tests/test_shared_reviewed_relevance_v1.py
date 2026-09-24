from __future__ import annotations

from datetime import datetime

from app.services.medical_evidence_provider import (
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQuery,
)
from app.services.reviewed_evidence_relevance import (
    ReviewedEvidenceRelevance,
    ReviewedPediatricMatch,
    ReviewedRelevanceClass,
    normalize_reviewed_text,
)


NOW = datetime(2026, 9, 14, 10, 0, 0)


def context(*disease_terms: str, factor_key: str = "humidity"):
    return ReviewedMedicalEvidenceQuery(
        disease_terms=disease_terms or ("Plague",),
        factor_type="WEATHER",
        factor_key=factor_key,
        factor_value=None,
        weather_factor=factor_key,
        year_from=None,
        year_to=None,
    )


def source(provider_id: str, title: str, *, abstract: str = ""):
    return NormalizedMedicalEvidence(
        provider_id=provider_id,
        source_kind=MedicalEvidenceSourceKind.RESEARCH_ARTICLE,
        external_id=f"{provider_id}-{abs(hash((title, abstract)))}",
        title=title,
        abstract_text=abstract,
        canonical_url=f"https://example.test/{provider_id.lower()}/item",
        retrieved_at=NOW,
    )


def classify(title: str, *, provider_id: str = "PUBMED", query_level: str | None = None):
    return ReviewedEvidenceRelevance(context()).classify(
        source(provider_id, title), query_level=query_level
    )


def test_01_disease_and_factor_is_direct():
    assessment = classify("Human plague risk associated with relative humidity")
    assert assessment.classification is ReviewedRelevanceClass.DIRECT
    assert assessment.disease_match and assessment.factor_match


def test_02_disease_without_factor_is_related():
    assessment = classify("Pediatric plague vaccination guidance")
    assert assessment.classification is ReviewedRelevanceClass.RELATED
    assert assessment.pediatric_match is ReviewedPediatricMatch.PEDIATRIC_MATCH


def test_03_factor_without_disease_is_rejected():
    assert classify("Smart agriculture sensors for humidity").classification is ReviewedRelevanceClass.REJECT


def test_04_neither_disease_nor_factor_is_rejected():
    assert classify("Violence prevention for children").classification is ReviewedRelevanceClass.REJECT


def test_05_case_and_punctuation_are_normalized_with_token_boundaries():
    assessment = classify("HUMAN PLAGUE: effects of HUMIDITY!")
    assert assessment.classification is ReviewedRelevanceClass.DIRECT
    assert classify("Plagued crops and dehumidity devices").classification is ReviewedRelevanceClass.REJECT


def test_06_hyphen_normalization_is_deterministic():
    classifier = ReviewedEvidenceRelevance(context("Hand foot and mouth disease"))
    assessment = classifier.classify(
        source("PUBMED", "HAND-FOOT-AND-MOUTH DISEASE under high humidity")
    )
    assert assessment.classification is ReviewedRelevanceClass.DIRECT


def test_07_unicode_nfkc_and_casefold_are_used():
    classifier = ReviewedEvidenceRelevance(context("Café syndrome"))
    assessment = classifier.classify(
        source("WHO", "CAFE\u0301 SYNDROME — HUMIDITY")
    )
    assert normalize_reviewed_text("ＣＡＦÉ") == "café"
    assert assessment.classification is ReviewedRelevanceClass.DIRECT


def test_08_canonical_disease_context_aliases_are_available():
    classifier = ReviewedEvidenceRelevance(
        context("Other arthropod", "Lyme disease", "Tick-borne relapsing fever")
    )
    assessment = classifier.classify(
        source("FAKE_CDC", "Tick-borne relapsing fever and humidity")
    )
    assert assessment.classification is ReviewedRelevanceClass.DIRECT
    assert assessment.matched_disease_alias == "Tick-borne relapsing fever"


def test_09_reviewed_factor_vocabulary_includes_moisture():
    assessment = classify("Moisture patterns associated with human plague")
    assert assessment.classification is ReviewedRelevanceClass.DIRECT
    assert assessment.matched_factor_term == "moisture"


def test_10_direct_query_level_cannot_override_missing_disease():
    assessment = classify(
        "SARS-CoV-2 and environmental temperature",
        query_level="DIRECT_DISEASE_FACTOR_PEDIATRIC",
    )
    assert assessment.classification is ReviewedRelevanceClass.REJECT


def test_11_related_query_level_cannot_make_wrong_disease_relevant():
    assessment = classify(
        "Smart agriculture humidity monitoring",
        query_level="RELATED_DISEASE_PEDIATRIC",
    )
    assert assessment.classification is ReviewedRelevanceClass.REJECT


def test_12_provider_id_does_not_change_classification():
    classes = {
        classify("Human plague humidity evidence", provider_id=provider).classification
        for provider in ("PUBMED", "WHO", "FAKE_CDC")
    }
    assert classes == {ReviewedRelevanceClass.DIRECT}


def test_13_pubmed_and_who_identical_semantics_classify_identically():
    classifier = ReviewedEvidenceRelevance(context())
    pubmed = classifier.classify(source("PUBMED", "Plague vaccine effectiveness"))
    who = classifier.classify(source("WHO", "Plague vaccine effectiveness"))
    assert pubmed.classification is who.classification is ReviewedRelevanceClass.RELATED


def test_14_fake_future_cdc_uses_the_same_classifier_without_a_branch():
    classifier = ReviewedEvidenceRelevance(context())
    assessments = [
        classifier.classify(source("FAKE_CDC", "Human plague humidity evidence")),
        classifier.classify(source("FAKE_CDC", "Plague vaccination guidance")),
        classifier.classify(source("FAKE_CDC", "Humidity in smart agriculture")),
    ]
    assert [item.classification for item in assessments] == [
        ReviewedRelevanceClass.DIRECT,
        ReviewedRelevanceClass.RELATED,
        ReviewedRelevanceClass.REJECT,
    ]
