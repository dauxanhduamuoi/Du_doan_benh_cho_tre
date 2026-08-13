"""Train-only hierarchical frequency baseline for multi-label disease ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


HIERARCHY = [
    ("age_group", "gender", "month"),
    ("age_group", "month"),
    ("month",),
]


@dataclass
class FrequencyRankingBaseline:
    """Rank diseases by positive case frequency learned from TRAIN queries only."""

    horizon: int
    disease_ids: list[str]
    hierarchy_tables: list[dict[tuple[Any, ...], dict[str, float]]]
    global_scores: dict[str, float]

    @classmethod
    def fit_train(
        cls,
        contexts: pd.DataFrame,
        targets: pd.DataFrame,
        disease_ids: list[str],
        horizon: int,
        *,
        split_name: str,
    ) -> "FrequencyRankingBaseline":
        if split_name != "train":
            raise ValueError("Baseline priors may only be built from the train split")
        if horizon not in {3, 7, 14}:
            raise ValueError(f"Unsupported horizon: {horizon}")
        weight_column = f"case_count_h{horizon}"
        required_context = {"query_id", "age_group", "gender", "month"}
        if not required_context.issubset(contexts.columns):
            raise ValueError(f"Missing context columns: {sorted(required_context - set(contexts))}")
        if weight_column not in targets.columns:
            raise ValueError(f"Missing target column: {weight_column}")

        positive = targets.loc[targets[weight_column] > 0, ["query_id", "disease_group_id", weight_column]]
        joined = positive.merge(
            contexts[["query_id", "age_group", "gender", "month"]],
            on="query_id",
            how="inner",
            validate="many_to_one",
        )
        tables: list[dict[tuple[Any, ...], dict[str, float]]] = []
        for keys in HIERARCHY:
            grouped = joined.groupby([*keys, "disease_group_id"], dropna=False)[weight_column].sum()
            table: dict[tuple[Any, ...], dict[str, float]] = {}
            levels: int | list[int] = 0 if len(keys) == 1 else list(range(len(keys)))
            for key_values, subset in grouped.groupby(level=levels):
                key = key_values if isinstance(key_values, tuple) else (key_values,)
                scores = subset.droplevel(list(range(len(keys)))).to_dict()
                table[key] = {str(label): float(value) for label, value in scores.items()}
            tables.append(table)
        global_grouped = joined.groupby("disease_group_id")[weight_column].sum()
        global_scores = {str(label): float(value) for label, value in global_grouped.items()}
        return cls(horizon, [str(value) for value in disease_ids], tables, global_scores)

    def rank(self, context: pd.Series | dict[str, Any], top_k: int | None = None) -> list[str]:
        values = context if isinstance(context, dict) else context.to_dict()
        scores: dict[str, float] | None = None
        for keys, table in zip(HIERARCHY, self.hierarchy_tables):
            key = tuple(values[column] for column in keys)
            if key in table:
                scores = table[key]
                break
        selected = self.global_scores if scores is None else scores
        ranked = sorted(
            self.disease_ids,
            key=lambda label: (-float(selected.get(label, 0.0)), label),
        )
        return ranked if top_k is None else ranked[: int(top_k)]
