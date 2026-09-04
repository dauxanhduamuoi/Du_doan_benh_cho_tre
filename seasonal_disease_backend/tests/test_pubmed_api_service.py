from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.medical_knowledge_models import MedicalEvidenceSource
from app.models import User
from app.pubmed_schemas import (
    MedicalKnowledgeTopicSourceLibraryResponse,
    PubMedImportRequest,
    PubMedImportResponse,
    PubMedImportedSource,
    PubMedLookupRequest,
    PubMedLookupResponse,
    PubMedRecord,
    PubMedSearchRequest,
    PubMedSearchResponse,
)
from app.routers.medical_knowledge_pubmed import get_pubmed_service, options_router, router
from app.security import create_access_token
from app.services.medical_knowledge_pubmed_service import (
    DiseaseGroupNotFoundError,
    MedicalKnowledgePubMedService,
    PubMedArticleNotFoundError,
    load_deployed_disease_ids,
)
from app.services.pubmed_client import (
    PubMedArticleRecord,
    PubMedRateLimitError,
    PubMedUnavailableError,
)


def article(pmid: str, title: str = "Weather evidence") -> PubMedArticleRecord:
    return PubMedArticleRecord(
        pmid=pmid,
        title=title,
        authors="An Nguyen",
        journal="Medical Journal",
        publication_year=2024,
        doi=f"10.1000/{pmid}",
        abstract_text="Evidence abstract",
        pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        raw_metadata={"provider": "NCBI PubMed", "pmid": pmid, "languages": ["eng"]},
    )


def import_request(*pmids: str) -> PubMedImportRequest:
    return PubMedImportRequest(
        disease_group_id="1", weather_factor="humidity", pmids=list(pmids)
    )


def lookup_request(pmid: str) -> PubMedLookupRequest:
    return PubMedLookupRequest(
        pmid=pmid, disease_group_id="1", weather_factor="humidity"
    )


class FakePubMedClient:
    def __init__(self, records=None):
        self.records = records or []
        self.search_calls = []
        self.fetch_calls = []

    def search(self, query: str, max_results: int):
        self.search_calls.append((query, max_results))
        return len(self.records), self.records[:max_results]

    def fetch_records(self, pmids: list[str]):
        self.fetch_calls.append(pmids)
        by_pmid = {record.pmid: record for record in self.records}
        return [by_pmid[pmid] for pmid in pmids if pmid in by_pmid]

    def get_article_by_pmid(self, pmid: str):
        records = self.fetch_records([pmid])
        return records[0] if records else None


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def manifest(tmp_path):
    path = tmp_path / "model_manifest.json"
    path.write_text(json.dumps({"model_count": 2, "disease_order": ["1", "4"]}), encoding="utf-8")
    load_deployed_disease_ids.cache_clear()
    return path


def test_invalid_disease_group_is_rejected_before_provider_call(db, manifest):
    client = FakePubMedClient([article("12345678")])
    service = MedicalKnowledgePubMedService(db, client, disease_manifest_path=manifest)
    request = PubMedSearchRequest(disease_group_id="999", weather_factor="humidity", disease_terms=["asthma"])
    with pytest.raises(DiseaseGroupNotFoundError):
        service.search(request)
    assert client.search_calls == []


def test_search_zero_result_returns_structured_empty_response(db, manifest):
    client = FakePubMedClient()
    service = MedicalKnowledgePubMedService(db, client, disease_manifest_path=manifest)
    response = service.search(
        PubMedSearchRequest(disease_group_id="1", weather_factor="humidity", disease_terms=["asthma"])
    )
    assert response.count == 0
    assert response.results == []
    assert response.disease_group_id == "1"
    assert len(client.search_calls) == 1
    query, max_results = client.search_calls[0]
    assert '"asthma"[Title/Abstract]' in query
    assert '"humidity"[Title/Abstract]' in query
    assert query.count('"Child"[MeSH Terms]') == 1
    assert max_results == 10


def test_exact_pmid_lookup_is_single_record_and_does_not_persist(db, manifest):
    client = FakePubMedClient([article("34201085"), article("99999999")])
    service = MedicalKnowledgePubMedService(db, client, disease_manifest_path=manifest)

    response = service.lookup_pmid(lookup_request("34201085"))

    assert response.pmid == "34201085"
    assert response.result.pmid == "34201085"
    assert response.existing_source is None
    assert client.fetch_calls == [["34201085"]]
    assert client.search_calls == []
    assert db.query(MedicalEvidenceSource).count() == 0


