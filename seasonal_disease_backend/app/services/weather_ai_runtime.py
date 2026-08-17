from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from pathlib import Path
from threading import RLock
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


class ModelRuntimeError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LightGBMModelRegistry:
    """Process-local immutable registry for the locked 221 LightGBM boosters."""

    def __init__(
        self,
        deployment_dir: Path,
        manifest_path: Path,
        feature_schema_path: Path,
        category_mappings_path: Path,
        disease_catalog_path: Path,
        expected_model_count: int = 221,
    ) -> None:
        self.deployment_dir = deployment_dir
        self.manifest_path = manifest_path
        self.feature_schema_path = feature_schema_path
        self.category_mappings_path = category_mappings_path
        self.disease_catalog_path = disease_catalog_path
        self.expected_model_count = expected_model_count
        self._load_lock = RLock()
        self._predict_lock = RLock()
        self._loaded = False
        self._manifest: dict[str, Any] = {}
        self._models: dict[str, lgb.Booster] = {}
        self._disease_order: tuple[str, ...] = ()
        self._feature_order: tuple[str, ...] = ()
        self._feature_schema: dict[str, Any] = {}
        self._category_mappings: dict[str, dict[str, int]] = {}
        self._disease_catalog: dict[str, dict[str, str]] = {}
        self._load_seconds = 0.0

    @staticmethod
    def _read_json(path: Path, label: str) -> dict[str, Any]:
        if not path.is_file():
            raise ModelRuntimeError(f"Thiếu {label}: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ModelRuntimeError(f"Không đọc được {label}: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ModelRuntimeError(f"{label} phải là JSON object: {path}")
        return payload

    def _load_catalog(self) -> dict[str, dict[str, str]]:
        if not self.disease_catalog_path.is_file():
            raise ModelRuntimeError(f"Thiếu disease catalog: {self.disease_catalog_path}")
        with self.disease_catalog_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        catalog = {str(row["disease_group_id"]): row for row in rows}
        missing = [disease_id for disease_id in self._disease_order if disease_id not in catalog]
        if missing:
            raise ModelRuntimeError(f"Disease catalog thiếu model-supported IDs: {missing[:10]}")
        return catalog

    def load(self) -> None:
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            started = time.perf_counter()
            manifest = self._read_json(self.manifest_path, "model manifest")
            feature_schema = self._read_json(self.feature_schema_path, "feature schema")
            category_mappings = self._read_json(self.category_mappings_path, "category mappings")
            model_entries = manifest.get("models")
            disease_order = tuple(str(value) for value in manifest.get("disease_order", []))
            feature_order = tuple(str(value) for value in manifest.get("feature_order", []))
            if manifest.get("model_count") != self.expected_model_count:
                raise ModelRuntimeError(
                    f"Manifest model_count={manifest.get('model_count')}, expected={self.expected_model_count}."
                )
            if not isinstance(model_entries, list) or len(model_entries) != self.expected_model_count:
                raise ModelRuntimeError("Manifest không chứa đúng 221 model entries.")
            if len(disease_order) != self.expected_model_count or len(set(disease_order)) != len(disease_order):
                raise ModelRuntimeError("Disease order trong manifest không hợp lệ.")
            if tuple(str(value) for value in feature_schema.get("feature_order", [])) != feature_order:
                raise ModelRuntimeError("Feature schema và manifest không cùng feature order.")
            if feature_schema.get("feature_count") != len(feature_order) or len(feature_order) != 45:
                raise ModelRuntimeError("Locked V3 runtime phải có đúng 45 features.")
            for categorical in ("age_group", "gender", "season"):
                mapping = category_mappings.get(categorical)
                if not isinstance(mapping, dict) or not mapping:
                    raise ModelRuntimeError(f"Category mapping không hợp lệ: {categorical}")

            models: dict[str, lgb.Booster] = {}
            entry_order: list[str] = []
            for index, entry in enumerate(model_entries):
                disease_id = str(entry.get("disease_id", ""))
                entry_order.append(disease_id)
                relative_path = Path(str(entry.get("model_path", "")))
                model_path = (self.deployment_dir / relative_path).resolve()
                try:
                    model_path.relative_to(self.deployment_dir.resolve())
                except ValueError as exc:
                    raise ModelRuntimeError(f"Model path ra ngoài deployment dir: {relative_path}") from exc
                if not model_path.is_file():
                    raise ModelRuntimeError(f"Thiếu model {disease_id}: {model_path}")
                if model_path.stat().st_size != int(entry.get("bytes", -1)):
                    raise ModelRuntimeError(f"Model size mismatch: disease {disease_id}")
                if sha256_file(model_path) != entry.get("sha256"):
                    raise ModelRuntimeError(f"Model checksum mismatch: disease {disease_id}")
                try:
                    booster = lgb.Booster(model_str=model_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise ModelRuntimeError(f"Không load được model disease {disease_id}: {exc}") from exc
                if booster.num_feature() != len(feature_order):
                    raise ModelRuntimeError(f"Model disease {disease_id} có sai feature count.")
                models[disease_id] = booster
                if index != int(entry.get("index", -1)):
                    raise ModelRuntimeError(f"Manifest index mismatch tại disease {disease_id}.")
            if tuple(entry_order) != disease_order or len(models) != self.expected_model_count:
                raise ModelRuntimeError("Model entry order/count khác disease order đã khóa.")

            self._manifest = manifest
            self._disease_order = disease_order
            self._feature_order = feature_order
            self._feature_schema = feature_schema
            self._category_mappings = {
                key: {str(label): int(value) for label, value in mapping.items()}
                for key, mapping in category_mappings.items()
            }
            self._disease_catalog = self._load_catalog()
            self._models = models
            self._load_seconds = time.perf_counter() - started
            self._loaded = True
            logger.info(
                "Weather AI V3 registry loaded: models=%s features=%s seconds=%.3f",
                len(models),
                len(feature_order),
                self._load_seconds,
            )

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def disease_order(self) -> tuple[str, ...]:
        self.load()
        return self._disease_order

    @property
    def feature_order(self) -> tuple[str, ...]:
        self.load()
        return self._feature_order

    @property
    def feature_schema(self) -> dict[str, Any]:
        self.load()
        return self._feature_schema

    @property
    def category_mappings(self) -> dict[str, dict[str, int]]:
        self.load()
        return self._category_mappings

    @property
    def disease_catalog(self) -> dict[str, dict[str, str]]:
        self.load()
        return self._disease_catalog

    @property
    def load_seconds(self) -> float:
        return self._load_seconds

    def status(self) -> dict[str, Any]:
        self.load()
        return {
            "ready": True,
            "model_type": self._manifest.get("model"),
            "horizon": "H14",
            "with_weather": True,
            "model_count": len(self._models),
            "feature_count": len(self._feature_order),
            "load_seconds": self._load_seconds,
            "manifest_verified": True,
        }

    def _validate_frame(self, features: pd.DataFrame) -> None:
        if list(features.columns) != list(self.feature_order):
            raise ModelRuntimeError("Inference feature order khác locked manifest.")
        if len(features) != 1:
            raise ModelRuntimeError("Runtime API chỉ chấp nhận một context mỗi request.")

    def predict_scores(self, features: pd.DataFrame) -> np.ndarray:
        self.load()
        self._validate_frame(features)
        scores = np.empty(len(self._disease_order), dtype=np.float64)
        try:
            with self._predict_lock:
                for index, disease_id in enumerate(self._disease_order):
                    scores[index] = float(self._models[disease_id].predict(features)[0])
        except Exception as exc:
            raise ModelRuntimeError(f"LightGBM inference thất bại: {exc}") from exc
        if not np.isfinite(scores).all():
            raise ModelRuntimeError("LightGBM trả ranking score không hữu hạn.")
        return scores

    def local_contributions(
        self, disease_id: str, features: pd.DataFrame
    ) -> tuple[np.ndarray, float, float]:
        self.load()
        self._validate_frame(features)
        model = self._models.get(str(disease_id))
        if model is None:
            raise ModelRuntimeError(f"Disease không có model: {disease_id}")
        try:
            with self._predict_lock:
                values = np.asarray(model.predict(features, pred_contrib=True), dtype=np.float64)
                raw_score = float(model.predict(features, raw_score=True)[0])
        except Exception as exc:
            raise ModelRuntimeError(f"Local SHAP thất bại cho disease {disease_id}: {exc}") from exc
        if values.shape != (1, len(self._feature_order) + 1):
            raise ModelRuntimeError(f"Local SHAP shape không hợp lệ cho disease {disease_id}: {values.shape}")
        contributions = values[0, :-1]
        base_value = float(values[0, -1])
        additivity_error = abs(float(contributions.sum() + base_value) - raw_score)
        if additivity_error > 1e-6:
            raise ModelRuntimeError(
                f"Local SHAP additivity fail cho disease {disease_id}: {additivity_error}"
            )
        return contributions, base_value, additivity_error
