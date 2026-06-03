from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
import re
import unicodedata
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AreaDistrict, AreaProvince, AreaWard, DiseaseKnowledge, ForecastResult, PatientRecord, User
from app.security import require_admin_permission, require_permission
from app.services.area_service import (
    apply_area_filters,
    fill_known_province_coordinates,
    resolve_area,
    seed_default_areas,
    sync_areas_from_payload,
    sync_areas_from_url,
)
from app.services.weather_ai_service import predict_weather_risk

router = APIRouter(prefix="/api/areas", tags=["Areas"])

PROVINCE_REGIONS_JSON = Path("uploads") / "province_regions" / "province_regions.json"


class AreaUpsert(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=255)
    province_code: str | None = Field(None, max_length=20)
    district_code: str | None = Field(None, max_length=20)
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool = True


class AreaSyncPayload(BaseModel):
    source_url: str | None = None
    payload: dict[str, Any] | None = None


class AreaWeatherRiskPayload(BaseModel):
    age_group: str
    gender: str
    top_k: int = Field(5, ge=1, le=20)
    province_code: str | None = None
    district_code: str | None = None
    ward_code: str | None = None
    weather: dict[str, Any] | None = None


def _serialize_area(row) -> dict:
    return {
        "code": row.code,
        "name": row.name,
        "province_code": getattr(row, "province_code", None),
        "district_code": getattr(row, "district_code", None),
        "latitude": row.latitude,
        "longitude": row.longitude,
        "is_active": row.is_active,
    }


def _classify_area_risk(case_count: int, forecast_risk: str | None = None) -> str:
    if forecast_risk == "Cao":
        return "Cao"
    if forecast_risk == "Trung binh" or forecast_risk == "Trung bình":
        return "Trung bình"
    if case_count >= 20:
        return "Cao"
    if case_count >= 5:
        return "Trung bình"
    return "Thấp"


def _forecast_risk_map(db: Session) -> dict[str, str]:
    latest = db.query(func.max(ForecastResult.forecast_period)).scalar()
    if not latest:
        return {}
    rows = (
        db.query(ForecastResult.disease_group, ForecastResult.risk_level)
        .filter(ForecastResult.forecast_period == latest)
        .all()
    )
    rank = {"Cao": 3, "Trung bình": 2, "Thấp": 1}
    output: dict[str, str] = {}
    for disease_group, risk_level in rows:
        cur = output.get(disease_group)
        if cur is None or rank.get(risk_level, 0) > rank.get(cur, 0):
            output[disease_group] = risk_level
    return output


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFD", value.lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d")


def _split_guidance(value: str | None) -> list[str]:
    if not value:
        return []
    return [
        item.strip(" \t\r\n.-•")
        for item in re.split(r"\n|;|•", value)
        if item.strip(" \t\r\n.-•")
    ]


def _find_disease_knowledge(disease_group: str, rows: list[DiseaseKnowledge]) -> DiseaseKnowledge | None:
    target = _normalize_text(disease_group)
    if not target:
        return None
    for row in rows:
        source = _normalize_text(f"{row.disease_group} {row.title}")
        if target in source or source in target:
            return row
    return None


@router.get("/provinces")
def list_provinces(
    db: Session = Depends(get_db),
):
    fill_known_province_coordinates(db)
    rows = (
        db.query(AreaProvince)
        .filter(AreaProvince.is_active.is_(True))
        .order_by(AreaProvince.name.asc())
        .all()
    )
    return [_serialize_area(r) for r in rows]