def test_exact_pmid_lookup_reports_existing_source_without_duplicate(db, manifest):
    client = FakePubMedClient([article("34201085")])
    service = MedicalKnowledgePubMedService(db, client, disease_manifest_path=manifest)
    imported = service.import_pmids(import_request("34201085"), added_by=None)

    response = service.lookup_pmid(lookup_request("34201085"))

    assert response.existing_source is not None
    assert response.existing_source.id == imported.sources[0].id
    assert response.existing_source.created is False
    assert response.existing_source.content_kind == "ABSTRACT"
    assert db.query(MedicalEvidenceSource).count() == 1


def test_exact_pmid_lookup_returns_not_found_for_unknown_numeric_id(db, manifest):
    service = MedicalKnowledgePubMedService(db, FakePubMedClient(), disease_manifest_path=manifest)
    with pytest.raises(PubMedArticleNotFoundError):
        service.lookup_pmid(lookup_request("9999999999999999"))


@pytest.mark.parametrize("value", [" 34201085 ", "1"])
def test_exact_pmid_schema_normalizes_valid_values(value):
    assert lookup_request(value).pmid == value.strip()


@pytest.mark.parametrize(
    "value",
    ["", "   ", "abc", "34201085 OR pneumonia", "https://pubmed.ncbi.nlm.nih.gov/34201085/", "1 OR 1=1"],
)
def test_exact_pmid_schema_rejects_non_numeric_or_query_input(value):
    with pytest.raises(Exception):
        lookup_request(value)


def test_import_creates_pubmed_source_and_raw_metadata_without_secret(db, manifest):
    service = MedicalKnowledgePubMedService(db, FakePubMedClient([article("12345678")]), disease_manifest_path=manifest)
    response = service.import_pmids(import_request("12345678"), added_by=None)

    assert response.created_count == 1
    source = db.scalar(select(MedicalEvidenceSource).where(MedicalEvidenceSource.pmid == "12345678"))
    assert source is not None
    assert source.source_type == "PUBMED"
    assert source.url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert source.raw_metadata_json["provider"] == "NCBI PubMed"
    assert "api_key" not in json.dumps(source.raw_metadata_json).lower()


def test_reimport_same_pmid_reuses_source(db, manifest):
    service = MedicalKnowledgePubMedService(db, FakePubMedClient([article("12345678")]), disease_manifest_path=manifest)
    first = service.import_pmids(import_request("12345678"), added_by=None)
    second = service.import_pmids(import_request("12345678"), added_by=None)

    assert first.sources[0].id == second.sources[0].id
    assert second.created_count == 0
    assert second.reused_count == 1
    assert db.query(MedicalEvidenceSource).filter_by(pmid="12345678").count() == 1


def test_batch_import_multiple_pmids(db, manifest):
    client = FakePubMedClient([article("12345678"), article("87654321", "Second source")])
    service = MedicalKnowledgePubMedService(db, client, disease_manifest_path=manifest)
    response = service.import_pmids(
        import_request("12345678", "87654321"), added_by=None
    )

    assert response.count == 2
    assert response.created_count == 2
    assert client.fetch_calls == [["12345678", "87654321"]]
    assert db.query(MedicalEvidenceSource).count() == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"disease_group_id": "1", "weather_factor": "pressure", "disease_terms": ["asthma"]},
        {"disease_group_id": "1", "weather_factor": "humidity", "disease_terms": []},
        {"disease_group_id": "1", "weather_factor": "humidity", "disease_terms": ["bad[query"]},
        {"disease_group_id": "1", "weather_factor": "humidity", "disease_terms": ["asthma"], "max_results": 1000},
    ],
)
def test_search_request_validation_rejects_unsafe_or_unbounded_input(payload):
    with pytest.raises(Exception):
        PubMedSearchRequest(**payload)


