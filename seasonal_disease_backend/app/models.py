from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(30), default="staff")  # admin / staff
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserPermission(Base):
    __tablename__ = "user_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    permission_code: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "permission_code", name="uq_user_permissions_user_code"),
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    birth_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AreaProvince(Base):
    __tablename__ = "area_provinces"

    code: Mapped[str] = mapped_column(String(20), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AreaDistrict(Base):
    __tablename__ = "area_districts"

    code: Mapped[str] = mapped_column(String(20), primary_key=True, index=True)
    province_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AreaWard(Base):
    __tablename__ = "area_wards"

    code: Mapped[str] = mapped_column(String(20), primary_key=True, index=True)
    district_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    province_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DiseaseCode(Base):
    __tablename__ = "disease_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    icd_code: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    disease_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    group_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_group_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    english_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("icd_code", name="uq_disease_codes_icd_code"),
    )

class PatientRecord(Base):
    __tablename__ = "patient_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    data_type: Mapped[str] = mapped_column(String(30), index=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)

    icd_admission: Mapped[str | None] = mapped_column(String(50), nullable=True)
    icd_discharge: Mapped[str | None] = mapped_column(String(50), nullable=True)
    main_icd: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)

    check_in_date: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    date_of_birth: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    age: Mapped[float | None] = mapped_column(Float, nullable=True)
    age_group: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)

    month_age: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)

    gender: Mapped[str | None] = mapped_column(String(50), nullable=True)

    province_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    province_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    district_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    district_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    ward_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    ward_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)

    year: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    month: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)  # tháng nhập viện
    period: Mapped[str | None] = mapped_column(String(7), index=True, nullable=True)
    season: Mapped[str | None] = mapped_column(String(50), nullable=True)

    disease_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    disease_group: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonthlyStatistic(Base):
    __tablename__ = "monthly_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    data_type: Mapped[str] = mapped_column(String(30), index=True)  # train_history / predict_current

    period: Mapped[str] = mapped_column(String(7), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    season: Mapped[str] = mapped_column(String(50))

    disease_group: Mapped[str] = mapped_column(Text, index=True)
    age_group: Mapped[str] = mapped_column(String(50), index=True)
    case_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ForecastResult(Base):
    __tablename__ = "forecast_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    forecast_period: Mapped[str] = mapped_column(String(7), index=True)
    disease_group: Mapped[str] = mapped_column(Text, index=True)
    age_group: Mapped[str] = mapped_column(String(50), index=True)

    previous_cases: Mapped[int] = mapped_column(Integer, default=0)
    predicted_cases: Mapped[int] = mapped_column(Integer, default=0)
    change_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    trend: Mapped[str] = mapped_column(String(100))
    risk_level: Mapped[str] = mapped_column(String(50), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class DiseaseKnowledge(Base):
    __tablename__ = "disease_knowledge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    disease_group: Mapped[str] = mapped_column(Text, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    symptoms: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning_signs: Mapped[str | None] = mapped_column(Text, nullable=True)
    prevention: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ImportLog(Base):
    __tablename__ = "import_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    data_type: Mapped[str] = mapped_column(String(30))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
