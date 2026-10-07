from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from app.services.trusted_reference_source_policy import _https_identity


# Preserve the Phase B version and JSON bytes; existing approvals remain valid.
CURATION_POLICY_VERSION = "parent-source-policy-v1"


def build_parent_reference_identity(selected: Mapping, source: Mapping, proof: Mapping) -> tuple[dict, str]:
    """Pure Phase B snapshot/SHA-256 builder shared by approval and batch reads.

    Callers enforce selector, ownership and Source Policy separately. Only the
    selected proof's identity/provenance is included, never body or arbitrary JSON.
    Malformed metadata raises ValueError/KeyError/TypeError, which readers hide.
    """
    provenance = proof["provenance_json"]
    if not isinstance(provenance, Mapping):
        raise ValueError("Proof provenance is missing")
    snapshot = dict(
        selector=dict(selected), source_id=source["id"], provider_id=source["provider_id"],
        source_type=source["source_type"], external_id=source["external_id"],
        original_url=_https_identity(source["url"]), source_kind=source["source_kind"],
        display=dict(title=source["title"], publisher=source["journal"], year=source["publication_year"]),
        proof=dict(evidence_content_id=proof["id"], source_id=proof["source_id"],
                   content_kind=proof["content_kind"], content_origin=proof["content_origin"],
                   external_identifier=proof["external_identifier"], content_sha256=proof["content_sha256"],
                   provider_id=provenance["provider_id"], external_id=provenance["external_id"],
                   canonical_url=_https_identity(provenance["canonical_url"]),
                   retrieval_surface=provenance["retrieval_surface"],
                   metadata_storage_allowed=provenance["metadata_storage_allowed"],
                   full_text_stored=provenance["full_text_stored"]),
        policy_version=CURATION_POLICY_VERSION,
    )
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return snapshot, hashlib.sha256(encoded.encode("utf-8")).hexdigest()
