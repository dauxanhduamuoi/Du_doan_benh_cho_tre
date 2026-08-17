from __future__ import annotations

import logging
import time
from datetime import date
from functools import lru_cache
from typing import Any

import numpy as np

from app.config import (
    WEATHER_AI_V3_CATEGORY_MAPPINGS,
    WEATHER_AI_V3_DEPLOYMENT_DIR,
    WEATHER_AI_V3_DISEASE_CATALOG,
    WEATHER_AI_V3_EXPECTED_MODEL_COUNT,
    WEATHER_AI_V3_FEATURE_SCHEMA,
    WEATHER_AI_V3_MEDICAL_KB,
    WEATHER_AI_V3_MODEL_MANIFEST,
)
from app.services.weather_ai_explanations import (
    MedicalKnowledgeService,
    Tier1ExplanationService,
)
from app.services.weather_ai_features import (
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_TIMEZONE,
    WeatherFeatureBuilder,
)
from app.services.weather_ai_runtime import LightGBMModelRegistry, ModelRuntimeError


logger = logging.getLogger(__name__)
DISCLAIMER = (
    "Thông tin này nhằm hỗ trợ theo dõi và phòng ngừa, "
    "không thay thế chẩn đoán của bác sĩ."
)
MODEL_RUNTIME_WEATHER_NOTE = (
    "Model được huấn luyện bằng lịch sử thời tiết TP.HCM; weather tại context hiện tại "
    "được dùng để xếp hạng tương đối các nhóm bệnh."
)


@lru_cache(maxsize=1)
def get_model_registry() -> LightGBMModelRegistry:
    return LightGBMModelRegistry(
        deployment_dir=WEATHER_AI_V3_DEPLOYMENT_DIR,
        manifest_path=WEATHER_AI_V3_MODEL_MANIFEST,
        feature_schema_path=WEATHER_AI_V3_FEATURE_SCHEMA,
        category_mappings_path=WEATHER_AI_V3_CATEGORY_MAPPINGS,
        disease_catalog_path=WEATHER_AI_V3_DISEASE_CATALOG,
        expected_model_count=WEATHER_AI_V3_EXPECTED_MODEL_COUNT,
    )


@lru_cache(maxsize=1)
def get_medical_knowledge_service() -> MedicalKnowledgeService:
    return MedicalKnowledgeService(WEATHER_AI_V3_MEDICAL_KB)


