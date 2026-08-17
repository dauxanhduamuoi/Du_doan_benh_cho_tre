from __future__ import annotations

import json
import urllib.parse
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import public as public_router_module
from app.routers.public import ParentRiskRequest, router as public_router
from app.services.weather_ai_explanations import MedicalKnowledgeService
from app.services.weather_ai_features import DEFAULT_TIMEZONE
from app.services.weather_ai_runtime import ModelRuntimeError
from app.services.weather_ai_service import WeatherAIRuntimeService
from app.weather_ai_schemas import WeatherAIPredictRequest


def _public_client() -> TestClient:
    app = FastAPI()
    app.include_router(public_router)
    return TestClient(app)


def _manual_payload(train_context: dict[str, Any], top_k: int = 5) -> dict[str, Any]:
    return {
        "age_group": train_context["age_group"],
        "gender": train_context["gender"],
        "top_k": top_k,
        "weather": {
            "anchor_date": str(train_context["target_date"]),
            **{key: float(value) for key, value in train_context["weather"].items()},
        },
    }


def test_application_timezone_convention_is_ho_chi_minh():
    assert DEFAULT_TIMEZONE == "Asia/Ho_Chi_Minh"
    assert WeatherAIPredictRequest.model_fields["timezone"].default == DEFAULT_TIMEZONE
    assert ParentRiskRequest.model_fields["timezone"].default == DEFAULT_TIMEZONE


def test_open_meteo_request_uses_explicit_application_timezone(
    runtime_service, monkeypatch
):
    timestamps = pd.date_range("2026-08-01", periods=7 * 24, freq="h")
    count = len(timestamps)
    hourly = {
        "time": timestamps.strftime("%Y-%m-%dT%H:%M").tolist(),
        "temperature_2m": [30.0] * count,
        "relative_humidity_2m": [75.0] * count,
        "precipitation": [0.0] * count,
        "rain": [0.0] * count,
        "weather_code": [1] * count,
        "wind_speed_10m": [8.0] * count,
        "wind_gusts_10m": [12.0] * count,
    }
    captured: dict[str, str] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"timezone": DEFAULT_TIMEZONE, "hourly": hourly}
            ).encode("utf-8")

    def _fake_urlopen(url: str, timeout: int):
        captured["url"] = url
        assert timeout == 15
        return _FakeResponse()

    monkeypatch.setattr(
        "app.services.weather_ai_features.urllib.request.urlopen", _fake_urlopen
    )
    values, anchor, meta = runtime_service.feature_builder._fetch_open_meteo(
        10.790861, 106.6313, DEFAULT_TIMEZONE, None
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
    assert query["timezone"] == ["Asia/Ho_Chi_Minh"]
    assert meta["timezone"] == "Asia/Ho_Chi_Minh"
    assert str(anchor) == "2026-08-07"
    assert len(values) == 39


def test_timezone_label_change_preserves_locked_features_and_ranking(
    registry, runtime_service, train_context
):
    prepared_hcm = runtime_service.feature_builder.prepare(
        train_context["age_group"],
        train_context["gender"],
        train_context["weather"],
        None,
        None,
        "Asia/Ho_Chi_Minh",
        train_context["target_date"],
    )
    prepared_bangkok = runtime_service.feature_builder.prepare(
        train_context["age_group"],
        train_context["gender"],
        train_context["weather"],
        None,
        None,
        "Asia/Bangkok",
        train_context["target_date"],
    )
    assert prepared_hcm.anchor_date == train_context["target_date"]
    assert prepared_hcm.encoded.shape == (1, 45)
    assert np.array_equal(
        prepared_hcm.encoded.to_numpy(), prepared_bangkok.encoded.to_numpy()
    )
    scores_hcm = registry.predict_scores(prepared_hcm.encoded)
    scores_bangkok = registry.predict_scores(prepared_bangkok.encoded)
    assert np.allclose(scores_hcm, scores_bangkok, rtol=0, atol=1e-12)
    assert np.array_equal(
        np.argsort(-scores_hcm, kind="stable")[:5],
        np.argsort(-scores_bangkok, kind="stable")[:5],
    )


def test_public_invalid_input_returns_422():
    with _public_client() as client:
        response = client.post(
            "/api/public/parent-risk",
            json={"age_group": "1-5 tuổi", "gender": "Nam", "top_k": 5},
        )
    assert response.status_code == 422


def test_public_model_unavailable_returns_503(monkeypatch):
    def _raise_model_error(**kwargs):
        raise ModelRuntimeError("model unavailable at D:\\private\\model")

    monkeypatch.setattr(public_router_module, "predict_weather_risk", _raise_model_error)
    with _public_client() as client:
        response = client.post(
            "/api/public/parent-risk",
            json={
                "age_group": "1-5 tuổi",
                "gender": "Nam",
                "weather": {"placeholder": 1},
            },
        )
    assert response.status_code == 503
    assert "D:\\private" not in response.text


def test_public_unexpected_runtime_error_returns_500(monkeypatch):
    def _raise_runtime_error(**kwargs):
        raise RuntimeError("unexpected at D:\\private\\runtime")

    monkeypatch.setattr(public_router_module, "predict_weather_risk", _raise_runtime_error)
    with _public_client() as client:
        response = client.post(
            "/api/public/parent-risk",
            json={
                "age_group": "1-5 tuổi",
                "gender": "Nam",
                "weather": {"placeholder": 1},
            },
        )
    assert response.status_code == 500
    assert response.json()["detail"] == "Weather AI runtime error."
    assert "D:\\private" not in response.text


def test_public_successful_prediction_contract_is_unchanged(train_context):
    with _public_client() as client:
        response = client.post(
            "/api/public/parent-risk", json=_manual_payload(train_context)
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["top_risks"] == body["predictions"]
    assert len(body["predictions"]) == 5
    assert [item["rank"] for item in body["predictions"]] == [1, 2, 3, 4, 5]
    assert len(body["weather"]["features"]) + 2 == 45
    assert body["context"]["ranking_universe"] == 221
    assert body["disclaimer"]


def test_public_medical_kb_unavailable_keeps_ranking_and_tier1(
    registry, train_context, tmp_path, monkeypatch
):
    service = WeatherAIRuntimeService(
        registry, MedicalKnowledgeService(tmp_path / "missing-medical-kb.json")
    )
    monkeypatch.setattr(
        public_router_module,
        "predict_weather_risk",
        lambda **kwargs: service.predict(**kwargs),
    )
    with _public_client() as client:
        response = client.post(
            "/api/public/parent-risk", json=_manual_payload(train_context, top_k=1)
        )
    assert response.status_code == 200, response.text
    prediction = response.json()["predictions"][0]
    assert prediction["tier1"]["available"] is True
    assert prediction["tier2"]["available"] is False
    assert prediction["tier2"]["reason"] == "MEDICAL_KB_ERROR"
