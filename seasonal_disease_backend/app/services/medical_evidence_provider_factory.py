from __future__ import annotations

from app.config import (
    MEDICAL_KNOWLEDGE_EVIDENCE_MAX_CHARS_PER_SOURCE,
    NCBI_API_KEY,
    NCBI_EMAIL,
    NCBI_TOOL,
    WHO_EVIDENCE_MAX_RESPONSE_BYTES,
    WHO_EVIDENCE_TIMEOUT_SECONDS,
)
from app.services.medical_evidence_content_service import MedicalEvidenceContentService
from app.services.medical_evidence_provider import MedicalEvidenceProviderRegistry
from app.services.pmc_client import PmcClient
from app.services.pubmed_client import PubMedClient
from app.services.pubmed_evidence_provider import PubMedMedicalEvidenceProvider
from app.services.who_evidence_provider import WhoMedicalEvidenceProvider


# Registration is inventory only. These defaults intentionally remain separate
# until the Admin Medical Source Settings task adds persisted selection.
DEFAULT_AUTO_MEDICAL_EVIDENCE_PROVIDER_IDS = ("PUBMED",)
DEFAULT_REVIEWED_MEDICAL_EVIDENCE_PROVIDER_IDS = ("PUBMED",)


def create_medical_evidence_provider_registry() -> MedicalEvidenceProviderRegistry:
    """Construct the production registry in one configuration-owned boundary."""

    registry = MedicalEvidenceProviderRegistry()
    client = PubMedClient(tool=NCBI_TOOL, email=NCBI_EMAIL, api_key=NCBI_API_KEY)
    registry.register(
        PubMedMedicalEvidenceProvider(
            client,
            MedicalEvidenceContentService(
                PmcClient(client),
                max_chars_per_source=MEDICAL_KNOWLEDGE_EVIDENCE_MAX_CHARS_PER_SOURCE,
            ),
        )
    )
    registry.register(
        WhoMedicalEvidenceProvider(
            timeout_seconds=WHO_EVIDENCE_TIMEOUT_SECONDS,
            max_response_bytes=WHO_EVIDENCE_MAX_RESPONSE_BYTES,
            max_excerpt_chars=MEDICAL_KNOWLEDGE_EVIDENCE_MAX_CHARS_PER_SOURCE,
        )
    )
    return registry
