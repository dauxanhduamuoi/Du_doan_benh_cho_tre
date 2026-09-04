from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.auto_evidence_discovery import (
    AutoEvidenceSearchError,
    PubMedAutoEvidenceProvider,
)
from app.services.auto_evidence_relevance import (
    DiseaseAliasSet,
    build_disease_aliases,
    factor_vocabulary,
    phrase_present,
)
from app.services.medical_evidence_content_service import ResolvedEvidenceContent
from app.services.pubmed_client import PubMedArticleRecord, PubMedUnavailableError
from app.services.pubmed_query_builder import build_pubmed_query


NOW = datetime(2026, 8, 29, 8, 0, 0)


def topic(factor_key="humidity"):
    return SimpleNamespace(
        factor_type="WEATHER",
        factor_key=factor_key,
        factor_value=None,
        weather_factor=factor_key,
    )


def record(pmid: str, text: str, *, title: str | None = None):
    return PubMedArticleRecord(
        pmid=pmid,
        title=title or text,
        authors="Researcher A",
        journal="Journal",
        publication_year=2024,
        doi=None,
        abstract_text=text,
        pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        raw_metadata={"mesh_terms": ["Child"]},
    )


class SearchClient:
    def __init__(self, batches, *, error=None):
        self.batches = list(batches)
        self.error = error
        self.calls = []

    def search(self, query, max_results):
        self.calls.append((query, max_results))
        if self.error:
            raise self.error
        batch = self.batches.pop(0) if self.batches else []
        return len(batch), batch


class EvidenceService:
    def resolve(self, *, pmid, abstract_text):
        if not abstract_text:
            return None
        return ResolvedEvidenceContent(
            content_kind="ABSTRACT",
            content_origin="NCBI_PUBMED",
            external_identifier=pmid,
            evidence_text=abstract_text,
            retrieved_at=NOW,
            is_truncated=False,
            license_name=None,
            license_url=None,
            provenance={"provider": "NCBI PubMed"},
        )


def provider(batches, **kwargs):
    client = SearchClient(batches)
    return PubMedAutoEvidenceProvider(client, EvidenceService(), **kwargs), client


def good_records(count=3, *, disease="influenza", factor="relative humidity", start=100):
    return [
        record(
            str(start + index),
            f"Pediatric children study marker{index}: {disease} admissions were associated with meteorological {factor}.",
        )
        for index in range(count)
    ]


def test_aliases_use_catalog_children_and_reject_incomplete_group_suffix():
    aliases = build_disease_aliases(
        "Sốt virut - Other arthropod",
        ("Dengue fever", "Chikungunya virus disease", "Dengue fever"),
    )
    assert "Other arthropod" not in aliases.strict
    assert aliases.strict == ("Dengue fever", "Chikungunya virus disease")
    assert len(aliases.broad) == len(set(aliases.broad))


def test_factor_vocabulary_is_phrase_oriented_and_guided_query_is_unchanged():
    assert factor_vocabulary(topic("humidity"), expanded=False) == (
        "humidity",
        "relative humidity",
    )
    assert "absolute humidity" in factor_vocabulary(topic("humidity"), expanded=True)
    assert build_pubmed_query(["Influenza"], weather_factor="humidity") == (
        '("Influenza"[Title/Abstract]) AND ("humidity"[Title/Abstract]) AND '
        '("Infant"[MeSH Terms] OR "Child"[MeSH Terms] OR "Adolescent"[MeSH Terms] '
        'OR "pediatric"[Title/Abstract] OR "paediatric"[Title/Abstract])'
    )


def test_phrase_matching_does_not_use_arbitrary_substrings():
    assert phrase_present("cold weather exposure", "cold weather")
    assert not phrase_present("cold agglutinin disease", "cold weather")
    assert not phrase_present("childhood cohort", "child")


