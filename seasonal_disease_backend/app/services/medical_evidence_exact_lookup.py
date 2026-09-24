"""Human-selected identity retrieval, separate from Guided relevance discovery."""
from app.services.medical_evidence_provider import (
    ExactMedicalEvidenceProvider, MedicalEvidenceProviderBadResponseError,
    MedicalEvidenceProviderRegistry, NormalizedMedicalEvidence,
)


def lookup_exact(
    registry: MedicalEvidenceProviderRegistry, provider_id: str, identifier: str,
) -> NormalizedMedicalEvidence | None:
    provider = registry.get(provider_id)
    if not isinstance(provider, ExactMedicalEvidenceProvider) or not provider.descriptor.exact_identifier_types:
        raise ValueError("INVALID_IDENTIFIER: provider does not support exact lookup")
    source = provider.lookup_exact(identifier)
    if source is not None and source.provider_id != provider.descriptor.provider_id:
        raise MedicalEvidenceProviderBadResponseError("Exact lookup returned a different provider")
    # The provider verifies its own identifier grammar and returned identity.
    # Do not classify or enrich (which could change identity) on this path.
    return source
