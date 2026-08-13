"""Build the positive-only weather disease multiclass dataset and time splits."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.dataset import build_dataset_artifacts
from src.data.io import ensure_source_files, load_config


def main() -> None:
    config = load_config(PROJECT_ROOT)
    patient_path, weather_path = ensure_source_files(PROJECT_ROOT, config)
    result = build_dataset_artifacts(
        project_root=PROJECT_ROOT,
        patient_path=patient_path,
        weather_path=weather_path,
        patient_sheet=config["data"]["patient_sheet"],
        disease_sheet=config["data"]["disease_sheet"],
        windows=[int(value) for value in config["weather"]["windows"]],
    )
    metadata = result["dataset_metadata"]
    print("Dataset build completed.")
    print(f"Rows: {metadata['rows']:,}")
    print(f"Total case_count: {metadata['total_case_count']:,}")
    print("Dataset: data/processed/weather_disease_multiclass.csv.gz")


if __name__ == "__main__":
    main()
