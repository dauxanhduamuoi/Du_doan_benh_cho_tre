from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from app.services.disease_concept_matcher import DiseaseConceptMatcher, DiseaseMatchStrength
from app.services.reviewed_semantic_evidence import ReviewedSemanticEvidence
from app.services.pubmed_client import PubMedArticleRecord, parse_pubmed_records
from app.services.pubmed_client import PubMedClient
from app.services.pubmed_evidence_provider import normalize_pubmed_record, PubMedMedicalEvidenceProvider
from app.services.medical_evidence_provider import MedicalEvidenceProviderBadResponseError, MedicalEvidenceProviderRegistry
from app.services.medical_evidence_reviewed_service import MedicalEvidenceReviewedService, ReviewedProviderSelectionError
from app.medical_evidence_reviewed_schemas import ReviewedProviderExactLookupRequest
from app.medical_evidence_reviewed_schemas import ReviewedProviderImportRequest, ReviewedProviderSourceReference
from app.services.medical_knowledge_pubmed_service import MedicalKnowledgePubMedService, PubMedArticleNotFoundError
from app.pubmed_schemas import PubMedLookupRequest
from test_shared_reviewed_relevance_v1 import context, source
from app.services.reviewed_evidence_relevance import ReviewedEvidenceRelevance
from test_pubmed_api_service import db, manifest, FakePubMedClient, article, lookup_request, import_request
from test_who_evidence_provider import WHO_ID, WHO_ID_2, provider_with, response, who_record


# SARS abstract fragments verified through the production PubMed normalizer on
# 2026-09-16 (PMID 36071812). Agriculture text is a faithful shortened fixture
# from the publisher abstract. The additional archived EFetch test below now
# verifies the complete real response after the user authorized one extra call.
MPRO_TITLE = 'The temperature-dependent conformational ensemble of SARS-CoV-2 main protease (Mpro).'
AGRICULTURE_TITLE = 'Edge IoT Prototyping Using Model-Driven Representations: A Use Case for Smart Agriculture.'
MPRO_ABSTRACT = (
    'The COVID-19 pandemic continues to plague the globe. SARS-CoV-2 Mpro '
    'crystal structures were measured at multiple temperatures and high humidity. '
    'The results inform antiviral drug development against coronavirus.'
)
AGRICULTURE_ABSTRACT = (
    'Industry 4.0 agriculture systems combine humidity/temperature/soil sensors '
    'and drones for plague detection with smart irrigation. Model-driven '
    'development supports prototyping edge IoT systems for crop control.'
)


def test_archived_actual_agriculture_efetch_is_rejected_guided_but_exact_stays_visible():
    xml = Path(__file__).with_name('fixtures').joinpath('pubmed_38257588_efetch.xml').read_bytes()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path.endswith('/efetch.fcgi')
        assert parse_qs(request.content.decode())['id'] == ['38257588']
        return httpx.Response(200, content=xml, request=request)

    with httpx.Client(base_url='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/',
                      transport=httpx.MockTransport(handler)) as transport:
        client = PubMedClient(tool='offline_regression', email='fixture@example.test',
                              max_retries=0, client=transport)
        provider = PubMedMedicalEvidenceProvider(client, content_service=None)
        exact = provider.lookup_exact('38257588')

    assert len(calls) == 1  # EFetch only, never keyword search or enrichment.
    assert exact is not None and exact.pmid == exact.external_id == '38257588'
    assert exact.title == AGRICULTURE_TITLE
    assert exact.doi == '10.3390/s24020495' and exact.pmcid == 'PMC10818290'
    assert exact.article_mesh_terms == ()
    assert exact.provider_metadata['mesh_terms'] == []
    assert exact.article_keywords == ('Industry 4.0', 'analytics', 'model-driven development', 'smart agriculture')
    assert 'drones for plague detection' in exact.abstract_text
    assert 'humidity/temperature/soil sensors' in exact.abstract_text
    assert set(exact.provenance) == {'provider', 'pmid', 'pmcid'}
    assessment = ReviewedEvidenceRelevance(context()).classify(exact)
    assert assessment.factor_match and assessment.disease_strength is DiseaseMatchStrength.WEAK
    assert assessment.classification.value == 'REJECT'


