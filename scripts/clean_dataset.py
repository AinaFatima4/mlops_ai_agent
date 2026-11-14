"""Clean the raw Adult dataset in place to produce the next dataset version."""

import csv
import sys
from pathlib import Path

DATASET_PATH = Path("data/adult.csv")
MISSING_VALUE_MARKER = "?"


def read_rows(dataset_path: Path) -> tuple[list[str], list[list[str]]]:
    with dataset_path.open(newline="", encoding="utf-8") as input_file:
        reader = csv.reader(input_file)
        header = next(reader)
        rows = list(reader)
    return header, rows


def clean_rows(rows: list[list[str]]) -> list[list[str]]:
    cleaned_rows = []
    for row in rows:
        stripped_values = [value.strip() for value in row]
        if MISSING_VALUE_MARKER in stripped_values:
            continue
        cleaned_rows.append(stripped_values)
    return cleaned_rows


def write_rows(dataset_path: Path, header: list[str], rows: list[list[str]]) -> None:
    with dataset_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> int:
    header, raw_rows = read_rows(DATASET_PATH)
    cleaned_rows = clean_rows(raw_rows)
    write_rows(DATASET_PATH, header, cleaned_rows)
    removed_row_count = len(raw_rows) - len(cleaned_rows)
    print(f"Kept {len(cleaned_rows)} rows, removed {removed_row_count} rows with missing values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
