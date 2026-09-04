from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import csv
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    MEDICAL_KNOWLEDGE_LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    WEATHER_AI_V3_DISEASE_CATALOG,
    WEATHER_AI_V3_MODEL_MANIFEST,
)
from app.medical_knowledge_schemas import (
    MedicalEvidenceContentCreate,
    MedicalEvidenceSourceCreate,
)
from app.medical_knowledge_factors import factor_catalog
from app.pubmed_schemas import (
    PubMedImportRequest,
    PubMedImportResponse,
    PubMedImportedSource,
    MedicalKnowledgeTopicSourceLibraryResponse,
    PubMedLookupRequest,
    PubMedLookupResponse,
    PubMedRecord,
    PubMedSearchRequest,
    PubMedSearchResponse,
)
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.services.pubmed_client import PubMedClient
from app.services.pubmed_query_builder import build_pubmed_query
from app.services.medical_knowledge_draft_generator import (
    get_medical_knowledge_llm_configuration,
)
from app.services.medical_evidence_content_service import MedicalEvidenceContentService
from app.services.medical_knowledge_topic_source_service import (
    MedicalKnowledgeTopicSourceService,
)


WEATHER_FACTOR_LABELS_VI = {
    "temperature": "Nhiệt độ",
    "humidity": "Độ ẩm",
    "precipitation": "Mưa / lượng mưa",
    "wind": "Gió",
    "weather_condition": "Điều kiện thời tiết",
}


class DiseaseGroupNotFoundError(ValueError):
    pass


class DiseaseUniverseConfigurationError(RuntimeError):
    pass


class PubMedArticleNotFoundError(LookupError):
    pass


@lru_cache(maxsize=4)
def load_deployed_disease_ids(manifest_path: str) -> frozenset[str]:
    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiseaseUniverseConfigurationError("Deployed disease manifest is unavailable") from exc
    disease_order = manifest.get("disease_order")
    model_count = manifest.get("model_count")
    if not isinstance(disease_order, list) or not disease_order:
        raise DiseaseUniverseConfigurationError("Deployed disease manifest has no disease_order")
    normalized = frozenset(str(value) for value in disease_order)
    if len(normalized) != len(disease_order) or model_count != len(disease_order):
        raise DiseaseUniverseConfigurationError("Deployed disease manifest is inconsistent")
    return normalized


@lru_cache(maxsize=4)
def load_deployed_disease_options(manifest_path: str, catalog_path: str) -> tuple[tuple[str, str], ...]:
    deployed_ids = load_deployed_disease_ids(manifest_path)
    try:
        with Path(manifest_path).open(encoding="utf-8") as stream:
            disease_order = [str(value) for value in json.load(stream)["disease_order"]]
        with Path(catalog_path).open(encoding="utf-8-sig", newline="") as stream:
            rows = csv.DictReader(stream)
            catalog = {
                str(row["disease_group_id"]): str(row["disease_group_name"]).strip()
                for row in rows
                if row.get("disease_group_id") and row.get("disease_group_name")
            }
    except (OSError, KeyError, json.JSONDecodeError, csv.Error) as exc:
        raise DiseaseUniverseConfigurationError("Disease catalog metadata is unavailable") from exc
    missing = [disease_id for disease_id in disease_order if disease_id not in catalog]
    if missing or frozenset(disease_order) != deployed_ids:
        raise DiseaseUniverseConfigurationError("Disease catalog does not cover the deployed universe")
    return tuple((disease_id, catalog[disease_id]) for disease_id in disease_order)


def get_medical_knowledge_options() -> dict:
    disease_groups = load_deployed_disease_options(
        str(WEATHER_AI_V3_MODEL_MANIFEST.resolve()),
        str(WEATHER_AI_V3_DISEASE_CATALOG.resolve()),
    )
    return {
        "disease_groups": [{"id": disease_id, "name": name} for disease_id, name in disease_groups],
        "weather_factors": [
            {"value": value, "label_vi": label}
            for value, label in WEATHER_FACTOR_LABELS_VI.items()
        ],
        "explanation_factors": factor_catalog(),
        "llm_draft_generation_available": get_medical_knowledge_llm_configuration(
            provider=MEDICAL_KNOWLEDGE_LLM_PROVIDER,
            openai_api_key=OPENAI_API_KEY,
            openai_model=OPENAI_MODEL,
            ollama_base_url=OLLAMA_BASE_URL,
            ollama_model=OLLAMA_MODEL,
            groq_api_key=GROQ_API_KEY,
            groq_model=GROQ_MODEL,
        ).configured,
    }