class EndpointService:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def search(self, request):
        if self.error:
            raise self.error
        return PubMedSearchResponse(
            disease_group_id=request.disease_group_id,
            weather_factor=request.weather_factor,
            query='("asthma"[Title/Abstract]) AND ("humidity"[Title/Abstract])',
            count=0,
            results=[],
        )

    def import_pmids(self, _request, *, added_by):
        return PubMedImportResponse(
            topic_id=1,
            count=1,
            created_count=1,
            reused_count=0,
            sources=[PubMedImportedSource(id=1, pmid="12345678", created=True, title="Weather evidence")],
        )

    def lookup_pmid(self, request):
        if self.error:
            raise self.error
        record = article(request.pmid)
        return PubMedLookupResponse(
            pmid=request.pmid,
            result=PubMedRecord(
                pmid=record.pmid,
                title=record.title,
                authors=record.authors,
                journal=record.journal,
                publication_year=record.publication_year,
                doi=record.doi,
                abstract_text=record.abstract_text,
                pubmed_url=record.pubmed_url,
            ),
        )

    def get_topic_source_library(self, *, disease_group_id, weather_factor):
        if self.error:
            raise self.error
        return MedicalKnowledgeTopicSourceLibraryResponse(
            topic_id=None,
            disease_group_id=disease_group_id,
            weather_factor=weather_factor,
            sources=[],
        )


@pytest.fixture
def api_client(db):
    users = [
        User(username="admin", password_hash="x", role="admin", is_active=True),
        User(username="staff", password_hash="x", role="staff", is_active=True),
        User(username="viewer", password_hash="x", role="viewer", is_active=True),
    ]
    db.add_all(users)
    db.commit()
    app = FastAPI()
    app.include_router(router)
    app.include_router(options_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_pubmed_service] = lambda: EndpointService()
    with TestClient(app) as client:
        yield client, app


def search_payload():
    return {"disease_group_id": "1", "weather_factor": "humidity", "disease_terms": ["asthma"]}


def auth_header(username: str):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def test_anonymous_search_is_blocked(api_client):
    client, _app = api_client
    response = client.post("/api/medical-knowledge/pubmed/search", json=search_payload())
    assert response.status_code == 401


def test_unauthorized_role_is_blocked(api_client):
    client, _app = api_client
    response = client.post(
        "/api/medical-knowledge/pubmed/search", json=search_payload(), headers=auth_header("viewer")
    )
    assert response.status_code == 403


@pytest.mark.parametrize("username", ["admin", "staff"])
def test_admin_and_staff_can_search(api_client, username):
    client, _app = api_client
    response = client.post(
        "/api/medical-knowledge/pubmed/search", json=search_payload(), headers=auth_header(username)
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_admin_can_add_imported_pmids_to_an_explicit_topic(api_client):
    client, _app = api_client
    response = client.post(
        "/api/medical-knowledge/pubmed/import",
        json={
            "disease_group_id": "1",
            "weather_factor": "humidity",
            "pmids": ["12345678"],
        },
        headers=auth_header("admin"),
    )
    assert response.status_code == 200
    assert response.json()["sources"][0]["pmid"] == "12345678"


@pytest.mark.parametrize("username", ["admin", "staff"])
def test_admin_and_staff_can_read_the_exact_topic_source_library(api_client, username):
    client, _app = api_client
    response = client.get(
        "/api/medical-knowledge/topic-sources",
        params={"disease_group_id": "1", "weather_factor": "humidity"},
        headers=auth_header(username),
    )
    assert response.status_code == 200
    assert response.json() == {
        "topic_id": None,
        "disease_group_id": "1",
        "factor_type": "WEATHER",
        "factor_key": "humidity",
        "factor_value": None,
        "weather_factor": "humidity",
        "sources": [],
    }


def test_topic_source_library_blocks_viewer_and_invalid_weather_factor(api_client):
    client, _app = api_client
    viewer = client.get(
        "/api/medical-knowledge/topic-sources",
        params={"disease_group_id": "1", "weather_factor": "humidity"},
        headers=auth_header("viewer"),
    )
    invalid = client.get(
        "/api/medical-knowledge/topic-sources",
        params={"disease_group_id": "1", "weather_factor": "pressure"},
        headers=auth_header("admin"),
    )
    assert viewer.status_code == 403
    assert invalid.status_code == 422


@pytest.mark.parametrize("username", ["admin", "staff"])
def test_admin_and_staff_can_lookup_one_exact_pmid(api_client, username):
    client, _app = api_client
    response = client.post(
        "/api/medical-knowledge/pubmed/lookup",
        json={
            "pmid": " 34201085 ",
            "disease_group_id": "1",
            "weather_factor": "humidity",
        },
        headers=auth_header(username),
    )
    assert response.status_code == 200
    assert response.json()["pmid"] == "34201085"
    assert response.json()["result"]["pmid"] == "34201085"


@pytest.mark.parametrize("payload", [{}, {"pmid": "abc"}, {"pmid": "34201085 OR pneumonia"}])
def test_exact_pmid_endpoint_rejects_missing_or_unsafe_values(api_client, payload):
    client, _app = api_client
    response = client.post(
        "/api/medical-knowledge/pubmed/lookup",
        json=payload,
        headers=auth_header("admin"),
    )
    assert response.status_code == 422


def test_exact_pmid_endpoint_maps_not_found_safely(api_client):
    client, app = api_client
    app.dependency_overrides[get_pubmed_service] = lambda: EndpointService(
        PubMedArticleNotFoundError("internal provider context")
    )
    response = client.post(
        "/api/medical-knowledge/pubmed/lookup",
        json={
            "pmid": "99999999",
            "disease_group_id": "1",
            "weather_factor": "humidity",
        },
        headers=auth_header("admin"),
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "PubMed article was not found"}
    assert "internal provider context" not in response.text


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (PubMedUnavailableError("PubMed request timed out or failed"), 502),
        (PubMedRateLimitError("PubMed rate limit exceeded"), 503),
        (PubMedUnavailableError("PubMed service is unavailable"), 502),
    ],
)
def test_exact_pmid_endpoint_maps_provider_failures_safely(api_client, error, status_code):
    client, app = api_client
    app.dependency_overrides[get_pubmed_service] = lambda: EndpointService(error)
    response = client.post(
        "/api/medical-knowledge/pubmed/lookup",
        json={
            "pmid": "34201085",
            "disease_group_id": "1",
            "weather_factor": "humidity",
        },
        headers=auth_header("admin"),
    )
    assert response.status_code == status_code
    assert "traceback" not in response.text.lower()


