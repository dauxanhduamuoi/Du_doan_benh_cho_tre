"""Audit the patient/ICD workbook and historical weather source."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.audit import run_data_audit
from src.data.io import ensure_source_files, load_config


def main() -> None:
    config = load_config(PROJECT_ROOT)
    patient_path, weather_path = ensure_source_files(PROJECT_ROOT, config)
    audit, _, _, _ = run_data_audit(
        patient_path=patient_path,
        weather_path=weather_path,
        patient_sheet=config["data"]["patient_sheet"],
        disease_sheet=config["data"]["disease_sheet"],
        output_dir=PROJECT_ROOT / "reports/audit",
    )
    print("Data audit completed.")
    print(f"Initial encounters: {audit['patient']['initial_patient_rows']:,}")
    print(f"Mapped encounters: {audit['icd_mapping']['mapped_rows']:,}")
    print("Audit report: reports/audit/data_audit.md")


if __name__ == "__main__":
    main()
