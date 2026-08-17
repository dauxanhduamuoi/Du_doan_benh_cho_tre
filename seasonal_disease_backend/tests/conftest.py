from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.services.weather_ai_service import get_model_registry, get_runtime_service


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V3_ROOT = REPOSITORY_ROOT / "weather_disease_ai_v3"


@pytest.fixture(scope="session")
def registry():
    value = get_model_registry()
    value.load()
    return value


@pytest.fixture(scope="session")
def runtime_service():
    return get_runtime_service()


@pytest.fixture(scope="session")
def train_context(registry):
    # A TRAIN context only; no TEST ID and no target file is read.
    train_ids = pd.read_csv(V3_ROOT / "data/splits/train_query_ids.csv", dtype=str)
    query_id = str(train_ids.iloc[0, 0])
    contexts = pd.read_csv(
        V3_ROOT / "data/processed/contexts.csv.gz", dtype={"query_id": str}
    )
    row = contexts.loc[contexts["query_id"] == query_id].iloc[0]
    weather = {feature: row[feature] for feature in registry.feature_order[6:]}
    return {
        "query_id": query_id,
        "row": row,
        "age_group": str(row["age_group"]),
        "gender": str(row["gender"]),
        "target_date": pd.Timestamp(row["anchor_date"]).date(),
        "weather": weather,
    }
