from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from app.services.disease_factor_relation_matcher import DiseaseFactorRelationStatus
from app.services.medical_evidence_provider import MedicalEvidenceSourceKind, NormalizedMedicalEvidence
from app.services.pubmed_client import PubMedClient
from app.services.pubmed_evidence_provider import PubMedMedicalEvidenceProvider
from app.services.reviewed_evidence_relevance import ReviewedEvidenceRelevance
from test_shared_reviewed_relevance_v1 import context


def evidence(title: str, abstract: str = "", *, provider: str = "PUBMED", **changes):
    item = NormalizedMedicalEvidence(
        provider_id=provider,
        source_kind=MedicalEvidenceSourceKind.RESEARCH_ARTICLE,
        external_id=f"{provider}-fixture",
        title=title,
        abstract_text=abstract,
    )
    return replace(item, **changes)


def assess(title: str, abstract: str = "", *, provider: str = "PUBMED", **changes):
    return ReviewedEvidenceRelevance(context()).classify(
        evidence(title, abstract, provider=provider, **changes)
    )


@pytest.mark.parametrize("abstract,reason", [
    ("Relative humidity was associated with the occurrence of human plague outbreaks.", "EPIDEMIOLOGY_CONTEXT"),
    ("High humidity increased the risk of human plague outbreaks.", "EPIDEMIOLOGY_CONTEXT"),
    ("Relative humidity affected survival of flea vectors of human plague.", "VECTOR_ECOLOGY_CONTEXT"),
    ("Humidity altered pathogen survival and growth in a human plague ecology study.", "PATHOGEN_HOST_ECOLOGY_CONTEXT"),
])
def test_related_to_topic_local_context(abstract, reason):
    result = assess("Human plague study", abstract)
    assert result.classification.value == "DIRECT_TOPIC"
    assert result.relation_status is DiseaseFactorRelationStatus.RELATED_TO_TOPIC
    assert result.relation_reason == reason


@pytest.mark.parametrize("abstract,reason", [
    ("The vaccine was stored at 75% relative humidity.", "STORAGE_FORMULATION_CONTEXT"),
    ("Formulation stability was evaluated at 75% relative humidity.", "STORAGE_FORMULATION_CONTEXT"),
    ("Samples were incubated under controlled relative humidity as an assay condition.", "PROCEDURAL_LAB_CONTEXT"),
])
def test_ancillary_factor_is_incidental(abstract, reason):
    result = assess("Human plague vaccine candidate", abstract)
    assert result.classification.value == "RELATED_CONTEXT"
    assert result.factor_match
    assert result.relation_status is DiseaseFactorRelationStatus.INCIDENTAL
    assert result.relation_reason == reason


def test_unresolved_factor_never_becomes_direct():
    result = assess("Human plague review", "The report also recorded relative humidity.")
    assert result.classification.value == "RELATED_CONTEXT"
    assert result.relation_status is DiseaseFactorRelationStatus.UNRESOLVED


def test_ancillary_title_is_not_promoted_by_title_colocation():
    result = assess(
        "Formulation stability of a human plague vaccine at 75% relative humidity"
    )
    assert result.classification.value == "RELATED_CONTEXT"
    assert result.relation_status is DiseaseFactorRelationStatus.INCIDENTAL


def test_clause_boundary_prevents_borrowing_disease_context():
    result = assess(
        "Human plague vaccine",
        "The vaccine prevents human plague; however formulation stability was tested at 75% relative humidity.",
    )
    assert result.classification.value == "RELATED_CONTEXT"
    assert result.relation_status is DiseaseFactorRelationStatus.INCIDENTAL


def test_long_scientific_sentence_does_not_borrow_outbreak_context_for_storage():
    result = assess(
        "Human plague vaccine",
        "This is needed to control human plague outbreaks in endemic areas and is supported "
        "further by exceptional stability of the vaccine formulation under thermostressed "
        "conditions, 40 C with 75% relative humidity for 6 weeks, meaning no cold chain "
        "for storage or distribution is needed.",
    )
    assert result.classification.value == "RELATED_CONTEXT"
    assert result.relation_status is DiseaseFactorRelationStatus.INCIDENTAL
    assert result.relation_reason == "STORAGE_FORMULATION_CONTEXT"


