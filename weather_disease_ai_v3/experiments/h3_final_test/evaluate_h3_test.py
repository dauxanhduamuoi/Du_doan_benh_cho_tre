"""One-time final TEST evaluation for the validation-selected H3 models.

This module never trains or modifies a CatBoost model. It loads the two locked
H3 models, predicts the fixed TEST split once, evaluates a TRAIN-only baseline,
and performs paired query-level bootstrap on fixed predictions.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EVALUATION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVALUATION_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.h7_full_train import train_h7 as metric_contract
from src.baseline import FrequencyRankingBaseline


CONFIG_PATH = EVALUATION_DIR / "evaluation_config.json"
REPORT_PATH = EVALUATION_DIR / "H3_FINAL_TEST_REPORT.md"
RESULTS_PATH = EVALUATION_DIR / "test_results.csv"
METRICS_DIR = EVALUATION_DIR / "metrics"
PREDICTIONS_DIR = EVALUATION_DIR / "predictions"
LOG_DIR = EVALUATION_DIR / "logs"
LOG_PATH = LOG_DIR / "evaluation.log"

CONTEXTS_PATH = PROJECT_ROOT / "data/processed/contexts.csv.gz"
TARGETS_PATH = PROJECT_ROOT / "data/processed/targets.csv.gz"
CATALOG_PATH = PROJECT_ROOT / "data/processed/disease_catalog.csv"
METADATA_PATH = PROJECT_ROOT / "data/processed/dataset_metadata.json"
TRAIN_IDS_PATH = PROJECT_ROOT / "data/splits/train_query_ids.csv"
TEST_IDS_PATH = PROJECT_ROOT / "data/splits/test_query_ids.csv"

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
        "training_artifacts": verify_hash_map(
            config["locked_training_artifact_sha256"], "training artifact"
        ),
    }


def build_target_matrix(
    query_ids: list[str], disease_ids: list[str], targets: pd.DataFrame
) -> np.ndarray:
    query_index = {value: index for index, value in enumerate(query_ids)}
    disease_index = {value: index for index, value in enumerate(disease_ids)}
    matrix = np.zeros((len(query_ids), len(disease_ids)), dtype=np.uint8)
    positive = targets.loc[
        (targets["has_case_h3"] == 1)
        & targets["query_id"].isin(query_index)
        & targets["disease_group_id"].isin(disease_index),
        ["query_id", "disease_group_id"],
    ]
    for query_id, disease_id in positive.itertuples(index=False):
        matrix[query_index[str(query_id)], disease_index[str(disease_id)]] = 1
    return matrix


def prepare_features(
    indexed_contexts: pd.DataFrame,
    query_ids: list[str],
    feature_names: list[str],
    categorical_features: list[str],
) -> pd.DataFrame:
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
    frame = indexed_contexts.loc[query_ids, feature_names].reset_index(drop=True).copy()
    for column in categorical_features:
        frame[column] = frame[column].fillna("Không rõ").astype(str)
    frame["month"] = pd.to_numeric(frame["month"], errors="raise").astype("int16")
    if frame.columns.tolist() != feature_names:
        raise RuntimeError("Feature order changed while preparing TEST")
    return frame


def per_query_metrics(
    query_ids: list[str], order: np.ndarray, target: np.ndarray
) -> pd.DataFrame:
    if order.shape != target.shape:
        raise RuntimeError(f"Ranking shape {order.shape} != target shape {target.shape}")
    records: list[dict[str, Any]] = []
    for row_index, query_id in enumerate(query_ids):
        relevant = set(np.flatnonzero(target[row_index]))
        if not relevant:
            continue
        row: dict[str, Any] = {
            "query_id": query_id,
            "positive_count": len(relevant),
        }
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
    return pd.DataFrame(records)


def summarize_order(
    query_ids: list[str], order: np.ndarray, target: np.ndarray
) -> tuple[dict[str, Any], pd.DataFrame]:
    summary = metric_contract.ranking_metrics_from_order(order, target)
    summary["evaluated_test_queries"] = summary.pop("evaluated_validation_queries")
    summary["zero_positive_test_queries"] = summary.pop(
        "zero_positive_validation_queries"
    )
    per_query = per_query_metrics(query_ids, order, target)
    for key in METRIC_KEYS:
        if not math.isclose(
            float(summary[key]), float(per_query[key].mean()), rel_tol=0.0, abs_tol=1e-12
        ):
            raise RuntimeError(f"Metric implementation mismatch for {key}")
    return summary, per_query


def bootstrap_summary(
    weather: pd.DataFrame,
    control: pd.DataFrame,
    baseline: pd.DataFrame,
    repetitions: int,
    seed: int,
) -> pd.DataFrame:
    aligned = (
        weather.merge(control, on="query_id", suffixes=("_weather", "_control"))
        .merge(baseline, on="query_id")
        .sort_values("query_id")
        .reset_index(drop=True)
    )
    if len(aligned) != len(weather) or len(aligned) != len(control) or len(aligned) != len(baseline):
        raise RuntimeError("Bootstrap query alignment failed")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(aligned), size=(repetitions, len(aligned)))
    rows = []
    for key in ("ndcg_at_5", "ndcg_at_10"):
        w = aligned[f"{key}_weather"].to_numpy(dtype=float)
        n = aligned[f"{key}_control"].to_numpy(dtype=float)
        b = aligned[key].to_numpy(dtype=float)
        series = {
            f"with_weather_{key}": w,
            f"no_weather_{key}": n,
            f"baseline_{key}": b,
            f"weather_minus_no_weather_{key}": w - n,
            f"weather_minus_baseline_{key}": w - b,
        }
        for name, values in series.items():
            boot_means = values[indices].mean(axis=1)
            lower, upper = np.quantile(boot_means, [0.025, 0.975])
            rows.append(
                {
                    "statistic": name,
                    "estimate": float(values.mean()),
                    "ci_lower_95": float(lower),
                    "ci_upper_95": float(upper),
                    "bootstrap_repetitions": repetitions,
                    "random_seed": seed,
                    "evaluated_queries": len(values),
                }
            )
    return pd.DataFrame(rows)


def decide_final(
    config: dict[str, Any],
    weather: dict[str, Any],
    control: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[str, str]:
    deltas = {key: float(weather[key]) - float(control[key]) for key in METRIC_KEYS}
    tolerance = float(config["baseline_competitive_tolerance"])
    competitive = (
        float(weather["ndcg_at_5"]) >= float(baseline["ndcg_at_5"]) - tolerance
        or float(weather["ndcg_at_10"]) >= float(baseline["ndcg_at_10"]) - tolerance
    )
    if not competitive:
        return (
            "H3_FINAL_MODEL_NOT_GENERALIZED",
            "WITH WEATHER không cạnh tranh baseline trên TEST trong tolerance đã khóa.",
        )
    if (
        deltas["ndcg_at_5"] <= 0
        or deltas["ndcg_at_10"]
        <= float(config["weather_reversal_ndcg10_threshold"])
    ):
        return (
            "H3_FINAL_WEATHER_NOT_CONFIRMED",
            "Weather gain trên TEST mất hoặc đảo chiều theo gate NDCG đã khóa, dù validation từng promising.",
        )
    practical = deltas["ndcg_at_5"] >= float(
        config["weather_practical_ndcg_delta"]
    )
    severe_drop = min(deltas.values()) < float(config["severe_metric_drop"])
    if practical and not severe_drop:
        return (
            "H3_FINAL_WEATHER_SUPPORTED",
            "WITH WEATHER cạnh tranh baseline và giữ weather gain NDCG@5 đủ ngưỡng thực dụng trên TEST.",
        )
    return (
        "H3_FINAL_MODEL_GOOD_WEATHER_WEAK",
        "WITH WEATHER cạnh tranh baseline nhưng weather gain trên TEST gần 0 hoặc chưa đạt ngưỡng thực dụng.",
    )


def fmt(value: Any, digits: int = 4) -> str:
    return metric_contract.fmt(value, digits)


def write_predictions(
    query_ids: list[str],
    indexed_contexts: pd.DataFrame,
    disease_ids: list[str],
    disease_names: dict[str, str],
    target: np.ndarray,
    weather_scores: np.ndarray,
    control_scores: np.ndarray,
) -> int:
    records: list[dict[str, Any]] = []
    for variant, scores in (
        ("with_weather", weather_scores),
        ("no_weather", control_scores),
    ):
        order = np.argsort(-scores, axis=1, kind="stable")[:, :10]
        for row_index, query_id in enumerate(query_ids):
            context = indexed_contexts.loc[query_id]
            for rank, disease_index in enumerate(order[row_index], start=1):
                disease_id = disease_ids[int(disease_index)]
                records.append(
                    {
                        "model_variant": variant,
                        "query_id": query_id,
                        "anchor_date": context["anchor_date"],
                        "age_group": context["age_group"],
                        "gender": context["gender"],
                        "rank": rank,
                        "disease_group_id": disease_id,
                        "disease_group_name": disease_names.get(disease_id, ""),
                        "ranking_score": float(scores[row_index, int(disease_index)]),
                        "actual_positive_h3": int(target[row_index, int(disease_index)]),
                    }
                )
    output = PREDICTIONS_DIR / "test_top10_predictions.csv.gz"
    pd.DataFrame(records).to_csv(
        output,
        index=False,
        compression={"method": "gzip", "compresslevel": 9, "mtime": 0},
    )
    return len(records)


def write_report(
    config: dict[str, Any],
    data: dict[str, Any],
    weather: dict[str, Any],
    control: dict[str, Any],
    baseline: dict[str, Any],
    comparison: pd.DataFrame,
    bootstrap: pd.DataFrame,
    decision: str,
    reason: str,
    integrity_pass: bool,
    model_hashes: dict[str, str],
) -> None:
    by_metric = comparison.set_index("metric")
    validation = config["validation_reference"]
    boot = bootstrap.set_index("statistic")
    labels = {
        "precision_at_5": "Precision@5",
        "recall_at_5": "Recall@5",
        "ndcg_at_5": "NDCG@5",
        "precision_at_10": "Precision@10",
        "recall_at_10": "Recall@10",
        "ndcg_at_10": "NDCG@10",
    }
    lines = [
        "# H3 Final Test Report",
        "",
        "## 1. MODEL LOCK",
        "",
        f"- H3 WITH WEATHER SHA-256: `{model_hashes['with_weather']}`; tree count: 18.",
        f"- H3 NO WEATHER SHA-256: `{model_hashes['no_weather']}`; tree count: 15.",
        "- H3 đã được chọn bằng VALIDATION trước khi TEST được load. Không retrain, tuning, resume training hay chọn iteration mới.",
        "",
        "## 2. TEST DATA",
        "",
        f"- TEST queries: {data['test_query_count']}; date range: {data['test_date_start']} → {data['test_date_end']}.",
        f"- Supported diseases từ TRAIN: {data['disease_count']}; target shape: `{data['target_shape']}`.",
        f"- Positive diseases/query: mean={fmt(data['mean_positive_diseases'], 3)}, median={fmt(data['median_positive_diseases'], 3)}; zero-positive={data['zero_positive_queries']}.",
        f"- Query tham gia mean metric: {weather['evaluated_test_queries']} / {data['test_query_count']}.",
        f"- Positive TEST pairs ngoài TRAIN-supported universe, không được chấm như label model: {data['unsupported_positive_pairs']}.",
        "",
        "## 3. WITH WEATHER",
        "",
        f"- 45 features theo đúng schema/order model; prediction time={fmt(weather['prediction_seconds'], 3)} giây.",
        "",
        "## 4. NO WEATHER",
        "",
        f"- 6 features theo đúng schema/order model; prediction time={fmt(control['prediction_seconds'], 3)} giây.",
        "",
        "## 5. BASELINE",
        "",
        "Baseline H3 rebuild từ TRAIN-only theo `age_group + gender + month → age_group + month → month → global`, dùng `case_count_h3` làm frequency prior. TEST chỉ được evaluate.",
        "",
        "## 6. TEST METRICS",
        "",
        "| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather-NoWeather | Weather-Baseline |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key in METRIC_KEYS:
        row = by_metric.loc[key]
        lines.append(
            f"| {labels[key]} | {fmt(row['with_weather'])} | {fmt(row['no_weather'])} | "
            f"{fmt(row['baseline'])} | {fmt(row['weather_minus_no_weather'], 6)} | "
            f"{fmt(row['weather_minus_baseline'], 6)} |"
        )
    lines.extend(
        [
            "",
            "## 7. WEATHER DELTA",
            "",
            f"- Weather-NoWeather NDCG@5: {fmt(by_metric.loc['ndcg_at_5', 'weather_minus_no_weather'], 6)}.",
            f"- Weather-NoWeather NDCG@10: {fmt(by_metric.loc['ndcg_at_10', 'weather_minus_no_weather'], 6)}.",
            "",
            "Weather delta chỉ là bằng chứng dự báo thống kê trong bộ dữ liệu hiện tại, không phải quan hệ nhân quả.",
            "",
            "## 8. BASELINE DELTA",
            "",
            f"- Weather-Baseline NDCG@5: {fmt(by_metric.loc['ndcg_at_5', 'weather_minus_baseline'], 6)}.",
            f"- Weather-Baseline NDCG@10: {fmt(by_metric.loc['ndcg_at_10', 'weather_minus_baseline'], 6)}.",
            "",
            "## 9. VALIDATION VS TEST",
            "",
            "| Metric | Validation Weather | Test Weather | Difference (Test-Validation) |",
            "|---|---:|---:|---:|",
        ]
    )
    for key in ("precision_at_5", "recall_at_5", "ndcg_at_5", "ndcg_at_10"):
        lines.append(
            f"| {labels[key]} | {fmt(validation[key])} | {fmt(weather[key])} | "
            f"{fmt(float(weather[key]) - float(validation[key]), 6)} |"
        )
    lines.extend(
        [
            "",
            "### Weather gain: VALIDATION vs TEST",
            "",
            "| Metric | Validation Weather Gain | Test Weather Gain |",
            "|---|---:|---:|",
        ]
    )
    for key in ("ndcg_at_5", "ndcg_at_10", "precision_at_5", "recall_at_5"):
        lines.append(
            f"| {labels[key]} | {fmt(validation[f'weather_gain_{key}'], 6)} | "
            f"{fmt(by_metric.loc[key, 'weather_minus_no_weather'], 6)} |"
        )
    lines.extend(
        [
            "",
            "## 10. BOOTSTRAP CI",
            "",
            f"Paired query bootstrap: {config['bootstrap_repetitions']} repetitions, random_seed={config['random_seed']}; prediction cố định, không retrain.",
            "",
            "| Statistic | Estimate | 95% CI lower | 95% CI upper |",
            "|---|---:|---:|---:|",
        ]
    )
    for statistic in (
        "with_weather_ndcg_at_5",
        "no_weather_ndcg_at_5",
        "baseline_ndcg_at_5",
        "weather_minus_no_weather_ndcg_at_5",
        "weather_minus_baseline_ndcg_at_5",
        "weather_minus_no_weather_ndcg_at_10",
        "weather_minus_baseline_ndcg_at_10",
    ):
        row = boot.loc[statistic]
        lines.append(
            f"| {statistic} | {fmt(row['estimate'], 6)} | {fmt(row['ci_lower_95'], 6)} | {fmt(row['ci_upper_95'], 6)} |"
        )
    lines.extend(
        [
            "",
            "## 11. FINAL CONCLUSION",
            "",
            f"**{decision}** — {reason}",
            "",
            "Model xếp hạng các nhóm bệnh đáng chú ý dựa trên tuổi, giới tính, thời điểm trong năm và mẫu hình thời tiết hiện tại/gần đây trong dữ liệu lịch sử bệnh viện.",
            "",
            "## 12. LIMITATIONS",
            "",
            "- Ranking score chưa được chứng minh/calibrate thành xác suất cá nhân.",
            "- Đây không phải mô hình chẩn đoán và không chứng minh weather gây ra disease.",
            "- TEST là final holdout; không được dùng lại như validation cho tuning sau báo cáo này.",
            "",
            "## 13. INTEGRITY",
            "",
            f"- Model/source/training artifact checksum sau evaluation: **{'PASS' if integrity_pass else 'FAIL'}**.",
            "- Không train model, không sửa H3, không test H7/H14, không SHAP, API, backend hay frontend.",
            "- Mọi artifact mới chỉ nằm trong `experiments/h3_final_test/`.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    for directory in (METRICS_DIR, PREDICTIONS_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("", encoding="utf-8")
    config = read_config()
    locked_before = verify_locked(config)
    model_hashes_before = {
        name: metric_contract.sha256_file(PROJECT_ROOT / contract["path"])
        for name, contract in config["expected_models"].items()
    }
    log("Locked model/source checksums verified before opening TEST")

    from catboost import CatBoostClassifier, Pool

    models: dict[str, CatBoostClassifier] = {}
    for name, contract in config["expected_models"].items():
        model = CatBoostClassifier()
        model.load_model(PROJECT_ROOT / contract["path"])
        if int(model.tree_count_) != int(contract["tree_count"]):
            raise RuntimeError(f"{name} tree count changed")
        if len(model.feature_names_) != int(contract["feature_count"]):
            raise RuntimeError(f"{name} feature count changed")
        models[name] = model

    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    contexts = pd.read_csv(CONTEXTS_PATH, dtype={"query_id": str})
    targets = pd.read_csv(
        TARGETS_PATH, dtype={"query_id": str, "disease_group_id": str}
    )
    catalog = pd.read_csv(CATALOG_PATH, dtype={"disease_group_id": str})
    train_ids = pd.read_csv(TRAIN_IDS_PATH, dtype={"query_id": str})["query_id"].tolist()
    test_ids = pd.read_csv(TEST_IDS_PATH, dtype={"query_id": str})["query_id"].tolist()
    if set(train_ids) & set(test_ids):
        raise RuntimeError("TRAIN and TEST query IDs overlap")
    indexed_contexts = contexts.set_index("query_id", drop=False)
    if not set(train_ids + test_ids).issubset(indexed_contexts.index):
        raise RuntimeError("Some TRAIN/TEST query IDs are missing from contexts")

    train_targets = targets[targets["query_id"].isin(set(train_ids))]
    support_mask = (
        train_targets[["has_case_h3", "has_case_h7", "has_case_h14"]].max(axis=1) > 0
    )
    disease_ids = metric_contract.sorted_disease_ids(
        set(train_targets.loc[support_mask, "disease_group_id"].astype(str))
    )
    if len(disease_ids) != 221:
        raise RuntimeError(f"Unexpected TRAIN-supported disease count: {len(disease_ids)}")

    weather_features = list(metadata["model_feature_columns"])
    control_features = list(config["no_weather_features"])
    if weather_features != list(models["with_weather"].feature_names_):
        raise RuntimeError("WITH WEATHER TEST schema/order differs from locked model")
    if control_features != list(models["no_weather"].feature_names_):
        raise RuntimeError("NO WEATHER TEST schema/order differs from locked model")
    test_weather = prepare_features(
        indexed_contexts,
        test_ids,
        weather_features,
        config["categorical_features"],
    )
    test_control = prepare_features(
        indexed_contexts,
        test_ids,
        control_features,
        config["categorical_features"],
    )
    test_target = build_target_matrix(test_ids, disease_ids, targets)
    if test_target.shape != (len(test_ids), len(disease_ids)):
        raise RuntimeError("TEST target shape mismatch")

    pools = {
        "with_weather": Pool(
            test_weather, cat_features=config["categorical_features"]
        ),
        "no_weather": Pool(
            test_control, cat_features=config["categorical_features"]
        ),
    }
    model_results: dict[str, dict[str, Any]] = {}
    orders: dict[str, np.ndarray] = {}
    per_query: dict[str, pd.DataFrame] = {}
    scores_by_model: dict[str, np.ndarray] = {}
    for name in ("with_weather", "no_weather"):
        started = time.perf_counter()
        scores = np.asarray(models[name].predict_proba(pools[name]), dtype=np.float64)
        elapsed = time.perf_counter() - started
        if scores.shape != test_target.shape:
            raise RuntimeError(f"{name} prediction shape {scores.shape} != {test_target.shape}")
        order = np.argsort(-scores, axis=1, kind="stable")
        metrics, query_metrics = summarize_order(test_ids, order, test_target)
        model_results[name] = {
            "run_name": name,
            "status": "success",
            "prediction_seconds": elapsed,
            "feature_count": pools[name].num_col(),
            **metrics,
        }
        orders[name] = order
        per_query[name] = query_metrics
        scores_by_model[name] = scores
        log(f"Predicted TEST once for {name}; rows={len(test_ids)}, seconds={elapsed:.4f}")

    baseline = FrequencyRankingBaseline.fit_train(
        contexts[contexts["query_id"].isin(set(train_ids))].copy(),
        train_targets.copy(),
        disease_ids,
        3,
        split_name="train",
    )
    disease_index = {disease_id: index for index, disease_id in enumerate(disease_ids)}
    baseline_order = np.empty((len(test_ids), len(disease_ids)), dtype=np.int32)
    test_contexts = indexed_contexts.loc[test_ids]
    for row_index, (_, context) in enumerate(test_contexts.iterrows()):
        baseline_order[row_index] = [
            disease_index[disease_id] for disease_id in baseline.rank(context)
        ]
    baseline_metrics, baseline_per_query = summarize_order(
        test_ids, baseline_order, test_target
    )
    baseline_result = {
        "run_name": "baseline",
        "status": "success",
        "prediction_seconds": 0.0,
        "feature_count": 3,
        **baseline_metrics,
    }

    comparison_rows = []
    for key in METRIC_KEYS:
        weather_value = float(model_results["with_weather"][key])
        control_value = float(model_results["no_weather"][key])
        baseline_value = float(baseline_result[key])
        comparison_rows.append(
            {
                "metric": key,
                "with_weather": weather_value,
                "no_weather": control_value,
                "baseline": baseline_value,
                "weather_minus_no_weather": weather_value - control_value,
                "weather_minus_baseline": weather_value - baseline_value,
                "no_weather_minus_baseline": control_value - baseline_value,
            }
        )
    comparison = pd.DataFrame(comparison_rows)
    bootstrap = bootstrap_summary(
        per_query["with_weather"],
        per_query["no_weather"],
        baseline_per_query,
        int(config["bootstrap_repetitions"]),
        int(config["random_seed"]),
    )
    decision, reason = decide_final(
        config,
        model_results["with_weather"],
        model_results["no_weather"],
        baseline_result,
    )

    catalog_names = dict(
        zip(
            catalog["disease_group_id"].astype(str),
            catalog["disease_group_name"].fillna("").astype(str),
        )
    )
    prediction_rows = write_predictions(
        test_ids,
        indexed_contexts,
        disease_ids,
        catalog_names,
        test_target,
        scores_by_model["with_weather"],
        scores_by_model["no_weather"],
    )

    test_dates = pd.to_datetime(indexed_contexts.loc[test_ids, "anchor_date"])
    test_positive_counts = test_target.sum(axis=1)
    unsupported_positive = targets.loc[
        (targets["query_id"].isin(set(test_ids)))
        & (targets["has_case_h3"] == 1)
        & (~targets["disease_group_id"].isin(set(disease_ids))),
        ["query_id", "disease_group_id"],
    ].drop_duplicates()
    data_summary = {
        "test_query_count": len(test_ids),
        "test_date_start": str(test_dates.min().date()),
        "test_date_end": str(test_dates.max().date()),
        "disease_count": len(disease_ids),
        "target_shape": f"{len(test_ids)}x{len(disease_ids)}",
        "mean_positive_diseases": float(test_positive_counts.mean()),
        "median_positive_diseases": float(np.median(test_positive_counts)),
        "zero_positive_queries": int((test_positive_counts == 0).sum()),
        "unsupported_positive_pairs": int(len(unsupported_positive)),
        "prediction_rows": prediction_rows,
    }

    metrics_frame = pd.DataFrame(
        [model_results["with_weather"], model_results["no_weather"], baseline_result]
    )
    metrics_frame.to_csv(METRICS_DIR / "test_metrics.csv", index=False)
    comparison.to_csv(METRICS_DIR / "test_comparison.csv", index=False)
    bootstrap.to_csv(METRICS_DIR / "bootstrap_summary.csv", index=False)

    result_row: dict[str, Any] = {**data_summary, "final_conclusion": decision}
    for prefix, row in (
        ("with_weather", model_results["with_weather"]),
        ("no_weather", model_results["no_weather"]),
        ("baseline", baseline_result),
    ):
        for key in METRIC_KEYS:
            result_row[f"{prefix}_{key}"] = row[key]
    for row in comparison.itertuples(index=False):
        result_row[f"weather_minus_no_weather_{row.metric}"] = row.weather_minus_no_weather
        result_row[f"weather_minus_baseline_{row.metric}"] = row.weather_minus_baseline
    pd.DataFrame([result_row]).to_csv(RESULTS_PATH, index=False)

    locked_after = verify_locked(config)
    model_hashes_after = {
        name: metric_contract.sha256_file(PROJECT_ROOT / contract["path"])
        for name, contract in config["expected_models"].items()
    }
    integrity_pass = (
        locked_before == locked_after and model_hashes_before == model_hashes_after
    )
    if not integrity_pass:
        raise RuntimeError("Locked checksum changed during FINAL TEST")
    write_report(
        config,
        data_summary,
        model_results["with_weather"],
        model_results["no_weather"],
        baseline_result,
        comparison,
        bootstrap,
        decision,
        reason,
        integrity_pass,
        model_hashes_after,
    )
    summary = {
        "decision": decision,
        "test_query_count": len(test_ids),
        "evaluated_queries": model_results["with_weather"]["evaluated_test_queries"],
        "integrity_pass": integrity_pass,
        "models_retrained": False,
        "h7_h14_tested": False,
        "report": str(REPORT_PATH),
    }
    log(json.dumps(summary, ensure_ascii=True))
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
