from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from threading import RLock
from typing import Any

import pandas as pd

from app.services.weather_ai_runtime import LightGBMModelRegistry


logger = logging.getLogger(__name__)
DISPLAYABLE_EVIDENCE = {"SUPPORTED", "LIMITED_OR_INDIRECT"}


def normalize_weather_factor(value: str) -> str | None:
    """Central mapping between locked feature names and medical KB factors."""
    text = str(value or "").strip().lower()
    if "temperature" in text or "nhiệt độ" in text:
        return "temperature"
    if "humidity" in text or "độ ẩm" in text:
        return "humidity"
    if "precipitation" in text or "rain" in text or "mưa" in text:
        return "precipitation"
    if "wind" in text or "gió" in text:
        return "wind"
    if "weather_code" in text or "weather code" in text or "trạng thái thời tiết" in text:
        return "weather_code"
    return None


def feature_window(feature: str) -> str:
    if feature.endswith("_current"):
        return "CURRENT"
    if feature.endswith("_3d"):
        return "3D"
    if feature.endswith("_7d"):
        return "7D"
    return "NONE"


class Tier1ExplanationService:
    def __init__(self, registry: LightGBMModelRegistry, max_factors_each_direction: int = 5) -> None:
        self.registry = registry
        self.max_factors_each_direction = max_factors_each_direction
        schema = registry.feature_schema
        self._metadata = {
            str(item["feature"]): item for item in schema.get("features", [])
        }

    def _factor(
        self,
        feature: str,
        input_value: Any,
        shap_value: float,
    ) -> dict[str, Any]:
        metadata = self._metadata.get(feature, {})
        feature_group = str(metadata.get("feature_group", ""))
        if feature_group.startswith("WEATHER"):
            category = "WEATHER"
        elif feature_group == "DEMOGRAPHIC":
            category = "DEMOGRAPHIC"
        else:
            category = "SEASONAL_CALENDAR"
        return {
            "feature": feature,
            "label_vi": str(metadata.get("human_label") or feature),
            "category": category,
            "window": feature_window(feature),
            "input_value": input_value,
            "shap_value": float(shap_value),
            "direction": "UP" if shap_value > 0 else "DOWN",
            "weather_factor": normalize_weather_factor(feature) if category == "WEATHER" else None,
        }

    @staticmethod
    def _summary(positive_factors: list[dict[str, Any]]) -> str:
        labels: list[str] = []
        for factor in positive_factors:
            label = str(factor["label_vi"])
            if label not in labels:
                labels.append(label)
            if len(labels) == 3:
                break
        if not labels:
            return "Không có feature dương đủ rõ để mô tả lý do điểm xếp hạng tăng trong context này."
        if len(labels) == 1:
            subject = labels[0]
        else:
            subject = ", ".join(labels[:-1]) + " và " + labels[-1]
        return f"{subject} đang góp phần làm nhóm bệnh này được model xếp hạng cao hơn."

    def explain(
        self,
        disease_id: str,
        encoded_features: pd.DataFrame,
        raw_features: dict[str, Any],
    ) -> dict[str, Any]:
        values, base_value, additivity_error = self.registry.local_contributions(
            disease_id, encoded_features
        )
        factors = [
            self._factor(feature, raw_features[feature], float(values[index]))
            for index, feature in enumerate(self.registry.feature_order)
            if abs(float(values[index])) > 1e-12
        ]
        positive = sorted(
            (factor for factor in factors if factor["shap_value"] > 0),
            key=lambda factor: factor["shap_value"],
            reverse=True,
        )[: self.max_factors_each_direction]
        negative = sorted(
            (factor for factor in factors if factor["shap_value"] < 0),
            key=lambda factor: abs(factor["shap_value"]),
            reverse=True,
        )[: self.max_factors_each_direction]
        return {
            "available": True,
            "summary_vi": self._summary(positive),
            "positive_factors": positive,
            "negative_factors": negative,
            "base_value_raw": base_value,
            "additivity_max_abs_error": additivity_error,
            "error": None,
        }


