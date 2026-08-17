from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from app.services.weather_ai_explanations import (
    MedicalKnowledgeService,
    Tier1ExplanationService,
)
from app.services.weather_ai_features import DEFAULT_TIMEZONE
from app.services.weather_ai_service import WeatherAIRuntimeService


def test_01_registry_loads_exactly_221_locked_models(registry):
    assert registry.loaded
    assert len(registry.disease_order) == 221
    assert len(registry.feature_order) == 45
    status = registry.status()
    assert status["model_count"] == 221
    assert status["manifest_verified"] is True
    assert "manifest_path" not in status


def test_02_feature_transform_matches_locked_train_context(registry, runtime_service, train_context):
    prepared = runtime_service.feature_builder.prepare(
        train_context["age_group"],
        train_context["gender"],
        train_context["weather"],
        None,
        None,
        DEFAULT_TIMEZONE,
        train_context["target_date"],
    )
    expected = train_context["row"].loc[list(registry.feature_order)].copy()
    for column in ("age_group", "gender", "season"):
        expected[column] = registry.category_mappings[column][str(expected[column])]
    expected_values = pd.to_numeric(expected, errors="raise").to_numpy(dtype=float)
    assert np.allclose(prepared.encoded.iloc[0].to_numpy(dtype=float), expected_values, atol=1e-12)