@router.get("/province-regions")
def list_province_regions():
    if not PROVINCE_REGIONS_JSON.exists():
        raise HTTPException(status_code=404, detail="Chưa import file phân miền tỉnh/thành.")
    try:
        return json.loads(PROVINCE_REGIONS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Không đọc được file phân miền tỉnh/thành: {e}")


@router.get("/districts")
def list_districts(
    province_code: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(AreaDistrict).filter(AreaDistrict.is_active.is_(True))
    if province_code:
        query = query.filter(AreaDistrict.province_code == province_code)
    rows = query.order_by(AreaDistrict.name.asc()).all()
    return [_serialize_area(r) for r in rows]


@router.get("/wards")
def list_wards(
    district_code: str | None = Query(None),
    province_code: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(AreaWard).filter(AreaWard.is_active.is_(True))
    if district_code:
        query = query.filter(AreaWard.district_code == district_code)
    if province_code:
        query = query.filter(AreaWard.province_code == province_code)
    rows = query.order_by(AreaWard.name.asc()).all()
    return [_serialize_area(r) for r in rows]


@router.get("/case-summary")
def case_summary(
    level: str = Query("province", pattern="^(province|district|ward)$"),
    province_code: str | None = None,
    district_code: str | None = None,
    ward_code: str | None = None,
    data_type: str = Query("predict_current"),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.areas")),
):
    if level == "ward":
        code_col, name_col = PatientRecord.ward_code, PatientRecord.ward_name
    elif level == "district":
        code_col, name_col = PatientRecord.district_code, PatientRecord.district_name
    else:
        code_col, name_col = PatientRecord.province_code, PatientRecord.province_name

    query = db.query(
        code_col.label("area_code"),
        name_col.label("area_name"),
        func.count(PatientRecord.id).label("case_count"),
        func.count(func.distinct(PatientRecord.disease_group)).label("disease_groups"),
    ).filter(PatientRecord.data_type == data_type)
    query = apply_area_filters(query, PatientRecord, province_code, district_code, ward_code)

    rows = (
        query.group_by(code_col, name_col)
        .order_by(func.count(PatientRecord.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "area_code": r.area_code,
            "area_name": r.area_name or "Khong ro",
            "level": level,
            "case_count": int(r.case_count or 0),
            "disease_groups": int(r.disease_groups or 0),
        }
        for r in rows
    ]


@router.get("/disease-summary")
def disease_summary(
    province_code: str | None = None,
    district_code: str | None = None,
    ward_code: str | None = None,
    data_type: str = Query("predict_current"),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.areas")),
):
    query = db.query(
        PatientRecord.disease_group,
        func.count(PatientRecord.id).label("case_count"),
    ).filter(PatientRecord.data_type == data_type)
    query = apply_area_filters(query, PatientRecord, province_code, district_code, ward_code)
    rows = (
        query.group_by(PatientRecord.disease_group)
        .order_by(func.count(PatientRecord.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {"disease_group": r.disease_group or "Khong ro", "case_count": int(r.case_count or 0)}
        for r in rows
    ]


@router.get("/local-risks")
def local_risks(
    province_code: str | None = None,
    district_code: str | None = None,
    ward_code: str | None = None,
    data_type: str = Query("predict_current"),
    limit: int = Query(10, ge=1, le=200),
    db: Session = Depends(get_db),
):
    base_query = db.query(PatientRecord).filter(PatientRecord.data_type == data_type)
    base_query = apply_area_filters(base_query, PatientRecord, province_code, district_code, ward_code)
    period_range = base_query.with_entities(
        func.min(PatientRecord.period),
        func.max(PatientRecord.period),
    ).first()
    period_from = period_range[0] if period_range else None
    period_to = period_range[1] if period_range else None
    query = base_query.with_entities(
        PatientRecord.disease_group,
        func.count(PatientRecord.id).label("recent_cases"),
    )
    rows = (
        query.group_by(PatientRecord.disease_group)
        .order_by(func.count(PatientRecord.id).desc())
        .limit(limit)
        .all()
    )
    forecast_risks = _forecast_risk_map(db)
    return [
        {
            "disease_group": r.disease_group or "Khong ro",
            "recent_cases": int(r.recent_cases or 0),
            "risk_level": _classify_area_risk(int(r.recent_cases or 0), forecast_risks.get(r.disease_group)),
            "forecast_risk_level": forecast_risks.get(r.disease_group),
            "period_from": period_from,
            "period_to": period_to,
        }
        for r in rows
    ]


@router.get("/recommendations")
def recommendations(
    province_code: str | None = None,
    district_code: str | None = None,
    ward_code: str | None = None,
    db: Session = Depends(get_db),
):
    risks = local_risks(province_code, district_code, ward_code, "predict_current", 5, db)
    area = resolve_area(db, province_code, district_code, ward_code)

    knowledge_rows = db.query(DiseaseKnowledge).all()
    notes: list[str] = []
    for risk in risks:
        matched = _find_disease_knowledge(risk["disease_group"], knowledge_rows)
        for item in _split_guidance(matched.prevention if matched else None)[:2]:
            notes.append(f"{risk['disease_group']}: {item}")
        if len(notes) >= 5:
            break

    return {
        "area": {
            "province": _serialize_area(area["province"]) if area["province"] else None,
            "district": _serialize_area(area["district"]) if area["district"] else None,
            "ward": _serialize_area(area["ward"]) if area["ward"] else None,
        },
        "top_risks": risks,
        "recommendations": notes,
    }


@router.post("/weather-risk")
def weather_risk_by_area(
    payload: AreaWeatherRiskPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.weather_risk")),
):
    area = resolve_area(db, payload.province_code, payload.district_code, payload.ward_code)
    latitude = area["latitude"]
    longitude = area["longitude"]
    if latitude is None or longitude is None:
        raise HTTPException(status_code=400, detail="Khu vuc chua co toa do de lay thoi tiet.")
    try:
        result = predict_weather_risk(
            age_group=payload.age_group,
            gender=payload.gender,
            top_k=payload.top_k,
            weather=payload.weather,
            latitude=float(latitude),
            longitude=float(longitude),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    result["area"] = {
        "province": _serialize_area(area["province"]) if area["province"] else None,
        "district": _serialize_area(area["district"]) if area["district"] else None,
        "ward": _serialize_area(area["ward"]) if area["ward"] else None,
    }
    return result


@router.post("/sync-defaults")
def sync_defaults(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.assign_permissions")),
):
    return {"message": "Da dong bo danh muc khu vuc mac dinh.", "inserted": seed_default_areas(db)}


@router.post("/sync-external")
def sync_external(
    payload: AreaSyncPayload,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.assign_permissions")),
):
    if payload.payload:
        counts = sync_areas_from_payload(db, payload.payload)
    elif payload.source_url:
        try:
            counts = sync_areas_from_url(db, payload.source_url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail="Can truyen source_url hoac payload.")
    return {"message": "Da dong bo danh muc khu vuc.", "updated": counts}


@router.post("/provinces")
def upsert_province(
    payload: AreaUpsert,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.assign_permissions")),
):
    row = db.query(AreaProvince).filter(AreaProvince.code == payload.code).first()
    values = {
        "name": payload.name,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "is_active": payload.is_active,
        "updated_at": datetime.utcnow(),
    }
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        row = AreaProvince(code=payload.code, **values)
        db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_area(row)


@router.post("/districts")
def upsert_district(
    payload: AreaUpsert,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.assign_permissions")),
):
    if not payload.province_code:
        raise HTTPException(status_code=400, detail="province_code la bat buoc.")
    row = db.query(AreaDistrict).filter(AreaDistrict.code == payload.code).first()
    values = {
        "province_code": payload.province_code,
        "name": payload.name,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "is_active": payload.is_active,
        "updated_at": datetime.utcnow(),
    }
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        row = AreaDistrict(code=payload.code, **values)
        db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_area(row)


@router.post("/wards")
def upsert_ward(
    payload: AreaUpsert,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.assign_permissions")),
):
    if not payload.province_code or not payload.district_code:
        raise HTTPException(status_code=400, detail="province_code va district_code la bat buoc.")
    row = db.query(AreaWard).filter(AreaWard.code == payload.code).first()
    values = {
        "province_code": payload.province_code,
        "district_code": payload.district_code,
        "name": payload.name,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "is_active": payload.is_active,
        "updated_at": datetime.utcnow(),
    }
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        row = AreaWard(code=payload.code, **values)
        db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_area(row)
