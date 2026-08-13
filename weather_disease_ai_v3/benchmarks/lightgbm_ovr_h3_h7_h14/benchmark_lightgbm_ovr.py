"""LightGBM binary-relevance benchmark on TRAIN/VALIDATION only.

The script deliberately has no TEST path. It trains one natural-prevalence
binary classifier per TRAIN-supported disease for each horizon and feature set.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil


BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parents[1]
ARTIFACT_DIR = BENCHMARK_DIR / "artifacts"
RUNTIME_DEPS = ARTIFACT_DIR / "runtime_deps"
if str(RUNTIME_DEPS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DEPS))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import lightgbm as lgb
from lightgbm import LGBMClassifier

from experiments.h7_full_train import train_h7 as metric_contract
from src.baseline import FrequencyRankingBaseline


CONFIG_PATH = BENCHMARK_DIR / "benchmark_config.json"
REPORT_PATH = BENCHMARK_DIR / "LIGHTGBM_OVR_REPORT.md"
HORIZON_COMPARISON_PATH = BENCHMARK_DIR / "horizon_comparison.csv"
BENCHMARK_RESULTS_PATH = BENCHMARK_DIR / "benchmark_results.csv"
METRICS_DIR = BENCHMARK_DIR / "metrics"
LOG_DIR = BENCHMARK_DIR / "logs"
LOG_PATH = LOG_DIR / "benchmark.log"

CONTEXTS_PATH = PROJECT_ROOT / "data/processed/contexts.csv.gz"
TARGETS_PATH = PROJECT_ROOT / "data/processed/targets.csv.gz"
METADATA_PATH = PROJECT_ROOT / "data/processed/dataset_metadata.json"
TRAIN_IDS_PATH = PROJECT_ROOT / "data/splits/train_query_ids.csv"
VALIDATION_IDS_PATH = PROJECT_ROOT / "data/splits/validation_query_ids.csv"
CATBOOST_COMPARISON_PATH = (
    PROJECT_ROOT / "experiments/h3_h14_full_train/metrics/horizon_comparison.csv"
)

METRIC_KEYS = metric_contract.METRIC_KEYS


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}"
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


def read_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def verify_hash_map(mapping: dict[str, str], label: str) -> dict[str, str]:
    actual: dict[str, str] = {}
    for relative, expected in mapping.items():
        path = PROJECT_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing locked {label}: {path}")
        checksum = metric_contract.sha256_file(path)
        actual[relative] = checksum
        if checksum != expected:
            raise RuntimeError(
                f"Locked {label} changed: {relative}; expected={expected}, actual={checksum}"
            )
    return actual


def verify_locked(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        "sources": verify_hash_map(config["source_sha256"], "source"),
        "catboost_validation": verify_hash_map(
            config["catboost_validation_sha256"], "CatBoost validation artifact"
        ),
    }


def build_target_matrix(
    query_ids: list[str],
    disease_ids: list[str],
    targets: pd.DataFrame,
    horizon: int,
) -> np.ndarray:
    query_index = {value: index for index, value in enumerate(query_ids)}
    disease_index = {value: index for index, value in enumerate(disease_ids)}
    matrix = np.zeros((len(query_ids), len(disease_ids)), dtype=np.uint8)
    column = f"has_case_h{horizon}"
    positive = targets.loc[
        (targets[column] == 1)
        & targets["query_id"].isin(query_index)
        & targets["disease_group_id"].isin(disease_index),
        ["query_id", "disease_group_id"],
    ]
    for query_id, disease_id in positive.itertuples(index=False):
        matrix[query_index[str(query_id)], disease_index[str(disease_id)]] = 1
    return matrix


def encode_features(
    indexed_contexts: pd.DataFrame,
    train_ids: list[str],
    validation_ids: list[str],
    feature_names: list[str],
    categorical_features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, int]]]:
    forbidden = [
        column
        for column in feature_names
        if column
        in {
            "query_id",
            "anchor_date",
            "year",
            "disease_group_id",
            "disease_group_name",
        }
        or any(token in column.lower() for token in ("target", "has_case", "case_count"))
    ]
    if forbidden:
        raise RuntimeError(f"Forbidden feature columns: {forbidden}")
    train = indexed_contexts.loc[train_ids, feature_names].reset_index(drop=True).copy()
    validation = (
        indexed_contexts.loc[validation_ids, feature_names].reset_index(drop=True).copy()
    )
    mappings: dict[str, dict[str, int]] = {}
    for column in categorical_features:
        train_values = train[column].fillna("Không rõ").astype(str)
        validation_values = validation[column].fillna("Không rõ").astype(str)
        categories = sorted(train_values.unique().tolist())
        mapping = {value: index for index, value in enumerate(categories)}
        mappings[column] = mapping
        train[column] = train_values.map(mapping).astype("int32")
        validation[column] = validation_values.map(mapping).fillna(-1).astype("int32")
    train["month"] = pd.to_numeric(train["month"], errors="raise").astype("int16")
    validation["month"] = pd.to_numeric(
        validation["month"], errors="raise"
    ).astype("int16")
    for column in feature_names:
        if column not in categorical_features and column != "month":
            train[column] = pd.to_numeric(train[column], errors="raise")
            validation[column] = pd.to_numeric(validation[column], errors="raise")
    if train.columns.tolist() != feature_names or validation.columns.tolist() != feature_names:
        raise RuntimeError("Feature schema/order changed")
    return train, validation, mappings


class ResourceMonitor:
    def __init__(self, interval: float = 0.2) -> None:
        self.interval = interval
        self.process = psutil.Process()
        self.stop_event = threading.Event()
        self.samples: list[dict[str, float]] = []
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        logical = max(psutil.cpu_count(logical=True) or 1, 1)
        self.process.cpu_percent(interval=None)
        while not self.stop_event.wait(self.interval):
            self.samples.append(
                {
                    "rss_mib": self.process.memory_info().rss / (1024 * 1024),
                    "process_cpu_machine_percent": self.process.cpu_percent(interval=None)
                    / logical,
                    "system_cpu_percent": psutil.cpu_percent(interval=None),
                }
            )

    def start(self) -> float:
        before = self.process.memory_info().rss / (1024 * 1024)
        self.thread.start()
        return before

    def stop(self) -> dict[str, float]:
        self.stop_event.set()
        self.thread.join(timeout=2)
        if not self.samples:
            rss = self.process.memory_info().rss / (1024 * 1024)
            self.samples.append(
                {
                    "rss_mib": rss,
                    "process_cpu_machine_percent": 0.0,
                    "system_cpu_percent": 0.0,
                }
            )
        return {
            "peak_rss_mib": max(item["rss_mib"] for item in self.samples),
            "mean_process_cpu_machine_percent": statistics.mean(
                item["process_cpu_machine_percent"] for item in self.samples
            ),
            "mean_system_cpu_percent": statistics.mean(
                item["system_cpu_percent"] for item in self.samples
            ),
        }


def classifier_params(config: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "objective",
        "boosting_type",
        "n_estimators",
        "learning_rate",
        "num_leaves",
        "max_depth",
        "min_child_samples",
        "subsample",
        "subsample_freq",
        "colsample_bytree",
        "reg_lambda",
        "reg_alpha",
        "random_state",
        "verbosity",
    )
    params = {key: config[key] for key in keys}
    params["n_jobs"] = int(config["classifier_n_jobs"])
    return params


def train_ovr(
    run_name: str,
    horizon: int,
    with_weather: bool,
    train_features: pd.DataFrame,
    validation_features: pd.DataFrame,
    train_target: np.ndarray,
    validation_target: np.ndarray,
    disease_ids: list[str],
    categorical_features: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    run_dir = ARTIFACT_DIR / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    scores = np.zeros(validation_target.shape, dtype=np.float32)
    details: list[dict[str, Any]] = []
    serialized_bytes = 0
    prediction_seconds = 0.0
    constant_labels = 0
    monitor = ResourceMonitor()
    memory_before = monitor.start()
    started_total = time.perf_counter()
    for disease_index, disease_id in enumerate(disease_ids):
        y_train = train_target[:, disease_index]
        y_validation = validation_target[:, disease_index]
        unique = np.unique(y_train)
        label_started = time.perf_counter()
        if len(unique) == 1:
            constant_labels += 1
            constant_score = float(unique[0])
            scores[:, disease_index] = constant_score
            details.append(
                {
                    "disease_group_id": disease_id,
                    "train_positive": int(y_train.sum()),
                    "validation_positive": int(y_validation.sum()),
                    "status": "constant_train_target",
                    "best_iteration": 0,
                    "train_seconds": 0.0,
                    "prediction_seconds": 0.0,
                    "serialized_model_bytes": 0,
                }
            )
            continue
        model = LGBMClassifier(**classifier_params(config))
        model.fit(
            train_features,
            y_train,
            eval_set=[(validation_features, y_validation)],
            eval_metric="binary_logloss",
            categorical_feature=categorical_features,
            callbacks=[
                lgb.early_stopping(
                    stopping_rounds=int(config["early_stopping_rounds"]), verbose=False
                ),
                lgb.log_evaluation(period=0),
            ],
        )
        train_seconds = time.perf_counter() - label_started
        predict_started = time.perf_counter()
        positive_scores = model.predict_proba(
            validation_features, num_iteration=model.best_iteration_
        )[:, 1]
        label_prediction_seconds = time.perf_counter() - predict_started
        prediction_seconds += label_prediction_seconds
        scores[:, disease_index] = positive_scores.astype(np.float32)
        model_bytes = len(model.booster_.model_to_string().encode("utf-8"))
        serialized_bytes += model_bytes
        details.append(
            {
                "disease_group_id": disease_id,
                "train_positive": int(y_train.sum()),
                "validation_positive": int(y_validation.sum()),
                "status": "trained",
                "best_iteration": int(model.best_iteration_),
                "train_seconds": train_seconds,
                "prediction_seconds": label_prediction_seconds,
                "serialized_model_bytes": model_bytes,
            }
        )
        if (disease_index + 1) % 25 == 0 or disease_index + 1 == len(disease_ids):
            log(
                f"{run_name}: classifiers={disease_index + 1}/{len(disease_ids)}, "
                f"elapsed={time.perf_counter() - started_total:.1f}s"
            )
        del model
    training_seconds = time.perf_counter() - started_total
    resource = monitor.stop()
    order = np.argsort(-scores, axis=1, kind="stable")
    metrics = metric_contract.ranking_metrics_from_order(order, validation_target)
    trained_iterations = [
        int(item["best_iteration"])
        for item in details
        if item["status"] == "trained"
    ]
    np.savez_compressed(
        run_dir / "validation_scores.npz",
        scores=scores,
        disease_ids=np.asarray(disease_ids, dtype=str),
    )
    pd.DataFrame(details).to_csv(run_dir / "label_training_details.csv", index=False)
    result = {
        "run_name": run_name,
        "horizon": horizon,
        "with_weather": with_weather,
        "status": "success",
        "train_query_count": len(train_features),
        "validation_query_count": len(validation_features),
        "disease_count": len(disease_ids),
        "classifier_count": len(disease_ids),
        "trained_classifier_count": len(trained_iterations),
        "constant_classifier_count": constant_labels,
        "feature_count": train_features.shape[1],
        "training_seconds": training_seconds,
        "prediction_seconds": prediction_seconds,
        "memory_before_mib": memory_before,
        "peak_rss_mib": resource["peak_rss_mib"],
        "peak_delta_rss_mib": resource["peak_rss_mib"] - memory_before,
        "mean_process_cpu_machine_percent": resource[
            "mean_process_cpu_machine_percent"
        ],
        "mean_system_cpu_percent": resource["mean_system_cpu_percent"],
        "total_serialized_model_bytes": serialized_bytes,
        "models_persisted": False,
        "mean_best_iteration": float(np.mean(trained_iterations)),
        "median_best_iteration": float(np.median(trained_iterations)),
        "min_best_iteration": int(min(trained_iterations)),
        "max_best_iteration": int(max(trained_iterations)),
        **metrics,
    }
    (run_dir / "run_metadata.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(
        f"{run_name}: success, train={training_seconds:.2f}s, "
        f"NDCG@5={result['ndcg_at_5']:.6f}, peakRSS={result['peak_rss_mib']:.1f}MiB"
    )
    return result


def evaluate_baseline(
    horizon: int,
    contexts: pd.DataFrame,
    targets: pd.DataFrame,
    train_ids: list[str],
    validation_ids: list[str],
    disease_ids: list[str],
    validation_target: np.ndarray,
) -> dict[str, Any]:
    train_set = set(train_ids)
    baseline = FrequencyRankingBaseline.fit_train(
        contexts[contexts["query_id"].isin(train_set)].copy(),
        targets[targets["query_id"].isin(train_set)].copy(),
        disease_ids,
        horizon,
        split_name="train",
    )
    disease_index = {disease_id: index for index, disease_id in enumerate(disease_ids)}
    indexed_contexts = contexts.set_index("query_id")
    order = np.empty((len(validation_ids), len(disease_ids)), dtype=np.int32)
    for row_index, (_, context) in enumerate(
        indexed_contexts.loc[validation_ids].iterrows()
    ):
        order[row_index] = [
            disease_index[disease_id] for disease_id in baseline.rank(context)
        ]
    return {
        "run_name": f"h{horizon}_baseline",
        "horizon": horizon,
        "with_weather": False,
        "status": "success",
        "train_query_count": len(train_ids),
        "validation_query_count": len(validation_ids),
        "disease_count": len(disease_ids),
        "classifier_count": 0,
        "feature_count": 3,
        "training_seconds": 0.0,
        "prediction_seconds": 0.0,
        **metric_contract.ranking_metrics_from_order(order, validation_target),
    }


def comparison_rows(
    horizon: int,
    weather: dict[str, Any],
    control: dict[str, Any],
    baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for key in METRIC_KEYS:
        w, n, b = float(weather[key]), float(control[key]), float(baseline[key])
        rows.append(
            {
                "horizon": f"H{horizon}",
                "metric": key,
                "with_weather": w,
                "no_weather": n,
                "baseline": b,
                "weather_minus_no_weather": w - n,
                "weather_minus_baseline": w - b,
                "no_weather_minus_baseline": n - b,
            }
        )
    return rows


def load_catboost_reference() -> dict[int, dict[str, Any]]:
    frame = pd.read_csv(CATBOOST_COMPARISON_PATH)
    result: dict[int, dict[str, Any]] = {}
    for horizon in (3, 7, 14):
        row = frame.loc[frame["horizon"] == f"H{horizon}"].iloc[0]
        result[horizon] = {
            "weather_ndcg_at_5": float(row["with_weather_ndcg_at_5"]),
            "weather_ndcg_at_10": float(row["with_weather_ndcg_at_10"]),
            "weather_gain_ndcg_at_5": float(
                row["weather_minus_no_weather_ndcg_at_5"]
            ),
            "weather_gain_ndcg_at_10": float(
                row["weather_minus_no_weather_ndcg_at_10"]
            ),
        }
    return result


def choose_best_horizon(
    rows: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[str, str]:
    candidates = [
        row
        for row in rows
        if row["weather_minus_no_weather_ndcg_at_5"]
        >= float(config["weather_practical_ndcg_delta"])
        and row["weather_minus_no_weather_ndcg_at_10"]
        >= float(config["weather_gain_ndcg10_floor"])
        and row["weather_minus_baseline_ndcg_at_5"]
        >= -float(config["baseline_competitive_tolerance"])
    ]
    if len(candidates) == 1:
        return (
            candidates[0]["horizon"],
            "Chỉ horizon này đạt weather-gain gate và cạnh tranh baseline.",
        )
    if len(candidates) > 1:
        dominant = []
        for candidate in candidates:
            if all(
                candidate["weather_minus_no_weather_ndcg_at_5"]
                >= other["weather_minus_no_weather_ndcg_at_5"]
                and candidate["weather_minus_no_weather_ndcg_at_10"]
                >= other["weather_minus_no_weather_ndcg_at_10"]
                and candidate["weather_minus_baseline_ndcg_at_5"]
                >= other["weather_minus_baseline_ndcg_at_5"]
                for other in candidates
            ):
                dominant.append(candidate)
        if len(dominant) == 1:
            return (
                dominant[0]["horizon"],
                "Horizon này trội hơn các candidate khác về weather gain và baseline gain.",
            )
    return (
        "NO_CLEAR_WINNER",
        "Không có một horizon thắng nhất quán theo weather gain và baseline gain.",
    )


def decide_algorithm(
    rows: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[str, str]:
    material = float(config["algorithm_material_delta"])
    weather_gate = float(config["weather_practical_ndcg_delta"])
    if all(
        row["lightgbm_minus_catboost_ndcg_at_5"] < -material
        and row["lightgbm_minus_catboost_ndcg_at_10"] < -material
        for row in rows
    ):
        return "CATBOOST_STILL_BETTER", "LightGBM kém CatBoost rõ trên cả ba horizon."
    if any(
        row["lightgbm_minus_catboost_ndcg_at_5"] >= -material
        and row["lightgbm_minus_catboost_ndcg_at_10"] >= -material
        and row["weather_minus_no_weather_ndcg_at_5"] >= weather_gate
        and row["weather_minus_no_weather_ndcg_at_10"]
        >= float(config["weather_gain_ndcg10_floor"])
        for row in rows
    ):
        return (
            "LIGHTGBM_PROMISING",
            "Ít nhất một horizon cạnh tranh CatBoost và cho weather gain đủ ngưỡng.",
        )
    return (
        "SIMILAR_PERFORMANCE",
        "Chênh lệch không nhất quán đủ lớn để tuyên bố một thuật toán thắng rõ.",
    )


def fmt(value: Any, digits: int = 4) -> str:
    return metric_contract.fmt(value, digits)


def write_report(
    config: dict[str, Any],
    results: dict[int, dict[str, Any]],
    horizon_rows: list[dict[str, Any]],
    best_horizon: str,
    best_reason: str,
    algorithm_decision: str,
    algorithm_reason: str,
    total_seconds: float,
    integrity_pass: bool,
) -> None:
    indexed = {row["horizon"]: row for row in horizon_rows}
    lines = [
        "# LightGBM One-vs-Rest H3/H7/H14 Report",
        "",
        "## 1. Environment",
        "",
        f"- LightGBM `{lgb.__version__}`, Python `{sys.version.split()[0]}`.",
        f"- CPU: {psutil.cpu_count(logical=False)} physical / {psutil.cpu_count(logical=True)} logical; RAM: {psutil.virtual_memory().total / (1024**3):.1f} GiB.",
        f"- Strategy: disease loop tuần tự, outer parallel={config['outer_parallel_diseases']}, mỗi classifier n_jobs={config['classifier_n_jobs']}; không nested parallelism.",
        "",
        "## 2. Dataset",
        "",
        f"- TRAIN/VALIDATION: {results[3]['weather']['train_query_count']} / {results[3]['weather']['validation_query_count']} queries.",
        f"- TRAIN-supported diseases: {results[3]['weather']['disease_count']}; cùng universe cho H3/H7/H14.",
        "- TEST không có path trong benchmark script và không được load.",
        "",
        "## 3. One-vs-Rest design",
        "",
        "Mỗi disease là một binary classifier `has_case_h*`; positive-class score của 221 classifier được ghép thành query×disease matrix và xếp hạng. Natural TRAIN prevalence được giữ nguyên: không class weight, scale_pos_weight, oversampling hay SMOTE.",
        "",
        "## 4. Config",
        "",
        "`binary`, `gbdt`, n_estimators=200, learning_rate=0.05, num_leaves=15, max_depth=4, min_child_samples=20, subsample=0.9, colsample_bytree=0.9, reg_lambda=1, seed=42; early stopping 20 theo VALIDATION binary_logloss.",
    ]
    section_number = {3: 5, 7: 6, 14: 7}
    for horizon in (3, 7, 14):
        comparison = results[horizon]["comparison"].set_index("metric")
        weather = results[horizon]["weather"]
        control = results[horizon]["control"]
        lines.extend(
            [
                "",
                f"## {section_number[horizon]}. H{horizon} result",
                "",
                "| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather gain | Weather-Baseline |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        labels = {
            "precision_at_5": "Precision@5",
            "recall_at_5": "Recall@5",
            "ndcg_at_5": "NDCG@5",
            "precision_at_10": "Precision@10",
            "recall_at_10": "Recall@10",
            "ndcg_at_10": "NDCG@10",
        }
        for key in METRIC_KEYS:
            row = comparison.loc[key]
            lines.append(
                f"| {labels[key]} | {fmt(row['with_weather'])} | {fmt(row['no_weather'])} | "
                f"{fmt(row['baseline'])} | {fmt(row['weather_minus_no_weather'], 6)} | "
                f"{fmt(row['weather_minus_baseline'], 6)} |"
            )
        lines.extend(
            [
                "",
                f"Best iterations WITH: mean={fmt(weather['mean_best_iteration'], 2)}, median={fmt(weather['median_best_iteration'], 1)}, range={weather['min_best_iteration']}–{weather['max_best_iteration']}; NO: mean={fmt(control['mean_best_iteration'], 2)}, median={fmt(control['median_best_iteration'], 1)}, range={control['min_best_iteration']}–{control['max_best_iteration']}.",
            ]
        )
    lines.extend(
        [
            "",
            "## 8. Weather gain",
            "",
            "| Horizon | LightGBM gain NDCG@5 | CatBoost gain NDCG@5 | LightGBM gain NDCG@10 | CatBoost gain NDCG@10 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for label in ("H3", "H7", "H14"):
        row = indexed[label]
        lines.append(
            f"| {label} | {fmt(row['weather_minus_no_weather_ndcg_at_5'], 6)} | "
            f"{fmt(row['catboost_weather_gain_ndcg_at_5'], 6)} | "
            f"{fmt(row['weather_minus_no_weather_ndcg_at_10'], 6)} | "
            f"{fmt(row['catboost_weather_gain_ndcg_at_10'], 6)} |"
        )
    for key, title in (("ndcg_at_5", "NDCG@5"), ("ndcg_at_10", "NDCG@10")):
        lines.extend(
            [
                "",
                f"## {'9' if key.endswith('_5') else '10'}. {title}: baseline/CatBoost comparison",
                "",
                f"| Horizon | LightGBM Weather | LightGBM NoWeather | Baseline | Weather Gain | CatBoost Weather | LGBM-CatBoost |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for label in ("H3", "H7", "H14"):
            row = indexed[label]
            lines.append(
                f"| {label} | {fmt(row[f'lightgbm_weather_{key}'])} | "
                f"{fmt(row[f'lightgbm_no_weather_{key}'])} | {fmt(row[f'baseline_{key}'])} | "
                f"{fmt(row[f'weather_minus_no_weather_{key}'], 6)} | "
                f"{fmt(row[f'catboost_weather_{key}'])} | "
                f"{fmt(row[f'lightgbm_minus_catboost_{key}'], 6)} |"
            )
    lines.extend(
        [
            "",
            "## 11. Runtime/resource",
            "",
            "| Run | Train time (s) | Predict time (s) | Classifiers | Peak RSS (MiB) | Peak delta (MiB) | Mean CPU share (%) | Serialized size (MiB) |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for horizon in (3, 7, 14):
        for variant in ("weather", "control"):
            row = results[horizon][variant]
            lines.append(
                f"| H{horizon} {'WITH' if variant == 'weather' else 'NO'} | "
                f"{fmt(row['training_seconds'], 2)} | {fmt(row['prediction_seconds'], 2)} | "
                f"{row['classifier_count']} | {fmt(row['peak_rss_mib'], 1)} | "
                f"{fmt(row['peak_delta_rss_mib'], 1)} | "
                f"{fmt(row['mean_process_cpu_machine_percent'], 1)} | "
                f"{row['total_serialized_model_bytes'] / (1024**2):.2f} |"
            )
    lines.extend(
        [
            "",
            f"Tổng wall-clock benchmark: **{total_seconds:.2f} giây**. 1.326 model strings có tổng size được đo nhưng không persist để tránh rải nhiều file; score matrices và label metadata đã lưu trong `artifacts/`.",
            "",
            "## 12. Recommendation",
            "",
            f"**BEST_LIGHTGBM_HORIZON: {best_horizon}** — {best_reason}",
            "",
            f"**LIGHTGBM_VS_CATBOOST: {algorithm_decision}** — {algorithm_reason}",
            "",
            "Weather gain chỉ là tín hiệu dự báo thống kê trong TRAIN/VALIDATION, không phải quan hệ nhân quả.",
            "",
            "## 13. Integrity",
            "",
            f"- Raw/processed/TRAIN/VALIDATION/CatBoost validation checksum: **{'PASS' if integrity_pass else 'FAIL'}**.",
            "- TEST không có path trong script, không load feature/target/prediction/metric.",
            "- Không retrain CatBoost; không đọc CatBoost TEST result; không SHAP/tuning/API/frontend/backend.",
            "- Mọi artifact mới chỉ nằm trong `benchmarks/lightgbm_ovr_h3_h7_h14/`.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    for directory in (METRICS_DIR, LOG_DIR, ARTIFACT_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("", encoding="utf-8")
    config = read_config()
    locked_before = verify_locked(config)
    benchmark_started = time.perf_counter()
    log(
        f"LightGBM={lgb.__version__}; CPU physical/logical="
        f"{psutil.cpu_count(logical=False)}/{psutil.cpu_count(logical=True)}; "
        f"sequential diseases, classifier n_jobs={config['classifier_n_jobs']}"
    )
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    contexts = pd.read_csv(CONTEXTS_PATH, dtype={"query_id": str})
    targets = pd.read_csv(
        TARGETS_PATH, dtype={"query_id": str, "disease_group_id": str}
    )
    train_ids = pd.read_csv(TRAIN_IDS_PATH, dtype={"query_id": str})["query_id"].tolist()
    validation_ids = pd.read_csv(
        VALIDATION_IDS_PATH, dtype={"query_id": str}
    )["query_id"].tolist()
    if set(train_ids) & set(validation_ids):
        raise RuntimeError("TRAIN and VALIDATION overlap")
    indexed_contexts = contexts.set_index("query_id", drop=False)
    train_targets = targets[targets["query_id"].isin(set(train_ids))]
    supported_mask = (
        train_targets[["has_case_h3", "has_case_h7", "has_case_h14"]].max(axis=1) > 0
    )
    disease_ids = metric_contract.sorted_disease_ids(
        set(train_targets.loc[supported_mask, "disease_group_id"].astype(str))
    )
    weather_features = list(metadata["model_feature_columns"])
    control_features = list(config["no_weather_features"])
    train_weather, validation_weather, category_mappings = encode_features(
        indexed_contexts,
        train_ids,
        validation_ids,
        weather_features,
        config["categorical_features"],
    )
    train_control = train_weather[control_features].copy()
    validation_control = validation_weather[control_features].copy()
    (ARTIFACT_DIR / "category_mappings.json").write_text(
        json.dumps(category_mappings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    results: dict[int, dict[str, Any]] = {}
    result_frames: list[pd.DataFrame] = []
    catboost = load_catboost_reference()
    horizon_rows: list[dict[str, Any]] = []
    for horizon in config["horizons"]:
        train_target = build_target_matrix(train_ids, disease_ids, targets, horizon)
        validation_target = build_target_matrix(
            validation_ids, disease_ids, targets, horizon
        )
        weather = train_ovr(
            f"h{horizon}_with_weather",
            horizon,
            True,
            train_weather,
            validation_weather,
            train_target,
            validation_target,
            disease_ids,
            config["categorical_features"],
            config,
        )
        control = train_ovr(
            f"h{horizon}_no_weather",
            horizon,
            False,
            train_control,
            validation_control,
            train_target,
            validation_target,
            disease_ids,
            config["categorical_features"],
            config,
        )
        baseline = evaluate_baseline(
            horizon,
            contexts,
            targets,
            train_ids,
            validation_ids,
            disease_ids,
            validation_target,
        )
        comparisons = pd.DataFrame(
            comparison_rows(horizon, weather, control, baseline)
        )
        horizon_result_frame = pd.DataFrame([weather, control, baseline])
        horizon_result_frame.to_csv(
            METRICS_DIR / f"h{horizon}_metrics.csv", index=False
        )
        result_frames.append(horizon_result_frame)
        results[horizon] = {
            "weather": weather,
            "control": control,
            "baseline": baseline,
            "comparison": comparisons,
        }
        indexed_comparison = comparisons.set_index("metric")
        row: dict[str, Any] = {
            "horizon": f"H{horizon}",
            "weather_training_seconds": weather["training_seconds"],
            "no_weather_training_seconds": control["training_seconds"],
        }
        for key in ("ndcg_at_5", "ndcg_at_10"):
            comparison = indexed_comparison.loc[key]
            row[f"lightgbm_weather_{key}"] = comparison["with_weather"]
            row[f"lightgbm_no_weather_{key}"] = comparison["no_weather"]
            row[f"baseline_{key}"] = comparison["baseline"]
            row[f"weather_minus_no_weather_{key}"] = comparison[
                "weather_minus_no_weather"
            ]
            row[f"weather_minus_baseline_{key}"] = comparison[
                "weather_minus_baseline"
            ]
            row[f"catboost_weather_{key}"] = catboost[horizon][
                f"weather_{key}"
            ]
            row[f"catboost_weather_gain_{key}"] = catboost[horizon][
                f"weather_gain_{key}"
            ]
            row[f"lightgbm_minus_catboost_{key}"] = (
                comparison["with_weather"] - catboost[horizon][f"weather_{key}"]
            )
        horizon_rows.append(row)
    total_seconds = time.perf_counter() - benchmark_started
    best_horizon, best_reason = choose_best_horizon(horizon_rows, config)
    algorithm_decision, algorithm_reason = decide_algorithm(horizon_rows, config)
    comparison_frame = pd.DataFrame(horizon_rows)
    comparison_frame.to_csv(HORIZON_COMPARISON_PATH, index=False)
    pd.concat(result_frames, ignore_index=True).to_csv(
        BENCHMARK_RESULTS_PATH, index=False
    )
    locked_after = verify_locked(config)
    integrity_pass = locked_before == locked_after
    if not integrity_pass:
        raise RuntimeError("Locked input/reference checksum changed")
    write_report(
        config,
        results,
        horizon_rows,
        best_horizon,
        best_reason,
        algorithm_decision,
        algorithm_reason,
        total_seconds,
        integrity_pass,
    )
    summary = {
        "best_lightgbm_horizon": best_horizon,
        "lightgbm_vs_catboost": algorithm_decision,
        "total_seconds": total_seconds,
        "integrity_pass": integrity_pass,
        "test_used": False,
        "report": str(REPORT_PATH),
    }
    log(json.dumps(summary, ensure_ascii=True))
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "failure.log").open("w", encoding="utf-8") as handle:
            traceback.print_exc(file=handle)
        raise
