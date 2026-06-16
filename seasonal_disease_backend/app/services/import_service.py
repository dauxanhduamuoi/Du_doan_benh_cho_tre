# app/services/import_service.py
import json
from pathlib import Path

from sqlalchemy.orm import Session
import pandas as pd

from app.models import DiseaseCode, DiseaseKnowledge, ImportLog, MonthlyStatistic, PatientRecord
from app.services.data_processing_service import (
    load_disease_codes,
    process_patients,
    create_monthly_stats,
)
from app.services.area_service import attach_patient_areas, clear_area_lookup_caches


def is_missing(value):
    try:
        return pd.isna(value)
    except Exception:
        return value is None


def safe_text(value):
    if is_missing(value):
        return None
    value = str(value).strip()
    return value or None


def safe_datetime(value):
    if is_missing(value):
        return None

    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()

    return value


def safe_float(value):
    if is_missing(value):
        return None
    return float(value)


def safe_int(value):
    if is_missing(value):
        return None
    return int(value)


def clear_data_type(db: Session, data_type: str, commit: bool = True):
    db.query(PatientRecord).filter(PatientRecord.data_type == data_type).delete(synchronize_session=False)
    db.query(MonthlyStatistic).filter(MonthlyStatistic.data_type == data_type).delete(synchronize_session=False)
    if commit:
        db.commit()


def _row_to_code_dict(row) -> dict:
    def text_or_none(value):
        if is_missing(value):
            return None
        value = str(value).strip()
        return value if value else None

    icd_code = text_or_none(row.get("MAICD"))
    return {
        "icd_code": icd_code.upper() if icd_code else "",
        "disease_name": text_or_none(row.get("TENICD")),
        "group_id": text_or_none(row.get("IDNHOMICD")),
        "group_name": text_or_none(row.get("TENNHOMICD")),
        "report_group_code": text_or_none(row.get("MANHOMBAOCAO")),
        "english_name": text_or_none(row.get("TENTIENGANH")),
    }


def _code_dicts_from_dataframe(disease_codes: pd.DataFrame) -> list[dict]:
    """Chuyển DS-MaBenh thành list dict để bulk insert nhanh hơn."""
    rows: list[dict] = []
    if disease_codes is None or disease_codes.empty:
        return rows

    codes = disease_codes.copy()
    codes["MAICD"] = codes["MAICD"].astype("string").str.strip().str.upper()
    codes = codes.dropna(subset=["MAICD"])
    codes = codes[codes["MAICD"] != ""]
    codes = codes.drop_duplicates(subset=["MAICD"], keep="last")

    for _, row in codes.iterrows():
        item = _row_to_code_dict(row)
        if item["icd_code"]:
            rows.append(item)

    return rows


def _codes_to_dataframe(codes) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "MAICD": c.icd_code,
            "TENICD": c.disease_name,
            "IDNHOMICD": c.group_id,
            "TENNHOMICD": c.group_name,
            "MANHOMBAOCAO": c.report_group_code,
            "TENTIENGANH": c.english_name,
        }
        for c in codes
    ])


def import_disease_codes(db: Session, file_path: str):
    """
    Import DS-MaBenh do nhân viên y tế/admin cung cấp.
    Bảng này dùng để map ICD khi import DS-BenhNhan người dùng.
    """
    disease_codes = load_disease_codes(file_path)
    rows = _code_dicts_from_dataframe(disease_codes)

    if not rows:
        raise ValueError("File DS-MaBenh không có mã bệnh hợp lệ.")

    try:
        db.query(DiseaseCode).delete(synchronize_session=False)
        db.bulk_insert_mappings(DiseaseCode, rows)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return disease_codes


PARENT_GUIDE_SHEET_CANDIDATES = ["HuongDan-PhuHuynh", "HuongDan_PhuHuynh", "DiseaseKnowledge", "Sheet1"]
PARENT_GUIDE_REQUIRED_COLUMNS = [
    "TENNHOMICD",
    "TRIEUCHUNGTHUONGGAP",
    "DAUHIEUCANDIKHAM",
    "CACHPHONGBENH",
]

PROVINCE_REGION_SHEET_CANDIDATES = ["DS-TinhThanh-Mien", "DS_TinhThanh_Mien", "ProvinceRegions", "Sheet1"]
PROVINCE_REGION_REQUIRED_COLUMNS = ["province_code", "province_name", "mien_code", "mien"]
PROVINCE_REGION_OPTIONAL_COLUMNS = ["aliases"]
PROVINCE_REGION_CODES = {"north", "central", "south"}


