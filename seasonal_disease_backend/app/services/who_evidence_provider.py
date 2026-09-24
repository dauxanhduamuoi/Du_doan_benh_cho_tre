from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from html.parser import HTMLParser
from typing import Callable, Mapping
from urllib.parse import urljoin, urlsplit
from uuid import UUID
import json
import re

import httpx

from app.services.medical_evidence_provider import (
    MedicalEvidenceCapability,
    MedicalEvidenceProviderBadResponseError,
    MedicalEvidenceProviderConfigurationError,
    MedicalEvidenceProviderDescriptor,
    MedicalEvidenceProviderRateLimitedError,
    MedicalEvidenceProviderTimeoutError,
    MedicalEvidenceProviderUnavailableError,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQuery,
    ReviewedMedicalEvidenceQueryAttempt,
    ReviewedMedicalEvidenceRetrievalPolicy,
    deduplicate_normalized_evidence,
)


WHO_PROVIDER_ID = "WHO"
# The bounded search route and parameter contract are emitted by WHO's own
# Publications page and its versioned frontend bundle. The detail route/schema
# is documented at https://www.who.int/api/hubs/publications/sfhelp.
WHO_SEARCH_PATH = "/publications/b/search/Publications"
WHO_PUBLICATIONS_API_PATH = "/api/hubs/publications"
WHO_CONTENT_KIND = "OFFICIAL_SUMMARY_EXCERPT"
WHO_CONTENT_ORIGIN = "WHO_PUBLICATIONS_API"
WHO_LICENSE_NAME = "CC BY-NC-SA 3.0 IGO"
WHO_LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/3.0/igo/"
WHO_TRUST_CLASS = "WHO"
WHO_UNTRUSTED_CLASS = "UNTRUSTED"

WHO_DESCRIPTOR = MedicalEvidenceProviderDescriptor(
    provider_id=WHO_PROVIDER_ID,
    display_name="World Health Organization",
    capabilities=frozenset(
        {
            MedicalEvidenceCapability.SEARCH,
            MedicalEvidenceCapability.DIRECT_LOOKUP,
        }
    ),
    description="Ấn phẩm và hướng dẫn y tế chính thức của WHO.",
    settings_display_name="World Health Organization (WHO)",
    max_search_results=25,
    exact_identifier_types=("WHO_GUID",),
)

_TRANSPORT_HOST = "www.who.int"
_CANONICAL_HOSTS = frozenset({"www.who.int", "who.int", "iris.who.int"})
_MAX_SEARCH_RESULTS = 25
_MAX_FETCH_MANY = 25
_MAX_QUERY_CHARS = 500
_REVIEWED_MAX_PAGES = 4
_REVIEWED_MAX_RAW_CANDIDATES = 100
_METADATA_SUMMARY_CHARS = 2000
_ALLOWLISTED_LICENSE_MARKERS = (
    "cc by-nc-sa 3.0 igo",
    "creativecommons.org/licenses/by-nc-sa/3.0/igo",
)
_RESTRICTED_LICENSE_MARKERS = (
    "all rights reserved",
    "permission required",
    "not permitted",
    "restricted",
)


def _diagnostic_error(
    error_type: type[MedicalEvidenceProviderUnavailableError],
    message: str,
    *,
    code: str,
    stage: str,
    retry_after: str | None = None,
) -> MedicalEvidenceProviderUnavailableError:
    """Attach bounded machine diagnostics without exposing response bodies."""

    error = error_type(message)
    error.code = code  # type: ignore[attr-defined]
    error.stage = stage  # type: ignore[attr-defined]
    error.retry_after = retry_after  # type: ignore[attr-defined]
    return error


