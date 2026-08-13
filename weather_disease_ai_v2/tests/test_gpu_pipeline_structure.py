from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.models.common import EXPERIMENT_WINDOWS, experiment_feature_sets
from src.models.evaluation import select_best_experiment
from src.models.metrics import per_class_metrics
from src.models.training import GPUTrainingConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_gpu_config_refuses_cpu_fallback() -> None:
    with pytest.raises(ValueError, match="GPU-only"):
        GPUTrainingConfig(device="CPU")


def test_four_experiments_use_cumulative_window_subsets() -> None:
    metadata = json.loads(
        (PROJECT_ROOT / "data/processed/dataset_metadata.json").read_text(encoding="utf-8")
    )
    feature_sets = experiment_feature_sets(metadata["input_columns"])
    assert list(feature_sets) == list(EXPERIMENT_WINDOWS)
    assert [len(feature_sets[name]) for name in feature_sets] == [20, 33, 46, 59]


def test_selection_uses_only_validation_metrics() -> None:
    results = []
    for index, (name, windows) in enumerate(EXPERIMENT_WINDOWS.items()):
        results.append(
            {
                "experiment": name,
                "windows": list(windows),
                "feature_count": 20 + 13 * index,
                "validation_metrics": {
                    "case_weighted": {
                        "top_5_accuracy": 0.50 + index * 0.01,
                        "multiclass_log_loss": 2.0 - index * 0.1,
                    }
                },
            }
        )
    selected, reason = select_best_experiment(results)
    assert selected["experiment"] == "current_plus_3d_7d_14d"
    assert "test" not in " ".join(selected.keys()).lower()
    assert "No test prediction" in reason


def test_notebook_has_thirteen_pipeline_cells_and_no_absolute_user_path() -> None:
    notebook_path = PROJECT_ROOT / "notebooks/01_train_weather_disease_catboost_v2.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert len(code_cells) == 13
    source = "\n".join("".join(cell["source"]) for cell in code_cells)
    for number in range(1, 14):
        assert f"Cell {number}" in source
    assert "C:\\Users\\LENOVO" not in source
    assert "TrainingPipeline" in source


def test_per_class_metrics_tolerates_duplicate_catalog_ids() -> None:
    train = pd.DataFrame({"disease_group_id": ["19"], "case_count": [2]})
    evaluation = pd.DataFrame({"disease_group_id": ["19"], "case_count": [1]})
    catalog = pd.DataFrame(
        {
            "disease_group_id": ["19", "19"],
            "disease_group_name": ["first", "second"],
        }
    )
    result = per_class_metrics(
        train, evaluation, np.array([[1.0]]), ["19"], catalog, "validation"
    )
    assert len(result) == 1
    assert result.loc[0, "disease_group_name"] == "first"
