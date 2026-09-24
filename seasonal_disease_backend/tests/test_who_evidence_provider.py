from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session

from app.database import Base
from app.medical_knowledge_draft_schemas import DraftGenerationContext, DraftSourceInput
from app.medical_knowledge_models import MedicalEvidenceContent, MedicalEvidenceSource
from app.models import User  # noqa: F401 - register the referenced users table
from app.medical_knowledge_schemas import MedicalEvidenceContentCreate, MedicalEvidenceSourceCreate
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.services.auto_evidence_qualification import qualify_auto_evidence
from app.services.auto_evidence_relevance import RelevanceSignals
from app.services.medical_evidence_provider import (
    DEFAULT_AUTO_EVIDENCE_TRUST_POLICY,
    DEFAULT_REVIEWED_EVIDENCE_TRUST_POLICY,
    MedicalEvidenceCapability,
    MedicalEvidenceProviderBadResponseError,
    MedicalEvidenceProviderConfigurationError,
    MedicalEvidenceProviderRateLimitedError,
    MedicalEvidenceProviderRegistry,
    MedicalEvidenceProviderTimeoutError,
    MedicalEvidenceProviderUnavailableError,
    MedicalEvidenceSourceKind,
    deduplicate_normalized_evidence,
)
from app.services.medical_evidence_provider_factory import (
    DEFAULT_AUTO_MEDICAL_EVIDENCE_PROVIDER_IDS,
    DEFAULT_REVIEWED_MEDICAL_EVIDENCE_PROVIDER_IDS,
    create_medical_evidence_provider_registry,
)
from app.services.who_evidence_provider import (
    WHO_CONTENT_KIND,
    WHO_CONTENT_ORIGIN,
    WHO_LICENSE_URL,
    WHO_TRUST_CLASS,
    WhoMedicalEvidenceProvider,
    normalize_who_record,
    who_trust_class,
)
from migrations.v016_who_evidence_content import upgrade as upgrade_v016


NOW = datetime(2026, 9, 11, 9, 0, 0)
WHO_ID = "69e416c8-c71b-4e2b-839b-c6f44d59cc2f"
WHO_ID_2 = "742f074f-d820-4d95-a48d-054513c6bc73"


def who_record(**overrides) -> dict[str, object]:
    value: dict[str, object] = {
        "Id": WHO_ID,
        "SystemSourceKey": WHO_ID,
        "Title": "Guideline on influenza, humidity and children",
        "Subtitle": "Evidence-informed recommendations",
        "NavigationUrl": "/publications/i/item/9789240099999",
        "PublicationDate": "2024-06-15T00:00:00Z",
        "LastModified": "2025-01-09T12:30:00Z",
        "Publisher": "World Health Organization",
        "Languages": [{"Name": "English"}],
        "PublicationType": "Guideline",
        "Summary": (
            "<p>WHO guidance discusses influenza risk for children during "
            "high humidity and rainfall.</p>"
        ),
        "Copyright": "CC BY-NC-SA 3.0 IGO",
        "WHOReferenceNumber": "WHO/HEP/2024.1",
        "ISBN": "978-92-4-009999-9",
        "DOI": "https://doi.org/10.2471/WHO.2024.9999",
    }
    value.update(overrides)
    return value


def search_payload(*records: dict[str, object], total: int | None = None):
    items = list(records or (who_record(),))
    return {"Total": len(items) if total is None else total, "PagesCount": 1, "Results": items}


def response(request: httpx.Request, *, status=200, payload=None, headers=None, content=None):
    if content is not None:
        return httpx.Response(status, content=content, headers=headers or {}, request=request)
    return httpx.Response(
        status,
        json=search_payload() if payload is None else payload,
        headers=headers,
        request=request,
    )


def provider_with(handler, **kwargs) -> WhoMedicalEvidenceProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return WhoMedicalEvidenceProvider(client, clock=lambda: NOW, **kwargs)


def normalized(record=None, **kwargs):
    return normalize_who_record(
        record or who_record(),
        retrieved_at=NOW,
        retrieval_surface="OFFLINE_FIXTURE",
        max_excerpt_chars=kwargs.get("max_excerpt_chars", 6000),
    )


