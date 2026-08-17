from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.weather_ai import router


def _all_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [*value.keys(), *(key for child in value.values() for key in _all_keys(child))]
    if isinstance(value, list):
        return [key for child in value for key in _all_keys(child)]
    return []


def test_13_14_api_contract_has_no_probability_semantics_and_keeps_existing_route(
    train_context,
):
    app = FastAPI()
    app.include_router(router)
    prediction_route = next(
        route for route in router.routes if getattr(route, "path", None) == "/api/weather-ai/predict-risk"
    )
    for dependency in prediction_route.dependant.dependencies:
        app.dependency_overrides[dependency.call] = lambda: object()

    payload = {
        "age_group": train_context["age_group"],
        "gender": train_context["gender"],
        "top_k": 3,
        "target_date": str(train_context["target_date"]),
        "weather": {key: float(value) for key, value in train_context["weather"].items()},
    }
    with TestClient(app) as client:
        response = client.post("/api/weather-ai/predict-risk", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["top_risks"] == body["predictions"]
    assert body["input"]["top_k"] == 3
    assert len(body["predictions"]) == 3
    assert body["context"]["ranking_universe"] == 221
    assert all("ranking_score" in item for item in body["predictions"])
    assert all(item["disease_id"] == item["disease_group_id"] for item in body["predictions"])
    forbidden = {
        key.lower()
        for key in _all_keys(body)
        if "probability" in key.lower() or "percent" in key.lower()
    }
    assert forbidden == set()
    assert "không thay thế chẩn đoán" in body["disclaimer"]
