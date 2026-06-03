# app/services/data_processing_service.py
import numpy as np
import pandas as pd

# ===== Tên cột trong sheet bệnh nhân =====
ICD_ADMISSION_COL = "icdNV"
ICD_DISCHARGE_COL = "icdxuatvien"
CHECK_IN_DATE_COL = "check_in_date"
DATE_OF_BIRTH_COL = "date_of_birth"
GENDER_COL = "gender"
MONTH_AGE_COL = "month"  # số tháng tuổi đọc từ file Excel

# ===== Tên cột trong sheet danh mục mã bệnh =====
ICD_CODE_COL = "MAICD"
DISEASE_NAME_COL = "TENICD"
DISEASE_GROUP_COL = "TENNHOMICD"

# ===== Danh sách tên sheet có thể gặp trong file =====
PATIENT_SHEET_CANDIDATES = ["DS-BenhNhan", "DS_BenhNhan", "BenhNhan", "Sheet1"]
DISEASE_SHEET_CANDIDATES = ["DS-MaBenh", "DS_MaBenh", "MaBenh"]


# =========================================================
# HÀM ĐỌC SHEET LINH HOẠT
# =========================================================
def _read_sheet_flexible(file_path: str, candidates: list[str]) -> pd.DataFrame:
    """
    Thử đọc lần lượt các tên sheet trong danh sách candidates.
    Nếu không khớp tên nào, raise lỗi kèm danh sách sheet thực tế trong file.
    """
    xls = pd.ExcelFile(file_path)
    available = xls.sheet_names

    for name in candidates:
        if name in available:
            return pd.read_excel(xls, sheet_name=name)

    raise ValueError(
        f"Không tìm thấy sheet phù hợp. Đã thử: {candidates}. "
        f"Sheet thực tế trong file: {available}."
    )


# =========================================================
# CÁC HÀM TIỀN XỬ LÝ
# =========================================================
def parse_excel_date_value(x):
    if pd.isna(x):
        return pd.NaT

    if isinstance(x, pd.Timestamp):
        return pd.to_datetime(x)

    try:
        num = float(x)
        if 20000 <= num <= 80000:
            return pd.to_datetime("1899-12-30") + pd.to_timedelta(num, unit="D")
    except Exception:
        pass

    return pd.to_datetime(x, errors="coerce", dayfirst=True)


def parse_mixed_excel_date(series):
    return series.apply(parse_excel_date_value)


def normalize_icd(x):
    if pd.isna(x):
        return np.nan
    return str(x).strip().upper()


def parse_month_age(value):
    """
    Đọc số tháng tuổi từ file Excel.
    - Giá trị 0 vẫn hợp lệ (trẻ chưa đủ 1 tháng tuổi).
    - NaN, chuỗi rỗng, giá trị âm hoặc không parse được số -> coi là không rõ (NaN).
    """
    if pd.isna(value):
        return np.nan

    if isinstance(value, str) and value.strip() == "":
        return np.nan

    try:
        m = int(float(value))
    except (ValueError, TypeError):
        return np.nan

    if m < 0:
        return np.nan

    return m


def calculate_age_years(check_in_date, date_of_birth):
    if pd.isna(check_in_date) or pd.isna(date_of_birth):
        return np.nan

    age = (check_in_date - date_of_birth).days / 365.25
    if age < 0:
        return np.nan

    return age


def to_age_group(age):
    if pd.isna(age):
        return "Không rõ"
    if age < 1:
        return "Dưới 1 tuổi"
    if age <= 5:
        return "1-5 tuổi"
    if age <= 10:
        return "6-10 tuổi"
    if age <= 15:
        return "11-15 tuổi"
    return "Trên 15 tuổi"


def month_to_season_vn(month):
    if month in [12, 1, 2, 3, 4]:
        return "Mùa khô"
    if month in [5, 6, 7, 8, 9, 10, 11]:
        return "Mùa mưa"
    return "Không rõ"


