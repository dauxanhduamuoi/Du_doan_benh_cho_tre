from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit, urlunsplit

from app.services.medical_evidence_provider import (
    MedicalEvidenceProviderBadResponseError,
    MedicalEvidenceSourceKind,
)
from app.services.who_evidence_provider import WHO_CONTENT_ORIGIN, _official_url


class TrustedReferenceDecision(str, Enum):
    ALLOW_PARENT_REFERENCE = "ALLOW_PARENT_REFERENCE"
    STAFF_ONLY = "STAFF_ONLY"
    REJECT_PARENT_REFERENCE = "REJECT_PARENT_REFERENCE"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class TrustedReferencePolicyResult:
    decision: TrustedReferenceDecision
    reason_code: str


@dataclass(frozen=True)
class TrustedReferenceSourceMetadata:
    """Persisted identity/provenance only; no medical body or generated prose."""

    provider_id: str | None
    source_type: str | None
    external_id: str | None
    source_kind: str | None
    original_url: str | None
    content_origin: str | None = None
    content_external_id: str | None = None
    provenance: object = None


_GUIDANCE_KINDS = frozenset({
    MedicalEvidenceSourceKind.GUIDELINE.value,
    MedicalEvidenceSourceKind.HEALTH_GUIDANCE.value,
    MedicalEvidenceSourceKind.TECHNICAL_REPORT.value,
})
_RESEARCH_KINDS = frozenset({
    MedicalEvidenceSourceKind.RESEARCH_ARTICLE.value,
    MedicalEvidenceSourceKind.SYSTEMATIC_REVIEW.value,
})
_WHO_RETRIEVAL_SURFACES = frozenset({
    "WHO_BIBLIO_SEARCH", "WHO_PUBLICATIONS_REST_API", "WHO_PUBLICATIONS_REST_EXACT",
})


def _https_identity(value: object) -> str | None:
    if not isinstance(value, str) or not value or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value
    ) or "\\" in value:
        return None
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https" or not parts.hostname
            or parts.username or parts.password or parts.port not in (None, 443)
        ):
            return None
        return urlunsplit(("https", parts.hostname.casefold(), parts.path.rstrip("/") or "/", parts.query, ""))
    except ValueError:
        return None


def evaluate_trusted_reference_source(
    source: TrustedReferenceSourceMetadata,
) -> TrustedReferencePolicyResult:
    """Fail closed independently of publication, Auto and drafting trust policies.

    WHO proof must be from the snapshot linked to this revision AND source.
    Metadata-only imports have no such proof and remain UNCERTAIN in V1.
    License/body availability is deliberately not a condition for a read-more link.
    """
    decision = TrustedReferenceDecision

    def result(value: TrustedReferenceDecision, reason: str) -> TrustedReferencePolicyResult:
        return TrustedReferencePolicyResult(value, reason)

    if not source.original_url:
        return result(decision.UNCERTAIN, "MISSING_TRUST_METADATA")
    canonical = _https_identity(source.original_url)
    if canonical is None:
        return result(decision.REJECT_PARENT_REFERENCE, "UNSAFE_URL")
    if not source.provider_id:
        return result(decision.UNCERTAIN, "MISSING_TRUST_METADATA")
    if source.provider_id in {"PUBMED", "PMC"}:
        return result(decision.STAFF_ONLY, "PUBMED_RESEARCH_STAFF_ONLY")
    if source.provider_id != "WHO":
        return result(decision.UNCERTAIN, "UNSUPPORTED_PROVIDER")
    if source.source_type not in (None, "WHO"):
        return result(decision.REJECT_PARENT_REFERENCE, "PROVIDER_IDENTITY_MISMATCH")
    try:
        # This provider helper is pure: reuse its exact host/HTTPS/port rules,
        # without constructing a provider or performing lookup/enrichment.
        _official_url(source.original_url, required=True)
    except (MedicalEvidenceProviderBadResponseError, ValueError):
        return result(decision.REJECT_PARENT_REFERENCE, "PROVIDER_HOST_MISMATCH")
    if source.source_kind in _RESEARCH_KINDS:
        return result(decision.STAFF_ONLY, "RESEARCH_LITERATURE_STAFF_ONLY")
    if source.source_kind not in _GUIDANCE_KINDS:
        return result(decision.UNCERTAIN, "UNSUPPORTED_SOURCE_KIND")
    if not isinstance(source.external_id, str) or not source.external_id.strip():
        return result(decision.UNCERTAIN, "MISSING_TRUST_METADATA")
    if source.external_id != source.external_id.strip():
        return result(decision.REJECT_PARENT_REFERENCE, "SOURCE_IDENTITY_MISMATCH")
    if source.external_id.isdigit():
        # Numeric Biblio identity uses the same ID/path contract as Reviewed
        # import. A label/provenance assertion cannot override a different ID.
        parts = urlsplit(canonical)
        if parts.path != f"/publications/b/{source.external_id}" or parts.query:
            return result(decision.REJECT_PARENT_REFERENCE, "SOURCE_IDENTITY_MISMATCH")
    if not isinstance(source.provenance, Mapping):
        return result(decision.UNCERTAIN, "MISSING_TRUST_METADATA")
    proof = source.provenance
    if any(not proof.get(key) for key in ("provider_id", "external_id", "canonical_url")):
        return result(decision.UNCERTAIN, "MISSING_TRUST_METADATA")
    if (
        proof["provider_id"] != "WHO"
        or proof["external_id"] != source.external_id
        or _https_identity(proof["canonical_url"]) != canonical
        or (source.content_external_id is not None and source.content_external_id != source.external_id)
    ):
        return result(decision.REJECT_PARENT_REFERENCE, "SOURCE_IDENTITY_MISMATCH")
    if (
        source.content_origin != WHO_CONTENT_ORIGIN
        or source.content_external_id is None
        or not isinstance(proof.get("retrieval_surface"), str)
        or proof.get("retrieval_surface") not in _WHO_RETRIEVAL_SURFACES
        or proof.get("metadata_storage_allowed") is not True
        or proof.get("full_text_stored") is not False
    ):
        return result(decision.UNCERTAIN, "MISSING_TRUST_METADATA")
    return result(decision.ALLOW_PARENT_REFERENCE, "WHO_OFFICIAL_GUIDANCE")