class _TextExtractor(HTMLParser):
    _SKIP_TAGS = frozenset({"script", "style", "nav", "footer", "noscript", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag.casefold() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _clean_text(value: object, *, max_chars: int | None = None) -> str | None:
    if value is None:
        return None
    parser = _TextExtractor()
    try:
        parser.feed(str(value))
        parser.close()
    except Exception as exc:
        raise MedicalEvidenceProviderBadResponseError(
            "WHO returned malformed publication text"
        ) from exc
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    if not text:
        return None
    return text[:max_chars] if max_chars is not None else text


def _field(record: Mapping[str, object], *names: str) -> object | None:
    by_casefold = {str(key).casefold(): value for key, value in record.items()}
    for name in names:
        value = by_casefold.get(name.casefold())
        if value is not None:
            return value
    return None


def _string_value(value: object) -> str | None:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, Mapping):
        return _clean_text(
            _field(value, "Name", "Title", "Value", "Label", "Code")
        )
    if isinstance(value, list):
        values = [_string_value(item) for item in value]
        joined = ", ".join(item for item in values if item)
        return joined or None
    return _clean_text(value)


def _official_url(value: object, *, required: bool = False) -> str | None:
    raw = _string_value(value)
    if not raw:
        if required:
            raise MedicalEvidenceProviderBadResponseError(
                "WHO publication is missing its canonical URL"
            )
        return None
    candidate = urljoin("https://www.who.int", raw)
    parts = urlsplit(candidate)
    try:
        port = parts.port
    except ValueError as exc:
        raise MedicalEvidenceProviderBadResponseError(
            "WHO publication returned an unsafe canonical URL"
        ) from exc
    if parts.scheme != "https" or parts.hostname not in _CANONICAL_HOSTS:
        raise MedicalEvidenceProviderBadResponseError(
            "WHO publication returned a non-official canonical URL"
        )
    if parts.username or parts.password or port not in (None, 443):
        raise MedicalEvidenceProviderBadResponseError(
            "WHO publication returned an unsafe canonical URL"
        )
    return candidate


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


def _source_kind(record: Mapping[str, object]) -> MedicalEvidenceSourceKind:
    raw = _field(
        record,
        "PublicationType",
        "PublicationTypes",
        "Type",
        "Types",
        "DocumentType",
        "Tag",
        "Format",
    )
    value = (_string_value(raw) or "").casefold()
    if "systematic review" in value or "meta-analysis" in value:
        return MedicalEvidenceSourceKind.SYSTEMATIC_REVIEW
    if "guideline" in value:
        return MedicalEvidenceSourceKind.GUIDELINE
    if "technical report" in value or "meeting report" in value or value == "report":
        return MedicalEvidenceSourceKind.TECHNICAL_REPORT
    if any(
        marker in value
        for marker in ("health guidance", "guidance", "fact sheet", "manual")
    ):
        return MedicalEvidenceSourceKind.HEALTH_GUIDANCE
    return MedicalEvidenceSourceKind.OTHER


def _license_status(record: Mapping[str, object]) -> tuple[str, str | None, str | None]:
    copyright_text = _string_value(
        _field(record, "Copyright", "License", "Licence", "LicenseUrl")
    )
    normalized = (copyright_text or "").casefold()
    if any(marker in normalized for marker in _ALLOWLISTED_LICENSE_MARKERS):
        return "ALLOWED_EXCERPT", WHO_LICENSE_NAME, WHO_LICENSE_URL
    if any(marker in normalized for marker in _RESTRICTED_LICENSE_MARKERS):
        return "RESTRICTED", copyright_text, None
    return "UNKNOWN", copyright_text, None


def _publication_date(record: Mapping[str, object]) -> tuple[str | None, int | None]:
    value = _string_value(
        _field(
            record,
            "PublicationDate",
            "PublicationDateAndTime",
            "Date",
            "Published",
        )
    )
    if not value:
        return None, None
    match = re.match(r"^(\d{4})(?:-(\d{2})-(\d{2}))?", value)
    return value, int(match.group(1)) if match else None


def _doi(record: Mapping[str, object]) -> str | None:
    value = _string_value(_field(record, "DOI", "Doi"))
    if value:
        return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I).strip()
    links = _string_value(_field(record, "Links")) or ""
    match = re.search(r"(?:doi\.org/|doi:\s*)(10\.\d{4,9}/[^\s<]+)", links, re.I)
    return match.group(1).rstrip(".,;)") if match else None


