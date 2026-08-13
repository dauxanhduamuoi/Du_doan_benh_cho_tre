"""Multi-label ranking metrics shared by future H3/H7/H14 experiments."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

import pandas as pd


def recall_at_k(positive_ids: Iterable[str], ranking: Iterable[str], k: int) -> float:
    positives = {str(value) for value in positive_ids}
    if not positives:
        return float("nan")
    predicted = {str(value) for value in list(ranking)[: int(k)]}
    return len(positives & predicted) / len(positives)


def ndcg_at_k(positive_ids: Iterable[str], ranking: Iterable[str], k: int) -> float:
    positives = {str(value) for value in positive_ids}
    if not positives:
        return float("nan")
    ranked = [str(value) for value in list(ranking)[: int(k)]]
    dcg = sum(
        1.0 / math.log2(position + 2)
        for position, label in enumerate(ranked)
        if label in positives
    )
    ideal_hits = min(len(positives), int(k))
    ideal = sum(1.0 / math.log2(position + 2) for position in range(ideal_hits))
    return dcg / ideal if ideal else float("nan")


def reciprocal_rank(positive_ids: Iterable[str], ranking: Iterable[str]) -> float:
    positives = {str(value) for value in positive_ids}
    if not positives:
        return float("nan")
    for position, label in enumerate(ranking, start=1):
        if str(label) in positives:
            return 1.0 / position
    return 0.0


def evaluate_rankings(
    positives_by_query: Mapping[str, Iterable[str]],
    rankings_by_query: Mapping[str, Iterable[str]],
) -> tuple[pd.DataFrame, dict[str, float]]:
    records = []
    for query_id, positives in positives_by_query.items():
        ranking = list(rankings_by_query.get(query_id, []))
        positive_list = list(positives)
        if not positive_list:
            continue
        records.append(
            {
                "query_id": query_id,
                "positive_count": len(set(positive_list)),
                "recall_at_5": recall_at_k(positive_list, ranking, 5),
                "recall_at_10": recall_at_k(positive_list, ranking, 10),
                "ndcg_at_5": ndcg_at_k(positive_list, ranking, 5),
                "ndcg_at_10": ndcg_at_k(positive_list, ranking, 10),
                "mrr": reciprocal_rank(positive_list, ranking),
            }
        )
    per_query = pd.DataFrame(records)
    metric_columns = ["recall_at_5", "recall_at_10", "ndcg_at_5", "ndcg_at_10", "mrr"]
    summary = {
        column: float(per_query[column].mean()) if not per_query.empty else float("nan")
        for column in metric_columns
    }
    summary["evaluated_queries"] = int(len(per_query))
    return per_query, summary
