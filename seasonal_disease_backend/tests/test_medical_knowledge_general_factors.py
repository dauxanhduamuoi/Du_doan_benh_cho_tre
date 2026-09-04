from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.medical_knowledge_draft_schemas import (
    DraftGenerationContext,
    DraftGenerationRequest,
    MedicalKnowledgeDraftProposal,
)
from app.medical_knowledge_factor_schemas import GenericFactorSelector
from app.medical_knowledge_factors import (
    FACTOR_TYPES,
    WEATHER_FACTORS,
    factor_catalog,
    load_factor_values,
    normalize_factor,
)
from app.medical_knowledge_models import (
    MedicalEvidenceContent,
    MedicalEvidenceSource,
    MedicalKnowledgeTopic,
    MedicalKnowledgeTopicSource,
)
from app.models import User
from app.medical_knowledge_schemas import MedicalTopicCreate
from app.pubmed_schemas import PubMedLookupRequest, PubMedSearchRequest
from app.published_medical_knowledge_schemas import (
    PublishedMedicalKnowledgeBatchRequest,
    PublishedMedicalKnowledgeSelector,
)
from app.repositories.medical_knowledge_repository import MedicalKnowledgeRepository
from app.services.medical_knowledge_prompt import SYSTEM_INSTRUCTIONS, build_generation_input
from app.services.medical_knowledge_approval_service import MedicalKnowledgeApprovalService
from app.services.medical_knowledge_draft_service import (
    MedicalKnowledgeDraftService,
    load_deployed_disease_contexts,
)
from app.services.medical_knowledge_publication_service import MedicalKnowledgePublicationService
from app.services.published_medical_knowledge_read_service import PublishedMedicalKnowledgeReadService
from app.services.pubmed_query_builder import PEDIATRIC_SEARCH_COMPONENT, build_pubmed_query
from migrations.v007_medical_knowledge_general_factors import upgrade


AGE_VALUES = load_factor_values()["AGE"]
SEX_VALUES = load_factor_values()["SEX"]


@pytest.mark.parametrize("weather", WEATHER_FACTORS)
def test_legacy_weather_selector_is_canonical(weather):
    factor = normalize_factor(weather_factor=weather)
    assert (factor.factor_type, factor.factor_key, factor.factor_value) == (
        "WEATHER",
        weather,
        None,
    )
    assert factor.weather_factor == weather


@pytest.mark.parametrize("factor_type", FACTOR_TYPES)
def test_factor_catalog_contains_each_required_type(factor_type):
    assert any(item["type"] == factor_type for item in factor_catalog())


@pytest.mark.parametrize("value", AGE_VALUES)
def test_age_uses_exact_deployed_weather_ai_values(value):
    factor = normalize_factor(
        factor_type="AGE", factor_key="age_group", factor_value=value
    )
    assert factor.factor_value == value
    assert factor.weather_factor is None


@pytest.mark.parametrize("value", SEX_VALUES)
def test_sex_uses_exact_deployed_weather_ai_values(value):
    factor = normalize_factor(
        factor_type="SEX", factor_key="gender", factor_value=value
    )
    assert factor.factor_value == value


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"factor_type": "AGE", "factor_key": "age_group"}, "nhóm tuổi"),
        ({"factor_type": "SEX", "factor_key": "gender"}, "giới tính"),
        (
            {"factor_type": "SEASONALITY", "factor_key": "time_of_year", "factor_value": "August"},
            "must be null",
        ),
        (
            {"factor_type": "WEATHER", "factor_key": "humidity", "factor_value": "80"},
            "must be null",
        ),
        ({"factor_type": "AGE", "factor_key": "gender", "factor_value": AGE_VALUES[0]}, "factor_key"),
        ({"factor_type": "UNKNOWN", "factor_key": "x"}, "factor_type"),
    ],
)
def test_invalid_factor_selection_has_specific_error(payload, message):
    with pytest.raises(ValueError, match=message):
        normalize_factor(**payload)