def qualification_input(evidence=None, *, trust_class=WHO_TRUST_CLASS, signals=None):
    evidence = evidence or normalized()
    source_input = DraftSourceInput(
        source_id=1,
        source_type="WHO",
        pmid=None,
        doi=evidence.doi,
        title=evidence.title,
        publication_year=evidence.publication_year,
        evidence_content_id=2,
        content_kind=WHO_CONTENT_KIND,
        evidence_text=evidence.evidence_text or "",
        content_origin=WHO_CONTENT_ORIGIN,
        license_name=evidence.license_name,
        license_url=evidence.license_url,
    )
    context = DraftGenerationContext(
        disease_group_id="influenza",
        disease_group_name="Influenza",
        factor_type="WEATHER",
        factor_key="humidity",
        weather_factor="humidity",
        sources=[source_input],
    )
    selected = [
        (
            SimpleNamespace(id=1, provider_id="WHO", source_type="WHO"),
            SimpleNamespace(id=2, source_id=1),
            source_input,
            trust_class,
            signals or RelevanceSignals(disease=1, factor=1, pediatric=1),
        )
    ]
    return context, selected


# 1
def test_01_production_registry_contains_pubmed():
    registry = create_medical_evidence_provider_registry()
    try:
        assert registry.get("PUBMED").descriptor.provider_id == "PUBMED"
    finally:
        registry.close()


# 2
def test_02_production_registry_contains_who():
    registry = create_medical_evidence_provider_registry()
    try:
        assert [item.provider_id for item in registry.list_descriptors()] == ["PUBMED", "WHO"]
        assert registry.get("who").descriptor.display_name == "World Health Organization"
    finally:
        registry.close()


# 3
def test_03_who_registration_does_not_enable_auto():
    assert DEFAULT_AUTO_MEDICAL_EVIDENCE_PROVIDER_IDS == ("PUBMED",)


# 4
def test_04_who_registration_does_not_enable_reviewed():
    assert DEFAULT_REVIEWED_MEDICAL_EVIDENCE_PROVIDER_IDS == ("PUBMED",)
    assert not DEFAULT_REVIEWED_EVIDENCE_TRUST_POLICY.is_provider_trusted("WHO")


# 5
def test_05_registration_does_not_imply_trust():
    registry = MedicalEvidenceProviderRegistry()
    provider = provider_with(lambda request: response(request))
    registry.register(provider)
    assert registry.get("WHO") is provider
    assert not DEFAULT_AUTO_EVIDENCE_TRUST_POLICY.is_trusted(
        provider_id="WHO", trust_class="UNTRUSTED"
    )
    registry.close()


# 6
def test_06_who_search_normalizes_official_result():
    seen = []

    def handler(request):
        seen.append(request)
        return response(request)

    provider = provider_with(handler)
    result = provider.search("influenza humidity children", 5)
    assert result.total_count == 1
    assert result.sources[0].external_id == WHO_ID
    assert result.sources[0].title == normalized().title
    assert result.sources[0].content_sha256 == normalized().content_sha256
    assert seen[0].url.path == "/publications/b/search/Publications"
    assert seen[0].url.params["term"] == "influenza humidity children"


# 7
def test_07_who_evidence_does_not_require_pmid():
    source = normalized()
    assert source.pmid is None and source.pmcid is None


# 8
def test_08_who_stable_external_id_is_preserved():
    assert normalized().external_id == WHO_ID


# 9
def test_09_who_canonical_url_is_preserved():
    assert normalized().canonical_url == "https://www.who.int/publications/i/item/9789240099999"


# 10
@pytest.mark.parametrize(
    ("publication_type", "expected"),
    [
        ("Guideline", MedicalEvidenceSourceKind.GUIDELINE),
        ("Systematic Review", MedicalEvidenceSourceKind.SYSTEMATIC_REVIEW),
        ("Technical report", MedicalEvidenceSourceKind.TECHNICAL_REPORT),
        ("Fact sheet", MedicalEvidenceSourceKind.HEALTH_GUIDANCE),
        (None, MedicalEvidenceSourceKind.OTHER),
    ],
)
def test_10_who_source_kind_is_deterministic(publication_type, expected):
    assert normalized(who_record(PublicationType=publication_type)).source_kind == expected


