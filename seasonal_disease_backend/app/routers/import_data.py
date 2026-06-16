from pathlib import Path
import json
import shutil
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models import DiseaseCode, DiseaseKnowledge, ImportLog, MonthlyStatistic, PatientRecord, User
from app.security import get_current_user, require_permission
from app.services.import_service import (
    import_disease_codes,
    import_parent_guide_file,
    import_patient_file,
    import_province_regions_file,
    preview_parent_guide_file,
    preview_province_regions_file,
)
from app.services.import_job_state import (
    finish_import_job,
    get_import_job_status,
    start_import_job,
)

router = APIRouter(
    prefix="/api/import",
    tags=["Import"],
    dependencies=[Depends(require_permission("feature.data_import"))],
)

# Thư mục upload riêng cho từng loại file
UPLOAD_DIR = Path("uploads")
PREDICT_CURRENT_DIR = UPLOAD_DIR / "predict_current"
DISEASE_CODES_DIR = UPLOAD_DIR / "disease_codes"
PARENT_GUIDE_DIR = UPLOAD_DIR / "parent_guide"
PROVINCE_REGIONS_DIR = UPLOAD_DIR / "province_regions"
PROVINCE_REGIONS_EXCEL_DIR = PROVINCE_REGIONS_DIR / "excel"
TEMP_UPLOAD_DIR = UPLOAD_DIR / "_tmp"
PROVINCE_REGIONS_JSON = PROVINCE_REGIONS_DIR / "province_regions.json"
PREDICT_CURRENT_META = PREDICT_CURRENT_DIR / "latest_import.json"

UPLOAD_DIR.mkdir(exist_ok=True)
PREDICT_CURRENT_DIR.mkdir(exist_ok=True)
DISEASE_CODES_DIR.mkdir(exist_ok=True)
PARENT_GUIDE_DIR.mkdir(exist_ok=True)
PROVINCE_REGIONS_DIR.mkdir(exist_ok=True)
PROVINCE_REGIONS_EXCEL_DIR.mkdir(exist_ok=True)
TEMP_UPLOAD_DIR.mkdir(exist_ok=True)


def _safe_upload_name(upload_file: UploadFile) -> str:
    return Path(upload_file.filename or "upload.xlsx").name


def _is_excel_upload(upload_file: UploadFile) -> bool:
    return _safe_upload_name(upload_file).lower().endswith(".xlsx")


def save_file_temp(upload_file: UploadFile) -> Path:
    """Luu file upload vao thu muc tam; chi thay file chinh sau khi import hop le."""
    safe_name = _safe_upload_name(upload_file)
    suffix = Path(safe_name).suffix or ".upload"
    temp_path = TEMP_UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    upload_file.file.seek(0)
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(upload_file.file, f)
    return temp_path


def replace_single_file_from_path(source_path: Path, target_dir: Path, filename: str) -> str:
    """Thay file dang luu bang file da duoc validate/import thanh cong."""
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / Path(filename).name
    staged_path = target_dir / f".{target_path.name}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copy2(source_path, staged_path)
        staged_path.replace(target_path)
    finally:
        if staged_path.exists():
            staged_path.unlink(missing_ok=True)

    for old_file in target_dir.iterdir():
        if old_file.is_file() and old_file != target_path:
            old_file.unlink()
    return str(target_path)


def record_predict_current_import(filename: str) -> None:
    """Ghi ten file DS-BenhNhan vua import, khong giu lai file Excel goc."""
    PREDICT_CURRENT_DIR.mkdir(parents=True, exist_ok=True)

    for old_file in PREDICT_CURRENT_DIR.iterdir():
        if old_file.is_file() and old_file != PREDICT_CURRENT_META:
            old_file.unlink(missing_ok=True)

    payload = {
        "uploaded_file": Path(filename).name,
        "imported_at": datetime.utcnow().isoformat(),
    }
    staged_path = PREDICT_CURRENT_DIR / f".{PREDICT_CURRENT_META.name}.{uuid.uuid4().hex}.tmp"
    staged_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    staged_path.replace(PREDICT_CURRENT_META)


def read_predict_current_import_meta() -> dict:
    try:
        return json.loads(PREDICT_CURRENT_META.read_text(encoding="utf-8"))
    except Exception:
        return {}


def cleanup_temp_file(file_path: Path | None) -> None:
    if not file_path:
        return
    try:
        file_path.unlink(missing_ok=True)
    except Exception:
        pass


@router.get("/job-status")
def import_job_status(
    current_user: User = Depends(get_current_user),
):
    return get_import_job_status()


