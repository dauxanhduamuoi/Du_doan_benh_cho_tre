from __future__ import annotations

import httpx
import pytest
from urllib.parse import parse_qs

from app.services.pubmed_client import (
    EUTILS_BASE_URL,
    PubMedClient,
    PubMedConfigurationError,
    PubMedParseError,
    PubMedRateLimitError,
    PubMedUnavailableError,
    parse_pubmed_records,
)
from app.services.pubmed_query_builder import WEATHER_SEARCH_TERMS, build_pubmed_query


PUBMED_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <Journal>
          <JournalIssue><PubDate><MedlineDate>2024 Jan-Feb</MedlineDate></PubDate></JournalIssue>
          <Title>Journal of Weather Medicine</Title>
        </Journal>
        <ArticleTitle>Weather and <i>pediatric</i> gastroenteritis</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">First section.</AbstractText>
          <AbstractText Label="METHODS">Second <b>section</b>.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Nguyen</LastName><ForeName>An</ForeName></Author>
          <Author><LastName>Smith</LastName><Initials>BC</Initials></Author>
          <Author><CollectiveName>Weather Study Group</CollectiveName></Author>
        </AuthorList>
        <Language>eng</Language>
        <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList><ArticleId IdType="doi">10.1000/example</ArticleId></ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

MISSING_FIELDS_XML = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation>
<PMID>87654321</PMID><Article><Journal><Title>Minimal Journal</Title></Journal>
<ArticleTitle>Minimal article</ArticleTitle></Article></MedlineCitation>
</PubmedArticle></PubmedArticleSet>"""


class NoopRateLimiter:
    def wait(self, has_api_key: bool) -> None:
        return None


def make_client(handler, **kwargs) -> PubMedClient:
    http_client = httpx.Client(transport=httpx.MockTransport(handler), base_url=EUTILS_BASE_URL)
    return PubMedClient(
        tool="weather_ai_tests",
        email="tests@example.org",
        client=http_client,
        rate_limiter=NoopRateLimiter(),
        sleeper=lambda _seconds: None,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("factor", "expected"),
    [
        ("temperature", '"temperature"[Title/Abstract]'),
        ("precipitation", '"rainfall"[Title/Abstract]'),
        ("humidity", '"humidity"[Title/Abstract]'),
        ("wind", '"wind speed"[Title/Abstract]'),
        ("weather_condition", '"meteorological conditions"[Title/Abstract]'),
    ],
)
def test_query_builder_has_disease_and_weather_components(factor, expected):
    query = build_pubmed_query(["gastroenteritis", "infectious diarrhea"], factor)
    assert query.startswith('("gastroenteritis"[Title/Abstract] OR "infectious diarrhea"[Title/Abstract]) AND (')
    assert expected in query
    assert tuple(WEATHER_SEARCH_TERMS) == (
        "temperature",
        "humidity",
        "precipitation",
        "wind",
        "weather_condition",
    )


def test_query_builder_adds_year_range_deterministically():
    query = build_pubmed_query(["asthma"], "temperature", year_from=2020, year_to=2024)
    assert query.endswith('AND ("2020"[Date - Publication] : "2024"[Date - Publication])')


def test_query_builder_rejects_unsupported_weather_factor():
    with pytest.raises(ValueError, match="Unsupported"):
        build_pubmed_query(["asthma"], "air_pressure")


def test_query_builder_rejects_empty_disease_terms():
    with pytest.raises(ValueError, match="At least one"):
        build_pubmed_query([], "humidity")


def test_parser_reads_complete_record_and_nested_text():
    record = parse_pubmed_records(PUBMED_XML)[0]
    assert record.pmid == "12345678"
    assert record.title == "Weather and pediatric gastroenteritis"
    assert record.authors == "An Nguyen, BC Smith, Weather Study Group"
    assert record.doi == "10.1000/example"
    assert record.journal == "Journal of Weather Medicine"
    assert record.publication_year == 2024
    assert record.abstract_text == "BACKGROUND: First section. METHODS: Second section."
    assert record.pubmed_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"


def test_parser_missing_doi_and_abstract_is_safe():
    record = parse_pubmed_records(MISSING_FIELDS_XML)[0]
    assert record.doi is None
    assert record.abstract_text is None
    assert record.publication_year is None


def test_parser_skips_unexpected_record_without_losing_valid_batch_item():
    xml = PUBMED_XML.replace(b"<PubmedArticleSet>", b"<PubmedArticleSet><PubmedArticle><MedlineCitation /></PubmedArticle>")
    records = parse_pubmed_records(xml)
    assert [record.pmid for record in records] == ["12345678"]


def test_parser_rejects_malformed_xml():
    with pytest.raises(PubMedParseError, match="invalid XML"):
        parse_pubmed_records(b"<PubmedArticleSet>")


def test_search_uses_esearch_then_one_batch_efetch_and_keeps_secret_out_of_records(caplog):
    caplog.set_level("DEBUG")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, content=b"<eSearchResult><Count>2</Count><IdList><Id>12345678</Id><Id>87654321</Id></IdList></eSearchResult>")
        return httpx.Response(200, content=PUBMED_XML)

    client = make_client(handler, api_key="test-secret-key")
    total, records = client.search("query", 10)

    assert total == 2
    assert len(records) == 1
    assert len(requests) == 2
    assert requests[0].url.path.endswith("esearch.fcgi")
    assert requests[1].url.path.endswith("efetch.fcgi")
    second_form = parse_qs(requests[1].content.decode("utf-8"))
    assert second_form["id"] == ["12345678,87654321"]
    assert "test-secret-key" not in str(requests[1].url)
    assert all("test-secret-key" not in str(record.raw_metadata) for record in records)
    assert "test-secret-key" not in caplog.text


def test_zero_esearch_result_does_not_call_efetch():
    calls = 0

    def handler(_request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"<eSearchResult><Count>0</Count><IdList /></eSearchResult>")

    total, records = make_client(handler).search("query", 5)
    assert total == 0
    assert records == []
    assert calls == 1


def test_timeout_is_retried_only_to_bound_then_mapped():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    client = make_client(handler, max_retries=1)
    with pytest.raises(PubMedUnavailableError, match="timed out"):
        client.search_ids("query", 5)
    assert calls == 2


def test_http_429_is_bounded_and_mapped():
    calls = 0

    def handler(_request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = make_client(handler, max_retries=1)
    with pytest.raises(PubMedRateLimitError):
        client.search_ids("query", 5)
    assert calls == 2


def test_esearch_malformed_xml_is_mapped():
    client = make_client(lambda _request: httpx.Response(200, content=b"<eSearchResult>"))
    with pytest.raises(PubMedParseError):
        client.search_ids("query", 5)


def test_missing_email_fails_at_request_not_client_startup():
    http_client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500)), base_url=EUTILS_BASE_URL)
    client = PubMedClient(tool="weather_ai", email=None, client=http_client, rate_limiter=NoopRateLimiter())
    with pytest.raises(PubMedConfigurationError, match="NCBI_EMAIL"):
        client.search_ids("query", 1)
