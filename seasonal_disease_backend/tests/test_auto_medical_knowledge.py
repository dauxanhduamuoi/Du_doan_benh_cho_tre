from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.database import get_db
from app.auto_medical_knowledge_schemas import (
    AutoBasicMedicalKnowledgeProposal,
    AutoMedicalKnowledgeDraftProposal,
    AutoNumericClaimProposal,
)
from app.medical_knowledge_draft_schemas import (
    DraftGenerationContext,
    DraftSourceInput,
    MedicalKnowledgeDraftProposal,
    SourceAssessment,
)
from app.medical_knowledge_models import (
    AutoMedicalKnowledgeJob,
    AutoMedicalKnowledgeNumericClaim,
    AutoMedicalKnowledgeProviderCooldown,
    AutoMedicalKnowledgeRevision,
    AutoMedicalKnowledgeTopicState,
    AutoMedicalKnowledgeVisibilityAudit,
    MedicalEvidenceSource,
    MedicalKnowledgeRevision,
    MedicalKnowledgeTopic,
    MedicalKnowledgeTopicSource,
    MedicalRevisionSource,
)
from app.models import User
from app.published_medical_knowledge_schemas import PublishedMedicalKnowledgeBatchRequest
from app.repositories.auto_medical_knowledge_repository import AutoMedicalKnowledgeRepository
from app.routers.auto_medical_knowledge import router as auto_router
from app.security import get_current_user
from app.services.auto_evidence_discovery import (
    AutoEvidenceSearchError,
    AutoDiscoveryResult,
    AutoEvidenceCandidate,
)
from app.services.auto_evidence_relevance import RelevanceSignals
from app.services.auto_medical_knowledge_prompt import (
    AUTO_SYSTEM_INSTRUCTIONS,
    build_auto_generation_input,
)
from app.services.auto_medical_numeric_validation import (
    NumericClaimContractViolation,
    NumericEvidenceSnapshot,
    NumericMetadata,
    find_unsupported_numeric_claim,
    validate_numeric_claim_contract,
)
from app.medical_knowledge_factors import load_factor_values
from app.services.auto_medical_knowledge_service import (
    AUTO_BASIC_PARENT_WARNING,
    AUTO_PARENT_WARNING,
    AUTO_SAFE_FALLBACK_PARENT_WARNING,
    AUTO_OUTPUT_REPAIRABLE_FAILURE_CODES,
    MAX_AUTO_CONTRACT_REPAIR_ATTEMPTS,
    MAX_AUTO_GENERATION_CALLS,
    MAX_AUTO_STRICT_GENERATION_CALLS,
    AutoMedicalKnowledgeAdminService,
    AutoMedicalKnowledgeProcessor,
    AutoMedicalKnowledgeQueueService,
    classify_auto_failure,
    is_auto_output_repairable,
)
from app.services.auto_medical_knowledge_safe_fallback import (
    AutoSafeFallbackRenderer,
    SafeFallbackEligibilitySnapshot,
    SafeFallbackSourceSnapshot,
    evaluate_safe_fallback_eligibility,
    factor_phrase_vi,
    is_safe_fallback_trigger,
)
from app.services.auto_evidence_qualification import qualify_auto_evidence
from app.services.auto_medical_knowledge_basic import validate_basic_proposal
from app.services.medical_knowledge_draft_generator import (
    DraftGeneratorOutputError,
    DraftGeneratorRateLimitError,
    DraftGeneratorStructuredOutputError,
    DraftGeneratorUnavailableError,
    parse_medical_draft_output,
)
from app.services.medical_knowledge_groq_generator import (
    GroqMedicalKnowledgeDraftGenerator,
)
from app.services.medical_evidence_content_service import ResolvedEvidenceContent
from app.services.published_medical_knowledge_read_service import PublishedMedicalKnowledgeReadService
from app.services.pubmed_client import PubMedArticleRecord
from migrations.v008_auto_medical_knowledge import upgrade as upgrade_auto_schema
from migrations.v009_auto_medical_knowledge_runtime_toggle import (
    upgrade as upgrade_auto_runtime_toggle,
)
from migrations.v010_auto_medical_knowledge_provider_cooldown import (
    upgrade as upgrade_auto_provider_cooldown,
)
from migrations.v011_auto_numeric_claim_contract import (
    upgrade as upgrade_auto_numeric_claim_contract,
)
from migrations.v012_auto_safe_fallback import upgrade as upgrade_auto_safe_fallback
from migrations.v013_auto_multi_tier_generation import upgrade as upgrade_auto_multi_tier
from migrations.v014_auto_topic_visibility import upgrade as upgrade_auto_topic_visibility


NOW = datetime(2026, 8, 28, 9, 0, 0)


def test_v008_is_additive_and_idempotent_for_reviewed_rows():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE medical_knowledge_topics (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE medical_evidence_sources (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE medical_evidence_contents (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO medical_knowledge_topics (id,marker) VALUES (7,'reviewed-unchanged')"
        )
    upgrade_auto_schema(engine)
    upgrade_auto_schema(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT id,marker FROM medical_knowledge_topics"
        ).fetchall() == [(7, "reviewed-unchanged")]
        names = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'auto_medical_knowledge_%'"
        ).fetchall()
        assert len(names) == 6
        assert connection.exec_driver_sql(
            "SELECT display_mode,auto_visible_default FROM auto_medical_knowledge_settings"
        ).fetchone() == ("REVIEWED_ONLY", 0)
    engine.dispose()


def test_v009_adds_persisted_runtime_toggle_default_off_idempotently():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE auto_medical_knowledge_settings ("
            "id INTEGER PRIMARY KEY, display_mode TEXT NOT NULL, "
            "auto_visible_default BOOLEAN NOT NULL, updated_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO auto_medical_knowledge_settings VALUES "
            "(1,'REVIEWED_WITH_AUTO_FALLBACK',1,CURRENT_TIMESTAMP)"
        )
    upgrade_auto_runtime_toggle(engine)
    upgrade_auto_runtime_toggle(engine)
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT enabled,display_mode,auto_visible_default "
            "FROM auto_medical_knowledge_settings WHERE id=1"
        ).fetchone()
        assert row == (0, "REVIEWED_WITH_AUTO_FALLBACK", 1)
    engine.dispose()


def test_v010_adds_persisted_provider_cooldown_idempotently_without_reviewed_writes():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE medical_knowledge_revisions (id INTEGER PRIMARY KEY, marker TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO medical_knowledge_revisions VALUES (7,'reviewed-unchanged')"
        )
    upgrade_auto_provider_cooldown(engine)
    upgrade_auto_provider_cooldown(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT id,marker FROM medical_knowledge_revisions"
        ).fetchall() == [(7, "reviewed-unchanged")]
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM auto_medical_knowledge_provider_cooldowns"
        ).scalar_one() == 0
    engine.dispose()


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def disease_files(tmp_path):
    manifest = tmp_path / "model_manifest.json"
    catalog = tmp_path / "disease_catalog.csv"
    manifest.write_text(json.dumps({"model_count": 1, "disease_order": ["5"]}), encoding="utf-8")
    catalog.write_text(
        "disease_group_id,disease_group_name,report_group_code\n"
        "5,Tiêu chảy - Gastroenteritis,A09\n",
        encoding="utf-8",
    )
    return manifest, catalog


def request():
    return PublishedMedicalKnowledgeBatchRequest(
        items=[{"disease_group_id": "5", "weather_factor": "precipitation"}]
    )


def queue(db, *, enabled=True):
    settings = AutoMedicalKnowledgeRepository(db).get_settings()
    settings.enabled = enabled
    db.commit()
    return AutoMedicalKnowledgeQueueService(
        db,
        max_retries=3,
        insufficient_stale_days=30,
        clock=lambda: NOW,
    )


class FakeDiscovery:
    provider_name = "PUBMED_PMC"

    def __init__(self, *, empty=False, fail=False, trust_class="PUBMED"):
        self.empty = empty
        self.fail = fail
        self.trust_class = trust_class
        self.calls = 0

    def discover(self, *, topic, disease_name, max_sources, disease_aliases=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("deterministic discovery failure")
        if self.empty:
            return AutoDiscoveryResult(selected=(), audit=(), queries=("bounded query",))
        record = PubMedArticleRecord(
            pmid="40123456",
            title="Rainfall and pediatric gastroenteritis admissions",
            authors="Nguyen A; Tran B",
            journal="Pediatric Evidence Journal",
            publication_year=2025,
            doi="10.1000/ped-rain",
            abstract_text="A pediatric study of children reports an association between rainfall and gastroenteritis admissions.",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/40123456/",
            raw_metadata={"publication_types": ["Journal Article"]},
        )
        evidence = ResolvedEvidenceContent(
            content_kind="ABSTRACT",
            content_origin="NCBI_PUBMED",
            external_identifier="40123456",
            evidence_text=record.abstract_text or "",
            retrieved_at=NOW,
            is_truncated=False,
            license_name=None,
            license_url=None,
            provenance={"provider": "NCBI_PUBMED", "pmid": record.pmid},
        )
        return AutoDiscoveryResult(
            selected=(AutoEvidenceCandidate(
                record,
                evidence,
                self.trust_class,
                100,
                RelevanceSignals(disease=1, factor=1, pediatric=1),
            ),),
            audit=(),
            queries=("bounded query",),
        )


class AdultEvidenceDiscovery(FakeDiscovery):
    def discover(self, **kwargs):
        result = super().discover(**kwargs)
        candidate = result.selected[0]
        adult_text = "An adult cohort reports an association between rainfall and gastroenteritis."
        return replace(
            result,
            selected=(replace(
                candidate,
                record=replace(candidate.record, abstract_text=adult_text),
                evidence=replace(candidate.evidence, evidence_text=adult_text),
            ),),
        )


class CountEvidenceDiscovery(FakeDiscovery):
    def discover(self, **kwargs):
        result = super().discover(**kwargs)
        candidate = result.selected[0]
        evidence_text = (
            "A pediatric cohort included 5087 hospitalized children and reported "
            "an association between rainfall and gastroenteritis admissions."
        )
        return replace(
            result,
            selected=(replace(
                candidate,
                record=replace(candidate.record, abstract_text=evidence_text),
                evidence=replace(candidate.evidence, evidence_text=evidence_text),
            ),),
        )


class YearRangeEvidenceDiscovery(FakeDiscovery):
    def __init__(self, evidence_text):
        super().__init__()
        self.evidence_text = evidence_text

    def discover(self, **kwargs):
        result = super().discover(**kwargs)
        candidate = result.selected[0]
        return replace(
            result,
            selected=(replace(
                candidate,
                record=replace(candidate.record, abstract_text=self.evidence_text),
                evidence=replace(candidate.evidence, evidence_text=self.evidence_text),
            ),),
        )


class FakeGenerator:
    model_name = "deterministic-test-model"

    def __init__(self, *, fail=False, population="PEDIATRIC_DIRECT"):
        self.fail = fail
        self.population = population
        self.calls = 0
        self.contexts = []

    def generate(
        self,
        context,
        *,
        structural_retry=False,
        user_input_override=None,
    ):
        self.calls += 1
        self.contexts.append(context)
        if self.fail:
            raise RuntimeError("deterministic generation failure")
        return AutoMedicalKnowledgeDraftProposal(
            evidence_level="SUPPORTED",
            evidence_scope="PARTIAL_GROUP",
            short_explanation_vi="Nghiên cứu đã chọn ghi nhận mối liên quan ở trẻ em.",
            detailed_explanation_vi="Bằng chứng nhóm cho thấy mưa có liên quan với số ca nhập viện do viêm dạ dày ruột ở trẻ em; không khẳng định quan hệ nhân quả.",
            limitations_vi="Chỉ áp dụng cho quần thể và bối cảnh trong nghiên cứu đã chọn.",
            source_assessments=[
                SourceAssessment(
                    source_id=source.source_id,
                    relevance="DIRECT",
                    note_vi="Nguồn trực tiếp đánh giá yếu tố và nhóm bệnh.",
                    population_relevance=self.population,
                    population_note="Nghiên cứu mô tả trực tiếp trẻ em." if self.population == "PEDIATRIC_DIRECT" else "Nguồn chỉ mô tả người lớn.",
                )
                for source in context.sources
            ],
            numeric_claims=[],
        )


class FakeBasicGenerator:
    model_name = "deterministic-basic-model"

    def __init__(self, *, summary="Các nghiên cứu ghi nhận một mối liên hệ ở trẻ em.", source_ids=None, result="SUPPORTED", error=None):
        self.summary = summary
        self.source_ids = source_ids
        self.result = result
        self.error = error
        self.calls = 0
        self.contexts = []

    def generate(self, context, **_kwargs):
        self.calls += 1
        self.contexts.append(context)
        if self.error is not None:
            raise self.error
        return AutoBasicMedicalKnowledgeProposal(
            result=self.result,
            summary_vi=self.summary if self.result == "SUPPORTED" else None,
            source_ids=(
                self.source_ids
                if self.source_ids is not None
                else ([context.sources[0].source_id] if self.result == "SUPPORTED" else [])
            ),
        )


class RiskyGenerator(FakeGenerator):
    def __init__(self, text, numeric_claims=()):
        super().__init__()
        self.text = text
        self.numeric_claims = [
            claim if isinstance(claim, AutoNumericClaimProposal)
            else AutoNumericClaimProposal.model_validate(claim)
            for claim in numeric_claims
        ]

    def generate(
        self,
        context,
        *,
        structural_retry=False,
        user_input_override=None,
    ):
        proposal = super().generate(
            context,
            structural_retry=structural_retry,
            user_input_override=user_input_override,
        )
        return proposal.model_copy(update={
            "detailed_explanation_vi": self.text,
            "numeric_claims": self.numeric_claims,
        })


class ContractRepairGenerator(FakeGenerator):
    def __init__(
        self,
        *,
        initial_text,
        repaired_text,
        initial_claims=(),
        repaired_claims=(),
        repair_error=None,
    ):
        super().__init__()
        self.initial_text = initial_text
        self.repaired_text = repaired_text
        self.initial_claims = [
            claim if isinstance(claim, AutoNumericClaimProposal)
            else AutoNumericClaimProposal.model_validate(claim)
            for claim in initial_claims
        ]
        self.repaired_claims = [
            claim if isinstance(claim, AutoNumericClaimProposal)
            else AutoNumericClaimProposal.model_validate(claim)
            for claim in repaired_claims
        ]
        self.repair_error = repair_error
        self.repair_instructions = []

    def generate(
        self,
        context,
        *,
        structural_retry=False,
        user_input_override=None,
    ):
        proposal = super().generate(
            context,
            structural_retry=structural_retry,
            user_input_override=user_input_override,
        )
        if user_input_override is None:
            return proposal.model_copy(update={
                "detailed_explanation_vi": self.initial_text,
                "numeric_claims": self.initial_claims,
            })
        self.repair_instructions.append(user_input_override)
        if self.repair_error is not None:
            raise self.repair_error
        return proposal.model_copy(update={
            "detailed_explanation_vi": self.repaired_text,
            "numeric_claims": self.repaired_claims,
        })


class NotSupportiveGenerator(FakeGenerator):
    def generate(self, context):
        proposal = super().generate(context)
        return proposal.model_copy(
            update={
                "source_assessments": [
                    item.model_copy(update={"relevance": "NOT_SUPPORTIVE"})
                    for item in proposal.source_assessments
                ]
            }
        )


class StructuralThenValidGenerator(FakeGenerator):
    def generate(self, context, *, structural_retry=False):
        if not structural_retry:
            self.calls += 1
            raise DraftGeneratorStructuredOutputError(
                "AUTO_OUTPUT_SCHEMA_INVALID",
                "Provider output does not satisfy the required structured schema.",
                field="evidence_level",
            )
        return super().generate(context)


class StructuralThenContractInvalidGenerator(FakeGenerator):
    def generate(
        self,
        context,
        *,
        structural_retry=False,
        user_input_override=None,
    ):
        if not structural_retry:
            self.calls += 1
            raise DraftGeneratorStructuredOutputError(
                "AUTO_OUTPUT_SCHEMA_INVALID",
                "Provider output does not satisfy the required structured schema.",
                field="evidence_level",
            )
        proposal = super().generate(context, structural_retry=True)
        return proposal.model_copy(update={
            "detailed_explanation_vi": (
                "The pediatric study used 3 groups and reported an association."
            )
        })


class RateLimitedGenerator(FakeGenerator):
    def __init__(self, *, retry_after_seconds=None):
        super().__init__()
        self.retry_after_seconds = retry_after_seconds

    def generate(self, context):
        self.calls += 1
        raise DraftGeneratorRateLimitError(
            "provider detail must not be persisted",
            retry_after_seconds=self.retry_after_seconds,
        )


class GenericOutputGenerator(FakeGenerator):
    def generate(self, context):
        self.calls += 1
        raise DraftGeneratorOutputError("untyped provider envelope detail")


class UnsupportedSourceClaimGenerator(FakeGenerator):
    def generate(self, context):
        proposal = super().generate(context)
        return proposal.model_copy(update={
            "source_assessments": [item.model_copy(update={
                "note_vi": "Đây là thử nghiệm ngẫu nhiên trực tiếp."
            }) for item in proposal.source_assessments]
        })


class FencedJsonGenerator(FakeGenerator):
    def generate(self, context):
        proposal = super().generate(context)
        return parse_medical_draft_output(
            f"```json\n{proposal.model_dump_json()}\n```",
            context,
            AutoMedicalKnowledgeDraftProposal,
        )


def groq_auto_proposal(*, detailed=None, numeric_claims=()):
    return {
        "evidence_level": "SUPPORTED",
        "evidence_scope": "PARTIAL_GROUP",
        "short_explanation_vi": "Nghiên cứu đã chọn ghi nhận mối liên quan ở trẻ em.",
        "detailed_explanation_vi": detailed or (
            "Bằng chứng nhóm cho thấy mưa có liên quan với số ca nhập viện do "
            "viêm dạ dày ruột ở trẻ em; không khẳng định quan hệ nhân quả."
        ),
        "limitations_vi": "Chỉ áp dụng cho quần thể và bối cảnh trong nghiên cứu đã chọn.",
        "source_assessments": [{
            "source_id": 1,
            "relevance": "DIRECT",
            "note_vi": "Nguồn trực tiếp đánh giá yếu tố và nhóm bệnh.",
            "population_relevance": "PEDIATRIC_DIRECT",
            "population_note": "Nghiên cứu mô tả trực tiếp trẻ em.",
        }],
        "numeric_claims": list(numeric_claims),
    }


def groq_completion(content, *, finish_reason="stop"):
    return {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        }]
    }


