from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.repositories.parent_trusted_reference_repository import ParentTrustedReferenceRepository
from app.services.parent_trusted_reference_identity import CURATION_POLICY_VERSION, build_parent_reference_identity
from app.services.trusted_reference_source_policy import (
    TrustedReferenceDecision,
    TrustedReferenceSourceMetadata,
    evaluate_trusted_reference_source,
)
from app.trusted_reference_schemas import (
    TrustedReference,
    TrustedReferenceBatchRequest,
    TrustedReferenceBatchResponse,
    TrustedReferenceItem,
)


class TrustedReferenceReadService:
    """Read eligible APPROVED curation only; no legacy fallback or repairs."""

    def __init__(self, db: Session):
        self.repository = ParentTrustedReferenceRepository(db)

    def read_batch(self, request: TrustedReferenceBatchRequest) -> TrustedReferenceBatchResponse:
        selectors = {
            (item.disease_group_id, *item.factor_identity): item
            for item in request.items
        }
        references: dict[tuple[str, str, str, str | None], dict[int, TrustedReference]] = {
            selector: {} for selector in selectors
        }
        for row in self.repository.get_approved_reference_metadata(list(selectors)):
            selector = (
                row["disease_group_id"], row["factor_type"], row["factor_key"], row["factor_value"]
            )
            if selector not in references:
                continue
            if row["policy_version"] != CURATION_POLICY_VERSION or not row["identity_sha256"]:
                continue
            selected = dict(zip(("disease_group_id", "factor_type", "factor_key", "factor_value"), selector))
            source = {key: row[key] for key in (
                "provider_id", "source_type", "external_id", "source_kind", "title", "journal", "publication_year",
            )}
            source.update(id=row["source_id"], url=row["original_url"])
            proof = dict(id=row["proof_id"], source_id=row["proof_source_id"], content_kind=row["content_kind"],
                         content_origin=row["content_origin"], external_identifier=row["content_external_id"],
                         provenance_json=row["provenance"], content_sha256=row["content_sha256"])
            try:
                snapshot, digest = build_parent_reference_identity(selected, source, proof)
            except (ValueError, KeyError, TypeError):
                continue  # Malformed proof metadata is ineligible; never repaired.
            if digest != row["identity_sha256"] or snapshot != row["identity_snapshot_json"]:
                continue
            policy_source = TrustedReferenceSourceMetadata(**{
                key: row[key] for key in TrustedReferenceSourceMetadata.__dataclass_fields__
            })
            if evaluate_trusted_reference_source(policy_source).decision != TrustedReferenceDecision.ALLOW_PARENT_REFERENCE:
                continue
            metadata = {key: row[key] for key in TrustedReference.model_fields}
            metadata["title"] = (metadata["title"] or "").strip()
            metadata["original_url"] = snapshot["original_url"] or ""
            url = metadata["original_url"]
            if not url.startswith("https://") or urlsplit(url).query or any(char.isspace() for char in url):
                # Canonical links omit fragments; query credentials must not reach Parent.
                continue
            try:
                reference = TrustedReference(**metadata)
            except ValidationError:
                # Missing/invalid metadata is an empty reference, never generation demand.
                continue
            if reference.original_url.username or reference.original_url.password:
                continue
            # Curation order is (sort_order, source_id); retain the first identity.
            references[selector].setdefault(reference.source_id, reference)
        return TrustedReferenceBatchResponse(items=[
            TrustedReferenceItem(selector=item, references=list(references[selector].values()))
            for selector, item in selectors.items()
        ])
