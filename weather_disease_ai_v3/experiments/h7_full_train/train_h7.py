"""Full-TRAIN H7 weather experiment with a train-only frequency baseline.

The default process validates locked inputs, runs WITH_WEATHER and NO_WEATHER
in separate CUDA subprocesses, evaluates a TRAIN-only baseline on VALIDATION,
and writes all artifacts below experiments/h7_full_train/. TEST is never
parsed as data; its bytes are hashed only for the final integrity check.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
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
CONFIG_PATH = EXPERIMENT_DIR / "train_config.json"
REPORT_PATH = EXPERIMENT_DIR / "H7_TRAINING_REPORT.md"
METRICS_DIR = EXPERIMENT_DIR / "metrics"
LOG_DIR = EXPERIMENT_DIR / "logs"
MODEL_DIR = EXPERIMENT_DIR / "models"
VALIDATION_METRICS_PATH = METRICS_DIR / "validation_metrics.csv"
COMPARISON_PATH = METRICS_DIR / "comparison.csv"
ORCHESTRATOR_LOG = LOG_DIR / "orchestrator.log"

CONTEXTS_PATH = PROJECT_ROOT / "data/processed/contexts.csv.gz"
TARGETS_PATH = PROJECT_ROOT / "data/processed/targets.csv.gz"
METADATA_PATH = PROJECT_ROOT / "data/processed/dataset_metadata.json"
TRAIN_IDS_PATH = PROJECT_ROOT / "data/splits/train_query_ids.csv"
VALIDATION_IDS_PATH = PROJECT_ROOT / "data/splits/validation_query_ids.csv"

METRIC_KEYS = (
    "precision_at_5",
    "recall_at_5",
    "ndcg_at_5",
    "precision_at_10",
    "recall_at_10",
    "ndcg_at_10",
)


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}"
    with ORCHESTRATOR_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


def read_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sources(config: dict[str, Any]) -> dict[str, str]:
    actual: dict[str, str] = {}
    for relative, expected in config["source_sha256"].items():
        path = PROJECT_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing locked source: {path}")
        checksum = sha256_file(path)
        actual[relative] = checksum
        if checksum != expected:
            raise RuntimeError(
                f"Locked input changed: {relative}; expected={expected}, actual={checksum}"
            )
    return actual


def query_gpu() -> tuple[str, float, float, float]:
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
            "--id=0",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    ).strip()
    row = next(csv.reader([output]))
    return row[0].strip(), float(row[1]), float(row[2]), float(row[3])


def sorted_disease_ids(values: set[str]) -> list[str]:
    def key(value: str) -> tuple[int, int | str]:
        return (0, int(value)) if value.isdigit() else (1, value)

    return sorted((str(value) for value in values), key=key)


def build_target_matrix(
    query_ids: list[str], disease_ids: list[str], targets: pd.DataFrame
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


def load_full_data(
    *, with_weather: bool
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
        raise RuntimeError("TRAIN and VALIDATION query IDs overlap")
    indexed_contexts = contexts.set_index("query_id", drop=False)
    if not set(train_ids + validation_ids).issubset(indexed_contexts.index):
        raise RuntimeError("Some TRAIN/VALIDATION query IDs are absent from contexts")
    train_targets = targets[targets["query_id"].isin(set(train_ids))]
    supported_mask = (
        train_targets[["has_case_h3", "has_case_h7", "has_case_h14"]].max(axis=1) > 0
    )
    disease_ids = sorted_disease_ids(
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
        if column in {"query_id", "anchor_date", "year", "disease_group_id", "disease_group_name"}
        or any(token in column.lower() for token in ("target", "has_case", "case_count"))
    ]
    if forbidden:
        raise RuntimeError(f"Forbidden feature columns: {forbidden}")
    if not with_weather:
        weather_tokens = (
            "weather",
            "temperature",
            "humidity",
            "rain",
            "precipitation",
            "wind",
        )
        weather_leak = [
            column
            for column in feature_columns
            if any(token in column.lower() for token in weather_tokens)
        ]
        if weather_leak:
            raise RuntimeError(f"NO_WEATHER contains weather columns: {weather_leak}")

    def prepare(ids: list[str]) -> pd.DataFrame:
        frame = indexed_contexts.loc[ids, feature_columns].reset_index(drop=True).copy()
        for column in config["categorical_features"]:
            frame[column] = frame[column].fillna("Không rõ").astype(str)
        frame["month"] = pd.to_numeric(frame["month"], errors="raise").astype("int16")
        return frame

    train_features = prepare(train_ids)
    validation_features = prepare(validation_ids)
    train_target = build_target_matrix(train_ids, disease_ids, targets)
    validation_target = build_target_matrix(validation_ids, disease_ids, targets)
    if not ((train_target.min(axis=0) == 0) & (train_target.max(axis=0) == 1)).all():
        raise RuntimeError("TRAIN target contains a constant disease column")
    train_dates = pd.to_datetime(indexed_contexts.loc[train_ids, "anchor_date"])
    validation_dates = pd.to_datetime(indexed_contexts.loc[validation_ids, "anchor_date"])
    data_summary = {
        "train_date_start": str(train_dates.min().date()),
        "train_date_end": str(train_dates.max().date()),
        "validation_date_start": str(validation_dates.min().date()),
        "validation_date_end": str(validation_dates.max().date()),
        "train_mean_positive_diseases": float(train_target.sum(axis=1).mean()),
        "train_median_positive_diseases": float(np.median(train_target.sum(axis=1))),
        "validation_mean_positive_diseases": float(validation_target.sum(axis=1).mean()),
        "validation_median_positive_diseases": float(np.median(validation_target.sum(axis=1))),
        "validation_zero_positive_queries": int((validation_target.sum(axis=1) == 0).sum()),
    }
    return (
        train_features,
        validation_features,
        train_target,
        validation_target,
        train_ids,
        validation_ids,
        disease_ids,
        data_summary,
    )


def ranking_metrics_from_order(
    order: np.ndarray, target: np.ndarray
) -> dict[str, float | int]:
    if order.shape != target.shape:
        raise RuntimeError(f"Ranking shape {order.shape} != target shape {target.shape}")
    records: list[dict[str, float]] = []
    for row_index in range(len(target)):
        relevant = set(np.flatnonzero(target[row_index]))
        if not relevant:
            continue
        row: dict[str, float] = {}
        for k in (5, 10):
            top = order[row_index, :k]
            hits = sum(int(index) in relevant for index in top)
            dcg = sum(
                1.0 / math.log2(position + 2)
                for position, index in enumerate(top)
                if int(index) in relevant
            )
            ideal = sum(
                1.0 / math.log2(position + 2)
                for position in range(min(len(relevant), k))
            )
            row[f"precision_at_{k}"] = hits / k
            row[f"recall_at_{k}"] = hits / len(relevant)
            row[f"ndcg_at_{k}"] = dcg / ideal
        records.append(row)
    frame = pd.DataFrame(records)
    result: dict[str, float | int] = {
        column: float(frame[column].mean()) for column in frame.columns
    }
    result["evaluated_validation_queries"] = int(len(frame))
    result["zero_positive_validation_queries"] = int(len(target) - len(frame))
    return result


def ranking_metrics(scores: np.ndarray, target: np.ndarray) -> dict[str, float | int]:
    if scores.shape != target.shape:
        raise RuntimeError(f"Score shape {scores.shape} != target shape {target.shape}")
    order = np.argsort(-scores, axis=1, kind="stable")
    return ranking_metrics_from_order(order, target)


def result_template(run_name: str, with_weather: bool) -> dict[str, Any]:
    return {
        "run_name": run_name,
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
        "precision_at_5": float("nan"),
        "recall_at_5": float("nan"),
        "ndcg_at_5": float("nan"),
        "precision_at_10": float("nan"),
        "recall_at_10": float("nan"),
        "ndcg_at_10": float("nan"),
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


def worker(run_name: str, with_weather: bool) -> int:
    from catboost import CatBoostClassifier, Pool
    import catboost

    config = read_config()
    phase_path = LOG_DIR / f"{run_name}_phase.txt"
    go_path = LOG_DIR / f"{run_name}_go.flag"
    result_path = LOG_DIR / f"{run_name}_result.json"
    result = result_template(run_name, with_weather)
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
        ) = load_full_data(with_weather=with_weather)
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
        cat_features = list(config["categorical_features"])
        train_pool = Pool(train_features, label=train_target, cat_features=cat_features)
        validation_pool = Pool(
            validation_features, label=validation_target, cat_features=cat_features
        )
        params = {
            "loss_function": config["loss_function"],
            "task_type": config["task_type"],
            "devices": config["devices"],
            "gpu_ram_part": config["gpu_ram_part"],
            "iterations": config["iterations"],
            "depth": config["depth"],
            "border_count": config["border_count"],
            "one_hot_max_size": config["one_hot_max_size"],
            "learning_rate": config["learning_rate"],
            "random_seed": config["random_seed"],
            "verbose": config["verbose"],
            "allow_writing_files": config["allow_writing_files"],
            "use_best_model": config["use_best_model"],
            "od_type": config["od_type"],
            "od_wait": config["od_wait"],
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
        model_path = MODEL_DIR / f"h7_{run_name}.cbm"
        model.save_model(model_path)
        loaded = CatBoostClassifier()
        loaded.load_model(model_path)
        started = time.perf_counter()
        scores = np.asarray(loaded.predict_proba(validation_pool), dtype=np.float64)
        result["prediction_seconds"] = time.perf_counter() - started
        if scores.shape != (len(validation_ids), len(disease_ids)):
            raise RuntimeError(f"Prediction shape invalid: {scores.shape}")
        result.update(ranking_metrics(scores, validation_target))
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


def terminate_process(process: subprocess.Popen[Any]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_isolated(run_name: str, with_weather: bool) -> dict[str, Any]:
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
                    _, _, memory_before, _ = query_gpu()
                    log(
                        f"{run_name}: GPU memory before training={memory_before:.0f} MiB"
                    )
                    go_path.write_text("go", encoding="utf-8")
                if phase == "training":
                    training_started = time.perf_counter()
            gpu_name, total_memory, used_memory, utilization = query_gpu()
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
                    f"training exceeded safety timeout "
                    f"{config['training_timeout_seconds']} seconds"
                )
            if stopped_reason:
                log(f"{run_name}: FAIL_RESOURCE {stopped_reason}")
                terminate_process(process)
                break
            time.sleep(config["gpu_monitor_interval_seconds"])
    _, total_memory, memory_after, _ = query_gpu()
    pd.DataFrame(samples).to_csv(gpu_log, index=False)
    if result_path.exists() and not stopped_reason:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = result_template(run_name, with_weather)
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
            "peak_delta_mib": (
                peak - memory_before if memory_before is not None else float("nan")
            ),
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


def evaluate_baseline() -> dict[str, Any]:
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.baseline import FrequencyRankingBaseline

    (
        _,
        _,
        train_target,
        validation_target,
        train_ids,
        validation_ids,
        disease_ids,
        data_summary,
    ) = load_full_data(with_weather=False)
    contexts = pd.read_csv(CONTEXTS_PATH, dtype={"query_id": str})
    targets = pd.read_csv(
        TARGETS_PATH, dtype={"query_id": str, "disease_group_id": str}
    )
    train_set = set(train_ids)
    train_contexts = contexts[contexts["query_id"].isin(train_set)].copy()
    train_targets = targets[targets["query_id"].isin(train_set)].copy()
    baseline = FrequencyRankingBaseline.fit_train(
        train_contexts,
        train_targets,
        disease_ids,
        7,
        split_name="train",
    )
    validation_contexts = contexts.set_index("query_id").loc[validation_ids]
    disease_index = {disease_id: index for index, disease_id in enumerate(disease_ids)}
    order = np.empty((len(validation_ids), len(disease_ids)), dtype=np.int32)
    for row_index, (_, context) in enumerate(validation_contexts.iterrows()):
        ranking = baseline.rank(context)
        order[row_index] = [disease_index[disease_id] for disease_id in ranking]
    result = {
        "run_name": "baseline",
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
        **ranking_metrics_from_order(order, validation_target),
    }
    if train_target.shape != (len(train_ids), len(disease_ids)):
        raise RuntimeError("Baseline TRAIN target shape mismatch")
    return result


def decide(
    config: dict[str, Any],
    with_weather: dict[str, Any],
    no_weather: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[str, str]:
    if any(
        row.get("status") != "success" or row.get("oom")
        for row in (with_weather, no_weather)
    ):
        return "H7_TRAINING_FAILED", "Ít nhất một GPU training run không hoàn tất an toàn."
    tolerance = float(config["baseline_competitive_tolerance"])
    baseline_competitive = (
        float(with_weather["ndcg_at_5"]) >= float(baseline["ndcg_at_5"]) - tolerance
        or float(with_weather["ndcg_at_10"])
        >= float(baseline["ndcg_at_10"]) - tolerance
    )
    if not baseline_competitive:
        return (
            "H7_NOT_BETTER_THAN_BASELINE",
            "WITH WEATHER không cạnh tranh baseline trong tolerance NDCG đã khóa.",
        )
    weather_deltas = {
        key: float(with_weather[key]) - float(no_weather[key]) for key in METRIC_KEYS
    }
    practical = max(weather_deltas["ndcg_at_5"], weather_deltas["ndcg_at_10"]) >= float(
        config["weather_practical_ndcg_delta"]
    )
    severe_drop = min(weather_deltas.values()) < -float(config["severe_metric_drop"])
    if practical and not severe_drop:
        return (
            "H7_WEATHER_PROMISING",
            "WITH WEATHER có NDCG gain đủ ngưỡng thực dụng và không làm suy giảm nghiêm trọng metric khác.",
        )
    return (
        "H7_MODEL_GOOD_BUT_WEATHER_WEAK",
        "Model cạnh tranh baseline nhưng weather gain chưa đạt ngưỡng thực dụng đã khóa.",
    )


def fmt(value: Any, digits: int = 4) -> str:
    try:
        number = float(value)
        return "N/A" if math.isnan(number) else f"{number:.{digits}f}"
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "N/A"


def write_metric_files(
    with_weather: dict[str, Any],
    no_weather: dict[str, Any],
    baseline: dict[str, Any],
) -> pd.DataFrame:
    validation_columns = [
        "run_name",
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
    rows = [with_weather, no_weather, baseline]
    frame = pd.DataFrame(rows)
    for column in validation_columns:
        if column not in frame:
            frame[column] = None
    frame[validation_columns].to_csv(VALIDATION_METRICS_PATH, index=False)
    comparison_rows = []
    for key in METRIC_KEYS:
        weather = float(with_weather[key])
        control = float(no_weather[key])
        base = float(baseline[key])
        comparison_rows.append(
            {
                "metric": key,
                "with_weather": weather,
                "no_weather": control,
                "baseline": base,
                "weather_minus_no_weather": weather - control,
                "weather_minus_baseline": weather - base,
                "no_weather_minus_baseline": control - base,
            }
        )
    comparison = pd.DataFrame(comparison_rows)
    comparison.to_csv(COMPARISON_PATH, index=False)
    return comparison


def write_report(
    config: dict[str, Any],
    with_weather: dict[str, Any],
    no_weather: dict[str, Any],
    baseline: dict[str, Any],
    comparison: pd.DataFrame,
    decision: str,
    reason: str,
    integrity_pass: bool,
) -> None:
    by_metric = comparison.set_index("metric")
    lines = [
        "# H7 Full-Train Stage 1 Report",
        "",
        "> Chỉ train H7 trên TRAIN và đánh giá trên VALIDATION. TEST không được load vào pipeline.",
        "",
        "## Dữ liệu",
        "",
        f"- TRAIN queries: {with_weather.get('query_count')}; date range: {with_weather.get('train_date_start')} → {with_weather.get('train_date_end')}.",
        f"- VALIDATION queries: {with_weather.get('validation_query_count')}; date range: {with_weather.get('validation_date_start')} → {with_weather.get('validation_date_end')}.",
        f"- Disease supported tính lại từ TRAIN: {with_weather.get('disease_count')}.",
        f"- Target TRAIN/VALIDATION: `{with_weather.get('train_target_shape')}` / `{with_weather.get('validation_target_shape')}`.",
        f"- Feature count WITH/NO: {with_weather.get('feature_count')} / {no_weather.get('feature_count')}.",
        f"- Số disease positive/query trên VALIDATION: mean={fmt(with_weather.get('validation_mean_positive_diseases'), 3)}, median={fmt(with_weather.get('validation_median_positive_diseases'), 3)}; zero-positive={with_weather.get('zero_positive_validation_queries')}.",
        f"- Metric chỉ average trên {with_weather.get('evaluated_validation_queries')} query có ít nhất một positive, giống benchmark trước.",
        "",
        "## Cấu hình cố định",
        "",
        f"- CatBoost `{with_weather.get('catboost_version', 'N/A')}`, `MultiLogloss`, GPU `{with_weather.get('gpu_name', 'N/A')}`.",
        "- LIGHT_A: depth=4, border_count=32, one_hot_max_size=20, learning_rate=0.1, random_seed=42.",
        "- iterations=300, use_best_model=true, od_type=Iter, od_wait=30, gpu_ram_part=0.85.",
        f"- CatBoost chấp nhận gpu_ram_part: WITH={with_weather.get('gpu_ram_part_supported')}, NO={no_weather.get('gpu_ram_part_supported')}.",
        "- Categorical: age_group, gender, season; month là numeric.",
        "",
        "## Kết quả VALIDATION",
        "",
        "| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather-NoWeather | Weather-Baseline |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    display = {
        "precision_at_5": "Precision@5",
        "recall_at_5": "Recall@5",
        "ndcg_at_5": "NDCG@5",
        "precision_at_10": "Precision@10",
        "recall_at_10": "Recall@10",
        "ndcg_at_10": "NDCG@10",
    }
    for key in METRIC_KEYS:
        row = by_metric.loc[key]
        lines.append(
            f"| {display[key]} | {fmt(row['with_weather'])} | {fmt(row['no_weather'])} | "
            f"{fmt(row['baseline'])} | {fmt(row['weather_minus_no_weather'], 6)} | "
            f"{fmt(row['weather_minus_baseline'], 6)} |"
        )
    lines.extend(
        [
            "",
            "Baseline dùng hierarchy `age_group + gender + month → age_group + month → month → global`, fit từ full TRAIN only và không dùng weather.",
            "",
            "## Tài nguyên",
            "",
            "| Resource | WITH WEATHER | NO WEATHER |",
            "|---|---:|---:|",
            f"| Requested iterations | {with_weather.get('requested_iterations')} | {no_weather.get('requested_iterations')} |",
            f"| Best iteration (1-based) | {with_weather.get('best_iteration')} | {no_weather.get('best_iteration')} |",
            f"| Final/model tree count | {with_weather.get('final_iteration')} | {no_weather.get('final_iteration')} |",
            f"| Early stopped | {with_weather.get('early_stopped')} | {no_weather.get('early_stopped')} |",
            f"| Train time (s) | {fmt(with_weather.get('training_seconds'), 3)} | {fmt(no_weather.get('training_seconds'), 3)} |",
            f"| Prediction time (s) | {fmt(with_weather.get('prediction_seconds'), 3)} | {fmt(no_weather.get('prediction_seconds'), 3)} |",
            f"| Memory before (MiB) | {fmt(with_weather.get('memory_before_mib'), 1)} | {fmt(no_weather.get('memory_before_mib'), 1)} |",
            f"| Peak total VRAM (MiB) | {fmt(with_weather.get('peak_total_mib'), 1)} | {fmt(no_weather.get('peak_total_mib'), 1)} |",
            f"| Peak delta VRAM (MiB) | {fmt(with_weather.get('peak_delta_mib'), 1)} | {fmt(no_weather.get('peak_delta_mib'), 1)} |",
            f"| Mean GPU utilization (%) | {fmt(with_weather.get('mean_gpu_utilization_percent'), 1)} | {fmt(no_weather.get('mean_gpu_utilization_percent'), 1)} |",
            f"| Model size (bytes) | {with_weather.get('model_size_bytes')} | {no_weather.get('model_size_bytes')} |",
            "",
            "WITH WEATHER và NO WEATHER chạy trong hai Python/CUDA process riêng. Không CPU fallback.",
            "",
            "## Kết luận",
            "",
            f"**{decision}** — {reason}",
            "",
            "Ngưỡng decision gate được khóa trước khi train: NDCG weather gain thực dụng ≥ 0.005; baseline tolerance 0.005; metric drop nghiêm trọng < -0.01.",
            "",
            "Model xếp hạng các nhóm bệnh dựa trên mẫu hình thống kê trong dữ liệu bệnh viện và thời tiết lịch sử. Không phải chẩn đoán cá nhân và không chứng minh quan hệ nhân quả.",
            "",
            "## Integrity",
            "",
            f"- Raw/processed/split checksum không đổi: **{'PASS' if integrity_pass else 'FAIL'}**.",
            "- TEST không được parse, load, train, predict hay tính metric; chỉ checksum file split được đối chiếu integrity.",
            "- Không train H3/H14; không SHAP, tuning, API hay frontend/backend.",
            "- Mọi artifact experiment mới chỉ nằm trong `experiments/h7_full_train/`.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def orchestrate() -> int:
    for directory in (METRICS_DIR, LOG_DIR, MODEL_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    ORCHESTRATOR_LOG.write_text("", encoding="utf-8")
    config = read_config()
    hashes_before = verify_sources(config)
    gpu_name, total, used, _ = query_gpu()
    log(f"GPU={gpu_name}; total={total:.0f} MiB; initial used={used:.0f} MiB")
    with_weather = run_isolated("with_weather", True)
    no_weather = run_isolated("no_weather", False)
    try:
        baseline = evaluate_baseline()
    except Exception as exc:
        traceback.print_exc()
        baseline = {"run_name": "baseline", "status": "failed", "error": str(exc)}
    if baseline.get("status") == "success" and all(
        row.get("status") == "success" for row in (with_weather, no_weather)
    ):
        comparison = write_metric_files(with_weather, no_weather, baseline)
        decision, reason = decide(config, with_weather, no_weather, baseline)
    else:
        pd.DataFrame([with_weather, no_weather, baseline]).to_csv(
            VALIDATION_METRICS_PATH, index=False
        )
        comparison = pd.DataFrame()
        comparison.to_csv(COMPARISON_PATH, index=False)
        decision = "H7_TRAINING_FAILED"
        reason = "Training hoặc baseline evaluation không hoàn tất."
    hashes_after = verify_sources(config)
    integrity_pass = hashes_before == hashes_after
    if not comparison.empty:
        write_report(
            config,
            with_weather,
            no_weather,
            baseline,
            comparison,
            decision,
            reason,
            integrity_pass,
        )
    else:
        REPORT_PATH.write_text(
            "# H7 Full-Train Stage 1 Report\n\n"
            f"**{decision}** — {reason}\n\n"
            "TEST chưa được sử dụng.\n",
            encoding="utf-8",
        )
    summary = {
        "with_weather": with_weather.get("status"),
        "no_weather": no_weather.get("status"),
        "baseline": baseline.get("status"),
        "decision": decision,
        "integrity_pass": integrity_pass,
        "test_used": False,
        "horizons_trained": [7],
        "report": str(REPORT_PATH),
    }
    log(json.dumps(summary, ensure_ascii=True))
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0 if decision != "H7_TRAINING_FAILED" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker")
    parser.add_argument("--with-weather", choices=["0", "1"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        if args.with_weather is None:
            raise SystemExit("Worker requires --with-weather")
        return worker(args.worker, args.with_weather == "1")
    return orchestrate()


if __name__ == "__main__":
    raise SystemExit(main())