def groq_auto_generator(response_body):
    calls = []

    def handler(request: httpx.Request):
        calls.append(json.loads(request.content))
        body = response_body(len(calls)) if callable(response_body) else response_body
        if isinstance(body, httpx.Response):
            return body
        return httpx.Response(200, json=body)

    generator = GroqMedicalKnowledgeDraftGenerator(
        api_key="deterministic-groq-key",
        model="openai/gpt-oss-20b",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        system_instructions=AUTO_SYSTEM_INSTRUCTIONS,
        input_builder=build_auto_generation_input,
        proposal_model=AutoMedicalKnowledgeDraftProposal,
    )
    return generator, calls


def processor(
    db,
    disease_files,
    discovery,
    generator,
    *,
    basic_generator=None,
    visible=True,
    provider_name=None,
    cooldown_seconds=300,
    retry_delay_seconds=60,
    now=NOW,
):
    manifest, catalog = disease_files
    return AutoMedicalKnowledgeProcessor(
        db,
        discovery,
        generator,
        basic_generator,
        disease_manifest_path=manifest,
        disease_catalog_path=catalog,
        max_sources=10,
        max_retries=3,
        retry_delay_seconds=retry_delay_seconds,
        provider_name=provider_name,
        rate_limit_cooldown_seconds=cooldown_seconds,
        prompt_version="medical_knowledge_auto_v2_numeric_claims",
        auto_visible_default=visible,
        max_input_chars=60_000,
        clock=lambda: now,
    )


def parent(db, auto_queue):
    return PublishedMedicalKnowledgeReadService(db, auto_queue=auto_queue)


def enable_fallback(db):
    settings = AutoMedicalKnowledgeRepository(db).get_settings()
    settings.display_mode = "REVIEWED_WITH_AUTO_FALLBACK"
    db.commit()


def generate_ready_auto(db, disease_files, *, population="PEDIATRIC_DIRECT"):
    q = queue(db)
    assert parent(db, q).read_batch(request()).items == []
    AutoMedicalKnowledgeRepository(db).get_settings().auto_visible_default = True
    db.commit()
    discovery = FakeDiscovery()
    generator = FakeGenerator(population=population)
    processor(db, disease_files, discovery, generator).process_next()
    return q, discovery, generator


def generate_safe_fallback_auto(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    AutoMedicalKnowledgeRepository(db).get_settings().auto_visible_default = True
    db.commit()
    prose = "The pediatric study used 3 groups and reported an association."
    discovery = FakeDiscovery()
    generator = ContractRepairGenerator(initial_text=prose, repaired_text=prose)
    processor(db, disease_files, discovery, generator).process_next()
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert revision.generation_mode == "SAFE_FALLBACK"
    return q, discovery, generator


def test_admin_overview_resolves_disease_name_once_for_jobs_and_revisions(
    db, disease_files, monkeypatch
):
    q, _discovery, _generator = generate_ready_auto(db, disease_files)
    calls = []

    def deployed_contexts(manifest_path, catalog_path):
        calls.append((manifest_path, catalog_path))
        return {"5": ("Tiêu chảy - Gastroenteritis", "A09")}

    monkeypatch.setattr(
        "app.services.auto_medical_knowledge_service.load_deployed_disease_contexts",
        deployed_contexts,
    )
    overview = AutoMedicalKnowledgeAdminService(db, queue_service=q).overview()

    assert len(calls) == 1
    assert overview.jobs[0].disease_group_name == "Tiêu chảy - Gastroenteritis"
    assert overview.revisions[0].disease_group_name == "Tiêu chảy - Gastroenteritis"


def test_feature_disabled_is_zero_write_and_zero_external_work(db):
    disabled = queue(db, enabled=False)
    discovery = FakeDiscovery()
    assert disabled.enqueue_selectors(request().items) == []
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 0
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeTopicState)) == 0
    assert discovery.calls == 0


def test_non_deployed_public_selector_cannot_create_auto_topic(db):
    q = queue(db)
    payload = PublishedMedicalKnowledgeBatchRequest(
        items=[{"disease_group_id": "999999", "weather_factor": "precipitation"}]
    )
    assert q.enqueue_selectors(payload.items) == []
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 0


def test_auto_demand_generation_e2e(db, disease_files):
    q, discovery, generator = generate_ready_auto(db, disease_files)
    enable_fallback(db)
    result = parent(db, q).read_batch(request())

    assert discovery.calls == generator.calls == 1
    assert len(result.items) == 1
    assert result.items[0].knowledge_type == "AUTO"
    assert result.items[0].auto_tier == "STRICT"
    assert result.items[0].warning == AUTO_PARENT_WARNING
    assert result.items[0].sources[0].pmid == "40123456"
    prompt_payload = json.loads(build_auto_generation_input(generator.contexts[0]))
    assert set(prompt_payload["scope"]) == {
        "disease_group_id", "disease_group_name", "report_group_code", "factor_type",
        "factor_key", "factor_value", "weather_factor", "population",
    }
    assert prompt_payload["numeric_claim_contract"]["version"] == (
        "medical_knowledge_auto_v2_numeric_claims"
    )
    assert "Prefer a qualitative explanation" in AUTO_SYSTEM_INSTRUCTIONS
    assert "numeric_claims" in AUTO_SYSTEM_INSTRUCTIONS
    assert "Before returning, scan short_explanation_vi" in AUTO_SYSTEM_INSTRUCTIONS
    assert "numeric_claims" not in result.items[0].model_dump()
    assert db.scalar(select(func.count()).select_from(MedicalKnowledgeTopicSource)) == 0


def test_auto_job_dedup_e2e(db):
    q = queue(db)
    for _ in range(5):
        q.enqueue_selectors(request().items)
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 1
    state = db.scalar(select(AutoMedicalKnowledgeTopicState))
    assert state.request_count == 5


def test_auto_insufficient_e2e_suppresses_repeat_generation(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    discovery = FakeDiscovery(empty=True)
    generator = FakeGenerator()
    processor(db, disease_files, discovery, generator).process_next()
    enable_fallback(db)

    assert parent(db, q).read_batch(request()).items == []
    assert generator.calls == 0
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 1
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert revision.generation_status == "INSUFFICIENT"
    assert revision.is_visible is False


@pytest.mark.parametrize("failure_stage", ["discovery", "generation"])
def test_auto_failure_isolation_e2e(db, disease_files, failure_stage):
    q = queue(db)
    q.enqueue_selectors(request().items)
    discovery = FakeDiscovery(fail=failure_stage == "discovery")
    generator = FakeGenerator(fail=failure_stage == "generation")
    processor(db, disease_files, discovery, generator).process_next()
    enable_fallback(db)

    assert parent(db, q).read_batch(request()).items == []
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert job.status == "FAILED"
    assert job.last_error_code == "UNKNOWN_INTERNAL_ERROR"


def test_unsupported_provider_trust_class_fails_closed(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(db, disease_files, FakeDiscovery(trust_class="WHO"), FakeGenerator()).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert job.status == "INSUFFICIENT"
    assert job.last_error_code is None
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert revision.generation_status == "INSUFFICIENT"
    assert revision.short_explanation_vi is None


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "Mưa gây ra bệnh ở trẻ em.",
        "Độ ẩm làm suy yếu miễn dịch của trẻ em.",
    ],
)
def test_causal_and_mechanism_claims_fail_closed(
    db, disease_files, unsafe_text
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(db, disease_files, FakeDiscovery(), RiskyGenerator(unsafe_text)).process_next()
    assert db.scalar(select(AutoMedicalKnowledgeJob)).status == "FAILED"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_adult_only_output_becomes_hidden_insufficient(db, disease_files):
    q, _discovery, _generator = generate_ready_auto(
        db, disease_files, population="ADULT_ONLY"
    )
    enable_fallback(db)
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert revision.generation_status == "INSUFFICIENT"
    assert revision.is_visible is False
    assert parent(db, q).read_batch(request()).items == []


def test_reviewed_overrides_auto_e2e_and_withdraw_restores_auto(db, disease_files):
    q, _discovery, _generator = generate_safe_fallback_auto(db, disease_files)
    enable_fallback(db)
    initial_auto = parent(db, q).read_batch(request()).items[0]
    assert initial_auto.knowledge_type == "AUTO"
    assert initial_auto.auto_tier == "BASIC"

    canonical_topic = db.scalar(
        select(MedicalKnowledgeTopic).where(MedicalKnowledgeTopic.disease_group_id == "5")
    )
    source = MedicalEvidenceSource(
        source_type="PUBMED", pmid="40999999", title="Reviewed pediatric source",
        abstract_text="A pediatric study in children.", raw_metadata_json={},
    )
    reviewed = MedicalKnowledgeRevision(
        topic_id=canonical_topic.id, revision_number=1, evidence_level="SUPPORTED",
        evidence_scope="PARTIAL_GROUP", short_explanation_vi="Nội dung đã kiểm duyệt.",
        detailed_explanation_vi="Nội dung chi tiết đã kiểm duyệt.", limitations_vi="Có giới hạn.",
        status="APPROVED", parent_display_allowed=True, generated_by_llm=False,
    )
    db.add_all([source, reviewed])
    db.flush()
    db.add(MedicalRevisionSource(
        revision_id=reviewed.id, source_id=source.id, source_role="PRIMARY", sort_order=0,
        relevance_note="DIRECT: Nguồn hỗ trợ trực tiếp.", population_relevance="PEDIATRIC_DIRECT",
        population_note="Nguồn đánh giá trực tiếp trẻ em.",
    ))
    canonical_topic.published_revision_id = reviewed.id
    db.commit()

    reviewed_result = parent(db, q).read_batch(request())
    assert [item.knowledge_type for item in reviewed_result.items] == ["REVIEWED"]
    canonical_topic.published_revision_id = None
    reviewed.parent_display_allowed = False
    db.commit()
    restored = parent(db, q).read_batch(request()).items[0]
    assert restored.knowledge_type == "AUTO"
    assert restored.auto_tier == "BASIC"


def test_parent_display_gate_and_default_auto_visibility_are_independent(
    db, disease_files
):
    q, _discovery, _generator = generate_ready_auto(db, disease_files)
    assert parent(db, q).read_batch(request()).items == []
    enable_fallback(db)
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    revision.is_visible = False
    db.commit()
    # Legacy false is not evidence that staff explicitly hid the canonical topic.
    assert parent(db, q).read_batch(request()).items[0].knowledge_type == "AUTO"


def test_eligible_strict_is_automatic_when_legacy_auto_default_is_false(
    db, disease_files
):
    q = queue(db)
    settings = AutoMedicalKnowledgeRepository(db).get_settings()
    assert settings.auto_visible_default is False
    settings.display_mode = "REVIEWED_WITH_AUTO_FALLBACK"
    db.commit()
    q.enqueue_selectors(request().items)

    processor(db, disease_files, FakeDiscovery(), FakeGenerator()).process_next()

    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert revision.auto_tier == "STRICT"
    assert parent(db, q).read_batch(request()).items[0].auto_tier == "STRICT"


def _visibility_actor(db, *, username="visibility-staff", role="staff"):
    actor = User(
        username=username,
        password_hash="not-used-in-test",
        role=role,
        is_active=True,
    )
    db.add(actor)
    db.commit()
    return actor


def _set_topic_hidden(db, q, *, hidden, actor):
    return AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).set_topic_visibility(
        disease_group_id="5",
        factor_type="WEATHER",
        factor_key="precipitation",
        factor_value=None,
        weather_factor="precipitation",
        hidden=hidden,
        actor_user_id=actor.id,
    )


def test_topic_hide_unhide_is_immediate_audited_and_does_not_generate(
    db, disease_files
):
    q, _discovery, _generator = generate_ready_auto(db, disease_files)
    enable_fallback(db)
    actor = _visibility_actor(db)
    before_jobs = db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob))
    before_revisions = db.scalar(
        select(func.count()).select_from(AutoMedicalKnowledgeRevision)
    )

    topic, state = _set_topic_hidden(db, q, hidden=True, actor=actor)
    assert state.is_hidden_by_staff is True
    assert state.hidden_at is not None
    hidden_revision = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().revisions[0]
    assert hidden_revision.auto_display_eligible is True
    assert hidden_revision.topic_hidden_by_staff is True
    assert hidden_revision.is_visible is False
    assert parent(db, q).read_batch(request()).items == []

    _set_topic_hidden(db, q, hidden=False, actor=actor)
    unhidden_revision = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().revisions[0]
    assert unhidden_revision.topic_hidden_by_staff is False
    assert unhidden_revision.is_visible is True
    assert parent(db, q).read_batch(request()).items[0].knowledge_type == "AUTO"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == before_jobs
    assert db.scalar(
        select(func.count()).select_from(AutoMedicalKnowledgeRevision)
    ) == before_revisions
    audits = list(
        db.scalars(
            select(AutoMedicalKnowledgeVisibilityAudit).order_by(
                AutoMedicalKnowledgeVisibilityAudit.id
            )
        )
    )
    assert [(row.topic_id, row.action, row.actor_user_id) for row in audits] == [
        (topic.id, "HIDE_AUTO_TOPIC", actor.id),
        (topic.id, "UNHIDE_AUTO_TOPIC", actor.id),
    ]