def test_controlled_article_terms_can_establish_relation():
    result = assess(
        "Indexed evidence", article_mesh_terms=("Plague", "Humidity"),
    )
    assert result.classification.value == "DIRECT_TOPIC"
    assert result.relation_reason == "ARTICLE_CONTROLLED_TOPIC_TERMS"


def test_query_provenance_cannot_create_relation():
    result = assess(
        "Human plague vaccine", "Vaccine immunogenicity was evaluated.",
        provenance={"query": "plague humidity outbreak incidence"},
        provider_metadata={"requested_factor": "relative humidity"},
    )
    assert result.classification.value == "RELATED_CONTEXT"
    assert not result.factor_match


@pytest.mark.parametrize("provider", ["PUBMED", "WHO", "FAKE_CDC"])
def test_provider_identity_does_not_change_relation(provider):
    result = assess(
        "Human plague study",
        "Relative humidity was associated with plague outbreak occurrence.",
        provider=provider,
    )
    assert result.classification.value == "DIRECT_TOPIC"
    assert result.relation_status is DiseaseFactorRelationStatus.RELATED_TO_TOPIC


def test_realistic_shared_relevance_contract():
    cases = [
        ("Climate drivers of plague epidemiology in British India, 1898-1949.",
         "Rainfall and relative humidity were associated with occurrence, timing and severity of plague outbreaks.",
         "DIRECT_TOPIC", {}),
        ("Dual route vaccination for plague with emergency use applications.",
         "Thermostressed vaccine formulation stability was evaluated at 75% relative humidity during storage.",
         "RELATED_CONTEXT", {"article_mesh_terms": ("Plague",)}),
        ("Effect of temperature and relative humidity on flea vectors of plague",
         "Relative humidity affected flea development and vector survival.", "DIRECT_TOPIC",
         {"article_mesh_terms": ("Plague",)}),
        ("Plague vaccination guidance", "Vaccine recommendations are reviewed.", "RELATED_CONTEXT", {}),
        ("SARS-CoV-2 protease", "COVID-19 continues to plague the globe. Structures were tested at high humidity.", "REJECT", {}),
        ("Smart agriculture IoT", "Humidity sensors and drones support plague detection for crops.", "REJECT", {}),
    ]
    assert [assess(title, abstract, **changes).classification.value
            for title, abstract, _, changes in cases] == [
        expected for _, _, expected, _ in cases
    ]


def test_archived_actual_pmid_30017148_is_related_guided_and_exact_identity_survives():
    xml = Path(__file__).with_name("fixtures").joinpath(
        "pubmed_30017148_efetch.xml"
    ).read_bytes()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path.endswith("/efetch.fcgi")
        assert parse_qs(request.content.decode())["id"] == ["30017148"]
        return httpx.Response(200, content=xml, request=request)

    with httpx.Client(
        base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
        transport=httpx.MockTransport(handler),
    ) as transport:
        client = PubMedClient(
            tool="offline_relation_regression",
            email="fixture@example.test",
            max_retries=0,
            client=transport,
        )
        provider = PubMedMedicalEvidenceProvider(client, content_service=None)
        exact = provider.lookup_exact("30017148")

    assert len(calls) == 1  # Exact EFetch only; no Guided search/fallback.
    assert exact is not None and exact.pmid == exact.external_id == "30017148"
    assert exact.title == "Dual route vaccination for plague with emergency use applications."
    assert "Plague" in exact.article_mesh_terms
    assert "Plague Vaccine" in exact.article_mesh_terms
    assert "Yersinia pestis" in exact.article_mesh_terms
    assert "75% relative humidity for 6 weeks" in exact.abstract_text
    assert "cold chain for storage or distribution" in exact.abstract_text

    assessment = ReviewedEvidenceRelevance(context()).classify(exact)
    assert assessment.classification.value == "RELATED_CONTEXT"
    assert assessment.disease_match and assessment.factor_match
    assert assessment.factor_match_field == "abstract"
    assert assessment.relation_status is DiseaseFactorRelationStatus.INCIDENTAL
    assert assessment.relation_reason == "STORAGE_FORMULATION_CONTEXT"
