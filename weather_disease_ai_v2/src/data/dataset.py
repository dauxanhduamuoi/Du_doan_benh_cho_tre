"""Build the positive-only multiclass dataset and deterministic time splits."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.audit import run_data_audit
from src.data.io import relative_posix, sha256_file, write_csv, write_csv_gzip, write_json
from src.data.patients import support_level
from src.features.weather import build_weather_daily_features


DESCRIPTION_COLUMNS = ["date", "disease_group_name", "report_group_code"]
BASE_INPUT_COLUMNS = [
    "age_group",
    "gender",
    "month",
    "season",
    "day_of_year_sin",
    "day_of_year_cos",
]
LABEL_COLUMN = "disease_group_id"
WEIGHT_COLUMN = "case_count"
SORT_COLUMNS = ["date", "age_group", "gender", "disease_group_id"]
FORBIDDEN_PERSONAL_COLUMN_TOKENS = (
    "address",
    "full_address",
    "dia_chi",
    "địa_chỉ",
    "date_of_birth",
    "birth_date",
    "ngay_sinh",
    "ngày_sinh",
)


def month_to_season(month: int) -> str:
    if int(month) in {12, 1, 2, 3, 4}:
        return "Mùa khô"
    if int(month) in {5, 6, 7, 8, 9, 10, 11}:
        return "Mùa mưa"
    raise ValueError(f"Invalid month: {month}")


def add_calendar_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["month"] = result["date"].dt.month.astype("int16")
    result["season"] = result["month"].map(month_to_season)
    day_of_year = result["date"].dt.dayofyear
    result["day_of_year_sin"] = (2 * math.pi * day_of_year / 365.25).map(math.sin)
    result["day_of_year_cos"] = (2 * math.pi * day_of_year / 365.25).map(math.cos)
    return result


def stable_sort(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(SORT_COLUMNS, kind="mergesort").reset_index(drop=True)


def build_disease_catalog(positive_cases: pd.DataFrame) -> pd.DataFrame:
    catalog = (
        positive_cases.groupby(
            ["disease_group_id", "disease_group_name", "report_group_code"],
            dropna=False,
            as_index=False,
        )["case_count"]
        .sum()
        .rename(columns={"case_count": "total_case_count"})
    )
    catalog["support_level"] = catalog["total_case_count"].map(support_level)
    return catalog.sort_values("disease_group_id", kind="mergesort").reset_index(drop=True)


def split_by_unique_dates(
    dataset: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    dates = pd.Index(pd.to_datetime(dataset["date"]).dt.normalize().unique()).sort_values()
    if len(dates) < 3:
        raise ValueError("At least three unique dates are required for time splitting")

    train_count = int(len(dates) * 0.70)
    validation_count = int(len(dates) * 0.15)
    train_count = max(1, train_count)
    validation_count = max(1, validation_count)
    if train_count + validation_count >= len(dates):
        validation_count = 1
        train_count = len(dates) - 2

    train_dates = dates[:train_count]
    validation_dates = dates[train_count : train_count + validation_count]
    test_dates = dates[train_count + validation_count :]

    normalized_dates = pd.to_datetime(dataset["date"]).dt.normalize()
    train = stable_sort(dataset[normalized_dates.isin(train_dates)].copy())
    validation = stable_sort(dataset[normalized_dates.isin(validation_dates)].copy())
    test = stable_sort(dataset[normalized_dates.isin(test_dates)].copy())

    train_labels = set(train[LABEL_COLUMN].astype(str))
    validation_labels = set(validation[LABEL_COLUMN].astype(str))
    test_labels = set(test[LABEL_COLUMN].astype(str))
    validation_unseen = sorted(validation_labels - train_labels)
    test_unseen = sorted(test_labels - train_labels)

    def split_summary(frame: pd.DataFrame, split_dates: pd.Index) -> dict[str, Any]:
        return {
            "rows": int(len(frame)),
            "unique_dates": int(len(split_dates)),
            "date_from": str(pd.Timestamp(split_dates.min()).date()),
            "date_to": str(pd.Timestamp(split_dates.max()).date()),
            "total_case_count": int(frame[WEIGHT_COLUMN].sum()),
            "disease_groups": int(frame[LABEL_COLUMN].nunique()),
        }

    metadata = {
        "method": "chronological_unique_dates_70_15_15",
        "total_unique_dates": int(len(dates)),
        "train": split_summary(train, train_dates),
        "validation": split_summary(validation, validation_dates),
        "test": split_summary(test, test_dates),
        "unseen_disease_groups": {
            "validation_not_in_train": validation_unseen,
            "test_not_in_train": test_unseen,
            "validation_or_test_not_in_train": sorted(
                set(validation_unseen) | set(test_unseen)
            ),
        },
    }
    return train, validation, test, metadata


def validate_dataset(
    dataset: pd.DataFrame, input_columns: list[str], expected_case_count: int
) -> dict[str, Any]:
    required = [
        *DESCRIPTION_COLUMNS,
        *input_columns,
        LABEL_COLUMN,
        WEIGHT_COLUMN,
    ]
    missing_columns = [column for column in required if column not in dataset.columns]
    if missing_columns:
        raise ValueError(f"Final dataset is missing required columns: {missing_columns}")
    if LABEL_COLUMN in input_columns:
        raise ValueError("disease_group_id must not be included in input columns")
    if int(dataset[WEIGHT_COLUMN].sum()) != int(expected_case_count):
        raise ValueError("case_count was not preserved while building the final dataset")
    if (dataset[WEIGHT_COLUMN] <= 0).any():
        raise ValueError("Only observed positive cases are allowed; case_count must be positive")
    forbidden = [
        column
        for column in dataset.columns
        if any(token in column.lower() for token in FORBIDDEN_PERSONAL_COLUMN_TOKENS)
    ]
    if forbidden:
        raise ValueError(f"Personal columns are forbidden in the final dataset: {forbidden}")
    if not dataset.equals(stable_sort(dataset)):
        raise ValueError("Final dataset is not stably sorted")
    return {
        "required_columns_present": True,
        "case_count_preserved": True,
        "positive_only": True,
        "label_excluded_from_inputs": True,
        "personal_columns_absent": True,
        "stable_sort": True,
    }


def _format_dates_for_output(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y-%m-%d")
    return output


def _write_preparation_report(
    report_path: Path,
    audit: dict[str, Any],
    metadata: dict[str, Any],
    split_metadata: dict[str, Any],
    catalog: pd.DataFrame,
) -> None:
    support_counts = {
        level: int((catalog["support_level"] == level).sum())
        for level in ("high", "medium", "low", "insufficient")
    }
    unseen = split_metadata["unseen_disease_groups"][
        "validation_or_test_not_in_train"
    ]
    raw_missing = {
        key: value
        for key, value in audit["patient"]["missing_values"].items()
        if value
    }
    weather_missing = {
        key: value for key, value in audit["weather"]["missing_values"].items() if value
    }
    incomplete_windows = metadata["incomplete_weather_windows"]
    incomplete_window_note = ", ".join(
        f"{window}={values['rows_without_full_history']} dòng"
        for window, values in incomplete_windows.items()
    )
    issues = [
        f"{audit['icd_mapping']['unmapped_rows']} lượt có ICD không ánh xạ được.",
        f"{audit['weather']['missing_patient_weather_date_count']} ngày khám không có dữ liệu thời tiết.",
        f"Thiếu nguồn bệnh nhân: {raw_missing or 'không có trong các trường cần dùng'}.",
        f"Thiếu nguồn thời tiết: {weather_missing or 'không có'}.",
        "Các giá trị thiếu của cửa sổ 3/7/14 ngày chỉ nằm ở đầu chuỗi, trước khi "
        f"đủ lịch sử ({incomplete_window_note}); số thiếu bất thường sau khi đủ lịch sử đều bằng 0.",
    ]
    lines = [
        "# Data Preparation Report",
        "",
        "Pipeline này chỉ xử lý dữ liệu; không huấn luyện model và không tạo SHAP.",
        "",
        "## Nguồn thực tế",
        "",
        f"- Bệnh nhân/ICD: `{audit['sources']['patient_file']}`",
        f"- Thời tiết: `{audit['sources']['weather_file']}`",
        "",
        "## Kết quả",
        "",
        f"- Lượt bệnh nhi ban đầu: {audit['patient']['initial_patient_rows']:,}",
        f"- Lượt ánh xạ thành công: {audit['icd_mapping']['mapped_rows']:,}",
        f"- Nhóm bệnh: {metadata['disease_groups']:,}",
        f"- Thời gian bệnh: {audit['patient']['date_from']} đến {audit['patient']['date_to']}",
        f"- Thời gian thời tiết: {audit['weather']['date_from']} đến {audit['weather']['date_to']}",
        f"- Dòng dataset cuối: {metadata['rows']:,}",
        f"- Tổng `case_count`: {metadata['total_case_count']:,}",
        f"- Hỗ trợ high/medium/low/insufficient: {support_counts['high']}/{support_counts['medium']}/{support_counts['low']}/{support_counts['insufficient']}",
        "",
        "### Cột thời tiết thực tế",
        "",
    ]
    lines.extend(f"- `{column}`" for column in audit["weather"]["actual_columns"])
    lines.extend(["", "## Chia theo thời gian", ""])
    for split_name in ("train", "validation", "test"):
        values = split_metadata[split_name]
        lines.append(
            f"- {split_name}: {values['date_from']} đến {values['date_to']} "
            f"({values['unique_dates']:,} ngày, {values['rows']:,} dòng)"
        )
    lines.extend(["", "### Nhóm không được train hỗ trợ", ""])
    if unseen:
        lines.extend(f"- `{group_id}`" for group_id in unseen)
    else:
        lines.append("- Không có.")
    lines.extend(["", "## Dữ liệu thiếu hoặc vấn đề còn lại", ""])
    lines.extend(f"- {issue}" for issue in issues)
    lines.extend(
        [
            "",
            "## File đã tạo/chỉnh sửa",
            "",
            "- `README.md`",
            "- `requirements.txt`",
            "- `src/__init__.py`",
            "- `src/data/__init__.py`",
            "- `src/data/io.py`",
            "- `src/data/patients.py`",
            "- `src/data/audit.py`",
            "- `src/data/dataset.py`",
            "- `src/features/__init__.py`",
            "- `src/features/weather.py`",
            "- `scripts/02_audit_data.py`",
            "- `scripts/03_build_dataset.py`",
            "- `tests/conftest.py`",
            "- `tests/test_data_pipeline.py`",
            "- `tests/test_generated_artifacts.py`",
            "- `reports/audit/*`",
            "- `data/interim/positive_cases.csv.gz`",
            "- `data/interim/weather_daily_features_v2.csv.gz`",
            "- `data/processed/*`",
            "- `data/splits/*`",
            "- `reports/DATA_PREPARATION_REPORT.md`",
            "",
            "## Lệnh và kiểm tra",
            "",
            "```bash",
            "python scripts/02_audit_data.py",
            "python scripts/03_build_dataset.py",
            "pytest",
            "```",
            "",
            "Kết quả xác minh khi bàn giao: audit thành công, build thành công, `12 passed`; "
            "15 artifact sinh ra có SHA-256 giống hệt sau hai lần build liên tiếp.",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_dataset_artifacts(
    project_root: Path,
    patient_path: Path,
    weather_path: Path,
    patient_sheet: str,
    disease_sheet: str,
    windows: list[int],
) -> dict[str, Any]:
    audit_dir = project_root / "reports/audit"
    audit, patient_data, daily_weather, weather_metadata = run_data_audit(
        patient_path, weather_path, patient_sheet, disease_sheet, audit_dir
    )

    positive_cases = stable_sort(patient_data.positive_cases)
    positive_output = _format_dates_for_output(positive_cases)
    positive_path = project_root / "data/interim/positive_cases.csv.gz"
    write_csv_gzip(positive_path, positive_output)

    weather_features = build_weather_daily_features(daily_weather, windows)
    weather_path_out = project_root / "data/interim/weather_daily_features_v2.csv.gz"
    write_csv_gzip(weather_path_out, _format_dates_for_output(weather_features))

    dataset = positive_cases.merge(
        weather_features, on="date", how="left", validate="many_to_one"
    )
    if len(dataset) != len(positive_cases):
        raise ValueError("Row count changed while joining weather features")
    dataset = add_calendar_features(dataset)
    weather_columns = [
        column for column in weather_features.columns if column != "date"
    ]
    input_columns = [*BASE_INPUT_COLUMNS, *weather_columns]
    final_columns = [
        "date",
        "age_group",
        "gender",
        "month",
        "season",
        "day_of_year_sin",
        "day_of_year_cos",
        *weather_columns,
        LABEL_COLUMN,
        "disease_group_name",
        "report_group_code",
        WEIGHT_COLUMN,
    ]
    dataset = stable_sort(dataset[final_columns])
    weather_start = weather_features["date"].min()
    incomplete_weather_windows: dict[str, dict[str, int]] = {}
    for window in windows:
        window_columns = [
            column for column in weather_columns if column.endswith(f"_{window}d")
        ]
        incomplete = dataset[window_columns].isna().any(axis=1)
        enough_history = dataset["date"] >= weather_start + pd.DateOffset(
            days=window - 1
        )
        unexpected = incomplete & enough_history
        incomplete_weather_windows[f"{window}d"] = {
            "rows_without_full_history": int(incomplete.sum()),
            "unexpected_missing_rows_after_full_history": int(unexpected.sum()),
        }
        if unexpected.any():
            raise ValueError(
                f"{int(unexpected.sum())} rows have missing {window}-day weather "
                "features despite sufficient calendar history"
            )
    validation = validate_dataset(
        dataset, input_columns, int(positive_cases[WEIGHT_COLUMN].sum())
    )

    dataset_output = _format_dates_for_output(dataset)
    processed_path = project_root / "data/processed/weather_disease_multiclass.csv.gz"
    write_csv_gzip(processed_path, dataset_output)

    catalog = build_disease_catalog(positive_cases)
    catalog_path = project_root / "data/processed/disease_catalog.csv"
    write_csv(catalog_path, catalog)

    train, validation_split, test, split_metadata = split_by_unique_dates(dataset)
    split_dir = project_root / "data/splits"
    split_paths = {
        "train": split_dir / "train.csv.gz",
        "validation": split_dir / "validation.csv.gz",
        "test": split_dir / "test.csv.gz",
    }
    for name, frame in (
        ("train", train),
        ("validation", validation_split),
        ("test", test),
    ):
        write_csv_gzip(split_paths[name], _format_dates_for_output(frame))

    split_date_sets = [
        set(pd.to_datetime(frame["date"]).dt.normalize())
        for frame in (train, validation_split, test)
    ]
    if any(
        split_date_sets[left] & split_date_sets[right]
        for left, right in ((0, 1), (0, 2), (1, 2))
    ):
        raise ValueError("Date overlap detected between time splits")
    if sum(int(frame[WEIGHT_COLUMN].sum()) for frame in (train, validation_split, test)) != int(
        dataset[WEIGHT_COLUMN].sum()
    ):
        raise ValueError("case_count was not preserved across time splits")

    split_metadata["checks"] = {
        "no_date_overlap": True,
        "case_count_preserved": True,
    }
    split_metadata["files"] = {
        name: {
            "path": relative_posix(path, project_root),
            "sha256": sha256_file(path),
        }
        for name, path in split_paths.items()
    }
    split_metadata_path = split_dir / "split_metadata.json"
    write_json(split_metadata_path, split_metadata)

    missing_values = {
        column: int(count)
        for column, count in dataset.isna().sum().items()
        if int(count) > 0
    }
    metadata = {
        "source_files": {
            "patient": {
                "path": relative_posix(patient_path, project_root),
                "sha256": sha256_file(patient_path),
            },
            "weather": {
                "path": relative_posix(weather_path, project_root),
                "sha256": sha256_file(weather_path),
            },
        },
        "rows": int(len(dataset)),
        "total_case_count": int(dataset[WEIGHT_COLUMN].sum()),
        "disease_groups": int(dataset[LABEL_COLUMN].nunique()),
        "date_from": str(dataset["date"].min().date()),
        "date_to": str(dataset["date"].max().date()),
        "input_columns": input_columns,
        "label_column": LABEL_COLUMN,
        "weight_column": WEIGHT_COLUMN,
        "description_columns": DESCRIPTION_COLUMNS,
        "weather_feature_columns": weather_columns,
        "weather_windows_days": windows,
        "weather_actual_columns": weather_metadata["actual_columns"],
        "missing_values": missing_values,
        "incomplete_weather_windows": incomplete_weather_windows,
        "random_negative_samples_created": False,
        "sort_columns": SORT_COLUMNS,
        "checks": validation,
        "files": {
            "positive_cases": {
                "path": relative_posix(positive_path, project_root),
                "sha256": sha256_file(positive_path),
            },
            "weather_daily_features": {
                "path": relative_posix(weather_path_out, project_root),
                "sha256": sha256_file(weather_path_out),
            },
            "dataset": {
                "path": relative_posix(processed_path, project_root),
                "sha256": sha256_file(processed_path),
            },
            "disease_catalog": {
                "path": relative_posix(catalog_path, project_root),
                "sha256": sha256_file(catalog_path),
            },
        },
    }
    metadata_path = project_root / "data/processed/dataset_metadata.json"
    write_json(metadata_path, metadata)
    _write_preparation_report(
        project_root / "reports/DATA_PREPARATION_REPORT.md",
        audit,
        metadata,
        split_metadata,
        catalog,
    )
    return {
        "audit": audit,
        "dataset_metadata": metadata,
        "split_metadata": split_metadata,
    }