@pytest.mark.parametrize(
    "factor_type,factor_key,factor_value,needle",
    [
        ("AGE", "age_group", AGE_VALUES[0], "age-specific"),
        ("SEX", "gender", SEX_VALUES[0], "sex differences"),
        ("SEASONALITY", "time_of_year", None, "seasonal variation"),
        ("WEATHER", "humidity", None, "humidity"),
    ],
)
def test_guided_query_has_factor_terms_and_one_pediatric_clause(
    factor_type, factor_key, factor_value, needle
):
    query = build_pubmed_query(
        ["gastroenteritis"],
        factor_type=factor_type,
        factor_key=factor_key,
        factor_value=factor_value,
    )
    assert needle in query
    assert query.count(PEDIATRIC_SEARCH_COMPONENT) == 1
    assert '"gastroenteritis"[Title/Abstract]' in query


def test_guided_weather_legacy_query_is_unchanged():
    legacy = build_pubmed_query(["asthma"], "precipitation")
    generic = build_pubmed_query(
        ["asthma"], factor_type="WEATHER", factor_key="precipitation"
    )
    assert legacy == generic


def test_age_guided_query_keeps_selected_bucket_soft_in_or_component():
    query = build_pubmed_query(
        ["diarrhea"],
        factor_type="AGE",
        factor_key="age_group",
        factor_value=AGE_VALUES[0],
    )
    assert f'"{AGE_VALUES[0]}"[Title/Abstract]' in query
    assert " OR " in query


def test_free_pubmed_query_preserves_valid_syntax():
    query = 'intestinal infection AND ("sex differences"[Title/Abstract])'
    request = PubMedSearchRequest(
        disease_group_id="5",
        factor_type="SEX",
        factor_key="gender",
        factor_value=SEX_VALUES[0],
        search_mode="FREE",
        free_query=query,
    )
    assert request.free_query == query
    assert request.disease_terms == []


@pytest.mark.parametrize("query", ["", "   ", "abc\x00def", "abc\ndef"])
def test_free_pubmed_query_rejects_empty_or_control_text(query):
    with pytest.raises(ValidationError):
        PubMedSearchRequest(
            disease_group_id="5",
            factor_type="SEASONALITY",
            factor_key="time_of_year",
            search_mode="FREE",
            free_query=query,
        )


def test_free_pubmed_query_is_bounded():
    with pytest.raises(ValidationError):
        PubMedSearchRequest(
            disease_group_id="5",
            weather_factor="humidity",
            search_mode="FREE",
            free_query="x" * 1001,
        )


def test_direct_pmid_accepts_generic_age_selector():
    request = PubMedLookupRequest(
        pmid="34201085",
        disease_group_id="5",
        factor_type="AGE",
        factor_key="age_group",
        factor_value=AGE_VALUES[0],
    )
    assert request.pmid == "34201085"
    assert request.factor_type == "AGE"


def test_direct_pmid_legacy_weather_contract_remains():
    request = PubMedLookupRequest(
        pmid="34201085", disease_group_id="5", weather_factor="humidity"
    )
    assert request.factor_key == "humidity"


def test_topic_repository_distinguishes_age_values_and_sex_values():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        repository = MedicalKnowledgeRepository(db)
        topics = [
            repository.create_topic(
                MedicalTopicCreate(
                    disease_group_id="5",
                    factor_type="AGE",
                    factor_key="age_group",
                    factor_value=value,
                )
            )
            for value in AGE_VALUES[:2]
        ]
        topics += [
            repository.create_topic(
                MedicalTopicCreate(
                    disease_group_id="5",
                    factor_type="SEX",
                    factor_key="gender",
                    factor_value=value,
                )
            )
            for value in SEX_VALUES
        ]
        db.commit()
        assert len({topic.id for topic in topics}) == 4