def _load_parent_guide_dataframe(file_path: str) -> tuple[pd.DataFrame, str, list[str]]:
    xls = pd.ExcelFile(file_path)
    sheet_name = next((name for name in PARENT_GUIDE_SHEET_CANDIDATES if name in xls.sheet_names), None)
    if sheet_name is None:
        sheet_name = xls.sheet_names[0] if xls.sheet_names else None
    if not sheet_name:
        raise ValueError("File Excel không có sheet dữ liệu.")

    df = pd.read_excel(xls, sheet_name=sheet_name)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in PARENT_GUIDE_REQUIRED_COLUMNS if c not in df.columns]
    return df, sheet_name, missing


def _parent_guide_rows_from_dataframe(df: pd.DataFrame, source_file: str) -> list[dict]:
    rows: list[dict] = []
    if df.empty:
        return rows

    work = df.copy().replace(r"^\s*$", pd.NA, regex=True)
    work = work.dropna(subset=["TENNHOMICD"])

    for _, row in work.iterrows():
        disease_group = safe_text(row.get("TENNHOMICD"))
        if not disease_group:
            continue
        symptoms = safe_text(row.get("TRIEUCHUNGTHUONGGAP"))
        warning_signs = safe_text(row.get("DAUHIEUCANDIKHAM"))
        prevention = safe_text(row.get("CACHPHONGBENH"))
        if not symptoms and not warning_signs and not prevention:
            continue

        group_id = safe_text(row.get("IDNHOMICD"))
        report_group_code = safe_text(row.get("MANHOMBAOCAO"))
        source_parts = [f"Excel: {source_file}"]
        if group_id:
            source_parts.append(f"IDNHOMICD={group_id}")
        if report_group_code:
            source_parts.append(f"MANHOMBAOCAO={report_group_code}")

        rows.append({
            "disease_group": disease_group,
            "title": disease_group,
            "description": None,
            "symptoms": symptoms,
            "warning_signs": warning_signs,
            "prevention": prevention,
            "source": "; ".join(source_parts),
        })

    deduped: dict[str, dict] = {}
    for row in rows:
        deduped[row["disease_group"].strip().lower()] = row
    return list(deduped.values())


def preview_parent_guide_file(file_path: str) -> dict:
    df, sheet_name, missing = _load_parent_guide_dataframe(file_path)
    sample_cols = [
        "IDNHOMICD",
        "TENNHOMICD",
        "MANHOMBAOCAO",
        "TRIEUCHUNGTHUONGGAP",
        "DAUHIEUCANDIKHAM",
        "CACHPHONGBENH",
    ]
    existing_sample_cols = [c for c in sample_cols if c in df.columns]

    rows = [] if missing else _parent_guide_rows_from_dataframe(df, "preview.xlsx")
    invalid_rows = int(len(df) - len(rows)) if not missing else len(df)

    return {
        "sheet": sheet_name,
        "columns": list(df.columns),
        "required_columns": PARENT_GUIDE_REQUIRED_COLUMNS,
        "missing_columns": missing,
        "total_rows": int(len(df)),
        "valid_rows": int(len(rows)),
        "invalid_rows": invalid_rows,
        "duplicate_groups_removed": int(max(0, len(df.dropna(subset=["TENNHOMICD"])) - len(rows))) if "TENNHOMICD" in df.columns and not missing else 0,
        "sample_rows": df.head(10)[existing_sample_cols].fillna("").astype(str).to_dict(orient="records"),
    }


def import_parent_guide_file(db: Session, file_path: str, source_file: str, imported_by: str | None = None) -> dict:
    df, sheet_name, missing = _load_parent_guide_dataframe(file_path)
    if missing:
        raise ValueError(f"File thiếu các cột bắt buộc: {missing}. Cột trong file: {list(df.columns)}")

    rows = _parent_guide_rows_from_dataframe(df, source_file)
    if not rows:
        raise ValueError("File không có dòng hướng dẫn phụ huynh hợp lệ.")

    try:
        db.query(DiseaseKnowledge).delete(synchronize_session=False)
        db.bulk_insert_mappings(DiseaseKnowledge, rows)
        log = ImportLog(
            file_name=source_file,
            data_type="parent_guide",
            total_rows=len(df),
            valid_rows=len(rows),
            invalid_rows=max(0, len(df) - len(rows)),
            imported_by=imported_by,
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "sheet": sheet_name,
        "source_file": source_file,
        "total_rows": len(df),
        "saved_rows": len(rows),
        "invalid_rows": max(0, len(df) - len(rows)),
    }