@pytest.mark.parametrize('title,abstract', [(MPRO_TITLE, MPRO_ABSTRACT), (AGRICULTURE_TITLE, AGRICULTURE_ABSTRACT)])
def test_real_abstract_mechanisms_are_weak_and_rejected(title, abstract):
    item = source('PUBMED', title, abstract=abstract)
    assessment = ReviewedEvidenceRelevance(context()).classify(item)
    assert assessment.disease_strength is DiseaseMatchStrength.WEAK
    assert assessment.factor_match
    assert assessment.classification.value == 'REJECT'
    # The former lexical mechanism falsely accepted both signals.
    text = f'{title} {abstract}'.casefold()
    assert 'plague' in text and 'humidity' in text


@pytest.mark.parametrize('title,expected', [
    ('Human plague and humidity', 'DIRECT_TOPIC'),
    ('Plague vaccination', 'RELATED_CONTEXT'),
    ('WHO guidelines for plague management', 'RELATED_CONTEXT'),
    ('Plague humidity', 'REJECT'),
    ('Humidity sensors', 'REJECT'),
    ('COVID patients continue to plague the globe at high humidity', 'REJECT'),
    ('Crop plague detection and humidity sensors', 'REJECT'),
])
def test_strength_and_final_classification(title, expected):
    assert ReviewedEvidenceRelevance(context()).classify(source('WHO', title)).classification.value == expected


@pytest.mark.parametrize('field', ['article_mesh_terms', 'article_subject_terms'])
def test_article_owned_medical_heading_disambiguates(field):
    item = replace(source('PUBMED', 'Humidity outcomes'), **{field: ('Plague',)})
    assessment = ReviewedEvidenceRelevance(context()).classify(item)
    assert assessment.disease_strength is DiseaseMatchStrength.STRONG
    assert assessment.classification.value == 'RELATED_CONTEXT'


def test_ambiguous_keyword_is_not_medical_heading():
    item = replace(source('PUBMED', 'Crop humidity sensors'), article_keywords=('plague',))
    assert ReviewedEvidenceRelevance(context()).classify(item).classification.value == 'REJECT'


def test_provenance_ids_journal_arbitrary_metadata_and_request_mesh_do_not_count():
    item = replace(source('PUBMED', 'Unrelated article'),
        canonical_url='https://example.test/Plague-humidity', external_id='Plague humidity',
        publisher_or_journal='Plague disease humidity',
        provenance={'query': 'Plague humidity'},
        provider_metadata={'query': 'Plague humidity', 'mesh_terms': ['Plague'],
                           'nested': {'subject': 'Plague disease humidity'}, 'request_aliases': ['Plague']})
    assessment = ReviewedEvidenceRelevance(context()).classify(item, query_level='DIRECT_TOPIC')
    assert assessment.disease_strength is DiseaseMatchStrength.NONE
    assert not assessment.factor_match


def test_factor_cannot_be_injected_through_metadata_or_publisher():
    item = replace(source('WHO', 'Plague vaccination'),
                   provider_metadata={'query': 'humidity'}, publisher_or_journal='humidity')
    assert ReviewedEvidenceRelevance(context()).classify(item).classification.value == 'RELATED_CONTEXT'


def test_no_cross_field_phrase_and_generic_configuration_without_disease_branch():
    config = {'concepts': [{'canonical_label': 'Example', 'ambiguous_aliases': ['Example']}],
              'clinical_prefixes': ['human'], 'clinical_suffixes': ['vaccination']}
    matcher = DiseaseConceptMatcher(('Example',), configuration=config)
    assert matcher.match(ReviewedSemanticEvidence(('example problem',), ())).strength is DiseaseMatchStrength.WEAK
    assert matcher.match(ReviewedSemanticEvidence(('example vaccination',), ())).strength is DiseaseMatchStrength.STRONG
    assert matcher.match(ReviewedSemanticEvidence(('example', 'vaccination'), ())).strength is DiseaseMatchStrength.WEAK


def test_pubmed_xml_projects_only_article_mesh_and_author_keywords():
    xml = '''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID>
    <Article><ArticleTitle>Humidity outcomes</ArticleTitle></Article>
    <MeshHeadingList><MeshHeading><DescriptorName>Plague</DescriptorName></MeshHeading></MeshHeadingList>
    <KeywordList><Keyword>human plague</Keyword></KeywordList></MedlineCitation>
    </PubmedArticle></PubmedArticleSet>'''
    item = normalize_pubmed_record(parse_pubmed_records(xml)[0])
    assert item.article_mesh_terms == ('Plague',)
    assert item.article_keywords == ('human plague',)
    assessment = ReviewedEvidenceRelevance(context()).classify(item)
    assert assessment.disease_strength is DiseaseMatchStrength.STRONG
    assert assessment.classification.value == 'RELATED_CONTEXT'


