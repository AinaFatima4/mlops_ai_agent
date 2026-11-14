"""Download a registered MLflow model by alias and write its metadata for the API image."""

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import mlflow
from mlflow import MlflowClient

DEFAULT_TRACKING_URI = "http://localhost:5000"
DEFAULT_MODEL_NAME = "adult-income-classifier"
DEFAULT_ALIAS = "candidate"
DEFAULT_OUTPUT_DIRECTORY = Path("build/model")


def export_model(model_name: str, alias: str, output_directory: Path) -> dict[str, str]:
    client = MlflowClient()
    model_version = client.get_model_version_by_alias(model_name, alias)

    if output_directory.exists():
        shutil.rmtree(output_directory)
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    mlflow.artifacts.download_artifacts(
        f"models:/{model_name}@{alias}", dst_path=str(output_directory)
    )

    metadata = {
        "model_name": model_name,
        "model_version": str(model_version.version),
        "model_alias": alias,
        "run_id": model_version.run_id,
        "dataset_version": model_version.tags.get("dataset.version", "unknown"),
        "exported_at": datetime.now(UTC).isoformat(),
    }
    (output_directory / "model_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def main(arguments: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--alias", default=DEFAULT_ALIAS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parsed_arguments = parser.parse_args(arguments)

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    metadata = export_model(
        parsed_arguments.model_name, parsed_arguments.alias, parsed_arguments.output
    )
    logging.info("Exported %s", metadata)
    # The last stdout line is the image tag, read by deploy_api.sh
    print(f"model-v{metadata['model_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
