from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy.orm import Session

from app.medical_evidence_reviewed_schemas import (
    ReviewedProviderExactLookupRequest,
    ReviewedProviderExactLookupResponse,
    ReviewedProviderImportRequest,
    ReviewedProviderImportedSource,
    ReviewedProviderImportResponse,
    ReviewedProviderSearchRequest,
    ReviewedProviderSearchResponse,
    ReviewedProviderSearchGroup,
    ReviewedProviderQueryAttempt,
    ReviewedProviderSource,
    ReviewedProviderSourceReference,
    ReviewedProviderWarning,
)
from app.medical_knowledge_schemas import MedicalEvidenceContentCreate, MedicalEvidenceSourceCreate
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.services.medical_evidence_provider import (
    MedicalEvidenceProviderError,
    MedicalEvidenceProviderRegistry,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQuery,
    ReviewedMedicalEvidenceQueryAttempt,
    ReviewedMedicalEvidenceRetrievalPolicy,
    deduplicate_normalized_evidence,
    normalized_evidence_identity_keys,
)
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingsService,
)
from app.services.medical_knowledge_pubmed_service import load_deployed_disease_ids
from app.services.medical_knowledge_topic_source_service import MedicalKnowledgeTopicSourceService
from app.services.who_evidence_provider import who_trust_class
from app.config import WEATHER_AI_V3_MODEL_MANIFEST
from app.services.reviewed_evidence_relevance import (
    ReviewedEvidenceRelevance,
    ReviewedRelevanceClass,
)


MAX_REVIEWED_QUERY_ATTEMPTS = 3
MAX_REVIEWED_PAGE_REQUESTS = 4
MAX_REVIEWED_RAW_CANDIDATES = 100
MAX_REVIEWED_PAGE_SIZE = 25


class ReviewedProviderSelectionError(ValueError):
    pass


class ReviewedProvidersUnavailableError(RuntimeError):
    pass


class ReviewedSourceNotFoundError(LookupError):
    pass