def test_unrelated_pmid_is_returned_exactly_and_library_reuses_identity(db, manifest):
    record = replace(article('36071812', MPRO_TITLE), abstract_text=None)
    client = FakePubMedClient([record])
    service = MedicalKnowledgePubMedService(db, client, disease_manifest_path=manifest)
    result = service.lookup_pmid(lookup_request('36071812'))
    assert result.result.pmid == '36071812' and result.result.title == MPRO_TITLE
    assert ReviewedEvidenceRelevance(context()).classify(normalize_pubmed_record(record)).classification.value == 'REJECT'
    first = service.import_pmids(import_request('36071812'), added_by=None)
    second = service.import_pmids(import_request('36071812'), added_by=None)
    assert first.sources[0].id == second.sources[0].id
    stored = service.repository.get_source_by_pmid('36071812')
    assert stored.provider_id == 'PUBMED' and stored.external_id == stored.pmid == '36071812'
    assert service.lookup_pmid(lookup_request('36071812')).existing_source.already_in_topic_library
    assert first.sources[0].content_kind is None  # Reference is not made AI-readable.
    assert client.search_calls == []


def test_pmid_returned_identity_must_equal_requested(db, manifest):
    class WrongClient(FakePubMedClient):
        def get_article_by_pmid(self, pmid):
            return article('999')
    service = MedicalKnowledgePubMedService(db, WrongClient(), disease_manifest_path=manifest)
    with pytest.raises(MedicalEvidenceProviderBadResponseError, match='identity mismatch'):
        service.lookup_pmid(lookup_request('123'))


def test_invalid_and_missing_pmid_never_search(db, manifest):
    with pytest.raises(ValidationError):
        lookup_request('not-pmid')
    client = FakePubMedClient()
    service = MedicalKnowledgePubMedService(db, client, disease_manifest_path=manifest)
    with pytest.raises(PubMedArticleNotFoundError):
        service.lookup_pmid(lookup_request('123'))
    assert client.search_calls == [] and client.fetch_calls == [['123']]


def test_import_refuses_substituted_pmid_before_persistence(db, manifest):
    class WrongClient(FakePubMedClient):
        def fetch_records(self, pmids):
            return [article('999')]
    service = MedicalKnowledgePubMedService(db, WrongClient(), disease_manifest_path=manifest)
    with pytest.raises(MedicalEvidenceProviderBadResponseError, match='identity mismatch'):
        service.import_pmids(import_request('123'), added_by=None)
    assert service.repository.get_source_by_pmid('999') is None


@pytest.mark.parametrize('identifier', ['73164', 'https://www.who.int/publications/b/73164',
    'https://www.who.int/publications/i/item/9789240099999', 'https://evil.test/file', 'WHO/2024.1'])
def test_who_unsupported_identifiers_never_search_or_fetch(identifier):
    def handler(request):
        pytest.fail('Unsupported exact identifiers must not make a network call')
    with pytest.raises(ValueError, match='INVALID_IDENTIFIER'):
        provider_with(handler).lookup_exact(identifier)


@pytest.mark.parametrize('returned_id', [WHO_ID_2, None, '73164'])
def test_who_exact_response_must_supply_same_guid(returned_id):
    with pytest.raises(MedicalEvidenceProviderBadResponseError, match='identity mismatch'):
        provider_with(lambda req: response(req, payload=who_record(Id=returned_id))).lookup_exact(WHO_ID)


def test_who_guid_exact_unrelated_record_and_404():
    calls = []
    def handler(req):
        calls.append(str(req.url))
        return response(req, payload=who_record(Title='Unrelated policy', Summary='A policy document'))
    item = provider_with(handler).lookup_exact(WHO_ID.upper())
    assert item.external_id == WHO_ID and item.title == 'Unrelated policy'
    assert calls == [f'https://www.who.int/api/hubs/publications({WHO_ID})']
    assert provider_with(lambda req: response(req, status=404)).lookup_exact(WHO_ID) is None


def test_exact_service_does_not_classify_or_call_guided(db, monkeypatch):
    provider = provider_with(lambda req: response(req, payload=who_record(Title='Unrelated policy', Summary=None)))
    registry = MedicalEvidenceProviderRegistry()
    registry.register(provider)
    service = MedicalEvidenceReviewedService(db, registry)
    monkeypatch.setattr(service, '_validate_disease', lambda disease: None)
    monkeypatch.setattr(service, '_enabled_selection', lambda selected: tuple(selected))
    def forbidden(*args, **kwargs):
        pytest.fail('Exact must not discover or reject by relevance')
    monkeypatch.setattr(provider, 'search', forbidden)
    monkeypatch.setattr(ReviewedEvidenceRelevance, 'classify', forbidden)
    result = service.lookup_exact(ReviewedProviderExactLookupRequest(
        disease_group_id='9', weather_factor='humidity', provider_id='WHO', identifier=WHO_ID))
    assert result.result.external_id == WHO_ID
    assert result.result.relevance == 'EXACT_LOOKUP'
    assert not result.result.usable_for_draft


