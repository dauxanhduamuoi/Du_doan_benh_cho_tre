"""Input validation and feature-schema utilities for offline model training."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import catboost
from catboost.utils import get_gpu_device_count

from src.data.io import sha256_file


TARGET_COLUMN = "disease_group_id"
WEIGHT_COLUMN = "case_count"
CATEGORICAL_FEATURES = ["age_group", "gender", "season", "weather_code"]
EXCLUDED_FEATURE_COLUMNS = {
    "date",
    WEIGHT_COLUMN,
    "disease_group_name",
    "report_group_code",
    TARGET_COLUMN,
}
FORBIDDEN_PERSONAL_TOKENS = (
    "date_of_birth",
    "birth_date",
    "ngay_sinh",
    "ngày_sinh",
    "address",
    "full_address",
    "dia_chi",
    "địa_chỉ",
    "icd",
)
EXPERIMENT_WINDOWS = {
    "current_only": (1,),
    "current_plus_3d": (1, 3),
    "current_plus_3d_7d": (1, 3, 7),
    "current_plus_3d_7d_14d": (1, 3, 7, 14),
}
EXPERIMENT_LABELS = {
    "current_only": "A = current_only",
    "current_plus_3d": "B = current + 3d",
    "current_plus_3d_7d": "C = current + 3d + 7d",
    "current_plus_3d_7d_14d": "D = current + 3d + 7d + 14d",
}
REQUIRED_INPUTS = (
    "data/processed/weather_disease_multiclass.csv.gz",
    "data/processed/disease_catalog.csv",
    "data/processed/dataset_metadata.json",
    "data/splits/train.csv.gz",
    "data/splits/validation.csv.gz",
    "data/splits/test.csv.gz",
    "data/splits/split_metadata.json",
    "reports/DATA_PREPARATION_REPORT.md",
)


@dataclass
class TrainingData:
    dataset: pd.DataFrame
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    catalog: pd.DataFrame
    dataset_metadata: dict[str, Any]
    split_metadata: dict[str, Any]
    input_columns: list[str]
    universe_classes: list[str]
    unsupported_validation: list[str]
    unsupported_test: list[str]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def nvidia_smi_output() -> str:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,driver_version,memory.total,memory.free",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"nvidia-smi unavailable: {exc}"
    output = (completed.stdout or completed.stderr).strip()
    return output or f"nvidia-smi exited with code {completed.returncode}"


def environment_diagnostics(project_root: Path) -> dict[str, Any]:
    return {
        "python_version": sys.version,
        "catboost_version": catboost.__version__,
        "pandas_version": pd.__version__,
        "gpu_device_count": int(get_gpu_device_count()),
        "nvidia_smi": nvidia_smi_output(),
        "project_root": str(project_root.resolve()),
    }


def _read_dataset(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={TARGET_COLUMN: "string"})
    if frame.empty:
        raise ValueError(f"Dataset is empty: {path}")
    frame[TARGET_COLUMN] = frame[TARGET_COLUMN].astype("string").str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame[WEIGHT_COLUMN] = pd.to_numeric(frame[WEIGHT_COLUMN], errors="raise")
    return frame


def _date_set(frame: pd.DataFrame) -> set[pd.Timestamp]:
    return set(pd.to_datetime(frame["date"]).dt.normalize())


def validate_and_load_inputs(project_root: Path) -> TrainingData:
    missing = [relative for relative in REQUIRED_INPUTS if not (project_root / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"Required training artifacts are missing: {missing}")

    dataset_path = project_root / REQUIRED_INPUTS[0]
    catalog_path = project_root / REQUIRED_INPUTS[1]
    dataset_metadata_path = project_root / REQUIRED_INPUTS[2]
    split_metadata_path = project_root / "data/splits/split_metadata.json"
    dataset_metadata = read_json(dataset_metadata_path)
    split_metadata = read_json(split_metadata_path)

    expected_hash = dataset_metadata.get("files", {}).get("dataset", {}).get("sha256")
    if expected_hash and sha256_file(dataset_path) != expected_hash:
        raise ValueError("Processed dataset checksum does not match dataset_metadata.json")

    dataset = _read_dataset(dataset_path)
    train = _read_dataset(project_root / "data/splits/train.csv.gz")
    validation = _read_dataset(project_root / "data/splits/validation.csv.gz")
    test = _read_dataset(project_root / "data/splits/test.csv.gz")
    catalog = pd.read_csv(catalog_path, dtype={TARGET_COLUMN: "string"})
    catalog[TARGET_COLUMN] = catalog[TARGET_COLUMN].astype("string").str.strip()

    input_columns = list(dataset_metadata.get("input_columns", []))
    if not input_columns:
        raise ValueError("dataset_metadata.json has no input_columns")
    forbidden_inputs = sorted(set(input_columns) & EXCLUDED_FEATURE_COLUMNS)
    if forbidden_inputs:
        raise ValueError(f"Forbidden columns found in feature input: {forbidden_inputs}")
    missing_features = [column for column in input_columns if column not in dataset.columns]
    if missing_features:
        raise ValueError(f"Feature columns are missing from dataset: {missing_features}")

    forbidden_personal = [
        column
        for column in dataset.columns
        if any(token in column.lower() for token in FORBIDDEN_PERSONAL_TOKENS)
    ]
    if forbidden_personal:
        raise ValueError(f"Personal or encounter ICD columns are forbidden: {forbidden_personal}")

    date_sets = [_date_set(frame) for frame in (train, validation, test)]
    overlaps = {
        "train_validation": len(date_sets[0] & date_sets[1]),
        "train_test": len(date_sets[0] & date_sets[2]),
        "validation_test": len(date_sets[1] & date_sets[2]),
    }
    if any(overlaps.values()):
        raise ValueError(f"Date overlap detected between splits: {overlaps}")

    split_case_count = sum(int(frame[WEIGHT_COLUMN].sum()) for frame in (train, validation, test))
    dataset_case_count = int(dataset[WEIGHT_COLUMN].sum())
    if split_case_count != dataset_case_count:
        raise ValueError(
            f"Split case_count {split_case_count} does not equal dataset total {dataset_case_count}"
        )
    if dataset_case_count != int(dataset_metadata.get("total_case_count", -1)):
        raise ValueError("Dataset case_count does not match dataset metadata")

    split_rows = len(train) + len(validation) + len(test)
    if split_rows != len(dataset):
        raise ValueError(f"Split rows {split_rows} do not equal dataset rows {len(dataset)}")

    train_classes = set(train[TARGET_COLUMN].dropna().astype(str))
    validation_classes = set(validation[TARGET_COLUMN].dropna().astype(str))
    test_classes = set(test[TARGET_COLUMN].dropna().astype(str))
    universe = sorted(
        set(catalog[TARGET_COLUMN].dropna().astype(str))
        | set(dataset[TARGET_COLUMN].dropna().astype(str))
    )
    unsupported_validation = sorted(validation_classes - train_classes)
    unsupported_test = sorted(test_classes - train_classes)

    recorded = split_metadata.get("unseen_disease_groups", {})
    if set(unsupported_validation) != set(recorded.get("validation_not_in_train", [])):
        raise ValueError("Unsupported validation classes differ from split_metadata.json")
    if set(unsupported_test) != set(recorded.get("test_not_in_train", [])):
        raise ValueError("Unsupported test classes differ from split_metadata.json")

    return TrainingData(
        dataset=dataset,
        train=train,
        validation=validation,
        test=test,
        catalog=catalog,
        dataset_metadata=dataset_metadata,
        split_metadata=split_metadata,
        input_columns=input_columns,
        universe_classes=universe,
        unsupported_validation=unsupported_validation,
        unsupported_test=unsupported_test,
    )


def experiment_feature_sets(input_columns: list[str]) -> dict[str, list[str]]:
    window_pattern = re.compile(r"_(1|3|7|14)d$")
    base = [column for column in input_columns if window_pattern.search(column) is None]
    results: dict[str, list[str]] = {}
    for name, windows in EXPERIMENT_WINDOWS.items():
        allowed = set(windows)
        selected = list(base)
        selected.extend(
            column
            for column in input_columns
            if (match := window_pattern.search(column)) is not None
            and int(match.group(1)) in allowed
        )
        results[name] = selected
    return results


def prepare_features(frame: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    features = frame[feature_columns].copy()
    for column in feature_columns:
        if column in CATEGORICAL_FEATURES:
            features[column] = features[column].astype("string").fillna("__MISSING__").astype(str)
        else:
            features[column] = pd.to_numeric(features[column], errors="coerce")
    return features
