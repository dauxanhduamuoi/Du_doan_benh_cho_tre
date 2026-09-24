from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Protocol
import re

from app.medical_knowledge_models import MedicalKnowledgeTopic
from app.services.auto_evidence_relevance import (
    DiseaseAliasSet,
    RelevanceSignals,
    build_disease_aliases,
    factor_vocabulary,
    normalize_phrase,
    record_relevance_signals,
)
from app.services.medical_evidence_content_service import MedicalEvidenceContentService
from app.services.medical_evidence_provider import (
    MedicalEvidenceProvider,
    MedicalEvidenceProviderError,
    NormalizedMedicalEvidence,
    normalized_evidence_identity_keys,
)
from app.services.pubmed_client import PubMedClient
from app.services.pubmed_evidence_provider import (
    PubMedMedicalEvidenceProvider,
    normalize_pubmed_record,
)
from app.services.pubmed_query_builder import build_auto_pubmed_query


class AutoEvidenceSearchError(RuntimeError):
    pass


class AutoEvidenceEnrichmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutoEvidenceCandidate:
    record: NormalizedMedicalEvidence
    evidence: NormalizedMedicalEvidence
    trust_class: str
    score: int
    signals: RelevanceSignals = field(default_factory=lambda: RelevanceSignals(0, 0, 0))

    def __post_init__(self) -> None:
        """Normalize legacy test/caller inputs at the discovery boundary."""

        record = self.record
        if not isinstance(record, NormalizedMedicalEvidence):
            record = normalize_pubmed_record(record)
        evidence = self.evidence
        if isinstance(evidence, NormalizedMedicalEvidence):
            enriched = replace(
                record,
                pmcid=evidence.pmcid,
                content_kind=evidence.content_kind,
                content_origin=evidence.content_origin,
                evidence_text=evidence.evidence_text,
                retrieved_at=evidence.retrieved_at,
                is_truncated=evidence.is_truncated,
                license_name=evidence.license_name,
                license_url=evidence.license_url,
                provenance=dict(evidence.provenance),
            )
        else:
            external_identifier = getattr(evidence, "external_identifier", None)
            enriched = replace(
                record,
                pmcid=(
                    external_identifier
                    if (external_identifier or "").startswith("PMC")
                    else record.pmcid
                ),
                content_kind=evidence.content_kind,
                content_origin=evidence.content_origin,
                evidence_text=evidence.evidence_text,
                retrieved_at=evidence.retrieved_at,
                is_truncated=evidence.is_truncated,
                license_name=evidence.license_name,
                license_url=evidence.license_url,
                provenance=dict(evidence.provenance),
            )
        object.__setattr__(self, "record", enriched)
        object.__setattr__(self, "evidence", enriched)


@dataclass(frozen=True)
class AutoDiscoveryAudit:
    provider: str
    trust_class: str
    decision: str
    reason_code: str
    pmid: str
    title: str
    stage: str | None = None


@dataclass(frozen=True)
class AutoDiscoveryQuery:
    stage: str
    query: str
    returned_results: int


@dataclass(frozen=True)
class AutoDiscoveryDiagnostics:
    queries_run: int = 0
    raw_results: int = 0
    deduplicated: int = 0
    disease_relevant: int = 0
    factor_relevant: int = 0
    pediatric_relevant: int = 0
    usable_evidence: int = 0
    selected_for_generation: int = 0
    insufficient_reason: str | None = None
    query_details: tuple[AutoDiscoveryQuery, ...] = ()


@dataclass(frozen=True)
class AutoDiscoveryResult:
    selected: tuple[AutoEvidenceCandidate, ...]
    audit: tuple[AutoDiscoveryAudit, ...]
    queries: tuple[str, ...]
    diagnostics: AutoDiscoveryDiagnostics = field(default_factory=AutoDiscoveryDiagnostics)


class AutoEvidenceDiscoveryProvider(Protocol):
    provider_name: str

    def discover(
        self,
        *,
        topic: MedicalKnowledgeTopic,
        disease_name: str,
        max_sources: int,
        disease_aliases: DiseaseAliasSet | None = None,
    ) -> AutoDiscoveryResult:
        ...


def _insufficient_reason(*, raw: int, disease: int, factor: int, pediatric: int, usable: int) -> str | None:
    if raw == 0:
        return "NO_SEARCH_RESULTS"
    if disease == 0:
        return "NO_DISEASE_RELEVANT_SOURCE"
    if factor == 0:
        return "NO_FACTOR_RELEVANT_SOURCE"
    if pediatric == 0:
        return "NO_PEDIATRIC_RELEVANT_SOURCE"
    if usable == 0:
        return "NO_USABLE_EVIDENCE"
    return None