def test_provider_timeout_maps_to_502_without_secret_or_trace(api_client):
    client, app = api_client
    app.dependency_overrides[get_pubmed_service] = lambda: EndpointService(
        PubMedUnavailableError("PubMed request timed out or failed")
    )
    response = client.post(
        "/api/medical-knowledge/pubmed/search", json=search_payload(), headers=auth_header("admin")
    )
    assert response.status_code == 502
    assert response.json() == {"detail": "PubMed request timed out or failed"}
    assert "api_key" not in response.text.lower()


def test_anonymous_medical_knowledge_options_is_blocked(api_client):
    client, _app = api_client
    response = client.get("/api/medical-knowledge/options")
    assert response.status_code == 401


def test_invalid_role_medical_knowledge_options_is_blocked(api_client):
    client, _app = api_client
    response = client.get("/api/medical-knowledge/options", headers=auth_header("viewer"))
    assert response.status_code == 403


@pytest.mark.parametrize("username", ["admin", "staff"])
def test_admin_and_staff_can_load_medical_knowledge_options(api_client, username):
    client, _app = api_client
    response = client.get("/api/medical-knowledge/options", headers=auth_header(username))
    assert response.status_code == 200
    body = response.json()
    assert len(body["disease_groups"]) == 221
    assert body["disease_groups"][0]["id"] == "1"
    assert [factor["value"] for factor in body["weather_factors"]] == [
        "temperature",
        "humidity",
        "precipitation",
        "wind",
        "weather_condition",
    ]
    assert isinstance(body["llm_draft_generation_available"], bool)
    assert "api_key" not in response.text.lower()


def test_options_disease_groups_match_deployed_universe_without_model_loading(api_client, monkeypatch):
    client, _app = api_client

    def fail_if_model_registry_loads():
        raise AssertionError("Model registry must not load for metadata options")

    monkeypatch.setattr("app.services.weather_ai_service.get_model_registry", fail_if_model_registry_loads)
    response = client.get("/api/medical-knowledge/options", headers=auth_header("admin"))
    assert response.status_code == 200
    body = response.json()
    manifest_path = Path(__file__).resolve().parents[2] / "weather_disease_ai_v3" / "deployment" / "lightgbm_h14_weather" / "model_manifest.json"
    deployed = json.loads(manifest_path.read_text(encoding="utf-8"))["disease_order"]
    assert [item["id"] for item in body["disease_groups"]] == [str(value) for value in deployed]