class MedicalKnowledgeService:
    """Process-local, read-once Tier 2 knowledge index with graceful failure."""

    def __init__(self, knowledge_path: Path | None = None) -> None:
        self.knowledge_path = knowledge_path
        self._lock = RLock()
        self._load_attempted = False
        self._records: dict[str, dict[str, Any]] = {}
        self._error: str | None = None

    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> "MedicalKnowledgeService":
        service = cls(None)
        service._records = {str(record["disease_id"]): dict(record) for record in records}
        service._load_attempted = True
        return service

    @staticmethod
    def _validate_record(record: dict[str, Any]) -> None:
        required = {
            "disease_id",
            "medical_evidence_status",
            "runtime_tier2_display_allowed",
            "weather_factor",
            "medical_explanation_short_vi",
            "limitations_vi",
        }
        missing = sorted(required - set(record))
        if missing:
            raise ValueError(f"Medical KB record thiếu fields: {missing}")

    def load(self) -> None:
        if self._load_attempted:
            return
        with self._lock:
            if self._load_attempted:
                return
            try:
                if self.knowledge_path is None or not self.knowledge_path.is_file():
                    raise FileNotFoundError(f"Không tìm thấy medical knowledge base: {self.knowledge_path}")
                payload = json.loads(self.knowledge_path.read_text(encoding="utf-8"))
                records = payload.get("records")
                if not isinstance(records, list):
                    raise ValueError("Medical knowledge base không có records array.")
                indexed: dict[str, dict[str, Any]] = {}
                for record in records:
                    if not isinstance(record, dict):
                        raise ValueError("Medical KB record phải là object.")
                    self._validate_record(record)
                    disease_id = str(record["disease_id"])
                    if disease_id in indexed:
                        raise ValueError(f"Medical KB trùng disease_id={disease_id}")
                    indexed[disease_id] = record
                self._records = indexed
            except Exception as exc:
                self._error = str(exc)
                self._records = {}
                logger.error("Medical knowledge unavailable: %s", exc)
            finally:
                self._load_attempted = True

    @property
    def available(self) -> bool:
        self.load()
        return self._error is None

    @property
    def error(self) -> str | None:
        self.load()
        return self._error

    @property
    def record_count(self) -> int:
        self.load()
        return len(self._records)

    @staticmethod
    def _unavailable(reason: str, evidence_status: str | None = None) -> dict[str, Any]:
        return {
            "available": False,
            "reason": reason,
            "evidence_status": evidence_status,
            "relationship_type": None,
            "matched_weather_factor": None,
            "explanation_short_vi": None,
            "limitations_vi": None,
            "sources": [],
        }

    @staticmethod
    def _record_factors(record: dict[str, Any]) -> set[str]:
        tokens = re.split(r"[;,/|]", str(record.get("weather_factor", "")))
        return {factor for token in tokens if (factor := normalize_weather_factor(token))}

    @staticmethod
    def _sources(record: dict[str, Any]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for index in (1, 2, 3):
            url = str(record.get(f"source_{index}_url") or "").strip()
            if not url:
                continue
            sources.append(
                {
                    "title": str(record.get(f"source_{index}_title") or ""),
                    "organization": str(record.get(f"source_{index}_organization") or ""),
                    "url": url,
                    "year": int(record[f"source_{index}_year"])
                    if str(record.get(f"source_{index}_year") or "").strip()
                    else None,
                }
            )
        return sources

    def explain(
        self,
        disease_id: str,
        positive_factors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.load()
        if self._error is not None:
            return self._unavailable("MEDICAL_KB_ERROR")
        record = self._records.get(str(disease_id))
        if record is None:
            return self._unavailable("NO_MEDICAL_KNOWLEDGE")
        evidence_status = str(record.get("medical_evidence_status") or "")
        if evidence_status not in DISPLAYABLE_EVIDENCE:
            return self._unavailable("EVIDENCE_NOT_DISPLAYABLE", evidence_status)
        if record.get("runtime_tier2_display_allowed") is not True:
            return self._unavailable("RUNTIME_DISPLAY_NOT_ALLOWED", evidence_status)
        supported_factors = self._record_factors(record)
        matches = [
            factor
            for factor in positive_factors
            if factor.get("category") == "WEATHER"
            and float(factor.get("shap_value", 0)) > 0
            and factor.get("weather_factor") in supported_factors
        ]
        if not matches:
            return self._unavailable("NO_MATCHING_POSITIVE_WEATHER_FACTOR", evidence_status)
        matched = max(matches, key=lambda factor: float(factor["shap_value"]))
        sources = self._sources(record)
        if not sources:
            return self._unavailable("MEDICAL_SOURCE_UNAVAILABLE", evidence_status)
        return {
            "available": True,
            "reason": None,
            "evidence_status": evidence_status,
            "relationship_type": record.get("relationship_type") or None,
            "matched_weather_factor": matched["weather_factor"],
            "explanation_short_vi": record.get("medical_explanation_short_vi"),
            "limitations_vi": record.get("limitations_vi"),
            "sources": sources,
        }