@router.post("/predict-current")
def import_predict_current(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Import file predict_current.xlsx (chỉ cần sheet DS-BenhNhan).
    File này dùng để phân tích và dự đoán ca bệnh tháng tiếp theo.
    Yêu cầu: import DS-MaBenh của người dùng qua /api/import/disease-codes trước.
    """
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    # Kiểm tra có DS-MaBenh người dùng để map ICD -> nhóm bệnh.
    # Dữ liệu train của model nằm riêng trong app/ml/seasonal_forecast_data,
    # không dùng để map dữ liệu người dùng hiện tại.
    user_codes_count = db.query(DiseaseCode).count()
    if user_codes_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Chưa có bảng mã bệnh (DS-MaBenh) trong hệ thống. "
                   "Hãy import DS-MaBenh trước, sau đó mới import DS-BenhNhan."
        )

    safe_name = _safe_upload_name(file)
    try:
        job = start_import_job("patient", "DS-BenhNhan", safe_name, current_user.username)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    temp_path = None
    try:
        temp_path = save_file_temp(file)
        result = import_patient_file(
            db=db,
            file_path=str(temp_path),
            data_type="predict_current",
            source_file=safe_name,
            imported_by=current_user.username,
            import_codes=False,
        )
        record_predict_current_import(safe_name)
    except Exception as e:
        finish_import_job(job["id"], success=False, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cleanup_temp_file(temp_path)

    finish_import_job(job["id"], success=True)

    return {
        "message": "Import dữ liệu predict_current thành công.",
        "result": result,
    }


@router.post("/disease-codes")
def import_disease_codes_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import riêng file DS-MaBenh và chỉ lưu file sau khi validate thành công."""
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    safe_name = _safe_upload_name(file)
    try:
        job = start_import_job("disease-codes", "DS-MaBenh", safe_name, current_user.username)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    temp_path = None
    try:
        temp_path = save_file_temp(file)
        disease_codes = import_disease_codes(db, str(temp_path))
        replace_single_file_from_path(temp_path, DISEASE_CODES_DIR, safe_name)
    except Exception as e:
        finish_import_job(job["id"], success=False, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cleanup_temp_file(temp_path)

    finish_import_job(job["id"], success=True)

    return {
        "message": "Import bảng mã bệnh (DS-MaBenh) thành công.",
        "total_codes": len(disease_codes),
        "file": safe_name,
    }

@router.post("/parent-guide/preview")
def preview_parent_guide_endpoint(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Preview Excel file for parent-facing disease guidance before importing."""
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    temp_path = save_file_temp(file)
    try:
        return preview_parent_guide_file(str(temp_path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cleanup_temp_file(temp_path)


@router.post("/parent-guide")
def import_parent_guide_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import parent-facing disease guidance into disease_knowledge."""
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    temp_path = save_file_temp(file)
    try:
        result = import_parent_guide_file(db, str(temp_path), _safe_upload_name(file), current_user.username)
        replace_single_file_from_path(temp_path, PARENT_GUIDE_DIR, _safe_upload_name(file))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cleanup_temp_file(temp_path)

    return {
        "message": "Import hướng dẫn phụ huynh thành công.",
        "result": result,
    }


@router.get("/parent-guide/status")
def get_parent_guide_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total = db.query(DiseaseKnowledge).count()
    files_in_dir = [f.name for f in PARENT_GUIDE_DIR.iterdir() if f.is_file()]
    return {
        "has_parent_guide": total > 0,
        "total_rows": total,
        "uploaded_file": files_in_dir[0] if files_in_dir else None,
    }


@router.get("/parent-guide")
def list_parent_guide(
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(DiseaseKnowledge)
    if search:
        kw = f"%{search.strip()}%"
        query = query.filter(
            or_(
                DiseaseKnowledge.disease_group.ilike(kw),
                DiseaseKnowledge.symptoms.ilike(kw),
                DiseaseKnowledge.warning_signs.ilike(kw),
                DiseaseKnowledge.prevention.ilike(kw),
            )
        )

    total = query.count()
    rows = query.order_by(DiseaseKnowledge.disease_group.asc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "rows": [
            {
                "id": r.id,
                "disease_group": r.disease_group,
                "title": r.title,
                "symptoms": r.symptoms,
                "warning_signs": r.warning_signs,
                "prevention": r.prevention,
                "source": r.source,
            }
            for r in rows
        ],
    }


@router.post("/province-regions/preview")
def preview_province_regions_endpoint(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Preview Excel file for province/city to region mapping before importing."""
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    temp_path = save_file_temp(file)
    try:
        return preview_province_regions_file(str(temp_path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cleanup_temp_file(temp_path)


@router.post("/province-regions")
def import_province_regions_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import province/city to north/central/south mapping used by Area insights."""
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    temp_path = save_file_temp(file)
    try:
        result = import_province_regions_file(
            db=db,
            file_path=str(temp_path),
            source_file=_safe_upload_name(file),
            output_json_path=str(PROVINCE_REGIONS_JSON),
            imported_by=current_user.username,
        )
        replace_single_file_from_path(temp_path, PROVINCE_REGIONS_EXCEL_DIR, _safe_upload_name(file))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cleanup_temp_file(temp_path)

    return {
        "message": "Import phân miền tỉnh/thành thành công.",
        "result": result,
    }


@router.get("/province-regions/status")
def get_province_regions_status(
    current_user: User = Depends(get_current_user),
):
    uploaded_files = [
        f.name
        for f in PROVINCE_REGIONS_EXCEL_DIR.iterdir()
        if f.is_file() and f.suffix.lower() == ".xlsx"
    ]
    total_rows = 0
    if PROVINCE_REGIONS_JSON.exists():
        try:
            import json
            total_rows = len(json.loads(PROVINCE_REGIONS_JSON.read_text(encoding="utf-8")))
        except Exception:
            total_rows = 0

    return {
        "has_province_regions": PROVINCE_REGIONS_JSON.exists(),
        "total_rows": total_rows,
        "uploaded_file": uploaded_files[0] if uploaded_files else None,
    }


@router.get("/disease-codes/status")
def get_disease_codes_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Kiểm tra trạng thái bảng mã bệnh trong hệ thống.
    """
    total = db.query(DiseaseCode).count()

    # Kiểm tra file trong thư mục
    files_in_dir = [f.name for f in DISEASE_CODES_DIR.iterdir() if f.is_file()]

    # Lấy số nhóm bệnh phân biệt
    distinct_groups = db.query(DiseaseCode.group_name).distinct().count()

    return {
        "has_disease_codes": total > 0,
        "total_codes": total,
        "distinct_groups": distinct_groups,
        "uploaded_file": files_in_dir[0] if files_in_dir else None,
    }


@router.get("/patient-data/status")
def get_patient_data_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Kiem tra trang thai du lieu DS-BenhNhan da import cho dashboard/du bao.
    """
    patient_rows = db.query(PatientRecord).filter(PatientRecord.data_type == "predict_current").count()
    monthly_rows = db.query(MonthlyStatistic).filter(MonthlyStatistic.data_type == "predict_current").count()
    periods = (
        db.query(MonthlyStatistic.period)
        .filter(MonthlyStatistic.data_type == "predict_current")
        .distinct()
        .count()
    )
    latest_log = (
        db.query(ImportLog)
        .filter(ImportLog.data_type == "predict_current")
        .order_by(ImportLog.created_at.desc())
        .first()
    )
    import_meta = read_predict_current_import_meta()

    return {
        "has_patient_data": patient_rows > 0 or monthly_rows > 0,
        "patient_rows": patient_rows,
        "monthly_rows": monthly_rows,
        "periods": periods,
        "uploaded_file": import_meta.get("uploaded_file") or (latest_log.file_name if latest_log else None),
        "latest_import_file": import_meta.get("uploaded_file") or (latest_log.file_name if latest_log else None),
        "latest_import_at": import_meta.get("imported_at") or (latest_log.created_at.isoformat() if latest_log else None),
    }


@router.get("/disease-codes")
def list_disease_codes(
    search: str | None = Query(None, description="Tìm theo MAICD, tên bệnh, mã nhóm báo cáo hoặc tên nhóm bệnh"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    only_missing_group: bool = Query(False, description="Chỉ xem mã bệnh thiếu nhóm bệnh"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Danh sách DS-MaBenh người dùng đã import. Dùng cho frontend tìm kiếm/kiểm tra mã bệnh.
    """
    query = db.query(DiseaseCode)

    if only_missing_group:
        query = query.filter(
            or_(
                DiseaseCode.group_id.is_(None),
                DiseaseCode.group_id == "",
                DiseaseCode.group_name.is_(None),
                DiseaseCode.group_name == "",
            )
        )

    if search:
        kw = f"%{search.strip()}%"
        query = query.filter(
            or_(
                DiseaseCode.icd_code.ilike(kw),
                DiseaseCode.disease_name.ilike(kw),
                DiseaseCode.group_id.ilike(kw),
                DiseaseCode.group_name.ilike(kw),
                DiseaseCode.report_group_code.ilike(kw),
                DiseaseCode.english_name.ilike(kw),
            )
        )

    total = query.count()
    rows = query.order_by(DiseaseCode.icd_code.asc()).offset(offset).limit(limit).all()

    missing_group_total = db.query(DiseaseCode).filter(
        or_(
            DiseaseCode.group_id.is_(None),
            DiseaseCode.group_id == "",
            DiseaseCode.group_name.is_(None),
            DiseaseCode.group_name == "",
        )
    ).count()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "missing_group_total": missing_group_total,
        "rows": [
            {
                "id": r.id,
                "icd_code": r.icd_code,
                "disease_name": r.disease_name,
                "group_id": r.group_id,
                "group_name": r.group_name,
                "report_group_code": r.report_group_code,
                "english_name": r.english_name,
                "missing_group": not bool((r.group_id or "").strip()) or not bool((r.group_name or "").strip()),
            }
            for r in rows
        ],
    }
