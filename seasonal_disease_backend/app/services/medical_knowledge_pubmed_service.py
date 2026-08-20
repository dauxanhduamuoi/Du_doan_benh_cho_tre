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
from app.medical_knowledge_schemas import MedicalEvidenceSourceCreate
from app.pubmed_schemas import (
    PubMedImportRequest,
    PubMedImportResponse,
    PubMedImportedSource,
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
    ):
        self.db = db
        self.client = client
        self.repository = MedicalKnowledgeRepository(db)
        self.disease_manifest_path = disease_manifest_path

    def _validate_disease_group(self, disease_group_id: str) -> None:
        deployed_ids = load_deployed_disease_ids(str(self.disease_manifest_path.resolve()))
        if disease_group_id not in deployed_ids:
            raise DiseaseGroupNotFoundError("Disease group is not in the deployed Weather AI universe")

    def search(self, request: PubMedSearchRequest) -> PubMedSearchResponse:
        self._validate_disease_group(request.disease_group_id)
        query = build_pubmed_query(
            request.disease_terms,
            request.weather_factor,
            year_from=request.year_from,
            year_to=request.year_to,
        )
        _total_count, records = self.client.search(query, request.max_results)
        results = [
            PubMedRecord(
                pmid=record.pmid,
                title=record.title,
                authors=record.authors,
                journal=record.journal,
                publication_year=record.publication_year,
                doi=record.doi,
                abstract_text=record.abstract_text,
                pubmed_url=record.pubmed_url,
            )
            for record in records
        ]
        return PubMedSearchResponse(
            disease_group_id=request.disease_group_id,
            weather_factor=request.weather_factor,
            query=query,
            count=len(results),
            results=results,
        )

    def import_pmids(self, request: PubMedImportRequest) -> PubMedImportResponse:
        # Network retrieval occurs before the first repository query/write so the
        # database transaction is not held open while waiting for NCBI.
        records = self.client.fetch_records(request.pmids)
        now = datetime.utcnow()
        imported: list[PubMedImportedSource] = []
        created_count = 0
        try:
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
                imported.append(
                    PubMedImportedSource(
                        id=source.id,
                        pmid=record.pmid,
                        created=created,
                        title=source.title,
                        retrieved_at=source.retrieved_at,
                    )
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return PubMedImportResponse(
            count=len(imported),
            created_count=created_count,
            reused_count=len(imported) - created_count,
            sources=imported,
        )
