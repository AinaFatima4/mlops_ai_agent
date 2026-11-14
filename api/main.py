"""FastAPI inference service for the Adult Income classifier."""

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
import skops.io
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_DIRECTORY = Path(os.environ.get("MODEL_PATH", "/app/model"))
APP_VERSION = os.environ.get("APP_VERSION", "1.0.0")
APP_ENVIRONMENT = os.environ.get("APP_ENVIRONMENT", "local")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
METADATA_FILE_NAME = "model_metadata.json"
MAXIMUM_BATCH_SIZE = 100

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("adult_income_api")


class AdultIncomeFeatures(BaseModel):
    age: float = Field(ge=0, le=120)
    workclass: str
    fnlwgt: float = Field(ge=0)
    education: str
    education_num: float = Field(ge=0, le=20)
    marital_status: str
    occupation: str
    relationship: str
    race: str
    sex: str
    capital_gain: float = Field(ge=0)
    capital_loss: float = Field(ge=0)
    hours_per_week: float = Field(ge=0, le=168)
    native_country: str


class PredictionRequest(BaseModel):
    records: list[AdultIncomeFeatures] = Field(min_length=1, max_length=MAXIMUM_BATCH_SIZE)


class Prediction(BaseModel):
    income_above_50k: bool
    probability_above_50k: float


class PredictionResponse(BaseModel):
    model_version: str
    predictions: list[Prediction]


class ModelState:
    def __init__(self) -> None:
        self.model: Any = None
        self.metadata: dict[str, Any] = {}
        self.load_error: str | None = None


model_state = ModelState()


def load_model(model_directory: Path) -> tuple[Any, dict[str, Any]]:
    model_definition = yaml.safe_load((model_directory / "MLmodel").read_text(encoding="utf-8"))
    sklearn_flavor = model_definition["flavors"]["sklearn"]
    if sklearn_flavor.get("serialization_format") != "skops":
        raise ValueError("Only skops-serialized models are accepted")
    model = skops.io.load(
        model_directory / sklearn_flavor["pickled_model"],
        trusted=sklearn_flavor.get("skops_trusted_types", []),
    )
    metadata_path = model_directory / METADATA_FILE_NAME
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    )
    return model, metadata


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    try:
        model_state.model, model_state.metadata = load_model(MODEL_DIRECTORY)
        logger.info("Model loaded from %s: %s", MODEL_DIRECTORY, model_state.metadata)
    except Exception as error:
        # Stay alive so the liveness probe passes; readiness reports the real problem
        model_state.load_error = f"{type(error).__name__}: {error}"
        logger.error("Model failed to load from %s: %s", MODEL_DIRECTORY, model_state.load_error)
    yield


app = FastAPI(title="Adult Income Prediction API", version=APP_VERSION, lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/ready")
def ready() -> dict[str, str]:
    if model_state.model is None:
        raise HTTPException(
            status_code=503, detail={"status": "not_ready", "reason": model_state.load_error}
        )
    return {"status": "ready"}


@app.get("/version")
def version() -> dict[str, Any]:
    return {
        "app_version": APP_VERSION,
        "environment": APP_ENVIRONMENT,
        "model_loaded": model_state.model is not None,
        "model": model_state.metadata,
    }


@app.post("/predict", response_model=PredictionResponse)
def predict(request: PredictionRequest) -> PredictionResponse:
    if model_state.model is None:
        raise HTTPException(status_code=503, detail="Model is not loaded")
    features = pd.DataFrame([record.model_dump() for record in request.records])
    predicted_labels = model_state.model.predict(features)
    positive_probabilities = model_state.model.predict_proba(features)[:, 1]
    logger.info("Served %d predictions", len(features))
    return PredictionResponse(
        model_version=str(model_state.metadata.get("model_version", "unknown")),
        predictions=[
            Prediction(income_above_50k=bool(label), probability_above_50k=float(probability))
            for label, probability in zip(predicted_labels, positive_probabilities, strict=True)
        ],
    )