# 11
def test_11_who_publication_date_is_optional():
    source = normalized(who_record(PublicationDate=None))
    assert source.publication_date is None and source.publication_year is None


# 12
def test_12_who_language_is_preserved():
    assert normalized().language == "English"


# 13
def test_13_who_official_provenance_is_preserved():
    provenance = normalized().provenance
    assert provenance["provider_id"] == "WHO"
    assert provenance["canonical_url"].startswith("https://www.who.int/")
    assert provenance["retrieved_at"] == NOW.isoformat()


# 14
def test_14_who_content_hash_is_deterministic():
    assert normalized().content_sha256 == normalized().content_sha256
    assert len(normalized().content_sha256) == 64


# 15
def test_15_same_unchanged_content_reuses_immutable_snapshot():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    evidence = normalized()
    with Session(engine) as db:
        repository = MedicalKnowledgeRepository(db)
        source = repository.create_source(
            MedicalEvidenceSourceCreate(
                source_type="WHO", provider_id="WHO", external_id=evidence.external_id,
                source_kind=evidence.source_kind.value, title=evidence.title,
                url=evidence.canonical_url,
            )
        )
        content = repository.create_evidence_content(
            MedicalEvidenceContentCreate(
                source_id=source.id, content_kind=evidence.content_kind,
                content_origin=evidence.content_origin, evidence_text=evidence.evidence_text,
                retrieved_at=NOW, license_name=evidence.license_name,
                license_url=evidence.license_url, provenance_json=dict(evidence.provenance),
                content_sha256=evidence.content_sha256,
            )
        )
        assert repository.get_evidence_content_by_hash(source.id, evidence.content_sha256).id == content.id
    engine.dispose()


# 16
def test_16_changed_content_creates_distinct_snapshot():
    first = normalized()
    second = normalized(who_record(Summary="Updated guidance for influenza, humidity and children."))
    assert first.content_sha256 != second.content_sha256


# 17
def test_17_html_boilerplate_is_removed_from_summary():
    source = normalized(
        who_record(Summary="<nav>Menu</nav><p>Children and humidity.</p><script>bad()</script><footer>Links</footer>")
    )
    assert source.evidence_text == "Children and humidity."


# 18
def test_18_oversized_response_is_blocked():
    body = b'{"Results":[],"padding":"' + (b"x" * 2000) + b'"}'
    provider = provider_with(
        lambda request: response(
            request, content=body, headers={"content-type": "application/json"}
        ),
        max_response_bytes=1024,
    )
    with pytest.raises(MedicalEvidenceProviderBadResponseError):
        provider.search("influenza children", 5)


# 19
def test_19_unsupported_content_type_fails_safely():
    provider = provider_with(
        lambda request: response(request, content=b"<html></html>", headers={"content-type": "text/html"})
    )
    with pytest.raises(MedicalEvidenceProviderBadResponseError):
        provider.search("influenza children", 5)


# 20
@pytest.mark.parametrize("copyright_text", [None, "All rights reserved", "Permission required"])
def test_20_unknown_or_restricted_license_fails_closed(copyright_text):
    source = normalized(who_record(Copyright=copyright_text))
    assert source.abstract_text.startswith("WHO guidance")  # metadata remains usable for discovery
    assert source.evidence_text is None
    assert source.content_kind is None and source.content_origin is None
    assert who_trust_class(source) == "UNTRUSTED"


# 21
def test_21_bounded_safe_excerpt_is_preserved():
    source = normalized(who_record(Summary="children humidity " * 100), max_excerpt_chars=80)
    assert len(source.evidence_text) == 80
    assert source.is_truncated is True


