from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier

from src.models.common import EXCLUDED_FEATURE_COLUMNS, prepare_features
from src.models.metrics import top_k_predictions


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "models"


def load_json(name: str) -> dict:
    path = MODELS_DIR / name
    assert path.is_file(), f"Missing model artifact; run scripts/04_train_model.py: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def load_model() -> CatBoostClassifier:
    path = MODELS_DIR / "weather_disease_catboost_v2.cbm"
    assert path.is_file(), f"Missing trained model: {path}"
    model = CatBoostClassifier()
    model.load_model(path)
    return model


def reference_input() -> tuple[pd.DataFrame, np.ndarray]:
    metadata = load_json("model_metadata.json")
    schema = load_json("feature_schema.json")
    frame = pd.DataFrame(metadata["serialization_check"]["sample_input"])
    features = prepare_features(frame, schema["feature_columns"])
    expected = np.asarray(
        metadata["serialization_check"]["expected_probabilities"], dtype=float
    )
    return features, expected


def test_model_loads_and_output_class_count_matches_mapping() -> None:
    model = load_model()
    mapping = load_json("class_mapping.json")
    features, _ = reference_input()
    probability = model.predict_proba(features)
    assert probability.shape[1] == mapping["model_class_count"]
    assert probability.shape[1] == len(model.classes_)
    assert [str(value) for value in model.classes_] == mapping["model_classes"]


def test_prediction_probabilities_sum_to_one() -> None:
    model = load_model()
    features, _ = reference_input()
    probability = model.predict_proba(features)
    np.testing.assert_allclose(probability.sum(axis=1), 1.0, atol=1e-10)


def test_top_k_maps_to_catalog_names() -> None:
    model = load_model()
    mapping = load_json("class_mapping.json")
    features, _ = reference_input()
    probability = model.predict_proba(features.iloc[:1])
    lookup = {
        row["disease_group_id"]: row for row in mapping["classes"]
    }
    predictions = top_k_predictions(
        probability,
        [str(value) for value in model.classes_],
        lookup,
        5,
    )[0]
    assert len(predictions) == 5
    for prediction in predictions:
        expected = lookup[prediction["disease_group_id"]]["disease_group_name"]
        assert prediction["disease_group_name"] == expected


def test_feature_schema_contains_no_target_description_or_weight() -> None:
    schema = load_json("feature_schema.json")
    assert not set(schema["feature_columns"]) & EXCLUDED_FEATURE_COLUMNS
    assert schema["target_column"] not in schema["feature_columns"]
    assert schema["weight_column"] not in schema["feature_columns"]


def test_selection_uses_validation_and_never_test() -> None:
    selection = load_json("model_selection.json")
    assert selection["selection_split"] == "validation"
    assert selection["test_metrics_read_or_used_for_selection"] is False
    assert selection["test_rows_scored_during_selection"] == 0
    assert "test" not in selection["selection_rules"]["primary"]


def test_predictions_match_pre_save_reference() -> None:
    model = load_model()
    features, expected = reference_input()
    actual = model.predict_proba(features)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12)