class MedicalEvidenceReviewedService:
    def __init__(self, db: Session, registry: MedicalEvidenceProviderRegistry):
        self.db = db
        self.registry = registry
        self.settings = MedicalEvidenceProviderSettingsService(db, registry)
        self.repository = MedicalKnowledgeRepository(db)
        self.topic_sources = MedicalKnowledgeTopicSourceService(db)

    def _validate_disease(self, disease_group_id: str) -> None:
        if disease_group_id not in load_deployed_disease_ids(
            str(WEATHER_AI_V3_MODEL_MANIFEST.resolve())
        ):
            raise ReviewedProviderSelectionError("Unknown disease group")

    def lookup_exact(self, request: ReviewedProviderExactLookupRequest) -> ReviewedProviderExactLookupResponse:
        from app.services.medical_evidence_exact_lookup import lookup_exact

        self._validate_disease(request.disease_group_id)
        self._enabled_selection([request.provider_id])
        try:
            source = lookup_exact(self.registry, request.provider_id, request.identifier)
        except ValueError as exc:
            raise ReviewedProviderSelectionError(str(exc)) from exc
        if source is None:
            raise ReviewedSourceNotFoundError("NOT_FOUND: exact publication was not found")
        stored = self._find_stored_source(source)
        topic = self.repository.get_topic_by_selector(
            request.disease_group_id, request.factor_type, request.factor_key, request.factor_value,
        )
        in_library = bool(stored and topic and self.repository.get_topic_source(topic.id, stored.id))
        return ReviewedProviderExactLookupResponse(
            requested_identifier=request.identifier.strip(),
            result=self._response(source, stored=stored, in_library=in_library,
                                  relevance="EXACT_LOOKUP", query_level="EXACT_IDENTIFIER"),
        )

    def _enabled_selection(self, selected: list[str]) -> tuple[str, ...]:
        enabled = self.settings.enabled_provider_ids("REVIEWED")
        invalid = [provider_id for provider_id in selected if provider_id not in enabled]
        if invalid:
            raise ReviewedProviderSelectionError(
                f"Provider is not enabled for REVIEWED: {', '.join(invalid)}"
            )
        return tuple(provider_id for provider_id in enabled if provider_id in selected)

    @staticmethod
    def _retrieval_policy(provider, target_relevant: int) -> ReviewedMedicalEvidenceRetrievalPolicy:
        factory = getattr(provider, "build_reviewed_retrieval_policy", None)
        if not callable(factory) or not callable(getattr(provider, "search_page", None)):
            return ReviewedMedicalEvidenceRetrievalPolicy(
                batch_size=target_relevant,
                max_pages=1,
                max_raw_candidates=target_relevant,
            )
        policy = factory(target_relevant)
        max_raw_candidates = max(
            1, min(int(policy.max_raw_candidates), MAX_REVIEWED_RAW_CANDIDATES)
        )
        return ReviewedMedicalEvidenceRetrievalPolicy(
            batch_size=max(
                1,
                min(int(policy.batch_size), MAX_REVIEWED_PAGE_SIZE, max_raw_candidates),
            ),
            max_pages=max(1, min(int(policy.max_pages), MAX_REVIEWED_PAGE_REQUESTS)),
            max_raw_candidates=max_raw_candidates,
        )

    @staticmethod
    def _usable(source: NormalizedMedicalEvidence) -> bool:
        if source.provider_id == "WHO":
            return who_trust_class(source) == "WHO"
        return source.provider_id == "PUBMED" and bool(
            source.content_sha256 and (source.evidence_text or "").strip()
        )

    @staticmethod
    def _response(
        source: NormalizedMedicalEvidence, *, stored=None, in_library: bool = False,
        relevance: str, query_level: str,
    ) -> ReviewedProviderSource:
        usable = MedicalEvidenceReviewedService._usable(source)
        return ReviewedProviderSource(
            provider_id=source.provider_id,
            external_id=source.external_id,
            source_kind=source.source_kind.value,
            title=source.title,
            authors=source.authors,
            publisher_or_journal=source.publisher_or_journal,
            publication_date=source.publication_date,
            publication_year=source.publication_year,
            doi=source.doi,
            url=source.canonical_url,
            abstract_text=source.abstract_text,
            license_name=source.license_name,
            license_url=source.license_url,
            usability="USABLE_FOR_DRAFT" if usable else "METADATA_ONLY",
            usable_for_draft=usable,
            source_id=stored.id if stored is not None else None,
            in_topic_library=in_library,
            relevance=relevance,
            query_level=query_level,
        )

    @staticmethod
    def _query_context(request: ReviewedProviderSearchRequest) -> ReviewedMedicalEvidenceQuery:
        return ReviewedMedicalEvidenceQuery(
            disease_terms=tuple(request.disease_terms),
            factor_type=request.factor_type,
            factor_key=request.factor_key,
            factor_value=request.factor_value,
            weather_factor=request.weather_factor,
            year_from=request.year_from,
            year_to=request.year_to,
        )

    @staticmethod
    def _query_plan(provider, context: ReviewedMedicalEvidenceQuery) -> tuple[ReviewedMedicalEvidenceQueryAttempt, ...]:
        planner = getattr(provider, "build_reviewed_query_plan", None)
        if callable(planner):
            plan = tuple(planner(context))[:MAX_REVIEWED_QUERY_ATTEMPTS]
        else:
            plan = (ReviewedMedicalEvidenceQueryAttempt(
                level="DIRECT_TOPIC",
                query=provider.build_reviewed_query(context),
                relevance="DIRECT_TOPIC",
            ),)
        if not plan or any(not attempt.query.strip() for attempt in plan):
            raise ValueError("Reviewed provider returned an invalid query plan")
        return plan

    @staticmethod
    def _canonical_url(value: str) -> str:
        parts = urlsplit(value.strip())
        try:
            port = parts.port
        except ValueError as exc:
            raise ValueError("Source canonical URL is invalid") from exc
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or port not in (None, 443)
        ):
            raise ValueError("Source canonical URL is invalid")
        host = parts.hostname.casefold()
        path = parts.path.rstrip("/") or "/"
        return urlunsplit(("https", host, path, parts.query, ""))

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            UUID(value)
        except (ValueError, AttributeError):
            return False
        return True

    def _validate_reference(self, reference: ReviewedProviderSourceReference) -> None:
        if reference.provider_id != "WHO":
            return
        if not reference.canonical_url or not reference.title:
            raise ValueError("WHO reference requires its official URL and title")
        canonical = self._canonical_url(reference.canonical_url)
        if urlsplit(canonical).hostname not in {"www.who.int", "who.int", "iris.who.int"}:
            raise ValueError("WHO reference requires an official WHO URL")

    def _is_who_biblio_reference(
        self, reference: ReviewedProviderSourceReference
    ) -> bool:
        if reference.provider_id != "WHO" or not reference.external_id.isdigit():
            return False
        canonical = self._canonical_url(reference.canonical_url or "")
        parts = urlsplit(canonical)
        return bool(
            parts.hostname in {"www.who.int", "who.int"}
            and not parts.query
            and parts.path.rstrip("/") == f"/publications/b/{reference.external_id}"
        )

    def _metadata_only_who_reference(
        self, reference: ReviewedProviderSourceReference
    ) -> NormalizedMedicalEvidence:
        if not self._is_who_biblio_reference(reference):
            raise ValueError("WHO source identity could not be validated")
        try:
            source_kind = MedicalEvidenceSourceKind(reference.source_kind or "OTHER")
        except ValueError as exc:
            raise ValueError("WHO source kind is invalid") from exc
        # The Biblio numeric ID and its same-origin canonical route form one
        # verifiable identity. Client medical content, trust and license fields
        # are deliberately absent from the import DTO and are never persisted.
        return NormalizedMedicalEvidence(
            provider_id="WHO",
            source_kind=source_kind,
            external_id=reference.external_id,
            title=reference.title or "WHO publication",
            canonical_url=self._canonical_url(reference.canonical_url or ""),
            authors=reference.authors,
            publication_date=reference.publication_date,
            publisher_or_journal=reference.publisher_or_journal,
            # A Biblio reference DTO is sufficient for reference-only display,
            # but client-supplied DOI must not participate in trusted dedup.
            doi=None,
            publication_year=reference.publication_year,
            retrieved_at=datetime.utcnow(),
            provenance={
                "provider": "World Health Organization",
                "provider_id": "WHO",
                "external_id": reference.external_id,
                "canonical_url": self._canonical_url(reference.canonical_url or ""),
                "retrieval_surface": "WHO_BIBLIO_SEARCH_REFERENCE",
                "metadata_storage_allowed": True,
                "license_allowlisted": False,
                "full_text_stored": False,
            },
            provider_metadata={
                "metadata_only_import": True,
                "identity_validation": "WHO_BIBLIO_NUMERIC_CANONICAL_PATH",
            },
        )

    def _resolve_reference(
        self, reference: ReviewedProviderSourceReference
    ) -> NormalizedMedicalEvidence:
        self._validate_reference(reference)
        if self._is_who_biblio_reference(reference):
            return self._metadata_only_who_reference(reference)
        if reference.provider_id == "WHO" and not self._is_uuid(reference.external_id):
            raise ValueError("WHO source identity could not be validated")

        provider = self.registry.get(reference.provider_id)
        lookup = getattr(provider, "lookup_exact", provider.lookup)
        record = lookup(reference.external_id)
        if record is None:
            raise ReviewedSourceNotFoundError("Provider source was not found")
        record = provider.enrich(record)
        if (
            record.provider_id != reference.provider_id
            or record.external_id.casefold() != reference.external_id.casefold()
            or (record.provider_id == "PUBMED" and record.pmid != reference.external_id)
        ):
            raise ValueError("Provider returned a different source identity")
        if reference.canonical_url:
            if not record.canonical_url or self._canonical_url(
                record.canonical_url
            ) != self._canonical_url(reference.canonical_url):
                raise ValueError("Provider returned a different canonical URL")
        if record.provider_id == "WHO":
            canonical = self._canonical_url(record.canonical_url or "")
            if urlsplit(canonical).hostname not in {"www.who.int", "who.int", "iris.who.int"}:
                raise ValueError("WHO provider returned a non-official URL")
        return record

    def _find_stored_source(self, record: NormalizedMedicalEvidence):
        source = self.repository.get_source_by_provider_external_id(
            record.provider_id, record.external_id
        )
        if source is None and record.pmid:
            source = self.repository.get_source_by_pmid(record.pmid)
        if source is None and record.doi:
            source = self.repository.get_source_by_doi(record.doi)
        if source is None and record.canonical_url:
            source = self.repository.get_source_by_canonical_url(record.canonical_url)
        return source

    @staticmethod
    def _stored_content_usable_for_draft(source, content) -> bool:
        if content is None or not (content.evidence_text or "").strip():
            return False
        provider_id = (source.provider_id or source.source_type).upper()
        if provider_id != "WHO":
            return provider_id == "PUBMED"
        provenance = content.provenance_json if isinstance(content.provenance_json, dict) else {}
        return bool(
            content.content_kind == "OFFICIAL_SUMMARY_EXCERPT"
            and content.content_origin == "WHO_PUBLICATIONS_API"
            and content.license_url == "https://creativecommons.org/licenses/by-nc-sa/3.0/igo/"
            and provenance.get("license_allowlisted") is True
            and provenance.get("full_text_stored") is False
        )

    @staticmethod
    def _failed_import(
        reference: ReviewedProviderSourceReference, *, outcome: str, message: str
    ) -> ReviewedProviderImportedSource:
        return ReviewedProviderImportedSource(
            outcome=outcome,
            source_id=None,
            provider_id=reference.provider_id,
            external_id=reference.external_id,
            title=reference.title,
            created=False,
            topic_link_created=False,
            content_kind=None,
            license_name=None,
            license_url=None,
            usable_for_draft=False,
            imported_at=None,
            message=message,
        )

    def search(self, request: ReviewedProviderSearchRequest) -> ReviewedProviderSearchResponse:
        self._validate_disease(request.disease_group_id)
        providers = self._enabled_selection(request.provider_ids)
        grouped_records: list[
            tuple[ReviewedProviderSearchGroup, list[tuple[NormalizedMedicalEvidence, str, str]]]
        ] = []
        queries: dict[str, str] = {}
        warnings: list[ReviewedProviderWarning] = []
        context = self._query_context(request)
        relevance_classifier = ReviewedEvidenceRelevance(context)
        for provider_id in providers:
            provider = self.registry.get(provider_id)
            descriptor = provider.descriptor
            effective_limit = min(request.max_results, descriptor.max_search_results)
            plan = self._query_plan(provider, context)
            query = plan[0].query
            queries[provider_id] = query
            collected: list[tuple[NormalizedMedicalEvidence, str, str]] = []
            seen: set[str] = set()
            attempts: list[ReviewedProviderQueryAttempt] = []
            raw_result_count = normalized_count = 0
            disease_match_count = factor_match_count = 0
            rejected_count = 0
            pages_fetched = 0
            budget_exhausted = False
            provider_exhausted = False
            total_available: int | None = None
            provider_warning: ReviewedProviderWarning | None = None
            provider_invoked = False
            for attempt in plan:
                prioritizes_direct = attempt.relevance == "DIRECT_TOPIC"
                collected_direct = sum(
                    relevance == "DIRECT_TOPIC" for _, relevance, _ in collected
                )
                if collected_direct >= effective_limit or (
                    not prioritizes_direct and len(collected) >= effective_limit
                ):
                    break
                policy = self._retrieval_policy(provider, effective_limit)
                progressive = policy.max_pages > 1
                page_search = getattr(provider, "search_page", None)
                attempt_fetched = attempt_normalized = 0
                attempt_disease_matches = attempt_factor_matches = 0
                attempt_relevant = attempt_pages = 0
                attempt_direct = attempt_related = attempt_rejected = 0
                attempt_total = 0
                attempt_exhausted = False
                attempt_budget_exhausted = False
                attempt_stop_reason = "QUERY_ATTEMPT_COMPLETE"
                attempt_warning: ReviewedProviderWarning | None = None
                examined: set[str] = set()
                for page_number in range(policy.max_pages):
                    collected_direct = sum(
                        relevance == "DIRECT_TOPIC" for _, relevance, _ in collected
                    )
                    if collected_direct >= effective_limit or (
                        not prioritizes_direct and len(collected) >= effective_limit
                    ):
                        attempt_stop_reason = "TARGET_REACHED"
                        break
                    if attempt_fetched + policy.batch_size > policy.max_raw_candidates:
                        attempt_budget_exhausted = progressive
                        attempt_stop_reason = "CANDIDATE_BUDGET_REACHED"
                        break
                    try:
                        provider_invoked = True
                        if progressive:
                            if not callable(page_search):
                                raise RuntimeError(
                                    f"Provider {provider_id} configured pagination without search_page"
                                )
                            search_result = page_search(
                                attempt.query, policy.batch_size, page_number
                            )
                        else:
                            search_result = provider.search(attempt.query, policy.batch_size)
                    except MedicalEvidenceProviderError as exc:
                        attempt_warning = ReviewedProviderWarning(
                            provider_id=provider_id,
                            code=str(getattr(exc, "code", "PROVIDER_UNAVAILABLE")),
                            message=f"{descriptor.display_name} is temporarily unavailable.",
                        )
                        provider_warning = attempt_warning
                        warnings.append(attempt_warning)
                        attempt_stop_reason = "PROVIDER_ERROR"
                        break
                    attempt_pages += 1
                    pages_fetched += 1
                    attempt_total = max(attempt_total, search_result.total_count)
                    if total_available is None:
                        total_available = search_result.total_count
                    fetched = search_result.fetched_count
                    if fetched is None:
                        fetched = len(search_result.sources)
                    attempt_fetched += fetched
                    raw_result_count += fetched

                    unique_sources: list[NormalizedMedicalEvidence] = []
                    for source in search_result.sources:
                        keys = normalized_evidence_identity_keys(source)
                        if examined.intersection(keys):
                            examined.update(keys)
                            continue
                        examined.update(keys)
                        unique_sources.append(source)
                    attempt_normalized += len(unique_sources)
                    normalized_count += len(unique_sources)
                    evaluated = [
                        (
                            source,
                            relevance_classifier.classify(
                                source, query_level=attempt.level
                            ),
                        )
                        for source in unique_sources
                    ]
                    page_disease_matches = sum(
                        assessment.disease_match for _, assessment in evaluated
                    )
                    page_factor_matches = sum(
                        assessment.factor_match for _, assessment in evaluated
                    )
                    page_direct = sum(
                        assessment.classification is ReviewedRelevanceClass.DIRECT
                        for _, assessment in evaluated
                    )
                    page_related = sum(
                        assessment.classification is ReviewedRelevanceClass.RELATED
                        for _, assessment in evaluated
                    )
                    page_rejected = sum(
                        assessment.classification is ReviewedRelevanceClass.REJECT
                        for _, assessment in evaluated
                    )
                    attempt_disease_matches += page_disease_matches
                    attempt_factor_matches += page_factor_matches
                    attempt_direct += page_direct
                    attempt_related += page_related
                    attempt_rejected += page_rejected
                    disease_match_count += page_disease_matches
                    factor_match_count += page_factor_matches
                    rejected_count += page_rejected
                    relevant = [
                        (source, assessment)
                        for source, assessment in evaluated
                        if assessment.accepted
                    ]
                    relevant.sort(
                        key=lambda item: (
                            item[1].classification is not ReviewedRelevanceClass.DIRECT
                        )
                    )
                    attempt_relevant += len(relevant)
                    for source, assessment in relevant:
                        keys = normalized_evidence_identity_keys(source)
                        if seen.intersection(keys):
                            seen.update(keys)
                            continue
                        seen.update(keys)
                        collected.append(
                            (source, assessment.classification.value, attempt.level)
                        )
                        if not prioritizes_direct and len(collected) >= effective_limit:
                            break
                    collected_direct = sum(
                        relevance == "DIRECT_TOPIC" for _, relevance, _ in collected
                    )
                    if collected_direct >= effective_limit or (
                        not prioritizes_direct and len(collected) >= effective_limit
                    ):
                        attempt_stop_reason = "TARGET_REACHED"
                        break
                    attempt_exhausted = (
                        fetched == 0
                        or attempt_fetched >= search_result.total_count
                        or (
                            search_result.pages_count is not None
                            and page_number + 1 >= search_result.pages_count
                        )
                        or fetched < policy.batch_size
                    )
                    if attempt_exhausted:
                        attempt_stop_reason = "PROVIDER_EXHAUSTED"
                        break
                else:
                    if progressive and not attempt_exhausted:
                        attempt_budget_exhausted = True
                        attempt_stop_reason = "CANDIDATE_BUDGET_REACHED"

                budget_exhausted = budget_exhausted or attempt_budget_exhausted
                provider_exhausted = provider_exhausted or (progressive and attempt_exhausted)
                attempts.append(ReviewedProviderQueryAttempt(
                    level=attempt.level,
                    relevance=attempt.relevance,
                    query=attempt.query,
                    provider_match_count=attempt_total,
                    fetched_count=attempt_fetched,
                    normalized_count=attempt_normalized,
                    disease_match_count=attempt_disease_matches,
                    factor_match_count=attempt_factor_matches,
                    relevant_count=attempt_relevant,
                    direct_count=attempt_direct,
                    related_count=attempt_related,
                    rejected_count=attempt_rejected,
                    pages_fetched=attempt_pages,
                    budget_exhausted=attempt_budget_exhausted,
                    provider_exhausted=attempt_exhausted,
                    stop_reason=attempt_stop_reason,
                    status="PROVIDER_ERROR" if attempt_warning is not None else "SUCCESS",
                    warning=attempt_warning,
                ))
                if attempt_warning is not None:
                    break
            if not provider_invoked:
                raise RuntimeError(
                    f"Selected provider {provider_id} was not invoked by Reviewed orchestration"
                )
            collected.sort(key=lambda item: 0 if item[1] == "DIRECT_TOPIC" else 1)
            collected = collected[:effective_limit]
            direct_count = sum(relevance == "DIRECT_TOPIC" for _, relevance, _ in collected)
            related_count = len(collected) - direct_count
            status = (
                "SUCCESS" if collected
                else "PROVIDER_ERROR" if provider_warning is not None
                else "NO_RESULTS"
            )
            stop_reason = (
                "TARGET_REACHED" if len(collected) >= effective_limit
                else "PROVIDER_ERROR" if provider_warning is not None
                else "CANDIDATE_BUDGET_REACHED" if budget_exhausted
                else "PROVIDER_EXHAUSTED" if provider_exhausted
                else "QUERY_PLAN_EXHAUSTED"
            )
            grouped_records.append((ReviewedProviderSearchGroup(
                provider_id=provider_id,
                display_name=descriptor.display_name,
                requested_count=request.max_results,
                requested_relevant_count=effective_limit,
                effective_limit=effective_limit,
                returned_count=len(collected),
                total_available=total_available,
                provider_total_available=total_available,
                provider_invoked=provider_invoked,
                provider_status="PROVIDER_ERROR" if provider_warning is not None else "SUCCESS",
                raw_result_count=raw_result_count,
                raw_candidates_examined=raw_result_count,
                normalized_count=normalized_count,
                normalized_candidates=normalized_count,
                disease_match_count=disease_match_count,
                factor_match_count=factor_match_count,
                relevant_count=len(collected),
                rejected_count=rejected_count,
                pages_fetched=pages_fetched,
                budget_exhausted=budget_exhausted,
                provider_exhausted=provider_exhausted,
                stop_reason=stop_reason,
                direct_count=direct_count,
                related_count=related_count,
                contextual_count=related_count,
                status=status,
                query=query,
                warning=provider_warning,
                query_attempts=attempts,
                results=[],
            ), collected))
        topic = self.repository.get_topic_by_selector(
            request.disease_group_id, request.factor_type, request.factor_key, request.factor_value
        )
        linked = self.repository.get_topic_source_ids(topic.id) if topic is not None else set()
        groups: list[ReviewedProviderSearchGroup] = []
        response: list[ReviewedProviderSource] = []
        all_records: list[NormalizedMedicalEvidence] = []
        for group, records in grouped_records:
            items: list[ReviewedProviderSource] = []
            for record, relevance, query_level in records:
                stored = self.repository.get_source_by_provider_external_id(
                    record.provider_id, record.external_id
                )
                item = self._response(
                    record, stored=stored, in_library=bool(stored and stored.id in linked),
                    relevance=relevance, query_level=query_level,
                )
                items.append(item)
                response.append(item)
                all_records.append(record)
            groups.append(group.model_copy(update={"results": items}))
        return ReviewedProviderSearchResponse(
            requested_count=request.max_results,
            provider_count=len(providers),
            max_candidates=sum(group.effective_limit for group in groups),
            count=len(response),
            unique_count=len(deduplicate_normalized_evidence(tuple(all_records))),
            providers=groups,
            results=response,
            queries=queries,
            warnings=warnings,
        )

    def import_sources(
        self, request: ReviewedProviderImportRequest, *, added_by: int
    ) -> ReviewedProviderImportResponse:
        self._validate_disease(request.disease_group_id)
        selected = list(dict.fromkeys(item.provider_id for item in request.sources))
        self._enabled_selection(selected)
        now = datetime.utcnow()
        imported: list[ReviewedProviderImportedSource] = []
        topic = self.repository.get_topic_by_selector(
            request.disease_group_id,
            request.factor_type,
            request.factor_key,
            request.factor_value,
        )

        def ensure_topic():
            nonlocal topic
            if topic is None:
                topic = self.topic_sources.get_or_create_topic(
                    disease_group_id=request.disease_group_id,
                    factor_type=request.factor_type,
                    factor_key=request.factor_key,
                    factor_value=request.factor_value,
                    weather_factor=request.weather_factor,
                    created_by=added_by,
                )
            return topic

        try:
            for reference in request.sources:
                try:
                    self._validate_reference(reference)
                except (ValueError, ReviewedSourceNotFoundError):
                    imported.append(self._failed_import(
                        reference,
                        outcome="REJECTED_INVALID",
                        message="Nguồn không có định danh hoặc URL chính thức hợp lệ.",
                    ))
                    continue

                source = self.repository.get_source_by_provider_external_id(
                    reference.provider_id, reference.external_id
                )
                if source is not None and reference.provider_id == "WHO":
                    if not source.url or self._canonical_url(source.url) != self._canonical_url(
                        reference.canonical_url or ""
                    ):
                        imported.append(self._failed_import(
                            reference,
                            outcome="REJECTED_INVALID",
                            message="Định danh WHO không khớp URL chính thức đã lưu.",
                        ))
                        continue

                record: NormalizedMedicalEvidence | None = None
                if source is None:
                    try:
                        record = self._resolve_reference(reference)
                    except MedicalEvidenceProviderError:
                        imported.append(self._failed_import(
                            reference,
                            outcome="PROVIDER_ERROR",
                            message=f"{reference.provider_id} tạm thời không khả dụng.",
                        ))
                        continue
                    except (ValueError, ReviewedSourceNotFoundError):
                        imported.append(self._failed_import(
                            reference,
                            outcome="REJECTED_INVALID",
                            message="Nguồn không thể được nhà cung cấp xác minh.",
                        ))
                        continue
                    source = self._find_stored_source(record)

                created = source is None
                if source is None:
                    assert record is not None
                    source = self.repository.create_source(MedicalEvidenceSourceCreate(
                        source_type=record.provider_id if record.provider_id in {"PUBMED", "WHO"} else "OTHER",
                        provider_id=record.provider_id,
                        external_id=record.external_id,
                        source_kind=record.source_kind.value,
                        pmid=record.pmid,
                        doi=record.doi,
                        title=record.title,
                        authors=record.authors,
                        journal=record.publisher_or_journal,
                        publication_year=record.publication_year,
                        abstract_text=record.abstract_text,
                        url=record.canonical_url,
                        retrieved_at=record.retrieved_at or now,
                        raw_metadata_json=dict(record.provider_metadata),
                    ))
                content = self.repository.get_preferred_evidence_contents([source.id]).get(source.id)
                if record is not None and self._usable(record) and record.content_sha256:
                    content = self.repository.get_evidence_content_by_hash(
                        source.id, record.content_sha256
                    ) or self.repository.create_evidence_content(MedicalEvidenceContentCreate(
                        source_id=source.id,
                        content_kind=record.content_kind,
                        content_origin=record.content_origin,
                        external_identifier=record.pmcid or record.external_id,
                        evidence_text=record.evidence_text,
                        retrieved_at=record.retrieved_at or now,
                        is_truncated=record.is_truncated,
                        license_name=record.license_name,
                        license_url=record.license_url,
                        provenance_json=dict(record.provenance),
                        content_sha256=record.content_sha256,
                    ))
                linked = self.topic_sources.ensure_source(
                    topic_id=ensure_topic().id, source_id=source.id, added_by=added_by
                )
                usable_for_draft = self._stored_content_usable_for_draft(source, content)
                outcome = (
                    "ALREADY_EXISTS"
                    if not linked
                    else "ADDED"
                    if usable_for_draft
                    else "ADDED_REFERENCE_ONLY"
                )
                imported.append(ReviewedProviderImportedSource(
                    outcome=outcome,
                    source_id=source.id,
                    provider_id=reference.provider_id,
                    external_id=reference.external_id,
                    title=source.title,
                    created=created,
                    topic_link_created=linked,
                    content_kind=content.content_kind if content else None,
                    license_name=content.license_name if content else None,
                    license_url=content.license_url if content else None,
                    usable_for_draft=usable_for_draft,
                    imported_at=now,
                    message=None,
                ))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        added_count = sum(item.topic_link_created for item in imported)
        already_exists_count = sum(item.outcome == "ALREADY_EXISTS" for item in imported)
        failed_count = sum(
            item.outcome in {"REJECTED_INVALID", "PROVIDER_ERROR"} for item in imported
        )
        return ReviewedProviderImportResponse(
            topic_id=topic.id if topic is not None else None,
            count=len(imported) - failed_count,
            requested_count=len(request.sources),
            added_count=added_count,
            reference_only_count=sum(
                item.outcome == "ADDED_REFERENCE_ONLY" for item in imported
            ),
            already_exists_count=already_exists_count,
            failed_count=failed_count,
            sources=imported,
        )
