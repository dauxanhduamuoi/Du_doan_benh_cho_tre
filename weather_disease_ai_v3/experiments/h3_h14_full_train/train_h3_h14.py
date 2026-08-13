"""Train H3 and H14 with the exact successful H7 CatBoost pipeline.

All four CUDA fits run in isolated subprocesses. H7 is read-only reference.
TEST is never parsed; its file hash is checked only for integrity.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EXPERIMENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.h7_full_train import train_h7 as h7_pipeline
from src.baseline import FrequencyRankingBaseline


CONFIG_PATH = EXPERIMENT_DIR / "train_config.json"
TRAINING_REPORT_PATH = EXPERIMENT_DIR / "H3_H14_TRAINING_REPORT.md"
HORIZON_REPORT_PATH = EXPERIMENT_DIR / "HORIZON_COMPARISON.md"
METRICS_DIR = EXPERIMENT_DIR / "metrics"
LOG_DIR = EXPERIMENT_DIR / "logs"
MODEL_DIR = EXPERIMENT_DIR / "models"
ORCHESTRATOR_LOG = LOG_DIR / "orchestrator.log"

CONTEXTS_PATH = PROJECT_ROOT / "data/processed/contexts.csv.gz"
TARGETS_PATH = PROJECT_ROOT / "data/processed/targets.csv.gz"
METADATA_PATH = PROJECT_ROOT / "data/processed/dataset_metadata.json"
TRAIN_IDS_PATH = PROJECT_ROOT / "data/splits/train_query_ids.csv"
VALIDATION_IDS_PATH = PROJECT_ROOT / "data/splits/validation_query_ids.csv"
H7_METRICS_PATH = PROJECT_ROOT / "experiments/h7_full_train/metrics/validation_metrics.csv"
H7_COMPARISON_PATH = PROJECT_ROOT / "experiments/h7_full_train/metrics/comparison.csv"
H7_REPORT_PATH = PROJECT_ROOT / "experiments/h7_full_train/H7_TRAINING_REPORT.md"

METRIC_KEYS = h7_pipeline.METRIC_KEYS


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}"
    with ORCHESTRATOR_LOG.open("a", encoding="utf-8") as handle:
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
        checksum = h7_pipeline.sha256_file(path)
        actual[relative] = checksum
        if checksum != expected:
            raise RuntimeError(
                f"Locked {label} changed: {relative}; expected={expected}, actual={checksum}"
            )
    return actual


def verify_all_locked(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        "sources": verify_hash_map(config["source_sha256"], "source"),
        "h7_artifacts": verify_hash_map(config["h7_artifact_sha256"], "H7 artifact"),
    }


def build_target_matrix(
    query_ids: list[str], disease_ids: list[str], targets: pd.DataFrame, horizon: int
) -> np.ndarray:
    query_index = {value: index for index, value in enumerate(query_ids)}
    disease_index = {value: index for index, value in enumerate(disease_ids)}
    matrix = np.zeros((len(query_ids), len(disease_ids)), dtype=np.uint8)
    target_column = f"has_case_h{horizon}"
    positive = targets.loc[
        (targets[target_column] == 1)
        & targets["query_id"].isin(query_index)
        & targets["disease_group_id"].isin(disease_index),
        ["query_id", "disease_group_id"],
    ]
    for query_id, disease_id in positive.itertuples(index=False):
        matrix[query_index[str(query_id)], disease_index[str(disease_id)]] = 1
    return matrix


def load_full_data(
    horizon: int, *, with_weather: bool
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    np.ndarray,
    np.ndarray,
    list[str],
    list[str],
    list[str],
    dict[str, Any],
]:
    config = read_config()
    if horizon not in config["horizons"]:
        raise ValueError(f"Horizon not authorized in this experiment: {horizon}")
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
    if not set(train_ids + validation_ids).issubset(indexed_contexts.index):
        raise RuntimeError("Some TRAIN/VALIDATION query IDs are missing from contexts")
    train_targets = targets[targets["query_id"].isin(set(train_ids))]
    supported_mask = (
        train_targets[["has_case_h3", "has_case_h7", "has_case_h14"]].max(axis=1) > 0
    )
    disease_ids = h7_pipeline.sorted_disease_ids(
        set(train_targets.loc[supported_mask, "disease_group_id"].astype(str))
    )
    feature_columns = (
        list(metadata["model_feature_columns"])
        if with_weather
        else list(config["no_weather_features"])
    )
    forbidden = [
        column
        for column in feature_columns
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
        raise RuntimeError(f"Forbidden features: {forbidden}")
    if not with_weather:
        weather_tokens = (
            "weather",
            "temperature",
            "humidity",
            "rain",
            "precipitation",
            "wind",
        )
        leaks = [
            column
            for column in feature_columns
            if any(token in column.lower() for token in weather_tokens)
        ]
        if leaks:
            raise RuntimeError(f"NO_WEATHER contains weather features: {leaks}")

    def prepare(ids: list[str]) -> pd.DataFrame:
        frame = indexed_contexts.loc[ids, feature_columns].reset_index(drop=True).copy()
        for column in config["categorical_features"]:
            frame[column] = frame[column].fillna("Không rõ").astype(str)
        frame["month"] = pd.to_numeric(frame["month"], errors="raise").astype("int16")
        return frame

    train_features = prepare(train_ids)
    validation_features = prepare(validation_ids)
    train_target = build_target_matrix(train_ids, disease_ids, targets, horizon)
    validation_target = build_target_matrix(validation_ids, disease_ids, targets, horizon)
    if not ((train_target.min(axis=0) == 0) & (train_target.max(axis=0) == 1)).all():
        raise RuntimeError(f"H{horizon} TRAIN target contains a constant disease column")
    train_dates = pd.to_datetime(indexed_contexts.loc[train_ids, "anchor_date"])
    validation_dates = pd.to_datetime(indexed_contexts.loc[validation_ids, "anchor_date"])
    stats = {
        "train_date_start": str(train_dates.min().date()),
        "train_date_end": str(train_dates.max().date()),
        "validation_date_start": str(validation_dates.min().date()),
        "validation_date_end": str(validation_dates.max().date()),
        "train_mean_positive_diseases": float(train_target.sum(axis=1).mean()),
        "train_median_positive_diseases": float(np.median(train_target.sum(axis=1))),
        "validation_mean_positive_diseases": float(validation_target.sum(axis=1).mean()),
        "validation_median_positive_diseases": float(
            np.median(validation_target.sum(axis=1))
        ),
        "validation_zero_positive_queries": int(
            (validation_target.sum(axis=1) == 0).sum()
        ),
    }
    return (
        train_features,
        validation_features,
        train_target,
        validation_target,
        train_ids,
        validation_ids,
        disease_ids,
        stats,
    )


def result_template(run_name: str, horizon: int, with_weather: bool) -> dict[str, Any]:
    return {
        "run_name": run_name,
        "horizon": horizon,
        "status": "not_run",
        "error": "",
        "with_weather": with_weather,
        "requested_iterations": 300,
        "best_iteration": None,
        "best_iteration_zero_based": None,
        "final_iteration": None,
        "early_stopped": None,
        "query_count": 0,
        "validation_query_count": 0,
        "disease_count": 0,
        "feature_count": 0,
        "train_target_shape": "",
        "validation_target_shape": "",
        "training_seconds": float("nan"),
        "prediction_seconds": float("nan"),
        "model_size_bytes": 0,
        **{key: float("nan") for key in METRIC_KEYS},
        "oom": False,
        "gpu_ram_part_requested": 0.85,
        "gpu_ram_part_supported": False,
    }


def wait_for_go(go_path: Path, timeout_seconds: int = 90) -> None:
    started = time.perf_counter()
    while not go_path.exists():
        if time.perf_counter() - started > timeout_seconds:
            raise TimeoutError("Orchestrator did not release GPU worker")
        time.sleep(0.05)


def worker(run_name: str, horizon: int, with_weather: bool) -> int:
    from catboost import CatBoostClassifier, Pool
    import catboost

    config = read_config()
    phase_path = LOG_DIR / f"{run_name}_phase.txt"
    go_path = LOG_DIR / f"{run_name}_go.flag"
    result_path = LOG_DIR / f"{run_name}_result.json"
    result = result_template(run_name, horizon, with_weather)
    result["catboost_version"] = catboost.__version__
    try:
        phase_path.write_text("setup", encoding="utf-8")
        (
            train_features,
            validation_features,
            train_target,
            validation_target,
            train_ids,
            validation_ids,
            disease_ids,
            data_summary,
        ) = load_full_data(horizon, with_weather=with_weather)
        result.update(
            {
                "query_count": len(train_ids),
                "validation_query_count": len(validation_ids),
                "disease_count": len(disease_ids),
                "feature_count": train_features.shape[1],
                "train_target_shape": f"{len(train_ids)}x{len(disease_ids)}",
                "validation_target_shape": f"{len(validation_ids)}x{len(disease_ids)}",
                **data_summary,
            }
        )
        train_pool = Pool(
            train_features,
            label=train_target,
            cat_features=list(config["categorical_features"]),
        )
        validation_pool = Pool(
            validation_features,
            label=validation_target,
            cat_features=list(config["categorical_features"]),
        )
        params = {
            key: config[key]
            for key in (
                "loss_function",
                "task_type",
                "devices",
                "gpu_ram_part",
                "iterations",
                "depth",
                "border_count",
                "one_hot_max_size",
                "learning_rate",
                "random_seed",
                "verbose",
                "allow_writing_files",
                "use_best_model",
                "od_type",
                "od_wait",
            )
        }
        model = CatBoostClassifier(**params)
        result["gpu_ram_part_supported"] = model.get_param("gpu_ram_part") == 0.85
        phase_path.write_text("ready", encoding="utf-8")
        wait_for_go(go_path)
        phase_path.write_text("training", encoding="utf-8")
        started = time.perf_counter()
        model.fit(train_pool, eval_set=validation_pool)
        result["training_seconds"] = time.perf_counter() - started
        best_zero = int(model.get_best_iteration())
        result["best_iteration_zero_based"] = best_zero
        result["best_iteration"] = best_zero + 1 if best_zero >= 0 else None
        result["final_iteration"] = int(model.tree_count_)
        result["early_stopped"] = int(model.tree_count_) < int(config["iterations"])
        model_path = MODEL_DIR / f"{run_name}.cbm"
        model.save_model(model_path)
        loaded = CatBoostClassifier()
        loaded.load_model(model_path)
        started = time.perf_counter()
        scores = np.asarray(loaded.predict_proba(validation_pool), dtype=np.float64)
        result["prediction_seconds"] = time.perf_counter() - started
        if scores.shape != (len(validation_ids), len(disease_ids)):
            raise RuntimeError(f"Invalid prediction shape: {scores.shape}")
        result.update(h7_pipeline.ranking_metrics(scores, validation_target))
        result["model_size_bytes"] = model_path.stat().st_size
        result["status"] = "success"
        phase_path.write_text("done", encoding="utf-8")
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        result["status"] = "failed"
        result["error"] = text
        result["oom"] = any(
            token in text.lower()
            for token in ("out of memory", "memory allocation", "cuda error 2")
        )
        traceback.print_exc()
        phase_path.write_text("failed", encoding="utf-8")
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


def run_isolated(run_name: str, horizon: int, with_weather: bool) -> dict[str, Any]:
    config = read_config()
    phase_path = LOG_DIR / f"{run_name}_phase.txt"
    go_path = LOG_DIR / f"{run_name}_go.flag"
    result_path = LOG_DIR / f"{run_name}_result.json"
    worker_log = LOG_DIR / f"{run_name}.log"
    gpu_log = LOG_DIR / f"{run_name}_gpu.csv"
    go_path.unlink(missing_ok=True)
    result_path.unlink(missing_ok=True)
    phase_path.write_text("launch", encoding="utf-8")
    command = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "--worker",
        run_name,
        "--horizon",
        str(horizon),
        "--with-weather",
        "1" if with_weather else "0",
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    samples: list[dict[str, Any]] = []
    current_phase = "launch"
    training_started: float | None = None
    high_memory_started: float | None = None
    memory_before: float | None = None
    stopped_reason = ""
    with worker_log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=flags,
        )
        while process.poll() is None:
            phase = (
                phase_path.read_text(encoding="utf-8").strip()
                if phase_path.exists()
                else "launch"
            )
            if phase != current_phase:
                current_phase = phase
                log(f"{run_name}: phase={phase}")
                if phase == "ready":
                    _, _, memory_before, _ = h7_pipeline.query_gpu()
                    log(f"{run_name}: GPU memory before training={memory_before:.0f} MiB")
                    go_path.write_text("go", encoding="utf-8")
                if phase == "training":
                    training_started = time.perf_counter()
            gpu_name, total_memory, used_memory, utilization = h7_pipeline.query_gpu()
            samples.append(
                {
                    "timestamp": time.time(),
                    "phase": current_phase,
                    "memory_used_mib": used_memory,
                    "gpu_utilization_percent": utilization,
                }
            )
            if used_memory >= config["gpu_abort_total_memory_mib"]:
                high_memory_started = high_memory_started or time.perf_counter()
                if (
                    time.perf_counter() - high_memory_started
                    >= config["gpu_abort_consecutive_seconds"]
                ):
                    stopped_reason = (
                        f"GPU memory >= {config['gpu_abort_total_memory_mib']} MiB for "
                        f"{config['gpu_abort_consecutive_seconds']} seconds"
                    )
            else:
                high_memory_started = None
            if (
                training_started is not None
                and time.perf_counter() - training_started
                > config["training_timeout_seconds"]
            ):
                stopped_reason = (
                    f"training exceeded safety timeout {config['training_timeout_seconds']} seconds"
                )
            if stopped_reason:
                log(f"{run_name}: FAIL_RESOURCE {stopped_reason}")
                h7_pipeline.terminate_process(process)
                break
            time.sleep(config["gpu_monitor_interval_seconds"])
    _, total_memory, memory_after, _ = h7_pipeline.query_gpu()
    pd.DataFrame(samples).to_csv(gpu_log, index=False)
    if result_path.exists() and not stopped_reason:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = result_template(run_name, horizon, with_weather)
        result["status"] = "FAIL_RESOURCE" if stopped_reason else "failed_worker"
        result["error"] = stopped_reason or f"worker exit code {process.returncode}"
        result["oom"] = "memory" in result["error"].lower()
    frame = pd.DataFrame(samples)
    training_samples = frame[frame["phase"] == "training"] if not frame.empty else frame
    if training_samples.empty:
        training_samples = frame
    peak = (
        float(training_samples["memory_used_mib"].max())
        if not training_samples.empty
        else float("nan")
    )
    result.update(
        {
            "gpu_name": gpu_name,
            "gpu_total_memory_mib": total_memory,
            "memory_before_mib": memory_before,
            "peak_total_mib": peak,
            "peak_delta_mib": peak - memory_before if memory_before is not None else float("nan"),
            "memory_after_mib": memory_after,
            "mean_gpu_utilization_percent": (
                float(training_samples["gpu_utilization_percent"].mean())
                if not training_samples.empty
                else float("nan")
            ),
        }
    )
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(
        f"{run_name}: status={result['status']}, time={result.get('training_seconds')}, "
        f"before={memory_before}, peak={peak}, after={memory_after} MiB"
    )
    return result


def evaluate_baseline(horizon: int) -> dict[str, Any]:
    (
        _,
        _,
        train_target,
        validation_target,
        train_ids,
        validation_ids,
        disease_ids,
        data_summary,
    ) = load_full_data(horizon, with_weather=False)
    contexts = pd.read_csv(CONTEXTS_PATH, dtype={"query_id": str})
    targets = pd.read_csv(
        TARGETS_PATH, dtype={"query_id": str, "disease_group_id": str}
    )
    train_set = set(train_ids)
    baseline = FrequencyRankingBaseline.fit_train(
        contexts[contexts["query_id"].isin(train_set)].copy(),
        targets[targets["query_id"].isin(train_set)].copy(),
        disease_ids,
        horizon,
        split_name="train",
    )
    validation_contexts = contexts.set_index("query_id").loc[validation_ids]
    disease_index = {disease_id: index for index, disease_id in enumerate(disease_ids)}
    order = np.empty((len(validation_ids), len(disease_ids)), dtype=np.int32)
    for row_index, (_, context) in enumerate(validation_contexts.iterrows()):
        order[row_index] = [
            disease_index[disease_id] for disease_id in baseline.rank(context)
        ]
    if train_target.shape != (len(train_ids), len(disease_ids)):
        raise RuntimeError("Baseline TRAIN target shape mismatch")
    return {
        "run_name": f"h{horizon}_baseline",
        "horizon": horizon,
        "status": "success",
        "query_count": len(train_ids),
        "validation_query_count": len(validation_ids),
        "disease_count": len(disease_ids),
        "feature_count": 3,
        "train_target_shape": f"{len(train_ids)}x{len(disease_ids)}",
        "validation_target_shape": f"{len(validation_ids)}x{len(disease_ids)}",
        "training_seconds": 0.0,
        "prediction_seconds": 0.0,
        "model_size_bytes": 0,
        **data_summary,
        **h7_pipeline.ranking_metrics_from_order(order, validation_target),
    }


def decide_horizon(
    horizon: int,
    config: dict[str, Any],
    weather: dict[str, Any],
    control: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[str, str]:
    prefix = f"H{horizon}"
    if any(row.get("status") != "success" or row.get("oom") for row in (weather, control)):
        return f"{prefix}_TRAINING_FAILED", "GPU training không hoàn tất an toàn."
    tolerance = float(config["baseline_competitive_tolerance"])
    competitive = (
        float(weather["ndcg_at_5"]) >= float(baseline["ndcg_at_5"]) - tolerance
        or float(weather["ndcg_at_10"]) >= float(baseline["ndcg_at_10"]) - tolerance
    )
    if not competitive:
        return (
            f"{prefix}_NOT_BETTER_THAN_BASELINE",
            "WITH WEATHER không cạnh tranh baseline trong tolerance NDCG đã khóa.",
        )
    deltas = {key: float(weather[key]) - float(control[key]) for key in METRIC_KEYS}
    practical = max(deltas["ndcg_at_5"], deltas["ndcg_at_10"]) >= float(
        config["weather_practical_ndcg_delta"]
    )
    severe_drop = min(deltas.values()) < -float(config["severe_metric_drop"])
    if practical and not severe_drop:
        return (
            f"{prefix}_WEATHER_PROMISING",
            "Weather NDCG gain đạt ngưỡng thực dụng và không suy giảm nghiêm trọng metric khác.",
        )
    return (
        f"{prefix}_MODEL_GOOD_BUT_WEATHER_WEAK",
        "Model cạnh tranh baseline nhưng weather gain chưa đạt ngưỡng thực dụng.",
    )


def load_h7_reference() -> dict[str, Any]:
    metrics = pd.read_csv(H7_METRICS_PATH)
    comparison = pd.read_csv(H7_COMPARISON_PATH).set_index("metric")
    weather = metrics.loc[metrics["run_name"] == "with_weather"].iloc[0].to_dict()
    control = metrics.loc[metrics["run_name"] == "no_weather"].iloc[0].to_dict()
    baseline = metrics.loc[metrics["run_name"] == "baseline"].iloc[0].to_dict()
    match = re.search(r"\*\*(H7_[A-Z_]+)\*\*", H7_REPORT_PATH.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("Cannot read H7 conclusion")
    return {
        "horizon": 7,
        "weather": weather,
        "control": control,
        "baseline": baseline,
        "comparison": comparison,
        "conclusion": match.group(1),
    }


def comparison_frame(
    horizon: int,
    weather: dict[str, Any],
    control: dict[str, Any],
    baseline: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    for key in METRIC_KEYS:
        w, n, b = float(weather[key]), float(control[key]), float(baseline[key])
        rows.append(
            {
                "metric": key,
                "with_weather": w,
                "no_weather": n,
                "baseline": b,
                "weather_minus_no_weather": w - n,
                "weather_minus_baseline": w - b,
                "no_weather_minus_baseline": n - b,
            }
        )
    return pd.DataFrame(rows)


def write_validation_metrics(
    horizon: int,
    weather: dict[str, Any],
    control: dict[str, Any],
    baseline: dict[str, Any],
) -> None:
    frame = pd.DataFrame([weather, control, baseline])
    preferred = [
        "run_name",
        "horizon",
        "status",
        "query_count",
        "validation_query_count",
        "disease_count",
        "feature_count",
        "train_target_shape",
        "validation_target_shape",
        "requested_iterations",
        "best_iteration",
        "final_iteration",
        "early_stopped",
        "training_seconds",
        "prediction_seconds",
        "model_size_bytes",
        *METRIC_KEYS,
        "train_mean_positive_diseases",
        "train_median_positive_diseases",
        "validation_mean_positive_diseases",
        "validation_median_positive_diseases",
        "evaluated_validation_queries",
        "zero_positive_validation_queries",
        "memory_before_mib",
        "peak_total_mib",
        "peak_delta_mib",
        "memory_after_mib",
        "mean_gpu_utilization_percent",
        "oom",
        "error",
    ]
    for column in preferred:
        if column not in frame:
            frame[column] = None
    frame[preferred].to_csv(METRICS_DIR / f"h{horizon}_validation_metrics.csv", index=False)


def make_horizon_row(
    horizon: int,
    weather: dict[str, Any],
    control: dict[str, Any],
    baseline: dict[str, Any],
    conclusion: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "horizon": f"H{horizon}",
        "conclusion": conclusion,
        "validation_mean_positive_diseases": weather.get("validation_mean_positive_diseases"),
        "validation_median_positive_diseases": weather.get("validation_median_positive_diseases"),
        "zero_positive_validation_queries": weather.get("zero_positive_validation_queries"),
        "with_weather_best_iteration": weather.get("best_iteration"),
        "no_weather_best_iteration": control.get("best_iteration"),
        "with_weather_training_seconds": weather.get("training_seconds"),
        "no_weather_training_seconds": control.get("training_seconds"),
    }
    for key in METRIC_KEYS:
        w, n, b = float(weather[key]), float(control[key]), float(baseline[key])
        row[f"with_weather_{key}"] = w
        row[f"no_weather_{key}"] = n
        row[f"baseline_{key}"] = b
        row[f"weather_minus_no_weather_{key}"] = w - n
        row[f"weather_minus_baseline_{key}"] = w - b
    return row


def recommend_horizon(rows: list[dict[str, Any]]) -> tuple[str, str]:
    promising = [row for row in rows if row["conclusion"].endswith("WEATHER_PROMISING")]
    if len(promising) == 1:
        winner = promising[0]
        return (
            winner["horizon"],
            "Chỉ horizon này đạt weather-gain gate, cạnh tranh baseline và không có metric suy giảm nghiêm trọng.",
        )
    if len(promising) > 1:
        for candidate in promising:
            others = [row for row in promising if row is not candidate]
            if all(
                candidate["weather_minus_no_weather_ndcg_at_5"]
                >= other["weather_minus_no_weather_ndcg_at_5"]
                and candidate["weather_minus_no_weather_ndcg_at_10"]
                >= other["weather_minus_no_weather_ndcg_at_10"]
                and candidate["weather_minus_baseline_ndcg_at_5"]
                >= other["weather_minus_baseline_ndcg_at_5"]
                for other in others
            ):
                return (
                    candidate["horizon"],
                    "Horizon này trội hơn các horizon promising còn lại về weather gain và baseline gain, không chỉ metric tuyệt đối.",
                )
    return (
        "NO_CLEAR_WINNER",
        "Không có một horizon thắng rõ theo weather gain, baseline gain và tính nhất quán NDCG@5/NDCG@10; không nên chọn chỉ theo metric tuyệt đối.",
    )


def fmt(value: Any, digits: int = 4) -> str:
    return h7_pipeline.fmt(value, digits)


def metric_table_lines(comparison: pd.DataFrame) -> list[str]:
    labels = {
        "precision_at_5": "Precision@5",
        "recall_at_5": "Recall@5",
        "ndcg_at_5": "NDCG@5",
        "precision_at_10": "Precision@10",
        "recall_at_10": "Recall@10",
        "ndcg_at_10": "NDCG@10",
    }
    lines = [
        "| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather-NoWeather | Weather-Baseline |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in comparison.itertuples(index=False):
        lines.append(
            f"| {labels[row.metric]} | {fmt(row.with_weather)} | {fmt(row.no_weather)} | "
            f"{fmt(row.baseline)} | {fmt(row.weather_minus_no_weather, 6)} | "
            f"{fmt(row.weather_minus_baseline, 6)} |"
        )
    return lines


def write_training_report(
    results: dict[int, dict[str, Any]],
    comparisons: dict[int, pd.DataFrame],
    conclusions: dict[int, tuple[str, str]],
    integrity_pass: bool,
) -> None:
    first = results[3]["weather"]
    lines = [
        "# H3 and H14 Full-Train Report",
        "",
        "> Full TRAIN cho H3/H14; chọn iteration bằng VALIDATION. H7 chỉ là reference và TEST chưa được sử dụng.",
        "",
        "## DATA",
        "",
        f"- TRAIN: {first.get('query_count')} queries, {first.get('train_date_start')} → {first.get('train_date_end')}.",
        f"- VALIDATION: {first.get('validation_query_count')} queries, {first.get('validation_date_start')} → {first.get('validation_date_end')}.",
        f"- Cùng disease universe tính từ TRAIN cho H3/H7/H14: {first.get('disease_count')}.",
        f"- Feature count WITH/NO: {first.get('feature_count')} / {results[3]['control'].get('feature_count')}.",
        "- LIGHT_A giữ nguyên H7: MultiLogloss, GPU, 300 max iterations, depth=4, border_count=32, one_hot_max_size=20, learning_rate=0.1, seed=42, gpu_ram_part=0.85, od_wait=30.",
    ]
    for horizon in (3, 14):
        weather = results[horizon]["weather"]
        control = results[horizon]["control"]
        baseline = results[horizon]["baseline"]
        conclusion, reason = conclusions[horizon]
        lines.extend(
            [
                "",
                f"## H{horizon}",
                "",
                f"- Target: `has_case_h{horizon}`; TRAIN/VALIDATION matrix: `{weather.get('train_target_shape')}` / `{weather.get('validation_target_shape')}`.",
                f"- Positive diseases/query VALIDATION: mean={fmt(weather.get('validation_mean_positive_diseases'), 3)}, median={fmt(weather.get('validation_median_positive_diseases'), 3)}, zero-positive={weather.get('zero_positive_validation_queries')}.",
                f"- Metrics average trên {weather.get('evaluated_validation_queries')} query có positive, đúng logic H7.",
                "",
                *metric_table_lines(comparisons[horizon]),
                "",
                "| Resource | WITH WEATHER | NO WEATHER |",
                "|---|---:|---:|",
                f"| Best iteration (1-based) | {weather.get('best_iteration')} | {control.get('best_iteration')} |",
                f"| Final/model tree count | {weather.get('final_iteration')} | {control.get('final_iteration')} |",
                f"| Train time (s) | {fmt(weather.get('training_seconds'), 3)} | {fmt(control.get('training_seconds'), 3)} |",
                f"| Prediction time (s) | {fmt(weather.get('prediction_seconds'), 3)} | {fmt(control.get('prediction_seconds'), 3)} |",
                f"| Memory before (MiB) | {fmt(weather.get('memory_before_mib'), 1)} | {fmt(control.get('memory_before_mib'), 1)} |",
                f"| Peak total VRAM (MiB) | {fmt(weather.get('peak_total_mib'), 1)} | {fmt(control.get('peak_total_mib'), 1)} |",
                f"| Peak delta VRAM (MiB) | {fmt(weather.get('peak_delta_mib'), 1)} | {fmt(control.get('peak_delta_mib'), 1)} |",
                f"| Mean GPU utilization (%) | {fmt(weather.get('mean_gpu_utilization_percent'), 1)} | {fmt(control.get('mean_gpu_utilization_percent'), 1)} |",
                f"| Model size (bytes) | {weather.get('model_size_bytes')} | {control.get('model_size_bytes')} |",
                "",
                f"**{conclusion}** — {reason}",
                "",
                f"Baseline H{horizon} dùng hierarchy TRAIN-only `age_group + gender + month → age_group + month → month → global` và `case_count_h{horizon}` làm tần suất prior; target model vẫn là binary `has_case_h{horizon}`.",
            ]
        )
    lines.extend(
        [
            "",
            "## Diễn giải và integrity",
            "",
            "Weather delta chỉ thể hiện tín hiệu dự báo thống kê, không chứng minh quan hệ nhân quả.",
            "",
            "Model xếp hạng các nhóm bệnh dựa trên mẫu hình thống kê trong dữ liệu bệnh viện và thời tiết lịch sử. Không phải chẩn đoán cá nhân.",
            "",
            f"- Raw/processed/split và toàn bộ H7 checksum: **{'PASS' if integrity_pass else 'FAIL'}**.",
            "- TEST không được parse, predict, tính metric hay dùng chọn horizon; chỉ checksum file được đối chiếu.",
            "- H7 không retrain; không model chính thức, SHAP, tuning, API, frontend/backend.",
            "- Mọi artifact mới chỉ nằm trong `experiments/h3_h14_full_train/`.",
            "",
        ]
    )
    TRAINING_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def write_horizon_report(
    rows: list[dict[str, Any]], recommended: str, reason: str
) -> None:
    indexed = {row["horizon"]: row for row in rows}
    lines = [
        "# H3 / H7 / H14 Horizon Comparison",
        "",
        "> So sánh VALIDATION trên cùng temporal split và cùng 221-disease universe. TEST chưa được sử dụng.",
        "",
        "## Summary",
        "",
    ]
    for label in ("H3", "H7", "H14"):
        row = indexed[label]
        lines.append(
            f"- **{label}:** {row['conclusion']}; positive/query mean={fmt(row['validation_mean_positive_diseases'], 2)}, median={fmt(row['validation_median_positive_diseases'], 1)}."
        )
    lines.extend(
        [
            "",
            "## WITH WEATHER metrics",
            "",
            "| Metric | H3 Weather | H7 Weather | H14 Weather |",
            "|---|---:|---:|---:|",
        ]
    )
    for key, label in (
        ("precision_at_5", "Precision@5"),
        ("recall_at_5", "Recall@5"),
        ("ndcg_at_5", "NDCG@5"),
        ("precision_at_10", "Precision@10"),
        ("recall_at_10", "Recall@10"),
        ("ndcg_at_10", "NDCG@10"),
    ):
        lines.append(
            f"| {label} | {fmt(indexed['H3'][f'with_weather_{key}'])} | "
            f"{fmt(indexed['H7'][f'with_weather_{key}'])} | "
            f"{fmt(indexed['H14'][f'with_weather_{key}'])} |"
        )
    for key, title in (("ndcg_at_5", "NDCG@5"), ("ndcg_at_10", "NDCG@10")):
        lines.extend(
            [
                "",
                f"## {title}: weather, control và baseline",
                "",
                f"| Horizon | Weather {title} | NoWeather {title} | Baseline {title} | Weather-NoWeather | Weather-Baseline |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for label in ("H3", "H7", "H14"):
            row = indexed[label]
            lines.append(
                f"| {label} | {fmt(row[f'with_weather_{key}'])} | "
                f"{fmt(row[f'no_weather_{key}'])} | {fmt(row[f'baseline_{key}'])} | "
                f"{fmt(row[f'weather_minus_no_weather_{key}'], 6)} | "
                f"{fmt(row[f'weather_minus_baseline_{key}'], 6)} |"
            )
    lines.extend(
        [
            "",
            "## Positive support và training",
            "",
            "| Horizon | Mean positive/query | Median | Zero-positive VALIDATION | WITH time (s) | NO time (s) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for label in ("H3", "H7", "H14"):
        row = indexed[label]
        lines.append(
            f"| {label} | {fmt(row['validation_mean_positive_diseases'], 3)} | "
            f"{fmt(row['validation_median_positive_diseases'], 3)} | "
            f"{row['zero_positive_validation_queries']} | "
            f"{fmt(row['with_weather_training_seconds'], 3)} | "
            f"{fmt(row['no_weather_training_seconds'], 3)} |"
        )
    lines.extend(
        [
            "",
            "Recall giữa các horizon không nên so máy móc vì số positive disease/query thay đổi theo độ dài horizon.",
            "",
            "## Recommendation",
            "",
            f"**Recommended horizon for final TEST: {recommended}**",
            "",
            f"**Reason:** {reason}",
            "",
            "Không model nào được copy thành production/final và TEST chưa được chạy.",
            "",
        ]
    )
    HORIZON_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def orchestrate() -> int:
    for directory in (METRICS_DIR, LOG_DIR, MODEL_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    ORCHESTRATOR_LOG.write_text("", encoding="utf-8")
    config = read_config()
    hashes_before = verify_all_locked(config)
    gpu_name, total, used, _ = h7_pipeline.query_gpu()
    log(f"GPU={gpu_name}; total={total:.0f} MiB; initial used={used:.0f} MiB")
    results: dict[int, dict[str, Any]] = {}
    conclusions: dict[int, tuple[str, str]] = {}
    comparisons: dict[int, pd.DataFrame] = {}
    failed = False
    for horizon in config["horizons"]:
        weather = run_isolated(f"h{horizon}_with_weather", horizon, True)
        control = run_isolated(f"h{horizon}_no_weather", horizon, False)
        try:
            baseline = evaluate_baseline(horizon)
        except Exception as exc:
            traceback.print_exc()
            baseline = {
                "run_name": f"h{horizon}_baseline",
                "horizon": horizon,
                "status": "failed",
                "error": str(exc),
            }
        results[horizon] = {
            "weather": weather,
            "control": control,
            "baseline": baseline,
        }
        write_validation_metrics(horizon, weather, control, baseline)
        if all(row.get("status") == "success" for row in (weather, control, baseline)):
            comparisons[horizon] = comparison_frame(horizon, weather, control, baseline)
            conclusions[horizon] = decide_horizon(
                horizon, config, weather, control, baseline
            )
        else:
            comparisons[horizon] = pd.DataFrame()
            conclusions[horizon] = (
                f"H{horizon}_TRAINING_FAILED",
                "Training hoặc baseline evaluation không hoàn tất.",
            )
            failed = True
    hashes_after = verify_all_locked(config)
    integrity_pass = hashes_before == hashes_after
    if not failed:
        h7_ref = load_h7_reference()
        rows = [
            make_horizon_row(
                3,
                results[3]["weather"],
                results[3]["control"],
                results[3]["baseline"],
                conclusions[3][0],
            ),
            make_horizon_row(
                7,
                h7_ref["weather"],
                h7_ref["control"],
                h7_ref["baseline"],
                h7_ref["conclusion"],
            ),
            make_horizon_row(
                14,
                results[14]["weather"],
                results[14]["control"],
                results[14]["baseline"],
                conclusions[14][0],
            ),
        ]
        pd.DataFrame(rows).to_csv(METRICS_DIR / "horizon_comparison.csv", index=False)
        recommended, recommendation_reason = recommend_horizon(rows)
        write_training_report(
            results, comparisons, conclusions, integrity_pass
        )
        write_horizon_report(rows, recommended, recommendation_reason)
    else:
        recommended = "NO_CLEAR_WINNER"
        recommendation_reason = "Ít nhất một training/evaluation run thất bại."
        pd.DataFrame().to_csv(METRICS_DIR / "horizon_comparison.csv", index=False)
        TRAINING_REPORT_PATH.write_text(
            "# H3 and H14 Full-Train Report\n\nH3/H14 training failed. TEST chưa được sử dụng.\n",
            encoding="utf-8",
        )
        HORIZON_REPORT_PATH.write_text(
            "# Horizon Comparison\n\nRecommended horizon: NO_CLEAR_WINNER\n",
            encoding="utf-8",
        )
    summary = {
        "h3": conclusions[3][0],
        "h14": conclusions[14][0],
        "recommended_horizon_for_final_test": recommended,
        "recommendation_reason": recommendation_reason,
        "integrity_pass": integrity_pass,
        "h7_retrained": False,
        "test_used": False,
        "reports": [str(TRAINING_REPORT_PATH), str(HORIZON_REPORT_PATH)],
    }
    log(json.dumps(summary, ensure_ascii=True))
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker")
    parser.add_argument("--horizon", type=int, choices=[3, 14])
    parser.add_argument("--with-weather", choices=["0", "1"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        if args.horizon is None or args.with_weather is None:
            raise SystemExit("Worker requires --horizon and --with-weather")
        return worker(args.worker, args.horizon, args.with_weather == "1")
    return orchestrate()


if __name__ == "__main__":
    raise SystemExit(main())
