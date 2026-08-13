"""Ranking, probability, F1, and per-class evaluation utilities."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def expand_probabilities(
    probabilities: np.ndarray,
    model_classes: list[str],
    universe_classes: list[str],
) -> np.ndarray:
    expanded = np.zeros((len(probabilities), len(universe_classes)), dtype=np.float64)
    universe_index = {label: index for index, label in enumerate(universe_classes)}
    for source_index, label in enumerate(model_classes):
        expanded[:, universe_index[str(label)]] = probabilities[:, source_index]
    return expanded


def top_k_indices(probabilities: np.ndarray, k: int) -> np.ndarray:
    effective_k = min(int(k), probabilities.shape[1])
    partition = np.argpartition(-probabilities, effective_k - 1, axis=1)[:, :effective_k]
    values = np.take_along_axis(probabilities, partition, axis=1)
    order = np.argsort(-values, axis=1, kind="stable")
    return np.take_along_axis(partition, order, axis=1)


def top_k_predictions(
    probabilities: np.ndarray,
    classes: list[str],
    catalog_lookup: dict[str, dict[str, Any]],
    k: int,
) -> list[list[dict[str, Any]]]:
    indices = top_k_indices(probabilities, k)
    output: list[list[dict[str, Any]]] = []
    for row_number, row_indices in enumerate(indices):
        rows = []
        for class_index in row_indices:
            label = str(classes[int(class_index)])
            catalog = catalog_lookup.get(label, {})
            rows.append(
                {
                    "disease_group_id": label,
                    "disease_group_name": str(catalog.get("disease_group_name", "")),
                    "score": float(probabilities[row_number, int(class_index)]),
                }
            )
        output.append(rows)
    return output


def _weighted_mean(values: np.ndarray, weights: np.ndarray | None) -> float:
    if weights is None:
        return float(np.mean(values))
    return float(np.average(values, weights=weights))


def _f1_metrics(
    true_indices: np.ndarray,
    predicted_indices: np.ndarray,
    weights: np.ndarray | None,
) -> tuple[float, float]:
    effective_weights = (
        np.ones(len(true_indices), dtype=np.float64)
        if weights is None
        else weights.astype(np.float64)
    )
    labels = np.union1d(true_indices, predicted_indices)
    f1_values = []
    supports = []
    for label in labels:
        true_mask = true_indices == label
        predicted_mask = predicted_indices == label
        true_positive = effective_weights[true_mask & predicted_mask].sum()
        false_positive = effective_weights[~true_mask & predicted_mask].sum()
        false_negative = effective_weights[true_mask & ~predicted_mask].sum()
        denominator = 2 * true_positive + false_positive + false_negative
        f1_values.append(float(2 * true_positive / denominator) if denominator else 0.0)
        supports.append(float(effective_weights[true_mask].sum()))
    macro = float(np.mean(f1_values)) if f1_values else 0.0
    weighted = float(np.average(f1_values, weights=supports)) if sum(supports) else 0.0
    return macro, weighted


def metric_version(
    y_true: pd.Series,
    probabilities: np.ndarray,
    classes: list[str],
    sample_weight: pd.Series | None,
) -> dict[str, float]:
    class_index = {label: index for index, label in enumerate(classes)}
    true_indices = np.array([class_index[str(label)] for label in y_true], dtype=np.int64)
    weights = None if sample_weight is None else sample_weight.to_numpy(dtype=np.float64)
    ranking = top_k_indices(probabilities, min(10, len(classes)))
    metrics: dict[str, float] = {}
    for k in (1, 3, 5, 10):
        effective_k = min(k, ranking.shape[1])
        hits = (ranking[:, :effective_k] == true_indices[:, None]).any(axis=1).astype(float)
        metrics[f"top_{k}_accuracy"] = _weighted_mean(hits, weights)

    true_probability = probabilities[np.arange(len(probabilities)), true_indices]
    losses = -np.log(np.clip(true_probability, 1e-15, 1.0))
    metrics["multiclass_log_loss"] = _weighted_mean(losses, weights)
    predicted_indices = ranking[:, 0]
    macro_f1, weighted_f1 = _f1_metrics(true_indices, predicted_indices, weights)
    metrics["macro_f1"] = macro_f1
    metrics["weighted_f1"] = weighted_f1
    return metrics


def compute_metrics(
    y_true: pd.Series,
    probabilities: np.ndarray,
    classes: list[str],
    case_count: pd.Series,
) -> dict[str, dict[str, float]]:
    return {
        "unweighted": metric_version(y_true, probabilities, classes, None),
        "case_weighted": metric_version(y_true, probabilities, classes, case_count),
    }


def per_class_metrics(
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    probabilities: np.ndarray,
    classes: list[str],
    catalog: pd.DataFrame,
    split_name: str,
) -> pd.DataFrame:
    class_index = {label: index for index, label in enumerate(classes)}
    true_indices = np.array(
        [class_index[str(label)] for label in evaluation["disease_group_id"]], dtype=np.int64
    )
    ranking = top_k_indices(probabilities, min(5, len(classes)))
    weights = evaluation["case_count"].to_numpy(dtype=float)

    train_rows = train.groupby("disease_group_id").size()
    train_cases = train.groupby("disease_group_id")["case_count"].sum()
    eval_rows = evaluation.groupby("disease_group_id").size()
    eval_cases = evaluation.groupby("disease_group_id")["case_count"].sum()
    train_classes = set(train["disease_group_id"].astype(str))
    # The source workbook can contain more than one descriptive row for the
    # same disease-group id. Metrics are keyed by model class, so choose the
    # first catalog row deterministically without modifying the source file.
    catalog_lookup = (
        catalog.drop_duplicates("disease_group_id", keep="first")
        .set_index("disease_group_id")
        .to_dict("index")
    )

    records = []
    for label in classes:
        label_index = class_index[label]
        mask = true_indices == label_index
        support_weight = float(weights[mask].sum())
        recall_top_1 = (
            float(np.average(ranking[mask, 0] == label_index, weights=weights[mask]))
            if support_weight
            else np.nan
        )
        recall_top_5 = (
            float(
                np.average(
                    (ranking[mask, :5] == label_index).any(axis=1), weights=weights[mask]
                )
            )
            if support_weight
            else np.nan
        )
        details = catalog_lookup.get(label, {})
        records.append(
            {
                "disease_group_id": label,
                "disease_group_name": details.get("disease_group_name", ""),
                "report_group_code": details.get("report_group_code", ""),
                "support_level": details.get("support_level", ""),
                "model_supported": label in train_classes,
                "train_support_rows": int(train_rows.get(label, 0)),
                "train_support_case_count": int(train_cases.get(label, 0)),
                f"{split_name}_support_rows": int(eval_rows.get(label, 0)),
                f"{split_name}_support_case_count": int(eval_cases.get(label, 0)),
                f"{split_name}_recall_top_1": recall_top_1,
                f"{split_name}_recall_top_5": recall_top_5,
            }
        )
    return pd.DataFrame(records)