def test_strict_stage_stops_when_enough_pediatric_sources_exist():
    discovery, client = provider([good_records()])
    result = discovery.discover(
        topic=topic(), disease_name="Cúm - Influenza", max_sources=10,
        disease_aliases=DiseaseAliasSet(("Influenza",), ("Influenza",)),
    )
    assert len(client.calls) == 1
    assert result.diagnostics.queries_run == 1
    assert result.diagnostics.selected_for_generation == 3
    assert all("humidity" in item.record.abstract_text.lower() for item in result.selected)


def test_expanded_factor_stage_finds_absolute_humidity_evidence():
    discovery, client = provider([[], good_records(factor="absolute humidity")])
    result = discovery.discover(
        topic=topic(), disease_name="Cúm - Influenza", max_sources=10,
        disease_aliases=DiseaseAliasSet(("Influenza",), ("Influenza",)),
    )
    assert len(client.calls) == 2
    assert result.diagnostics.query_details[-1].stage == "EXPANDED_FACTOR"
    assert len(result.selected) == 3


def test_broader_disease_stage_uses_catalog_child_aliases():
    discovery, client = provider([[], [], good_records(disease="chikungunya")])
    aliases = DiseaseAliasSet(
        ("Dengue fever",),
        ("Dengue fever", "Chikungunya"),
    )
    result = discovery.discover(
        topic=topic(), disease_name="Viral fever - Other arthropod", max_sources=10,
        disease_aliases=aliases,
    )
    assert len(client.calls) == 3
    assert result.diagnostics.query_details[-1].stage == "BROADER_DISEASE"
    assert len(result.selected) == 3


def test_dedup_and_query_bound_are_enforced():
    repeated = good_records(1)
    discovery, client = provider([repeated, repeated, repeated], min_pediatric_sources_before_stop=3)
    result = discovery.discover(
        topic=topic(), disease_name="Influenza", max_sources=10,
        disease_aliases=DiseaseAliasSet(("Influenza",), ("Influenza", "Flu virus")),
    )
    assert len(client.calls) <= 3
    assert result.diagnostics.raw_results == 3
    assert result.diagnostics.deduplicated == 1
    assert len(result.selected) == 1


def test_group_32_malaria_bed_net_source_is_rejected_without_pmid_hardcode():
    malaria = record(
        "14636983",
        "Children in villages received alphacypermethrin treated bed nets for malaria control and seasonal transmission.",
        title="Impact of treated bed nets on malaria",
    )
    discovery, _client = provider([[malaria], [], []])
    result = discovery.discover(
        topic=SimpleNamespace(factor_type="SEASONALITY", factor_key="time_of_year", factor_value="time_of_year", weather_factor=None),
        disease_name="Other viral fever - Other arthropod",
        max_sources=10,
        disease_aliases=DiseaseAliasSet(("Dengue fever",), ("Dengue fever", "Chikungunya virus disease")),
    )
    assert result.selected == ()
    assert result.diagnostics.disease_relevant == 0
    assert result.diagnostics.insufficient_reason == "NO_DISEASE_RELEVANT_SOURCE"


def test_cold_agglutinin_is_not_temperature_evidence():
    collision = record(
        "200",
        "Children with pneumonia and cold agglutinin antibodies were studied.",
    )
    discovery, _client = provider([[collision], [], []])
    result = discovery.discover(
        topic=topic("temperature"), disease_name="Pneumonia", max_sources=10,
        disease_aliases=DiseaseAliasSet(("Pneumonia",), ("Pneumonia",)),
    )
    assert result.selected == ()
    assert result.diagnostics.factor_relevant == 0
    assert result.diagnostics.insufficient_reason == "NO_FACTOR_RELEVANT_SOURCE"