def test_exact_pmid_and_guided_import_share_one_source_and_topic_link(db, manifest, monkeypatch):
    record = article('36071812', MPRO_TITLE)
    client = FakePubMedClient([record])
    legacy = MedicalKnowledgePubMedService(db, client, disease_manifest_path=manifest)
    registry = MedicalEvidenceProviderRegistry()
    registry.register(legacy.provider)
    reviewed = MedicalEvidenceReviewedService(db, registry)
    monkeypatch.setattr(reviewed, '_validate_disease', lambda value: None)
    monkeypatch.setattr(reviewed, '_enabled_selection', lambda values: tuple(values))
    exact = legacy.lookup_pmid(lookup_request(record.pmid))
    guided_import = reviewed.import_sources(ReviewedProviderImportRequest(
        disease_group_id='1', weather_factor='humidity', sources=[
            ReviewedProviderSourceReference(provider_id='PUBMED', external_id=record.pmid),
        ]), added_by=None)
    exact_import = legacy.import_pmids(import_request(exact.result.pmid), added_by=None)
    assert guided_import.sources[0].source_id == exact_import.sources[0].id
    assert not exact_import.sources[0].topic_link_created
    assert exact_import.sources[0].pmid == record.pmid
    assert client.search_calls == []


def test_who_exact_and_guided_library_import_preserve_guid_and_dedup(db, monkeypatch):
    provider = provider_with(lambda req: response(req, payload=who_record(Title='Unrelated policy', Summary=None)))
    registry = MedicalEvidenceProviderRegistry()
    registry.register(provider)
    service = MedicalEvidenceReviewedService(db, registry)
    monkeypatch.setattr(service, '_validate_disease', lambda value: None)
    monkeypatch.setattr(service, '_enabled_selection', lambda values: tuple(values))
    exact = service.lookup_exact(ReviewedProviderExactLookupRequest(
        disease_group_id='9', weather_factor='humidity', provider_id='WHO', identifier=WHO_ID))
    request = ReviewedProviderImportRequest(disease_group_id='9', weather_factor='humidity', sources=[
        ReviewedProviderSourceReference(provider_id='WHO', external_id=exact.result.external_id,
                                       canonical_url=exact.result.url, title=exact.result.title),
    ])
    first = service.import_sources(request, added_by=None)
    second = service.import_sources(request, added_by=None)
    assert first.sources[0].source_id == second.sources[0].source_id
    assert first.sources[0].external_id == WHO_ID
    assert first.sources[0].outcome == 'ADDED_REFERENCE_ONLY'
    assert second.sources[0].outcome == 'ALREADY_EXISTS'
    assert not first.sources[0].usable_for_draft


@pytest.mark.parametrize('identifier,status', [(WHO_ID, 200), ('73164', 422),
                                           ('https://www.who.int/publications/i/item/123', 422)])
def test_who_exact_http_contract(db, monkeypatch, identifier, status):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.routers import medical_evidence_reviewed as routes
    from app.security import require_staff_or_admin
    registry = MedicalEvidenceProviderRegistry()
    registry.register(provider_with(lambda req: response(req, payload=who_record(Title='Unrelated policy', Summary=None))))
    service = MedicalEvidenceReviewedService(db, registry)
    monkeypatch.setattr(service, '_validate_disease', lambda value: None)
    monkeypatch.setattr(service, '_enabled_selection', lambda values: tuple(values))
    api = FastAPI()
    api.include_router(routes.router)
    api.dependency_overrides[routes._service] = lambda: service
    api.dependency_overrides[require_staff_or_admin] = lambda: SimpleNamespace(id=1, role='admin')
    with TestClient(api) as client:
        result = client.post('/api/medical-knowledge/providers/lookup', json={
            'disease_group_id': '9', 'weather_factor': 'humidity', 'provider_id': 'WHO', 'identifier': identifier,
        })
    assert result.status_code == status, result.text
    if status == 200:
        assert result.json()['result']['external_id'] == WHO_ID
        assert result.json()['result']['relevance'] == 'EXACT_LOOKUP'