def _load_province_region_dataframe(file_path: str) -> tuple[pd.DataFrame, str, list[str]]:
    xls = pd.ExcelFile(file_path)
    sheet_name = next((name for name in PROVINCE_REGION_SHEET_CANDIDATES if name in xls.sheet_names), None)
    if sheet_name is None:
        sheet_name = xls.sheet_names[0] if xls.sheet_names else None
    if not sheet_name:
        raise ValueError("File Excel không có sheet dữ liệu.")

    df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in PROVINCE_REGION_REQUIRED_COLUMNS if c not in df.columns]
    return df, sheet_name, missing


def _province_region_rows_from_dataframe(df: pd.DataFrame) -> tuple[list[dict], int]:
    rows: list[dict] = []
    invalid_rows = 0
    if df.empty:
        return rows, invalid_rows

    work = df.copy().replace(r"^\s*$", pd.NA, regex=True)
    seen_names: set[str] = set()

    for _, row in work.iterrows():
        province_name = safe_text(row.get("province_name"))
        region_code = safe_text(row.get("mien_code"))
        region_name = safe_text(row.get("mien"))
        if not province_name or not region_code or not region_name or region_code not in PROVINCE_REGION_CODES:
            invalid_rows += 1
            continue

        key = province_name.strip().lower()
        if key in seen_names:
            invalid_rows += 1
            continue
        seen_names.add(key)

        aliases_raw = safe_text(row.get("aliases")) or ""
        aliases = [item.strip() for item in aliases_raw.split("|") if item.strip()]
        rows.append({
            "province_code": safe_text(row.get("province_code")) or "",
            "province_name": province_name,
            "mien_code": region_code,
            "mien": region_name,
            "aliases": aliases,
        })

    return rows, invalid_rows


def preview_province_regions_file(file_path: str) -> dict:
    df, sheet_name, missing = _load_province_region_dataframe(file_path)
    sample_cols = PROVINCE_REGION_REQUIRED_COLUMNS + PROVINCE_REGION_OPTIONAL_COLUMNS
    existing_sample_cols = [c for c in sample_cols if c in df.columns]
    rows: list[dict] = []
    invalid_rows = len(df)
    if not missing:
        rows, invalid_rows = _province_region_rows_from_dataframe(df)

    return {
        "sheet": sheet_name,
        "columns": list(df.columns),
        "required_columns": PROVINCE_REGION_REQUIRED_COLUMNS,
        "missing_columns": missing,
        "total_rows": int(len(df)),
        "valid_rows": int(len(rows)),
        "invalid_rows": int(invalid_rows),
        "sample_rows": df.head(10)[existing_sample_cols].fillna("").astype(str).to_dict(orient="records"),
    }


