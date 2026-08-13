"""Paired query-level bootstrap of LightGBM weather gain on VALIDATION only.

This analysis consumes saved score matrices. It does not import LightGBM,
load a model, perform inference, or train any estimator.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


BOOTSTRAP_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = BOOTSTRAP_DIR.parent
PROJECT_ROOT = BENCHMARK_DIR.parents[1]
CONFIG_PATH = BOOTSTRAP_DIR / "bootstrap_config.json"
SUMMARY_PATH = BOOTSTRAP_DIR / "bootstrap_summary.csv"
REPORT_PATH = BOOTSTRAP_DIR / "BOOTSTRAP_REPORT.md"
TARGETS_PATH = PROJECT_ROOT / "data/processed/targets.csv.gz"
VALIDATION_IDS_PATH = PROJECT_ROOT / "data/splits/validation_query_ids.csv"

METRICS = (
    "precision_at_5",
    "recall_at_5",
    "ndcg_at_5",
    "precision_at_10",
    "recall_at_10",
    "ndcg_at_10",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_locked_files(config: dict[str, Any]) -> dict[str, str]:
    actual: dict[str, str] = {}
    for relative, expected in config["locked_files_sha256"].items():
        path = PROJECT_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing locked input: {relative}")
        checksum = sha256_file(path)
        actual[relative] = checksum
        if checksum != expected:
            raise RuntimeError(
                f"Locked input changed: {relative}; expected={expected}, actual={checksum}"
            )
    return actual


def ordered_id_sha256(query_ids: list[str]) -> str:
    return hashlib.sha256(("\n".join(query_ids) + "\n").encode("utf-8")).hexdigest()


def sorted_disease_ids(values: set[str]) -> list[str]:
    def key(value: str) -> tuple[int, int | str]:
        return (0, int(value)) if value.isdigit() else (1, value)

    return sorted(values, key=key)


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


def per_query_metrics(scores: np.ndarray, target: np.ndarray) -> dict[str, np.ndarray]:
    """Return the exact V3 metric contributions, with zero-positive rows as NaN."""
    if scores.shape != target.shape:
        raise RuntimeError(f"Score shape {scores.shape} != target shape {target.shape}")
    order = np.argsort(-scores, axis=1, kind="stable")
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


def aggregate(contributions: dict[str, np.ndarray]) -> dict[str, float]:
    return {metric: float(np.nanmean(contributions[metric])) for metric in METRICS}


def load_and_validate_horizon(
    horizon: int,
    query_ids: list[str],
    targets: pd.DataFrame,
    config: dict[str, Any],
) -> dict[str, Any]:
    matrices: dict[str, np.ndarray] = {}
    disease_orders: dict[str, list[str]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for variant in ("with_weather", "no_weather"):
        run_dir = BENCHMARK_DIR / "artifacts" / f"h{horizon}_{variant}"
        with np.load(run_dir / "validation_scores.npz", allow_pickle=False) as artifact:
            if set(artifact.files) != {"scores", "disease_ids"}:
                raise RuntimeError(
                    f"Unexpected score artifact keys for H{horizon} {variant}: {artifact.files}"
                )
            matrices[variant] = artifact["scores"].copy()
            disease_orders[variant] = [str(value) for value in artifact["disease_ids"]]
        metadata[variant] = json.loads(
            (run_dir / "run_metadata.json").read_text(encoding="utf-8")
        )

    if disease_orders["with_weather"] != disease_orders["no_weather"]:
        raise RuntimeError(f"H{horizon}: WITH/NO disease order mismatch")
    disease_ids = disease_orders["with_weather"]
    expected_shape = (len(query_ids), len(disease_ids))
    for variant in ("with_weather", "no_weather"):
        if matrices[variant].shape != expected_shape:
            raise RuntimeError(
                f"H{horizon} {variant}: {matrices[variant].shape} != {expected_shape}"
            )
        if int(metadata[variant]["validation_query_count"]) != len(query_ids):
            raise RuntimeError(f"H{horizon} {variant}: validation count mismatch")
        if int(metadata[variant]["disease_count"]) != len(disease_ids):
            raise RuntimeError(f"H{horizon} {variant}: disease count mismatch")
        if int(metadata[variant]["horizon"]) != horizon:
            raise RuntimeError(f"H{horizon} {variant}: metadata horizon mismatch")

    if len(disease_ids) != int(config["expected_disease_count"]):
        raise RuntimeError(f"H{horizon}: unexpected disease count {len(disease_ids)}")
    if len(disease_ids) != len(set(disease_ids)):
        raise RuntimeError(f"H{horizon}: duplicate disease IDs")
    target = build_target_matrix(query_ids, disease_ids, targets, horizon)
    if target.shape != expected_shape:
        raise RuntimeError(f"H{horizon}: target shape mismatch")

    contributions = {
        variant: per_query_metrics(matrices[variant], target)
        for variant in ("with_weather", "no_weather")
    }
    observed = {variant: aggregate(contributions[variant]) for variant in contributions}
    metrics_frame = pd.read_csv(BENCHMARK_DIR / "metrics" / f"h{horizon}_metrics.csv")
    tolerance = float(config["metric_tolerance"])
    for variant in ("with_weather", "no_weather"):
        expected_row = metrics_frame.loc[
            metrics_frame["run_name"] == f"h{horizon}_{variant}"
        ]
        if len(expected_row) != 1:
            raise RuntimeError(f"H{horizon} {variant}: benchmark metric row missing/duplicate")
        row = expected_row.iloc[0]
        for metric in METRICS:
            if not math.isclose(
                observed[variant][metric], float(row[metric]), rel_tol=0.0, abs_tol=tolerance
            ):
                raise RuntimeError(
                    f"H{horizon} {variant} {metric} does not reproduce benchmark: "
                    f"{observed[variant][metric]} != {row[metric]}"
                )

    reference_tolerance = float(config["rounded_reference_tolerance"])
    references = config["observed_ndcg_gain_references"][f"H{horizon}"]
    for metric in ("ndcg_at_5", "ndcg_at_10"):
        gain = observed["with_weather"][metric] - observed["no_weather"][metric]
        if not math.isclose(
            gain, float(references[metric]), rel_tol=0.0, abs_tol=reference_tolerance
        ):
            raise RuntimeError(
                f"H{horizon} observed {metric} gain mismatch: {gain} != {references[metric]}"
            )

    return {
        "disease_ids": disease_ids,
        "target": target,
        "contributions": contributions,
        "observed": observed,
        "zero_positive_queries": int((target.sum(axis=1) == 0).sum()),
    }


def paired_bootstrap(
    horizon: int,
    validated: dict[str, Any],
    config: dict[str, Any],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    n_query = validated["target"].shape[0]
    n_bootstrap = int(config["n_bootstrap"])
    rng = np.random.default_rng(int(config["random_seed"]))
    valid = ~np.isnan(validated["contributions"]["with_weather"][METRICS[0]])
    differences = {
        metric: np.nan_to_num(
            validated["contributions"]["with_weather"][metric]
            - validated["contributions"]["no_weather"][metric],
            nan=0.0,
        )
        for metric in METRICS
    }
    gains = {metric: np.empty(n_bootstrap, dtype=np.float64) for metric in METRICS}
    evaluated_draws = np.empty(n_bootstrap, dtype=np.int64)
    batch_size = 250
    for start in range(0, n_bootstrap, batch_size):
        stop = min(start + batch_size, n_bootstrap)
        indices = rng.integers(0, n_query, size=(stop - start, n_query))
        denominator = valid[indices].sum(axis=1)
        if np.any(denominator == 0):
            raise RuntimeError(f"H{horizon}: bootstrap sample has no positive-target query")
        evaluated_draws[start:stop] = denominator
        for metric in METRICS:
            gains[metric][start:stop] = differences[metric][indices].sum(axis=1) / denominator

    detail = pd.DataFrame(
        {
            "bootstrap_iteration": np.arange(1, n_bootstrap + 1),
            "sampled_query_count": n_query,
            "evaluated_positive_query_draws": evaluated_draws,
            **{f"{metric}_gain": gains[metric] for metric in METRICS},
        }
    )
    summary_rows: list[dict[str, Any]] = []
    for metric in METRICS:
        values = gains[metric]
        observed_with = validated["observed"]["with_weather"][metric]
        observed_no = validated["observed"]["no_weather"][metric]
        lower, upper = np.percentile(values, [2.5, 97.5])
        decision = (
            "ROBUST_POSITIVE"
            if lower > 0
            else "ROBUST_NEGATIVE"
            if upper < 0
            else "UNCERTAIN"
        )
        summary_rows.append(
            {
                "horizon": f"H{horizon}",
                "metric": metric,
                "observed_with": observed_with,
                "observed_no_weather": observed_no,
                "observed_gain": observed_with - observed_no,
                "bootstrap_mean_gain": float(values.mean()),
                "bootstrap_median_gain": float(np.median(values)),
                "bootstrap_se": float(values.std(ddof=1)),
                "ci95_lower": float(lower),
                "ci95_upper": float(upper),
                "prob_gain_gt_zero": float((values > 0).mean()),
                "n_bootstrap": n_bootstrap,
                "decision": decision,
            }
        )
    return detail, summary_rows


def fmt(value: float, digits: int = 6, signed: bool = False) -> str:
    return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"


def result_table(summary: pd.DataFrame, metric: str) -> list[str]:
    rows = summary.loc[summary["metric"] == metric]
    lines = [
        "| Horizon | Observed gain | 95% CI | P(gain > 0) | Decision |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows.itertuples(index=False):
        lines.append(
            f"| {row.horizon} | {fmt(row.observed_gain, signed=True)} | "
            f"[{fmt(row.ci95_lower, signed=True)}, {fmt(row.ci95_upper, signed=True)}] | "
            f"{row.prob_gain_gt_zero:.4f} | {row.decision} |"
        )
    return lines


def write_report(
    summary: pd.DataFrame,
    validated: dict[int, dict[str, Any]],
    config: dict[str, Any],
    runtime_seconds: float,
    integrity_pass: bool,
) -> None:
    ndcg5 = summary.loc[summary["metric"] == "ndcg_at_5"].sort_values(
        ["ci95_lower", "observed_gain"], ascending=False
    )
    strongest = str(ndcg5.iloc[0]["horizon"])
    robust5 = summary.loc[
        (summary["metric"] == "ndcg_at_5")
        & (summary["decision"] == "ROBUST_POSITIVE"),
        "horizon",
    ].tolist()
    robust10 = summary.loc[
        (summary["metric"] == "ndcg_at_10")
        & (summary["decision"] == "ROBUST_POSITIVE"),
        "horizon",
    ].tolist()
    lines = [
        "# Paired Bootstrap Report: LightGBM Weather Gain",
        "",
        "## 1. Method",
        "",
        f"Paired percentile bootstrap ở query level, {config['n_bootstrap']:,} lần, seed={config['random_seed']}. "
        "Mỗi lần dùng cùng indices cho WITH WEATHER, NO WEATHER và target.",
        "",
        "## 2. Validation dataset",
        "",
        f"- Validation queries: {config['expected_validation_query_count']:,}.",
        f"- Disease order: {config['expected_disease_count']} nhóm, WITH/NO giống nhau.",
        "- Zero-positive query được loại khỏi trung bình đúng như metric contract V3.",
        "",
        "## 3. Paired bootstrap design",
        "",
        "Score được chuyển thành đóng góp metric theo từng query bằng stable descending rank. "
        "Bootstrap lấy trung bình paired difference trực tiếp; không trừ hai confidence interval độc lập.",
    ]
    for horizon in (3, 7, 14):
        section_number = {3: 4, 7: 5, 14: 6}[horizon]
        lines.extend(["", f"## {section_number}. H{horizon} results", ""])
        rows = summary.loc[summary["horizon"] == f"H{horizon}"]
        lines.extend(
            [
                "| Metric | Observed gain | Bootstrap mean | Median | SE | 95% CI | P(gain > 0) | Decision |",
                "|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in rows.itertuples(index=False):
            lines.append(
                f"| {row.metric} | {fmt(row.observed_gain, signed=True)} | "
                f"{fmt(row.bootstrap_mean_gain, signed=True)} | {fmt(row.bootstrap_median_gain, signed=True)} | "
                f"{row.bootstrap_se:.6f} | [{fmt(row.ci95_lower, signed=True)}, "
                f"{fmt(row.ci95_upper, signed=True)}] | {row.prob_gain_gt_zero:.4f} | {row.decision} |"
            )
        lines.append(
            f"Zero-positive validation queries: {validated[horizon]['zero_positive_queries']}."
        )
    lines.extend(["", "## 7. NDCG@5 comparison", "", *result_table(summary, "ndcg_at_5")])
    lines.extend(["", "## 8. NDCG@10 comparison", "", *result_table(summary, "ndcg_at_10")])
    lines.extend(
        [
            "",
            "## 9. Precision/Recall results",
            "",
        ]
    )
    for metric in ("precision_at_5", "recall_at_5", "precision_at_10", "recall_at_10"):
        lines.extend([f"### {metric}", "", *result_table(summary, metric), ""])
    lines.extend(
        [
            "## 10. Weather contribution conclusion",
            "",
            f"**{strongest}_HAS_STRONGEST_VALIDATION_WEATHER_SIGNAL** theo CI lower bound NDCG@5, "
            "sau đó observed gain và xác nhận NDCG@10.",
            "",
            f"- NDCG@5 robust positive: {', '.join(robust5) if robust5 else 'không có'}.",
            f"- NDCG@10 robust positive: {', '.join(robust10) if robust10 else 'không có'}.",
            "- Đây là đóng góp dự báo/thống kê trên VALIDATION, không phải bằng chứng nhân quả và không phải kết luận TEST.",
            f"- Runtime bootstrap + validation: {runtime_seconds:.3f} giây.",
            "",
            "## 11. Integrity",
            "",
            f"- Locked input/artifact checksum: **{'PASS' if integrity_pass else 'FAIL'}**.",
            "- Không train lại TRAIN, LightGBM hay CatBoost; không load model và không inference lại.",
            "- TEST không được load, predict hay đọc metric; phân tích chỉ dùng VALIDATION.",
            "- WITH/NO paired bằng cùng query indices; seed=42.",
            "- Sáu score matrix tái tạo chính xác benchmark metrics trước bootstrap.",
            "- Query order được khóa bởi validation ID order, benchmark source hash và exact metric reproduction.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    started = time.perf_counter()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    locked_before = verify_locked_files(config)
    query_ids = pd.read_csv(VALIDATION_IDS_PATH, dtype={"query_id": str})[
        "query_id"
    ].tolist()
    if len(query_ids) != int(config["expected_validation_query_count"]):
        raise RuntimeError(f"Unexpected validation query count: {len(query_ids)}")
    if len(query_ids) != len(set(query_ids)):
        raise RuntimeError("Validation query IDs are not unique")
    query_order_hash = ordered_id_sha256(query_ids)
    if query_order_hash != config["validation_query_order_sha256"]:
        raise RuntimeError(
            f"Validation query order changed: {query_order_hash} != "
            f"{config['validation_query_order_sha256']}"
        )
    targets = pd.read_csv(
        TARGETS_PATH, dtype={"query_id": str, "disease_group_id": str}
    )

    # Complete all alignment/reproduction gates before producing bootstrap outputs.
    validated = {
        horizon: load_and_validate_horizon(horizon, query_ids, targets, config)
        for horizon in config["horizons"]
    }
    canonical_order = validated[3]["disease_ids"]
    for horizon in config["horizons"]:
        if validated[horizon]["disease_ids"] != canonical_order:
            raise RuntimeError(f"H{horizon}: cross-horizon disease order mismatch")

    summary_rows: list[dict[str, Any]] = []
    details: dict[int, pd.DataFrame] = {}
    for horizon in config["horizons"]:
        detail, rows = paired_bootstrap(horizon, validated[horizon], config)
        details[horizon] = detail
        summary_rows.extend(rows)

    locked_after = verify_locked_files(config)
    integrity_pass = locked_before == locked_after
    if not integrity_pass:
        raise RuntimeError("Locked files changed during bootstrap")
    summary = pd.DataFrame(summary_rows)
    runtime_seconds = time.perf_counter() - started

    # Write only after every validation, bootstrap and integrity gate has passed.
    for horizon, detail in details.items():
        detail.to_csv(BOOTSTRAP_DIR / f"h{horizon}_bootstrap.csv", index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    write_report(summary, validated, config, runtime_seconds, integrity_pass)
    print(
        json.dumps(
            {
                "status": "success",
                "n_bootstrap": config["n_bootstrap"],
                "runtime_seconds": runtime_seconds,
                "report": str(REPORT_PATH),
                "integrity_pass": integrity_pass,
                "test_used": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