# =========================================================
# ĐỌC DANH MỤC MÃ BỆNH
# =========================================================
def load_disease_codes(file_path: str) -> pd.DataFrame:
    disease_codes = _read_sheet_flexible(file_path, DISEASE_SHEET_CANDIDATES)
    disease_codes[ICD_CODE_COL] = disease_codes[ICD_CODE_COL].apply(normalize_icd)
    return disease_codes


# =========================================================
# XỬ LÝ DANH SÁCH BỆNH NHÂN
# =========================================================
def process_patients(file_path: str, disease_codes: pd.DataFrame) -> pd.DataFrame:
    patients = _read_sheet_flexible(file_path, PATIENT_SHEET_CANDIDATES)

    # Parse ngày tháng (kể cả ngày dạng số Excel)
    patients[CHECK_IN_DATE_COL] = parse_mixed_excel_date(patients[CHECK_IN_DATE_COL])
    patients[DATE_OF_BIRTH_COL] = parse_mixed_excel_date(patients[DATE_OF_BIRTH_COL])

    # Chuẩn hoá mã ICD
    patients[ICD_ADMISSION_COL] = patients[ICD_ADMISSION_COL].apply(normalize_icd)
    patients[ICD_DISCHARGE_COL] = patients[ICD_DISCHARGE_COL].apply(normalize_icd)

    # Ưu tiên ICD xuất viện, không có thì dùng ICD nhập viện
    patients["main_icd"] = patients[ICD_DISCHARGE_COL].fillna(patients[ICD_ADMISSION_COL])
    patients["main_icd"] = patients["main_icd"].apply(normalize_icd)

    # Đọc cột số tháng tuổi - chấp nhận giá trị 0
    if MONTH_AGE_COL in patients.columns:
        patients["month_age"] = patients[MONTH_AGE_COL].apply(parse_month_age)
    else:
        patients["month_age"] = np.nan

    # Ghép với danh mục bệnh để lấy tên bệnh + nhóm bệnh
    df = patients.merge(
        disease_codes,
        left_on="main_icd",
        right_on=ICD_CODE_COL,
        how="left"
    )

    # Tính tuổi (theo năm) và nhóm tuổi
    df["age"] = df.apply(
        lambda row: calculate_age_years(row[CHECK_IN_DATE_COL], row[DATE_OF_BIRTH_COL]),
        axis=1
    )
    df["age_group"] = df["age"].apply(to_age_group)

    # Tách năm/tháng/period/season từ ngày khám
    df["year"] = df[CHECK_IN_DATE_COL].dt.year
    df["month_num"] = df[CHECK_IN_DATE_COL].dt.month
    df["period"] = df[CHECK_IN_DATE_COL].dt.to_period("M").astype(str)
    df["season"] = df["month_num"].apply(month_to_season_vn)

    # Tên bệnh và nhóm bệnh
    df["disease_name"] = df[DISEASE_NAME_COL].fillna("Không rõ bệnh")
    df["disease_group"] = df[DISEASE_GROUP_COL].fillna("Không rõ nhóm bệnh")

    # Giới tính
    df[GENDER_COL] = df[GENDER_COL].fillna("Không rõ").astype(str).str.strip()

    # Loại các dòng thiếu ngày khám hoặc mã bệnh chính.
    # Cột month_age được phép null (không bắt buộc), không đưa vào subset.
    df = df.dropna(subset=[CHECK_IN_DATE_COL, "main_icd"])

    return df


# =========================================================
# TỔNG HỢP THỐNG KÊ THEO THÁNG
# =========================================================
def create_monthly_stats(df: pd.DataFrame) -> pd.DataFrame:
    monthly_stats = (
        df.groupby(["period", "year", "month_num", "season", "disease_group", "age_group"])
        .size()
        .reset_index(name="case_count")
    )

    monthly_stats = monthly_stats.rename(columns={"month_num": "month"})

    return monthly_stats
