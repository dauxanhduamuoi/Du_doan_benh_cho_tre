from __future__ import annotations

from dataclasses import dataclass, field
import re
import threading
import time
from typing import Any, Callable
from xml.etree import ElementTree

import httpx


EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
PUBMED_RECORD_URL = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


class PubMedError(Exception):
    pass


class PubMedConfigurationError(PubMedError):
    pass


class PubMedUnavailableError(PubMedError):
    pass


class PubMedRateLimitError(PubMedUnavailableError):
    pass


class PubMedParseError(PubMedUnavailableError):
    pass


@dataclass(frozen=True)
class PubMedArticleRecord:
    pmid: str
    title: str
    authors: str | None
    journal: str | None
    publication_year: int | None
    doi: str | None
    abstract_text: str | None
    pubmed_url: str
    pmcid: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class PubMedRequestRateLimiter:
    """Process-local conservative limiter for NCBI request start times."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, sleeper: Callable[[float], None] = time.sleep):
        self._clock = clock
        self._sleep = sleeper
        self._lock = threading.Lock()
        self._next_request_at = 0.0

    def wait(self, has_api_key: bool) -> None:
        interval = 0.1 if has_api_key else 1.0 / 3.0
        with self._lock:
            now = self._clock()
            delay = max(0.0, self._next_request_at - now)
            if delay:
                self._sleep(delay)
                now = self._clock()
            self._next_request_at = max(now, self._next_request_at) + interval


_GLOBAL_RATE_LIMITER = PubMedRequestRateLimiter()


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    value = " ".join("".join(element.itertext()).split())
    return value or None


def _publication_year(article: ElementTree.Element) -> int | None:
    candidates = (
        article.find(".//Article/Journal/JournalIssue/PubDate/Year"),
        article.find(".//ArticleDate/Year"),
        article.find(".//DateCompleted/Year"),
        article.find(".//Article/Journal/JournalIssue/PubDate/MedlineDate"),
    )
    for candidate in candidates:
        value = _text(candidate)
        match = re.search(r"\b(?:18|19|20)\d{2}\b", value or "")
        if match:
            return int(match.group(0))
    return None


def _authors(article: ElementTree.Element) -> str | None:
    values: list[str] = []
    for author in article.findall(".//Article/AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        if collective:
            values.append(collective)
            continue
        last_name = _text(author.find("LastName"))
        given_name = _text(author.find("ForeName")) or _text(author.find("Initials"))
        name = " ".join(part for part in (given_name, last_name) if part)
        if name:
            values.append(name)
    return ", ".join(values) or None


def _doi(article: ElementTree.Element) -> str | None:
    for article_id in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if (article_id.get("IdType") or "").lower() == "doi":
            return _text(article_id)
    for location_id in article.findall(".//Article/ELocationID"):
        if (location_id.get("EIdType") or "").lower() == "doi":
            return _text(location_id)
    return None


def _pmcid(article: ElementTree.Element) -> str | None:
    for article_id in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if (article_id.get("IdType") or "").lower() == "pmc":
            return _text(article_id)
    return None


def _abstract(article: ElementTree.Element) -> str | None:
    sections: list[str] = []
    for section in article.findall(".//Article/Abstract/AbstractText"):
        value = _text(section)
        if not value:
            continue
        label = (section.get("Label") or "").strip()
        sections.append(f"{label}: {value}" if label else value)
    return " ".join(sections) or None


def parse_pubmed_records(xml_content: bytes | str) -> list[PubMedArticleRecord]:
    try:
        root = ElementTree.fromstring(xml_content)
    except (ElementTree.ParseError, ValueError) as exc:
        raise PubMedParseError("PubMed returned invalid XML") from exc

    records: list[PubMedArticleRecord] = []
    for article in [*root.findall(".//PubmedArticle"), *root.findall(".//PubmedBookArticle")]:
        pmid = _text(article.find(".//MedlineCitation/PMID")) or _text(article.find(".//BookDocument/PMID"))
        title = _text(article.find(".//Article/ArticleTitle")) or _text(article.find(".//BookDocument/ArticleTitle"))
        if not pmid or not pmid.isdigit() or not title:
            continue
        publication_types = [
            value for node in article.findall(".//PublicationTypeList/PublicationType") if (value := _text(node))
        ]
        languages = [value for node in article.findall(".//Language") if (value := _text(node))]
        journal_identifiers = {
            (node.get("IdType") or "unknown"): value
            for node in article.findall(".//JournalInfo/JournalId")
            if (value := _text(node))
        }
        doi = _doi(article)
        pmcid = _pmcid(article)
        mesh_terms = [
            value
            for node in article.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
            if (value := _text(node))
        ]
        records.append(
            PubMedArticleRecord(
                pmid=pmid,
                title=title,
                authors=_authors(article),
                journal=_text(article.find(".//Article/Journal/Title")),
                publication_year=_publication_year(article),
                doi=doi,
                abstract_text=_abstract(article),
                pubmed_url=PUBMED_RECORD_URL.format(pmid=pmid),
                pmcid=pmcid,
                raw_metadata={
                    "provider": "NCBI PubMed",
                    "pmid": pmid,
                    "doi": doi,
                    "pmcid": pmcid,
                    "publication_types": publication_types,
                    "languages": languages,
                    "journal_identifiers": journal_identifiers,
                    "mesh_terms": mesh_terms,
                },
            )
        )
    return records


class PubMedClient:
    def __init__(
        self,
        *,
        tool: str,
        email: str | None,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        rate_limiter: PubMedRequestRateLimiter = _GLOBAL_RATE_LIMITER,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.tool = tool
        self.email = email
        self.api_key = api_key
        self.max_retries = max_retries
        self.rate_limiter = rate_limiter
        self.sleeper = sleeper
        self._client = client or httpx.Client(base_url=EUTILS_BASE_URL, timeout=timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _config_params(self) -> dict[str, str]:
        if not self.email:
            raise PubMedConfigurationError("NCBI_EMAIL is required for PubMed requests")
        if not self.tool or not re.fullmatch(r"[A-Za-z0-9_.-]+", self.tool):
            raise PubMedConfigurationError("NCBI_TOOL must be a non-empty identifier without spaces")
        params = {"tool": self.tool, "email": self.email}
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _request(self, endpoint: str, params: dict[str, str | int]) -> bytes:
        safe_params = {**params, **self._config_params()}
        for attempt in range(self.max_retries + 1):
            self.rate_limiter.wait(bool(self.api_key))
            try:
                # POST keeps bounded but potentially long search expressions and
                # the optional API key out of request URLs/access logs.
                response = self._client.post(endpoint, data=safe_params)
            except httpx.RequestError as exc:
                if attempt >= self.max_retries:
                    raise PubMedUnavailableError("PubMed request timed out or failed") from exc
                self.sleeper(0.25 * (2**attempt))
                continue
            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise PubMedRateLimitError("PubMed rate limit exceeded")
                retry_after = response.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 0.5 * (2**attempt)
                self.sleeper(min(delay, 2.0))
                continue
            if 500 <= response.status_code < 600:
                if attempt >= self.max_retries:
                    raise PubMedUnavailableError("PubMed service is unavailable")
                self.sleeper(0.25 * (2**attempt))
                continue
            if response.is_error:
                raise PubMedUnavailableError(f"PubMed request failed with HTTP {response.status_code}")
            return response.content
        raise PubMedUnavailableError("PubMed request failed")

    def request_eutils(self, endpoint: str, params: dict[str, str | int]) -> bytes:
        """Expose the shared, policy-compliant NCBI transport to sibling clients."""

        return self._request(endpoint, params)

    def search_ids(self, query: str, max_results: int) -> tuple[int, list[str]]:
        content = self._request(
            "esearch.fcgi",
            {"db": "pubmed", "term": query, "retmode": "xml", "retmax": max_results, "sort": "relevance"},
        )
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            raise PubMedParseError("PubMed ESearch returned invalid XML") from exc
        error = _text(root.find(".//ERROR"))
        if error:
            raise PubMedUnavailableError("PubMed rejected the search query")
        count_text = _text(root.find("Count")) or "0"
        ids = [value for node in root.findall(".//IdList/Id") if (value := _text(node)) and value.isdigit()]
        return int(count_text) if count_text.isdigit() else len(ids), ids

    def fetch_records(self, pmids: list[str]) -> list[PubMedArticleRecord]:
        if not pmids:
            return []
        content = self._request(
            "efetch.fcgi",
            {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
        )
        return parse_pubmed_records(content)

    def get_article_by_pmid(self, pmid: str) -> PubMedArticleRecord | None:
        """Fetch one exact PubMed record while reusing the bounded EFetch parser."""

        return next((record for record in self.fetch_records([pmid]) if record.pmid == pmid), None)

    def search(self, query: str, max_results: int) -> tuple[int, list[PubMedArticleRecord]]:
        total_count, pmids = self.search_ids(query, max_results)
        return total_count, self.fetch_records(pmids)