def test_weather_aggregation_matches_locked_v3_pipeline(runtime_service):
    pipeline_path = (
        Path(__file__).resolve().parents[2] / "weather_disease_ai_v3/src/data_pipeline.py"
    )
    spec = importlib.util.spec_from_file_location("locked_v3_data_pipeline_test", pipeline_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    hourly, _ = module.read_weather_hourly(
        Path(__file__).resolve().parents[2]
        / "weather_disease_ai_v3/data/raw/weather_hcm_history.csv"
    )
    daily = module.build_daily_weather(hourly)
    expected, _, weather_columns = module.build_weather_features(daily)
    expected = expected.dropna(subset=weather_columns).iloc[0]
    anchor = pd.Timestamp(expected["anchor_date"])
    actual_daily = daily.loc[daily["date"] <= anchor].copy()
    actual = runtime_service.feature_builder._weather_feature_frame(actual_daily)
    actual = actual.loc[actual["anchor_date"] == anchor].iloc[0]
    assert np.allclose(
        actual[weather_columns].to_numpy(dtype=float),
        expected[weather_columns].to_numpy(dtype=float),
        rtol=0,
        atol=1e-12,
    )


def test_03_ranking_regression_matches_standalone_locked_boosters(
    registry, runtime_service, train_context
):
    prepared = runtime_service.feature_builder.prepare(
        train_context["age_group"],
        train_context["gender"],
        train_context["weather"],
        None,
        None,
        DEFAULT_TIMEZONE,
        train_context["target_date"],
    )
    integrated_scores = registry.predict_scores(prepared.encoded)
    manifest = json.loads(registry.manifest_path.read_text(encoding="utf-8"))
    standalone_scores = []
    for entry in manifest["models"]:
        path = registry.deployment_dir / entry["model_path"]
        booster = lgb.Booster(model_str=path.read_text(encoding="utf-8"))
        standalone_scores.append(float(booster.predict(prepared.encoded)[0]))
    standalone = np.asarray(standalone_scores)
    assert np.allclose(integrated_scores, standalone, rtol=0, atol=1e-12)
    assert np.array_equal(
        np.argsort(-integrated_scores, kind="stable"),
        np.argsort(-standalone, kind="stable"),
    )


def test_04_top_k_is_selected_from_all_221_models(runtime_service, train_context):
    result = runtime_service.predict(
        train_context["age_group"],
        train_context["gender"],
        top_k=5,
        weather=train_context["weather"],
        target_date=train_context["target_date"],
    )
    assert result["context"]["ranking_universe"] == 221
    assert len(result["predictions"]) == 5
    assert [item["rank"] for item in result["predictions"]] == [1, 2, 3, 4, 5]
    # The natural TRAIN fixture ranks diseases outside the 20-record medical KB;
    # absence from Tier 2 does not remove them from ranking.
    assert any(item["tier2"]["reason"] == "NO_MEDICAL_KNOWLEDGE" for item in result["predictions"])


class _ContributionRegistry:
    feature_order = ("age_group", "temperature_mean_current", "humidity_mean_7d")
    feature_schema = {
        "features": [
            {"feature": "age_group", "feature_group": "DEMOGRAPHIC", "human_label": "Nhóm tuổi"},
            {"feature": "temperature_mean_current", "feature_group": "WEATHER_CURRENT", "human_label": "Nhiệt độ — hiện tại"},
            {"feature": "humidity_mean_7d", "feature_group": "WEATHER_7D", "human_label": "Độ ẩm — 7 ngày gần đây"},
        ]
    }

    def local_contributions(self, disease_id, features):
        return np.asarray([0.7, 0.4, -0.2]), -1.0, 0.0


def test_05_local_shap_direction_up_and_down():
    service = Tier1ExplanationService(_ContributionRegistry())
    result = service.explain(
        "5",
        pd.DataFrame([[0, 30.0, 80.0]], columns=_ContributionRegistry.feature_order),
        {"age_group": "1-5 tuổi", "temperature_mean_current": 30.0, "humidity_mean_7d": 80.0},
    )
    by_feature = {
        factor["feature"]: factor
        for factor in [*result["positive_factors"], *result["negative_factors"]]
    }
    assert by_feature["temperature_mean_current"]["direction"] == "UP"
    assert by_feature["humidity_mean_7d"]["direction"] == "DOWN"


def _record(status: str, allowed: bool = True, disease_id: str = "5") -> dict:
    return {
        "disease_id": disease_id,
        "medical_evidence_status": status,
        "runtime_tier2_display_allowed": allowed,
        "weather_factor": "temperature; precipitation",
        "relationship_type": "ENVIRONMENTAL_EXPOSURE",
        "medical_explanation_short_vi": "Giải thích có nguồn.",
        "limitations_vi": "Chỉ là liên hệ thống kê.",
        "source_1_title": "Source",
        "source_1_organization": "WHO",
        "source_1_url": "https://www.who.int/example",
        "source_1_year": 2025,
    }


def _weather_factor(value: float = 0.4, factor: str = "temperature") -> dict:
    return {
        "feature": "temperature_mean_current",
        "label_vi": "Nhiệt độ — hiện tại",
        "category": "WEATHER",
        "window": "CURRENT",
        "input_value": 30.0,
        "shap_value": value,
        "direction": "UP" if value > 0 else "DOWN",
        "weather_factor": factor,
    }


@pytest.mark.parametrize("status", ["SUPPORTED", "LIMITED_OR_INDIRECT"])
def test_06_07_supported_or_limited_valid_gates_enable_tier2(status):
    service = MedicalKnowledgeService.from_records([_record(status)])
    result = service.explain("5", [_weather_factor()])
    assert result["available"] is True
    assert result["evidence_status"] == status
    assert result["matched_weather_factor"] == "temperature"


@pytest.mark.parametrize("status", ["INSUFFICIENT", "CONFLICTING"])
def test_08_09_insufficient_or_conflicting_disables_tier2(status):
    service = MedicalKnowledgeService.from_records([_record(status)])
    result = service.explain("5", [_weather_factor()])
    assert result["available"] is False
    assert result["reason"] == "EVIDENCE_NOT_DISPLAYABLE"


def test_10_disease_without_knowledge_keeps_tier1_contract():
    service = MedicalKnowledgeService.from_records([_record("SUPPORTED")])
    result = service.explain("999", [_weather_factor()])
    assert result["available"] is False
    assert result["reason"] == "NO_MEDICAL_KNOWLEDGE"


def test_11_negative_weather_shap_cannot_trigger_tier2():
    service = MedicalKnowledgeService.from_records([_record("SUPPORTED")])
    result = service.explain("5", [_weather_factor(-0.4)])
    assert result["available"] is False
    assert result["reason"] == "NO_MATCHING_POSITIVE_WEATHER_FACTOR"


def test_12_missing_medical_kb_does_not_break_ranking(registry, train_context, tmp_path):
    missing = MedicalKnowledgeService(tmp_path / "missing.json")
    service = WeatherAIRuntimeService(registry, missing)
    result = service.predict(
        train_context["age_group"],
        train_context["gender"],
        top_k=1,
        weather=train_context["weather"],
        target_date=train_context["target_date"],
    )
    assert len(result["predictions"]) == 1
    assert result["predictions"][0]["tier1"]["available"] is True
    assert result["predictions"][0]["tier2"] == {
        "available": False,
        "reason": "MEDICAL_KB_ERROR",
        "evidence_status": None,
        "relationship_type": None,
        "matched_weather_factor": None,
        "explanation_short_vi": None,
        "limitations_vi": None,
        "sources": [],
    }


def test_runtime_display_allowed_is_a_hard_gate():
    service = MedicalKnowledgeService.from_records([_record("SUPPORTED", allowed=False)])
    result = service.explain("5", [_weather_factor()])
    assert result["available"] is False
    assert result["reason"] == "RUNTIME_DISPLAY_NOT_ALLOWED"


def test_weather_factor_must_match_record():
    service = MedicalKnowledgeService.from_records([_record("SUPPORTED")])
    result = service.explain("5", [_weather_factor(factor="wind")])
    assert result["available"] is False
    assert result["reason"] == "NO_MATCHING_POSITIVE_WEATHER_FACTOR"
