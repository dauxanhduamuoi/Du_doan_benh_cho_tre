"""Patient and ICD catalog normalization derived from the validated V1 rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ICD_ADMISSION_COL = "icdNV"
ICD_DISCHARGE_COL = "icdxuatvien"
CHECK_IN_DATE_COL = "check_in_date"
DATE_OF_BIRTH_COL = "date_of_birth"
GENDER_COL = "gender"
MONTH_AGE_COL = "month"

ICD_CODE_COL = "MAICD"
DISEASE_GROUP_ID_COL = "IDNHOMICD"
DISEASE_GROUP_NAME_COL = "TENNHOMICD"
REPORT_GROUP_CODE_COL = "MANHOMBAOCAO"

PATIENT_COLUMNS = [
    ICD_ADMISSION_COL,
    ICD_DISCHARGE_COL,
    CHECK_IN_DATE_COL,
    DATE_OF_BIRTH_COL,
    MONTH_AGE_COL,
    GENDER_COL,
]
CATALOG_COLUMNS = [
    ICD_CODE_COL,
    DISEASE_GROUP_ID_COL,
    DISEASE_GROUP_NAME_COL,
    REPORT_GROUP_CODE_COL,
]
POSITIVE_CASE_COLUMNS = [
    "date",
    "age_group",
    "gender",
    "disease_group_id",
    "disease_group_name",
    "report_group_code",
    "case_count",
]


@dataclass
class PatientData:
    positive_cases: pd.DataFrame
    disease_catalog: pd.DataFrame
    unmapped_icd: pd.DataFrame
    stats: dict[str, Any]


def normalize_icd_series(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip().str.upper()
    values = values.str.replace("†", "", regex=False).str.replace("*", "", regex=False)
    return values.replace({"": pd.NA, "<NA>": pd.NA, "NAN": pd.NA, "NONE": pd.NA})


def parse_mixed_date_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", dayfirst=True)
    numeric = pd.to_numeric(series, errors="coerce")
    excel_serial = numeric.between(20_000, 80_000) & numeric.notna()
    if excel_serial.any():
        parsed.loc[excel_serial] = pd.Timestamp("1899-12-30") + pd.to_timedelta(
            numeric.loc[excel_serial], unit="D"
        )
    return parsed


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def normalize_gender(value: object) -> str:
    if pd.isna(value):
        return "Không rõ"
    text = str(value).strip()
    folded = _fold_text(text)
    if folded in {"nam", "male", "m", "1"}:
        return "Nam"
    if folded in {"nu", "female", "f", "0", "2"}:
        return "Nữ"
    return text or "Không rõ"


def age_to_group(age_years: pd.Series) -> pd.Series:
    conditions = [
        age_years.isna(),
        age_years < 1,
        age_years <= 5,
        age_years <= 10,
        age_years <= 15,
    ]
    choices = ["Không rõ", "Dưới 1 tuổi", "1-5 tuổi", "6-10 tuổi", "11-15 tuổi"]
    return pd.Series(
        np.select(conditions, choices, default="Trên 15 tuổi"), index=age_years.index
    )


def normalize_identifier_series(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    values = values.str.replace(r"^(-?\d+)\.0+$", r"\1", regex=True)
    return values.replace({"": pd.NA, "<NA>": pd.NA, "NAN": pd.NA, "NONE": pd.NA})


def read_workbook_tables(
    workbook_path: Path, patient_sheet: str, disease_sheet: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    workbook = pd.ExcelFile(workbook_path)
    missing_sheets = [
        name for name in (patient_sheet, disease_sheet) if name not in workbook.sheet_names
    ]
    if missing_sheets:
        raise ValueError(
            f"Workbook is missing sheets {missing_sheets}; actual sheets: {workbook.sheet_names}"
        )
    patients = pd.read_excel(workbook, sheet_name=patient_sheet)
    catalog = pd.read_excel(workbook, sheet_name=disease_sheet)
    return patients, catalog


def _require_columns(frame: pd.DataFrame, columns: list[str], table_name: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{table_name} is missing required columns: {missing}")


def _prepare_catalog(raw_catalog: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    _require_columns(raw_catalog, CATALOG_COLUMNS, "DS-MaBenh")
    catalog = raw_catalog[CATALOG_COLUMNS].copy()
    catalog["icd_code"] = normalize_icd_series(catalog[ICD_CODE_COL])
    catalog["disease_group_id"] = normalize_identifier_series(
        catalog[DISEASE_GROUP_ID_COL]
    )
    catalog["disease_group_name"] = catalog[DISEASE_GROUP_NAME_COL].astype("string").str.strip()
    catalog["report_group_code"] = normalize_identifier_series(catalog[REPORT_GROUP_CODE_COL])
    valid = catalog.dropna(subset=["icd_code", "disease_group_id", "disease_group_name"])
    duplicate_icd_rows = int(valid.duplicated("icd_code", keep=False).sum())
    valid = valid.drop_duplicates("icd_code", keep="last")
    result = valid[
        ["icd_code", "disease_group_id", "disease_group_name", "report_group_code"]
    ].copy()
    result = result.sort_values("icd_code", kind="mergesort").reset_index(drop=True)
    stats = {
        "catalog_rows": int(len(raw_catalog)),
        "catalog_valid_unique_icd_codes": int(result["icd_code"].nunique()),
        "catalog_duplicate_icd_rows": duplicate_icd_rows,
        "catalog_disease_groups": int(result["disease_group_id"].nunique()),
    }
    return result, stats


def build_patient_data(
    workbook_path: Path, patient_sheet: str, disease_sheet: str
) -> PatientData:
    raw_patients, raw_catalog = read_workbook_tables(
        workbook_path, patient_sheet, disease_sheet
    )
    _require_columns(raw_patients, PATIENT_COLUMNS, "DS-BenhNhan")
    catalog, catalog_stats = _prepare_catalog(raw_catalog)

    missing_values = {
        column: int(raw_patients[column].isna().sum()) for column in PATIENT_COLUMNS
    }
    raw_duplicate_rows = int(raw_patients.duplicated().sum())

    patients = raw_patients[PATIENT_COLUMNS].copy()
    patients[CHECK_IN_DATE_COL] = parse_mixed_date_series(patients[CHECK_IN_DATE_COL])
    patients[DATE_OF_BIRTH_COL] = parse_mixed_date_series(patients[DATE_OF_BIRTH_COL])
    patients[ICD_ADMISSION_COL] = normalize_icd_series(patients[ICD_ADMISSION_COL])
    patients[ICD_DISCHARGE_COL] = normalize_icd_series(patients[ICD_DISCHARGE_COL])
    patients["main_icd"] = patients[ICD_DISCHARGE_COL].fillna(
        patients[ICD_ADMISSION_COL]
    )
    patients["main_icd"] = normalize_icd_series(patients["main_icd"])

    eligible = patients.dropna(subset=[CHECK_IN_DATE_COL, "main_icd"]).copy()
    mapped = eligible.merge(catalog, left_on="main_icd", right_on="icd_code", how="left")
    unmapped_rows = mapped[mapped["disease_group_id"].isna()].copy()
    unmapped_icd = (
        unmapped_rows.groupby("main_icd", dropna=False)
        .size()
        .reset_index(name="encounter_count")
        .sort_values(["encounter_count", "main_icd"], ascending=[False, True], kind="mergesort")
        .reset_index(drop=True)
    )

    mapped = mapped.dropna(subset=["disease_group_id", "disease_group_name"]).copy()
    mapped["gender"] = mapped[GENDER_COL].map(normalize_gender)
    age_years = (
        mapped[CHECK_IN_DATE_COL] - mapped[DATE_OF_BIRTH_COL]
    ).dt.total_seconds() / (365.25 * 24 * 60 * 60)
    month_age = pd.to_numeric(mapped[MONTH_AGE_COL], errors="coerce") / 12
    age_years = age_years.fillna(month_age).where(lambda values: values >= 0)
    mapped["age_group"] = age_to_group(age_years)
    mapped["date"] = mapped[CHECK_IN_DATE_COL].dt.normalize()

    group_columns = [
        "date",
        "age_group",
        "gender",
        "disease_group_id",
        "disease_group_name",
        "report_group_code",
    ]
    positive_cases = (
        mapped.groupby(group_columns, dropna=False, sort=True)
        .size()
        .reset_index(name="case_count")
    )
    positive_cases["case_count"] = positive_cases["case_count"].astype("int64")
    positive_cases = positive_cases[POSITIVE_CASE_COLUMNS].sort_values(
        ["date", "age_group", "gender", "disease_group_id"], kind="mergesort"
    ).reset_index(drop=True)

    disease_support = (
        positive_cases.groupby(
            ["disease_group_id", "disease_group_name", "report_group_code"],
            dropna=False,
            as_index=False,
        )["case_count"]
        .sum()
        .sort_values(["case_count", "disease_group_id"], ascending=[False, True], kind="mergesort")
        .reset_index(drop=True)
    )
    gender_distribution = {
        str(key): int(value) for key, value in mapped["gender"].value_counts().sort_index().items()
    }
    age_distribution = {
        str(key): int(value)
        for key, value in mapped["age_group"].value_counts().sort_index().items()
    }

    eligible_count = int(len(eligible))
    mapped_count = int(len(mapped))
    disease_support_records = []
    for record in disease_support.to_dict("records"):
        record["case_count"] = int(record["case_count"])
        disease_support_records.append(record)

    stats: dict[str, Any] = {
        **catalog_stats,
        "initial_patient_rows": int(len(raw_patients)),
        "eligible_patient_rows": eligible_count,
        "mapped_patient_rows": mapped_count,
        "unmapped_patient_rows": int(len(unmapped_rows)),
        "mapping_success_rate": (mapped_count / eligible_count) if eligible_count else 0.0,
        "unique_patient_icd_codes": int(eligible["main_icd"].nunique()),
        "mapped_disease_groups": int(mapped["disease_group_id"].nunique()),
        "patient_date_from": str(eligible[CHECK_IN_DATE_COL].min().date()),
        "patient_date_to": str(eligible[CHECK_IN_DATE_COL].max().date()),
        "positive_case_rows": int(len(positive_cases)),
        "positive_total_case_count": int(positive_cases["case_count"].sum()),
        "raw_exact_duplicate_rows": raw_duplicate_rows,
        "missing_values": missing_values,
        "gender_distribution": gender_distribution,
        "age_group_distribution": age_distribution,
        "disease_support": disease_support_records,
    }
    return PatientData(positive_cases, catalog, unmapped_icd, stats)


def support_level(case_count: int) -> str:
    if case_count >= 1000:
        return "high"
    if case_count >= 200:
        return "medium"
    if case_count >= 20:
        return "low"
    return "insufficient"
