"""Download the UCI Adult Income dataset and save it as a CSV with a header row."""

import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

DATASET_URL = "https://archive.ics.uci.edu/static/public/2/adult.zip"
SOURCE_FILE_NAME = "adult.data"
OUTPUT_PATH = Path("data/adult.csv")
COLUMN_NAMES = [
    "age",
    "workclass",
    "fnlwgt",
    "education",
    "education_num",
    "marital_status",
    "occupation",
    "relationship",
    "race",
    "sex",
    "capital_gain",
    "capital_loss",
    "hours_per_week",
    "native_country",
    "income",
]
REQUEST_TIMEOUT_SECONDS = 60


def download_zip_archive(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read()


def extract_rows(archive_bytes: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        raw_text = archive.read(SOURCE_FILE_NAME).decode("utf-8")

    rows = []
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        values = next(csv.reader([line]))
        if len(values) != len(COLUMN_NAMES):
            raise ValueError(f"Unexpected column count {len(values)} in line: {line}")
        rows.append(values)
    return rows


def write_csv(rows: list[list[str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(COLUMN_NAMES)
        writer.writerows(rows)


def main() -> int:
    archive_bytes = download_zip_archive(DATASET_URL)
    rows = extract_rows(archive_bytes)
    write_csv(rows, OUTPUT_PATH)
    print(f"Saved {len(rows)} rows to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
