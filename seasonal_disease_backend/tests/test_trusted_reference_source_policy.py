from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from app.services.trusted_reference_source_policy import (
    TrustedReferenceDecision as Decision,
    TrustedReferenceSourceMetadata,
    evaluate_trusted_reference_source,
)
from app.services.who_evidence_provider import normalize_who_record


WHO_ID = "69e416c8-c71b-4e2b-839b-c6f44d59cc2f"


def verified_source(**overrides):
    # Use the actual normalizer's persisted metadata contract, not invented fields.
    record = normalize_who_record(
        {
            "Id": WHO_ID, "Title": "Official guidance", "PublicationType": "Guideline",
            "NavigationUrl": "/publications/i/item/9789240099999",
            "Summary": "Licensed summary", "Copyright": "CC BY-NC-SA 3.0 IGO",
        },
        retrieved_at=datetime(2025, 1, 1),
        retrieval_surface="WHO_PUBLICATIONS_REST_EXACT", max_excerpt_chars=6000,
    )
    return replace(TrustedReferenceSourceMetadata(
        provider_id=record.provider_id, source_type="WHO", external_id=record.external_id,
        source_kind=record.source_kind.value, original_url=record.canonical_url,
        content_origin=record.content_origin, content_external_id=record.external_id,
        provenance=dict(record.provenance),
    ), **overrides)


@pytest.mark.parametrize("kind", ["GUIDELINE", "HEALTH_GUIDANCE", "TECHNICAL_REPORT"])
@pytest.mark.parametrize("host", ["www.who.int", "who.int", "iris.who.int"])
def test_official_guidance_requires_consistent_persisted_identity(kind, host):
    source = verified_source(source_kind=kind)
    url = source.original_url.replace("www.who.int", host)
    source = replace(source, original_url=url, provenance={**source.provenance, "canonical_url": url})
    result = evaluate_trusted_reference_source(source)
    assert result.decision == Decision.ALLOW_PARENT_REFERENCE
    assert result.reason_code == "WHO_OFFICIAL_GUIDANCE"
    assert evaluate_trusted_reference_source(source) == result


@pytest.mark.parametrize("provider", ["PUBMED", "PMC"])
@pytest.mark.parametrize("kind", ["RESEARCH_ARTICLE", "SYSTEMATIC_REVIEW", "GUIDELINE"])
def test_pubmed_pmc_never_gain_parent_trust_from_kind_or_https(provider, kind):
    result = evaluate_trusted_reference_source(verified_source(
        provider_id=provider, source_type="PUBMED", source_kind=kind,
        original_url="https://pubmed.ncbi.nlm.nih.gov/12345/",
    ))
    assert result.decision == Decision.STAFF_ONLY
    assert result.reason_code == "PUBMED_RESEARCH_STAFF_ONLY"


@pytest.mark.parametrize("url", [
    "https://who.int.evil.example/guidance", "https://evil-who.int/guidance",
    "https://example.org/who.int", "https://subdomain.who.int/guidance",
])
def test_provider_host_mismatch_is_rejected(url):
    result = evaluate_trusted_reference_source(verified_source(original_url=url))
    assert result == type(result)(Decision.REJECT_PARENT_REFERENCE, "PROVIDER_HOST_MISMATCH")


@pytest.mark.parametrize("url", [
    "http://www.who.int/guidance", "javascript:alert(1)", "ftp://www.who.int/source",
    "/publications/b/10", "https:www.who.int/source", "https://",
    "https://user:password@www.who.int/source", "https://www.who.int:444/source",
    "https://www.who.int:bad/source", "https://www.who.int/bad path",
    "https://www.who.int/\nsource", "https://www.who.int/\\source",
])
def test_unsafe_or_non_absolute_non_https_url_is_rejected(url):
    result = evaluate_trusted_reference_source(verified_source(original_url=url))
    assert result.decision == Decision.REJECT_PARENT_REFERENCE
    assert result.reason_code == "UNSAFE_URL"


@pytest.mark.parametrize("changes", [
    {"provider_id": None}, {"external_id": None}, {"external_id": ""},
    {"provenance": None}, {"provenance": []}, {"provenance": {}},
    {"content_external_id": None}, {"content_origin": None},
    {"original_url": None}, {"source_kind": None}, {"source_kind": "OTHER"},
])
def test_missing_identity_or_unknown_kind_fails_closed(changes):
    assert evaluate_trusted_reference_source(verified_source(**changes)).decision == Decision.UNCERTAIN


@pytest.mark.parametrize("key,value", [
    ("provider_id", "PUBMED"), ("external_id", "different-record"),
    ("canonical_url", "https://www.who.int/publications/i/item/different-record"),
    ("canonical_url", "https://example.org/guidance"),
])
def test_provenance_cannot_disagree_with_source(key, value):
    source = verified_source()
    source = replace(source, provenance={**source.provenance, key: value})
    result = evaluate_trusted_reference_source(source)
    assert result.decision == Decision.REJECT_PARENT_REFERENCE
    assert result.reason_code == "SOURCE_IDENTITY_MISMATCH"


@pytest.mark.parametrize("key,value", [
    ("retrieval_surface", "WHO_BIBLIO_SEARCH_REFERENCE"), ("retrieval_surface", "UNKNOWN"),
    ("retrieval_surface", []), ("metadata_storage_allowed", None),
    ("metadata_storage_allowed", "true"), ("full_text_stored", None),
])
def test_unverified_or_malformed_provenance_does_not_raise_or_allow(key, value):
    source = verified_source()
    source = replace(source, provenance={**source.provenance, key: value})
    assert evaluate_trusted_reference_source(source).decision == Decision.UNCERTAIN


def test_metadata_only_import_marker_is_not_provider_verification():
    source = verified_source(provenance=None, content_origin=None, content_external_id=None)
    assert evaluate_trusted_reference_source(source).decision == Decision.UNCERTAIN


@pytest.mark.parametrize("provider", ["OTHER", "CDC", "UNKNOWN"])
def test_unsupported_provider_does_not_gain_trust_from_official_url(provider):
    result = evaluate_trusted_reference_source(verified_source(provider_id=provider, source_type="OTHER"))
    assert result.decision == Decision.UNCERTAIN
    assert result.reason_code == "UNSUPPORTED_PROVIDER"


@pytest.mark.parametrize("kind", ["RESEARCH_ARTICLE", "SYSTEMATIC_REVIEW"])
def test_who_research_is_staff_only(kind):
    assert evaluate_trusted_reference_source(verified_source(source_kind=kind)).decision == Decision.STAFF_ONLY


@pytest.mark.parametrize("changes", [{"source_type": "PUBMED"}, {"content_external_id": "wrong"}])
def test_provider_and_snapshot_identity_conflicts_are_rejected(changes):
    assert evaluate_trusted_reference_source(verified_source(**changes)).decision == Decision.REJECT_PARENT_REFERENCE


def test_numeric_identity_cannot_claim_another_biblio_path():
    source = verified_source(external_id="10", content_external_id="10", original_url="https://www.who.int/publications/b/20")
    source = replace(source, provenance={**source.provenance, "external_id": "10", "canonical_url": source.original_url})
    assert evaluate_trusted_reference_source(source).decision == Decision.REJECT_PARENT_REFERENCE


def test_excerpt_license_is_not_a_requirement_for_link_policy():
    source = verified_source()
    source = replace(source, provenance={**source.provenance, "license_allowlisted": False, "license_status": "UNKNOWN"})
    assert evaluate_trusted_reference_source(source).decision == Decision.ALLOW_PARENT_REFERENCE