def _bounded_metadata(record: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "Id",
        "SystemSourceKey",
        "SourceKey",
        "WHOReferenceNumber",
        "IRISID",
        "ISBN",
        "PublicationType",
        "PublicationTypes",
        "Type",
        "Types",
        "DocumentType",
        "Tag",
        "Format",
        "Publisher",
        "Language",
        "Languages",
        "LastModified",
        "Copyright",
    }
    result: dict[str, object] = {}
    for key, value in record.items():
        if str(key) not in allowed:
            continue
        try:
            encoded = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            continue
        if len(encoded) <= 2000:
            result[str(key)] = value
    return result


def normalize_who_record(
    record: Mapping[str, object],
    *,
    retrieved_at: datetime,
    retrieval_surface: str,
    max_excerpt_chars: int,
) -> NormalizedMedicalEvidence:
    if not isinstance(record, Mapping):
        raise MedicalEvidenceProviderBadResponseError(
            "WHO publication record must be a JSON object"
        )
    title = _clean_text(_field(record, "Title", "ContentTitle", "TrimmedTitle"))
    if not title:
        raise MedicalEvidenceProviderBadResponseError(
            "WHO publication record is missing a title"
        )
    canonical_url = _official_url(
        _field(record, "NavigationUrl", "ItemDefaultUrl", "CanonicalUrl", "Url")
    )
    api_id = _string_value(_field(record, "Id"))
    source_key = _string_value(_field(record, "SystemSourceKey", "SourceKey"))
    external_id = next(
        (
            value
            for value in (
                api_id,
                source_key,
                _string_value(_field(record, "WHOReferenceNumber")),
                _string_value(_field(record, "IRISID")),
                _string_value(_field(record, "ISBN")),
                canonical_url,
            )
            if value
        ),
        None,
    )
    if not external_id:
        raise MedicalEvidenceProviderBadResponseError(
            "WHO publication record has no stable identity"
        )

    summary = _clean_text(
        _field(record, "Summary", "Overview", "Abstract", "Description"),
        max_chars=_METADATA_SUMMARY_CHARS,
    )
    license_status, license_name, license_url = _license_status(record)
    evidence_text: str | None = None
    is_truncated = False
    if summary and license_status == "ALLOWED_EXCERPT":
        evidence_text = summary[:max_excerpt_chars]
        is_truncated = len(evidence_text) < len(summary)
    publication_date, publication_year = _publication_date(record)
    provider_metadata = _bounded_metadata(record)
    if _is_uuid(api_id):
        provider_metadata["api_id"] = api_id
    elif _is_uuid(source_key):
        provider_metadata["api_id"] = source_key
    provider_metadata.update(
        {
            "license_status": license_status,
            "metadata_summary_present": bool(summary),
        }
    )
    provenance: dict[str, object] = {
        "provider": "World Health Organization",
        "provider_id": WHO_PROVIDER_ID,
        "external_id": external_id,
        "canonical_url": canonical_url,
        "retrieval_surface": retrieval_surface,
        "retrieved_at": retrieved_at.isoformat(),
        "content_policy": "WHO_CC_BY_NC_SA_3_0_IGO_EXCERPT_ONLY",
        "license_status": license_status,
        "license_allowlisted": license_status == "ALLOWED_EXCERPT",
        "metadata_storage_allowed": True,
        "full_text_stored": False,
    }
    return NormalizedMedicalEvidence(
        provider_id=WHO_PROVIDER_ID,
        source_kind=_source_kind(record),
        external_id=external_id,
        title=title,
        canonical_url=canonical_url,
        authors=_string_value(_field(record, "Authors", "Author", "Editors")),
        publication_date=publication_date,
        publisher_or_journal=_string_value(
            _field(record, "Publisher", "PublishingOffice", "Journal")
        ),
        language=_string_value(_field(record, "Language", "Languages")),
        doi=_doi(record),
        publication_year=publication_year,
        abstract_text=summary,
        content_kind=WHO_CONTENT_KIND if evidence_text else None,
        content_origin=WHO_CONTENT_ORIGIN if evidence_text else None,
        evidence_text=evidence_text,
        retrieved_at=retrieved_at,
        is_truncated=is_truncated,
        license_name=license_name,
        license_url=license_url,
        provenance=provenance,
        provider_metadata=provider_metadata,
    )


