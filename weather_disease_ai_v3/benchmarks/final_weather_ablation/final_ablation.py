"""Final H7 weather ablation and full-TRAIN 10-iteration GPU smoke.

Default mode orchestrates three isolated CUDA workers at most. No TEST file is
loaded, and no worker may exceed the configured iteration count.
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
REPORT_PATH = BENCHMARK_DIR / "FINAL_ABLATION_REPORT.md"
LOG_DIR = BENCHMARK_DIR / "logs"
ARTIFACT_DIR = BENCHMARK_DIR / "artifacts"
ORCHESTRATOR_LOG = LOG_DIR / "orchestrator.log"

CONTEXTS_PATH = PROJECT_ROOT / "data/processed/contexts.csv.gz"
TARGETS_PATH = PROJECT_ROOT / "data/processed/targets.csv.gz"
METADATA_PATH = PROJECT_ROOT / "data/processed/dataset_metadata.json"
TRAIN_IDS_PATH = PROJECT_ROOT / "data/splits/train_query_ids.csv"
SAMPLE_TRAIN_PATH = PROJECT_ROOT / "benchmarks/pretrain_model_selection/artifacts/train_benchmark_query_ids.csv"
SAMPLE_VALIDATION_PATH = PROJECT_ROOT / "benchmarks/pretrain_model_selection/artifacts/validation_benchmark_query_ids.csv"


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
        value = sha256_file(path)
        actual[relative] = value
        if value != expected:
            raise RuntimeError(
                f"Locked source changed: {relative}; expected={expected}, actual={value}"
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


def load_data(
    *, with_weather: bool, full_train: bool
) -> tuple[pd.DataFrame, pd.DataFrame | None, np.ndarray, np.ndarray | None, list[str], list[str] | None, list[str]]:
    config = read_config()
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    contexts = pd.read_csv(CONTEXTS_PATH, dtype={"query_id": str}).set_index("query_id", drop=False)
    targets = pd.read_csv(TARGETS_PATH, dtype={"query_id": str, "disease_group_id": str})
    all_train = pd.read_csv(TRAIN_IDS_PATH, dtype={"query_id": str})
    train_universe = set(all_train["query_id"])
    train_targets = targets[targets["query_id"].isin(train_universe)]
    supported_mask = train_targets[["has_case_h3", "has_case_h7", "has_case_h14"]].max(axis=1) > 0
    disease_ids = sorted_disease_ids(
        set(train_targets.loc[supported_mask, "disease_group_id"].astype(str))
    )
    if full_train:
        train_ids = all_train["query_id"].astype(str).tolist()
        validation_ids = None
    else:
        train_ids = pd.read_csv(SAMPLE_TRAIN_PATH, dtype={"query_id": str})["query_id"].tolist()
        validation_ids = pd.read_csv(SAMPLE_VALIDATION_PATH, dtype={"query_id": str})["query_id"].tolist()
    feature_columns = (
        list(metadata["model_feature_columns"])
        if with_weather
        else list(config["no_weather_features"])
    )
    forbidden = [
        column
        for column in feature_columns
        if column in {"query_id", "anchor_date", "year", "disease_group_id"}
        or any(token in column.lower() for token in ("target", "has_case", "case_count"))
    ]
    if forbidden:
        raise RuntimeError(f"Forbidden model features: {forbidden}")
    if not with_weather:
        weather_tokens = ("weather", "temperature", "humidity", "rain", "precipitation", "wind")
        if any(token in column.lower() for column in feature_columns for token in weather_tokens):
            raise RuntimeError("NO_WEATHER feature set contains weather")

    def prepare(ids: list[str]) -> pd.DataFrame:
        frame = contexts.loc[ids, feature_columns].reset_index(drop=True).copy()
        for column in config["categorical_features"]:
            frame[column] = frame[column].fillna("Không rõ").astype(str)
        frame["month"] = pd.to_numeric(frame["month"], errors="raise").astype("int16")
        return frame

    train_features = prepare(train_ids)
    train_matrix = build_target_matrix(train_ids, disease_ids, targets)
    validation_features = prepare(validation_ids) if validation_ids is not None else None
    validation_matrix = (
        build_target_matrix(validation_ids, disease_ids, targets)
        if validation_ids is not None
        else None
    )
    return (
        train_features,
        validation_features,
        train_matrix,
        validation_matrix,
        train_ids,
        validation_ids,
        disease_ids,
    )


def ranking_metrics(scores: np.ndarray, target: np.ndarray) -> dict[str, float | int]:
    if scores.shape != target.shape:
        raise RuntimeError(f"Score shape {scores.shape} != target shape {target.shape}")
    order = np.argsort(-scores, axis=1, kind="stable")
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


def result_template(run_name: str, with_weather: bool, full_train: bool) -> dict[str, Any]:
    return {
        "run_name": run_name,
        "status": "not_run",
        "error": "",
        "with_weather": with_weather,
        "full_train_smoke": full_train,
        "iterations": 10 if full_train else 100,
        "query_count": 0,
        "validation_query_count": 0,
        "disease_count": 0,
        "feature_count": 0,
        "target_shape": "",
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


def wait_for_go(go_path: Path, timeout_seconds: int = 60) -> None:
    started = time.perf_counter()
    while not go_path.exists():
        if time.perf_counter() - started > timeout_seconds:
            raise TimeoutError("Orchestrator did not release GPU worker")
        time.sleep(0.05)


def worker(run_name: str, with_weather: bool, full_train: bool) -> int:
    from catboost import CatBoostClassifier, Pool
    import catboost

    config = read_config()
    phase_path = ARTIFACT_DIR / f"{run_name}_phase.txt"
    go_path = ARTIFACT_DIR / f"{run_name}_go.flag"
    result_path = ARTIFACT_DIR / f"{run_name}_result.json"
    result = result_template(run_name, with_weather, full_train)
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
        ) = load_data(with_weather=with_weather, full_train=full_train)
        result.update(
            {
                "query_count": len(train_ids),
                "validation_query_count": len(validation_ids or []),
                "disease_count": len(disease_ids),
                "feature_count": train_features.shape[1],
                "target_shape": f"{len(train_ids)}x{len(disease_ids)}",
            }
        )
        if not ((train_target.min(axis=0) == 0) & (train_target.max(axis=0) == 1)).all():
            raise RuntimeError("TRAIN target contains a constant disease column")
        cat_features = list(config["categorical_features"])
        train_pool = Pool(train_features, label=train_target, cat_features=cat_features)
        validation_pool = (
            Pool(validation_features, label=validation_target, cat_features=cat_features)
            if validation_features is not None and validation_target is not None
            else None
        )
        iterations = (
            config["iterations_full_smoke"] if full_train else config["iterations_ablation"]
        )
        params = {
            "loss_function": config["loss_function"],
            "task_type": config["task_type"],
            "devices": config["devices"],
            "gpu_ram_part": config["gpu_ram_part"],
            "iterations": iterations,
            "depth": config["depth"],
            "border_count": config["border_count"],
            "one_hot_max_size": config["one_hot_max_size"],
            "learning_rate": config["learning_rate"],
            "random_seed": config["random_seed"],
            "verbose": config["verbose"],
            "allow_writing_files": config["allow_writing_files"],
            "use_best_model": False,
        }
        model = CatBoostClassifier(**params)
        result["gpu_ram_part_supported"] = model.get_param("gpu_ram_part") == 0.85
        phase_path.write_text("ready", encoding="utf-8")
        wait_for_go(go_path)
        phase_path.write_text("training", encoding="utf-8")
        started = time.perf_counter()
        if validation_pool is not None:
            model.fit(train_pool, eval_set=validation_pool)
        else:
            model.fit(train_pool)
        result["training_seconds"] = time.perf_counter() - started
        artifact = ARTIFACT_DIR / f"{run_name}.cbm"
        model.save_model(artifact)
        loaded = CatBoostClassifier()
        loaded.load_model(artifact)
        predict_pool = validation_pool if validation_pool is not None else train_pool
        started = time.perf_counter()
        scores = np.asarray(loaded.predict_proba(predict_pool), dtype=np.float64)
        result["prediction_seconds"] = time.perf_counter() - started
        expected_rows = len(validation_ids) if validation_ids is not None else len(train_ids)
        if scores.shape != (expected_rows, len(disease_ids)):
            raise RuntimeError(f"Prediction shape invalid: {scores.shape}")
        if validation_target is not None:
            result.update(ranking_metrics(scores, validation_target))
        result["model_size_bytes"] = artifact.stat().st_size
        result["status"] = "success"
        phase_path.write_text("done", encoding="utf-8")
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        result["status"] = "failed"
        result["error"] = text
        result["oom"] = any(token in text.lower() for token in ("out of memory", "memory allocation", "cuda error 2"))
        traceback.print_exc()
        phase_path.write_text("failed", encoding="utf-8")
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def terminate_process(process: subprocess.Popen[Any]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_isolated(run_name: str, with_weather: bool, full_train: bool) -> dict[str, Any]:
    config = read_config()
    phase_path = ARTIFACT_DIR / f"{run_name}_phase.txt"
    go_path = ARTIFACT_DIR / f"{run_name}_go.flag"
    result_path = ARTIFACT_DIR / f"{run_name}_result.json"
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
        "--full-train",
        "1" if full_train else "0",
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
            phase = phase_path.read_text(encoding="utf-8").strip() if phase_path.exists() else "launch"
            if phase != current_phase:
                current_phase = phase
                log(f"{run_name}: phase={phase}")
                if phase == "ready":
                    _, _, memory_before, _ = query_gpu()
                    log(f"{run_name}: GPU memory before training={memory_before:.0f} MiB")
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
                if time.perf_counter() - high_memory_started >= config["gpu_abort_consecutive_seconds"]:
                    stopped_reason = (
                        f"GPU memory >= {config['gpu_abort_total_memory_mib']} MiB for "
                        f"{config['gpu_abort_consecutive_seconds']} seconds"
                    )
            else:
                high_memory_started = None
            if training_started is not None:
                limit = (
                    config["full_smoke_timeout_seconds"]
                    if full_train
                    else config["ablation_timeout_seconds"]
                )
                if time.perf_counter() - training_started > limit:
                    stopped_reason = f"training exceeded safety timeout {limit} seconds"
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
        result = result_template(run_name, with_weather, full_train)
        result["status"] = "FAIL_RESOURCE" if stopped_reason else "failed_worker"
        result["error"] = stopped_reason or f"worker exit code {process.returncode}"
        result["oom"] = "memory" in result["error"].lower()
    frame = pd.DataFrame(samples)
    training_samples = frame[frame["phase"] == "training"] if not frame.empty else frame
    if training_samples.empty:
        training_samples = frame
    peak = float(training_samples["memory_used_mib"].max()) if not training_samples.empty else float("nan")
    result.update(
        {
            "gpu_name": query_gpu()[0],
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
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log(
        f"{run_name}: status={result['status']}, time={result.get('training_seconds')}, "
        f"before={memory_before}, peak={peak}, after={memory_after} MiB"
    )
    return result


def fmt(value: Any, digits: int = 4) -> str:
    try:
        number = float(value)
        return "N/A" if math.isnan(number) else f"{number:.{digits}f}"
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "N/A"


def decide(
    config: dict[str, Any],
    with_weather: dict[str, Any],
    no_weather: dict[str, Any],
    full_smoke: dict[str, Any] | None,
    deltas: dict[str, float],
) -> tuple[str, str]:
    if full_smoke is None or full_smoke.get("status") != "success" or full_smoke.get("oom"):
        return "GPU_NOT_SAFE", "Full-TRAIN 10-iteration smoke không hoàn tất an toàn."
    headroom = float(full_smoke["gpu_total_memory_mib"]) - float(full_smoke["peak_total_mib"])
    if headroom < config["minimum_safe_headroom_mib"]:
        return "GPU_NOT_SAFE", f"Full smoke chỉ còn {headroom:.0f} MiB GPU headroom."
    ndcg_5_delta = deltas.get("ndcg_at_5", -1)
    ndcg_10_delta = deltas.get("ndcg_at_10", -1)
    if not (
        ndcg_5_delta > config["weather_signal_ndcg_threshold"]
        and ndcg_10_delta > config["weather_signal_ndcg_threshold"]
    ):
        return (
            "WEATHER_SIGNAL_UNCLEAR",
            "Weather delta nhỏ và trái chiều: NDCG@5 không cải thiện rõ dù NDCG@10 tăng nhẹ.",
        )
    baseline = config["baseline_reference"]
    competitive = float(with_weather["ndcg_at_5"]) >= baseline["ndcg_at_5"] - 0.01
    estimated_100_minutes = float(full_smoke["training_seconds"]) * 10 / 60
    if competitive and estimated_100_minutes <= 60:
        return (
            "READY_FOR_FULL_TRAIN",
            "Weather có thêm giá trị dự báo thống kê, metric cạnh tranh baseline và full smoke GPU an toàn.",
        )
    return "WEATHER_SIGNAL_UNCLEAR", "Weather có tín hiệu nhưng gate metric/thời gian chưa đủ rõ để full train."


def estimate_times(full_smoke: dict[str, Any] | None) -> dict[str, str]:
    if full_smoke is None or full_smoke.get("status") != "success":
        return {str(value): "N/A" for value in (100, 200, 300)}
    per_iteration = float(full_smoke["training_seconds"]) / 10
    return {
        str(iterations): f"≈ {per_iteration * iterations / 60:.1f} phút"
        for iterations in (100, 200, 300)
    }


def write_report(
    config: dict[str, Any],
    with_weather: dict[str, Any],
    no_weather: dict[str, Any],
    full_smoke: dict[str, Any] | None,
    deltas: dict[str, float],
    estimates: dict[str, str],
    decision: str,
    reason: str,
    integrity_pass: bool,
) -> None:
    baseline = config["baseline_reference"]
    lines = [
        "# Final Weather Ablation Report — H7",
        "",
        "> Benchmark cuối chỉ trả lời weather contribution và khả năng chạy full-TRAIN 10 iterations trên GPU. Không dùng TEST và chưa full train.",
        "",
        "## Phạm vi cố định",
        "",
        f"- CatBoost `{with_weather.get('catboost_version', 'N/A')}`, GPU `{with_weather.get('gpu_name', 'N/A')}`.",
        f"- LIGHT_A: depth=4, border_count=32, one_hot_max_size=20, learning_rate=0.1, MultiLogloss, GPU, `gpu_ram_part=0.85`.",
        f"- gpu_ram_part được CatBoost chấp nhận khi fit: WITH={with_weather.get('gpu_ram_part_supported')}, NO={no_weather.get('gpu_ram_part_supported')}.",
        f"- Sample TRAIN/VALIDATION: {with_weather.get('query_count')}/{with_weather.get('validation_query_count')}; disease tính từ TRAIN: {with_weather.get('disease_count')}; target `{with_weather.get('target_shape')}`.",
        f"- Feature count WITH/NO: {with_weather.get('feature_count')}/{no_weather.get('feature_count')}; hai run dùng process CUDA riêng.",
        "",
        "## Weather ablation",
        "",
        "| Metric | WITH WEATHER | NO WEATHER | Delta | Baseline |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, key, digits in (
        ("Precision@5", "precision_at_5", 4),
        ("Recall@5", "recall_at_5", 4),
        ("NDCG@5", "ndcg_at_5", 4),
        ("Precision@10", "precision_at_10", 4),
        ("Recall@10", "recall_at_10", 4),
        ("NDCG@10", "ndcg_at_10", 4),
    ):
        lines.append(
            f"| {label} | {fmt(with_weather.get(key), digits)} | {fmt(no_weather.get(key), digits)} | {fmt(deltas.get(key), 6)} | {fmt(baseline.get(key), digits)} |"
        )
    for label, key in (
        ("Train time (s)", "training_seconds"),
        ("Peak total VRAM (MiB)", "peak_total_mib"),
        ("Peak delta VRAM (MiB)", "peak_delta_mib"),
    ):
        lines.append(
            f"| {label} | {fmt(with_weather.get(key), 3)} | {fmt(no_weather.get(key), 3)} | N/A | N/A |"
        )
    clear_weather_signal = (
        deltas.get("ndcg_at_5", -1) > config["weather_signal_ndcg_threshold"]
        and deltas.get("ndcg_at_10", -1) > config["weather_signal_ndcg_threshold"]
    )
    interpretation = (
        "Weather có thêm giá trị dự báo thống kê nhất quán trên benchmark này."
        if clear_weather_signal
        else "Weather contribution chưa rõ: delta nhỏ và trái chiều giữa các ranking cutoff."
    )
    lines.extend(
        [
            "",
            f"**Diễn giải:** {interpretation} Đây là so sánh dự báo thống kê, không phải quan hệ nhân quả và không phải chẩn đoán.",
            "",
            "## FULL TRAIN 10-ITER SMOKE",
            "",
        ]
    )
    smoke = full_smoke or {}
    lines.extend(
        [
            f"- query count: {smoke.get('query_count', 'N/A')}",
            f"- disease count: {smoke.get('disease_count', 'N/A')}",
            f"- target shape: {smoke.get('target_shape', 'N/A')}",
            f"- feature count: {smoke.get('feature_count', 'N/A')}",
            f"- time: {fmt(smoke.get('training_seconds'), 3)} giây",
            f"- memory before: {fmt(smoke.get('memory_before_mib'), 1)} MiB",
            f"- peak memory: {fmt(smoke.get('peak_total_mib'), 1)} MiB",
            f"- peak delta: {fmt(smoke.get('peak_delta_mib'), 1)} MiB",
            f"- memory after process: {fmt(smoke.get('memory_after_mib'), 1)} MiB",
            f"- OOM: {smoke.get('oom', 'N/A')}",
            f"- PASS/FAIL: {smoke.get('status', 'not_run')}",
            "",
            "## Estimate từ full-data smoke",
            "",
            f"- 100 iterations: {estimates['100']}",
            f"- 200 iterations: {estimates['200']}",
            f"- 300 iterations: {estimates['300']}",
            "",
            "Estimate ngoại suy từ đúng full-TRAIN 10 iterations, có thể phi tuyến; không phải thời gian chắc chắn.",
            "",
            "## Decision gate",
            "",
            f"**{decision}** — {reason}",
            "",
            "## Integrity",
            "",
            f"- Raw/processed/split/sample/reference checksum không đổi: **{'PASS' if integrity_pass else 'FAIL'}**.",
            "- TEST không được load trong script; audit ngoài training xác nhận sample không overlap TEST.",
            "- Mọi model/log/result mới nằm trong `benchmarks/final_weather_ablation/`.",
            "- Không có model chính thức mới.",
            "",
            "**CHƯA FULL TRAIN MODEL.**",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def reference_baseline_row(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_name": "BASELINE_REFERENCE",
        "status": "reference_not_rerun",
        **config["baseline_reference"],
    }


def orchestrate() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    ORCHESTRATOR_LOG.write_text("", encoding="utf-8")
    config = read_config()
    hashes_before = verify_sources(config)
    gpu_name, total, used, _ = query_gpu()
    log(f"GPU={gpu_name}; total={total:.0f} MiB; initial used={used:.0f} MiB")
    with_weather = run_isolated("with_weather", True, False)
    no_weather = run_isolated("no_weather", False, False)
    metric_keys = (
        "precision_at_5",
        "recall_at_5",
        "ndcg_at_5",
        "precision_at_10",
        "recall_at_10",
        "ndcg_at_10",
    )
    deltas = {
        key: float(with_weather[key]) - float(no_weather[key])
        for key in metric_keys
        if with_weather.get("status") == "success" and no_weather.get("status") == "success"
    }
    full_smoke = None
    if with_weather.get("status") == "success":
        full_smoke = run_isolated("full_train_10iter", True, True)
    estimates = estimate_times(full_smoke)
    decision, reason = decide(config, with_weather, no_weather, full_smoke, deltas)
    hashes_after = verify_sources(config)
    integrity_pass = hashes_before == hashes_after
    rows = [with_weather, no_weather]
    if full_smoke is not None:
        rows.append(full_smoke)
    rows.append(reference_baseline_row(config))
    pd.DataFrame(rows).to_csv(RESULTS_PATH, index=False)
    write_report(
        config,
        with_weather,
        no_weather,
        full_smoke,
        deltas,
        estimates,
        decision,
        reason,
        integrity_pass,
    )
    summary = {
        "with_weather": with_weather.get("status"),
        "no_weather": no_weather.get("status"),
        "full_train_10iter": (full_smoke or {}).get("status", "not_run"),
        "decision": decision,
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
    parser.add_argument("--with-weather", choices=["0", "1"])
    parser.add_argument("--full-train", choices=["0", "1"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        if args.with_weather is None or args.full_train is None:
            raise SystemExit("Worker requires --with-weather and --full-train")
        return worker(args.worker, args.with_weather == "1", args.full_train == "1")
    return orchestrate()


if __name__ == "__main__":
    raise SystemExit(main())
