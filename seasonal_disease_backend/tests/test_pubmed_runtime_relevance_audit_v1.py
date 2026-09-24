from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import medical_knowledge_models as _medical_knowledge_models  # noqa: F401
from app import models as _models  # noqa: F401 - register user FK targets
from app.database import Base
from app.routers import medical_evidence_reviewed
from app.security import require_staff_or_admin
from app.services.medical_evidence_provider import (
    MedicalEvidenceCapability,
    MedicalEvidenceProviderDescriptor,
    MedicalEvidenceProviderRegistry,
    MedicalEvidenceSearchResult,
    MedicalEvidenceSourceKind,
    NormalizedMedicalEvidence,
    ReviewedMedicalEvidenceQueryAttempt,
)
from app.services.medical_evidence_provider_settings_service import (
    MedicalEvidenceProviderSettingsService,
)
from app.services.medical_evidence_reviewed_service import MedicalEvidenceReviewedService
from app.services.pubmed_client import PubMedArticleRecord
from app.services.pubmed_evidence_provider import PubMedMedicalEvidenceProvider


BAD_MPRO = "The temperature-dependent conformational ensemble of SARS-CoV-2 main protease (Mpro)."
BAD_AGRICULTURE = (
    "Edge IoT Prototyping Using Model-Driven Representations: "
    "A Use Case for Smart Agriculture."
)
DIRECT_PLAGUE = "Human plague transmission and relative humidity"
RELATED_PLAGUE = "Plague vaccination"


def pubmed_record(pmid: str, title: str) -> PubMedArticleRecord:
    return PubMedArticleRecord(
        pmid=pmid,
        title=title,
        authors="Fixture Author",
        journal="Fixture Journal",
        publication_year=2026,
        doi=None,
        abstract_text=(
            "COVID-19 continues to plague the globe. Mpro structures were examined at high humidity."
            if title == BAD_MPRO else
            "Smart agriculture uses humidity sensors and drones for plague detection."
            if title == BAD_AGRICULTURE else None
        ),
        pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        raw_metadata={"publication_types": ["Journal Article"], "languages": ["eng"]},
    )


class FixturePubMedClient:
    def __init__(self):
        self.records = [
            pubmed_record("1001", BAD_MPRO),
            pubmed_record("1002", BAD_AGRICULTURE),
            pubmed_record("1003", DIRECT_PLAGUE),
            pubmed_record("1004", RELATED_PLAGUE),
        ]
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, max_results: int):
        self.calls.append((query, max_results))
        return len(self.records), self.records[:max_results]


@dataclass
class FixtureWhoProvider:
    descriptor = MedicalEvidenceProviderDescriptor(
        provider_id="WHO",
        display_name="World Health Organization (WHO)",
        capabilities=frozenset({MedicalEvidenceCapability.SEARCH}),
        max_search_results=25,
    )

    def build_reviewed_query_plan(self, _context):
        return (
            ReviewedMedicalEvidenceQueryAttempt(
                level="DIRECT_DISEASE_FACTOR",
                query="WHO plague humidity fixture",
                relevance="DIRECT_TOPIC",
            ),
        )

    def build_reviewed_query(self, _context):
        return "WHO plague humidity fixture"

    def search(self, _query: str, _max_results: int):
        source = NormalizedMedicalEvidence(
            provider_id="WHO",
            source_kind=MedicalEvidenceSourceKind.GUIDELINE,
            external_id="WHO-PLAGUE",
            title="WHO guidelines for plague management",
            canonical_url="https://www.who.int/publications/i/item/who-plague",
        )
        return MedicalEvidenceSearchResult(total_count=1, sources=(source,))


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def reviewed_service(db: Session, *, include_who: bool):
    pubmed_client = FixturePubMedClient()
    registry = MedicalEvidenceProviderRegistry()
    registry.register(PubMedMedicalEvidenceProvider(pubmed_client, SimpleNamespace()))
    if include_who:
        registry.register(FixtureWhoProvider())
        settings = MedicalEvidenceProviderSettingsService(db, registry)
        rows = settings.reconcile()
        rows[("WHO", "REVIEWED")].enabled = True
        db.commit()
    service = MedicalEvidenceReviewedService(db, registry)
    service._validate_disease = lambda _disease_group_id: None
    return service, pubmed_client


def post_runtime_search(service: MedicalEvidenceReviewedService, provider_ids: list[str]):
    api = FastAPI()
    api.include_router(medical_evidence_reviewed.router)
    api.dependency_overrides[medical_evidence_reviewed._service] = lambda: service
    api.dependency_overrides[require_staff_or_admin] = lambda: SimpleNamespace(
        id=1, role="admin"
    )
    payload = {
        "disease_group_id": "9",
        "disease_terms": ["Plague"],
        "provider_ids": provider_ids,
        "factor_type": "WEATHER",
        "factor_key": "humidity",
        "factor_value": None,
        "weather_factor": "humidity",
        "max_results": 10,
        "year_from": None,
        "year_to": None,
    }
    with TestClient(api) as client:
        response = client.post("/api/medical-knowledge/providers/search", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def pubmed_projection(response: dict):
    group = next(item for item in response["providers"] if item["provider_id"] == "PUBMED")
    return [
        (item["title"], item["relevance"], item["query_level"])
        for item in group["results"]
    ]


def test_01_real_ui_endpoint_pubmed_only_filters_exact_wrong_disease_titles(db):
    service, client = reviewed_service(db, include_who=False)
    response = post_runtime_search(service, ["PUBMED"])

    assert pubmed_projection(response) == [
        (DIRECT_PLAGUE, "DIRECT_TOPIC", "DIRECT_DISEASE_FACTOR_PEDIATRIC"),
        (RELATED_PLAGUE, "RELATED_CONTEXT", "DIRECT_DISEASE_FACTOR_PEDIATRIC"),
    ]
    visible_titles = {item[0] for item in pubmed_projection(response)}
    assert BAD_MPRO not in visible_titles
    assert BAD_AGRICULTURE not in visible_titles
    assert response["providers"][0]["rejected_count"] >= 2
    assert len(client.calls) == 3


def test_02_pubmed_classification_is_identical_with_who_selected(db):
    single_service, _ = reviewed_service(db, include_who=False)
    single = post_runtime_search(single_service, ["PUBMED"])

    mixed_service, _ = reviewed_service(db, include_who=True)
    mixed = post_runtime_search(mixed_service, ["PUBMED", "WHO"])

    assert pubmed_projection(mixed) == pubmed_projection(single)
    who = next(item for item in mixed["providers"] if item["provider_id"] == "WHO")
    assert [(item["title"], item["relevance"]) for item in who["results"]] == [
        ("WHO guidelines for plague management", "RELATED_CONTEXT")
    ]
