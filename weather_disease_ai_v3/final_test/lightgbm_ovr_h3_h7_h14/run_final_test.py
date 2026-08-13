"""One-time LightGBM OVR final evaluation with a hard pre/post TEST boundary."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FINAL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FINAL_DIR.parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmarks/lightgbm_ovr_h3_h7_h14"
RUNTIME_DEPS = BENCHMARK_DIR / "artifacts/runtime_deps"
if str(RUNTIME_DEPS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DEPS))

import lightgbm as lgb
from lightgbm import LGBMClassifier


CONFIG_PATH = FINAL_DIR / "config_locked.json"
REPORT_PATH = FINAL_DIR / "FINAL_TEST_REPORT.md"
SUMMARY_PATH = FINAL_DIR / "final_test_summary.csv"
BOOTSTRAP_SUMMARY_PATH = FINAL_DIR / "bootstrap_test_summary.csv"
INTEGRITY_PATH = FINAL_DIR / "integrity.json"
SCORES_DIR = FINAL_DIR / "scores"
PREDICTIONS_DIR = FINAL_DIR / "predictions"
LOGS_DIR = FINAL_DIR / "logs"
METADATA_DIR = FINAL_DIR / "model_metadata"
EVENT_LOG = LOGS_DIR / "event_log.jsonl"
TEST_OPENED_MARKER = LOGS_DIR / "TEST_OPENED_ONCE.lock"

CONTEXTS_PATH = PROJECT_ROOT / "data/processed/contexts.csv.gz"
TARGETS_PATH = PROJECT_ROOT / "data/processed/targets.csv.gz"
DATASET_METADATA_PATH = PROJECT_ROOT / "data/processed/dataset_metadata.json"
TRAIN_IDS_PATH = PROJECT_ROOT / "data/splits/train_query_ids.csv"
VALIDATION_IDS_PATH = PROJECT_ROOT / "data/splits/validation_query_ids.csv"
TEST_IDS_PATH = PROJECT_ROOT / "data/splits/test_query_ids.csv"

METRICS = (
    "precision_at_5",
    "recall_at_5",
    "ndcg_at_5",
    "precision_at_10",
    "recall_at_10",
    "ndcg_at_10",
)
HIERARCHY = [
    ("age_group", "gender", "month"),
    ("age_group", "month"),
    ("month",),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ordered_sha256(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def verify_locked(config: dict[str, Any]) -> dict[str, str]:
    actual: dict[str, str] = {}
    for relative, expected in config["locked_files_sha256"].items():
        path = PROJECT_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing locked file: {relative}")
        checksum = sha256_file(path)
        actual[relative] = checksum
        if checksum != expected:
            raise RuntimeError(
                f"Locked file changed: {relative}; expected={expected}, actual={checksum}"
            )
    return actual


def ensure_output_dirs() -> None:
    for directory in (SCORES_DIR, PREDICTIONS_DIR, LOGS_DIR, METADATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def event(name: str, **details: Any) -> None:
    record = {
        "event": name,
        "time_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        **details,
    }
    with EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False), flush=True)


def load_ids(path: Path) -> list[str]:
    frame = pd.read_csv(path, dtype={"query_id": str})
    if frame.columns.tolist() != ["query_id"]:
        raise RuntimeError(f"Unexpected split schema: {path}")
    values = frame["query_id"].tolist()
    if len(values) != len(set(values)):
        raise RuntimeError(f"Duplicate query IDs: {path}")
    return values


def load_selected_gzip_csv(
    path: Path,
    selected_ids: set[str],
    *,
    dtype: dict[str, Any],
    require_one_context_per_id: bool,
) -> pd.DataFrame:
    """Parse only rows whose first CSV field is an allowed query ID."""
    retained: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        header_line = handle.readline()
        header = next(csv.reader([header_line]))
        if not header or header[0] != "query_id":
            raise RuntimeError(f"query_id must be first column in {path}")
        retained.append(header_line)
        for line in handle:
            query_id = line.split(",", 1)[0].strip('"')
            if query_id in selected_ids:
                retained.append(line)
    frame = pd.read_csv(io.StringIO("".join(retained)), dtype=dtype)
    if not set(frame["query_id"].astype(str)).issubset(selected_ids):
        raise RuntimeError(f"Row filter leaked an unselected query in {path}")
    if require_one_context_per_id:
        counts = frame["query_id"].value_counts()
        if len(frame) != len(selected_ids) or not counts.eq(1).all():
            missing = sorted(selected_ids - set(frame["query_id"].astype(str)))[:5]
            raise RuntimeError(f"Context selection mismatch; missing sample={missing}")
    return frame


def build_target_matrix(
    query_ids: list[str], disease_ids: list[str], targets: pd.DataFrame, horizon: int
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


def load_disease_order(config: dict[str, Any]) -> list[str]:
    path = BENCHMARK_DIR / "artifacts/h3_with_weather/validation_scores.npz"
    with np.load(path, allow_pickle=False) as artifact:
        disease_ids = [str(value) for value in artifact["disease_ids"]]
    if len(disease_ids) != int(config["disease_count"]):
        raise RuntimeError("Disease count differs from locked contract")
    if len(disease_ids) != len(set(disease_ids)):
        raise RuntimeError("Duplicate disease IDs")
    if ordered_sha256(disease_ids) != config["disease_order_sha256"]:
        raise RuntimeError("Disease order differs from locked contract")
    for horizon in config["horizons"]:
        for variant in ("with_weather", "no_weather"):
            score_path = (
                BENCHMARK_DIR
                / "artifacts"
                / f"h{horizon}_{variant}"
                / "validation_scores.npz"
            )
            with np.load(score_path, allow_pickle=False) as artifact:
                other = [str(value) for value in artifact["disease_ids"]]
            if other != disease_ids:
                raise RuntimeError(f"Disease order mismatch: H{horizon} {variant}")
    return disease_ids


def load_best_iterations(
    config: dict[str, Any], disease_ids: list[str]
) -> tuple[dict[str, dict[str, int]], pd.DataFrame]:
    result: dict[str, dict[str, int]] = {}
    records: list[dict[str, Any]] = []
    for horizon in config["horizons"]:
        for variant in ("with_weather", "no_weather"):
            run_name = f"h{horizon}_{variant}"
            path = BENCHMARK_DIR / "artifacts" / run_name / "label_training_details.csv"
            frame = pd.read_csv(path, dtype={"disease_group_id": str})
            if frame["disease_group_id"].tolist() != disease_ids:
                raise RuntimeError(f"Best-iteration disease order mismatch: {run_name}")
            valid = (
                (frame["status"] == "trained")
                & frame["best_iteration"].notna()
                & frame["best_iteration"].between(1, 200)
            )
            if len(frame) != len(disease_ids) or not valid.all():
                raise RuntimeError(f"Best iterations unavailable/invalid: {run_name}")
            mapping = {
                disease_id: int(iteration)
                for disease_id, iteration in zip(
                    frame["disease_group_id"], frame["best_iteration"]
                )
            }
            result[run_name] = mapping
            for disease_id in disease_ids:
                records.append(
                    {
                        "run_name": run_name,
                        "horizon": horizon,
                        "variant": variant,
                        "disease_group_id": disease_id,
                        "best_iteration_locked": mapping[disease_id],
                        "source": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                    }
                )
    return result, pd.DataFrame(records)


def encode_fit_features(
    contexts: pd.DataFrame,
    query_ids: list[str],
    feature_names: list[str],
    categorical_features: list[str],
) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    indexed = contexts.set_index("query_id", drop=False)
    frame = indexed.loc[query_ids, feature_names].reset_index(drop=True).copy()
    mappings: dict[str, dict[str, int]] = {}
    for column in categorical_features:
        values = frame[column].fillna("Không rõ").astype(str)
        categories = sorted(values.unique().tolist())
        mapping = {value: index for index, value in enumerate(categories)}
        mappings[column] = mapping
        frame[column] = values.map(mapping).astype("int32")
    frame["month"] = pd.to_numeric(frame["month"], errors="raise").astype("int16")
    for column in feature_names:
        if column not in categorical_features and column != "month":
            frame[column] = pd.to_numeric(frame[column], errors="raise")
    if frame.isna().any().any():
        raise RuntimeError("Missing final-fit feature value")
    return frame, mappings


def transform_features(
    contexts: pd.DataFrame,
    query_ids: list[str],
    feature_names: list[str],
    categorical_features: list[str],
    mappings: dict[str, dict[str, int]],
) -> pd.DataFrame:
    indexed = contexts.set_index("query_id", drop=False)
    frame = indexed.loc[query_ids, feature_names].reset_index(drop=True).copy()
    for column in categorical_features:
        values = frame[column].fillna("Không rõ").astype(str)
        frame[column] = values.map(mappings[column]).fillna(-1).astype("int32")
    frame["month"] = pd.to_numeric(frame["month"], errors="raise").astype("int16")
    for column in feature_names:
        if column not in categorical_features and column != "month":
            frame[column] = pd.to_numeric(frame[column], errors="raise")
    if frame.isna().any().any():
        raise RuntimeError("Missing transformed feature value")
    return frame


def metric_contributions_from_order(
    order: np.ndarray, target: np.ndarray
) -> dict[str, np.ndarray]:
    if order.shape != target.shape:
        raise RuntimeError(f"Ranking shape {order.shape} != target shape {target.shape}")
    relevant_count = target.sum(axis=1).astype(np.int64)
    valid = relevant_count > 0
    result: dict[str, np.ndarray] = {}
    for k in (5, 10):
        top = order[:, :k]
        hit_matrix = np.take_along_axis(target, top, axis=1).astype(np.float64)
        hits = hit_matrix.sum(axis=1)
        discounts = 1.0 / np.log2(np.arange(k, dtype=np.float64) + 2.0)
        dcg = (hit_matrix * discounts).sum(axis=1)
        ideal_lookup = np.cumsum(discounts)
        ideal = np.ones(len(target), dtype=np.float64)
        ideal[valid] = ideal_lookup[np.minimum(relevant_count[valid], k) - 1]
        precision = np.full(len(target), np.nan, dtype=np.float64)
        recall = np.full(len(target), np.nan, dtype=np.float64)
        ndcg = np.full(len(target), np.nan, dtype=np.float64)
        precision[valid] = hits[valid] / k
        recall[valid] = hits[valid] / relevant_count[valid]
        ndcg[valid] = dcg[valid] / ideal[valid]
        result[f"precision_at_{k}"] = precision
        result[f"recall_at_{k}"] = recall
        result[f"ndcg_at_{k}"] = ndcg
    return result


def metric_contributions(scores: np.ndarray, target: np.ndarray) -> dict[str, np.ndarray]:
    if scores.shape != target.shape:
        raise RuntimeError(f"Score shape {scores.shape} != target shape {target.shape}")
    return metric_contributions_from_order(
        np.argsort(-scores, axis=1, kind="stable"), target
    )


def aggregate_metrics(contributions: dict[str, np.ndarray]) -> dict[str, float | int]:
    first = contributions[METRICS[0]]
    return {
        **{metric: float(np.nanmean(contributions[metric])) for metric in METRICS},
        "evaluated_queries": int((~np.isnan(first)).sum()),
        "zero_positive_queries": int(np.isnan(first).sum()),
    }


def fit_baseline(
    contexts: pd.DataFrame,
    targets: pd.DataFrame,
    disease_ids: list[str],
    horizon: int,
) -> dict[str, Any]:
    weight = f"case_count_h{horizon}"
    positive = targets.loc[
        (targets[weight] > 0) & targets["disease_group_id"].isin(disease_ids),
        ["query_id", "disease_group_id", weight],
    ]
    joined = positive.merge(
        contexts[["query_id", "age_group", "gender", "month"]],
        on="query_id",
        how="inner",
        validate="many_to_one",
    )
    tables: list[dict[tuple[Any, ...], dict[str, float]]] = []
    for keys in HIERARCHY:
        grouped = joined.groupby([*keys, "disease_group_id"], dropna=False)[weight].sum()
        table: dict[tuple[Any, ...], dict[str, float]] = {}
        levels: int | list[int] = 0 if len(keys) == 1 else list(range(len(keys)))
        for key_values, subset in grouped.groupby(level=levels):
            key = key_values if isinstance(key_values, tuple) else (key_values,)
            scores = subset.droplevel(list(range(len(keys)))).to_dict()
            table[key] = {str(label): float(value) for label, value in scores.items()}
        tables.append(table)
    global_scores = {
        str(label): float(value)
        for label, value in joined.groupby("disease_group_id")[weight].sum().items()
    }
    return {"tables": tables, "global": global_scores}


def baseline_order(
    baseline: dict[str, Any], contexts: pd.DataFrame, disease_ids: list[str]
) -> np.ndarray:
    disease_index = {value: index for index, value in enumerate(disease_ids)}
    rows: list[list[int]] = []
    for context in contexts.to_dict(orient="records"):
        selected: dict[str, float] | None = None
        for keys, table in zip(HIERARCHY, baseline["tables"]):
            key = tuple(context[column] for column in keys)
            if key in table:
                selected = table[key]
                break
        scores = baseline["global"] if selected is None else selected
        ranked = sorted(
            disease_ids,
            key=lambda label: (-float(scores.get(label, 0.0)), label),
        )
        rows.append([disease_index[label] for label in ranked])
    return np.asarray(rows, dtype=np.int32)


def prepare_fit_bundle(config: dict[str, Any]) -> dict[str, Any]:
    train_ids = load_ids(TRAIN_IDS_PATH)
    validation_ids = load_ids(VALIDATION_IDS_PATH)
    if set(train_ids) & set(validation_ids):
        raise RuntimeError("TRAIN/VALIDATION overlap")
    fit_ids = train_ids + validation_ids
    selected = set(fit_ids)
    contexts = load_selected_gzip_csv(
        CONTEXTS_PATH,
        selected,
        dtype={"query_id": str},
        require_one_context_per_id=True,
    )
    targets = load_selected_gzip_csv(
        TARGETS_PATH,
        selected,
        dtype={"query_id": str, "disease_group_id": str},
        require_one_context_per_id=False,
    )
    disease_ids = load_disease_order(config)
    train_rows = targets[targets["query_id"].isin(set(train_ids))]
    support = set(
        train_rows.loc[
            train_rows[["has_case_h3", "has_case_h7", "has_case_h14"]].max(axis=1) > 0,
            "disease_group_id",
        ].astype(str)
    )
    if support != set(disease_ids):
        raise RuntimeError("TRAIN-supported disease universe differs from locked benchmark")
    metadata = json.loads(DATASET_METADATA_PATH.read_text(encoding="utf-8"))
    feature_names = list(metadata["model_feature_columns"])
    if ordered_sha256(feature_names) != config["feature_order_sha256"]:
        raise RuntimeError("Feature order differs from locked benchmark")
    if len(feature_names) != int(config["feature_count_with_weather"]):
        raise RuntimeError("WITH WEATHER feature count mismatch")
    no_weather = list(config["no_weather_features"])
    if any(column not in feature_names for column in no_weather):
        raise RuntimeError("NO WEATHER feature is outside locked schema")
    fit_features, mappings = encode_fit_features(
        contexts,
        fit_ids,
        feature_names,
        list(config["categorical_features"]),
    )
    target_matrices = {
        horizon: build_target_matrix(fit_ids, disease_ids, targets, horizon)
        for horizon in config["horizons"]
    }
    for horizon, matrix in target_matrices.items():
        if not ((matrix.min(axis=0) == 0) & (matrix.max(axis=0) == 1)).all():
            raise RuntimeError(f"H{horizon} final-fit target contains a constant label")
    best_iterations, iteration_frame = load_best_iterations(config, disease_ids)
    return {
        "train_ids": train_ids,
        "validation_ids": validation_ids,
        "fit_ids": fit_ids,
        "contexts": contexts,
        "targets": targets,
        "disease_ids": disease_ids,
        "feature_names": feature_names,
        "no_weather_features": no_weather,
        "fit_features": fit_features,
        "mappings": mappings,
        "target_matrices": target_matrices,
        "best_iterations": best_iterations,
        "iteration_frame": iteration_frame,
    }


def fit_experiment(
    run_name: str,
    features: pd.DataFrame,
    target: np.ndarray,
    disease_ids: list[str],
    best_iterations: dict[str, int],
    config: dict[str, Any],
    state: dict[str, Any],
) -> tuple[list[LGBMClassifier], dict[str, Any], list[dict[str, Any]]]:
    if not state["training_allowed"] or TEST_OPENED_MARKER.exists():
        raise RuntimeError("Training attempted after TEST boundary")
    models: list[LGBMClassifier] = []
    details: list[dict[str, Any]] = []
    started = time.perf_counter()
    categorical = list(config["categorical_features"])
    for index, disease_id in enumerate(disease_ids):
        y = target[:, index]
        if np.unique(y).tolist() != [0, 1]:
            raise RuntimeError(f"{run_name}/{disease_id}: constant final-fit target")
        params = dict(config["classifier"])
        params["n_estimators"] = int(best_iterations[disease_id])
        model = LGBMClassifier(**params)
        label_started = time.perf_counter()
        model.fit(features, y, categorical_feature=categorical)
        details.append(
            {
                "run_name": run_name,
                "disease_group_id": disease_id,
                "n_estimators_locked": int(best_iterations[disease_id]),
                "positive_fit_queries": int(y.sum()),
                "fit_seconds": time.perf_counter() - label_started,
            }
        )
        models.append(model)
        if (index + 1) % 50 == 0 or index + 1 == len(disease_ids):
            event(
                "fit_progress",
                run_name=run_name,
                classifiers=index + 1,
                total=len(disease_ids),
            )
    return (
        models,
        {
            "run_name": run_name,
            "classifier_count": len(models),
            "feature_count": features.shape[1],
            "fit_query_count": len(features),
            "training_seconds": time.perf_counter() - started,
            "mean_locked_iteration": float(np.mean(list(best_iterations.values()))),
            "median_locked_iteration": float(np.median(list(best_iterations.values()))),
            "min_locked_iteration": int(min(best_iterations.values())),
            "max_locked_iteration": int(max(best_iterations.values())),
        },
        details,
    )


def predict_experiment(
    run_name: str,
    models: list[LGBMClassifier],
    features: pd.DataFrame,
    disease_ids: list[str],
) -> tuple[np.ndarray, float]:
    started = time.perf_counter()
    scores = np.empty((len(features), len(disease_ids)), dtype=np.float32)
    for index, model in enumerate(models):
        if model.classes_.tolist() != [0, 1]:
            raise RuntimeError(f"{run_name}/{disease_ids[index]}: invalid classes")
        scores[:, index] = model.predict_proba(features)[:, 1].astype(np.float32)
    return scores, time.perf_counter() - started


def save_top10_predictions(
    path: Path,
    query_ids: list[str],
    disease_ids: list[str],
    scores: np.ndarray,
) -> None:
    order = np.argsort(-scores, axis=1, kind="stable")[:, :10]
    records: list[dict[str, Any]] = []
    for query_index, query_id in enumerate(query_ids):
        for rank, disease_index in enumerate(order[query_index], start=1):
            records.append(
                {
                    "query_id": query_id,
                    "rank": rank,
                    "disease_group_id": disease_ids[int(disease_index)],
                    "score": float(scores[query_index, int(disease_index)]),
                }
            )
    pd.DataFrame(records).to_csv(path, index=False, compression="gzip")


def paired_bootstrap(
    horizon: int,
    weather: dict[str, np.ndarray],
    no_weather: dict[str, np.ndarray],
    iterations: int,
    seed: int,
) -> list[dict[str, Any]]:
    n_query = len(weather[METRICS[0]])
    valid = ~np.isnan(weather[METRICS[0]])
    differences = {
        metric: np.nan_to_num(weather[metric] - no_weather[metric], nan=0.0)
        for metric in METRICS
    }
    gains = {metric: np.empty(iterations, dtype=np.float64) for metric in METRICS}
    rng = np.random.default_rng(seed)
    for start in range(0, iterations, 250):
        stop = min(start + 250, iterations)
        indices = rng.integers(0, n_query, size=(stop - start, n_query))
        denominator = valid[indices].sum(axis=1)
        if np.any(denominator == 0):
            raise RuntimeError(f"H{horizon}: bootstrap draw has no evaluable query")
        for metric in METRICS:
            gains[metric][start:stop] = differences[metric][indices].sum(axis=1) / denominator
    rows: list[dict[str, Any]] = []
    for metric in METRICS:
        values = gains[metric]
        observed = float(np.nanmean(differences[metric][valid]))
        lower, upper = np.percentile(values, [2.5, 97.5])
        decision = (
            "ROBUST_POSITIVE"
            if lower > 0
            else "ROBUST_NEGATIVE"
            if upper < 0
            else "UNCERTAIN"
        )
        rows.append(
            {
                "horizon": f"H{horizon}",
                "metric": metric,
                "observed_gain": observed,
                "bootstrap_mean_gain": float(values.mean()),
                "bootstrap_median_gain": float(np.median(values)),
                "bootstrap_se": float(values.std(ddof=1)),
                "ci95_lower": float(lower),
                "ci95_upper": float(upper),
                "prob_gain_gt_zero": float((values > 0).mean()),
                "n_bootstrap": iterations,
                "decision": decision,
            }
        )
    return rows


def write_pretest_report(training_runs: list[dict[str, Any]]) -> None:
    lines = [
        "# LightGBM OVR One-Time Final Test",
        "",
        "> PRE-TEST LOCK: endpoint/model roles below were written after all final fitting "
        "and before TEST data or metric was opened.",
        "",
        "## Locked endpoint roles",
        "",
        "- **PRIMARY MODEL:** LightGBM One-vs-Rest H14 WITH WEATHER",
        "- **PRIMARY ENDPOINT:** H14 Weather vs NoWeather NDCG@5",
        "- **SECONDARY CONFIRMATORY:** H14 Weather vs NoWeather NDCG@10",
        "- **SECONDARY HORIZON ANALYSES:** H3 and H7",
        "- H3/H7 cannot replace H14 based on this final TEST.",
        "",
        "## Pre-TEST status",
        "",
        "All six final experiments and three baselines were fit using TRAIN+VALIDATION. "
        "Per-disease iteration counts came from the locked benchmark; no final early stopping was used.",
        "",
        "| Run | Classifiers | Features | Train time (s) |",
        "|---|---:|---:|---:|",
    ]
    for row in training_runs:
        lines.append(
            f"| {row['run_name']} | {row['classifier_count']} | {row['feature_count']} | "
            f"{row['training_seconds']:.3f} |"
        )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fmt(value: float, signed: bool = False) -> str:
    return f"{value:+.6f}" if signed else f"{value:.6f}"


def write_final_report(
    final_summary: pd.DataFrame,
    bootstrap_summary: pd.DataFrame,
    validation_reference: dict[int, dict[str, float]],
    training_runs: list[dict[str, Any]],
    test_stats: dict[int, dict[str, Any]],
    decisions: dict[str, str],
    prediction_total: float,
    bootstrap_seconds: float,
    total_seconds: float,
) -> None:
    weather = final_summary[final_summary["variant"] == "with_weather"].set_index("horizon")
    no_weather = final_summary[final_summary["variant"] == "no_weather"].set_index("horizon")
    baseline = final_summary[final_summary["variant"] == "baseline"].set_index("horizon")
    boot = bootstrap_summary.set_index(["horizon", "metric"])
    lines = [
        "# LightGBM OVR One-Time Final Test Report",
        "",
        "> Endpoint/model roles were locked and written to this report before TEST was opened.",
        "",
        "## 1. Primary / secondary endpoint lock",
        "",
        "- **PRIMARY MODEL:** LightGBM One-vs-Rest H14 WITH WEATHER",
        "- **PRIMARY ENDPOINT:** H14 Weather vs NoWeather NDCG@5",
        "- **SECONDARY CONFIRMATORY:** H14 Weather vs NoWeather NDCG@10",
        "- **SECONDARY HORIZONS:** H3 and H7; these results cannot replace H14 using this TEST.",
        "",
        "## 2. Final training protocol",
        "",
        "Six OVR experiments were refit on TRAIN+VALIDATION using locked per-disease best iterations. "
        "TEST was not used for fitting, early stopping, category mapping, hyperparameters or horizon selection.",
        "",
        "## 3. NDCG@5 final TEST",
        "",
        "| Horizon | Weather | NoWeather | Baseline | Weather gain | 95% CI | P(gain>0) | Decision |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for horizon in ("H3", "H7", "H14"):
        b = boot.loc[(horizon, "ndcg_at_5")]
        lines.append(
            f"| {horizon} | {weather.loc[horizon, 'ndcg_at_5']:.6f} | "
            f"{no_weather.loc[horizon, 'ndcg_at_5']:.6f} | {baseline.loc[horizon, 'ndcg_at_5']:.6f} | "
            f"{b.observed_gain:+.6f} | [{b.ci95_lower:+.6f}, {b.ci95_upper:+.6f}] | "
            f"{b.prob_gain_gt_zero:.4f} | {b.decision} |"
        )
    lines.extend(
        [
            "",
            "## 4. NDCG@10 final TEST",
            "",
            "| Horizon | Weather | NoWeather | Baseline | Weather gain | 95% CI | P(gain>0) | Decision |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for horizon in ("H3", "H7", "H14"):
        b = boot.loc[(horizon, "ndcg_at_10")]
        lines.append(
            f"| {horizon} | {weather.loc[horizon, 'ndcg_at_10']:.6f} | "
            f"{no_weather.loc[horizon, 'ndcg_at_10']:.6f} | {baseline.loc[horizon, 'ndcg_at_10']:.6f} | "
            f"{b.observed_gain:+.6f} | [{b.ci95_lower:+.6f}, {b.ci95_upper:+.6f}] | "
            f"{b.prob_gain_gt_zero:.4f} | {b.decision} |"
        )
    lines.extend(["", "## 5. All ranking metrics", ""])
    for horizon in ("H3", "H7", "H14"):
        lines.extend(
            [
                f"### {horizon}",
                "",
                "| Variant | P@5 | R@5 | NDCG@5 | P@10 | R@10 | NDCG@10 |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for variant, label in (
            ("with_weather", "WITH WEATHER"),
            ("no_weather", "NO WEATHER"),
            ("baseline", "BASELINE"),
        ):
            row = final_summary[
                (final_summary["horizon"] == horizon)
                & (final_summary["variant"] == variant)
            ].iloc[0]
            lines.append(
                f"| {label} | {row.precision_at_5:.6f} | {row.recall_at_5:.6f} | "
                f"{row.ndcg_at_5:.6f} | {row.precision_at_10:.6f} | "
                f"{row.recall_at_10:.6f} | {row.ndcg_at_10:.6f} |"
            )
    lines.extend(
        [
            "",
            "## 6. TEST target contract",
            "",
            "| Horizon | Queries | Date range | Mean positives/query | Median | Zero-positive | Included | Unsupported positive pairs excluded |",
            "|---|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for horizon in (3, 7, 14):
        row = test_stats[horizon]
        lines.append(
            f"| H{horizon} | {row['query_count']} | {row['date_start']} to {row['date_end']} | "
            f"{row['mean_positive']:.3f} | {row['median_positive']:.1f} | "
            f"{row['zero_positive']} | {row['included_queries']} | {row['unsupported_pairs']} |"
        )
    lines.extend(
        [
            "",
            "## 7. VALIDATION vs TEST",
            "",
            "| Horizon | Metric | Validation Weather | TEST Weather | Validation gain | TEST gain |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for horizon in (3, 7, 14):
        for metric in ("ndcg_at_5", "ndcg_at_10"):
            test_gain = boot.loc[(f"H{horizon}", metric), "observed_gain"]
            lines.append(
                f"| H{horizon} | {metric} | {validation_reference[horizon][f'weather_{metric}']:.6f} | "
                f"{weather.loc[f'H{horizon}', metric]:.6f} | "
                f"{validation_reference[horizon][f'gain_{metric}']:+.6f} | {test_gain:+.6f} |"
            )
    lines.extend(
        [
            "",
            "## 8. Time",
            "",
            "| Run | Training seconds | Prediction seconds |",
            "|---|---:|---:|",
        ]
    )
    for row in training_runs:
        prediction = final_summary.loc[
            final_summary["run_name"] == row["run_name"], "prediction_seconds"
        ].iloc[0]
        lines.append(
            f"| {row['run_name']} | {row['training_seconds']:.3f} | {prediction:.3f} |"
        )
    lines.extend(
        [
            "",
            f"Prediction total: {prediction_total:.3f}s; paired bootstrap: {bootstrap_seconds:.3f}s; "
            f"total wall-clock: {total_seconds:.3f}s.",
            "",
            "## 9. Final decisions",
            "",
            f"- **H14 PRIMARY:** {decisions['H14']}.",
            f"- **H3 SECONDARY:** {decisions['H3']}.",
            f"- **H7 SECONDARY:** {decisions['H7']}.",
            "- These are predictive/statistical associations, not causal claims.",
            "- H3/H7 results are descriptive secondary evaluations; another external temporal holdout is required to confirm a different horizon.",
            "",
            "## 10. Integrity",
            "",
            "- **PASS:** raw/processed/splits/schema/disease universe/benchmark config checksums stayed locked.",
            "- TEST was opened only after all six models and three baselines were fit.",
            "- TEST was not used for fitting, early stopping, category mapping, tuning, feature selection or horizon selection.",
            "- Six TEST score matrices were generated once and persisted; metrics/bootstrap reused them without inference.",
            "- No training occurred after TEST was opened or after TEST metrics were viewed.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def load_validation_reference(config: dict[str, Any]) -> dict[int, dict[str, float]]:
    result: dict[int, dict[str, float]] = {}
    for horizon in config["horizons"]:
        frame = pd.read_csv(BENCHMARK_DIR / "metrics" / f"h{horizon}_metrics.csv")
        weather = frame.loc[frame["run_name"] == f"h{horizon}_with_weather"].iloc[0]
        no_weather = frame.loc[frame["run_name"] == f"h{horizon}_no_weather"].iloc[0]
        result[horizon] = {}
        for metric in ("ndcg_at_5", "ndcg_at_10"):
            result[horizon][f"weather_{metric}"] = float(weather[metric])
            result[horizon][f"gain_{metric}"] = float(weather[metric] - no_weather[metric])
    return result


def run(preflight_only: bool) -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    locked_before = verify_locked(config)
    if TEST_OPENED_MARKER.exists():
        raise RuntimeError("One-time TEST marker already exists; refusing to rerun")
    bundle = prepare_fit_bundle(config)
    if preflight_only:
        print(
            json.dumps(
                {
                    "preflight": "PASS",
                    "lightgbm_version": lgb.__version__,
                    "fit_queries": len(bundle["fit_ids"]),
                    "train_queries": len(bundle["train_ids"]),
                    "validation_queries": len(bundle["validation_ids"]),
                    "disease_count": len(bundle["disease_ids"]),
                    "feature_count": len(bundle["feature_names"]),
                    "best_iteration_rows": len(bundle["iteration_frame"]),
                    "test_data_parsed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    ensure_output_dirs()
    EVENT_LOG.write_text("", encoding="utf-8")
    total_started = time.perf_counter()
    state = {"training_allowed": True, "training_calls_after_test": 0}
    event(
        "endpoint_lock_confirmed",
        primary_model=config["primary_model"],
        primary_endpoint=config["primary_endpoint"],
        secondary_confirmatory=config["secondary_confirmatory_endpoint"],
        horizon_selection=config["horizon_selection_locked"],
    )
    bundle["iteration_frame"].to_csv(
        METADATA_DIR / "best_iterations_locked.csv", index=False
    )
    (METADATA_DIR / "category_mappings.json").write_text(
        json.dumps(bundle["mappings"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validation_reference = load_validation_reference(config)

    models_by_run: dict[str, list[LGBMClassifier]] = {}
    training_runs: list[dict[str, Any]] = []
    classifier_details: list[dict[str, Any]] = []
    baselines: dict[int, dict[str, Any]] = {}
    baseline_fit_seconds: dict[int, float] = {}
    for horizon in config["horizons"]:
        target = bundle["target_matrices"][horizon]
        for variant in ("with_weather", "no_weather"):
            run_name = f"h{horizon}_{variant}"
            features = (
                bundle["fit_features"]
                if variant == "with_weather"
                else bundle["fit_features"][bundle["no_weather_features"]]
            )
            event("fit_started", run_name=run_name)
            models, run_meta, details = fit_experiment(
                run_name,
                features,
                target,
                bundle["disease_ids"],
                bundle["best_iterations"][run_name],
                config,
                state,
            )
            models_by_run[run_name] = models
            training_runs.append(run_meta)
            classifier_details.extend(details)
            event("fit_completed", **run_meta)
        baseline_started = time.perf_counter()
        baselines[horizon] = fit_baseline(
            bundle["contexts"], bundle["targets"], bundle["disease_ids"], horizon
        )
        baseline_fit_seconds[horizon] = time.perf_counter() - baseline_started
        event(
            "baseline_fit_completed",
            horizon=f"H{horizon}",
            training_seconds=baseline_fit_seconds[horizon],
        )

    if len(models_by_run) != 6 or any(len(models) != 221 for models in models_by_run.values()):
        raise RuntimeError("Final model inventory incomplete before TEST")
    pd.DataFrame(training_runs).to_csv(METADATA_DIR / "training_runs.csv", index=False)
    pd.DataFrame(classifier_details).to_csv(
        METADATA_DIR / "classifier_training_details.csv", index=False
    )
    write_pretest_report(training_runs)
    state["training_allowed"] = False
    event(
        "all_training_and_baseline_fit_complete",
        final_experiments=6,
        classifiers=1326,
        baselines=3,
        test_data_parsed=False,
    )

    # The one-time TEST boundary starts here. No .fit call is reachable below.
    TEST_OPENED_MARKER.write_text(
        json.dumps(
            {
                "opened_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
                "purpose": "one_time_final_evaluation",
                "training_complete": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    event("test_opened_once", training_allowed=False)
    test_ids = load_ids(TEST_IDS_PATH)
    test_selected = set(test_ids)
    test_contexts = load_selected_gzip_csv(
        CONTEXTS_PATH,
        test_selected,
        dtype={"query_id": str},
        require_one_context_per_id=True,
    )
    test_targets = load_selected_gzip_csv(
        TARGETS_PATH,
        test_selected,
        dtype={"query_id": str, "disease_group_id": str},
        require_one_context_per_id=False,
    )
    if test_selected & set(bundle["fit_ids"]):
        raise RuntimeError("TEST overlaps final-fit IDs")
    test_indexed = test_contexts.set_index("query_id", drop=False)
    ordered_test_contexts = test_indexed.loc[test_ids].reset_index(drop=True)
    test_weather = transform_features(
        test_contexts,
        test_ids,
        bundle["feature_names"],
        list(config["categorical_features"]),
        bundle["mappings"],
    )
    test_no_weather = test_weather[bundle["no_weather_features"]].copy()
    event("test_data_loaded", query_count=len(test_ids))

    scores: dict[str, np.ndarray] = {}
    prediction_seconds: dict[str, float] = {}
    prediction_total_started = time.perf_counter()
    for horizon in config["horizons"]:
        for variant in ("with_weather", "no_weather"):
            run_name = f"h{horizon}_{variant}"
            features = test_weather if variant == "with_weather" else test_no_weather
            score_matrix, seconds = predict_experiment(
                run_name, models_by_run[run_name], features, bundle["disease_ids"]
            )
            scores[run_name] = score_matrix
            prediction_seconds[run_name] = seconds
            np.save(SCORES_DIR / f"{run_name}.npy", score_matrix, allow_pickle=False)
            save_top10_predictions(
                PREDICTIONS_DIR / f"{run_name}_top10.csv.gz",
                test_ids,
                bundle["disease_ids"],
                score_matrix,
            )
            event("test_prediction_saved", run_name=run_name, prediction_seconds=seconds)
    prediction_total = time.perf_counter() - prediction_total_started
    models_by_run.clear()
    event("all_test_predictions_complete", score_matrices=6)

    score_contract = {
        "query_count": len(test_ids),
        "disease_count": len(bundle["disease_ids"]),
        "query_order_sha256": ordered_sha256(test_ids),
        "disease_order_sha256": ordered_sha256(bundle["disease_ids"]),
        "query_ids": test_ids,
        "disease_ids": bundle["disease_ids"],
        "score_files": {
            run_name: str((SCORES_DIR / f"{run_name}.npy").relative_to(FINAL_DIR)).replace("\\", "/")
            for run_name in scores
        },
    }
    (METADATA_DIR / "score_contract.json").write_text(
        json.dumps(score_contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    contributions: dict[str, dict[str, np.ndarray]] = {}
    metrics_by_run: dict[str, dict[str, float | int]] = {}
    baseline_metrics: dict[int, dict[str, float | int]] = {}
    baseline_prediction_seconds: dict[int, float] = {}
    targets_by_horizon: dict[int, np.ndarray] = {}
    test_stats: dict[int, dict[str, Any]] = {}
    supported = set(bundle["disease_ids"])
    dates = pd.to_datetime(ordered_test_contexts["anchor_date"], errors="raise")
    for horizon in config["horizons"]:
        target = build_target_matrix(test_ids, bundle["disease_ids"], test_targets, horizon)
        targets_by_horizon[horizon] = target
        for variant in ("with_weather", "no_weather"):
            run_name = f"h{horizon}_{variant}"
            contributions[run_name] = metric_contributions(scores[run_name], target)
            metrics_by_run[run_name] = aggregate_metrics(contributions[run_name])
        baseline_started = time.perf_counter()
        order = baseline_order(baselines[horizon], ordered_test_contexts, bundle["disease_ids"])
        baseline_contrib = metric_contributions_from_order(order, target)
        baseline_prediction_seconds[horizon] = time.perf_counter() - baseline_started
        baseline_metrics[horizon] = aggregate_metrics(baseline_contrib)
        unsupported_pairs = int(
            (
                (test_targets[f"has_case_h{horizon}"] == 1)
                & (~test_targets["disease_group_id"].isin(supported))
            ).sum()
        )
        positives = target.sum(axis=1)
        test_stats[horizon] = {
            "query_count": len(test_ids),
            "date_start": str(dates.min().date()),
            "date_end": str(dates.max().date()),
            "mean_positive": float(positives.mean()),
            "median_positive": float(np.median(positives)),
            "zero_positive": int((positives == 0).sum()),
            "included_queries": int((positives > 0).sum()),
            "unsupported_pairs": unsupported_pairs,
        }
    event("test_metrics_computed", training_calls_after_test=0)

    bootstrap_started = time.perf_counter()
    bootstrap_rows: list[dict[str, Any]] = []
    for horizon in config["horizons"]:
        bootstrap_rows.extend(
            paired_bootstrap(
                horizon,
                contributions[f"h{horizon}_with_weather"],
                contributions[f"h{horizon}_no_weather"],
                int(config["bootstrap"]["iterations"]),
                int(config["bootstrap"]["random_seed"]),
            )
        )
    bootstrap_seconds = time.perf_counter() - bootstrap_started
    bootstrap_summary = pd.DataFrame(bootstrap_rows)
    bootstrap_summary.to_csv(BOOTSTRAP_SUMMARY_PATH, index=False)
    event("test_bootstrap_complete", seconds=bootstrap_seconds, iterations=5000)

    final_rows: list[dict[str, Any]] = []
    training_by_run = {row["run_name"]: row for row in training_runs}
    for horizon in config["horizons"]:
        weather = metrics_by_run[f"h{horizon}_with_weather"]
        no_weather = metrics_by_run[f"h{horizon}_no_weather"]
        baseline = baseline_metrics[horizon]
        gains = {metric: float(weather[metric]) - float(no_weather[metric]) for metric in METRICS}
        for variant, values in (
            ("with_weather", weather),
            ("no_weather", no_weather),
            ("baseline", baseline),
        ):
            run_name = f"h{horizon}_{variant}"
            training_seconds = (
                baseline_fit_seconds[horizon]
                if variant == "baseline"
                else training_by_run[run_name]["training_seconds"]
            )
            prediction_time = (
                baseline_prediction_seconds[horizon]
                if variant == "baseline"
                else prediction_seconds[run_name]
            )
            final_rows.append(
                {
                    "horizon": f"H{horizon}",
                    "role": "PRIMARY" if horizon == 14 else "SECONDARY",
                    "variant": variant,
                    "run_name": run_name,
                    "test_query_count": len(test_ids),
                    "date_start": test_stats[horizon]["date_start"],
                    "date_end": test_stats[horizon]["date_end"],
                    "mean_positive_diseases": test_stats[horizon]["mean_positive"],
                    "median_positive_diseases": test_stats[horizon]["median_positive"],
                    "zero_positive_queries": test_stats[horizon]["zero_positive"],
                    "evaluated_queries": int(values["evaluated_queries"]),
                    "unsupported_positive_pairs_excluded": test_stats[horizon]["unsupported_pairs"],
                    "feature_count": 45 if variant == "with_weather" else 6 if variant == "no_weather" else 3,
                    "classifier_count": 221 if variant != "baseline" else 0,
                    "training_seconds": training_seconds,
                    "prediction_seconds": prediction_time,
                    **{metric: float(values[metric]) for metric in METRICS},
                    **{f"weather_gain_{metric}": gains[metric] for metric in METRICS},
                    **{
                        f"variant_minus_baseline_{metric}": float(values[metric]) - float(baseline[metric])
                        for metric in METRICS
                    },
                }
            )
    final_summary = pd.DataFrame(final_rows)
    final_summary.to_csv(SUMMARY_PATH, index=False)

    decisions: dict[str, str] = {}
    for horizon in (3, 7, 14):
        decision = bootstrap_summary.loc[
            (bootstrap_summary["horizon"] == f"H{horizon}")
            & (bootstrap_summary["metric"] == "ndcg_at_5"),
            "decision",
        ].iloc[0]
        if horizon == 14:
            decisions["H14"] = {
                "ROBUST_POSITIVE": "H14_FINAL_CONFIRMED",
                "UNCERTAIN": "H14_FINAL_WEATHER_UNCERTAIN",
                "ROBUST_NEGATIVE": "H14_FINAL_WEATHER_NEGATIVE",
            }[decision]
        else:
            decisions[f"H{horizon}"] = f"H{horizon}_SECONDARY_{decision}"

    locked_after = verify_locked(config)
    integrity_pass = locked_before == locked_after
    if not integrity_pass:
        raise RuntimeError("Locked inputs changed during final evaluation")
    total_seconds = time.perf_counter() - total_started
    write_final_report(
        final_summary,
        bootstrap_summary,
        validation_reference,
        training_runs,
        test_stats,
        decisions,
        prediction_total,
        bootstrap_seconds,
        total_seconds,
    )
    output_files = [
        REPORT_PATH,
        SUMMARY_PATH,
        BOOTSTRAP_SUMMARY_PATH,
        *sorted(SCORES_DIR.glob("*.npy")),
        *sorted(PREDICTIONS_DIR.glob("*.csv.gz")),
        *sorted(METADATA_DIR.glob("*")),
    ]
    integrity = {
        "status": "PASS",
        "primary_locked_before_test": True,
        "horizon_selection_locked_before_test": "H14",
        "locked_input_count": len(locked_before),
        "locked_inputs_unchanged": integrity_pass,
        "train_query_count": len(bundle["train_ids"]),
        "validation_query_count": len(bundle["validation_ids"]),
        "final_fit_query_count": len(bundle["fit_ids"]),
        "test_query_count": len(test_ids),
        "disease_count": len(bundle["disease_ids"]),
        "test_used_for_fit": False,
        "test_used_for_early_stopping": False,
        "test_used_for_category_mapping": False,
        "test_used_for_hyperparameter_selection": False,
        "test_used_for_horizon_selection": False,
        "test_used_for_final_evaluation_only": True,
        "training_calls_after_test_opened": 0,
        "test_score_inference_runs": 6,
        "bootstrap_reused_saved_scores": True,
        "output_sha256": {
            str(path.relative_to(FINAL_DIR)).replace("\\", "/"): sha256_file(path)
            for path in output_files
            if path.is_file()
        },
    }
    INTEGRITY_PATH.write_text(
        json.dumps(integrity, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    event("final_evaluation_complete", **decisions, total_seconds=total_seconds)
    print(
        json.dumps(
            {
                "status": "PASS",
                "decisions": decisions,
                "total_seconds": total_seconds,
                "prediction_seconds": prediction_total,
                "bootstrap_seconds": bootstrap_seconds,
                "unsupported_pairs": {
                    f"H{horizon}": test_stats[horizon]["unsupported_pairs"]
                    for horizon in config["horizons"]
                },
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    try:
        return run(args.preflight)
    except Exception:
        if not args.preflight:
            ensure_output_dirs()
            (LOGS_DIR / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
            INTEGRITY_PATH.write_text(
                json.dumps(
                    {
                        "status": "FAIL",
                        "test_boundary_crossed": TEST_OPENED_MARKER.exists(),
                        "rerun_allowed": not TEST_OPENED_MARKER.exists(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