def test_topic_null_safe_uniqueness_blocks_duplicate_seasonality():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                MedicalKnowledgeTopic(
                    disease_group_id="5",
                    factor_type="SEASONALITY",
                    factor_key="time_of_year",
                    factor_value=None,
                    weather_factor=None,
                )
                for _ in range(2)
            ]
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_topic_library_lookup_is_scoped_by_full_selector():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        repository = MedicalKnowledgeRepository(db)
        age = repository.create_topic(
            MedicalTopicCreate(
                disease_group_id="5",
                factor_type="AGE",
                factor_key="age_group",
                factor_value=AGE_VALUES[0],
            )
        )
        sex = repository.create_topic(
            MedicalTopicCreate(
                disease_group_id="5",
                factor_type="SEX",
                factor_key="gender",
                factor_value=SEX_VALUES[0],
            )
        )
        assert repository.get_topic_by_selector("5", "AGE", "age_group", AGE_VALUES[0]).id == age.id
        assert repository.get_topic_by_selector("5", "SEX", "gender", SEX_VALUES[0]).id == sex.id


def test_v007_backfills_weather_and_preserves_topic_ids_and_pointer():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE medical_knowledge_topics (id INTEGER PRIMARY KEY, "
            "disease_group_id VARCHAR(100) NOT NULL, weather_factor VARCHAR(32) NOT NULL, "
            "published_revision_id INTEGER NULL, created_by INTEGER NULL, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
            "UNIQUE(disease_group_id,weather_factor))"
        )
        connection.exec_driver_sql(
            "INSERT INTO medical_knowledge_topics VALUES "
            "(7,'5','humidity',42,NULL,'2026-01-01','2026-01-01')"
        )
    upgrade(engine)
    upgrade(engine)
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT id,weather_factor,factor_type,factor_key,factor_value,published_revision_id "
            "FROM medical_knowledge_topics"
        ).one()
    assert row == (7, "humidity", "WEATHER", "humidity", None, 42)


def test_generation_context_contains_exact_generic_factor_and_selected_sources_only():
    context = DraftGenerationContext(
        disease_group_id="5",
        disease_group_name="Gastroenteritis",
        factor_type="AGE",
        factor_key="age_group",
        factor_value=AGE_VALUES[0],
        sources=[],
    )
    payload = json.loads(build_generation_input(context))
    assert payload["scope"]["factor_type"] == "AGE"
    assert payload["scope"]["factor_value"] == AGE_VALUES[0]
    assert payload["selected_evidence_sources"] == []


@pytest.mark.parametrize("needle", ["AGE:", "SEX:", "SEASONALITY:", "Never invent mechanisms"])
def test_prompt_has_conservative_generic_factor_semantics(needle):
    assert needle in SYSTEM_INSTRUCTIONS


@pytest.mark.parametrize(
    "payload",
    [
        {"disease_group_id": "5", "weather_factor": "humidity"},
        {
            "disease_group_id": "5",
            "factor_type": "AGE",
            "factor_key": "age_group",
            "factor_value": AGE_VALUES[0],
        },
        {
            "disease_group_id": "5",
            "factor_type": "SEX",
            "factor_key": "gender",
            "factor_value": SEX_VALUES[0],
        },
        {
            "disease_group_id": "5",
            "factor_type": "SEASONALITY",
            "factor_key": "time_of_year",
        },
    ],
)
def test_parent_selector_supports_all_required_factor_types(payload):
    selector = PublishedMedicalKnowledgeSelector(**payload)
    assert selector.factor_type in FACTOR_TYPES


def test_generic_selector_rejects_weather_compatibility_mismatch():
    with pytest.raises(ValidationError):
        GenericFactorSelector(
            factor_type="WEATHER",
            factor_key="humidity",
            weather_factor="wind",
        )


class _DeterministicGenerator:
    model_name = "deterministic-general-factor"

    def __init__(self):
        self.contexts = []

    def generate(self, context):
        self.contexts.append(context)
        return MedicalKnowledgeDraftProposal(
            evidence_level="SUPPORTED",
            evidence_scope="WHOLE_GROUP",
            short_explanation_vi="Bằng chứng đã chọn ghi nhận một mối liên hệ, không chứng minh nhân quả.",
            detailed_explanation_vi="Nội dung này chỉ tóm tắt chính xác evidence fixture dành cho trẻ em.",
            limitations_vi="Fixture xác định và không đại diện cho tư vấn hay nguy cơ cá nhân.",
            source_assessments=[{
                "source_id": 1,
                "relevance": "DIRECT",
                "note_vi": "Nguồn trực tiếp phù hợp với yếu tố và giá trị đã chọn.",
                "population_relevance": "PEDIATRIC_DIRECT",
                "population_note": "Nguồn fixture báo cáo trực tiếp quần thể trẻ em.",
            }],
        )