class WeatherAIRuntimeService:
    """Orchestrates input -> features -> 221-model ranking -> Tier 1 -> Tier 2."""

    def __init__(
        self,
        registry: LightGBMModelRegistry,
        medical_knowledge: MedicalKnowledgeService,
    ) -> None:
        self.registry = registry
        self.medical_knowledge = medical_knowledge
        self.registry.load()
        self.feature_builder = WeatherFeatureBuilder(
            list(self.registry.feature_order), self.registry.category_mappings
        )
        self.tier1 = Tier1ExplanationService(self.registry)

    @staticmethod
    def _tier1_unavailable() -> dict[str, Any]:
        return {
            "available": False,
            "summary_vi": None,
            "positive_factors": [],
            "negative_factors": [],
            "base_value_raw": None,
            "additivity_max_abs_error": None,
            "error": "EXPLANATION_ERROR",
        }

    @staticmethod
    def _tier2_unavailable(reason: str) -> dict[str, Any]:
        return {
            "available": False,
            "reason": reason,
            "evidence_status": None,
            "relationship_type": None,
            "matched_weather_factor": None,
            "explanation_short_vi": None,
            "limitations_vi": None,
            "sources": [],
        }

    def predict(
        self,
        age_group: str,
        gender: str,
        top_k: int = 5,
        weather: dict[str, Any] | None = None,
        latitude: float | None = DEFAULT_LATITUDE,
        longitude: float | None = DEFAULT_LONGITUDE,
        timezone: str = DEFAULT_TIMEZONE,
        target_date: date | None = None,
    ) -> dict[str, Any]:
        total_started = time.perf_counter()
        requested_top_k = int(top_k)
        if requested_top_k < 1 or requested_top_k > 20:
            raise ValueError("top_k phải nằm trong khoảng 1..20.")

        feature_started = time.perf_counter()
        prepared = self.feature_builder.prepare(
            age_group=age_group,
            gender=gender,
            weather=weather,
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            target_date=target_date,
        )
        feature_seconds = time.perf_counter() - feature_started

        prediction_started = time.perf_counter()
        scores = self.registry.predict_scores(prepared.encoded)
        prediction_seconds = time.perf_counter() - prediction_started
        if len(scores) != WEATHER_AI_V3_EXPECTED_MODEL_COUNT:
            raise ModelRuntimeError("Inference không trả đủ 221 disease scores.")
        order = np.argsort(-scores, kind="stable")
        selected_indices = order[:requested_top_k]

        predictions: list[dict[str, Any]] = []
        tier1_seconds = 0.0
        tier2_seconds = 0.0
        for rank, disease_index in enumerate(selected_indices, start=1):
            disease_id = self.registry.disease_order[int(disease_index)]
            disease = self.registry.disease_catalog[disease_id]
            tier1_started = time.perf_counter()
            try:
                tier1 = self.tier1.explain(disease_id, prepared.encoded, prepared.raw)
            except Exception:
                logger.exception("Tier 1 explanation failed for disease_id=%s", disease_id)
                tier1 = self._tier1_unavailable()
            tier1_seconds += time.perf_counter() - tier1_started

            tier2_started = time.perf_counter()
            if tier1["available"]:
                tier2 = self.medical_knowledge.explain(
                    disease_id, tier1["positive_factors"]
                )
            else:
                tier2 = self._tier2_unavailable("TIER1_UNAVAILABLE")
            tier2_seconds += time.perf_counter() - tier2_started

            predictions.append(
                {
                    "rank": rank,
                    "disease_id": disease_id,
                    "disease_name": str(disease.get("disease_group_name") or ""),
                    "disease_group_id": disease_id,
                    "disease_group_name": str(disease.get("disease_group_name") or ""),
                    "report_group_code": str(disease.get("report_group_code") or ""),
                    "ranking_score": float(scores[int(disease_index)]),
                    "tier1": tier1,
                    "tier2": tier2,
                }
            )

        total_seconds = time.perf_counter() - total_started
        runtime_ms = {
            "feature_preparation": round(feature_seconds * 1000, 3),
            "ranking_221_models": round(prediction_seconds * 1000, 3),
            "tier1_top_k": round(tier1_seconds * 1000, 3),
            "tier2_top_k": round(tier2_seconds * 1000, 3),
            "total": round(total_seconds * 1000, 3),
        }
        return {
            "message": (
                "Model xếp hạng các nhóm bệnh thường được ghi nhận trong những trường hợp "
                "có tuổi, giới tính và điều kiện thời tiết tương tự."
            ),
            "context": {
                "age_group": prepared.raw["age_group"],
                "gender": prepared.raw["gender"],
                "anchor_date": str(prepared.anchor_date),
                "horizon": "H14",
                "top_k": requested_top_k,
                "ranking_universe": len(self.registry.disease_order),
            },
            "input": {
                "age_group": prepared.raw["age_group"],
                "gender": prepared.raw["gender"],
                "top_k": requested_top_k,
            },
            "weather": {
                "meta": prepared.weather_meta,
                "features": {
                    feature: prepared.raw[feature]
                    for feature in self.registry.feature_order
                    if feature not in {"age_group", "gender"}
                },
            },
            "predictions": predictions,
            # Existing endpoint clients can keep reading top_risks; records now expose
            # ranking_score and structured explanations instead of pseudo-probabilities.
            "top_risks": predictions,
            "model": {
                "model_type": "LightGBM One-vs-Rest",
                "horizon": "H14",
                "with_weather": True,
                "model_count": len(self.registry.disease_order),
                "score_semantics": "relative_ranking_score_not_calibrated_probability",
                "runtime_weather_note": MODEL_RUNTIME_WEATHER_NOTE,
            },
            "runtime_ms": runtime_ms,
            "disclaimer": DISCLAIMER,
        }


@lru_cache(maxsize=1)
def get_runtime_service() -> WeatherAIRuntimeService:
    return WeatherAIRuntimeService(get_model_registry(), get_medical_knowledge_service())


def initialize_weather_ai_runtime() -> dict[str, Any]:
    service = get_runtime_service()
    service.medical_knowledge.load()
    if service.medical_knowledge.error:
        logger.error(
            "Weather AI started without Tier 2 knowledge: %s",
            service.medical_knowledge.error,
        )
    return get_model_status()


def get_model_status() -> dict[str, Any]:
    try:
        registry_status = get_model_registry().status()
    except Exception as exc:
        return {"ready": False, "error": str(exc), "expected_model_count": 221}
    medical = get_medical_knowledge_service()
    medical.load()
    return {
        **registry_status,
        "age_groups": list(get_model_registry().category_mappings["age_group"]),
        "genders": list(get_model_registry().category_mappings["gender"]),
        "disease_groups": registry_status["model_count"],
        "medical_knowledge_ready": medical.available,
        "medical_knowledge_records": medical.record_count,
        "medical_knowledge_error": medical.error,
    }


def get_weather_ai_options() -> dict[str, Any]:
    registry = get_model_registry()
    registry.load()
    return {
        "age_groups": list(registry.category_mappings["age_group"]),
        "genders": list(registry.category_mappings["gender"]),
        "disease_catalog": [
            {
                "disease_id": disease_id,
                "disease_name": registry.disease_catalog[disease_id]["disease_group_name"],
                "disease_group_id": disease_id,
                "disease_group_name": registry.disease_catalog[disease_id]["disease_group_name"],
                "report_group_code": registry.disease_catalog[disease_id]["report_group_code"],
            }
            for disease_id in registry.disease_order
        ],
        "ranking_universe": len(registry.disease_order),
    }


def predict_weather_risk(
    age_group: str,
    gender: str,
    top_k: int = 5,
    weather: dict[str, Any] | None = None,
    latitude: float | None = DEFAULT_LATITUDE,
    longitude: float | None = DEFAULT_LONGITUDE,
    timezone: str = DEFAULT_TIMEZONE,
    target_date: date | None = None,
) -> dict[str, Any]:
    return get_runtime_service().predict(
        age_group=age_group,
        gender=gender,
        top_k=top_k,
        weather=weather,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        target_date=target_date,
    )
