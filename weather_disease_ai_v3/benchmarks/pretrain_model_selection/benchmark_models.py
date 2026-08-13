"""Small, isolated H7 GPU benchmark for V3 model-family selection.

This script does not full-train H3/H7/H14, read TEST, modify processed data,
run SHAP, or create an official model.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import catboost
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRanker, Pool


BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.baseline import FrequencyRankingBaseline  # noqa: E402


CONFIG_PATH = BENCHMARK_DIR / "benchmark_config.json"
RESULTS_PATH = BENCHMARK_DIR / "benchmark_results.csv"
REPORT_PATH = BENCHMARK_DIR / "BENCHMARK_REPORT.md"
LOG_DIR = BENCHMARK_DIR / "logs"
ARTIFACT_DIR = BENCHMARK_DIR / "artifacts"
LOG_PATH = LOG_DIR / "benchmark.log"
GPU_LOG_PATH = LOG_DIR / "gpu_samples.csv"

CONTEXTS_PATH = PROJECT_ROOT / "data/processed/contexts.csv.gz"
TARGETS_PATH = PROJECT_ROOT / "data/processed/targets.csv.gz"
CATALOG_PATH = PROJECT_ROOT / "data/processed/disease_catalog.csv"
METADATA_PATH = PROJECT_ROOT / "data/processed/dataset_metadata.json"
TRAIN_IDS_PATH = PROJECT_ROOT / "data/splits/train_query_ids.csv"
VALIDATION_IDS_PATH = PROJECT_ROOT / "data/splits/validation_query_ids.csv"
SPLIT_METADATA_PATH = PROJECT_ROOT / "data/splits/split_metadata.json"


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pretrain_model_selection")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


LOGGER = setup_logging()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def assert_source_hashes(config: dict[str, Any]) -> dict[str, str]:
    actual: dict[str, str] = {}
    for relative, expected in config["source_sha256"].items():
        path = PROJECT_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing immutable benchmark source: {path}")
        value = sha256_file(path)
        actual[relative] = value
        if value != expected:
            raise RuntimeError(
                f"Processed source checksum changed before benchmark: {relative}; "
                f"expected={expected}, actual={value}"
            )
    return actual


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def query_gpu() -> tuple[str, float, float]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
        "--id=0",
    ]
    output = subprocess.check_output(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creation_flags(),
    ).strip()
    row = next(csv.reader([output]))
    return row[0].strip(), float(row[1]), float(row[2])


@dataclass
class GpuMonitor:
    phase: str
    interval_seconds: float
    samples: list[dict[str, Any]] = field(default_factory=list)
    baseline_memory_mib: float | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        _, memory, utilization = query_gpu()
        self.baseline_memory_mib = memory
        self.samples.append(
            {
                "phase": self.phase,
                "elapsed_seconds": 0.0,
                "memory_used_mib": memory,
                "gpu_utilization_percent": utilization,
            }
        )
        started = time.perf_counter()

        def poll() -> None:
            while not self._stop.wait(self.interval_seconds):
                try:
                    _, used, util = query_gpu()
                    self.samples.append(
                        {
                            "phase": self.phase,
                            "elapsed_seconds": time.perf_counter() - started,
                            "memory_used_mib": used,
                            "gpu_utilization_percent": util,
                        }
                    )
                except Exception as exc:  # monitoring must not mask model result
                    LOGGER.warning("GPU monitor sample failed for %s: %s", self.phase, exc)

        self._thread = threading.Thread(target=poll, daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, float | None]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_seconds * 3))
        if not self.samples:
            return {
                "peak_vram_mib": None,
                "peak_total_gpu_memory_mib": None,
                "mean_gpu_utilization_percent": None,
            }
        memories = [float(sample["memory_used_mib"]) for sample in self.samples]
        utilizations = [float(sample["gpu_utilization_percent"]) for sample in self.samples]
        baseline = float(self.baseline_memory_mib or memories[0])
        return {
            "peak_vram_mib": max(0.0, max(memories) - baseline),
            "peak_total_gpu_memory_mib": max(memories),
            "mean_gpu_utilization_percent": float(np.mean(utilizations)),
        }


def append_gpu_samples(samples: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(samples)
    if frame.empty:
        return
    header = not GPU_LOG_PATH.exists()
    frame.to_csv(GPU_LOG_PATH, mode="a", header=header, index=False)


def deterministic_subset(ids: pd.DataFrame, fraction: float, seed: int) -> pd.DataFrame:
    count = max(1, int(round(len(ids) * float(fraction))))
    result = ids.sample(n=count, random_state=seed, replace=False)
    return result.sort_values("query_id", kind="mergesort").reset_index(drop=True)


def augment_and_order_for_label_coverage(
    base_sample: pd.DataFrame,
    all_train_ids: pd.DataFrame,
    targets: pd.DataFrame,
    disease_ids: list[str],
    smoke_query_count: int,
) -> tuple[pd.DataFrame, int]:
    """Add the minimum practical query coverage and place a cover in smoke rows."""
    train_universe = set(all_train_ids["query_id"].astype(str))
    positive = targets.loc[
        targets["query_id"].isin(train_universe)
        & targets["disease_group_id"].isin(disease_ids)
        & (targets["has_case_h7"] == 1),
        ["query_id", "disease_group_id"],
    ].drop_duplicates()
    labels_by_query = {
        str(query_id): set(group["disease_group_id"].astype(str))
        for query_id, group in positive.groupby("query_id", sort=True)
    }
    sample_ids = base_sample["query_id"].astype(str).tolist()
    sample_set = set(sample_ids)
    covered = set().union(*(labels_by_query.get(query_id, set()) for query_id in sample_ids))
    missing = set(disease_ids) - covered
    added: list[str] = []
    while missing:
        candidates = [
            (len(labels & missing), query_id)
            for query_id, labels in labels_by_query.items()
            if query_id not in sample_set and labels & missing
        ]
        if not candidates:
            raise RuntimeError(f"Cannot cover supported H7 labels in benchmark TRAIN: {sorted(missing)}")
        best_coverage = max(value for value, _ in candidates)
        chosen = min(query_id for value, query_id in candidates if value == best_coverage)
        sample_ids.append(chosen)
        sample_set.add(chosen)
        added.append(chosen)
        missing -= labels_by_query[chosen]

    uncovered = set(disease_ids)
    cover_order: list[str] = []
    while uncovered:
        candidates = [
            (len(labels_by_query.get(query_id, set()) & uncovered), query_id)
            for query_id in sample_ids
            if query_id not in cover_order and labels_by_query.get(query_id, set()) & uncovered
        ]
        best_coverage = max(value for value, _ in candidates)
        chosen = min(query_id for value, query_id in candidates if value == best_coverage)
        cover_order.append(chosen)
        uncovered -= labels_by_query[chosen]
    if len(cover_order) > smoke_query_count:
        raise RuntimeError(
            f"Smoke size {smoke_query_count} cannot cover {len(disease_ids)} labels; "
            f"minimum query cover is {len(cover_order)}"
        )
    remaining = [query_id for query_id in sample_ids if query_id not in set(cover_order)]
    ordered = cover_order + remaining
    result = pd.DataFrame({"query_id": ordered})
    return result, len(added)


def sorted_disease_ids(values: set[str]) -> list[str]:
    def key(value: str) -> tuple[int, int | str]:
        return (0, int(value)) if value.isdigit() else (1, value)

    return sorted((str(value) for value in values), key=key)


def prepare_common_features(frame: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    output = frame[feature_columns].copy()
    for column in ("age_group", "gender", "season"):
        output[column] = output[column].fillna("Không rõ").astype(str)
    output["month"] = pd.to_numeric(output["month"], errors="raise").astype("int16")
    return output


def build_target_matrix(
    query_ids: list[str],
    disease_ids: list[str],
    targets: pd.DataFrame,
) -> np.ndarray:
    query_index = {value: index for index, value in enumerate(query_ids)}
    disease_index = {value: index for index, value in enumerate(disease_ids)}
    matrix = np.zeros((len(query_ids), len(disease_ids)), dtype=np.uint8)
    positive = targets.loc[
        (targets["has_case_h7"] == 1)
        & targets["query_id"].isin(query_index)
        & targets["disease_group_id"].isin(disease_index),
        ["query_id", "disease_group_id"],
    ]
    for query_id, disease_id in positive.itertuples(index=False):
        matrix[query_index[str(query_id)], disease_index[str(disease_id)]] = 1
    return matrix


def positive_sets_from_matrix(
    query_ids: list[str], disease_ids: list[str], matrix: np.ndarray
) -> dict[str, set[str]]:
    return {
        query_id: {disease_ids[index] for index in np.flatnonzero(matrix[row_index])}
        for row_index, query_id in enumerate(query_ids)
    }


def ranking_metrics_from_scores(
    query_ids: list[str],
    disease_ids: list[str],
    positives: dict[str, set[str]],
    scores: np.ndarray,
) -> dict[str, float | int]:
    score_array = np.asarray(scores)
    if score_array.shape != (len(query_ids), len(disease_ids)):
        raise ValueError(
            f"Unexpected score shape {score_array.shape}; "
            f"expected {(len(query_ids), len(disease_ids))}"
        )
    order = np.argsort(-score_array, axis=1, kind="stable")
    records: list[dict[str, float]] = []
    for row_index, query_id in enumerate(query_ids):
        relevant = positives[query_id]
        if not relevant:
            continue
        ranked = [disease_ids[index] for index in order[row_index]]
        record: dict[str, float] = {}
        for k in (5, 10):
            top = ranked[:k]
            hits = sum(label in relevant for label in top)
            dcg = sum(
                1.0 / math.log2(position + 2)
                for position, label in enumerate(top)
                if label in relevant
            )
            ideal_hits = min(len(relevant), k)
            ideal = sum(1.0 / math.log2(position + 2) for position in range(ideal_hits))
            record[f"precision_at_{k}"] = hits / k
            record[f"recall_at_{k}"] = hits / len(relevant)
            record[f"ndcg_at_{k}"] = dcg / ideal if ideal else float("nan")
        records.append(record)
    if not records:
        raise ValueError("Benchmark validation subset has no H7 positive query")
    frame = pd.DataFrame(records)
    result: dict[str, float | int] = {
        column: float(frame[column].mean()) for column in frame.columns
    }
    result["evaluated_validation_queries"] = int(len(frame))
    result["validation_queries_without_positive_h7"] = int(len(query_ids) - len(frame))
    return result


def ranking_metrics_from_rankings(
    query_ids: list[str],
    disease_ids: list[str],
    positives: dict[str, set[str]],
    rankings: list[list[str]],
) -> dict[str, float | int]:
    disease_index = {value: index for index, value in enumerate(disease_ids)}
    scores = np.full((len(query_ids), len(disease_ids)), -np.inf, dtype=np.float32)
    for row_index, ranking in enumerate(rankings):
        for position, disease_id in enumerate(ranking):
            scores[row_index, disease_index[disease_id]] = -float(position)
    return ranking_metrics_from_scores(query_ids, disease_ids, positives, scores)


def expand_ranker_features(
    context_features: pd.DataFrame,
    target_matrix: np.ndarray,
    disease_ids: list[str],
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    disease_count = len(disease_ids)
    expanded = context_features.loc[
        context_features.index.repeat(disease_count)
    ].reset_index(drop=True)
    expanded["disease_group_id"] = np.tile(np.asarray(disease_ids, dtype=object), len(context_features))
    labels = np.asarray(target_matrix, dtype=np.float32).reshape(-1)
    group_id = np.repeat(np.arange(len(context_features), dtype=np.int64), disease_count)
    return expanded, labels, group_id


def model_result_template(algorithm: str) -> dict[str, Any]:
    return {
        "algorithm": algorithm,
        "status": "not_run",
        "smoke_test_status": "not_run",
        "error": "",
        "catboost_version": catboost.__version__,
        "gpu_name": "",
        "train_query_count": 0,
        "validation_query_count": 0,
        "disease_count": 0,
        "feature_rows": 0,
        "validation_feature_rows": 0,
        "expanded_candidate_rows": 0,
        "target_shape": "",
        "iterations": 0,
        "elapsed_training_seconds": float("nan"),
        "elapsed_prediction_seconds": float("nan"),
        "peak_vram_mib": float("nan"),
        "peak_total_gpu_memory_mib": float("nan"),
        "mean_gpu_utilization_percent": float("nan"),
        "model_artifact_size_bytes": 0,
        "precision_at_5": float("nan"),
        "recall_at_5": float("nan"),
        "ndcg_at_5": float("nan"),
        "precision_at_10": float("nan"),
        "recall_at_10": float("nan"),
        "ndcg_at_10": float("nan"),
        "evaluated_validation_queries": 0,
        "validation_queries_without_positive_h7": 0,
    }


def monitored_fit(
    phase: str,
    interval: float,
    fit_callable: Callable[[], None],
) -> tuple[float, dict[str, float | None]]:
    monitor = GpuMonitor(phase, interval)
    monitor.start()
    started = time.perf_counter()
    try:
        fit_callable()
    finally:
        elapsed = time.perf_counter() - started
        resources = monitor.stop()
        append_gpu_samples(monitor.samples)
    return elapsed, resources


def run_multilabel(
    config: dict[str, Any],
    train_features: pd.DataFrame,
    validation_features: pd.DataFrame,
    train_target: np.ndarray,
    validation_target: np.ndarray,
    train_query_ids: list[str],
    validation_query_ids: list[str],
    disease_ids: list[str],
    positives_validation: dict[str, set[str]],
    gpu_name: str,
) -> dict[str, Any]:
    result = model_result_template("CatBoost Multi-label")
    result.update(
        {
            "gpu_name": gpu_name,
            "train_query_count": len(train_features),
            "validation_query_count": len(validation_features),
            "disease_count": len(disease_ids),
            "feature_rows": len(train_features),
            "validation_feature_rows": len(validation_features),
            "target_shape": f"{train_target.shape[0]}x{train_target.shape[1]}",
            "iterations": int(config["multilabel"]["iterations"]),
        }
    )
    common = config["multilabel"]
    cat_features = list(config["categorical_features_common"])
    smoke_train_count = min(int(config["smoke_train_queries"]), len(train_features))
    smoke_validation_count = min(
        int(config["smoke_validation_queries"]), len(validation_features)
    )
    base_params = {
        "loss_function": common["loss_function"],
        "task_type": common["task_type"],
        "devices": common["devices"],
        "depth": int(common["depth"]),
        "learning_rate": float(common["learning_rate"]),
        "random_seed": int(config["random_seed"]),
        "allow_writing_files": bool(common["allow_writing_files"]),
        "use_best_model": False,
    }
    try:
        train_pool = Pool(train_features, label=train_target, cat_features=cat_features)
        validation_pool = Pool(
            validation_features, label=validation_target, cat_features=cat_features
        )
        smoke_train_pool = Pool(
            train_features.iloc[:smoke_train_count],
            label=train_target[:smoke_train_count],
            cat_features=cat_features,
        )
        smoke_validation_pool = Pool(
            validation_features.iloc[:smoke_validation_count],
            label=validation_target[:smoke_validation_count],
            cat_features=cat_features,
        )
        LOGGER.info("Multi-label GPU smoke test: %s train queries", smoke_train_count)
        smoke_model = CatBoostClassifier(
            **base_params,
            iterations=int(common["smoke_iterations"]),
            verbose=False,
        )
        monitored_fit(
            "multilabel_smoke",
            float(config["gpu_monitor_interval_seconds"]),
            lambda: smoke_model.fit(smoke_train_pool, eval_set=smoke_validation_pool),
        )
        smoke_path = ARTIFACT_DIR / "multilabel_smoke.cbm"
        smoke_model.save_model(smoke_path)
        loaded_smoke = CatBoostClassifier()
        loaded_smoke.load_model(smoke_path)
        smoke_prediction = np.asarray(loaded_smoke.predict_proba(smoke_validation_pool))
        if smoke_prediction.shape != (smoke_validation_count, len(disease_ids)):
            raise RuntimeError(f"Unexpected multi-label smoke prediction shape: {smoke_prediction.shape}")
        if smoke_model.get_param("task_type") != "GPU":
            raise RuntimeError("Multi-label smoke model did not preserve task_type=GPU")
        result["smoke_test_status"] = "passed_gpu_save_load_predict"
    except Exception as exc:
        result["status"] = "failed_smoke"
        result["smoke_test_status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.error("Multi-label smoke failed; 100-iteration benchmark skipped.\n%s", traceback.format_exc())
        return result

    try:
        LOGGER.info("Multi-label benchmark: 100 GPU iterations")
        model = CatBoostClassifier(
            **base_params,
            iterations=int(common["iterations"]),
            verbose=int(common["verbose"]),
        )
        elapsed, resources = monitored_fit(
            "multilabel_100_iterations",
            float(config["gpu_monitor_interval_seconds"]),
            lambda: model.fit(train_pool, eval_set=validation_pool),
        )
        artifact = ARTIFACT_DIR / "multilabel_benchmark.cbm"
        model.save_model(artifact)
        loaded = CatBoostClassifier()
        loaded.load_model(artifact)
        predict_started = time.perf_counter()
        scores = np.asarray(loaded.predict_proba(validation_pool), dtype=np.float64)
        prediction_time = time.perf_counter() - predict_started
        metrics = ranking_metrics_from_scores(
            validation_query_ids, disease_ids, positives_validation, scores
        )
        result.update(
            {
                "status": "success",
                "elapsed_training_seconds": elapsed,
                "elapsed_prediction_seconds": prediction_time,
                "model_artifact_size_bytes": artifact.stat().st_size,
                **resources,
                **metrics,
            }
        )
    except Exception as exc:
        result["status"] = "failed_benchmark"
        result["error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.error("Multi-label 100-iteration benchmark failed.\n%s", traceback.format_exc())
    return result


def run_ranker(
    config: dict[str, Any],
    train_features: pd.DataFrame,
    validation_features: pd.DataFrame,
    train_target: np.ndarray,
    validation_target: np.ndarray,
    validation_query_ids: list[str],
    disease_ids: list[str],
    positives_validation: dict[str, set[str]],
    gpu_name: str,
) -> dict[str, Any]:
    result = model_result_template("CatBoostRanker")
    disease_count = len(disease_ids)
    result.update(
        {
            "gpu_name": gpu_name,
            "train_query_count": len(train_features),
            "validation_query_count": len(validation_features),
            "disease_count": disease_count,
            "feature_rows": len(train_features) * disease_count,
            "validation_feature_rows": len(validation_features) * disease_count,
            "expanded_candidate_rows": len(train_features) * disease_count,
            "target_shape": f"{len(train_features) * disease_count}x1",
            "iterations": int(config["ranker"]["iterations"]),
        }
    )
    common = config["ranker"]
    cat_features = [*config["categorical_features_common"], "disease_group_id"]
    smoke_train_queries = min(int(config["smoke_train_queries"]), len(train_features))
    smoke_validation_queries = min(
        int(config["smoke_validation_queries"]), len(validation_features)
    )
    smoke_train_rows = smoke_train_queries * disease_count
    smoke_validation_rows = smoke_validation_queries * disease_count
    base_params = {
        "loss_function": common["loss_function"],
        "eval_metric": common["eval_metric"],
        "task_type": common["task_type"],
        "devices": common["devices"],
        "depth": int(common["depth"]),
        "learning_rate": float(common["learning_rate"]),
        "random_seed": int(config["random_seed"]),
        "allow_writing_files": bool(common["allow_writing_files"]),
        "use_best_model": False,
    }
    try:
        LOGGER.info("Expanding Ranker benchmark candidates")
        expanded_train, labels_train, groups_train = expand_ranker_features(
            train_features, train_target, disease_ids
        )
        expanded_validation, labels_validation, groups_validation = expand_ranker_features(
            validation_features, validation_target, disease_ids
        )
        train_pool = Pool(
            expanded_train,
            label=labels_train,
            group_id=groups_train,
            cat_features=cat_features,
        )
        validation_pool = Pool(
            expanded_validation,
            label=labels_validation,
            group_id=groups_validation,
            cat_features=cat_features,
        )
        smoke_train_pool = Pool(
            expanded_train.iloc[:smoke_train_rows],
            label=labels_train[:smoke_train_rows],
            group_id=groups_train[:smoke_train_rows],
            cat_features=cat_features,
        )
        smoke_validation_pool = Pool(
            expanded_validation.iloc[:smoke_validation_rows],
            label=labels_validation[:smoke_validation_rows],
            group_id=groups_validation[:smoke_validation_rows],
            cat_features=cat_features,
        )
        LOGGER.info("Ranker GPU smoke test: %s expanded rows", smoke_train_rows)
        smoke_model = CatBoostRanker(
            **base_params,
            iterations=int(common["smoke_iterations"]),
            verbose=False,
        )
        monitored_fit(
            "ranker_smoke",
            float(config["gpu_monitor_interval_seconds"]),
            lambda: smoke_model.fit(smoke_train_pool, eval_set=smoke_validation_pool),
        )
        smoke_path = ARTIFACT_DIR / "ranker_smoke.cbm"
        smoke_model.save_model(smoke_path)
        loaded_smoke = CatBoostRanker()
        loaded_smoke.load_model(smoke_path)
        smoke_prediction = np.asarray(loaded_smoke.predict(smoke_validation_pool))
        if smoke_prediction.shape != (smoke_validation_rows,):
            raise RuntimeError(f"Unexpected Ranker smoke prediction shape: {smoke_prediction.shape}")
        if smoke_model.get_param("task_type") != "GPU":
            raise RuntimeError("Ranker smoke model did not preserve task_type=GPU")
        result["smoke_test_status"] = "passed_gpu_save_load_predict"
    except Exception as exc:
        result["status"] = "failed_smoke"
        result["smoke_test_status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.error("Ranker smoke failed; 100-iteration benchmark skipped.\n%s", traceback.format_exc())
        return result

    try:
        LOGGER.info("Ranker benchmark: 100 GPU iterations")
        model = CatBoostRanker(
            **base_params,
            iterations=int(common["iterations"]),
            verbose=int(common["verbose"]),
        )
        elapsed, resources = monitored_fit(
            "ranker_100_iterations",
            float(config["gpu_monitor_interval_seconds"]),
            lambda: model.fit(train_pool, eval_set=validation_pool),
        )
        artifact = ARTIFACT_DIR / "ranker_benchmark.cbm"
        model.save_model(artifact)
        loaded = CatBoostRanker()
        loaded.load_model(artifact)
        predict_started = time.perf_counter()
        flat_scores = np.asarray(loaded.predict(validation_pool), dtype=np.float64)
        prediction_time = time.perf_counter() - predict_started
        scores = flat_scores.reshape(len(validation_features), disease_count)
        metrics = ranking_metrics_from_scores(
            validation_query_ids, disease_ids, positives_validation, scores
        )
        result.update(
            {
                "status": "success",
                "elapsed_training_seconds": elapsed,
                "elapsed_prediction_seconds": prediction_time,
                "model_artifact_size_bytes": artifact.stat().st_size,
                **resources,
                **metrics,
            }
        )
    except Exception as exc:
        result["status"] = "failed_benchmark"
        result["error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.error("Ranker 100-iteration benchmark failed.\n%s", traceback.format_exc())
    finally:
        del expanded_train, expanded_validation, labels_train, labels_validation
    return result


def run_baseline(
    benchmark_train_contexts: pd.DataFrame,
    benchmark_validation_contexts: pd.DataFrame,
    targets: pd.DataFrame,
    disease_ids: list[str],
    validation_query_ids: list[str],
    positives_validation: dict[str, set[str]],
    gpu_name: str,
) -> dict[str, Any]:
    result = model_result_template("Frequency baseline")
    result.update(
        {
            "status": "success",
            "smoke_test_status": "not_applicable",
            "gpu_name": gpu_name,
            "train_query_count": len(benchmark_train_contexts),
            "validation_query_count": len(benchmark_validation_contexts),
            "disease_count": len(disease_ids),
            "feature_rows": len(benchmark_train_contexts),
            "target_shape": "train-only hierarchical frequency",
            "iterations": 0,
        }
    )
    train_ids = set(benchmark_train_contexts["query_id"].astype(str))
    train_targets = targets[targets["query_id"].isin(train_ids)]
    baseline = FrequencyRankingBaseline.fit_train(
        benchmark_train_contexts,
        train_targets,
        disease_ids,
        7,
        split_name="train",
    )
    started = time.perf_counter()
    rankings = [
        baseline.rank(row, top_k=len(disease_ids))
        for _, row in benchmark_validation_contexts.iterrows()
    ]
    result["elapsed_prediction_seconds"] = time.perf_counter() - started
    metrics = ranking_metrics_from_rankings(
        validation_query_ids,
        disease_ids,
        positives_validation,
        rankings,
    )
    result.update(metrics)
    return result


def fmt(value: Any, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "N/A"
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def size_mib(value: Any) -> str:
    if not value:
        return "N/A"
    return f"{float(value) / (1024 * 1024):.2f} MiB"


def choose_algorithm(results: dict[str, dict[str, Any]]) -> tuple[str, str]:
    multilabel = results["multilabel"]
    ranker = results["ranker"]
    baseline = results["baseline"]
    ml_ok = multilabel["status"] == "success"
    rank_ok = ranker["status"] == "success"
    if ml_ok and rank_ok:
        ndcg_gain = float(ranker["ndcg_at_5"]) - float(multilabel["ndcg_at_5"])
        rank_cost_ok = (
            float(ranker["elapsed_training_seconds"])
            <= 3.0 * float(multilabel["elapsed_training_seconds"])
            and float(ranker["peak_vram_mib"]) <= 7500
        )
        if ndcg_gain >= 0.02 and rank_cost_ok:
            recommendation = "CatBoostRanker (YetiRank)"
            reason = (
                f"Ranker tăng NDCG@5 tuyệt đối {ndcg_gain:.4f} so với Multi-label, "
                "đủ ngưỡng tín hiệu 0.02 và chi phí benchmark vẫn trong giới hạn đã đặt."
            )
        else:
            recommendation = (
                "CatBoost Multi-label Classification (MultiLogloss) — "
                "hướng nghiên cứu có điều kiện, chưa phê duyệt full train"
            )
            reason = (
                f"Multi-label cao hơn Ranker {abs(ndcg_gain):.4f} NDCG@5, giữ đúng một row/query "
                f"và tránh expand {int(ranker['expanded_candidate_rows']):,} rows. Tuy nhiên, "
                "Multi-label chậm, dùng VRAM sát trần 8GB và chưa vượt baseline ở headline @5, "
                "nên chưa đủ điều kiện để full train."
            )
        reason += (
            f" Baseline NDCG@5={float(baseline['ndcg_at_5']):.4f}; "
            f"Multi-label={float(multilabel['ndcg_at_5']):.4f}; "
            f"Ranker={float(ranker['ndcg_at_5']):.4f}."
        )
        return recommendation, reason
    if ml_ok:
        return (
            "CatBoost Multi-label Classification (MultiLogloss)",
            "Multi-label hoàn tất smoke/benchmark GPU; Ranker không hoàn tất. Không có CPU fallback.",
        )
    if rank_ok:
        return (
            "CatBoostRanker (YetiRank)",
            "Ranker hoàn tất smoke/benchmark GPU; Multi-label không hoàn tất. Không có CPU fallback.",
        )
    return (
        "Chưa chọn được",
        "Cả hai GPU benchmark đều không hoàn tất; cần xử lý lỗi thật trước bước full train.",
    )


def estimate_times(
    recommended: str,
    results: dict[str, dict[str, Any]],
    full_train_queries: int,
    benchmark_train_queries: int,
) -> tuple[str, str]:
    key = "ranker" if recommended.startswith("CatBoostRanker") else "multilabel"
    selected = results[key]
    if selected["status"] != "success":
        return "Không thể ước lượng", "Không thể ước lượng"
    linear_seconds = float(selected["elapsed_training_seconds"]) * (
        full_train_queries / benchmark_train_queries
    )
    low = linear_seconds * 0.75
    high = linear_seconds * 1.50
    one = f"khoảng {low / 60:.1f}–{high / 60:.1f} phút (linear center {linear_seconds / 60:.1f} phút)"
    three = f"khoảng {3 * low / 60:.1f}–{3 * high / 60:.1f} phút (3× linear center {3 * linear_seconds / 60:.1f} phút)"
    return one, three


def write_report(
    config: dict[str, Any],
    results: dict[str, dict[str, Any]],
    supported_count: int,
    train_count: int,
    validation_count: int,
    full_train_queries: int,
    recommendation: str,
    reason: str,
    estimate_one: str,
    estimate_three: str,
    source_hashes_unchanged: bool,
    coverage_queries_added: int,
) -> None:
    ml = results["multilabel"]
    ranker = results["ranker"]
    baseline = results["baseline"]
    report = [
        "# H7 Pre-train Model Selection Benchmark",
        "",
        "> Đây là benchmark tạm 10% TRAIN/VALIDATION, 100 iterations trên H7. Không phải full train, không dùng TEST, không SHAP và không tạo model chính thức.",
        "",
        "## Phạm vi khóa",
        "",
        f"- CatBoost: `{catboost.__version__}`; GPU: `{ml.get('gpu_name') or ranker.get('gpu_name')}`.",
        f"- Benchmark TRAIN: {train_count:,}/{full_train_queries:,} query; VALIDATION: {validation_count:,} query.",
        f"- TRAIN bắt đầu từ sample 10% deterministic và bổ sung {coverage_queries_added} query để mọi model-supported H7 label có ít nhất một positive; cùng subset cuối được dùng cho cả hai algorithm.",
        f"- Model-supported disease từ toàn TRAIN, positive ở ít nhất một H3/H7/H14: **{supported_count}**.",
        "- Disease unsupported vẫn nằm trong catalog gốc; benchmark-local snapshot chỉ thêm cờ `model_supported`.",
        "- Month là calendar month dạng numeric; categorical dùng `age_group`, `gender`, `season`; Ranker thêm `disease_group_id`.",
        "- Baseline học prior từ đúng benchmark TRAIN subset để so sánh cùng lượng query, không dùng weather/VALIDATION/TEST.",
        f"- Validation metric tính trên {int(baseline['evaluated_validation_queries']):,} query có ít nhất một positive H7 trong disease universe; {int(baseline['validation_queries_without_positive_h7']):,} query zero-positive được loại khỏi mean metric.",
        "",
        "## Kết quả chung",
        "",
        "| Metric | Multi-label | Ranker | Baseline |",
        "|---|---:|---:|---:|",
        f"| Status | {ml['status']} | {ranker['status']} | {baseline['status']} |",
        f"| GPU smoke 10 iter | {ml['smoke_test_status']} | {ranker['smoke_test_status']} | N/A |",
        f"| Feature/train rows | {fmt(ml['feature_rows'])} | {fmt(ranker['feature_rows'])} | {fmt(baseline['feature_rows'])} |",
        f"| Expanded rows | 0 | {fmt(ranker['expanded_candidate_rows'])} | 0 |",
        f"| Disease labels | {fmt(ml['disease_count'])} | {fmt(ranker['disease_count'])} | {fmt(baseline['disease_count'])} |",
        f"| Target shape | {ml['target_shape']} | {ranker['target_shape']} | {baseline['target_shape']} |",
        f"| Train time 100 iter | {fmt(ml['elapsed_training_seconds'], 3)} s | {fmt(ranker['elapsed_training_seconds'], 3)} s | N/A |",
        f"| Prediction time | {fmt(ml['elapsed_prediction_seconds'], 3)} s | {fmt(ranker['elapsed_prediction_seconds'], 3)} s | {fmt(baseline['elapsed_prediction_seconds'], 3)} s |",
        f"| Peak VRAM delta | {fmt(ml['peak_vram_mib'], 1)} MiB | {fmt(ranker['peak_vram_mib'], 1)} MiB | N/A |",
        f"| Peak total GPU memory observed | {fmt(ml['peak_total_gpu_memory_mib'], 1)} MiB | {fmt(ranker['peak_total_gpu_memory_mib'], 1)} MiB | N/A |",
        f"| Mean GPU utilization observed | {fmt(ml['mean_gpu_utilization_percent'], 1)}% | {fmt(ranker['mean_gpu_utilization_percent'], 1)}% | N/A |",
        f"| Precision@5 | {fmt(ml['precision_at_5'])} | {fmt(ranker['precision_at_5'])} | {fmt(baseline['precision_at_5'])} |",
        f"| Recall@5 | {fmt(ml['recall_at_5'])} | {fmt(ranker['recall_at_5'])} | {fmt(baseline['recall_at_5'])} |",
        f"| NDCG@5 | {fmt(ml['ndcg_at_5'])} | {fmt(ranker['ndcg_at_5'])} | {fmt(baseline['ndcg_at_5'])} |",
        f"| Precision@10 | {fmt(ml['precision_at_10'])} | {fmt(ranker['precision_at_10'])} | {fmt(baseline['precision_at_10'])} |",
        f"| Recall@10 | {fmt(ml['recall_at_10'])} | {fmt(ranker['recall_at_10'])} | {fmt(baseline['recall_at_10'])} |",
        f"| NDCG@10 | {fmt(ml['ndcg_at_10'])} | {fmt(ranker['ndcg_at_10'])} | {fmt(baseline['ndcg_at_10'])} |",
        f"| Model size | {size_mib(ml['model_artifact_size_bytes'])} | {size_mib(ranker['model_artifact_size_bytes'])} | N/A |",
        "",
        "`Peak VRAM delta` là chênh lệch giữa peak `nvidia-smi memory.used` và mức ngay trước phase train; `Peak total` và GPU utilization là số quan sát toàn GPU, nên có thể gồm tải nền khác.",
        "Ranker chạy sau Multi-label đúng thứ tự yêu cầu trong cùng Python/CUDA process, nên thời gian Ranker có thể được lợi từ CUDA/kernel cache đã warm; không diễn giải 2 thời gian như cold-start tuyệt đối.",
        "",
        "## GPU/API verification",
        "",
        "Smoke test bắt buộc `task_type=GPU`, save/load artifact và predict. Nếu smoke thất bại, script không chạy 100 iterations cho algorithm đó và không fallback CPU.",
    ]
    if ml["error"]:
        report.extend(["", f"- Multi-label error thật: `{ml['error']}`"])
    if ranker["error"]:
        report.extend(["", f"- Ranker error thật: `{ranker['error']}`"])
    report.extend(
        [
            "",
            "## Khuyến nghị",
            "",
            f"**Recommended algorithm:** {recommendation}",
            "",
            f"**Reason:** {reason}",
            "",
            "**Decision gate:** Không model nào vượt baseline ở cả ba headline metric @5. Multi-label chỉ có tín hiệu nhỉnh hơn baseline ở Precision@10/NDCG@10, còn Ranker kém baseline rõ. Vì vậy khuyến nghị trên chỉ chọn hướng nghiên cứu tốt hơn giữa A/B, không phải phê duyệt full train.",
            "",
            "Multi-label bám sát target vector nhiều disease và có inference một row/query; Ranker bám trực tiếp objective xếp hạng nhưng phải expand query × disease. Khả năng SHAP của hướng được chọn vẫn phải được kiểm chứng ở bước riêng sau này; benchmark này không chạy SHAP.",
            "",
            "Trên laptop RTX 5060 8GB, peak total quan sát 7,818 MiB của Multi-label chỉ còn rất ít headroom; full TRAIN có rủi ro OOM/không ổn định. Ranker nhẹ hơn về model và nhanh hơn trong run này nhưng full candidate rows tăng xấp xỉ 10× và metric H7 hiện chưa đạt baseline.",
            "",
            f"**Ước lượng full-train 1 horizon:** {estimate_one}.",
            "",
            f"**Ước lượng H3+H7+H14:** {estimate_three}.",
            "",
            "Các khoảng trên chỉ ngoại suy tuyến tính từ benchmark 10%; startup GPU, dữ liệu lớn hơn và I/O có thể làm thời gian thực tế phi tuyến. Đây không phải cam kết thời gian.",
            "",
            "## Integrity và phạm vi artifact",
            "",
            f"- Processed/split source checksum không đổi sau benchmark: **{'PASS' if source_hashes_unchanged else 'FAIL'}**.",
            "- TEST không được đọc hoặc dùng.",
            "- Mọi query sample, support snapshot, model tạm và log nằm trong `benchmarks/pretrain_model_selection/`.",
            "- Không có model nào được copy sang `models/`, `data/processed/`, `reports/` hoặc `src/`.",
            "",
            "**CHƯA FULL TRAIN MODEL. Benchmark dừng sau 100 iterations H7.**",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    if GPU_LOG_PATH.exists():
        GPU_LOG_PATH.unlink()
    config = read_config()
    source_hashes_before = assert_source_hashes(config)
    gpu_name, initial_gpu_memory, _ = query_gpu()
    LOGGER.info("Workspace: %s", PROJECT_ROOT)
    LOGGER.info("CatBoost %s; GPU=%s; initial memory=%.0f MiB", catboost.__version__, gpu_name, initial_gpu_memory)

    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    feature_columns = list(metadata["model_feature_columns"])
    forbidden = [
        column
        for column in feature_columns
        if column in {"query_id", "anchor_date", "year"}
        or any(token in column.lower() for token in ("disease", "target", "has_case", "case_count"))
    ]
    if forbidden:
        raise RuntimeError(f"Forbidden model feature columns: {forbidden}")

    contexts = pd.read_csv(CONTEXTS_PATH, dtype={"query_id": str})
    targets = pd.read_csv(
        TARGETS_PATH,
        dtype={"query_id": str, "disease_group_id": str},
    )
    catalog = pd.read_csv(CATALOG_PATH, dtype={"disease_group_id": str})
    train_ids_all = pd.read_csv(TRAIN_IDS_PATH, dtype={"query_id": str})
    validation_ids_all = pd.read_csv(VALIDATION_IDS_PATH, dtype={"query_id": str})
    if set(train_ids_all["query_id"]) & set(validation_ids_all["query_id"]):
        raise RuntimeError("TRAIN and VALIDATION query IDs overlap")

    train_target_rows = targets[targets["query_id"].isin(set(train_ids_all["query_id"]))]
    supported_mask = train_target_rows[
        ["has_case_h3", "has_case_h7", "has_case_h14"]
    ].max(axis=1) > 0
    supported_ids = sorted_disease_ids(
        set(train_target_rows.loc[supported_mask, "disease_group_id"].astype(str))
    )
    if not supported_ids:
        raise RuntimeError("No model-supported disease from TRAIN")
    if not set(supported_ids).issubset(set(catalog["disease_group_id"].astype(str))):
        raise RuntimeError("Supported disease is missing from disease catalog")
    LOGGER.info("Model-supported disease count from TRAIN: %s", len(supported_ids))

    support_snapshot = catalog.copy()
    support_snapshot["model_supported"] = support_snapshot["disease_group_id"].isin(supported_ids)
    support_snapshot.to_csv(ARTIFACT_DIR / "disease_support_snapshot.csv", index=False)

    train_sample = deterministic_subset(
        train_ids_all,
        float(config["train_query_fraction"]),
        int(config["random_seed"]),
    )
    validation_sample = deterministic_subset(
        validation_ids_all,
        float(config["validation_query_fraction"]),
        int(config["random_seed"]),
    )
    train_sample, coverage_queries_added = augment_and_order_for_label_coverage(
        train_sample,
        train_ids_all,
        targets,
        supported_ids,
        int(config["smoke_train_queries"]),
    )
    train_sample.to_csv(ARTIFACT_DIR / "train_benchmark_query_ids.csv", index=False)
    validation_sample.to_csv(ARTIFACT_DIR / "validation_benchmark_query_ids.csv", index=False)
    LOGGER.info("Benchmark query counts: train=%s validation=%s", len(train_sample), len(validation_sample))

    context_index = contexts.set_index("query_id", drop=False)
    missing_train = set(train_sample["query_id"]) - set(context_index.index)
    missing_validation = set(validation_sample["query_id"]) - set(context_index.index)
    if missing_train or missing_validation:
        raise RuntimeError("Sample query missing from contexts")
    train_contexts = context_index.loc[train_sample["query_id"]].reset_index(drop=True)
    validation_contexts = context_index.loc[validation_sample["query_id"]].reset_index(drop=True)
    train_query_ids = train_contexts["query_id"].astype(str).tolist()
    validation_query_ids = validation_contexts["query_id"].astype(str).tolist()
    train_features = prepare_common_features(train_contexts, feature_columns)
    validation_features = prepare_common_features(validation_contexts, feature_columns)
    train_target = build_target_matrix(train_query_ids, supported_ids, targets)
    validation_target = build_target_matrix(validation_query_ids, supported_ids, targets)
    if not np.all(np.logical_or(train_target == 0, train_target == 1)):
        raise RuntimeError("Multi-label target is not binary")
    smoke_target = train_target[: int(config["smoke_train_queries"])]
    if not ((smoke_target.min(axis=0) == 0) & (smoke_target.max(axis=0) == 1)).all():
        raise RuntimeError("Coverage-aware smoke subset still has a constant H7 target column")
    positives_validation = positive_sets_from_matrix(
        validation_query_ids, supported_ids, validation_target
    )

    results: dict[str, dict[str, Any]] = {}
    results["baseline"] = run_baseline(
        train_contexts,
        validation_contexts,
        targets,
        supported_ids,
        validation_query_ids,
        positives_validation,
        gpu_name,
    )
    results["multilabel"] = run_multilabel(
        config,
        train_features,
        validation_features,
        train_target,
        validation_target,
        train_query_ids,
        validation_query_ids,
        supported_ids,
        positives_validation,
        gpu_name,
    )
    results["ranker"] = run_ranker(
        config,
        train_features,
        validation_features,
        train_target,
        validation_target,
        validation_query_ids,
        supported_ids,
        positives_validation,
        gpu_name,
    )

    output_order = [results["multilabel"], results["ranker"], results["baseline"]]
    pd.DataFrame(output_order).to_csv(RESULTS_PATH, index=False)
    recommendation, reason = choose_algorithm(results)
    estimate_one, estimate_three = estimate_times(
        recommendation,
        results,
        full_train_queries=len(train_ids_all),
        benchmark_train_queries=len(train_sample),
    )
    source_hashes_after = assert_source_hashes(config)
    unchanged = source_hashes_before == source_hashes_after
    write_report(
        config,
        results,
        supported_count=len(supported_ids),
        train_count=len(train_sample),
        validation_count=len(validation_sample),
        full_train_queries=len(train_ids_all),
        recommendation=recommendation,
        reason=reason,
        estimate_one=estimate_one,
        estimate_three=estimate_three,
        source_hashes_unchanged=unchanged,
        coverage_queries_added=coverage_queries_added,
    )
    summary = {
        "supported_disease": len(supported_ids),
        "train_queries": len(train_sample),
        "validation_queries": len(validation_sample),
        "multilabel_status": results["multilabel"]["status"],
        "ranker_status": results["ranker"]["status"],
        "recommended_algorithm": recommendation,
        "processed_checksums_unchanged": unchanged,
        "full_train_performed": False,
        "report": str(REPORT_PATH),
    }
    LOGGER.info("Benchmark complete:\n%s", json.dumps(summary, ensure_ascii=True, indent=2))
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
