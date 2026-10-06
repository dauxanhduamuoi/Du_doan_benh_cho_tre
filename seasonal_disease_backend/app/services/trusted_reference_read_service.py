from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
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
    """Read persisted Reviewed references without prose, settings or Auto fallback."""

    def __init__(self, db: Session):
        self.repository = MedicalKnowledgeRepository(db)

    def read_batch(self, request: TrustedReferenceBatchRequest) -> TrustedReferenceBatchResponse:
        selectors = {
            (item.disease_group_id, *item.factor_identity): item
            for item in request.items
        }
        references: dict[tuple[str, str, str, str | None], dict[int, TrustedReference]] = {
            selector: {} for selector in selectors
        }
        for row in self.repository.get_published_reference_metadata(list(selectors)):
            selector = (
                row["disease_group_id"], row["factor_type"], row["factor_key"], row["factor_value"]
            )
            if selector not in references:
                continue
            policy_source = TrustedReferenceSourceMetadata(**{
                key: row[key] for key in TrustedReferenceSourceMetadata.__dataclass_fields__
            })
            if evaluate_trusted_reference_source(policy_source).decision != TrustedReferenceDecision.ALLOW_PARENT_REFERENCE:
                continue
            metadata = {key: row[key] for key in TrustedReference.model_fields}
            metadata["title"] = (metadata["title"] or "").strip()
            metadata["original_url"] = (metadata["original_url"] or "").strip()
            url = metadata["original_url"]
            if not url.lower().startswith(("https://", "http://")) or any(char.isspace() for char in url):
                continue
            try:
                reference = TrustedReference(**metadata)
            except ValidationError:
                # Missing/invalid metadata is an empty reference, never generation demand.
                continue
            if reference.original_url.username or reference.original_url.password:
                continue
            # Repository order is (sort_order, source_id); retain the first identity.
            references[selector].setdefault(reference.source_id, reference)
        return TrustedReferenceBatchResponse(items=[
            TrustedReferenceItem(selector=item, references=list(references[selector].values()))
            for selector, item in selectors.items()
        ])
