"""Hierarchical frequency baseline for Top-K disease-group ranking."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FrequencyBaseline:
    classes: list[str]
    hierarchy: list[tuple[str, ...]]
    tables: list[dict[tuple[object, ...], np.ndarray]]
    global_probabilities: np.ndarray

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        output = np.zeros((len(frame), len(self.classes)), dtype=np.float64)
        for row_index, row in enumerate(frame.itertuples(index=False)):
            row_values = row._asdict()
            selected = None
            for keys, table in zip(self.hierarchy, self.tables):
                key = tuple(row_values[column] for column in keys)
                selected = table.get(key)
                if selected is not None:
                    break
            output[row_index] = (
                selected if selected is not None else self.global_probabilities
            )
        return output


def _probability_vector(
    grouped: pd.Series, classes: list[str], supported: set[str]
) -> np.ndarray:
    vector = np.zeros(len(classes), dtype=np.float64)
    index = {label: position for position, label in enumerate(classes)}
    for label, value in grouped.items():
        vector[index[str(label)]] = float(value)
    for label in supported:
        vector[index[label]] += 1e-12
    return vector / vector.sum()


def fit_frequency_baseline(train: pd.DataFrame, classes: list[str]) -> FrequencyBaseline:
    hierarchy = [
        ("age_group", "gender", "month"),
        ("age_group", "month"),
        ("month",),
    ]
    supported = set(train["disease_group_id"].astype(str))
    tables: list[dict[tuple[object, ...], np.ndarray]] = []
    for keys in hierarchy:
        grouped = (
            train.groupby([*keys, "disease_group_id"], dropna=False)["case_count"]
            .sum()
            .reset_index()
        )
        table: dict[tuple[object, ...], np.ndarray] = {}
        for key_values, subset in grouped.groupby(list(keys), dropna=False):
            key_tuple = key_values if isinstance(key_values, tuple) else (key_values,)
            counts = subset.set_index("disease_group_id")["case_count"]
            table[key_tuple] = _probability_vector(counts, classes, supported)
        tables.append(table)

    global_counts = train.groupby("disease_group_id")["case_count"].sum()
    global_probabilities = _probability_vector(global_counts, classes, supported)
    return FrequencyBaseline(classes, hierarchy, tables, global_probabilities)