def _title_signature(title: str) -> frozenset[str]:
    return frozenset(
        token for token in normalize_phrase(title).split()
        if len(token) > 3 and token not in {"study", "among", "with", "from"}
    )


def _near_duplicate(left: str, right: str) -> bool:
    a, b = _title_signature(left), _title_signature(right)
    return bool(a and b) and len(a & b) / len(a | b) >= 0.85


class PubMedAutoEvidenceProvider:
    """Bounded PubMed/PMC discovery with deterministic relevance gates."""

    provider_name = "NCBI_PUBMED_PMC"

    def __init__(
        self,
        client: PubMedClient | MedicalEvidenceProvider,
        evidence_service: MedicalEvidenceContentService | None = None,
        *,
        searches_per_topic: int = 3,
        results_per_search: int = 15,
        min_pediatric_sources_before_stop: int = 3,
        max_evidence_resolutions: int = 20,
        candidate_budget: int | None = None,
    ):
        self.provider = (
            client
            if isinstance(client, MedicalEvidenceProvider)
            else PubMedMedicalEvidenceProvider(
                client, evidence_service or MedicalEvidenceContentService(None)
            )
        )
        self.searches_per_topic = min(3, max(1, searches_per_topic))
        self.results_per_search = min(25, max(1, results_per_search))
        self.min_pediatric_sources_before_stop = min(10, max(1, min_pediatric_sources_before_stop))
        self.max_evidence_resolutions = min(30, max(1, max_evidence_resolutions))
        self.candidate_budget = max(1, candidate_budget) if candidate_budget is not None else None

    def _query_stages(self, topic: MedicalKnowledgeTopic, aliases: DiseaseAliasSet) -> tuple[tuple[str, str], ...]:
        strict_aliases = aliases.strict or aliases.broad
        stages = (
            ("STRICT", build_auto_pubmed_query(strict_aliases, factor_vocabulary(topic, expanded=False))),
            ("EXPANDED_FACTOR", build_auto_pubmed_query(strict_aliases, factor_vocabulary(topic, expanded=True))),
            ("BROADER_DISEASE", build_auto_pubmed_query(aliases.broad or strict_aliases, factor_vocabulary(topic, expanded=True))),
        )
        unique: list[tuple[str, str]] = []
        seen: set[str] = set()
        for stage in stages:
            if stage[1] not in seen:
                unique.append(stage)
                seen.add(stage[1])
        return tuple(unique[: self.searches_per_topic])

    def discover(
        self,
        *,
        topic: MedicalKnowledgeTopic,
        disease_name: str,
        max_sources: int,
        disease_aliases: DiseaseAliasSet | None = None,
    ) -> AutoDiscoveryResult:
        aliases = disease_aliases or build_disease_aliases(disease_name)
        if not aliases.strict and not aliases.broad:
            return AutoDiscoveryResult(
                selected=(), audit=(), queries=(),
                diagnostics=AutoDiscoveryDiagnostics(insufficient_reason="NO_DISEASE_RELEVANT_SOURCE"),
            )

        records: dict[str, tuple[NormalizedMedicalEvidence, str, RelevanceSignals]] = {}
        audits: list[AutoDiscoveryAudit] = []
        queries: list[AutoDiscoveryQuery] = []
        raw_results = 0
        resolutions = 0
        usable: list[AutoEvidenceCandidate] = []

        for stage, query in self._query_stages(topic, aliases):
            remaining = (
                self.results_per_search
                if self.candidate_budget is None
                else min(self.results_per_search, self.candidate_budget - raw_results)
            )
            if remaining <= 0:
                break
            try:
                found = self.provider.search(query, remaining).sources
            except MedicalEvidenceProviderError as exc:
                raise AutoEvidenceSearchError("PubMed search failed") from exc
            raw_results += len(found)
            queries.append(AutoDiscoveryQuery(stage, query, len(found)))

            for record in found:
                record_key = record.external_id
                if record_key in records:
                    audits.append(AutoDiscoveryAudit(
                        self.provider_name, "PUBMED", "SKIPPED", "DUPLICATE_PMID",
                        record.external_id, record.title, stage,
                    ))
                    continue
                raw_mesh = (record.raw_metadata or {}).get("mesh_terms", [])
                mesh_terms = (
                    [str(value) for value in raw_mesh]
                    if isinstance(raw_mesh, list)
                    else []
                )
                signals = record_relevance_signals(
                    title=record.title or "",
                    abstract=record.abstract_text or "",
                    mesh_terms=mesh_terms,
                    topic=topic,
                    aliases=aliases,
                )
                records[record_key] = (record, stage, signals)
                if signals.disease == 0:
                    audits.append(AutoDiscoveryAudit(
                        self.provider_name, "PUBMED", "SKIPPED", "DISEASE_METADATA_MISMATCH",
                        record.external_id, record.title, stage,
                    ))
                    continue
                if signals.factor == 0:
                    audits.append(AutoDiscoveryAudit(
                        self.provider_name, "PUBMED", "SKIPPED", "FACTOR_METADATA_MISMATCH",
                        record.external_id, record.title, stage,
                    ))
                    continue
                if resolutions >= self.max_evidence_resolutions:
                    audits.append(AutoDiscoveryAudit(
                        self.provider_name, "PUBMED", "SKIPPED", "EVIDENCE_RESOLUTION_CAP",
                        record.external_id, record.title, stage,
                    ))
                    continue
                resolutions += 1
                try:
                    evidence = self.provider.enrich(record)
                except Exception as exc:
                    raise AutoEvidenceEnrichmentError("PMC evidence enrichment failed") from exc
                if not (evidence.evidence_text or "").strip():
                    audits.append(AutoDiscoveryAudit(
                        self.provider_name, "PUBMED", "SKIPPED", "NO_USABLE_EVIDENCE_TEXT",
                        record.external_id, record.title, stage,
                    ))
                    continue
                trust_class = "PMC" if evidence.content_origin == "NCBI_PMC" else "PUBMED"
                kind_bonus = 2 if evidence.content_kind.startswith("PMC_FULL_TEXT") else 0
                recency_bonus = 1 if (record.publication_year or 0) >= 2020 else 0
                score = signals.disease * 100 + signals.factor * 40 + signals.pediatric * 20 + kind_bonus + recency_bonus
                usable.append(
                    AutoEvidenceCandidate(evidence, evidence, trust_class, score, signals)
                )

            if sum(item.signals.pediatric > 0 for item in usable) >= self.min_pediatric_sources_before_stop:
                break

        disease_count = sum(signals.disease > 0 for _, _, signals in records.values())
        factor_count = sum(signals.disease > 0 and signals.factor > 0 for _, _, signals in records.values())
        pediatric_count = sum(
            signals.disease > 0 and signals.factor > 0 and signals.pediatric > 0
            for _, _, signals in records.values()
        )
        ranked = sorted(
            usable,
            key=lambda item: (
                -item.signals.disease, -item.signals.factor, -item.signals.pediatric,
                -item.score, item.record.external_id,
            ),
        )
        selected: list[AutoEvidenceCandidate] = []
        if any(item.signals.pediatric > 0 for item in ranked):
            for candidate in ranked:
                if len(selected) >= min(10, max(1, max_sources)):
                    break
                if any(_near_duplicate(candidate.record.title, existing.record.title) for existing in selected):
                    audits.append(AutoDiscoveryAudit(
                        self.provider_name, candidate.trust_class, "SKIPPED", "NEAR_DUPLICATE_SOURCE",
                        candidate.record.external_id, candidate.record.title,
                        records[candidate.record.external_id][1],
                    ))
                    continue
                selected.append(candidate)

        selected_ids = {item.record.external_id for item in selected}
        final_audited = {audit.pmid for audit in audits if audit.reason_code == "NEAR_DUPLICATE_SOURCE"}
        for candidate in ranked:
            if candidate.record.external_id in final_audited:
                continue
            chosen = candidate.record.external_id in selected_ids
            audits.append(AutoDiscoveryAudit(
                self.provider_name, candidate.trust_class, "SELECTED" if chosen else "SKIPPED",
                "SELECTED_FOR_GENERATION" if chosen else "SOURCE_CAPACITY_LIMIT",
                candidate.record.external_id, candidate.record.title,
                records[candidate.record.external_id][1],
            ))

        reason = _insufficient_reason(
            raw=raw_results, disease=disease_count, factor=factor_count,
            pediatric=pediatric_count, usable=len(usable),
        )
        diagnostics = AutoDiscoveryDiagnostics(
            queries_run=len(queries), raw_results=raw_results, deduplicated=len(records),
            disease_relevant=disease_count, factor_relevant=factor_count,
            pediatric_relevant=pediatric_count, usable_evidence=len(usable),
            selected_for_generation=len(selected), insufficient_reason=reason if not selected else None,
            query_details=tuple(queries),
        )
        return AutoDiscoveryResult(
            selected=tuple(selected), audit=tuple(audits),
            queries=tuple(item.query for item in queries), diagnostics=diagnostics,
        )