def test_clinical_humidification_is_not_meteorological_humidity_evidence():
    ventilator = record(
        "201",
        "Children with pneumonia received ventilator humidification at controlled relative humidity to reduce device risk.",
    )
    discovery, _client = provider([[ventilator], [], []])
    result = discovery.discover(
        topic=topic("humidity"), disease_name="Pneumonia", max_sources=10,
        disease_aliases=DiseaseAliasSet(("Pneumonia",), ("Pneumonia",)),
    )
    assert result.selected == ()
    assert result.diagnostics.factor_relevant == 0


def test_weather_covariate_is_not_a_disease_factor_result():
    covariate = record(
        "202",
        "METHODS: Influenza incidence models evaluated air pollution while adjusting for temperature, relative humidity, and seasonality. RESULTS: Air pollution was associated with influenza incidence.",
        title="Air pollution and influenza incidence",
    )
    discovery, _client = provider([[covariate], [], []])
    result = discovery.discover(
        topic=topic("humidity"), disease_name="Influenza", max_sources=10,
        disease_aliases=DiseaseAliasSet(("Influenza",), ("Influenza",)),
    )
    assert result.selected == ()
    assert result.diagnostics.factor_relevant == 0


def test_covariate_in_same_result_sentence_does_not_borrow_another_factor_effect():
    covariate = record(
        "204",
        "After eliminating confounding factors such as relative humidity and wind speed, lower temperature was associated with a higher risk of pneumonia admission.",
        title="Air temperature and pneumonia admission",
    )
    discovery, _client = provider([[covariate], [], []])
    result = discovery.discover(
        topic=topic("humidity"), disease_name="Pneumonia", max_sources=10,
        disease_aliases=DiseaseAliasSet(("Pneumonia",), ("Pneumonia",)),
    )
    assert result.selected == ()
    assert result.diagnostics.factor_relevant == 0


def test_two_independent_exposures_do_not_create_false_disease_factor_link():
    unrelated_outcomes = record(
        "203",
        "METHODS: Asthma visits were correlated with meteorological humidity and influenza virus. RESULTS: Humidity was associated with asthma; influenza epidemics were also associated with asthma.",
        title="Environmental factors in asthma exacerbations",
    )
    discovery, _client = provider([[unrelated_outcomes], [], []])
    result = discovery.discover(
        topic=topic("humidity"), disease_name="Influenza", max_sources=10,
        disease_aliases=DiseaseAliasSet(("Influenza",), ("Influenza",)),
    )
    assert result.selected == ()
    assert result.diagnostics.factor_relevant == 0


def test_pediatric_signal_is_required_before_any_supplemental_source_is_selected():
    adult = record("300", "Influenza admissions were associated with meteorological relative humidity in adults.")
    adult = PubMedArticleRecord(**{**adult.__dict__, "raw_metadata": {}})
    discovery, _client = provider([[adult], [], []])
    result = discovery.discover(
        topic=topic(), disease_name="Influenza", max_sources=10,
        disease_aliases=DiseaseAliasSet(("Influenza",), ("Influenza",)),
    )
    assert result.selected == ()
    assert result.diagnostics.insufficient_reason == "NO_PEDIATRIC_RELEVANT_SOURCE"


def test_selection_is_relevance_ranked_and_capped_at_ten():
    discovery, _client = provider([good_records(15)], min_pediatric_sources_before_stop=3)
    result = discovery.discover(
        topic=topic(), disease_name="Influenza", max_sources=25,
        disease_aliases=DiseaseAliasSet(("Influenza",), ("Influenza",)),
    )
    assert len(result.selected) == 10
    assert result.diagnostics.selected_for_generation == 10


def test_pubmed_technical_error_is_not_misclassified_as_insufficient():
    client = SearchClient([], error=PubMedUnavailableError("offline"))
    discovery = PubMedAutoEvidenceProvider(client, EvidenceService())
    with pytest.raises(AutoEvidenceSearchError):
        discovery.discover(
            topic=topic(), disease_name="Influenza", max_sources=10,
            disease_aliases=DiseaseAliasSet(("Influenza",), ("Influenza",)),
        )
