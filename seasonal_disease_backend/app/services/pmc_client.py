from __future__ import annotations

from typing import Protocol
from xml.etree import ElementTree

from app.services.pubmed_client import PubMedParseError, PubMedUnavailableError


class NcbiEutilsRequester(Protocol):
    def request_eutils(self, endpoint: str, params: dict[str, str | int]) -> bytes:
        ...


class PmcParseError(PubMedParseError):
    pass


def parse_pmcid_link(xml_content: bytes | str) -> str | None:
    """Parse the official PubMed-to-PMC ELink response."""

    try:
        root = ElementTree.fromstring(xml_content)
    except (ElementTree.ParseError, ValueError) as exc:
        raise PmcParseError("NCBI ELink returned invalid XML") from exc

    for link_set in root.findall(".//LinkSetDb"):
        db_to = (link_set.findtext("DbTo") or "").strip().lower()
        link_name = (link_set.findtext("LinkName") or "").strip().lower()
        if db_to != "pmc" or link_name != "pubmed_pmc":
            continue
        for identifier in link_set.findall("./Link/Id"):
            value = (identifier.text or "").strip()
            if value.isdigit():
                return f"PMC{value}"
    return None


class PmcClient:
    """Official NCBI ELink/EFetch client; no HTML or publisher scraping."""

    def __init__(self, requester: NcbiEutilsRequester):
        self.requester = requester

    def resolve_pmcid(self, pmid: str) -> str | None:
        content = self.requester.request_eutils(
            "elink.fcgi",
            {
                "dbfrom": "pubmed",
                "db": "pmc",
                "id": pmid,
                "linkname": "pubmed_pmc",
                "retmode": "xml",
            },
        )
        return parse_pmcid_link(content)

    def fetch_article_xml(self, pmcid: str) -> bytes:
        normalized = pmcid.strip().upper()
        if not normalized.startswith("PMC") or not normalized[3:].isdigit():
            raise ValueError("PMCID must use the PMC followed by digits format")
        content = self.requester.request_eutils(
            "efetch.fcgi",
            {"db": "pmc", "id": normalized, "retmode": "xml"},
        )
        if not content.strip():
            raise PubMedUnavailableError("PMC EFetch returned an empty response")
        return content
