"""Isolated H7 lightweight CatBoost MultiLogloss benchmark.

The default mode orchestrates fresh GPU worker processes. Worker mode trains one
temporary configuration only. TEST is never loaded by this script.
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


BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parents[1]
CONFIG_PATH = BENCHMARK_DIR / "benchmark_config.json"
RESULTS_PATH = BENCHMARK_DIR / "benchmark_results.csv"
REPORT_PATH = BENCHMARK_DIR / "BENCHMARK_LIGHTWEIGHT_REPORT.md"
LOG_DIR = BENCHMARK_DIR / "logs"
ARTIFACT_DIR = BENCHMARK_DIR / "artifacts"
ORCHESTRATOR_LOG = LOG_DIR / "orchestrator.log"

CONTEXTS_PATH = PROJECT_ROOT / "data/processed/contexts.csv.gz"
TARGETS_PATH = PROJECT_ROOT / "data/processed/targets.csv.gz"
METADATA_PATH = PROJECT_ROOT / "data/processed/dataset_metadata.json"
TRAIN_ALL_PATH = PROJECT_ROOT / "data/splits/train_query_ids.csv"
OLD_TRAIN_SAMPLE = PROJECT_ROOT / "benchmarks/pretrain_model_selection/artifacts/train_benchmark_query_ids.csv"
OLD_VALIDATION_SAMPLE = PROJECT_ROOT / "benchmarks/pretrain_model_selection/artifacts/validation_benchmark_query_ids.csv"


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
    hashes: dict[str, str] = {}
    for relative, expected in config["source_sha256"].items():
        path = PROJECT_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing locked source: {path}")
        actual = sha256_file(path)
        hashes[relative] = actual
        if actual != expected:
            raise RuntimeError(
                f"Locked source changed: {relative}; expected={expected}, actual={actual}"
            )
    return hashes


def query_gpu() -> tuple[str, float, float]:
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
            "--id=0",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    ).strip()
    row = next(csv.reader([output]))
    return row[0].strip(), float(row[1]), float(row[2])


def disease_sort(values: set[str]) -> list[str]:
    def key(value: str) -> tuple[int, int | str]:
        return (0, int(value)) if value.isdigit() else (1, value)

    return sorted((str(value) for value in values), key=key)


def load_benchmark_data(
    with_weather: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, np.ndarray, list[str], list[str], list[str]]:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    targets = pd.read_csv(
        TARGETS_PATH, dtype={"query_id": str, "disease_group_id": str}
    )
    train_all = pd.read_csv(TRAIN_ALL_PATH, dtype={"query_id": str})
    train_universe = set(train_all["query_id"])
    train_rows = targets[targets["query_id"].isin(train_universe)]
    positive_any = train_rows[["has_case_h3", "has_case_h7", "has_case_h14"]].max(axis=1) > 0
    disease_ids = disease_sort(set(train_rows.loc[positive_any, "disease_group_id"]))
    train_sample = pd.read_csv(OLD_TRAIN_SAMPLE, dtype={"query_id": str})
    validation_sample = pd.read_csv(OLD_VALIDATION_SAMPLE, dtype={"query_id": str})
    contexts = pd.read_csv(CONTEXTS_PATH, dtype={"query_id": str}).set_index("query_id", drop=False)
    train_contexts = contexts.loc[train_sample["query_id"]].reset_index(drop=True)
    validation_contexts = contexts.loc[validation_sample["query_id"]].reset_index(drop=True)
    config = read_config()
    features = (
        list(metadata["model_feature_columns"])
        if with_weather
        else list(config["no_weather_features"])
    )
    forbidden = [
        column
        for column in features
        if column in {"query_id", "anchor_date", "year", "disease_group_id"}
        or any(token in column.lower() for token in ("target", "has_case", "case_count"))
    ]
    if forbidden:
        raise RuntimeError(f"Forbidden feature columns: {forbidden}")
    if not with_weather and any(
        token in column.lower()
        for column in features
        for token in ("temperature", "humidity", "rain", "precipitation", "wind", "weather")
    ):
        raise RuntimeError("NO_WEATHER feature list still contains weather")

    def feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
        output = frame[features].copy()
        for column in config["categorical_features"]:
            output[column] = output[column].fillna("Không rõ").astype(str)
        output["month"] = pd.to_numeric(output["month"], errors="raise").astype("int16")
        return output

    train_ids = train_contexts["query_id"].astype(str).tolist()
    validation_ids = validation_contexts["query_id"].astype(str).tolist()
    disease_index = {value: index for index, value in enumerate(disease_ids)}

    def target_matrix(query_ids: list[str]) -> np.ndarray:
        query_index = {value: index for index, value in enumerate(query_ids)}
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

    return (
        feature_frame(train_contexts),
        feature_frame(validation_contexts),
        target_matrix(train_ids),
        target_matrix(validation_ids),
        train_ids,
        validation_ids,
        disease_ids,
    )


def ranking_metrics(
    scores: np.ndarray,
    target: np.ndarray,
    query_ids: list[str],
) -> dict[str, float | int]:
    if scores.shape != target.shape:
        raise RuntimeError(f"Score shape {scores.shape} != target shape {target.shape}")
    order = np.argsort(-scores, axis=1, kind="stable")
    records: list[dict[str, float]] = []
    for row_index in range(len(query_ids)):
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
    result["validation_queries_without_positive_h7"] = int(len(query_ids) - len(frame))
    return result


def worker_result_template(name: str, with_weather: bool, depth: int) -> dict[str, Any]:
    return {
        "config_name": name,
        "status": "not_run",
        "error": "",
        "with_weather": with_weather,
        "depth": depth,
        "iterations": 100,
        "train_query_count": 0,
        "validation_query_count": 0,
        "disease_count": 0,
        "feature_count": 0,
        "target_shape": "",
        "categorical_handling": "CatBoost native categorical, one_hot_max_size=20",
        "smoke_status": "not_run",
        "smoke_seconds": float("nan"),
        "training_seconds": float("nan"),
        "prediction_seconds": float("nan"),
        "model_size_bytes": 0,
        "precision_at_5": float("nan"),
        "recall_at_5": float("nan"),
        "ndcg_at_5": float("nan"),
        "precision_at_10": float("nan"),
        "recall_at_10": float("nan"),
        "ndcg_at_10": float("nan"),
        "evaluated_validation_queries": 0,
        "validation_queries_without_positive_h7": 0,
    }


def write_phase(name: str, phase: str) -> None:
    (ARTIFACT_DIR / f"{name.lower()}_phase.txt").write_text(phase, encoding="utf-8")


def run_worker(name: str, depth: int, with_weather: bool) -> int:
    from catboost import CatBoostClassifier, Pool
    import catboost

    config = read_config()
    result = worker_result_template(name, with_weather, depth)
    result["catboost_version"] = catboost.__version__
    output_path = ARTIFACT_DIR / f"{name.lower()}_result.json"
    try:
        write_phase(name, "setup")
        (
            train_features,
            validation_features,
            train_target,
            validation_target,
            train_ids,
            validation_ids,
            disease_ids,
        ) = load_benchmark_data(with_weather)
        result.update(
            {
                "train_query_count": len(train_ids),
                "validation_query_count": len(validation_ids),
                "disease_count": len(disease_ids),
                "feature_count": train_features.shape[1],
                "target_shape": f"{len(train_ids)}x{len(disease_ids)}",
            }
        )
        smoke_train = min(config["smoke_train_queries"], len(train_ids))
        smoke_validation = min(config["smoke_validation_queries"], len(validation_ids))
        smoke_matrix = train_target[:smoke_train]
        if not ((smoke_matrix.min(axis=0) == 0) & (smoke_matrix.max(axis=0) == 1)).all():
            raise RuntimeError("Old smoke query order does not cover variable H7 labels")
        cat_features = list(config["categorical_features"])
        params = {
            "loss_function": config["loss_function"],
            "task_type": config["task_type"],
            "devices": config["devices"],
            "depth": depth,
            "learning_rate": config["learning_rate"],
            "border_count": config["border_count"],
            "one_hot_max_size": config["one_hot_max_size"],
            "random_seed": config["random_seed"],
            "allow_writing_files": config["allow_writing_files"],
            "use_best_model": False,
        }
        smoke_train_pool = Pool(
            train_features.iloc[:smoke_train],
            label=train_target[:smoke_train],
            cat_features=cat_features,
        )
        smoke_validation_pool = Pool(
            validation_features.iloc[:smoke_validation],
            label=validation_target[:smoke_validation],
            cat_features=cat_features,
        )
        write_phase(name, "smoke")
        smoke_model = CatBoostClassifier(
            **params, iterations=config["smoke_iterations"], verbose=False
        )
        started = time.perf_counter()
        smoke_model.fit(smoke_train_pool, eval_set=smoke_validation_pool)
        result["smoke_seconds"] = time.perf_counter() - started
        smoke_path = ARTIFACT_DIR / f"{name.lower()}_smoke.cbm"
        smoke_model.save_model(smoke_path)
        loaded_smoke = CatBoostClassifier()
        loaded_smoke.load_model(smoke_path)
        smoke_scores = np.asarray(loaded_smoke.predict_proba(smoke_validation_pool))
        if smoke_scores.shape != (smoke_validation, len(disease_ids)):
            raise RuntimeError(f"Smoke output shape invalid: {smoke_scores.shape}")
        if np.argsort(-smoke_scores, axis=1)[:, :5].shape != (smoke_validation, 5):
            raise RuntimeError("Smoke Top-5 ranking shape invalid")
        if smoke_model.get_param("task_type") != "GPU":
            raise RuntimeError("Smoke did not use task_type=GPU")
        result["smoke_status"] = "passed_gpu_save_load_predict_top5"

        train_pool = Pool(train_features, label=train_target, cat_features=cat_features)
        validation_pool = Pool(
            validation_features, label=validation_target, cat_features=cat_features
        )
        write_phase(name, "full")
        model = CatBoostClassifier(
            **params, iterations=config["iterations"], verbose=config["verbose"]
        )
        started = time.perf_counter()
        model.fit(train_pool, eval_set=validation_pool)
        result["training_seconds"] = time.perf_counter() - started
        model_path = ARTIFACT_DIR / f"{name.lower()}.cbm"
        model.save_model(model_path)
        loaded = CatBoostClassifier()
        loaded.load_model(model_path)
        started = time.perf_counter()
        scores = np.asarray(loaded.predict_proba(validation_pool), dtype=np.float64)
        result["prediction_seconds"] = time.perf_counter() - started
        result.update(ranking_metrics(scores, validation_target, validation_ids))
        result["model_size_bytes"] = model_path.stat().st_size
        result["status"] = "success"
        write_phase(name, "done")
    except Exception as exc:
        result["status"] = (
            "failed_smoke" if result["smoke_status"] == "not_run" else "failed_benchmark"
        )
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        write_phase(name, "failed")
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def terminate_process(process: subprocess.Popen[Any]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_isolated_worker(
    name: str, depth: int, with_weather: bool, config: dict[str, Any]
) -> dict[str, Any]:
    phase_path = ARTIFACT_DIR / f"{name.lower()}_phase.txt"
    result_path = ARTIFACT_DIR / f"{name.lower()}_result.json"
    log_path = LOG_DIR / f"{name.lower()}.log"
    gpu_path = LOG_DIR / f"{name.lower()}_gpu.csv"
    phase_path.write_text("launch", encoding="utf-8")
    command = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "--worker",
        name,
        "--depth",
        str(depth),
        "--with-weather",
        "1" if with_weather else "0",
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    samples: list[dict[str, Any]] = []
    phase_started = time.perf_counter()
    current_phase = "launch"
    high_memory_started: float | None = None
    stopped_reason = ""
    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=flags,
        )
        while process.poll() is None:
            phase = phase_path.read_text(encoding="utf-8").strip() if phase_path.exists() else "launch"
            if phase != current_phase:
                current_phase = phase
                phase_started = time.perf_counter()
                high_memory_started = None
                log(f"{name}: phase={phase}")
            gpu_name, memory, utilization = query_gpu()
            samples.append(
                {
                    "timestamp": time.time(),
                    "phase": current_phase,
                    "memory_used_mib": memory,
                    "gpu_utilization_percent": utilization,
                }
            )
            if memory >= config["resource_abort_total_memory_mib"]:
                high_memory_started = high_memory_started or time.perf_counter()
                if (
                    time.perf_counter() - high_memory_started
                    >= config["resource_abort_consecutive_seconds"]
                ):
                    stopped_reason = (
                        f"FAIL_RESOURCE: GPU memory >= {config['resource_abort_total_memory_mib']} MiB "
                        f"for {config['resource_abort_consecutive_seconds']} seconds"
                    )
            else:
                high_memory_started = None
            elapsed_phase = time.perf_counter() - phase_started
            if current_phase == "smoke" and elapsed_phase > config["smoke_timeout_seconds"]:
                stopped_reason = f"FAIL_RESOURCE: smoke exceeded {config['smoke_timeout_seconds']} seconds"
            if current_phase == "full" and elapsed_phase > config["full_timeout_seconds"]:
                stopped_reason = f"FAIL_RESOURCE: 100 iterations exceeded {config['full_timeout_seconds']} seconds"
            if stopped_reason:
                log(f"{name}: {stopped_reason}; terminating worker")
                terminate_process(process)
                break
            time.sleep(config["gpu_monitor_interval_seconds"])
    pd.DataFrame(samples).to_csv(gpu_path, index=False)
    if result_path.exists() and not stopped_reason:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = worker_result_template(name, with_weather, depth)
        result["status"] = "FAIL_RESOURCE" if stopped_reason else "failed_worker"
        result["error"] = stopped_reason or f"worker exit code {process.returncode}"
    sample_frame = pd.DataFrame(samples)
    relevant_phase = "full" if result["status"] == "success" else "smoke"
    relevant = sample_frame[sample_frame["phase"] == relevant_phase]
    if relevant.empty:
        relevant = sample_frame
    if not relevant.empty:
        result["peak_total_gpu_memory_mib"] = float(relevant["memory_used_mib"].max())
        result["baseline_gpu_memory_mib"] = float(relevant["memory_used_mib"].iloc[0])
        result["peak_vram_delta_mib"] = max(
            0.0,
            result["peak_total_gpu_memory_mib"] - result["baseline_gpu_memory_mib"],
        )
        result["mean_gpu_utilization_percent"] = float(
            relevant["gpu_utilization_percent"].mean()
        )
    else:
        result["peak_total_gpu_memory_mib"] = float("nan")
        result["baseline_gpu_memory_mib"] = float("nan")
        result["peak_vram_delta_mib"] = float("nan")
        result["mean_gpu_utilization_percent"] = float("nan")
    result["resource_warning"] = bool(
        result.get("peak_total_gpu_memory_mib", 0)
        >= config["resource_warning_total_memory_mib"]
    )
    result["gpu_name"] = query_gpu()[0]
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log(
        f"{name}: status={result['status']}, time={result.get('training_seconds')}, "
        f"peak_total={result.get('peak_total_gpu_memory_mib')} MiB"
    )
    return result


def successful(result: dict[str, Any]) -> bool:
    return result.get("status") == "success"


def select_best(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [result for result in (a, b) if successful(result)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if float(a["ndcg_at_5"]) >= float(b["ndcg_at_5"]) - 0.005:
        a_lighter = (
            float(a["training_seconds"]) <= float(b["training_seconds"])
            or float(a["peak_total_gpu_memory_mib"])
            < float(b["peak_total_gpu_memory_mib"])
        )
        if a_lighter:
            return a
    return max(
        candidates,
        key=lambda result: (
            float(result["ndcg_at_5"]),
            float(result["ndcg_at_10"]),
            -float(result["training_seconds"]),
        ),
    )


def reference_row(name: str, reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_name": name,
        "status": "reference_not_rerun",
        "with_weather": name == "OLD_DEPTH6",
        "depth": 6 if name == "OLD_DEPTH6" else "",
        "iterations": 100 if name == "OLD_DEPTH6" else 0,
        "train_query_count": 1296,
        "validation_query_count": 275,
        "disease_count": 221,
        "feature_count": "",
        "target_shape": "1296x221" if name == "OLD_DEPTH6" else "frequency prior",
        "training_seconds": reference.get("elapsed_training_seconds", float("nan")),
        "prediction_seconds": reference.get("prediction_seconds", float("nan")),
        "peak_total_gpu_memory_mib": reference.get("peak_total_gpu_memory_mib", float("nan")),
        "model_size_bytes": reference.get("model_size_bytes", 0),
        **{key: value for key, value in reference.items() if "_at_" in key},
    }


def fmt(value: Any, digits: int = 4) -> str:
    try:
        number = float(value)
        if math.isnan(number):
            return "N/A"
        return f"{number:.{digits}f}"
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "N/A"


def size_mib(value: Any) -> str:
    try:
        return f"{float(value) / 1048576:.2f} MiB" if float(value) > 0 else "N/A"
    except (TypeError, ValueError):
        return "N/A"


def estimate(best: dict[str, Any] | None, full_queries: int = 12864) -> dict[str, str]:
    if best is None or not successful(best):
        return {key: "Không thể ước lượng" for key in ("h3", "h7", "h14", "total")}
    center = float(best["training_seconds"]) * full_queries / int(best["train_query_count"])
    low, high = center * 0.75, center * 1.5
    one = f"{low / 60:.1f}–{high / 60:.1f} phút (center {center / 60:.1f})"
    return {
        "h3": one,
        "h7": one,
        "h14": one,
        "total": f"{3 * low / 60:.1f}–{3 * high / 60:.1f} phút (center {3 * center / 60:.1f})",
    }


def write_report(
    config: dict[str, Any],
    old: dict[str, Any],
    a: dict[str, Any],
    b: dict[str, Any],
    best: dict[str, Any] | None,
    no_weather: dict[str, Any] | None,
    baseline: dict[str, Any],
    estimates: dict[str, str],
    integrity_pass: bool,
) -> None:
    chosen = best["config_name"] if best else "NONE"
    speedup = (
        config["old_reference"]["elapsed_training_seconds"] / float(best["training_seconds"])
        if best and successful(best)
        else float("nan")
    )
    vram_saved = (
        config["old_reference"]["peak_total_gpu_memory_mib"]
        - float(best["peak_total_gpu_memory_mib"])
        if best and successful(best)
        else float("nan")
    )
    deltas: dict[str, float] = {}
    if best and no_weather and successful(best) and successful(no_weather):
        deltas = {
            metric: float(best[metric]) - float(no_weather[metric])
            for metric in (
                "precision_at_5",
                "recall_at_5",
                "ndcg_at_5",
                "precision_at_10",
                "recall_at_10",
                "ndcg_at_10",
            )
        }
    full_recommended = bool(
        best
        and no_weather
        and successful(best)
        and successful(no_weather)
        and not best.get("resource_warning", True)
        and speedup >= 1.5
        and float(best["ndcg_at_5"]) >= baseline["ndcg_at_5"] - 0.02
        and (deltas.get("ndcg_at_5", 0) > 0 or deltas.get("ndcg_at_10", 0) > 0)
    )
    rows = {"Old depth6": old, "LIGHT_A": a, "LIGHT_B": b, "BEST no-weather": no_weather or {}, "Baseline": baseline}
    lines = [
        "# CatBoost Multi-label Lightweight Benchmark — H7",
        "",
        "> Benchmark tạm trên đúng sample cũ; không dùng TEST, không Ranker, không SHAP và không full train.",
        "",
        "## Dữ liệu và cấu hình khóa",
        "",
        f"- CatBoost: `{a.get('catboost_version', b.get('catboost_version', 'N/A'))}`; GPU: `{a.get('gpu_name', b.get('gpu_name', 'N/A'))}`.",
        f"- TRAIN/VALIDATION: **1,296 / 275 query**; disease tính lại từ TRAIN: **{a.get('disease_count', b.get('disease_count', 'N/A'))}**.",
        f"- WITH_WEATHER feature count: {a.get('feature_count', 'N/A')}; NO_WEATHER: {(no_weather or {}).get('feature_count', 'N/A')}; target: `1296x221`.",
        "- `age_group`, `gender`, `season` dùng categorical native với `one_hot_max_size=20`, nên cardinality nhỏ được one-hot trực tiếp; `month` giữ numeric.",
        "- Mỗi config chạy trong GPU process mới để giảm ảnh hưởng CUDA warm-cache giữa LIGHT_A/LIGHT_B.",
        "",
        "## So sánh",
        "",
        "| Metric | Old depth6 | LIGHT_A | LIGHT_B | BEST no-weather | Baseline |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    metric_rows = [
        ("Status", "status", None),
        ("Train time 100 iter (s)", "training_seconds", 3),
        ("Prediction time (s)", "prediction_seconds", 4),
        ("Peak total GPU memory (MiB)", "peak_total_gpu_memory_mib", 1),
        ("Precision@5", "precision_at_5", 4),
        ("Recall@5", "recall_at_5", 4),
        ("NDCG@5", "ndcg_at_5", 4),
        ("Precision@10", "precision_at_10", 4),
        ("Recall@10", "recall_at_10", 4),
        ("NDCG@10", "ndcg_at_10", 4),
        ("Model size", "model_size_bytes", "size"),
    ]
    for label, key, digits in metric_rows:
        values = []
        for row in rows.values():
            value = row.get(key, float("nan"))
            values.append(size_mib(value) if digits == "size" else fmt(value, digits or 4))
        lines.append(f"| {label} | " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "Old depth6 và Baseline chỉ là reference đọc từ benchmark trước, không chạy lại.",
            "",
            "## Lựa chọn lightweight",
            "",
            f"- **BEST_LIGHT_CONFIG:** `{chosen}`.",
            f"- Speedup vs old: **{fmt(speedup, 2)}x**.",
            f"- VRAM saved vs old: **{fmt(vram_saved, 1)} MiB** (dương là tiết kiệm).",
        ]
    )
    if best:
        lines.append(
            f"- Lý do: chọn theo GPU/OOM, VRAM, thời gian, NDCG@5/NDCG@10 rồi Precision/Recall; LIGHT_A được ưu tiên nếu NDCG@5 nằm trong 0.005 của LIGHT_B và nhẹ hơn."
        )
    else:
        lines.append("- Cả LIGHT_A và LIGHT_B không hoàn tất an toàn; không chạy weather ablation.")
    lines.extend(["", "## Weather ablation", ""])
    if deltas:
        lines.extend(
            [
                f"- WITH_WEATHER: `{best['config_name']}`; NO_WEATHER dùng cùng depth/hyperparameter và cùng sample.",
                "",
                "| Delta = WITH_WEATHER − NO_WEATHER | Giá trị |",
                "|---|---:|",
            ]
        )
        for metric, value in deltas.items():
            lines.append(f"| {metric} | {value:+.6f} |")
        ndcg_delta = max(deltas["ndcg_at_5"], deltas["ndcg_at_10"])
        interpretation = (
            "weather có tín hiệu tăng metric trong sample này"
            if ndcg_delta > 0.002
            else "đóng góp weather yếu/gần 0 trong sample này"
            if ndcg_delta >= -0.002
            else "weather không giúp metric trong cấu hình/sample này"
        )
        lines.extend(
            [
                "",
                f"Diễn giải: **{interpretation}**. Đây là ablation quan sát, không chứng minh quan hệ nhân quả.",
            ]
        )
    else:
        lines.append(
            "Không có ablation hợp lệ vì không chọn được BEST_LIGHT_CONFIG hoặc cấu hình tốt nhất vẫn vượt resource-warning gate 7,500 MiB; pipeline dừng theo yêu cầu an toàn."
        )
    lines.extend(
        [
            "",
            "## Đề xuất và estimate",
            "",
            f"- Đề xuất full train ngay: **{'CÓ, có điều kiện' if full_recommended else 'KHÔNG'}**.",
            "- Gate gồm GPU ổn định, peak total <7,500 MiB, speedup ≥1.5x, NDCG@5 không thấp hơn baseline quá 0.02 và weather cải thiện NDCG@5 hoặc NDCG@10.",
            f"- Full H3 estimate: {estimates['h3']}.",
            f"- Full H7 estimate: {estimates['h7']}.",
            f"- Full H14 estimate: {estimates['h14']}.",
            f"- Tổng H3+H7+H14 estimate: {estimates['total']}.",
            "",
            "Estimate ngoại suy từ khoảng 10% TRAIN, có thể phi tuyến và không phải cam kết thời gian/VRAM.",
            "",
            "## Integrity",
            "",
            f"- Raw/processed/split/old sample checksum không đổi: **{'PASS' if integrity_pass else 'FAIL'}**.",
            "- TEST không được load trong script; audit cuối kiểm sample overlap TEST = 0.",
            "- Tất cả model/log/result mới nằm trong `benchmarks/multilabel_lightweight/`.",
            "- Không có model chính thức mới.",
            "",
            "**CHƯA FULL TRAIN MODEL.**",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def orchestrate() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    ORCHESTRATOR_LOG.write_text("", encoding="utf-8")
    config = read_config()
    hashes_before = verify_sources(config)
    gpu_name, memory, _ = query_gpu()
    log(f"GPU={gpu_name}; initial memory={memory:.0f} MiB")
    log("Reusing locked old sample: train=1296 validation=275")
    a = run_isolated_worker("LIGHT_A", int(config["configs"]["LIGHT_A"]["depth"]), True, config)
    b = run_isolated_worker("LIGHT_B", int(config["configs"]["LIGHT_B"]["depth"]), True, config)
    best = select_best(a, b)
    no_weather = None
    if best is not None and not best.get("resource_warning", True):
        no_weather = run_isolated_worker(
            "BEST_LIGHT_NO_WEATHER", int(best["depth"]), False, config
        )
    elif best is not None:
        log(
            "Weather ablation skipped: BEST_LIGHT_CONFIG exceeded "
            "resource-warning gate 7500 MiB"
        )
    old = reference_row("OLD_DEPTH6", config["old_reference"])
    baseline = reference_row("BASELINE", config["baseline_reference"])
    rows = [old, a, b]
    if no_weather is not None:
        rows.append(no_weather)
    else:
        rows.append(worker_result_template("BEST_LIGHT_NO_WEATHER", False, 0))
    rows.append(baseline)
    pd.DataFrame(rows).to_csv(RESULTS_PATH, index=False)
    estimates = estimate(best)
    hashes_after = verify_sources(config)
    integrity_pass = hashes_before == hashes_after
    write_report(config, old, a, b, best, no_weather, baseline, estimates, integrity_pass)
    summary = {
        "light_a_status": a["status"],
        "light_b_status": b["status"],
        "best": best["config_name"] if best else None,
        "no_weather_status": no_weather["status"] if no_weather else "not_run",
        "integrity_pass": integrity_pass,
        "full_train_performed": False,
        "report": str(REPORT_PATH),
    }
    log(json.dumps(summary, ensure_ascii=True))
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker")
    parser.add_argument("--depth", type=int)
    parser.add_argument("--with-weather", choices=["0", "1"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        if args.depth is None or args.with_weather is None:
            raise SystemExit("Worker requires --depth and --with-weather")
        return run_worker(args.worker, args.depth, args.with_weather == "1")
    return orchestrate()


if __name__ == "__main__":
    raise SystemExit(main())