def who_trust_class(source: NormalizedMedicalEvidence) -> str:
    if (
        source.provider_id == WHO_PROVIDER_ID
        and source.content_kind == WHO_CONTENT_KIND
        and source.content_origin == WHO_CONTENT_ORIGIN
        and bool((source.evidence_text or "").strip())
        and source.license_url == WHO_LICENSE_URL
        and source.provenance.get("license_allowlisted") is True
        and source.provenance.get("full_text_stored") is False
    ):
        return WHO_TRUST_CLASS
    return WHO_UNTRUSTED_CLASS


class WhoMedicalEvidenceProvider:
    descriptor = WHO_DESCRIPTOR

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        base_url: str = "https://www.who.int",
        timeout_seconds: float = 15.0,
        max_response_bytes: int = 2_000_000,
        max_excerpt_chars: int = 6000,
        clock: Callable[[], datetime] = datetime.utcnow,
    ) -> None:
        parts = urlsplit(base_url.strip())
        try:
            port = parts.port
        except ValueError as exc:
            raise MedicalEvidenceProviderConfigurationError(
                "WHO provider base URL must be https://www.who.int"
            ) from exc
        if (
            parts.scheme != "https"
            or parts.hostname != _TRANSPORT_HOST
            or parts.username
            or parts.password
            or port not in (None, 443)
            or parts.path.rstrip("/")
        ):
            raise MedicalEvidenceProviderConfigurationError(
                "WHO provider base URL must be https://www.who.int"
            )
        if timeout_seconds <= 0 or max_response_bytes < 1024 or max_excerpt_chars < 1:
            raise MedicalEvidenceProviderConfigurationError(
                "WHO provider bounds must be positive"
            )
        self.base_url = "https://www.who.int"
        self.timeout_seconds = min(float(timeout_seconds), 30.0)
        self.max_response_bytes = min(int(max_response_bytes), 5_000_000)
        self.max_excerpt_chars = min(int(max_excerpt_chars), 10_000)
        self.clock = clock
        self.client = client or httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "weather-ai-medical-knowledge/1.0"},
        )

    def _request_json(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        not_found_none: bool = False,
        operation: str = "LOOKUP",
    ) -> object | None:
        code_prefix = f"WHO_{operation}"
        url = urljoin(self.base_url, path)
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != _TRANSPORT_HOST:
            raise MedicalEvidenceProviderConfigurationError(
                "WHO provider refused a non-official transport URL"
            )
        try:
            with self.client.stream(
                "GET",
                url,
                params=params,
                timeout=self.timeout_seconds,
                follow_redirects=False,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status_code == 404 and not_found_none:
                    return None
                if response.status_code == 429:
                    raise _diagnostic_error(
                        MedicalEvidenceProviderRateLimitedError,
                        "WHO publication service rate limit exceeded",
                        code=f"{code_prefix}_RATE_LIMITED",
                        stage="http",
                        retry_after=response.headers.get("retry-after"),
                    )
                if response.status_code in {408, 504}:
                    raise _diagnostic_error(
                        MedicalEvidenceProviderTimeoutError,
                        "WHO publication service timed out",
                        code=f"{code_prefix}_TIMEOUT",
                        stage="http",
                    )
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location", "")
                    try:
                        redirect = urlsplit(urljoin(url, location))
                        official = redirect.scheme == "https" and redirect.hostname == _TRANSPORT_HOST
                    except ValueError:
                        official = False
                    reason = "redirect is not an official WHO URL" if not official else "redirects are disabled"
                    raise _diagnostic_error(
                        MedicalEvidenceProviderBadResponseError,
                        f"WHO publication service {reason}",
                        code=f"{code_prefix}_REDIRECT",
                        stage="redirect",
                    )
                if response.status_code >= 500:
                    raise _diagnostic_error(
                        MedicalEvidenceProviderUnavailableError,
                        "WHO publication service is unavailable",
                        code=f"{code_prefix}_HTTP_STATUS",
                        stage="http",
                    )
                if response.status_code >= 400:
                    raise _diagnostic_error(
                        MedicalEvidenceProviderBadResponseError,
                        "WHO publication service rejected the request",
                        code=f"{code_prefix}_HTTP_STATUS",
                        stage="http",
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json" and not content_type.endswith("+json"):
                    raise _diagnostic_error(
                        MedicalEvidenceProviderBadResponseError,
                        "WHO publication service returned an unsupported content type",
                        code=f"{code_prefix}_BAD_CONTENT_TYPE",
                        stage="content_type",
                    )
                declared = response.headers.get("content-length")
                if declared and int(declared) > self.max_response_bytes:
                    raise _diagnostic_error(
                        MedicalEvidenceProviderBadResponseError,
                        "WHO publication response exceeded the configured size limit",
                        code=f"{code_prefix}_RESPONSE_TOO_LARGE",
                        stage="response_size",
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.max_response_bytes:
                        raise _diagnostic_error(
                            MedicalEvidenceProviderBadResponseError,
                            "WHO publication response exceeded the configured size limit",
                            code=f"{code_prefix}_RESPONSE_TOO_LARGE",
                            stage="response_size",
                        )
        except MedicalEvidenceProviderUnavailableError:
            raise
        except httpx.TimeoutException as exc:
            raise _diagnostic_error(
                MedicalEvidenceProviderTimeoutError,
                "WHO publication service timed out",
                code=f"{code_prefix}_TIMEOUT",
                stage="transport",
            ) from exc
        except httpx.HTTPError as exc:
            raise _diagnostic_error(
                MedicalEvidenceProviderUnavailableError,
                "WHO publication service is unavailable",
                code=f"{code_prefix}_TRANSPORT",
                stage="transport",
            ) from exc
        except (ValueError, UnicodeError) as exc:
            raise _diagnostic_error(
                MedicalEvidenceProviderBadResponseError,
                "WHO publication service returned malformed headers or encoding",
                code=f"{code_prefix}_MALFORMED_ENCODING",
                stage="decode",
            ) from exc
        if not body:
            raise _diagnostic_error(
                MedicalEvidenceProviderBadResponseError,
                "WHO publication service returned an empty response",
                code=f"{code_prefix}_EMPTY_RESPONSE",
                stage="decode",
            )
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise _diagnostic_error(
                MedicalEvidenceProviderBadResponseError,
                "WHO publication service returned malformed JSON",
                code=f"{code_prefix}_MALFORMED_JSON",
                stage="decode",
            ) from exc

    def search_page(
        self, query: str, page_size: int, page_number: int
    ) -> MedicalEvidenceSearchResult:
        normalized_query = re.sub(r"\s+", " ", query or "").strip()
        if (
            not normalized_query
            or len(normalized_query) > _MAX_QUERY_CHARS
            or any(ord(char) < 32 for char in normalized_query)
        ):
            raise MedicalEvidenceProviderBadResponseError(
                "WHO search requires a bounded topic-level query"
            )
        bounded_results = min(_MAX_SEARCH_RESULTS, max(1, int(page_size)))
        bounded_page = int(page_number)
        if bounded_page < 0:
            raise MedicalEvidenceProviderBadResponseError(
                "WHO search page number must be non-negative"
            )
        payload = self._request_json(
            WHO_SEARCH_PATH,
            params={
                "term": normalized_query,
                "sort": 0,
                "pageSize": bounded_results,
                "pageNumber": bounded_page,
            },
            operation="SEARCH",
        )
        if not isinstance(payload, Mapping):
            raise _diagnostic_error(
                MedicalEvidenceProviderBadResponseError,
                "WHO search response must be a JSON object",
                code="WHO_SEARCH_RESPONSE_SHAPE_CHANGED",
                stage="shape",
            )
        results = _field(payload, "Results")
        if not isinstance(results, list):
            raise _diagnostic_error(
                MedicalEvidenceProviderBadResponseError,
                "WHO search response is missing its Results list",
                code="WHO_SEARCH_RESPONSE_SHAPE_CHANGED",
                stage="shape",
            )
        normalized: list[NormalizedMedicalEvidence] = []
        invalid = 0
        retrieved_at = self.clock()
        for item in results[:bounded_results]:
            try:
                normalized.append(
                    normalize_who_record(
                        item,
                        retrieved_at=retrieved_at,
                        retrieval_surface="WHO_BIBLIO_SEARCH",
                        max_excerpt_chars=self.max_excerpt_chars,
                    )
                )
            except MedicalEvidenceProviderBadResponseError:
                invalid += 1
        if results and not normalized and invalid:
            raise _diagnostic_error(
                MedicalEvidenceProviderBadResponseError,
                "WHO search returned no valid publication records",
                code="WHO_SEARCH_RESPONSE_SHAPE_CHANGED",
                stage="normalization",
            )
        total_raw = _field(payload, "Total")
        try:
            total = max(0, int(total_raw if total_raw is not None else len(results)))
        except (TypeError, ValueError) as exc:
            raise _diagnostic_error(
                MedicalEvidenceProviderBadResponseError,
                "WHO search returned an invalid result count",
                code="WHO_SEARCH_RESPONSE_SHAPE_CHANGED",
                stage="shape",
            ) from exc
        pages_raw = _field(payload, "PagesCount")
        try:
            pages_count = max(
                0,
                int(
                    pages_raw
                    if pages_raw is not None
                    else ((total + bounded_results - 1) // bounded_results)
                ),
            )
        except (TypeError, ValueError) as exc:
            raise _diagnostic_error(
                MedicalEvidenceProviderBadResponseError,
                "WHO search returned an invalid page count",
                code="WHO_SEARCH_RESPONSE_SHAPE_CHANGED",
                stage="shape",
            ) from exc
        sources = deduplicate_normalized_evidence(tuple(normalized))
        return MedicalEvidenceSearchResult(
            total_count=total,
            sources=sources,
            fetched_count=min(len(results), bounded_results),
            normalized_count=len(sources),
            page_number=bounded_page,
            pages_count=pages_count,
        )

    def search(self, query: str, max_results: int) -> MedicalEvidenceSearchResult:
        return self.search_page(query, max_results, 0)

    def build_reviewed_retrieval_policy(
        self, target_relevant: int
    ) -> ReviewedMedicalEvidenceRetrievalPolicy:
        # The verified route accepts at most 25 records per page. Four bounded
        # page requests cap worst-case transport exposure while allowing a
        # Reviewed search to inspect more candidates than its relevant target.
        batch_size = min(_MAX_SEARCH_RESULTS, max(10, int(target_relevant)))
        return ReviewedMedicalEvidenceRetrievalPolicy(
            batch_size=batch_size,
            max_pages=_REVIEWED_MAX_PAGES,
            max_raw_candidates=min(
                _REVIEWED_MAX_RAW_CANDIDATES,
                batch_size * _REVIEWED_MAX_PAGES,
            ),
        )

    def build_reviewed_query(self, context: ReviewedMedicalEvidenceQuery) -> str:
        # Lazy imports keep the generic provider contract independent from the
        # Auto orchestration module while reusing its canonical vocabulary.
        from types import SimpleNamespace

        from app.services.auto_evidence_relevance import (
            build_disease_aliases,
            reviewed_factor_vocabulary,
        )

        aliases = build_disease_aliases(context.disease_terms[0])
        # Reviewed disease terms already come from the selected catalog topic
        # plus explicit staff edits. Preserve them even when the shared Auto
        # alias guard rejects a specific one-word disease such as "Plague".
        disease_terms = tuple(dict.fromkeys((*context.disease_terms, *aliases.strict)))
        aliases = type(aliases)(
            strict=disease_terms,
            broad=tuple(dict.fromkeys((*disease_terms, *aliases.broad))),
        )
        topic = SimpleNamespace(
            factor_type=context.factor_type,
            factor_key=context.factor_key,
            factor_value=context.factor_value,
            weather_factor=context.weather_factor,
        )
        # WHO's public search surface uses plain terms. Keep Reviewed-specific
        # factor aliases here instead of changing Auto discovery vocabulary.
        terms = [
            *tuple(aliases.strict or aliases.broad)[:3],
            *reviewed_factor_vocabulary(topic)[:4],
            "children",
            "pediatric",
        ]
        cleaned = [re.sub(r"[^\w\s\-/]", " ", term).strip() for term in terms]
        return " ".join(term for term in cleaned if term)[:500]

    def build_reviewed_query_plan(
        self, context: ReviewedMedicalEvidenceQuery
    ) -> tuple[ReviewedMedicalEvidenceQueryAttempt, ...]:
        return (
            ReviewedMedicalEvidenceQueryAttempt(
                level="DIRECT_DISEASE_FACTOR",
                query=self.build_reviewed_query(context),
                relevance="DIRECT_TOPIC",
            ),
        )

    def lookup(self, external_id: str) -> NormalizedMedicalEvidence | None:
        value = (external_id or "").strip()
        if not _is_uuid(value):
            # Some Biblio records expose a stable WHO reference instead of the
            # REST UUID. Resolve it through the same bounded official search.
            matches = self.search(value, min(10, _MAX_SEARCH_RESULTS)).sources
            return next((item for item in matches if item.external_id == value), None)
        payload = self._request_json(
            f"{WHO_PUBLICATIONS_API_PATH}({value})", not_found_none=True
        )
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            raise MedicalEvidenceProviderBadResponseError(
                "WHO publication response must be a JSON object"
            )
        merged = dict(payload)
        merged.setdefault("Id", value)
        return normalize_who_record(
            merged,
            retrieved_at=self.clock(),
            retrieval_surface="WHO_PUBLICATIONS_REST_API",
            max_excerpt_chars=self.max_excerpt_chars,
        )

    def fetch_many(self, external_ids: list[str]) -> tuple[NormalizedMedicalEvidence, ...]:
        if len(external_ids) > _MAX_FETCH_MANY:
            raise MedicalEvidenceProviderBadResponseError(
                "WHO batch lookup exceeds the configured item limit"
            )
        sources = [source for value in external_ids if (source := self.lookup(value)) is not None]
        return deduplicate_normalized_evidence(tuple(sources))

    def lookup_exact(self, identifier: str) -> NormalizedMedicalEvidence | None:
        """REST GUID identity only; Biblio integers/URLs are not REST keys."""
        value = identifier.strip()
        if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
            raise ValueError("INVALID_IDENTIFIER: WHO exact lookup supports a publication GUID only")
        value = str(UUID(value))
        payload = self._request_json(
            f"{WHO_PUBLICATIONS_API_PATH}({value})", not_found_none=True
        )
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            raise MedicalEvidenceProviderBadResponseError("WHO exact response must be an object")
        # Unlike legacy enrichment, never manufacture a missing response Id.
        returned_id = _string_value(_field(payload, "Id"))
        if not _is_uuid(returned_id) or UUID(returned_id) != UUID(value):
            raise MedicalEvidenceProviderBadResponseError("WHO exact lookup identity mismatch")
        source = normalize_who_record(
            {**payload, "Id": value}, retrieved_at=self.clock(),
            retrieval_surface="WHO_PUBLICATIONS_REST_EXACT",
            max_excerpt_chars=self.max_excerpt_chars,
        )
        _official_url(source.canonical_url, required=True)
        return source

    def enrich(
        self, source: NormalizedMedicalEvidence, *, retrieved_at: datetime | None = None
    ) -> NormalizedMedicalEvidence:
        if source.provider_id != WHO_PROVIDER_ID:
            raise ValueError("WHO provider can only enrich normalized WHO evidence")
        api_id = _string_value(source.provider_metadata.get("api_id"))
        if api_id and _is_uuid(api_id):
            detailed = self.lookup(api_id)
            if detailed is None:
                return source
            effective_retrieved_at = retrieved_at or detailed.retrieved_at
            provenance = dict(detailed.provenance)
            if effective_retrieved_at is not None:
                provenance["retrieved_at"] = effective_retrieved_at.isoformat()
            return replace(
                detailed,
                retrieved_at=effective_retrieved_at,
                provenance=provenance,
            )
        return replace(source, retrieved_at=retrieved_at or source.retrieved_at or self.clock())

    def close(self) -> None:
        self.client.close()