@pytest.mark.parametrize(
    "factor_type,factor_key,factor_value,weather_factor",
    [
        ("AGE", "age_group", AGE_VALUES[0], None),
        ("SEX", "gender", SEX_VALUES[0], None),
        ("SEASONALITY", "time_of_year", None, None),
        ("WEATHER", "humidity", None, "humidity"),
    ],
)
def test_general_explanation_factors_e2e_draft_approve_publish_parent_read(
    tmp_path, factor_type, factor_key, factor_value, weather_factor
):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    manifest = tmp_path / f"manifest-{factor_type}.json"
    catalog = tmp_path / f"catalog-{factor_type}.csv"
    manifest.write_text(json.dumps({"model_count": 1, "disease_order": ["5"]}), encoding="utf-8")
    catalog.write_text(
        "disease_group_id,disease_group_name,report_group_code\n"
        "5,Infectious gastroenteritis,A09\n",
        encoding="utf-8",
    )
    load_deployed_disease_contexts.cache_clear()

    with Session(engine) as db:
        staff = User(username=f"staff-{factor_type}", password_hash="x", role="staff", is_active=True)
        db.add(staff)
        db.flush()
        topic = MedicalKnowledgeRepository(db).create_topic(
            MedicalTopicCreate(
                disease_group_id="5",
                factor_type=factor_type,
                factor_key=factor_key,
                factor_value=factor_value,
                weather_factor=weather_factor,
                created_by=staff.id,
            )
        )
        source = MedicalEvidenceSource(
            id=1,
            source_type="PUBMED",
            pmid="34201085",
            title=f"Pediatric {factor_type} evidence",
            abstract_text="A pediatric result directly reports the selected factor relationship.",
            url="https://pubmed.ncbi.nlm.nih.gov/34201085/",
        )
        db.add(source)
        db.flush()
        content = MedicalEvidenceContent(
            source_id=source.id,
            content_kind="ABSTRACT",
            content_origin="NCBI_PUBMED",
            evidence_text=source.abstract_text,
            retrieved_at=datetime(2026, 8, 25),
            is_truncated=False,
            content_sha256="a" * 64,
        )
        db.add(content)
        db.add(MedicalKnowledgeTopicSource(topic_id=topic.id, source_id=source.id, added_by=staff.id))
        db.commit()

        generator = _DeterministicGenerator()
        draft_service = MedicalKnowledgeDraftService(
            db,
            generator,
            disease_manifest_path=manifest,
            disease_catalog_path=catalog,
        )
        draft = draft_service.generate(
            DraftGenerationRequest(
                disease_group_id="5",
                factor_type=factor_type,
                factor_key=factor_key,
                factor_value=factor_value,
                weather_factor=weather_factor,
                source_ids=[source.id],
            ),
            created_by=staff.id,
        )
        assert generator.contexts[0].factor_type == factor_type
        assert generator.contexts[0].factor_value == factor_value
        MedicalKnowledgeApprovalService(db).approve(draft.id, approved_by=staff.id)
        MedicalKnowledgePublicationService(db).publish(draft.id, published_by=staff.id)

        response = PublishedMedicalKnowledgeReadService(db).read_batch(
            PublishedMedicalKnowledgeBatchRequest(items=[{
                "disease_group_id": "5",
                "factor_type": factor_type,
                "factor_key": factor_key,
                "factor_value": factor_value,
                "weather_factor": weather_factor,
            }])
        )
        assert len(response.items) == 1
        assert response.items[0].revision_id == draft.id
        assert response.items[0].factor_type == factor_type
        if factor_type == "SEX" and len(SEX_VALUES) > 1:
            missing = PublishedMedicalKnowledgeReadService(db).read_batch(
                PublishedMedicalKnowledgeBatchRequest(items=[{
                    "disease_group_id": "5",
                    "factor_type": "SEX",
                    "factor_key": "gender",
                    "factor_value": SEX_VALUES[1],
                }])
            )
            assert missing.items == []
    engine.dispose()