def build_who_topic_query(
    topic: MedicalKnowledgeTopic, aliases: DiseaseAliasSet
) -> str:
    """Build plain WHO topic terms; never emits PubMed operators or patient data."""

    disease_terms = tuple(aliases.strict or aliases.broad)[:3]
    factor_terms = tuple(factor_vocabulary(topic, expanded=True))[:3]
    terms = [*disease_terms, *factor_terms, "children", "pediatric"]
    cleaned = [re.sub(r"[^\w\s\-/]", " ", term).strip() for term in terms]
    return " ".join(term for term in cleaned if term)[:500]


class WhoAutoEvidenceProvider:
    provider_name = "WHO"

    def __init__(self, provider: MedicalEvidenceProvider, *, candidate_budget: int = 15):
        self.provider = provider
        self.candidate_budget = min(25, max(1, candidate_budget))

    def discover(
        self,
        *,
        topic: MedicalKnowledgeTopic,
        disease_name: str,
        max_sources: int,
        disease_aliases: DiseaseAliasSet | None = None,
    ) -> AutoDiscoveryResult:
        from app.services.who_evidence_provider import who_trust_class

        aliases = disease_aliases or build_disease_aliases(disease_name)
        query = build_who_topic_query(topic, aliases)
        if not query:
            return AutoDiscoveryResult((), (), (), AutoDiscoveryDiagnostics(
                insufficient_reason="NO_DISEASE_RELEVANT_SOURCE"
            ))
        try:
            records = self.provider.search(query, self.candidate_budget).sources
        except MedicalEvidenceProviderError as exc:
            raise AutoEvidenceSearchError("WHO search failed") from exc
        audits: list[AutoDiscoveryAudit] = []
        usable: list[AutoEvidenceCandidate] = []
        disease_count = factor_count = pediatric_count = 0
        for record in records:
            signals = record_relevance_signals(
                title=record.title,
                abstract=record.abstract_text or "",
                mesh_terms=[],
                topic=topic,
                aliases=aliases,
            )
            disease_count += signals.disease > 0
            factor_count += signals.disease > 0 and signals.factor > 0
            pediatric_count += (
                signals.disease > 0 and signals.factor > 0 and signals.pediatric > 0
            )
            if signals.disease == 0 or signals.factor == 0:
                audits.append(AutoDiscoveryAudit(
                    "WHO", "WHO", "SKIPPED",
                    "DISEASE_METADATA_MISMATCH" if signals.disease == 0 else "FACTOR_METADATA_MISMATCH",
                    record.external_id, record.title, "WHO_TOPIC",
                ))
                continue
            try:
                evidence = self.provider.enrich(record)
            except MedicalEvidenceProviderError as exc:
                raise AutoEvidenceEnrichmentError("WHO evidence enrichment failed") from exc
            if who_trust_class(evidence) != "WHO":
                audits.append(AutoDiscoveryAudit(
                    "WHO", "WHO", "SKIPPED", "WHO_METADATA_ONLY_NOT_TRUSTED",
                    record.external_id, record.title, "WHO_TOPIC",
                ))
                continue
            score = signals.disease * 100 + signals.factor * 40 + signals.pediatric * 20
            usable.append(AutoEvidenceCandidate(evidence, evidence, "WHO", score, signals))
        ranked = sorted(
            usable,
            key=lambda item: (
                -item.signals.disease, -item.signals.factor, -item.signals.pediatric,
                -item.score, item.record.external_id,
            ),
        )
        selected = tuple(ranked[: min(10, max(1, max_sources))]) if any(
            item.signals.pediatric > 0 for item in ranked
        ) else ()
        selected_ids = {item.record.external_id for item in selected}
        for candidate in ranked:
            chosen = candidate.record.external_id in selected_ids
            audits.append(AutoDiscoveryAudit(
                "WHO", "WHO", "SELECTED" if chosen else "SKIPPED",
                "SELECTED_FOR_GENERATION" if chosen else "SOURCE_CAPACITY_LIMIT",
                candidate.record.external_id, candidate.record.title, "WHO_TOPIC",
            ))
        reason = _insufficient_reason(
            raw=len(records), disease=disease_count, factor=factor_count,
            pediatric=pediatric_count, usable=len(usable),
        )
        diagnostics = AutoDiscoveryDiagnostics(
            queries_run=1, raw_results=len(records), deduplicated=len(records),
            disease_relevant=disease_count, factor_relevant=factor_count,
            pediatric_relevant=pediatric_count, usable_evidence=len(usable),
            selected_for_generation=len(selected), insufficient_reason=reason if not selected else None,
            query_details=(AutoDiscoveryQuery("WHO_TOPIC", query, len(records)),),
        )
        return AutoDiscoveryResult(
            selected, tuple(audits), (query,), diagnostics
        )


