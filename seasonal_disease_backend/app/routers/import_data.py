from pathlib import Path
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models import DiseaseCode, DiseaseKnowledge, PatientRecord, User
from app.security import get_current_user, require_permission
from app.services.import_service import (
    import_disease_codes,
    import_parent_guide_file,
    import_patient_file,
    preview_parent_guide_file,
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
PREPROCESS_DIR = UPLOAD_DIR / "preprocessed"

UPLOAD_DIR.mkdir(exist_ok=True)
PREDICT_CURRENT_DIR.mkdir(exist_ok=True)
DISEASE_CODES_DIR.mkdir(exist_ok=True)
PARENT_GUIDE_DIR.mkdir(exist_ok=True)
PREPROCESS_DIR.mkdir(exist_ok=True)


def _safe_upload_name(upload_file: UploadFile) -> str:
    return Path(upload_file.filename or "upload.xlsx").name


def _is_excel_upload(upload_file: UploadFile) -> bool:
    return _safe_upload_name(upload_file).lower().endswith(".xlsx")


def save_file_to_dir(upload_file: UploadFile, target_dir: Path) -> str:
    """Lưu file vào thư mục chỉ định."""
    file_path = target_dir / _safe_upload_name(upload_file)

    with open(file_path, "wb") as f:
        f.write(upload_file.file.read())

    return str(file_path)


def save_file_single(upload_file: UploadFile, target_dir: Path) -> str:
    """
    Lưu file vào thư mục chỉ định, xoá tất cả file cũ trong thư mục đó.
    Chỉ giữ 1 file mới nhất.
    """
    # Xoá file cũ
    for old_file in target_dir.iterdir():
        if old_file.is_file():
            old_file.unlink()

    file_path = target_dir / _safe_upload_name(upload_file)

    with open(file_path, "wb") as f:
        f.write(upload_file.file.read())

    return str(file_path)


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

    file_path = save_file_single(file, PREDICT_CURRENT_DIR)

    try:
        result = import_patient_file(
            db=db,
            file_path=file_path,
            data_type="predict_current",
            source_file=_safe_upload_name(file),
            imported_by=current_user.username,
            import_codes=False,
        )
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    """
    Import riêng file DS-MaBenh (.xlsx có sheet DS-MaBenh).
    Dùng khi cần cập nhật bảng mã bệnh mới (có nhóm bệnh mới xuất hiện).
    File cũ sẽ bị xoá, chỉ giữ file mới nhất.
    """
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    file_path = save_file_single(file, DISEASE_CODES_DIR)

    try:
        disease_codes = import_disease_codes(db, file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": "Import bảng mã bệnh (DS-MaBenh) thành công.",
        "total_codes": len(disease_codes),
        "file": _safe_upload_name(file),
    }


@router.post("/parent-guide/preview")
def preview_parent_guide_endpoint(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Preview Excel file for parent-facing disease guidance before importing."""
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    file_path = save_file_to_dir(file, PARENT_GUIDE_DIR)
    try:
        return preview_parent_guide_file(file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/parent-guide")
def import_parent_guide_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import parent-facing disease guidance into disease_knowledge."""
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    file_path = save_file_single(file, PARENT_GUIDE_DIR)
    try:
        result = import_parent_guide_file(db, file_path, _safe_upload_name(file), current_user.username)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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


@router.get("/model-data/status")
def get_model_data_status(
    current_user: User = Depends(get_current_user),
):
    """
    Kiểm tra file train_history.xlsx cố định đi kèm model dự báo tháng tiếp theo.

    Quy ước mới: 1 model dự báo tháng tiếp theo đi kèm 1 file Excel train_history.xlsx,
    trong đó có 2 sheet: DS-BenhNhan và DS-MaBenh. File này không import qua API,
    không lưu vào DB, và nằm cạnh model tại app/ml/seasonal_forecast_data/.
    """
    model_data_dir = Path("app/ml/seasonal_forecast_data")
    train_history_file = model_data_dir / "train_history.xlsx"

    sheets = []
    valid_structure = False
    error = None

    if train_history_file.exists():
        try:
            import pandas as pd
            xls = pd.ExcelFile(train_history_file)
            sheets = xls.sheet_names
            valid_structure = "DS-BenhNhan" in sheets and "DS-MaBenh" in sheets
        except Exception as e:
            error = str(e)

    return {
        "has_model_train_file": train_history_file.exists(),
        "source": "single_excel_file",
        "model_data_dir": str(model_data_dir),
        "train_history_file": str(train_history_file),
        "required_sheets": ["DS-BenhNhan", "DS-MaBenh"],
        "sheets": sheets,
        "valid_structure": valid_structure,
        "error": error,
        "note": "Forecast model đọc train_history.xlsx trực tiếp từ thư mục này; không dùng bảng model_disease_codes/model_metadata trong DB nữa.",
    }


# =========================================================
# Compatibility endpoints cho frontend từ ThucTap-main
# =========================================================
@router.post("/data", include_in_schema=False)
def import_data_for_frontend(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint tương thích với frontend.

    Frontend cũ chỉ upload 1 file dữ liệu. Với backend hiện tại, file này được
    xem là dữ liệu người dùng hiện tại để dashboard/forecast phân tích, nên lưu
    vào data_type='predict_current'. Nếu file có sheet DS-MaBenh thì cập nhật
    disease_codes trước; nếu không có thì dùng disease_codes đã có trong DB.
    """
    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    file_path = save_file_single(file, PREDICT_CURRENT_DIR)

    # Nếu file có DS-MaBenh thì import bảng mã bệnh người dùng. Nếu không có,
    # bỏ qua để import_patient_file dùng DS-MaBenh đã có trong DB.
    disease_codes_updated = False
    try:
        import_disease_codes(db, file_path)
        disease_codes_updated = True
    except Exception:
        disease_codes_updated = False

    try:
        result = import_patient_file(
            db=db,
            file_path=file_path,
            data_type="predict_current",
            source_file=_safe_upload_name(file),
            imported_by=current_user.username,
            import_codes=False,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": "Import dữ liệu thành công.",
        "disease_codes_updated": disease_codes_updated,
        "result": result,
    }


@router.post("/weather", include_in_schema=False)
def import_weather_for_frontend(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint tương thích với nút upload weather của frontend.

    Weather AI realtime hiện tại tự lấy dữ liệu Open-Meteo, không cần import
    weather vào DB. Endpoint này chỉ lưu file để người dùng không bị lỗi UI,
    đồng thời đọc nhanh số dòng/ngày để trả thông tin.
    """
    name = (file.filename or "").lower()
    if not (name.endswith(".csv") or name.endswith(".xlsx")):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .csv hoặc .xlsx.")

    weather_dir = UPLOAD_DIR / "weather"
    weather_dir.mkdir(exist_ok=True)
    file_path = save_file_single(file, weather_dir)

    rows = 0
    from_date = None
    to_date = None
    try:
        import pandas as pd
        if name.endswith(".csv"):
            df = pd.read_csv(file_path, comment="#")
        else:
            df = pd.read_excel(file_path)
        rows = len(df)
        date_col = "time" if "time" in df.columns else ("date" if "date" in df.columns else None)
        if date_col:
            dates = pd.to_datetime(df[date_col], errors="coerce")
            dates = dates.dropna()
            if not dates.empty:
                from_date = dates.min().strftime("%Y-%m-%d")
                to_date = dates.max().strftime("%Y-%m-%d")
    except Exception:
        # Vẫn coi upload thành công vì weather AI realtime không phụ thuộc file này.
        pass

    return {
        "message": "Upload file thời tiết thành công. Weather AI realtime vẫn tự lấy Open-Meteo khi dự đoán.",
        "result": {
            "rows": rows,
            "from_date": from_date,
            "to_date": to_date,
            "file": _safe_upload_name(file),
        },
    }


@router.post("/preprocess")
def preprocess_patient_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Tiền xử lý file DS-BenhNhan từ server bệnh viện.
    - Chỉ giữ các cột cần thiết: icdNV, icdxuatvien, check_in_date, date_of_birth, month, gender
    - Bỏ các dòng thiếu ngày khám (check_in_date)
    - Bỏ các dòng thiếu cả 2 mã ICD (icdNV và icdxuatvien đều rỗng)
    - Bỏ các cột không có dữ liệu (toàn null)
    - Trả về file .xlsx đã xử lý, sẵn sàng import vào hệ thống.
    """
    import pandas as pd
    import tempfile

    if not _is_excel_upload(file):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx.")

    try:
        xls = pd.ExcelFile(file.file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Không đọc được file Excel: {e}")

    # Tìm sheet bệnh nhân
    patient_candidates = ["DS-BenhNhan", "DS_BenhNhan", "BenhNhan", "Sheet1"]
    sheet_name = None
    for name in patient_candidates:
        if name in xls.sheet_names:
            sheet_name = name
            break

    if not sheet_name:
        raise HTTPException(
            status_code=400,
            detail=f"Không tìm thấy sheet bệnh nhân. "
                   f"Đã thử: {patient_candidates}. "
                   f"Sheet trong file: {xls.sheet_names}."
        )

    df = pd.read_excel(xls, sheet_name=sheet_name)
    original_rows = len(df)
    original_cols = list(df.columns)

    # Các cột hệ thống cần
    required_cols = ["icdNV", "icdxuatvien", "check_in_date", "date_of_birth", "month", "gender"]

    # Kiểm tra file có đủ cột cần thiết
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        raise HTTPException(
            status_code=400,
            detail=f"File thiếu các cột bắt buộc: {missing_cols}. "
                   f"Cột trong file: {list(df.columns)}"
        )

    # Chỉ giữ cột cần thiết
    df = df[required_cols].copy()

    # Chuẩn hoá: ô trống (chuỗi rỗng, khoảng trắng) → null
    df = df.replace(r'^\s*$', pd.NA, regex=True)

    # Bỏ dòng trống hoàn toàn (tất cả cột đều null)
    before_empty = len(df)
    df = df.dropna(how="all")
    removed_empty_rows = before_empty - len(df)

    # Bỏ dòng thiếu ngày khám
    before_check_in = len(df)
    df = df.dropna(subset=["check_in_date"])
    removed_no_checkin = before_check_in - len(df)

    # Bỏ dòng thiếu cả 2 mã ICD
    before_icd = len(df)
    df = df.dropna(subset=["icdNV", "icdxuatvien"], how="all")
    removed_no_icd = before_icd - len(df)

    # Bỏ cột toàn null (nếu có)
    cols_before = list(df.columns)
    df = df.dropna(axis=1, how="all")
    removed_cols = [c for c in cols_before if c not in df.columns]

    # Xoá file preprocessed cũ, chỉ giữ file mới nhất
    for old_file in PREPROCESS_DIR.iterdir():
        if old_file.is_file():
            old_file.unlink()

    output_filename = f"preprocessed_{Path(_safe_upload_name(file)).stem}.xlsx"
    output_path = PREPROCESS_DIR / output_filename

    df.to_excel(str(output_path), index=False, sheet_name="DS-BenhNhan")

    return {
        "message": "Tiền xử lý thành công.",
        "original_rows": original_rows,
        "original_columns": original_cols,
        "result_rows": len(df),
        "result_columns": list(df.columns),
        "removed_empty_rows": removed_empty_rows,
        "removed_no_check_in_date": removed_no_checkin,
        "removed_no_icd": removed_no_icd,
        "removed_columns_all_null": removed_cols,
        "download_url": f"/api/import/preprocess/download/{output_filename}",
    }


@router.get("/preprocess/download/{filename}")
def download_preprocessed_file(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Download preprocessed file."""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.startswith("preprocessed_") or not safe_name.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="File khong hop le.")

    file_path = (PREPROCESS_DIR / safe_name).resolve()
    if PREPROCESS_DIR.resolve() not in file_path.parents:
        raise HTTPException(status_code=400, detail="File khong hop le.")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File khong ton tai.")

    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