@pytest.mark.parametrize("tier", ["STRICT", "BASIC"])
def test_hidden_topic_stays_hidden_after_regeneration(db, disease_files, tier):
    q, _discovery, _generator = generate_ready_auto(db, disease_files)
    enable_fallback(db)
    actor = _visibility_actor(db, username=f"visibility-{tier.lower()}")
    topic, _state = _set_topic_hidden(db, q, hidden=True, actor=actor)

    result = q.regenerate_topic(request().items[0])
    assert result.created is True
    strict_generator = FakeGenerator(fail=tier == "BASIC")
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        strict_generator,
        basic_generator=FakeBasicGenerator() if tier == "BASIC" else None,
    ).process_next()

    revisions = list(
        db.scalars(
            select(AutoMedicalKnowledgeRevision)
            .where(AutoMedicalKnowledgeRevision.topic_id == topic.id)
            .order_by(AutoMedicalKnowledgeRevision.id)
        )
    )
    assert len(revisions) == 2
    assert revisions[-1].auto_tier == tier
    assert db.get(AutoMedicalKnowledgeTopicState, topic.id).is_hidden_by_staff is True
    assert parent(db, q).read_batch(request()).items == []


def test_hide_while_job_is_generating_cannot_be_overwritten(db, disease_files):
    q = queue(db)
    job_id = q.enqueue_selectors(request().items)[0]
    repository = AutoMedicalKnowledgeRepository(db)
    assert repository.claim_next_job(now=NOW, max_retries=3) == job_id
    actor = _visibility_actor(db, username="during-generation")
    topic_id = repository.get_job(job_id).topic_id

    class HideDuringGeneration(FakeGenerator):
        observed_status = None

        def generate(self, context, **kwargs):
            self.observed_status = db.get(AutoMedicalKnowledgeJob, job_id).status
            _set_topic_hidden(db, q, hidden=True, actor=actor)
            return super().generate(context, **kwargs)

    generator = HideDuringGeneration()

    processor(db, disease_files, FakeDiscovery(), generator)._process(job_id)

    assert generator.observed_status == "GENERATING"
    assert db.get(AutoMedicalKnowledgeJob, job_id).status == "READY"
    assert db.get(AutoMedicalKnowledgeTopicState, topic_id).is_hidden_by_staff is True
    enable_fallback(db)
    assert parent(db, q).read_batch(request()).items == []


def test_failed_job_can_be_retried_without_creating_duplicate(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(db, disease_files, FakeDiscovery(fail=True), FakeGenerator()).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    AutoMedicalKnowledgeAdminService(db, queue_service=q).retry_job(job.id)
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 1
    assert db.get(AutoMedicalKnowledgeJob, job.id).status == "QUEUED"


def test_admin_regenerate_insufficient_creates_new_job_and_preserves_history(
    db, disease_files
):
    q = queue(db)
    old_job_id = q.enqueue_selectors(request().items)[0]
    processor(
        db, disease_files, FakeDiscovery(empty=True), FakeGenerator()
    ).process_next()
    old_revision = db.scalar(select(AutoMedicalKnowledgeRevision))

    result = q.regenerate_topic(request().items[0])

    jobs = list(db.scalars(select(AutoMedicalKnowledgeJob).order_by(AutoMedicalKnowledgeJob.id)))
    assert result.created is True
    assert result.outcome == "CREATED"
    assert result.job_id != old_job_id
    assert result.job_status == "QUEUED"
    assert [job.status for job in jobs] == ["INSUFFICIENT", "QUEUED"]
    assert db.get(AutoMedicalKnowledgeRevision, old_revision.id) is old_revision
    assert old_revision.generation_status == "INSUFFICIENT"

    fresh_discovery = FakeDiscovery()
    processor(
        db, disease_files, fresh_discovery, FakeGenerator()
    ).process_next()
    overview = AutoMedicalKnowledgeAdminService(db, queue_service=q).overview()
    assert fresh_discovery.calls == 1
    assert [job.id for job in overview.jobs[:2]] == [result.job_id, old_job_id]
    assert overview.jobs[0].status == "READY"
    assert overview.jobs[0].is_current_attempt is True
    assert overview.jobs[1].status == "INSUFFICIENT"
    assert overview.jobs[1].is_current_attempt is False
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 2


def test_admin_regenerate_failed_creates_new_job(db, disease_files):
    q = queue(db)
    old_job_id = q.enqueue_selectors(request().items)[0]
    processor(
        db, disease_files, FakeDiscovery(fail=True), FakeGenerator()
    ).process_next()

    result = q.regenerate_topic(request().items[0])

    assert result.created is True
    assert result.job_id != old_job_id
    assert db.get(AutoMedicalKnowledgeJob, old_job_id).status == "FAILED"
    assert db.get(AutoMedicalKnowledgeJob, result.job_id).status == "QUEUED"


def test_admin_regenerate_ready_creates_new_job_and_preserves_revision(
    db, disease_files
):
    q = queue(db)
    old_job_id = q.enqueue_selectors(request().items)[0]
    processor(db, disease_files, FakeDiscovery(), FakeGenerator()).process_next()
    old_revision = db.scalar(select(AutoMedicalKnowledgeRevision))

    result = q.regenerate_topic(request().items[0])

    assert result.created is True
    assert result.job_id != old_job_id
    assert db.get(AutoMedicalKnowledgeJob, old_job_id).status == "READY"
    assert db.get(AutoMedicalKnowledgeRevision, old_revision.id) is old_revision
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 1


@pytest.mark.parametrize("active_status", ["QUEUED", "SEARCHING", "GENERATING"])
def test_admin_regenerate_returns_exact_active_job_without_duplicate(
    db, active_status
):
    q = queue(db)
    active_id = q.enqueue_selectors(request().items)[0]
    repository = AutoMedicalKnowledgeRepository(db)
    if active_status != "QUEUED":
        repository.set_job_status(active_id, active_status)
        db.commit()

    result = q.regenerate_topic(request().items[0])

    assert result.created is False
    assert result.outcome == "ALREADY_ACTIVE"
    assert result.job_id == active_id
    assert result.job_status == active_status
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 1


def test_admin_regenerate_waiting_retry_does_not_create_duplicate(db):
    q = queue(db)
    job_id = q.enqueue_selectors(request().items)[0]
    repository = AutoMedicalKnowledgeRepository(db)
    repository.set_job_status(
        job_id,
        "FAILED",
        next_retry_at=NOW + timedelta(minutes=5),
        finished_at=NOW,
        last_error_code="LLM_RATE_LIMITED",
    )
    db.commit()

    result = q.regenerate_topic(request().items[0], provider="groq")

    assert result.created is False
    assert result.outcome == "WAITING_RETRY"
    assert result.job_id == job_id
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 1


def test_admin_regenerate_provider_cooldown_does_not_create_job(db):
    q = queue(db)
    AutoMedicalKnowledgeRepository(db).set_provider_cooldown(
        "groq",
        cooldown_until=NOW + timedelta(minutes=5),
        reason="LLM_RATE_LIMITED",
        now=NOW,
    )
    db.commit()

    result = q.regenerate_topic(request().items[0], provider="groq")

    assert result.created is False
    assert result.outcome == "PROVIDER_COOLDOWN"
    assert result.job_id is None
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 0


def test_parent_enqueue_keeps_terminal_dedup_while_admin_can_regenerate(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(
        db, disease_files, FakeDiscovery(empty=True), FakeGenerator()
    ).process_next()

    assert q.enqueue_selectors(request().items, trigger_type="PARENT") == []
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 1
    assert q.regenerate_topic(request().items[0]).created is True
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 2


def test_restart_recovery_makes_interrupted_job_retryable(db):
    q = queue(db)
    job_id = q.enqueue_selectors(request().items)[0]
    repository = AutoMedicalKnowledgeRepository(db)
    assert repository.claim_next_job(now=NOW, max_retries=3) == job_id
    assert db.get(AutoMedicalKnowledgeJob, job_id).status == "SEARCHING"
    assert repository.recover_interrupted_jobs(now=NOW) == 1
    db.commit()
    recovered = db.get(AutoMedicalKnowledgeJob, job_id)
    assert recovered.status == "FAILED"
    assert recovered.next_retry_at == NOW
    assert repository.claim_next_job(now=NOW, max_retries=3) == job_id


def test_default_persisted_runtime_state_is_off(db):
    settings = AutoMedicalKnowledgeRepository(db).get_settings()
    db.commit()
    assert settings.enabled is False


def test_admin_runtime_toggle_persists_and_singleton_remains_unique(db):
    q = queue(db, enabled=False)
    service = AutoMedicalKnowledgeAdminService(db, queue_service=q)
    assert service.update_settings(enabled=True).enabled is True
    db.expire_all()
    assert AutoMedicalKnowledgeRepository(db).get_settings().enabled is True
    assert service.update_settings(enabled=False).enabled is False
    db.expire_all()
    assert AutoMedicalKnowledgeRepository(db).get_settings().enabled is False
    from app.medical_knowledge_models import AutoMedicalKnowledgeSetting
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeSetting)) == 1


def test_auto_runtime_enable_e2e_without_restart(db):
    q = queue(db, enabled=False)
    assert parent(db, q).read_batch(request()).items == []
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 0

    AutoMedicalKnowledgeAdminService(db, queue_service=q).update_settings(enabled=True)
    assert parent(db, q).read_batch(request()).items == []
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 1

    AutoMedicalKnowledgeAdminService(db, queue_service=q).update_settings(enabled=False)
    other = PublishedMedicalKnowledgeBatchRequest(
        items=[{"disease_group_id": "5", "weather_factor": "humidity"}]
    )
    assert parent(db, q).read_batch(other).items == []
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 1


def test_auto_runtime_pause_resume_e2e(db, disease_files):
    q = queue(db, enabled=True)
    job_id = q.enqueue_selectors(request().items)[0]
    service = AutoMedicalKnowledgeAdminService(db, queue_service=q)
    service.update_settings(enabled=False)
    discovery = FakeDiscovery()
    generator = FakeGenerator()
    worker = processor(db, disease_files, discovery, generator)

    assert worker.process_next() is None
    assert db.get(AutoMedicalKnowledgeJob, job_id).status == "QUEUED"
    assert discovery.calls == generator.calls == 0

    service.update_settings(enabled=True)
    assert worker.process_next() == job_id
    assert db.get(AutoMedicalKnowledgeJob, job_id).status == "READY"
    assert discovery.calls == generator.calls == 1


def test_inflight_job_finishes_after_off_and_following_job_stays_queued(
    db, disease_files
):
    q = queue(db, enabled=True)
    second_request = PublishedMedicalKnowledgeBatchRequest(
        items=[{"disease_group_id": "5", "weather_factor": "humidity"}]
    )
    first_id = q.enqueue_selectors(request().items)[0]
    second_id = q.enqueue_selectors(second_request.items)[0]
    repository = AutoMedicalKnowledgeRepository(db)
    assert repository.claim_next_job(now=NOW, max_retries=3) == first_id

    AutoMedicalKnowledgeAdminService(db, queue_service=q).update_settings(enabled=False)
    worker = processor(db, disease_files, FakeDiscovery(), FakeGenerator())
    worker._process(first_id)

    assert db.get(AutoMedicalKnowledgeJob, first_id).status == "READY"
    assert worker.process_next() is None
    assert db.get(AutoMedicalKnowledgeJob, second_id).status == "QUEUED"


def test_reviewed_while_auto_disabled_e2e(db):
    q = queue(db, enabled=False)
    topic = MedicalKnowledgeTopic(
        disease_group_id="5", factor_type="WEATHER", factor_key="precipitation",
        factor_value=None, weather_factor="precipitation",
    )
    source = MedicalEvidenceSource(
        source_type="PUBMED", pmid="40777777", title="Reviewed source",
        abstract_text="Direct pediatric evidence in children.", raw_metadata_json={},
    )
    revision = MedicalKnowledgeRevision(
        topic=topic, revision_number=1, evidence_level="SUPPORTED",
        evidence_scope="PARTIAL_GROUP", short_explanation_vi="Reviewed short.",
        detailed_explanation_vi="Reviewed detail.", limitations_vi="Reviewed limits.",
        status="APPROVED", parent_display_allowed=True, generated_by_llm=False,
    )
    db.add_all([topic, source, revision])
    db.flush()
    db.add(MedicalRevisionSource(
        revision_id=revision.id, source_id=source.id, source_role="PRIMARY", sort_order=0,
        relevance_note="DIRECT: reviewed", population_relevance="PEDIATRIC_DIRECT",
        population_note="Direct child population.",
    ))
    topic.published_revision_id = revision.id
    db.commit()

    result = parent(db, q).read_batch(request())
    assert [item.knowledge_type for item in result.items] == ["REVIEWED"]
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 0


def test_reviewed_tier_one_lookup_is_unaffected_by_auto_provider_cooldown(db):
    q = queue(db, enabled=True)
    topic = MedicalKnowledgeTopic(
        disease_group_id="5", factor_type="WEATHER", factor_key="precipitation",
        factor_value=None, weather_factor="precipitation",
    )
    source = MedicalEvidenceSource(
        source_type="PUBMED", pmid="40777778", title="Reviewed cooldown source",
        abstract_text="Direct pediatric evidence in children.", raw_metadata_json={},
    )
    revision = MedicalKnowledgeRevision(
        topic=topic, revision_number=1, evidence_level="SUPPORTED",
        evidence_scope="PARTIAL_GROUP", short_explanation_vi="Reviewed short.",
        detailed_explanation_vi="Reviewed detail.", limitations_vi="Reviewed limits.",
        status="APPROVED", parent_display_allowed=True, generated_by_llm=False,
    )
    db.add_all([topic, source, revision])
    db.flush()
    db.add(MedicalRevisionSource(
        revision_id=revision.id, source_id=source.id, source_role="PRIMARY", sort_order=0,
        relevance_note="DIRECT: reviewed", population_relevance="PEDIATRIC_DIRECT",
        population_note="Direct child population.",
    ))
    topic.published_revision_id = revision.id
    AutoMedicalKnowledgeRepository(db).set_provider_cooldown(
        "groq",
        cooldown_until=NOW + timedelta(minutes=5),
        reason="LLM_RATE_LIMITED",
        now=NOW,
    )
    db.commit()

    result = parent(db, q).read_batch(request())
    assert [item.knowledge_type for item in result.items] == ["REVIEWED"]
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 0


def test_runtime_setting_read_failure_fails_closed(db, monkeypatch):
    q = queue(db, enabled=True)
    monkeypatch.setattr(
        q.repository,
        "is_runtime_enabled",
        lambda: (_ for _ in ()).throw(SQLAlchemyError("unavailable")),
    )
    assert q.enqueue_selectors(request().items) == []
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == 0


