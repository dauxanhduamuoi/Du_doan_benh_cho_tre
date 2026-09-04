from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from app.services.pmc_client import PmcClient
from app.services.pmc_content_parser import parse_pmc_article, select_bounded_pmc_content
from app.services.pubmed_client import PubMedError


@dataclass(frozen=True)
class ResolvedEvidenceContent:
    content_kind: str
    content_origin: str
    external_identifier: str | None
    evidence_text: str
    retrieved_at: datetime
    is_truncated: bool
    license_name: str | None
    license_url: str | None
    provenance: dict[str, str | bool | None]

    @property
    def content_sha256(self) -> str:
        canonical = json.dumps(
            {
                "kind": self.content_kind,
                "origin": self.content_origin,
                "external_identifier": self.external_identifier,
                "text": self.evidence_text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _license_allows_cloud_evidence(license_url: str | None) -> bool:
    if not license_url:
        return False
    normalized = license_url.strip().lower().replace("http://", "https://")
    return normalized.startswith("https://creativecommons.org/licenses/by/") or normalized.startswith(
        "https://creativecommons.org/publicdomain/zero/"
    )


class MedicalEvidenceContentService:
    """Resolve a bounded evidence snapshot, with PubMed abstract as safe fallback."""

    def __init__(self, pmc_client: PmcClient | None, *, max_chars_per_source: int = 6000):
        self.pmc_client = pmc_client
        self.max_chars_per_source = max_chars_per_source

    def resolve(
        self, *, pmid: str, abstract_text: str | None, retrieved_at: datetime | None = None
    ) -> ResolvedEvidenceContent | None:
        now = retrieved_at or datetime.utcnow()
        pmcid: str | None = None
        fallback_reason = "pmc_client_unavailable"
        if self.pmc_client is not None:
            try:
                pmcid = self.pmc_client.resolve_pmcid(pmid)
                if pmcid is None:
                    fallback_reason = "no_pmcid"
                else:
                    article = parse_pmc_article(self.pmc_client.fetch_article_xml(pmcid))
                    if not article.has_body_content:
                        fallback_reason = "pmc_no_body_content"
                    elif not _license_allows_cloud_evidence(article.license_url):
                        fallback_reason = "license_not_allowlisted"
                    else:
                        selected = select_bounded_pmc_content(
                            article, max_chars=self.max_chars_per_source
                        )
                        return ResolvedEvidenceContent(
                            content_kind=(
                                "PMC_FULL_TEXT_EXCERPT" if selected.is_excerpt else "PMC_FULL_TEXT"
                            ),
                            content_origin="NCBI_PMC",
                            external_identifier=pmcid,
                            evidence_text=selected.text,
                            retrieved_at=now,
                            is_truncated=selected.is_excerpt,
                            license_name=article.license_name,
                            license_url=article.license_url,
                            provenance={
                                "provider": "NCBI PMC",
                                "retrieval": "ELink pubmed_pmc + EFetch db=pmc",
                                "pmid": pmid,
                                "pmcid": pmcid,
                                "license_allowlisted": True,
                            },
                        )
            except (PubMedError, ValueError):
                fallback_reason = "pmc_retrieval_or_parse_failed"

        abstract = (abstract_text or "").strip()
        if not abstract:
            return None
        bounded_abstract = abstract[: self.max_chars_per_source]
        return ResolvedEvidenceContent(
            content_kind="ABSTRACT",
            content_origin="NCBI_PUBMED",
            external_identifier=pmcid,
            evidence_text=bounded_abstract,
            retrieved_at=now,
            is_truncated=len(bounded_abstract) < len(abstract),
            license_name=None,
            license_url=None,
            provenance={
                "provider": "NCBI PubMed",
                "pmid": pmid,
                "pmcid": pmcid,
                "fallback_reason": fallback_reason,
                "license_allowlisted": False,
            },
        )
