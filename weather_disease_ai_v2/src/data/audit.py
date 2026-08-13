"""Generate privacy-safe audit artifacts for the two source datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.data.io import relative_posix, sha256_file, write_csv, write_json
from src.data.patients import PatientData, build_patient_data, support_level
from src.features.weather import build_daily_weather_base, read_weather_hourly


def _support_frame(patient_data: PatientData) -> pd.DataFrame:
    support = pd.DataFrame(patient_data.stats["disease_support"])
    support["support_level"] = support["case_count"].map(support_level)
    return support[
        [
            "disease_group_id",
            "disease_group_name",
            "report_group_code",
            "case_count",
            "support_level",
        ]
    ]


def _threshold_summary(support: pd.DataFrame) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for threshold in (20, 50, 100, 200):
        subset = support[support["case_count"] < threshold]
        result[f"under_{threshold}"] = {
            "group_count": int(len(subset)),
            "disease_group_ids": sorted(subset["disease_group_id"].astype(str).tolist()),
        }
    return result


def _audit_markdown(audit: dict[str, Any]) -> str:
    patient = audit["patient"]
    mapping = audit["icd_mapping"]
    weather = audit["weather"]
    lines = [
        "# Data Audit",
        "",
        "Báo cáo chỉ chứa thống kê tổng hợp; không chứa ngày sinh, địa chỉ hoặc thông tin nhận dạng cá nhân.",
        "",
        "## Bệnh nhi và ánh xạ ICD",
        "",
        f"- Số lượt ban đầu: {patient['initial_patient_rows']:,}",
        f"- Khoảng ngày khám: {patient['date_from']} đến {patient['date_to']}",
        f"- Số mã ICD chính duy nhất: {patient['unique_icd_codes']:,}",
        f"- Số nhóm bệnh đã ánh xạ: {patient['mapped_disease_groups']:,}",
        f"- Lượt ánh xạ thành công: {mapping['mapped_rows']:,}/{mapping['eligible_rows']:,} ({mapping['success_rate']:.4%})",
        f"- Lượt không ánh xạ: {mapping['unmapped_rows']:,}",
        f"- Dòng trùng hoàn toàn trong sheet bệnh nhân: {patient['exact_duplicate_rows']:,}",
        "",
        "### Thiếu dữ liệu trong các trường nguồn cần dùng",
        "",
    ]
    lines.extend(
        f"- `{column}`: {count:,}" for column, count in patient["missing_values"].items()
    )
    lines.extend(["", "### Phân bố giới tính", ""])
    lines.extend(f"- {name}: {count:,}" for name, count in patient["gender_distribution"].items())
    lines.extend(["", "### Phân bố nhóm tuổi", ""])
    lines.extend(f"- {name}: {count:,}" for name, count in patient["age_group_distribution"].items())
    lines.extend(
        [
            "",
            "## Hỗ trợ theo nhóm bệnh",
            "",
            f"- Tổng nhóm trong dữ liệu ca thật: {audit['disease_support']['group_count']:,}",
        ]
    )
    for name, values in audit["disease_support"]["thresholds"].items():
        lines.append(f"- `{name}`: {values['group_count']:,} nhóm")
    lines.extend(
        [
            "",
            "## Thời tiết",
            "",
            f"- Khoảng ngày: {weather['date_from']} đến {weather['date_to']}",
            f"- Số ngày: {weather['daily_rows']:,}",
            f"- Ngày khám không có thời tiết tương ứng: {weather['missing_patient_weather_date_count']:,}",
            f"- Timestamp trùng: {weather['duplicate_timestamps']:,}",
            "",
            "### Cột thực tế",
            "",
        ]
    )
    lines.extend(f"- `{column}`" for column in weather["actual_columns"])
    lines.extend(["", "### Thiếu dữ liệu thời tiết", ""])
    lines.extend(
        f"- `{column}`: {count:,}" for column, count in weather["missing_values"].items()
    )
    return "\n".join(lines) + "\n"


def run_data_audit(
    patient_path: Path,
    weather_path: Path,
    patient_sheet: str,
    disease_sheet: str,
    output_dir: Path,
) -> tuple[dict[str, Any], PatientData, pd.DataFrame, dict[str, Any]]:
    patient_data = build_patient_data(patient_path, patient_sheet, disease_sheet)
    hourly, weather_metadata = read_weather_hourly(weather_path)
    daily_weather = build_daily_weather_base(hourly)

    patient_dates = set(patient_data.positive_cases["date"])
    weather_dates = set(daily_weather["date"])
    missing_weather_dates = pd.DataFrame(
        {"date": sorted(patient_dates - weather_dates)}
    )
    if not missing_weather_dates.empty:
        missing_weather_dates["date"] = missing_weather_dates["date"].dt.strftime("%Y-%m-%d")

    support = _support_frame(patient_data)
    stats = patient_data.stats
    project_root = output_dir.parents[1]
    audit: dict[str, Any] = {
        "sources": {
            "patient_file": relative_posix(patient_path, project_root),
            "patient_sha256": sha256_file(patient_path),
            "weather_file": relative_posix(weather_path, project_root),
            "weather_sha256": sha256_file(weather_path),
        },
        "patient": {
            "initial_patient_rows": stats["initial_patient_rows"],
            "eligible_patient_rows": stats["eligible_patient_rows"],
            "date_from": stats["patient_date_from"],
            "date_to": stats["patient_date_to"],
            "unique_icd_codes": stats["unique_patient_icd_codes"],
            "mapped_disease_groups": stats["mapped_disease_groups"],
            "exact_duplicate_rows": stats["raw_exact_duplicate_rows"],
            "missing_values": stats["missing_values"],
            "gender_distribution": stats["gender_distribution"],
            "age_group_distribution": stats["age_group_distribution"],
        },
        "catalog": {
            "rows": stats["catalog_rows"],
            "valid_unique_icd_codes": stats["catalog_valid_unique_icd_codes"],
            "duplicate_icd_rows": stats["catalog_duplicate_icd_rows"],
            "disease_groups": stats["catalog_disease_groups"],
        },
        "icd_mapping": {
            "eligible_rows": stats["eligible_patient_rows"],
            "mapped_rows": stats["mapped_patient_rows"],
            "unmapped_rows": stats["unmapped_patient_rows"],
            "success_rate": stats["mapping_success_rate"],
            "unmapped_unique_icd_codes": int(len(patient_data.unmapped_icd)),
        },
        "positive_cases": {
            "rows": stats["positive_case_rows"],
            "total_case_count": stats["positive_total_case_count"],
        },
        "disease_support": {
            "group_count": int(len(support)),
            "thresholds": _threshold_summary(support),
        },
        "weather": {
            "date_from": str(daily_weather["date"].min().date()),
            "date_to": str(daily_weather["date"].max().date()),
            "daily_rows": int(len(daily_weather)),
            "hourly_rows": weather_metadata["hourly_rows"],
            "actual_columns": weather_metadata["actual_columns"],
            "canonical_column_mapping": weather_metadata["canonical_column_mapping"],
            "missing_values": weather_metadata["missing_values"],
            "invalid_timestamps": weather_metadata["invalid_timestamps"],
            "duplicate_timestamps": weather_metadata["duplicate_timestamps"],
            "missing_patient_weather_date_count": int(len(missing_weather_dates)),
            "missing_patient_weather_dates": missing_weather_dates.get(
                "date", pd.Series(dtype="string")
            ).astype(str).tolist(),
        },
        "privacy": {
            "contains_date_of_birth": False,
            "contains_address": False,
            "contains_personal_identifiers": False,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "data_audit.json", audit)
    (output_dir / "data_audit.md").write_text(_audit_markdown(audit), encoding="utf-8")
    write_csv(output_dir / "unmapped_icd.csv", patient_data.unmapped_icd)
    write_csv(output_dir / "disease_support.csv", support)
    write_csv(output_dir / "missing_weather_dates.csv", missing_weather_dates)
    return audit, patient_data, daily_weather, weather_metadata