class MultiProviderAutoEvidenceProvider:
    """Failure-isolated, deterministic merge across one immutable provider snapshot."""

    provider_name = "MULTI_PROVIDER"

    def __init__(self, providers: tuple[AutoEvidenceDiscoveryProvider, ...]):
        self.providers = providers

    def discover(
        self,
        *,
        topic: MedicalKnowledgeTopic,
        disease_name: str,
        max_sources: int,
        disease_aliases: DiseaseAliasSet | None = None,
    ) -> AutoDiscoveryResult:
        if not self.providers:
            raise AutoEvidenceSearchError("No AUTO medical evidence provider is enabled")
        aliases = disease_aliases or build_disease_aliases(disease_name)
        results: list[AutoDiscoveryResult] = []
        failures: list[AutoDiscoveryAudit] = []
        for provider in self.providers:
            try:
                results.append(provider.discover(
                    topic=topic,
                    disease_name=disease_name,
                    max_sources=max_sources,
                    disease_aliases=aliases,
                ))
            except (AutoEvidenceSearchError, AutoEvidenceEnrichmentError):
                failures.append(AutoDiscoveryAudit(
                    provider.provider_name,
                    "WHO" if provider.provider_name == "WHO" else "PUBMED",
                    "SKIPPED", "PROVIDER_UNAVAILABLE", provider.provider_name,
                    "Provider unavailable", "PROVIDER",
                ))
        if not results:
            raise AutoEvidenceSearchError("All enabled medical evidence providers failed")

        candidates = sorted(
            (item for result in results for item in result.selected),
            key=lambda item: (
                -item.signals.disease, -item.signals.factor, -item.signals.pediatric,
                -item.score, item.record.provider_id, item.record.external_id,
            ),
        )
        selected: list[AutoEvidenceCandidate] = []
        identities: set[str] = set()
        merge_audits: list[AutoDiscoveryAudit] = []
        for candidate in candidates:
            keys = normalized_evidence_identity_keys(candidate.record)
            duplicate = bool(identities.intersection(keys)) or any(
                _near_duplicate(candidate.record.title, existing.record.title)
                for existing in selected
            )
            if duplicate:
                merge_audits.append(AutoDiscoveryAudit(
                    candidate.record.provider_id, candidate.trust_class, "SKIPPED",
                    "CROSS_PROVIDER_DUPLICATE", candidate.record.external_id,
                    candidate.record.title, "MERGE",
                ))
                identities.update(keys)
                continue
            if len(selected) >= min(10, max(1, max_sources)):
                break
            selected.append(candidate)
            identities.update(keys)

        diagnostics = AutoDiscoveryDiagnostics(
            queries_run=sum(result.diagnostics.queries_run for result in results),
            raw_results=sum(result.diagnostics.raw_results for result in results),
            deduplicated=sum(result.diagnostics.deduplicated for result in results),
            disease_relevant=sum(result.diagnostics.disease_relevant for result in results),
            factor_relevant=sum(result.diagnostics.factor_relevant for result in results),
            pediatric_relevant=sum(result.diagnostics.pediatric_relevant for result in results),
            usable_evidence=sum(result.diagnostics.usable_evidence for result in results),
            selected_for_generation=len(selected),
            insufficient_reason=None if selected else next(
                (result.diagnostics.insufficient_reason for result in results if result.diagnostics.insufficient_reason),
                "NO_USABLE_EVIDENCE",
            ),
            query_details=tuple(
                detail for result in results for detail in result.diagnostics.query_details
            ),
        )
        return AutoDiscoveryResult(
            tuple(selected),
            tuple(audit for result in results for audit in result.audit) + tuple(failures) + tuple(merge_audits),
            tuple(query for result in results for query in result.queries),
            diagnostics,
        )


def create_auto_evidence_discovery_provider(
    provider: MedicalEvidenceProvider,
    *,
    searches_per_topic: int,
    results_per_search: int,
    candidate_budget: int,
) -> AutoEvidenceDiscoveryProvider:
    """Single adapter boundary; the worker remains provider-neutral."""

    provider_id = provider.descriptor.provider_id
    if provider_id == "PUBMED":
        return PubMedAutoEvidenceProvider(
            provider,
            searches_per_topic=searches_per_topic,
            results_per_search=results_per_search,
            candidate_budget=candidate_budget,
        )
    if provider_id == "WHO":
        return WhoAutoEvidenceProvider(provider, candidate_budget=candidate_budget)
    raise ValueError(f"No AUTO discovery adapter is registered for {provider_id}")