# 22
def test_22_timeout_is_typed():
    def handler(request):
        raise httpx.ReadTimeout("late", request=request)

    with pytest.raises(MedicalEvidenceProviderTimeoutError) as captured:
        provider_with(handler).search("influenza children", 2)
    assert (captured.value.code, captured.value.stage) == (
        "WHO_SEARCH_TIMEOUT", "transport"
    )


# 23
def test_23_rate_limit_is_typed():
    with pytest.raises(MedicalEvidenceProviderRateLimitedError) as captured:
        provider_with(
            lambda request: response(
                request, status=429, headers={"retry-after": "120"}
            )
        ).search("influenza children", 2)
    assert (captured.value.code, captured.value.stage, captured.value.retry_after) == (
        "WHO_SEARCH_RATE_LIMITED", "http", "120"
    )


# 24
def test_24_malformed_response_is_typed():
    provider = provider_with(
        lambda request: response(
            request, content=b"not-json", headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(MedicalEvidenceProviderBadResponseError) as captured:
        provider.search("influenza children", 2)
    assert captured.value.code == "WHO_SEARCH_MALFORMED_JSON"


# 25
def test_25_non_who_redirect_is_rejected():
    provider = provider_with(
        lambda request: response(
            request, status=302, content=b"", headers={"location": "https://evil.example/a"}
        )
    )
    with pytest.raises(MedicalEvidenceProviderBadResponseError):
        provider.search("influenza children", 2)


# 26
def test_26_unavailable_endpoint_is_typed():
    with pytest.raises(MedicalEvidenceProviderUnavailableError) as captured:
        provider_with(lambda request: response(request, status=503)).search("influenza children", 2)
    assert (captured.value.code, captured.value.stage) == (
        "WHO_SEARCH_HTTP_STATUS", "http"
    )


# 27
def test_27_invalid_document_response_is_typed():
    provider = provider_with(lambda request: response(request, payload=[]))
    with pytest.raises(MedicalEvidenceProviderBadResponseError):
        provider.lookup(WHO_ID)


# 28
def test_28_empty_content_is_typed():
    provider = provider_with(
        lambda request: response(request, content=b"", headers={"content-type": "application/json"})
    )
    with pytest.raises(MedicalEvidenceProviderBadResponseError):
        provider.search("influenza children", 2)


# 29
def test_29_configuration_error_rejects_non_official_base_url():
    with pytest.raises(MedicalEvidenceProviderConfigurationError):
        WhoMedicalEvidenceProvider(base_url="http://127.0.0.1")


# 30
def test_30_same_who_provider_external_id_dedups():
    duplicate = replace(normalized(), canonical_url="https://www.who.int/publications/i/item/other")
    assert deduplicate_normalized_evidence((normalized(), duplicate)) == (normalized(),)


# 31
def test_31_same_canonical_url_dedups():
    duplicate = normalized(who_record(Id=WHO_ID_2, SystemSourceKey=WHO_ID_2))
    assert deduplicate_normalized_evidence((normalized(), duplicate)) == (normalized(),)


# 32
def test_32_same_doi_cross_provider_dedups():
    who = normalized()
    fake = replace(
        who,
        provider_id="PUBMED",
        external_id="12345678",
        canonical_url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
        pmid="12345678",
    )
    assert deduplicate_normalized_evidence((who, fake)) == (who,)


# 33
def test_33_different_who_documents_do_not_collapse():
    second = normalized(
        who_record(
            Id=WHO_ID_2,
            SystemSourceKey=WHO_ID_2,
            NavigationUrl="/publications/i/item/9789240011111",
            DOI="10.2471/WHO.2024.1111",
        )
    )
    assert deduplicate_normalized_evidence((normalized(), second)) == (normalized(), second)


# 34
def test_34_no_pmid_assumption_in_batch_or_identity():
    calls = 0

    def handler(request):
        nonlocal calls
        item_id = (WHO_ID, WHO_ID_2)[calls]
        calls += 1
        return response(
            request,
            payload=who_record(
                Id=item_id,
                SystemSourceKey=item_id,
                NavigationUrl=f"/publications/i/item/{item_id}",
                DOI=f"10.2471/WHO.{calls}",
            ),
        )

    sources = provider_with(handler).fetch_many([WHO_ID, WHO_ID_2])
    assert len(sources) == 2 and all(source.pmid is None for source in sources)


# 35
def test_35_trusted_who_pediatric_evidence_can_pass():
    context, selected = qualification_input()
    result = qualify_auto_evidence(topic_id=1, context=context, selected=selected)
    assert result.eligible is True and result.snapshot.pediatric_support is True


# 36
def test_36_wrong_disease_fails():
    context, selected = qualification_input(signals=RelevanceSignals(0, 1, 1))
    result = qualify_auto_evidence(topic_id=1, context=context, selected=selected)
    assert (result.eligible, result.reason_code) == (False, "NO_DISEASE_RELEVANT_SOURCE")


# 37
def test_37_wrong_factor_fails():
    context, selected = qualification_input(signals=RelevanceSignals(1, 0, 1))
    result = qualify_auto_evidence(topic_id=1, context=context, selected=selected)
    assert (result.eligible, result.reason_code) == (False, "NO_FACTOR_RELEVANT_SOURCE")


# 38
def test_38_adult_only_fails_pediatric_requirement():
    adult = normalized(who_record(Summary="Influenza and humidity guidance for adults only."))
    context, selected = qualification_input(adult, signals=RelevanceSignals(1, 1, 0))
    result = qualify_auto_evidence(topic_id=1, context=context, selected=selected)
    assert (result.eligible, result.reason_code) == (False, "NO_PEDIATRIC_RELEVANT_SOURCE")


# 39
def test_39_unusable_content_fails():
    context, selected = qualification_input()
    broken = context.sources[0].model_copy(update={"evidence_text": ""})
    context = context.model_copy(update={"sources": [broken]})
    selected[0] = (*selected[0][:2], broken, *selected[0][3:])
    result = qualify_auto_evidence(topic_id=1, context=context, selected=selected)
    assert (result.eligible, result.reason_code) == (False, "SOURCE_PROVENANCE_MISMATCH")


# 40
def test_40_untrusted_source_class_fails():
    context, selected = qualification_input(trust_class="UNTRUSTED")
    result = qualify_auto_evidence(topic_id=1, context=context, selected=selected)
    assert (result.eligible, result.reason_code) == (False, "TRUSTED_SOURCE_REQUIRED")


# 41
def test_41_invalid_provenance_ownership_fails():
    context, selected = qualification_input()
    selected[0] = (selected[0][0], SimpleNamespace(id=2, source_id=99), *selected[0][2:])
    result = qualify_auto_evidence(topic_id=1, context=context, selected=selected)
    assert (result.eligible, result.reason_code) == (False, "SOURCE_PROVENANCE_MISMATCH")


# 42
def test_42_conflicting_evidence_behavior_is_preserved():
    context, selected = qualification_input()
    result = qualify_auto_evidence(
        topic_id=1, context=context, selected=selected, discovery_reason="CONFLICTING_EVIDENCE"
    )
    assert (result.eligible, result.reason_code) == (False, "CONFLICTING_EVIDENCE")


# 43
def test_43_who_exact_trust_conditions_only():
    source = normalized()
    assert who_trust_class(source) == "WHO"
    assert DEFAULT_AUTO_EVIDENCE_TRUST_POLICY.is_trusted(provider_id="WHO", trust_class="WHO")
    assert who_trust_class(replace(source, license_url=None)) == "UNTRUSTED"
    assert who_trust_class(replace(source, content_origin="FAKE")) == "UNTRUSTED"


# 44
def test_44_who_provider_declares_no_full_text_capability():
    capabilities = WhoMedicalEvidenceProvider.descriptor.capabilities
    assert MedicalEvidenceCapability.SEARCH in capabilities
    assert MedicalEvidenceCapability.DIRECT_LOOKUP in capabilities
    assert MedicalEvidenceCapability.FULL_TEXT_ENRICHMENT not in capabilities


# 45
def test_45_search_is_server_bounded_and_has_no_patient_fields():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return response(request)

    provider_with(handler).search("influenza humidity child", 999)
    assert seen == [{"term": "influenza humidity child", "sort": "0", "pageSize": "25", "pageNumber": "0"}]


# 46
def test_46_lookup_uses_documented_uuid_api_and_enriches():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return response(request, payload=who_record())

    provider = provider_with(handler)
    source = provider.lookup(WHO_ID)
    assert seen == [f"/api/hubs/publications({WHO_ID})"]
    assert source.evidence_text and who_trust_class(source) == "WHO"


# 47
def test_47_lookup_404_returns_none():
    provider = provider_with(lambda request: response(request, status=404))
    assert provider.lookup(WHO_ID) is None


# 48
def test_48_search_deduplicates_duplicate_canonical_urls():
    duplicate = who_record(Id=WHO_ID_2, SystemSourceKey=WHO_ID_2)
    provider = provider_with(lambda request: response(request, payload=search_payload(who_record(), duplicate)))
    assert len(provider.search("influenza children", 10).sources) == 1


# 49
def test_49_who_source_and_content_persist_without_pmid():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    evidence = normalized()
    with Session(engine) as db:
        repository = MedicalKnowledgeRepository(db)
        source = repository.create_source(
            MedicalEvidenceSourceCreate(
                source_type="WHO", provider_id="WHO", external_id=evidence.external_id,
                source_kind=evidence.source_kind.value, title=evidence.title,
                doi=evidence.doi, publication_year=evidence.publication_year,
                abstract_text=evidence.abstract_text, url=evidence.canonical_url,
                retrieved_at=evidence.retrieved_at,
                raw_metadata_json=dict(evidence.provider_metadata),
            )
        )
        repository.create_evidence_content(
            MedicalEvidenceContentCreate(
                source_id=source.id, content_kind=evidence.content_kind,
                content_origin=evidence.content_origin, evidence_text=evidence.evidence_text,
                retrieved_at=evidence.retrieved_at, is_truncated=evidence.is_truncated,
                license_name=evidence.license_name, license_url=evidence.license_url,
                provenance_json=dict(evidence.provenance), content_sha256=evidence.content_sha256,
            )
        )
        db.commit()
        loaded = db.scalar(select(MedicalEvidenceSource))
        content = db.scalar(select(MedicalEvidenceContent))
        assert loaded.provider_id == "WHO" and loaded.pmid is None
        assert content.content_origin == "WHO_PUBLICATIONS_API"
    engine.dispose()


# 50
def test_50_v016_preserves_rows_is_idempotent_and_has_valid_foreign_keys():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE medical_evidence_sources (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO medical_evidence_sources(id) VALUES (1)")
        connection.exec_driver_sql(
            "CREATE TABLE medical_evidence_contents ("
            "id INTEGER PRIMARY KEY,source_id INTEGER NOT NULL,content_kind VARCHAR(32) NOT NULL "
            "CONSTRAINT ck_medical_evidence_content_kind CHECK(content_kind IN "
            "('ABSTRACT','PMC_FULL_TEXT','PMC_FULL_TEXT_EXCERPT')),"
            "content_origin VARCHAR(32) NOT NULL CONSTRAINT ck_medical_evidence_content_origin "
            "CHECK(content_origin IN ('NCBI_PUBMED','NCBI_PMC')),"
            "external_identifier VARCHAR(64),evidence_text TEXT NOT NULL,retrieved_at DATETIME NOT NULL,"
            "is_truncated BOOLEAN NOT NULL CHECK(is_truncated IN (0,1)),license_name VARCHAR(255),"
            "license_url TEXT,provenance_json JSON,content_sha256 VARCHAR(64) NOT NULL,"
            "created_at DATETIME NOT NULL,UNIQUE(source_id,content_sha256),"
            "FOREIGN KEY(source_id) REFERENCES medical_evidence_sources(id) ON DELETE CASCADE)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_medical_evidence_contents_source_id ON medical_evidence_contents(source_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_medical_evidence_contents_external_id ON medical_evidence_contents(external_identifier)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE medical_revision_sources (revision_id INTEGER, evidence_content_id INTEGER, "
            "FOREIGN KEY(evidence_content_id) REFERENCES medical_evidence_contents(id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO medical_evidence_contents VALUES "
            "(1,1,'ABSTRACT','NCBI_PUBMED',NULL,'old evidence','2026-01-01',0,NULL,NULL,NULL,"
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','2026-01-01')"
        )
        connection.exec_driver_sql("INSERT INTO medical_revision_sources VALUES (10,1)")
    upgrade_v016(engine)
    upgrade_v016(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT evidence_text FROM medical_evidence_contents").scalar() == "old evidence"
        assert connection.exec_driver_sql("SELECT evidence_content_id FROM medical_revision_sources").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    checks = " ".join(str(item["sqltext"]) for item in inspect(engine).get_check_constraints("medical_evidence_contents"))
    assert "OFFICIAL_SUMMARY_EXCERPT" in checks and "WHO_PUBLICATIONS_API" in checks
    engine.dispose()


# 51
def test_51_parent_citation_input_accepts_who_without_pmid():
    evidence = normalized()
    source = DraftSourceInput(
        source_id=1, source_type="WHO", title=evidence.title, pmid=None,
        evidence_content_id=2, content_kind=WHO_CONTENT_KIND,
        evidence_text=evidence.evidence_text, content_origin=WHO_CONTENT_ORIGIN,
        license_name=evidence.license_name, license_url=WHO_LICENSE_URL,
    )
    assert source.pmid is None and source.title == evidence.title


def test_53_who_query_uses_standard_utf8_parameter_encoding():
    seen = []

    def handler(request):
        seen.append(request.url)
        return response(request, payload={"Total": 0, "PagesCount": 0, "Results": []})

    provider_with(handler).search("Sốt xuất huyết humidity children / pediatric", 3)
    assert seen[0].params["term"] == "Sốt xuất huyết humidity children / pediatric"
    assert "%E1%BB%91" in str(seen[0])


def test_54_current_biblio_numeric_identity_shape_normalizes_metadata_only():
    # Shape A is the bounded WHO Biblio response observed from the official
    # page-owned route. Biblio IDs are numeric and are not REST UUIDs.
    payload = {
        "Total": 330,
        "PagesCount": 66,
        "Results": [
            {
                "Id": "73164",
                "Title": "Influenza publications for children",
                "NavigationUrl": "/publications/b/73164",
                "PublicationDate": "2018-01-01T00:00:00Z",
                "Publisher": "World Health Organization",
                "Language": "English",
            }
        ],
    }
    result = provider_with(lambda request: response(request, payload=payload)).search(
        "influenza humidity children", 5
    )
    source = result.sources[0]
    assert result.total_count == 330
    assert (source.external_id, source.canonical_url) == (
        "73164", "https://www.who.int/publications/b/73164"
    )
    assert source.evidence_text is None and who_trust_class(source) == "UNTRUSTED"


def test_55_unknown_search_wrapper_fails_closed_with_shape_code():
    provider = provider_with(
        lambda request: response(request, payload={"items": []})
    )
    with pytest.raises(MedicalEvidenceProviderBadResponseError) as captured:
        provider.search("influenza humidity children", 5)
    assert (captured.value.code, captured.value.stage) == (
        "WHO_SEARCH_RESPONSE_SHAPE_CHANGED", "shape"
    )


def test_56_json_suffix_content_type_is_supported():
    provider = provider_with(
        lambda request: response(
            request,
            content=b'{"Total":0,"PagesCount":0,"Results":[]}',
            headers={"content-type": "application/problem+json"},
        )
    )
    assert provider.search("influenza humidity children", 5).sources == ()


def test_57_direct_lookup_diagnostic_namespace_is_preserved():
    with pytest.raises(MedicalEvidenceProviderUnavailableError) as captured:
        provider_with(lambda request: response(request, status=503)).lookup(WHO_ID)
    assert captured.value.code == "WHO_LOOKUP_HTTP_STATUS"