def test_worker_off_is_idle_before_provider_construction(db, monkeypatch):
    queue(db, enabled=False)
    from app.services import auto_medical_knowledge_worker as worker_module

    monkeypatch.setattr(worker_module, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(
        worker_module,
        "create_medical_knowledge_draft_generator",
        lambda **_kwargs: pytest.fail("provider must not be constructed while OFF"),
    )
    assert worker_module.process_auto_medical_knowledge_once() is False


def test_worker_cooldown_is_idle_before_provider_construction(db, monkeypatch):
    queue(db, enabled=True)
    AutoMedicalKnowledgeRepository(db).set_provider_cooldown(
        "groq",
        cooldown_until=datetime.utcnow() + timedelta(minutes=5),
        reason="LLM_RATE_LIMITED",
        now=datetime.utcnow(),
    )
    db.commit()
    from app.services import auto_medical_knowledge_worker as worker_module

    monkeypatch.setattr(worker_module, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(worker_module, "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "groq")
    monkeypatch.setattr(
        worker_module,
        "create_medical_knowledge_draft_generator",
        lambda **_kwargs: pytest.fail("provider must not be constructed during cooldown"),
    )
    assert worker_module.process_auto_medical_knowledge_once() is False


def test_parent_setting_read_failure_omits_auto_without_exception(db, monkeypatch):
    service = PublishedMedicalKnowledgeReadService(db, auto_queue=queue(db, enabled=True))
    monkeypatch.setattr(
        service.auto_repository,
        "get_settings",
        lambda: (_ for _ in ()).throw(SQLAlchemyError("unavailable")),
    )
    assert service.read_batch(request()).items == []


def test_runtime_off_does_not_override_display_mode_or_revision_visibility(
    db, disease_files
):
    q, _discovery, _generator = generate_ready_auto(db, disease_files)
    enable_fallback(db)
    AutoMedicalKnowledgeAdminService(db, queue_service=q).update_settings(enabled=False)
    result = parent(db, q).read_batch(request())
    assert [item.knowledge_type for item in result.items] == ["AUTO"]


def test_supported_with_all_not_supportive_is_rejected_as_inconsistent(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(
        db, disease_files, FakeDiscovery(), NotSupportiveGenerator()
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    diagnostics = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().jobs[0].diagnostics
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_EVIDENCE_LEVEL_INCONSISTENT"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0
    assert diagnostics is not None
    assert diagnostics.failure.code == "AUTO_OUTPUT_EVIDENCE_LEVEL_INCONSISTENT"


def test_structural_retry_occurs_exactly_once_and_can_reach_ready(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = StructuralThenValidGenerator()
    processor(db, disease_files, FakeDiscovery(), generator).process_next()
    assert generator.calls == 2
    assert db.scalar(select(AutoMedicalKnowledgeJob)).status == "READY"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 1


def test_structural_normalization_e2e_fenced_json_reaches_ready(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = FencedJsonGenerator()
    processor(db, disease_files, FakeDiscovery(), generator).process_next()
    assert generator.calls == 1
    assert db.scalar(select(AutoMedicalKnowledgeJob)).status == "READY"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 1


def test_auto_groq_v2_envelope_e2e_reaches_ready(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator, calls = groq_auto_generator(
        groq_completion(json.dumps(groq_auto_proposal()))
    )
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    assert len(calls) == 1
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert db.scalar(select(AutoMedicalKnowledgeJob)).status == "READY"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 1
    generator.client.close()


def test_auto_groq_empty_content_e2e_has_specific_failure_and_no_revision(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator, calls = groq_auto_generator(groq_completion(None))
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    diagnostics = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().jobs[0].diagnostics.failure
    assert len(calls) == 1
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_PROVIDER_CONTENT_EMPTY"
    assert diagnostics.provider == "groq"
    assert diagnostics.http_status == 200
    assert diagnostics.provider_stage == "content_empty"
    assert diagnostics.content_present is False
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0
    generator.client.close()


def test_auto_groq_invalid_json_classification_e2e_is_structural_not_envelope(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator, calls = groq_auto_generator(groq_completion("not-json"))
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert len(calls) == 2
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_JSON_INVALID"
    assert job.last_error_code != "AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0
    generator.client.close()


def test_auto_groq_v2_numeric_contract_e2e_reaches_ready(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    prose = "Nghiên cứu gồm 5.087 trẻ em nhập viện và ghi nhận mối liên hệ."
    value = groq_auto_proposal(
        detailed=prose,
        numeric_claims=[{
            "value_text": "5087",
            "claim_kind": "COUNT",
            "unit": "children",
            "source_id": 1,
            "supporting_text": "included 5087 hospitalized children",
        }],
    )
    generator, calls = groq_auto_generator(groq_completion(json.dumps(value)))
    processor(db, disease_files, CountEvidenceDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    claim = db.scalar(select(AutoMedicalKnowledgeNumericClaim))
    assert len(calls) == 1
    assert job.status == "READY", job.last_error_code
    assert claim.value_text == "5087"
    assert claim.support_sha256
    generator.client.close()


def test_auto_groq_contract_repair_reuses_same_v2_strict_schema_offline(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)

    def response(call_number):
        proposal = groq_auto_proposal(
            detailed=(
                "The pediatric study used 3 groups and reported an association."
                if call_number == 1
                else "The pediatric study reported an association at group level."
            )
        )
        return groq_completion(json.dumps(proposal))

    generator, calls = groq_auto_generator(response)
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert job.status == "READY", job.last_error_code
    assert len(calls) == 2
    assert calls[0]["response_format"] == calls[1]["response_format"]
    assert calls[1]["response_format"]["type"] == "json_schema"
    assert "AUTO_MEDICAL_KNOWLEDGE_V2_COMPLETE_CONTRACT_REPAIR" in (
        calls[1]["messages"][1]["content"]
    )
    generator.client.close()


def test_auto_groq_contract_repair_declares_supported_claim_e2e(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = (
        "A pediatric study reported an association; participants were divided "
        "into 3 groups for analysis."
    )
    prose = "The pediatric study divided participants into 3 groups and reported an association."

    def response(call_number):
        value = groq_auto_proposal(
            detailed=prose,
            numeric_claims=([] if call_number == 1 else [{
                "value_text": "3",
                "claim_kind": "COUNT",
                "unit": "groups",
                "source_id": 1,
                "supporting_text": "participants were divided into 3 groups",
            }]),
        )
        return groq_completion(json.dumps(value))

    generator, calls = groq_auto_generator(response)
    processor(
        db, disease_files, YearRangeEvidenceDiscovery(evidence), generator
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    claim = db.scalar(select(AutoMedicalKnowledgeNumericClaim))
    assert job.status == "READY", job.last_error_code
    assert len(calls) == 2
    assert calls[0]["response_format"] == calls[1]["response_format"]
    assert claim.value_text == "3"
    assert claim.source_id == 1
    assert claim.support_sha256
    generator.client.close()


def test_auto_groq_repair_http_400_uses_safe_fallback_without_error_leak(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)

    def response(call_number):
        if call_number == 1:
            return groq_completion(json.dumps(groq_auto_proposal(
                detailed="The pediatric study used 3 groups and reported an association."
            )))
        return httpx.Response(400, json={"error": {
            "code": "json_validate_failed",
            "type": "invalid_request_error",
            "message": "raw provider detail",
            "failed_generation": "raw provider output",
        }})

    generator, calls = groq_auto_generator(response)
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    overview = AutoMedicalKnowledgeAdminService(db, queue_service=q).overview()
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    persisted = json.dumps(
        [row.metadata_json for row in AutoMedicalKnowledgeRepository(db).get_discoveries(job.id)]
    )
    assert len(calls) == 2
    assert job.status == "READY"
    assert job.last_error_code is None
    assert revision.generation_mode == "SAFE_FALLBACK"
    assert revision.fallback_reason_code == "REPAIR_PROVIDER_FAILURE"
    assert overview.revisions[0].diagnostics.contract_repair_result == "SAFE_FALLBACK"
    assert "raw provider detail" not in persisted
    assert "raw provider output" not in persisted
    assert "3 groups" not in revision.detailed_explanation_vi
    generator.client.close()


def test_auto_groq_initial_http_400_has_call_one_diagnostics_and_no_repair(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator, calls = groq_auto_generator(httpx.Response(400, json={"error": {
        "code": "invalid_request",
        "type": "invalid_request_error",
    }}))
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    failure = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().jobs[0].diagnostics.failure
    assert len(calls) == 1
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED"
    assert failure.call_purpose == "INITIAL"
    assert failure.generation_call_number == 1
    assert failure.http_status == 400
    assert failure.provider_error_category == "invalid_request"
    assert failure.contract_repair_attempted is False
    assert failure.contract_repair_calls == 0
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0
    generator.client.close()


def test_auto_groq_provider_vs_safety_e2e_still_fails_closed(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    value = groq_auto_proposal(detailed="Mưa gây ra bệnh ở trẻ em.")
    generator, calls = groq_auto_generator(groq_completion(json.dumps(value)))
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert len(calls) == 1
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_CAUSAL_OVERCLAIM"
    assert job.last_error_code != "AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0
    generator.client.close()


def test_semantic_safety_failure_is_never_automatically_retried(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = RiskyGenerator("Rain causes disease in children: gây ra.")
    processor(db, disease_files, FakeDiscovery(), generator).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert generator.calls == 1
    assert job.last_error_code == "AUTO_OUTPUT_CAUSAL_OVERCLAIM"
    assert job.next_retry_at is None


def test_contract_repair_policy_is_centralized_and_fail_closed():
    assert MAX_AUTO_CONTRACT_REPAIR_ATTEMPTS == 1
    assert MAX_AUTO_STRICT_GENERATION_CALLS == 2
    assert MAX_AUTO_GENERATION_CALLS == 3
    assert AUTO_OUTPUT_REPAIRABLE_FAILURE_CODES == {
        "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH",
        "AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED",
        "AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED",
        "AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE",
    }
    for code in AUTO_OUTPUT_REPAIRABLE_FAILURE_CODES:
        assert is_auto_output_repairable(code) is True
    for code in (
        "AUTO_OUTPUT_CAUSAL_OVERCLAIM",
        "AUTO_OUTPUT_UNSUPPORTED_MECHANISM",
        "AUTO_OUTPUT_PEDIATRIC_CLAIM_INVALID",
        "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH",
        "AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID",
        "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID",
        "AUTO_OUTPUT_EVIDENCE_LEVEL_INCONSISTENT",
    ):
        assert is_auto_output_repairable(code) is False


def test_contract_repair_removes_unnecessary_number_and_persists_only_final(
    db, disease_files
):
    q = queue(db)
    job_id = q.enqueue_selectors(request().items)[0]
    discovery = FakeDiscovery()
    generator = ContractRepairGenerator(
        initial_text="RAW_INTERMEDIATE_SENTINEL: the study used 3 groups and reported an association.",
        repaired_text="The pediatric study reported an association at group level.",
    )
    processor(db, disease_files, discovery, generator).process_next()

    job = db.get(AutoMedicalKnowledgeJob, job_id)
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    rows = AutoMedicalKnowledgeRepository(db).get_discoveries(job_id)
    diagnostic = next(
        row.metadata_json for row in rows
        if row.reason_code == "GENERATION_DIAGNOSTIC"
    )
    persisted_metadata = json.dumps(
        [row.metadata_json for row in rows], ensure_ascii=False
    )
    admin_diagnostic = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().jobs[0].diagnostics

    assert job.status == "READY"
    assert generator.calls == MAX_AUTO_STRICT_GENERATION_CALLS == 2
    assert discovery.calls == 1
    assert len(generator.contexts) == 2
    assert generator.contexts[0].model_dump() == generator.contexts[1].model_dump()
    assert len(generator.repair_instructions) == 1
    repair_payload = json.loads(generator.repair_instructions[0])
    repair = repair_payload["contract_repair"]
    assert repair["safe_contract_violation"]["failure_code"] == (
        "AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED"
    )
    assert repair["selected_source_ids"] == [1]
    assert isinstance(repair["previous_proposal_json"], str)
    assert json.loads(repair["previous_proposal_json"])["numeric_claims"] == []
    assert repair_payload["trusted_selected_evidence"] == [
        generator.contexts[0].sources[0].model_dump()
    ]
    assert revision.detailed_explanation_vi == generator.repaired_text
    assert revision.generation_mode == "AI_FULL"
    assert revision.fallback_reason_code is None
    assert db.scalar(
        select(func.count()).select_from(AutoMedicalKnowledgeNumericClaim)
    ) == 0
    assert "RAW_INTERMEDIATE_SENTINEL" not in persisted_metadata
    assert diagnostic["contract_repair_result"] == "SUCCESS"
    assert diagnostic["contract_repair_calls"] == 1
    assert admin_diagnostic.contract_repair_attempted is True
    assert admin_diagnostic.contract_repair_result == "SUCCESS"


def test_contract_repair_declares_supported_group_count(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = (
        "A pediatric study reported an association; participants were divided "
        "into 3 groups for analysis."
    )
    prose = "The pediatric study divided participants into 3 groups and reported an association."
    generator = ContractRepairGenerator(
        initial_text=prose,
        repaired_text=prose,
        repaired_claims=[{
            "value_text": "3",
            "claim_kind": "COUNT",
            "unit": "groups",
            "source_id": 1,
            "supporting_text": "participants were divided into 3 groups",
        }],
    )
    processor(
        db,
        disease_files,
        YearRangeEvidenceDiscovery(evidence),
        generator,
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    claim = db.scalar(select(AutoMedicalKnowledgeNumericClaim))
    assert job.status == "READY", job.last_error_code
    assert generator.calls == 2
    assert claim.claim_kind == "COUNT"
    assert claim.value_text == "3"
    assert claim.source_id == 1
    assert claim.support_sha256


@pytest.mark.parametrize(
    ("repair_claim", "expected_code"),
    [
        (
            {
                "value_text": "3",
                "claim_kind": "COUNT",
                "unit": "groups",
                "source_id": 999,
                "supporting_text": "participants were divided into 3 groups",
            },
            "AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID",
        ),
        (
            {
                "value_text": "3",
                "claim_kind": "COUNT",
                "unit": "groups",
                "source_id": 1,
                "supporting_text": "participants were divided into 3 imaginary groups",
            },
            "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH",
        ),
    ],
)
def test_contract_repair_invalid_provenance_fails_without_revision(
    db, disease_files, repair_claim, expected_code
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = (
        "A pediatric study reported an association; participants were divided "
        "into 3 groups for analysis."
    )
    prose = "The pediatric study divided participants into 3 groups and reported an association."
    generator = ContractRepairGenerator(
        initial_text=prose,
        repaired_text=prose,
        repaired_claims=[repair_claim],
    )
    processor(
        db, disease_files, YearRangeEvidenceDiscovery(evidence), generator
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    failure = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().jobs[0].diagnostics.failure
    assert generator.calls == 2
    assert job.status == "FAILED"
    assert job.last_error_code == expected_code
    assert failure.contract_repair_attempted is True
    assert failure.contract_repair_calls == 1
    assert failure.contract_repair_result == "FAILED"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_contract_repair_still_undeclared_falls_back_at_two_calls(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    prose = "The pediatric study used 3 groups and reported an association."
    generator = ContractRepairGenerator(initial_text=prose, repaired_text=prose)
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert generator.calls == 2
    assert job.status == "READY"
    assert job.last_error_code is None
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert revision.generation_mode == "SAFE_FALLBACK"
    assert revision.fallback_reason_code == "CONTRACT_REPAIR_EXHAUSTED"
    assert "3 groups" not in revision.detailed_explanation_vi
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeNumericClaim)) == 0


def test_shared_budget_prevents_structural_retry_plus_contract_third_call(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = StructuralThenContractInvalidGenerator()
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert generator.calls == MAX_AUTO_STRICT_GENERATION_CALLS == 2
    assert job.status == "READY"
    assert job.last_error_code is None
    assert revision.generation_mode == "SAFE_FALLBACK"
    assert revision.fallback_reason_code == "CONTRACT_REPAIR_EXHAUSTED"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 1


def test_duplicate_and_unused_declarations_each_get_only_one_repair(db, disease_files):
    support = "participants were divided into 3 groups"
    claim = {
        "value_text": "3",
        "claim_kind": "COUNT",
        "unit": "groups",
        "source_id": 1,
        "supporting_text": support,
    }
    evidence = f"A pediatric study reported an association; {support} for analysis."
    scenarios = (
        ("The pediatric study used 3 groups.", [claim, claim]),
        ("The pediatric study reported an association.", [claim]),
    )
    for initial_text, initial_claims in scenarios:
        local_db = db
        q = queue(local_db)
        job_id = q.enqueue_selectors(request().items, force=True)[0]
        generator = ContractRepairGenerator(
            initial_text=initial_text,
            repaired_text="The pediatric study reported an association.",
            initial_claims=initial_claims,
        )
        processor(
            local_db,
            disease_files,
            YearRangeEvidenceDiscovery(evidence),
            generator,
        ).process_next()
        assert local_db.get(AutoMedicalKnowledgeJob, job_id).status == "READY"
        assert generator.calls == 2


def test_contract_repair_new_undeclared_number_uses_number_free_fallback(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = (
        "A pediatric study reported an association; participants were divided "
        "into 3 groups for analysis."
    )
    generator = ContractRepairGenerator(
        initial_text="The pediatric study reported an association.",
        repaired_text="The pediatric study used 4 groups and reported an association.",
        initial_claims=[{
            "value_text": "3",
            "claim_kind": "COUNT",
            "unit": "groups",
            "source_id": 1,
            "supporting_text": "participants were divided into 3 groups",
        }],
    )
    processor(
        db, disease_files, YearRangeEvidenceDiscovery(evidence), generator
    ).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert generator.calls == 2
    assert job.status == "READY"
    assert job.last_error_code is None
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert revision.generation_mode == "SAFE_FALLBACK"
    assert "4 groups" not in revision.detailed_explanation_vi
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeNumericClaim)) == 0


def test_contract_repair_unsupported_27_percent_stays_failed_closed(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = ContractRepairGenerator(
        initial_text="The pediatric study reported a 27% increase.",
        repaired_text="The pediatric study reported a 27% increase.",
        repaired_claims=[{
            "value_text": "27",
            "claim_kind": "PERCENTAGE",
            "unit": "%",
            "source_id": 1,
            "supporting_text": "the study reported a 27% increase",
        }],
    )
    processor(db, disease_files, FakeDiscovery(), generator).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert generator.calls == 2
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_contract_repair_runs_full_semantic_validation_again(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = ContractRepairGenerator(
        initial_text="The pediatric study used 3 groups and reported an association.",
        repaired_text="Rainfall g\u00e2y ra gastroenteritis in children.",
    )
    processor(db, disease_files, FakeDiscovery(), generator).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert generator.calls == 2
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_CAUSAL_OVERCLAIM"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_contract_repair_rate_limit_uses_existing_cooldown_and_backoff(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = ContractRepairGenerator(
        initial_text="The pediatric study used 3 groups and reported an association.",
        repaired_text="unused",
        repair_error=DraftGeneratorRateLimitError(
            "provider detail must not be persisted", retry_after_seconds=120
        ),
    )
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        generator,
        provider_name="groq",
        cooldown_seconds=60,
        retry_delay_seconds=30,
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    cooldown = db.get(AutoMedicalKnowledgeProviderCooldown, "GROQ")
    failure = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().jobs[0].diagnostics.failure
    assert generator.calls == 2
    assert job.status == "FAILED"
    assert job.last_error_code == "LLM_RATE_LIMITED"
    assert job.next_retry_at == NOW + timedelta(seconds=120)
    assert cooldown.cooldown_until == NOW + timedelta(seconds=120)
    assert failure.contract_repair_result == "RATE_LIMITED"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_contract_repair_does_not_bypass_concurrently_active_provider_cooldown(
    db, disease_files
):
    class CooldownAfterInitialGenerator(ContractRepairGenerator):
        def generate(self, context, **kwargs):
            proposal = super().generate(context, **kwargs)
            if kwargs.get("user_input_override") is None:
                AutoMedicalKnowledgeRepository(db).set_provider_cooldown(
                    "GROQ",
                    cooldown_until=NOW + timedelta(seconds=90),
                    reason="LLM_RATE_LIMITED",
                    now=NOW,
                )
                db.commit()
            return proposal

    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = CooldownAfterInitialGenerator(
        initial_text="The pediatric study used 3 groups and reported an association.",
        repaired_text="The pediatric study reported an association.",
    )
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        generator,
        provider_name="groq",
        retry_delay_seconds=30,
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    failure = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().jobs[0].diagnostics.failure
    assert generator.calls == 1
    assert job.status == "FAILED"
    assert job.last_error_code == "LLM_RATE_LIMITED"
    assert job.next_retry_at == NOW + timedelta(seconds=90)
    assert failure.contract_repair_attempted is True
    assert failure.contract_repair_calls == 0
    assert failure.contract_repair_result == "RATE_LIMITED"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Mưa gây ra bệnh.", "AUTO_OUTPUT_CAUSAL_OVERCLAIM"),
        ("Độ ẩm làm suy yếu miễn dịch.", "AUTO_OUTPUT_UNSUPPORTED_MECHANISM"),
        ("Con bạn sẽ mắc bệnh.", "AUTO_OUTPUT_PERSONALIZED_LANGUAGE"),
    ],
)
def test_precise_safety_code_and_safe_admin_detail(db, disease_files, text, code):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(db, disease_files, FakeDiscovery(), RiskyGenerator(text)).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    diagnostics = AutoMedicalKnowledgeAdminService(db, queue_service=q).overview().jobs[0].diagnostics
    assert job.last_error_code == code
    assert diagnostics.failure.code == code
    assert diagnostics.failure.field == "detailed_explanation_vi"
    assert "provider detail" not in diagnostics.failure.safe_detail


def test_rate_limit_keeps_existing_queue_backoff(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = RateLimitedGenerator()
    processor(db, disease_files, FakeDiscovery(), generator).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert generator.calls == 1
    assert job.last_error_code == "LLM_RATE_LIMITED"
    assert job.next_retry_at == NOW + timedelta(seconds=60)


def test_new_generic_provider_output_does_not_collapse_to_legacy_code(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(db, disease_files, FakeDiscovery(), GenericOutputGenerator()).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert job.last_error_code == "AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID"
    assert job.last_error_code != "LLM_INVALID_RESPONSE"
    assert classify_auto_failure(
        DraftGeneratorOutputError("historical"), new_pipeline=True
    ) == "AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID"


def test_historical_generic_error_remains_readable_and_is_marked_legacy(db):
    q = queue(db)
    job_id = q.enqueue_selectors(request().items)[0]
    job = db.get(AutoMedicalKnowledgeJob, job_id)
    job.status = "FAILED"
    job.attempt_count = 1
    job.last_error_code = "LLM_INVALID_RESPONSE"
    db.commit()
    response = AutoMedicalKnowledgeAdminService(db, queue_service=q).overview().jobs[0]
    assert response.last_error_code == "LLM_INVALID_RESPONSE"
    assert response.legacy is True


def test_safe_numeric_normalization_and_fail_closed_policy():
    metadata = NumericMetadata(
        pmids=("40123456",),
        publication_years=(2025,),
        source_ids=(7,),
        dois=("10.1000/2025.77",),
        disease_group_ids=("169",),
    )

    def issue(output, evidence="", context=""):
        return find_unsupported_numeric_claim(
            {"detailed_explanation_vi": output},
            [evidence],
            context_text=context,
            metadata=metadata,
        )

    assert issue("Tỷ lệ 12,5%.", "The rate was 12.5%.") is None
    assert issue("Nhiệt độ -2,5 °C.", "Temperature was -2.5 C.") is None
    assert issue("Có 5 087 trẻ em.", "There were 5087 hospitalized children.") is None
    assert issue("Có 5.087 trẻ em.", "There were 5087 hospitalized children.") is None
    assert issue("Khoảng −5–−2 °C.", "The observed range was -5 to -2 C.") is None
    assert issue("Nhóm 1–5 tuổi.", "No statistic.", "1-5 tuổi") is None

    ambiguous = issue("Giá trị là 5.087.", "There were 5087 hospitalized children.")
    assert ambiguous is not None and ambiguous.value == "5.087"
    unsupported = issue("Nguy cơ tăng 42%.", "The rate was 12.5%.")
    assert unsupported is not None and unsupported.value == "42"
    metadata_claim = issue(
        "PMID 40123456, xuất bản năm 2025, nguồn 7 và [7], DOI 10.1000/2025.77, nhóm bệnh 169.",
        "No statistic.",
    )
    assert metadata_claim is None
    fake_pmid_statistic = issue("Nguy cơ là 40123456%.", "No statistic.")
    assert fake_pmid_statistic is not None


def test_numeric_validation_never_rewrites_output_prose():
    prose = "Có 5.087 trẻ em trong nghiên cứu."
    before = prose[:]
    assert find_unsupported_numeric_claim(
        {"detailed_explanation_vi": prose},
        ["There were 5087 hospitalized children."],
    ) is None
    assert prose == before


@pytest.mark.parametrize(
    ("evidence", "output"),
    [
        ("The study period was 2004–2009.", "Giai đoạn 2004-2009."),
        ("Children were enrolled from 2004 to 2009.", "2004–2009"),
        ("Data were collected between 2004 and 2009.", "Giai đoạn 2004—2009."),
        (
            "Children were enrolled between January 2004 and December 2009.",
            "Giai đoạn 2004 - 2009.",
        ),
        ("The study period was 2004 Jan – 2009 Dec.", "During 2004—2009."),
    ],
)
def test_supported_temporal_year_range_formats_are_equivalent(evidence, output):
    assert find_unsupported_numeric_claim(
        {"detailed_explanation_vi": output}, [evidence]
    ) is None


@pytest.mark.parametrize(
    ("evidence", "output"),
    [
        ("The study period was 2004–2009.", "Giai đoạn 2004–2010."),
        ("Published in 2004; an unrelated result mentions 2009.", "Study period 2004–2009."),
        ("Children were aged 4–18 years.", "Study period 2004–2009."),
        ("The risk was 2–4%.", "2004–2009"),
        ("No calendar period was reported.", "Study period 2004–2009."),
        ("The study period was 2010–2012.", "Study period 2004–2009."),
        ("Risk was 2004–2009%.", "Study period 2004–2009."),
        ("The study period was 2004–2009.", "Risk was 2004–2009%."),
    ],
)
def test_unsupported_or_non_temporal_year_ranges_fail_closed(evidence, output):
    issue = find_unsupported_numeric_claim(
        {"detailed_explanation_vi": output}, [evidence]
    )
    assert issue is not None
    normalized = issue.value.replace("–", "-").replace("—", "-")
    assert normalized in {"2004-2009", "2004-2010"}


def test_publication_year_metadata_cannot_support_an_invented_study_period():
    issue = find_unsupported_numeric_claim(
        {"detailed_explanation_vi": "Study period 2004–2009."},
        ["The article was published in 2004. Another statement mentions 2009."],
        metadata=NumericMetadata(publication_years=(2004,)),
    )
    assert issue is not None
    assert issue.value == "2004–2009"


def test_numeric_normalization_e2e_reaches_ready_without_rewriting(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    prose = "Nghiên cứu gồm 5.087 trẻ em nhập viện và ghi nhận mối liên hệ."
    processor(
        db,
        disease_files,
        CountEvidenceDiscovery(),
        RiskyGenerator(prose, numeric_claims=[{
            "value_text": "5087",
            "claim_kind": "COUNT",
            "unit": "children",
            "source_id": 1,
            "supporting_text": "included 5087 hospitalized children",
        }]),
    ).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert job.status == "READY", job.last_error_code
    assert revision.detailed_explanation_vi == prose
    persisted_claim = db.scalar(select(AutoMedicalKnowledgeNumericClaim))
    assert persisted_claim.claim_kind == "COUNT"
    assert persisted_claim.value_text == "5087"
    assert persisted_claim.evidence_content_id is not None
    assert persisted_claim.support_end > persisted_claim.support_start


def test_numeric_hallucination_guard_e2e_discards_failed_prose_for_fallback(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        RiskyGenerator("Nghiên cứu ghi nhận 42% trẻ em."),
    ).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert job.status == "READY"
    assert job.last_error_code is None
    assert revision.generation_mode == "SAFE_FALLBACK"
    assert "42%" not in revision.detailed_explanation_vi
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeNumericClaim)) == 0


def test_auto_year_range_normalization_e2e_persists_ready_without_rewrite(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    prose = "Nghiên cứu theo dõi giai đoạn 2004-2009 và ghi nhận mối liên hệ."
    evidence = (
        "A pediatric study reports an association. Children were enrolled "
        "between January 2004 and December 2009."
    )
    processor(
        db,
        disease_files,
        YearRangeEvidenceDiscovery(evidence),
        RiskyGenerator(prose, numeric_claims=[{
            "value_text": "2004-2009",
            "claim_kind": "TEMPORAL_PERIOD",
            "unit": "years",
            "source_id": 1,
            "supporting_text": "between January 2004 and December 2009",
        }]),
    ).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert job.status == "READY"
    assert revision.detailed_explanation_vi == prose


def test_auto_year_range_hallucination_guard_e2e_fails_without_revision(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = (
        "A pediatric study reports an association. The study period was "
        "from 2010 to 2012."
    )
    processor(
        db,
        disease_files,
        YearRangeEvidenceDiscovery(evidence),
        RiskyGenerator(
            "Nghiên cứu theo dõi giai đoạn 2004-2009.",
            numeric_claims=[{
                "value_text": "2004-2009",
                "claim_kind": "TEMPORAL_PERIOD",
                "unit": "years",
                "source_id": 1,
                "supporting_text": "from 2010 to 2012",
            }],
        ),
    ).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_groq_cooldown_e2e_preserves_queue_and_auto_resumes(db, disease_files):
    q = queue(db)
    first_id = q.enqueue_selectors(request().items)[0]
    second_request = PublishedMedicalKnowledgeBatchRequest(
        items=[{"disease_group_id": "5", "weather_factor": "humidity"}]
    )
    second_id = q.enqueue_selectors(second_request.items)[0]
    rate_generator = RateLimitedGenerator()
    rate_worker = processor(
        db,
        disease_files,
        FakeDiscovery(),
        rate_generator,
        provider_name="groq",
        cooldown_seconds=60,
        retry_delay_seconds=600,
    )

    assert rate_worker.process_next() == first_id
    first = db.get(AutoMedicalKnowledgeJob, first_id)
    cooldown = db.get(AutoMedicalKnowledgeProviderCooldown, "GROQ")
    assert first.last_error_code == "LLM_RATE_LIMITED"
    assert first.next_retry_at == NOW + timedelta(seconds=600)
    assert cooldown.cooldown_until == NOW + timedelta(seconds=60)
    assert db.get(AutoMedicalKnowledgeJob, second_id).status == "QUEUED"
    cooldown_response = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().provider_cooldown
    assert cooldown_response is not None
    assert cooldown_response.provider == "GROQ"

    discovery = FakeDiscovery()
    generator = FakeGenerator()
    paused_worker = processor(
        db,
        disease_files,
        discovery,
        generator,
        provider_name="groq",
        cooldown_seconds=60,
    )
    assert paused_worker.process_next() is None
    assert paused_worker.process_next() is None
    assert discovery.calls == generator.calls == 0
    assert db.get(AutoMedicalKnowledgeJob, second_id).status == "QUEUED"

    resumed_worker = processor(
        db,
        disease_files,
        discovery,
        generator,
        provider_name="groq",
        cooldown_seconds=60,
        now=NOW + timedelta(seconds=61),
    )
    assert resumed_worker.process_next() == second_id
    assert db.get(AutoMedicalKnowledgeJob, second_id).status == "READY"
    assert discovery.calls == generator.calls == 1


def test_retry_after_overrides_fallback_cooldown(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        RateLimitedGenerator(retry_after_seconds=125),
        provider_name="groq",
        cooldown_seconds=60,
    ).process_next()
    cooldown = db.get(AutoMedicalKnowledgeProviderCooldown, "GROQ")
    assert cooldown.cooldown_until == NOW + timedelta(seconds=125)


def test_provider_cooldown_survives_session_restart_and_closes_claim_race(
    db, disease_files
):
    q = queue(db)
    job_id = q.enqueue_selectors(request().items)[0]
    repository = AutoMedicalKnowledgeRepository(db)
    repository.set_provider_cooldown(
        "groq",
        cooldown_until=NOW + timedelta(minutes=5),
        reason="LLM_RATE_LIMITED",
        now=NOW,
    )
    db.commit()

    with Session(db.get_bind()) as restarted_session:
        restarted = AutoMedicalKnowledgeRepository(restarted_session)
        persisted = restarted.get_active_provider_cooldown("groq", now=NOW)
        assert persisted is not None
        assert restarted.claim_next_job(
            now=NOW, max_retries=3, provider="groq"
        ) is None
    assert db.get(AutoMedicalKnowledgeJob, job_id).status == "QUEUED"


def test_parent_enqueue_remains_non_blocking_during_provider_cooldown(db):
    q = queue(db)
    AutoMedicalKnowledgeRepository(db).set_provider_cooldown(
        "groq",
        cooldown_until=NOW + timedelta(minutes=5),
        reason="LLM_RATE_LIMITED",
        now=NOW,
    )
    db.commit()
    assert q.enqueue_selectors(request().items)
    assert db.scalar(select(AutoMedicalKnowledgeJob)).status == "QUEUED"


def test_identifier_numbers_and_association_wording_are_not_false_positives(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    text = "PMID 40123456 năm 2025 ghi nhận có thể liên quan đến bệnh ở trẻ em."
    processor(db, disease_files, FakeDiscovery(), RiskyGenerator(text)).process_next()
    assert db.scalar(select(AutoMedicalKnowledgeJob)).status == "READY"


def test_age_bucket_number_from_topic_context_is_not_a_false_positive(db, disease_files):
    age_bucket = load_factor_values()["AGE"][0]
    age_request = PublishedMedicalKnowledgeBatchRequest(items=[{
        "disease_group_id": "5", "factor_type": "AGE",
        "factor_key": "age_group", "factor_value": age_bucket,
    }])
    q = queue(db)
    q.enqueue_selectors(age_request.items)
    text = f"Nghiên cứu ghi nhận mối liên hệ trong nhóm {age_bucket}."
    processor(db, disease_files, FakeDiscovery(), RiskyGenerator(text)).process_next()
    assert db.scalar(select(AutoMedicalKnowledgeJob)).status == "READY"


def test_pediatric_direct_label_without_pediatric_evidence_has_specific_code(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(db, disease_files, AdultEvidenceDiscovery(), FakeGenerator()).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert job.status == "INSUFFICIENT"
    assert job.last_error_code is None
    diagnostic = AutoMedicalKnowledgeAdminService(
        db, queue_service=q
    ).overview().jobs[0].diagnostics
    assert diagnostic.insufficient_reason == "NO_PEDIATRIC_RELEVANT_SOURCE"
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert revision.generation_status == "INSUFFICIENT"
    assert revision.short_explanation_vi is None


def test_unsupported_source_design_claim_has_specific_code(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(db, disease_files, FakeDiscovery(), UnsupportedSourceClaimGenerator()).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert job.last_error_code == "AUTO_OUTPUT_UNSUPPORTED_SOURCE_CLAIM"


def test_current_attempt_and_pipeline_version_are_persisted(db, disease_files):
    q = queue(db)
    first = q.enqueue_selectors(request().items)[0]
    processor(db, disease_files, FakeDiscovery(fail=True), FakeGenerator()).process_next()
    second = q.enqueue_selectors(request().items, trigger_type="ADMIN", force=True)[0]
    processor(db, disease_files, FakeDiscovery(), FakeGenerator()).process_next()
    jobs = AutoMedicalKnowledgeAdminService(db, queue_service=q).overview().jobs
    assert [job.id for job in jobs[:2]] == [second, first]
    assert jobs[0].is_current_attempt is True
    assert jobs[0].status == "READY"
    assert jobs[1].is_current_attempt is False
    assert jobs[0].legacy is False
    assert jobs[0].pipeline_version == "auto_medical_knowledge_v4_multi_tier"


def test_failed_attempt_history_remains_after_same_job_reaches_ready(db, disease_files):
    q = queue(db)
    job_id = q.enqueue_selectors(request().items)[0]
    processor(db, disease_files, FakeDiscovery(fail=True), FakeGenerator()).process_next()
    admin = AutoMedicalKnowledgeAdminService(db, queue_service=q)
    assert admin.retry_job(job_id) == job_id
    processor(db, disease_files, FakeDiscovery(), FakeGenerator()).process_next()
    job = admin.overview().jobs[0]
    assert job.status == "READY"
    assert job.is_current_attempt is True
    assert len(job.history) == 1
    assert job.history[0].status == "FAILED"
    assert job.history[0].failure_code == "UNKNOWN_INTERNAL_ERROR"
    assert job.history[0].legacy is False


def test_specific_technical_failure_codes_are_stable_and_safe():
    assert classify_auto_failure(AutoEvidenceSearchError("secret detail")) == "PUBMED_SEARCH_FAILED"
    assert classify_auto_failure(DraftGeneratorUnavailableError("secret detail")) == "LLM_PROVIDER_FAILED"
    assert classify_auto_failure(DraftGeneratorOutputError("raw output")) == "LLM_INVALID_RESPONSE"
    assert classify_auto_failure(SQLAlchemyError("database path")) == "PERSISTENCE_FAILED"
    assert classify_auto_failure(RuntimeError("internal path")) == "UNKNOWN_INTERNAL_ERROR"


@pytest.mark.parametrize(("role", "expected"), [("admin", 200), ("staff", 403)])
def test_runtime_toggle_api_authorization(db, role, expected):
    app = FastAPI()
    app.include_router(auto_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role)
    with TestClient(app) as client:
        response = client.patch(
            "/api/medical-knowledge/auto/settings", json={"enabled": True}
        )
    assert response.status_code == expected
    assert AutoMedicalKnowledgeRepository(db).get_settings().enabled is (role == "admin")


@pytest.mark.parametrize(("role", "expected"), [("admin", 200), ("staff", 403)])
def test_regenerate_api_requires_admin_and_returns_typed_created_state(
    db, role, expected
):
    queue(db)
    app = FastAPI()
    app.include_router(auto_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role)
    with TestClient(app) as client:
        response = client.post(
            "/api/medical-knowledge/auto/regenerate",
            json={"disease_group_id": "5", "weather_factor": "precipitation"},
        )
    assert response.status_code == expected
    if role == "admin":
        assert response.json() == {
            "ok": True,
            "job_id": 1,
            "revision_id": None,
            "topic_id": None,
            "created": True,
            "outcome": "CREATED",
            "job_status": "QUEUED",
            "message": "Đã tạo yêu cầu mới.",
        }
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeJob)) == (
        1 if role == "admin" else 0
    )


def test_public_caller_cannot_toggle_runtime(db):
    app = FastAPI()
    app.include_router(auto_router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.patch(
            "/api/medical-knowledge/auto/settings", json={"enabled": True}
        )
    assert response.status_code == 401
    assert AutoMedicalKnowledgeRepository(db).get_settings().enabled is False


@pytest.mark.parametrize(
    ("role", "expected"),
    [("admin", 200), ("staff", 200), ("parent", 403)],
)
def test_topic_visibility_api_authorization_and_strict_selector(
    db, disease_files, role, expected
):
    q, _discovery, _generator = generate_ready_auto(db, disease_files)
    actor = _visibility_actor(db, username=f"api-{role}", role=role)
    app = FastAPI()
    app.include_router(auto_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    payload = {
        "disease_group_id": "5",
        "factor_type": "WEATHER",
        "factor_key": "precipitation",
        "factor_value": None,
        "weather_factor": "precipitation",
        "hidden": True,
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/medical-knowledge/auto/topics/visibility", json=payload
        )
        extra_response = client.post(
            "/api/medical-knowledge/auto/topics/visibility",
            json={**payload, "revision_id": 999},
        )
    assert response.status_code == expected
    assert extra_response.status_code in ({422} if expected == 200 else {403})
    state = db.scalar(select(AutoMedicalKnowledgeTopicState))
    assert state.is_hidden_by_staff is (expected == 200)


def _numeric_contract(
    prose: str,
    evidence: str,
    claims=(),
    *,
    context_text: str = "",
    selected_source_id: int = 60,
):
    return validate_numeric_claim_contract(
        {
            "short_explanation_vi": "Giải thích định tính.",
            "detailed_explanation_vi": prose,
            "limitations_vi": "Bằng chứng có giới hạn.",
        },
        [
            claim if isinstance(claim, AutoNumericClaimProposal)
            else AutoNumericClaimProposal.model_validate(claim)
            for claim in claims
        ],
        [NumericEvidenceSnapshot(
            source_id=selected_source_id,
            evidence_content_id=600,
            evidence_text=evidence,
        )],
        context_text=context_text,
        metadata=NumericMetadata(source_ids=(selected_source_id,)),
    )


def _claim(value, kind, supporting_text, *, unit=None, source_id=60):
    return {
        "value_text": value,
        "claim_kind": kind,
        "unit": unit,
        "source_id": source_id,
        "supporting_text": supporting_text,
    }


def _contract_code(*args, **kwargs):
    with pytest.raises(NumericClaimContractViolation) as caught:
        _numeric_contract(*args, **kwargs)
    return caught.value


def test_numeric_contract_v2_qualitative_and_topic_context_paths_need_no_claims():
    assert _numeric_contract(
        "Nghiên cứu ghi nhận mối liên hệ ở cấp quần thể.",
        "A pediatric study reports an association.",
    ) == ()
    assert _numeric_contract(
        "Kết quả áp dụng cho trẻ 1-5 tuổi.",
        "No numeric medical statistic was reported.",
        context_text="1-5 tuổi",
    ) == ()


def test_numeric_contract_v2_supported_count_and_generic_three_group_count_pass():
    count = _numeric_contract(
        "Nghiên cứu gồm 5.087 trẻ em nhập viện.",
        "A total of 5087 hospitalized children were included.",
        [_claim(
            "5087", "COUNT", "A total of 5087 hospitalized children", unit="children"
        )],
    )
    assert count[0].claim_kind == "COUNT"
    assert count[0].evidence_content_id == 600

    groups = _numeric_contract(
        "Nghiên cứu chia thành 3 nhóm.",
        "Participants were divided into 3 groups before analysis.",
        [_claim(
            "3", "COUNT", "Participants were divided into 3 groups", unit="groups"
        )],
    )
    assert groups[0].value_text == "3"


def test_numeric_contract_v2_undeclared_and_unsupported_three_fail_closed():
    undeclared = _contract_code(
        "Nguy cơ tăng 27%.",
        "Risk increased by 27% in the selected cohort.",
    )
    assert undeclared.code == "AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED"
    assert undeclared.numeric_value == "27"

    unsupported_three = _contract_code(
        "Nghiên cứu chia thành 3 nhóm.",
        "The selected study did not report a group count.",
    )
    assert unsupported_three.code == "AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED"


def test_numeric_contract_v2_requires_exact_selected_source():
    invented = _contract_code(
        "Nguy cơ tăng 27%.",
        "Risk increased by 27%.",
        [_claim("27%", "PERCENTAGE", "Risk increased by 27%", source_id=999)],
    )
    assert invented.code == "AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID"
    assert invented.source_id == 999

    globally_existing_but_unselected = _contract_code(
        "Nguy cơ tăng 27%.",
        "Risk increased by 27%.",
        [_claim("27%", "PERCENTAGE", "Risk increased by 27%", source_id=61)],
    )
    assert globally_existing_but_unselected.code == "AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID"


def test_numeric_contract_v2_support_quote_is_normalized_but_never_paraphrased():
    verified = _numeric_contract(
        "Nghiên cứu gồm 5.087 trẻ em nhập viện.",
        "A total of 5087\n  hospitalized children were included.",
        [_claim(
            "5087", "COUNT", "A total of 5087 hospitalized children", unit="children"
        )],
    )
    assert verified[0].support_end > verified[0].support_start
    assert len(verified[0].support_sha256) == 64

    paraphrase = _contract_code(
        "Nghiên cứu gồm 5.087 trẻ em nhập viện.",
        "A total of 5087 hospitalized children were included.",
        [_claim(
            "5087", "COUNT", "The study enrolled 5087 hospitalized children", unit="children"
        )],
    )
    assert paraphrase.code == "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH"


def test_numeric_contract_v2_rejects_duplicate_and_unused_declarations():
    declaration = _claim(
        "27%", "PERCENTAGE", "Risk increased by 27%", unit="percent"
    )
    duplicate = _contract_code(
        "Nguy cơ tăng 27%.",
        "Risk increased by 27%.",
        [declaration, declaration],
    )
    assert duplicate.code == "AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE"

    unused = _contract_code(
        "Nghiên cứu ghi nhận mối liên hệ.",
        "Risk increased by 27%.",
        [declaration],
    )
    assert unused.code == "AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED"


@pytest.mark.parametrize(
    ("prose", "evidence", "claim"),
    [
        (
            "Nguy cơ tăng 27%.",
            "Risk increased by 27%.",
            _claim("27%", "PERCENTAGE", "Risk increased by 27%", unit="percent"),
        ),
        (
            "Nhiệt độ ghi nhận là 33,3\u00b0C.",
            "Temperature was 33.3\u00b0C.",
            _claim(
                "33.3\u00b0C", "MEASUREMENT", "Temperature was 33.3\u00b0C", unit="\u00b0C"
            ),
        ),
        (
            "Nghiên cứu gồm trẻ 4-18 tuổi.",
            "Children aged 4-18 years were included.",
            _claim("4-18 years", "AGE", "Children aged 4-18 years", unit="years"),
        ),
        (
            "Triệu chứng kéo dài 7 ngày.",
            "Symptoms lasted 7 days.",
            _claim("7 days", "DURATION", "Symptoms lasted 7 days", unit="days"),
        ),
        (
            "Nghiên cứu theo dõi giai đoạn 2004-2009.",
            "Children were enrolled between January 2004 and December 2009.",
            _claim(
                "2004-2009", "TEMPORAL_PERIOD",
                "between January 2004 and December 2009", unit="years"
            ),
        ),
        (
            "Nghiên cứu gồm 5.087 trẻ em.",
            "The cohort included 5087 children.",
            _claim("5087", "COUNT", "included 5087 children", unit="children"),
        ),
        (
            "Tỷ suất là 12 trên mỗi 1000 trẻ em.",
            "The incidence rate was 12 per 1000 children.",
            _claim(
                "12 per 1000", "RATE", "rate was 12 per 1000 children",
                unit="per 1000 children",
            ),
        ),
        (
            "Nguy cơ cao hơn 2 lần.",
            "Risk was 2 times higher.",
            _claim("2 times", "RATIO_OR_EFFECT", "Risk was 2 times higher", unit="times"),
        ),
    ],
)
def test_numeric_contract_v2_bounded_claim_kinds(prose, evidence, claim):
    assert len(_numeric_contract(prose, evidence, [claim])) == 1


def test_numeric_contract_v2_incompatible_kinds_and_wrong_values_do_not_cross_match():
    invalid_kind = _contract_code(
        "Nguy cơ tăng 27%.",
        "Risk increased by 27%.",
        [_claim("27%", "TEMPORAL_PERIOD", "Risk increased by 27%")],
    )
    assert invalid_kind.code == "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH"

    incompatible = _contract_code(
        "Nguy cơ là 4-18%.",
        "Children aged 4-18 years were included.",
        [_claim(
            "4-18%", "PERCENTAGE", "Children aged 4-18 years", unit="percent"
        )],
    )
    assert incompatible.code == "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID"

    wrong_count = _contract_code(
        "Nghiên cứu gồm 6000 trẻ em.",
        "A total of 5087 hospitalized children were included.",
        [_claim(
            "6000", "COUNT", "A total of 5087 hospitalized children", unit="children"
        )],
    )
    assert wrong_count.code == "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH"

    wrong_year = _contract_code(
        "Nghiên cứu theo dõi giai đoạn 2004-2010.",
        "Children were enrolled between January 2004 and December 2009.",
        [_claim(
            "2004-2010", "TEMPORAL_PERIOD",
            "between January 2004 and December 2009", unit="years"
        )],
    )
    assert wrong_year.code == "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH"


def test_numeric_kind_classifier_accepts_bare_ratio_when_evidence_and_prose_agree():
    evidence = "The study reported relative risk (RR) 1.07."
    verified = _numeric_contract(
        "Nghiên cứu ghi nhận relative risk (RR) 1.07.",
        evidence,
        [_claim(
            "1.07",
            "RATIO_OR_EFFECT",
            "relative risk (RR) 1.07",
        )],
    )
    assert verified[0].claim_kind == "RATIO_OR_EFFECT"


def test_numeric_kind_classifier_distinguishes_taxonomy_from_semantic_mismatch():
    evidence = "A 5°C increase was associated with an odds ratio of 1.07."
    taxonomy = _contract_code(
        "Nghiên cứu ghi nhận odds ratio 1.07.",
        evidence,
        [_claim(
            "1.07",
            "MEASUREMENT",
            "associated with an odds ratio of 1.07",
        )],
    )
    assert taxonomy.code == "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH"

    semantic = _contract_code(
        "Nhiệt độ được ghi nhận là 1.07°C.",
        evidence,
        [_claim(
            "1.07",
            "RATIO_OR_EFFECT",
            "associated with an odds ratio of 1.07",
        )],
    )
    assert semantic.code == "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID"

    inverse = _contract_code(
        "Nguy cơ được ghi nhận cao hơn 1.07 lần.",
        "Temperature increased by 1.07 °C.",
        [_claim(
            "1.07",
            "RATIO_OR_EFFECT",
            "Temperature increased by 1.07 °C",
        )],
    )
    assert inverse.code == "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID"

    ambiguous = _contract_code(
        "Nghiên cứu ghi nhận giá trị 1.07.",
        "The selected result was 1.07.",
        [_claim("1.07", "OTHER_NUMERIC", "result was 1.07")],
    )
    assert ambiguous.code == "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID"


def test_numeric_kind_mismatch_repairs_only_enum_and_persists_final_claim(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = "A pediatric study reported an odds ratio of 1.07."
    prose = "The pediatric study reported an odds ratio of 1.07."
    support = "reported an odds ratio of 1.07"
    generator = ContractRepairGenerator(
        initial_text=prose,
        repaired_text=prose,
        initial_claims=[_claim("1.07", "MEASUREMENT", support, source_id=1)],
        repaired_claims=[_claim("1.07", "RATIO_OR_EFFECT", support, source_id=1)],
    )
    processor(
        db, disease_files, YearRangeEvidenceDiscovery(evidence), generator
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    persisted = db.scalar(select(AutoMedicalKnowledgeNumericClaim))
    repair = json.loads(generator.repair_instructions[0])["contract_repair"]
    assert job.status == "READY", job.last_error_code
    assert generator.calls == 2
    assert persisted.claim_kind == "RATIO_OR_EFFECT"
    assert persisted.value_text == "1.07"
    assert persisted.source_id == 1
    assert repair["safe_contract_violation"]["failure_code"] == (
        "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH"
    )
    assert any("change only the flagged claim_kind" in item for item in repair["instructions"])


def test_numeric_kind_mismatch_repair_may_remove_number_and_declaration(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = "A pediatric study reported an odds ratio of 1.07."
    support = "reported an odds ratio of 1.07"
    generator = ContractRepairGenerator(
        initial_text="The pediatric study reported an odds ratio of 1.07.",
        repaired_text="The pediatric study reported an association.",
        initial_claims=[_claim("1.07", "MEASUREMENT", support, source_id=1)],
        repaired_claims=[],
    )
    processor(
        db, disease_files, YearRangeEvidenceDiscovery(evidence), generator
    ).process_next()

    assert db.scalar(select(AutoMedicalKnowledgeJob)).status == "READY"
    assert generator.calls == 2
    assert db.scalar(
        select(func.count()).select_from(AutoMedicalKnowledgeNumericClaim)
    ) == 0


def test_repeated_numeric_kind_mismatch_fails_after_two_calls_without_fallback(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = "A pediatric study reported an odds ratio of 1.07."
    support = "reported an odds ratio of 1.07"
    wrong = _claim("1.07", "MEASUREMENT", support, source_id=1)
    generator = ContractRepairGenerator(
        initial_text="The pediatric study reported an odds ratio of 1.07.",
        repaired_text="The pediatric study reported an odds ratio of 1.07.",
        initial_claims=[wrong],
        repaired_claims=[wrong],
    )
    processor(
        db, disease_files, YearRangeEvidenceDiscovery(evidence), generator
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert generator.calls == 2
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_unsupported_numeric_change_is_nonrepairable_and_uses_one_call(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = "A pediatric study reported an odds ratio of 1.07."
    generator = ContractRepairGenerator(
        initial_text="The pediatric study reported an odds ratio of 1.08.",
        repaired_text="unused",
        initial_claims=[_claim(
            "1.08",
            "RATIO_OR_EFFECT",
            "reported an odds ratio of 1.07",
            source_id=1,
        )],
    )
    processor(
        db, disease_files, YearRangeEvidenceDiscovery(evidence), generator
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert generator.calls == 1
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_semantic_kind_mismatch_e2e_fails_without_repair_or_fallback(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    evidence = "A pediatric study reported relative risk (RR) 1.07."
    generator = ContractRepairGenerator(
        initial_text="The pediatric study reported temperature 1.07°C.",
        repaired_text="unused",
        initial_claims=[_claim(
            "1.07",
            "MEASUREMENT",
            "relative risk (RR) 1.07",
            unit="°C",
            source_id=1,
        )],
    )
    processor(
        db, disease_files, YearRangeEvidenceDiscovery(evidence), generator
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert generator.calls == 1
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_v011_is_additive_idempotent_and_preserves_legacy_rows_with_fk_integrity():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql(
            "CREATE TABLE auto_medical_knowledge_revisions "
            "(id INTEGER PRIMARY KEY, prompt_version TEXT NOT NULL, marker TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE medical_evidence_sources (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE medical_evidence_contents (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO auto_medical_knowledge_revisions VALUES "
            "(7,'medical_knowledge_auto_v1','legacy-unchanged')"
        )
        connection.exec_driver_sql("INSERT INTO medical_evidence_sources VALUES (60)")
        connection.exec_driver_sql("INSERT INTO medical_evidence_contents VALUES (600)")
    upgrade_auto_numeric_claim_contract(engine)
    upgrade_auto_numeric_claim_contract(engine)
    with engine.begin() as connection:
        assert connection.exec_driver_sql(
            "SELECT prompt_version,marker FROM auto_medical_knowledge_revisions WHERE id=7"
        ).fetchone() == ("medical_knowledge_auto_v1", "legacy-unchanged")
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM auto_medical_knowledge_numeric_claims"
        ).scalar_one() == 0
        connection.exec_driver_sql(
            "INSERT INTO auto_medical_knowledge_numeric_claims "
            "(revision_id,claim_order,claim_kind,value_text,unit,source_id,"
            "evidence_content_id,support_start,support_end,support_sha256) "
            "VALUES (7,0,'COUNT','3','groups',60,600,0,8,?)",
            ("a" * 64,),
        )
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()


def test_numeric_contract_v2_qualitative_e2e_persists_zero_claims(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    processor(db, disease_files, FakeDiscovery(), FakeGenerator()).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert job.status == "READY"
    assert revision.prompt_version == "medical_knowledge_auto_v2_numeric_claims"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeNumericClaim)) == 0


def test_numeric_contract_v2_declared_hallucination_e2e_fails_without_revision(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    generator = RiskyGenerator(
        "Nghiên cứu ghi nhận nguy cơ tăng 27%.",
        numeric_claims=[_claim(
            "27%",
            "PERCENTAGE",
            "association between rainfall and gastroenteritis admissions",
            unit="percent",
            source_id=1,
        )],
    )
    processor(db, disease_files, FakeDiscovery(), generator).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert job.status == "FAILED"
    assert job.last_error_code == "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH"
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def _safe_fallback_policy_inputs(
    *,
    signals=RelevanceSignals(disease=1, factor=1, pediatric=1),
    trust_class="PUBMED",
    relevance="DIRECT",
    population="PEDIATRIC_DIRECT",
    evidence_level="SUPPORTED",
    assessed_source_id=1,
):
    source_input = DraftSourceInput(
        source_id=1,
        source_type="PUBMED",
        pmid="40123456",
        title="Pediatric evidence",
        content_kind="ABSTRACT",
        evidence_text=(
            "A pediatric study of children reports an association between "
            "rainfall and gastroenteritis."
        ),
        content_origin="NCBI_PUBMED",
        evidence_content_id=2,
    )
    context = DraftGenerationContext(
        disease_group_id="5",
        disease_group_name="Tiêu chảy - Gastroenteritis",
        report_group_code="A09",
        factor_type="WEATHER",
        factor_key="precipitation",
        factor_value=None,
        weather_factor="precipitation",
        sources=[source_input],
    )
    proposal = AutoMedicalKnowledgeDraftProposal(
        evidence_level=evidence_level,
        evidence_scope="PARTIAL_GROUP",
        short_explanation_vi="Nguồn ghi nhận mối liên hệ ở trẻ em.",
        detailed_explanation_vi="Nguồn ghi nhận mối liên hệ ở cấp độ nhóm.",
        limitations_vi="Không chứng minh quan hệ nhân quả.",
        source_assessments=[SourceAssessment(
            source_id=assessed_source_id,
            relevance=relevance,
            note_vi="Đánh giá có cấu trúc.",
            population_relevance=population,
            population_note="Đánh giá phạm vi quần thể.",
        )],
        numeric_claims=[],
    )
    selected = [(
        SimpleNamespace(id=1),
        SimpleNamespace(id=2, source_id=1),
        source_input,
        trust_class,
        signals,
    )]
    return context, selected, proposal


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"signals": RelevanceSignals(0, 1, 1)}, "DISEASE_RELEVANCE_REQUIRED"),
        ({"signals": RelevanceSignals(1, 0, 1)}, "FACTOR_RELEVANCE_REQUIRED"),
        ({"signals": RelevanceSignals(1, 1, 0)}, "PEDIATRIC_RELEVANCE_REQUIRED"),
        ({"population": "ADULT_ONLY"}, "PEDIATRIC_DIRECT_SUPPORT_REQUIRED"),
        ({"relevance": "INDIRECT"}, "DIRECT_EVIDENCE_REQUIRED"),
        ({"evidence_level": "INSUFFICIENT"}, "EVIDENCE_LEVEL_NOT_PARENT_DISPLAYABLE"),
        ({"evidence_level": "CONFLICTING"}, "EVIDENCE_LEVEL_NOT_PARENT_DISPLAYABLE"),
        ({"assessed_source_id": 9}, "SOURCE_PROVENANCE_MISMATCH"),
        ({"trust_class": "WHO"}, "TRUSTED_SOURCE_REQUIRED"),
    ],
)
def test_safe_fallback_eligibility_fails_closed_for_each_evidence_gate(
    overrides, reason
):
    context, selected, proposal = _safe_fallback_policy_inputs(**overrides)
    result = evaluate_safe_fallback_eligibility(
        topic_id=7,
        context=context,
        selected=selected,
        proposal=proposal,
        failure_code="AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED",
    )
    assert result.eligible is False
    assert result.reason_code == reason
    assert result.snapshot is None


def test_safe_fallback_snapshot_contains_only_bounded_validated_facts():
    context, selected, proposal = _safe_fallback_policy_inputs()
    result = evaluate_safe_fallback_eligibility(
        topic_id=7,
        context=context,
        selected=selected,
        proposal=proposal,
        failure_code="AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED",
    )
    assert result.eligible is True
    assert result.snapshot.validated_source_ids == (1,)
    assert not hasattr(result.snapshot, "short_explanation_vi")
    assert not hasattr(result.snapshot.sources[0], "note_vi")


@pytest.mark.parametrize(
    ("factor_type", "factor_key", "factor_value", "expected_phrase"),
    [
        ("WEATHER", "wind", None, "gió"),
        ("AGE", "age_group", load_factor_values()["AGE"][0], "nhóm tuổi"),
        ("SEX", "gender", load_factor_values()["SEX"][0], "giới tính"),
        ("SEASONALITY", "time_of_year", None, "thời điểm trong năm"),
    ],
)
def test_safe_fallback_renderer_is_deterministic_for_every_factor_type(
    factor_type, factor_key, factor_value, expected_phrase
):
    snapshot = SafeFallbackEligibilitySnapshot(
        topic_id=7,
        disease_group_id="5",
        disease_name="Tiêu chảy - Gastroenteritis",
        factor_type=factor_type,
        factor_key=factor_key,
        factor_value=factor_value,
        evidence_level="SUPPORTED",
        evidence_scope="PARTIAL_GROUP",
        sources=(SafeFallbackSourceSnapshot(
            source_id=1,
            evidence_content_id=2,
            trust_class="PUBMED",
            relevance="DIRECT",
            population_relevance="PEDIATRIC_DIRECT",
        ),),
    )
    first = AutoSafeFallbackRenderer().render(snapshot)
    second = AutoSafeFallbackRenderer().render(snapshot)
    assert first == second
    assert expected_phrase in factor_phrase_vi(snapshot)
    combined = " ".join((
        first.short_explanation_vi,
        first.detailed_explanation_vi,
        first.limitations_vi,
    )).lower()
    assert snapshot.disease_name.lower() in combined
    assert factor_phrase_vi(snapshot) in combined
    assert "quan hệ nhân quả" in combined
    assert "gây ra" not in combined
    assert "miễn dịch" not in combined
    assert "3 groups" not in combined
    assert first.numeric_claims == []


@pytest.mark.parametrize("code", ["AUTO_OUTPUT_JSON_INVALID", "AUTO_OUTPUT_SCHEMA_INVALID"])
def test_repair_structural_failure_uses_safe_fallback_without_third_call(
    db, disease_files, code
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    prose = "The pediatric study used 3 groups and reported an association."
    generator = ContractRepairGenerator(
        initial_text=prose,
        repaired_text="unused",
        repair_error=DraftGeneratorStructuredOutputError(
            code, "The repair response did not satisfy the structured contract."
        ),
    )
    processor(db, disease_files, FakeDiscovery(), generator).process_next()
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert generator.calls == 2
    assert db.scalar(select(AutoMedicalKnowledgeJob)).status == "READY"
    assert revision.generation_mode == "SAFE_FALLBACK"
    assert revision.fallback_reason_code == "REPAIR_STRUCTURAL_FAILURE"
    assert "3 groups" not in revision.detailed_explanation_vi


def test_parent_safe_fallback_exposes_only_safe_mode_warning_and_references(
    db, disease_files
):
    q, _discovery, generator = generate_safe_fallback_auto(db, disease_files)
    enable_fallback(db)
    item = parent(db, q).read_batch(request()).items[0]
    assert generator.calls == 2
    assert item.knowledge_type == "AUTO"
    assert item.auto_tier == "BASIC"
    assert item.warning == AUTO_SAFE_FALLBACK_PARENT_WARNING
    assert item.sources[0].pmid == "40123456"
    assert "3 groups" not in item.detailed_explanation_vi
    assert not hasattr(item, "generation_mode")
    assert not hasattr(item, "fallback_reason_code")


def test_v012_is_additive_idempotent_and_does_not_rewrite_legacy_auto_rows():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE auto_medical_knowledge_revisions "
            "(id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO auto_medical_knowledge_revisions VALUES (7,'legacy-unchanged')"
        )
    upgrade_auto_safe_fallback(engine)
    upgrade_auto_safe_fallback(engine)
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT marker,generation_mode,fallback_reason_code "
            "FROM auto_medical_knowledge_revisions WHERE id=7"
        ).fetchone()
        assert row == ("legacy-unchanged", None, None)
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()


def test_safe_fallback_trigger_allow_list_excludes_semantic_and_initial_provider_failures():
    assert is_safe_fallback_trigger(
        "AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED", "INITIAL_VALIDATION"
    )
    assert is_safe_fallback_trigger(
        "AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED", "CONTRACT_REPAIR"
    )
    for code in (
        "AUTO_OUTPUT_CAUSAL_OVERCLAIM",
        "AUTO_OUTPUT_UNSUPPORTED_MECHANISM",
        "AUTO_OUTPUT_PEDIATRIC_CLAIM_INVALID",
        "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH",
        "AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID",
        "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID",
        "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH",
    ):
        assert is_safe_fallback_trigger(code, "CONTRACT_REPAIR") is False
    assert is_safe_fallback_trigger(
        "AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED", "INITIAL_VALIDATION"
    ) is False


def test_temp_database_startup_lifespan_applies_v014_and_serves_root(
    tmp_path, monkeypatch
):
    import app.main as main_module

    temp_engine = create_engine(
        f"sqlite:///{tmp_path / 'startup.db'}",
        connect_args={"check_same_thread": False},
    )
    TempSession = sessionmaker(
        bind=temp_engine, autocommit=False, autoflush=False
    )

    async def idle_worker(stop_event):
        await stop_event.wait()

    monkeypatch.setattr(main_module, "engine", temp_engine)
    monkeypatch.setattr(main_module, "SessionLocal", TempSession)
    monkeypatch.setattr(main_module, "validate_security_configuration", lambda: None)
    monkeypatch.setattr(main_module, "WEATHER_AI_V3_PRELOAD", False)
    monkeypatch.setattr(
        main_module, "recover_interrupted_auto_medical_knowledge_jobs", lambda: 0
    )
    monkeypatch.setattr(main_module, "run_auto_medical_knowledge_worker", idle_worker)

    with TestClient(main_module.app) as client:
        response = client.get("/")
        assert response.status_code == 200

    with temp_engine.connect() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(auto_medical_knowledge_revisions)"
            ).fetchall()
        }
        assert {
            "generation_mode",
            "fallback_reason_code",
            "auto_tier",
            "generation_method",
            "strict_failure_code",
            "strict_failure_stage",
        } <= columns
        state_columns = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(auto_medical_knowledge_topic_states)"
            )
        }
        assert {"is_hidden_by_staff", "hidden_at"} <= state_columns
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM auto_medical_knowledge_visibility_audits"
        ).scalar_one() == 0
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        setting_columns = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(auto_medical_knowledge_settings)"
            ).fetchall()
        }
        assert "basic_fallback_enabled" in setting_columns
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    temp_engine.dispose()


def test_numeric_contract_v2_legacy_revision_remains_readable_and_parent_eligible(
    db, disease_files
):
    q, _discovery, _generator = generate_ready_auto(db, disease_files)
    enable_fallback(db)
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    state = db.scalar(select(AutoMedicalKnowledgeTopicState))
    revision.prompt_version = "medical_knowledge_auto_v1"
    db.commit()

    assert AutoMedicalKnowledgeRepository(db).get_revision_numeric_claims(revision.id) == []
    assert state.current_revision_id == revision.id
    assert parent(db, q).read_batch(request()).items[0].knowledge_type == "AUTO"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("disease", "NO_DISEASE_RELEVANT_SOURCE"),
        ("factor", "NO_FACTOR_RELEVANT_SOURCE"),
        ("pediatric", "NO_PEDIATRIC_RELEVANT_SOURCE"),
        ("trust", "TRUSTED_SOURCE_REQUIRED"),
        ("provenance", "SOURCE_PROVENANCE_MISMATCH"),
        ("conflicting", "CONFLICTING_EVIDENCE"),
        ("insufficient", "NO_USABLE_EVIDENCE"),
    ],
)
def test_multi_tier_shared_evidence_qualification_fails_independently(
    mutation, reason
):
    context, selected, _proposal = _safe_fallback_policy_inputs()
    row = selected[0]
    discovery_reason = None
    if mutation == "disease":
        row = (*row[:4], RelevanceSignals(0, 1, 1))
    elif mutation == "factor":
        row = (*row[:4], RelevanceSignals(1, 0, 1))
    elif mutation == "pediatric":
        row = (*row[:4], RelevanceSignals(1, 1, 0))
    elif mutation == "trust":
        row = (*row[:3], "WHO", row[4])
    elif mutation == "provenance":
        row = (row[0], SimpleNamespace(id=2, source_id=99), *row[2:])
    elif mutation == "conflicting":
        discovery_reason = "CONFLICTING_EVIDENCE"
    elif mutation == "insufficient":
        discovery_reason = "NO_USABLE_EVIDENCE"
    result = qualify_auto_evidence(
        topic_id=7,
        context=context,
        selected=[row],
        discovery_reason=discovery_reason,
    )
    assert result.eligible is False
    assert result.reason_code == reason
    assert result.snapshot is None


def test_multi_tier_shared_evidence_qualification_preserves_exact_provenance():
    context, selected, _proposal = _safe_fallback_policy_inputs()
    result = qualify_auto_evidence(topic_id=7, context=context, selected=selected)
    assert result.eligible is True
    assert result.snapshot.validated_source_ids == (1,)
    assert result.snapshot.validated_evidence_content_ids == (2,)
    assert result.snapshot.pediatric_support is True


def test_multi_tier_strict_success_never_calls_basic(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    strict = FakeGenerator()
    basic = FakeBasicGenerator()
    processor(
        db, disease_files, FakeDiscovery(), strict, basic_generator=basic
    ).process_next()
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert strict.calls == 1
    assert basic.calls == 0
    assert revision.auto_tier == "STRICT"
    assert revision.generation_method == "AI"


def test_multi_tier_strict_numeric_failure_discards_prose_and_uses_basic(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    failed_prose = "STRICT_FAILED_SENTINEL used 3 groups."
    strict = ContractRepairGenerator(
        initial_text=failed_prose,
        repaired_text=failed_prose,
    )
    basic = FakeBasicGenerator()
    processor(
        db, disease_files, FakeDiscovery(), strict, basic_generator=basic
    ).process_next()
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert strict.calls == 2
    assert basic.calls == 1
    assert revision.generation_status == "READY"
    assert revision.auto_tier == "BASIC"
    assert revision.generation_method == "AI"
    assert revision.generation_mode is None
    assert revision.strict_failure_code == "AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED"
    assert "STRICT_FAILED_SENTINEL" not in revision.detailed_explanation_vi


@pytest.mark.parametrize(
    "strict",
    [
        RiskyGenerator("Mưa gây ra bệnh ở trẻ em."),
        FakeGenerator(fail=True),
    ],
)
def test_multi_tier_generated_content_or_provider_failure_may_downgrade(
    db, disease_files, strict
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    basic = FakeBasicGenerator()
    processor(
        db, disease_files, FakeDiscovery(), strict, basic_generator=basic
    ).process_next()
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert revision.auto_tier == "BASIC"
    assert revision.generation_method == "AI"
    assert basic.calls == 1


@pytest.mark.parametrize(
    "summary",
    [
        "Nghiên cứu ghi nhận mức 1.07 ở trẻ em.",
        "Nghiên cứu ghi nhận 27% ở trẻ em.",
        "Mưa gây ra bệnh ở trẻ em.",
        "Con bạn nên dùng thuốc điều trị.",
    ],
)
def test_multi_tier_invalid_basic_output_uses_safe_template(
    db, disease_files, summary
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    strict = FakeGenerator(fail=True)
    basic = FakeBasicGenerator(summary=summary)
    processor(
        db, disease_files, FakeDiscovery(), strict, basic_generator=basic
    ).process_next()
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    assert strict.calls == 1
    assert basic.calls == 1
    assert revision.auto_tier == "BASIC"
    assert revision.generation_method == "SAFE_TEMPLATE"
    assert revision.generation_mode == "SAFE_FALLBACK"
    assert not any(token in revision.detailed_explanation_vi for token in ("1.07", "27%", "gây ra", "dùng thuốc"))


def test_multi_tier_basic_invented_source_never_persists(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    basic = FakeBasicGenerator(source_ids=[999])
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        FakeGenerator(fail=True),
        basic_generator=basic,
    ).process_next()
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    links = AutoMedicalKnowledgeRepository(db).get_revision_sources(revision.id)
    assert revision.generation_method == "SAFE_TEMPLATE"
    assert {source.id for _link, source, _content in links} == {1}


def test_multi_tier_basic_rate_limit_propagates_and_persists_cooldown(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    strict = FakeGenerator(fail=True)
    basic = FakeBasicGenerator(
        error=DraftGeneratorRateLimitError(
            "provider detail must not be persisted", retry_after_seconds=120
        )
    )
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        strict,
        basic_generator=basic,
        provider_name="groq",
        retry_delay_seconds=30,
    ).process_next()

    job = db.scalar(select(AutoMedicalKnowledgeJob))
    cooldown = db.get(AutoMedicalKnowledgeProviderCooldown, "GROQ")
    assert strict.calls == 1
    assert basic.calls == 1
    assert job.status == "FAILED"
    assert job.last_error_code == "LLM_RATE_LIMITED"
    assert job.next_retry_at == NOW + timedelta(seconds=120)
    assert cooldown.cooldown_until == NOW + timedelta(seconds=120)
    assert db.scalar(select(func.count()).select_from(AutoMedicalKnowledgeRevision)) == 0


def test_multi_tier_final_basic_rate_limit_uses_template_and_keeps_cooldown(
    db, disease_files
):
    q = queue(db)
    q.enqueue_selectors(request().items)
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    job.attempt_count = 2
    db.commit()
    strict = FakeGenerator(fail=True)
    basic = FakeBasicGenerator(
        error=DraftGeneratorRateLimitError(
            "provider detail must not be persisted", retry_after_seconds=120
        )
    )
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        strict,
        basic_generator=basic,
        provider_name="groq",
        retry_delay_seconds=30,
    ).process_next()

    db.refresh(job)
    revision = db.scalar(select(AutoMedicalKnowledgeRevision))
    cooldown = db.get(AutoMedicalKnowledgeProviderCooldown, "GROQ")
    assert strict.calls == 1
    assert basic.calls == 1
    assert job.status == "READY"
    assert revision.auto_tier == "BASIC"
    assert revision.generation_method == "SAFE_TEMPLATE"
    assert cooldown.cooldown_until == NOW + timedelta(seconds=120)


def test_multi_tier_evidence_failure_makes_zero_generation_calls(db, disease_files):
    q = queue(db)
    q.enqueue_selectors(request().items)
    strict = FakeGenerator()
    basic = FakeBasicGenerator()
    processor(
        db, disease_files, AdultEvidenceDiscovery(), strict, basic_generator=basic
    ).process_next()
    job = db.scalar(select(AutoMedicalKnowledgeJob))
    assert job.status == "INSUFFICIENT"
    assert strict.calls == 0
    assert basic.calls == 0


def test_multi_tier_basic_never_replaces_existing_strict_current(db, disease_files):
    q = queue(db)
    settings = AutoMedicalKnowledgeRepository(db).get_settings()
    settings.auto_visible_default = True
    db.commit()
    q.enqueue_selectors(request().items)
    processor(
        db, disease_files, FakeDiscovery(), FakeGenerator()
    ).process_next()
    strict_revision = db.scalar(select(AutoMedicalKnowledgeRevision))

    q.enqueue_selectors(request().items, trigger_type="ADMIN", force=True)
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        FakeGenerator(fail=True),
        basic_generator=FakeBasicGenerator(),
    ).process_next()
    revisions = list(db.scalars(select(AutoMedicalKnowledgeRevision).order_by(AutoMedicalKnowledgeRevision.id)))
    state = db.scalar(select(AutoMedicalKnowledgeTopicState))
    assert len(revisions) == 2
    assert revisions[1].auto_tier == "BASIC"
    assert state.current_revision_id == strict_revision.id


def test_multi_tier_parent_basic_dto_is_safe(db, disease_files):
    q = queue(db)
    settings = AutoMedicalKnowledgeRepository(db).get_settings()
    settings.auto_visible_default = False
    settings.display_mode = "REVIEWED_WITH_AUTO_FALLBACK"
    db.commit()
    q.enqueue_selectors(request().items)
    processor(
        db,
        disease_files,
        FakeDiscovery(),
        FakeGenerator(fail=True),
        basic_generator=FakeBasicGenerator(),
    ).process_next()
    item = parent(db, q).read_batch(request()).items[0]
    assert item.auto_tier == "BASIC"
    assert item.warning == AUTO_BASIC_PARENT_WARNING
    payload = item.model_dump()
    assert not {
        "generation_mode",
        "generation_method",
        "strict_failure_code",
        "strict_failure_stage",
        "fallback_reason_code",
        "numeric_claims",
        "diagnostics",
    } & payload.keys()


def test_v013_is_additive_idempotent_and_preserves_legacy_mapping():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE auto_medical_knowledge_revisions ("
            "id INTEGER PRIMARY KEY, generation_mode VARCHAR(20), marker TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE auto_medical_knowledge_settings (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO auto_medical_knowledge_revisions VALUES (1,'AI_FULL','unchanged')"
        )
        connection.exec_driver_sql(
            "INSERT INTO auto_medical_knowledge_settings VALUES (1)"
        )
    upgrade_auto_multi_tier(engine)
    upgrade_auto_multi_tier(engine)
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT generation_mode,auto_tier,generation_method,marker "
            "FROM auto_medical_knowledge_revisions WHERE id=1"
        ).one()
        assert row == ("AI_FULL", None, None, "unchanged")
        assert connection.exec_driver_sql(
            "SELECT basic_fallback_enabled FROM auto_medical_knowledge_settings WHERE id=1"
        ).scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()


def test_v014_is_idempotent_preserves_legacy_prose_and_does_not_invent_hides():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE medical_knowledge_topics (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE auto_medical_knowledge_revisions ("
            "id INTEGER PRIMARY KEY, short_explanation_vi TEXT, is_visible BOOLEAN NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE auto_medical_knowledge_topic_states ("
            "topic_id INTEGER PRIMARY KEY, current_revision_id INTEGER, "
            "request_count INTEGER NOT NULL DEFAULT 0, first_requested_at DATETIME, "
            "last_requested_at DATETIME, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL, "
            "FOREIGN KEY(topic_id) REFERENCES medical_knowledge_topics(id), "
            "FOREIGN KEY(current_revision_id) REFERENCES auto_medical_knowledge_revisions(id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO medical_knowledge_topics VALUES (7)"
        )
        connection.exec_driver_sql(
            "INSERT INTO auto_medical_knowledge_revisions VALUES "
            "(11,'legacy prose unchanged',0)"
        )
        connection.exec_driver_sql(
            "INSERT INTO auto_medical_knowledge_topic_states VALUES "
            "(7,11,0,NULL,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        )

    upgrade_auto_topic_visibility(engine)
    upgrade_auto_topic_visibility(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT is_hidden_by_staff,hidden_at "
            "FROM auto_medical_knowledge_topic_states WHERE topic_id=7"
        ).one() == (0, None)
        assert connection.exec_driver_sql(
            "SELECT short_explanation_vi,is_visible "
            "FROM auto_medical_knowledge_revisions WHERE id=11"
        ).one() == ("legacy prose unchanged", 0)
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM auto_medical_knowledge_visibility_audits"
        ).scalar_one() == 0
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()