class MedicalKnowledgePubMedService:
    def __init__(
        self,
        db: Session,
        client: PubMedClient,
        *,
        disease_manifest_path: Path = WEATHER_AI_V3_MODEL_MANIFEST,
        evidence_content_service: MedicalEvidenceContentService | None = None,
    ):
        self.db = db
        self.client = client
        self.repository = MedicalKnowledgeRepository(db)
        self.topic_sources = MedicalKnowledgeTopicSourceService(db)
        self.disease_manifest_path = disease_manifest_path
        self.evidence_content_service = evidence_content_service or MedicalEvidenceContentService(None)

    def _validate_disease_group(self, disease_group_id: str) -> None:
        deployed_ids = load_deployed_disease_ids(str(self.disease_manifest_path.resolve()))
        if disease_group_id not in deployed_ids:
            raise DiseaseGroupNotFoundError("Disease group is not in the deployed Weather AI universe")

    @staticmethod
    def _record_response(
        record,
        *,
        source=None,
        in_topic_library: bool = False,
        content=None,
    ) -> PubMedRecord:
        return PubMedRecord(
            pmid=record.pmid,
            title=record.title,
            authors=record.authors,
            journal=record.journal,
            publication_year=record.publication_year,
            doi=record.doi,
            abstract_text=record.abstract_text,
            pubmed_url=record.pubmed_url,
            pmcid=(
                content.external_identifier
                if content is not None
                and (content.external_identifier or "").startswith("PMC")
                else record.pmcid
            ),
            source_id=source.id if source is not None else None,
            stored_globally=source is not None,
            in_topic_library=in_topic_library,
            content_kind=content.content_kind if content is not None else None,
        )

    def _stored_state(self, request, pmids: list[str]):
        sources = self.repository.get_sources_by_pmids(pmids)
        by_pmid = {source.pmid: source for source in sources}
        content = self.repository.get_preferred_evidence_contents(
            [source.id for source in sources]
        )
        topic = self.repository.get_topic_by_selector(
            request.disease_group_id,
            request.factor_type,
            request.factor_key,
            request.factor_value,
        )
        linked_ids = (
            self.repository.get_topic_source_ids(topic.id) if topic is not None else set()
        )
        return by_pmid, content, linked_ids

    def search(self, request: PubMedSearchRequest) -> PubMedSearchResponse:
        self._validate_disease_group(request.disease_group_id)
        query = (
            request.free_query
            if request.search_mode == "FREE"
            else build_pubmed_query(
                request.disease_terms,
                factor_type=request.factor_type,
                factor_key=request.factor_key,
                factor_value=request.factor_value,
                weather_factor=request.weather_factor,
                year_from=request.year_from,
                year_to=request.year_to,
            )
        )
        assert query is not None
        _total_count, records = self.client.search(query, request.max_results)
        by_pmid, content, linked_ids = self._stored_state(
            request,
            [record.pmid for record in records],
        )
        results = [
            self._record_response(
                record,
                source=by_pmid.get(record.pmid),
                in_topic_library=(
                    by_pmid.get(record.pmid) is not None
                    and by_pmid[record.pmid].id in linked_ids
                ),
                content=(
                    content.get(by_pmid[record.pmid].id)
                    if by_pmid.get(record.pmid) is not None
                    else None
                ),
            )
            for record in records
        ]
        return PubMedSearchResponse(
            disease_group_id=request.disease_group_id,
            factor_type=request.factor_type,
            factor_key=request.factor_key,
            factor_value=request.factor_value,
            weather_factor=request.weather_factor,
            search_mode=request.search_mode,
            query=query,
            count=len(results),
            results=results,
        )

    def lookup_pmid(self, request: PubMedLookupRequest) -> PubMedLookupResponse:
        self._validate_disease_group(request.disease_group_id)
        record = self.client.get_article_by_pmid(request.pmid)
        if record is None:
            raise PubMedArticleNotFoundError("PubMed article was not found")

        source = self.repository.get_source_by_pmid(request.pmid)
        existing_source = None
        if source is not None:
            content = self.repository.get_preferred_evidence_contents([source.id]).get(source.id)
            existing_source = PubMedImportedSource(
                id=source.id,
                pmid=source.pmid,
                created=False,
                title=source.title,
                retrieved_at=source.retrieved_at,
                content_kind=content.content_kind if content else None,
                pmcid=content.external_identifier if content else None,
                source_reused=True,
                topic_link_created=False,
                already_in_topic_library=(
                    (
                        topic := self.repository.get_topic_by_selector(
                            request.disease_group_id,
                            request.factor_type,
                            request.factor_key,
                            request.factor_value,
                        )
                    )
                    is not None
                    and self.repository.get_topic_source(topic.id, source.id) is not None
                ),
            )
        return PubMedLookupResponse(
            pmid=request.pmid,
            result=self._record_response(
                record,
                source=source,
                in_topic_library=(
                    existing_source.already_in_topic_library
                    if existing_source is not None
                    else False
                ),
                content=(content if source is not None else None),
            ),
            existing_source=existing_source,
        )

    def import_pmids(
        self, request: PubMedImportRequest, *, added_by: int | None
    ) -> PubMedImportResponse:
        self._validate_disease_group(request.disease_group_id)
        # PubMed and optional PMC retrieval happen outside a write transaction.
        records = self.client.fetch_records(request.pmids)
        now = datetime.utcnow()
        existing_sources = self.repository.get_sources_by_pmids([record.pmid for record in records])
        existing_content = self.repository.get_preferred_evidence_contents(
            [source.id for source in existing_sources]
        )
        enriched_pmids = {
            source.pmid
            for source in existing_sources
            if (content := existing_content.get(source.id)) is not None
            and content.content_kind in {"PMC_FULL_TEXT", "PMC_FULL_TEXT_EXCERPT"}
        }
        # End the read transaction before bounded ELink/EFetch calls.
        self.db.rollback()
        resolved_by_pmid = {
            record.pmid: self.evidence_content_service.resolve(
                pmid=record.pmid,
                abstract_text=record.abstract_text,
                retrieved_at=now,
            )
            for record in records
            if record.pmid not in enriched_pmids
        }

        imported: list[PubMedImportedSource] = []
        created_count = 0
        try:
            topic = self.topic_sources.get_or_create_topic(
                disease_group_id=request.disease_group_id,
                factor_type=request.factor_type,
                factor_key=request.factor_key,
                factor_value=request.factor_value,
                weather_factor=request.weather_factor,
                created_by=added_by,
            )
            for record in records:
                source = self.repository.get_source_by_pmid(record.pmid)
                created = source is None
                if source is None:
                    source = self.repository.create_source(
                        MedicalEvidenceSourceCreate(
                            source_type="PUBMED",
                            pmid=record.pmid,
                            doi=record.doi,
                            title=record.title,
                            authors=record.authors,
                            journal=record.journal,
                            publication_year=record.publication_year,
                            abstract_text=record.abstract_text,
                            url=record.pubmed_url,
                            retrieved_at=now,
                            raw_metadata_json=record.raw_metadata,
                        )
                    )
                    created_count += 1
                content = None
                resolved = resolved_by_pmid.get(record.pmid)
                if resolved is not None:
                    content = self.repository.get_evidence_content_by_hash(
                        source.id, resolved.content_sha256
                    )
                    if content is None:
                        content = self.repository.create_evidence_content(
                            MedicalEvidenceContentCreate(
                                source_id=source.id,
                                content_kind=resolved.content_kind,
                                content_origin=resolved.content_origin,
                                external_identifier=resolved.external_identifier,
                                evidence_text=resolved.evidence_text,
                                retrieved_at=resolved.retrieved_at,
                                is_truncated=resolved.is_truncated,
                                license_name=resolved.license_name,
                                license_url=resolved.license_url,
                                provenance_json=resolved.provenance,
                                content_sha256=resolved.content_sha256,
                            )
                        )
                if content is None:
                    content = self.repository.get_preferred_evidence_contents([source.id]).get(
                        source.id
                    )
                topic_link_created = self.topic_sources.ensure_source(
                    topic_id=topic.id,
                    source_id=source.id,
                    added_by=added_by,
                )
                imported.append(
                    PubMedImportedSource(
                        id=source.id,
                        pmid=record.pmid,
                        created=created,
                        title=source.title,
                        retrieved_at=source.retrieved_at,
                        content_kind=content.content_kind if content else None,
                        pmcid=content.external_identifier if content else None,
                        source_reused=not created,
                        topic_link_created=topic_link_created,
                        already_in_topic_library=not topic_link_created,
                    )
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return PubMedImportResponse(
            topic_id=topic.id,
            count=len(imported),
            created_count=created_count,
            reused_count=len(imported) - created_count,
            sources=imported,
        )

    def get_topic_source_library(
        self,
        *,
        disease_group_id: str,
        factor_type: str | None = None,
        factor_key: str | None = None,
        factor_value: str | None = None,
        weather_factor: str | None = None,
    ) -> MedicalKnowledgeTopicSourceLibraryResponse:
        self._validate_disease_group(disease_group_id)
        from app.medical_knowledge_factors import normalize_factor

        factor = normalize_factor(
            factor_type=factor_type,
            factor_key=factor_key,
            factor_value=factor_value,
            weather_factor=weather_factor,
        )
        return self.topic_sources.read(
            disease_group_id=disease_group_id,
            factor_type=factor.factor_type,
            factor_key=factor.factor_key,
            factor_value=factor.factor_value,
            weather_factor=factor.weather_factor,
        )