def import_province_regions_file(
    db: Session,
    file_path: str,
    source_file: str,
    output_json_path: str,
    imported_by: str | None = None,
) -> dict:
    df, sheet_name, missing = _load_province_region_dataframe(file_path)
    if missing:
        raise ValueError(f"File thiếu các cột bắt buộc: {missing}. Cột trong file: {list(df.columns)}")

    rows, invalid_rows = _province_region_rows_from_dataframe(df)
    if not rows:
        raise ValueError("File không có dòng phân miền tỉnh/thành hợp lệ.")

    output_path = Path(output_json_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_name(f".{output_path.name}.tmp")
    temp_output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        log = ImportLog(
            file_name=source_file,
            data_type="province_regions",
            total_rows=len(df),
            valid_rows=len(rows),
            invalid_rows=invalid_rows,
            imported_by=imported_by,
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()
        try:
            temp_output_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    temp_output_path.replace(output_path)
    clear_area_lookup_caches()

    return {
        "sheet": sheet_name,
        "source_file": source_file,
        "total_rows": len(df),
        "saved_rows": len(rows),
        "invalid_rows": invalid_rows,
        "json_file": str(output_path),
    }


def get_predict_disease_codes(db: Session) -> tuple[pd.DataFrame, str]:
    """
    Lấy DS-MaBenh người dùng đã import để xử lý DS-BenhNhan.
    Không fallback sang dữ liệu train của model để tránh trộn dữ liệu model và dữ liệu người dùng.
    """
    user_codes = db.query(DiseaseCode).all()
    if user_codes:
        return _codes_to_dataframe(user_codes), "user_disease_codes"

    raise ValueError(
        "Chưa có bảng mã bệnh (DS-MaBenh) trong hệ thống. "
        "Hãy import DS-MaBenh trước, sau đó mới import DS-BenhNhan."
    )


def _build_patient_rows(df: pd.DataFrame, data_type: str, source_file: str) -> list[dict]:
    patient_rows = []

    for _, row in df.iterrows():
        patient_rows.append({
            "data_type": data_type,
            "source_file": source_file,
            "icd_admission": safe_text(row.get("icdNV")),
            "icd_discharge": safe_text(row.get("icdxuatvien")),
            "main_icd": safe_text(row.get("main_icd")),
            "check_in_date": safe_datetime(row.get("check_in_date")),
            "date_of_birth": safe_datetime(row.get("date_of_birth")),
            "age": safe_float(row.get("age")),
            "age_group": safe_text(row.get("age_group")),
            "month_age": safe_int(row.get("month_age")),
            "gender": safe_text(row.get("gender")),
            "province_code": safe_text(row.get("province_code")),
            "province_name": safe_text(row.get("province_name")),
            "district_code": safe_text(row.get("district_code")),
            "district_name": safe_text(row.get("district_name")),
            "ward_code": safe_text(row.get("ward_code")),
            "ward_name": safe_text(row.get("ward_name")),
            "year": safe_int(row.get("year")),
            "month": safe_int(row.get("month_num")),
            "period": safe_text(row.get("period")),
            "season": safe_text(row.get("season")),
            "disease_name": safe_text(row.get("disease_name")),
            "disease_group": safe_text(row.get("disease_group")),
        })

    return patient_rows


def _build_monthly_stat_rows(monthly_stats: pd.DataFrame, data_type: str) -> list[dict]:
    stat_rows = []

    for _, row in monthly_stats.iterrows():
        stat_rows.append({
            "data_type": data_type,
            "period": row["period"],
            "year": int(row["year"]),
            "month": int(row["month"]),
            "season": row["season"],
            "disease_group": row["disease_group"],
            "age_group": row["age_group"],
            "case_count": int(row["case_count"]),
        })

    return stat_rows


def import_patient_file(
    db: Session,
    file_path: str,
    data_type: str,
    source_file: str,
    imported_by: str | None = None,
    import_codes: bool = False,
    save_patient_records: bool = True,
):
    """
    Import DS-BenhNhan người dùng để phân tích/dashboard/forecast.

    Lưu ý: train_history của model dự báo tháng tiếp theo KHÔNG import qua API nữa.
    Train data của model nằm cố định trong app/ml/seasonal_forecast_data/train_history.xlsx.
    """
    if import_codes or data_type == "train_history":
        raise ValueError(
            "Không import train_history qua API nữa. "
            "Dữ liệu train của model nằm cố định tại app/ml/seasonal_forecast_data/train_history.xlsx."
        )

    disease_codes, disease_codes_source = get_predict_disease_codes(db)

    # Parse/validate trước để file lỗi thì dữ liệu cũ không bị xoá.
    df = process_patients(file_path, disease_codes)
    df = attach_patient_areas(db, df)
    if df.empty:
        raise ValueError(
            "File không chứa dòng dữ liệu hợp lệ sau khi xử lý "
            "(thiếu ngày khám hoặc mã bệnh chính). Dữ liệu cũ được giữ nguyên."
        )

    monthly_stats = create_monthly_stats(df)
    if monthly_stats.empty:
        raise ValueError("Không tạo được monthly_statistics từ file này. Dữ liệu cũ được giữ nguyên.")

    patient_rows = _build_patient_rows(df, data_type, source_file) if save_patient_records else []
    stat_rows = _build_monthly_stat_rows(monthly_stats, data_type)

    try:
        clear_data_type(db, data_type, commit=False)

        if patient_rows:
            db.bulk_insert_mappings(PatientRecord, patient_rows)

        if stat_rows:
            db.bulk_insert_mappings(MonthlyStatistic, stat_rows)

        log = ImportLog(
            file_name=source_file,
            data_type=data_type,
            total_rows=len(df),
            valid_rows=len(df),
            invalid_rows=0,
            imported_by=imported_by,
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "data_type": data_type,
        "source_file": source_file,
        "disease_codes_source": disease_codes_source,
        "processed_patient_rows": len(df),
        "saved_patient_records": len(patient_rows),
        "monthly_rows": len(monthly_stats),
        "from_period": df["period"].min() if len(df) > 0 else None,
        "to_period": df["period"].max() if len(df) > 0 else None,
    }
