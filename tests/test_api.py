import json
from pathlib import Path

import mlflow.sklearn
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api.main as api_module
from training.train import SKOPS_TRUSTED_TYPES, build_model_pipeline, split_dataset

VALID_RECORD = {
    "age": 39,
    "workclass": "Private",
    "fnlwgt": 77516,
    "education": "Bachelors",
    "education_num": 13,
    "marital_status": "Married",
    "occupation": "Sales",
    "relationship": "Husband",
    "race": "White",
    "sex": "Male",
    "capital_gain": 2174,
    "capital_loss": 0,
    "hours_per_week": 40,
    "native_country": "United-States",
}


@pytest.fixture
def exported_model_directory(tmp_path: Path, synthetic_dataset: pd.DataFrame) -> Path:
    train_features, _, train_target, _ = split_dataset(synthetic_dataset)
    pipeline, _ = build_model_pipeline("logistic_regression")
    pipeline.fit(train_features, train_target)
    model_directory = tmp_path / "model"
    mlflow.sklearn.save_model(
        pipeline,
        str(model_directory),
        serialization_format="skops",
        skops_trusted_types=SKOPS_TRUSTED_TYPES,
    )
    (model_directory / "model_metadata.json").write_text(
        json.dumps({"model_name": "adult-income-classifier", "model_version": "7"})
    )
    return model_directory


def build_client(monkeypatch: pytest.MonkeyPatch, model_directory: Path) -> TestClient:
    monkeypatch.setattr(api_module, "MODEL_DIRECTORY", model_directory)
    monkeypatch.setattr(api_module, "model_state", api_module.ModelState())
    return TestClient(api_module.app)


def test_ready_and_version_report_loaded_model(
    monkeypatch: pytest.MonkeyPatch, exported_model_directory: Path
) -> None:
    with build_client(monkeypatch, exported_model_directory) as client:
        assert client.get("/ready").status_code == 200
        version = client.get("/version").json()
        assert version["model_loaded"] is True
        assert version["model"]["model_version"] == "7"


def test_predict_returns_probability_per_record(
    monkeypatch: pytest.MonkeyPatch, exported_model_directory: Path
) -> None:
    with build_client(monkeypatch, exported_model_directory) as client:
        response = client.post("/predict", json={"records": [VALID_RECORD, VALID_RECORD]})
    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "7"
    assert len(body["predictions"]) == 2
    assert all(0.0 <= item["probability_above_50k"] <= 1.0 for item in body["predictions"])


@pytest.mark.parametrize(
    "request_body",
    [
        {"records": []},
        {"records": [{**VALID_RECORD, "age": -5}]},
        {"records": [{key: value for key, value in VALID_RECORD.items() if key != "sex"}]},
        {"records": [VALID_RECORD] * 101},
    ],
)
def test_invalid_requests_are_rejected(
    monkeypatch: pytest.MonkeyPatch, exported_model_directory: Path, request_body: dict
) -> None:
    with build_client(monkeypatch, exported_model_directory) as client:
        assert client.post("/predict", json=request_body).status_code == 422


def test_missing_model_keeps_liveness_but_fails_readiness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with build_client(monkeypatch, tmp_path / "does-not-exist") as client:
        assert client.get("/health").status_code == 200
        readiness = client.get("/ready")
        assert readiness.status_code == 503
        assert "FileNotFoundError" in readiness.json()["detail"]["reason"]
        assert client.post("/predict", json={"records": [VALID_RECORD]}).status_code == 503
