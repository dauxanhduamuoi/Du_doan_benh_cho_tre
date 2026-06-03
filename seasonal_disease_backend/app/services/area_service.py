from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import AreaDistrict, AreaProvince, AreaWard, PatientRecord


PATIENT_AREA_COLUMNS = {
    "province_code": "TEXT",
    "province_name": "TEXT",
    "district_code": "TEXT",
    "district_name": "TEXT",
    "ward_code": "TEXT",
    "ward_name": "TEXT",
}


DEFAULT_AREA_DATA = [
    {
        "code": "79",
        "name": "Thành phố Hồ Chí Minh",
        "latitude": 10.7769,
        "longitude": 106.7009,
        "districts": [
            {
                "code": "760",
                "name": "Quan 1",
                "latitude": 10.7757,
                "longitude": 106.7004,
                "wards": [
                    {"code": "26734", "name": "Phuong Ben Nghe", "latitude": 10.7816, "longitude": 106.7021},
                    {"code": "26737", "name": "Phuong Ben Thanh", "latitude": 10.7721, "longitude": 106.6983},
                ],
            },
            {
                "code": "766",
                "name": "Quan 5",
                "latitude": 10.7540,
                "longitude": 106.6634,
                "wards": [
                    {"code": "27301", "name": "Phuong 1", "latitude": 10.7581, "longitude": 106.6810},
                    {"code": "27310", "name": "Phuong 10", "latitude": 10.7547, "longitude": 106.6671},
                ],
            },
            {
                "code": "769",
                "name": "Quan Binh Thanh",
                "latitude": 10.8106,
                "longitude": 106.7091,
                "wards": [
                    {"code": "27433", "name": "Phuong 25", "latitude": 10.8038, "longitude": 106.7149},
                    {"code": "27448", "name": "Phuong 28", "latitude": 10.8206, "longitude": 106.7290},
                ],
            },
        ],
    },
    {
        "code": "01",
        "name": "Thành phố Hà Nội",
        "latitude": 21.0278,
        "longitude": 105.8342,
        "districts": [
            {
                "code": "001",
                "name": "Quan Ba Dinh",
                "latitude": 21.0369,
                "longitude": 105.8347,
                "wards": [
                    {"code": "00001", "name": "Phuong Phuc Xa", "latitude": 21.0457, "longitude": 105.8482},
                    {"code": "00004", "name": "Phuong Truc Bach", "latitude": 21.0451, "longitude": 105.8394},
                ],
            },
            {
                "code": "003",
                "name": "Quan Tay Ho",
                "latitude": 21.0688,
                "longitude": 105.8124,
                "wards": [
                    {"code": "00091", "name": "Phuong Buoi", "latitude": 21.0476, "longitude": 105.8102},
                    {"code": "00094", "name": "Phuong Thuy Khue", "latitude": 21.0435, "longitude": 105.8197},
                ],
            },
        ],
    },
    {
        "code": "48",
        "name": "Thành phố Đà Nẵng",
        "latitude": 16.0471,
        "longitude": 108.2068,
        "districts": [
            {
                "code": "490",
                "name": "Quan Hai Chau",
                "latitude": 16.0472,
                "longitude": 108.2208,
                "wards": [
                    {"code": "20194", "name": "Phuong Hai Chau I", "latitude": 16.0691, "longitude": 108.2246},
                    {"code": "20203", "name": "Phuong Thach Thang", "latitude": 16.0748, "longitude": 108.2209},
                ],
            },
            {
                "code": "493",
                "name": "Quan Son Tra",
                "latitude": 16.1061,
                "longitude": 108.2525,
                "wards": [
                    {"code": "20257", "name": "Phuong An Hai Bac", "latitude": 16.0712, "longitude": 108.2343},
                    {"code": "20266", "name": "Phuong Phuoc My", "latitude": 16.0647, "longitude": 108.2433},
                ],
            },
        ],
    },
]


PROVINCE_CODE_COLUMNS = ["province_code", "ma_tinh", "matinh", "tinh_code", "city_code"]
PROVINCE_NAME_COLUMNS = ["province_name", "tinh", "thanh_pho", "province", "city"]
FULL_ADDRESS_COLUMNS = ["full_address", "dia_chi", "diachi", "address"]
DISTRICT_CODE_COLUMNS = ["district_code", "ma_huyen", "mahuyen", "huyen_code", "quan_code"]
WARD_CODE_COLUMNS = ["ward_code", "ma_xa", "maxa", "xa_code", "phuong_code"]

KNOWN_PROVINCES = {
    "an giang": ("89", "An Giang", 10.5216, 105.1259),
    "binh dinh": ("52", "Bình Định", 13.7820, 109.2190),
    "can tho": ("92", "Cần Thơ", 10.0452, 105.7469),
    "ho chi minh": ("79", "Thành phố Hồ Chí Minh", 10.7769, 106.7009),
    "tp ho chi minh": ("79", "Thành phố Hồ Chí Minh", 10.7769, 106.7009),
    "thanh pho ho chi minh": ("79", "Thành phố Hồ Chí Minh", 10.7769, 106.7009),
    "hcm": ("79", "Thành phố Hồ Chí Minh", 10.7769, 106.7009),
    "ha noi": ("01", "Thành phố Hà Nội", 21.0278, 105.8342),
    "thanh pho ha noi": ("01", "Thành phố Hà Nội", 21.0278, 105.8342),
    "hai phong": ("31", "Hải Phòng", 20.8449, 106.6881),
    "lam dong": ("68", "Lâm Đồng", 11.5753, 108.1429),
    "nghe an": ("40", "Nghệ An", 19.2342, 104.9200),
    "quang nam": ("49", "Quảng Nam", 15.5394, 108.0191),
    "thanh hoa": ("38", "Thanh Hóa", 19.8075, 105.7764),
    "da nang": ("48", "Thành phố Đà Nẵng", 16.0471, 108.2068),
    "thanh pho da nang": ("48", "Thành phố Đà Nẵng", 16.0471, 108.2068),
    "dong nai": ("75", "Đồng Nai", 11.0686, 107.1676),
    "tra vinh": ("84", "Trà Vinh", 9.8127, 106.2993),
}


def fill_known_province_coordinates(db: Session) -> int:
    """Backfill province coordinates from the local known-province table."""
    updated = 0
    rows = db.query(AreaProvince).filter(AreaProvince.is_active.is_(True)).all()
    for province in rows:
        known = KNOWN_PROVINCES.get(_key(province.name))
        if not known:
            continue
        if province.latitude is None or province.longitude is None:
            province.latitude = known[2]
            province.longitude = known[3]
            province.updated_at = datetime.utcnow()
            updated += 1
    if updated:
        db.commit()
    return updated


def ensure_area_schema(engine: Engine) -> None:
    """SQLite does not alter existing tables on create_all, so add new patient area columns."""
    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("patient_records")}
    missing = [(name, sql_type) for name, sql_type in PATIENT_AREA_COLUMNS.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as conn:
        for name, sql_type in missing:
            conn.execute(text(f"ALTER TABLE patient_records ADD COLUMN {name} {sql_type}"))


def _normalize_code(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    if text_value.endswith(".0"):
        text_value = text_value[:-2]
    return text_value.zfill(2) if text_value.isdigit() and len(text_value) == 1 else text_value


def _find_value(row: pd.Series, candidates: list[str]) -> str | None:
    columns = {str(c).strip().lower(): c for c in row.index}
    for name in candidates:
        col = columns.get(name.lower())
        if col is not None:
            return _normalize_code(row.get(col))
    return None


def _strip_accents(value: str) -> str:
    value = value.replace("Đ", "D").replace("đ", "d")
    return "".join(
        c for c in unicodedata.normalize("NFD", value)
        if unicodedata.category(c) != "Mn"
    )


def _key(value: str) -> str:
    value = _strip_accents(value).lower()
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _province_code_from_name(name: str) -> str:
    name_key = _key(name)
    stripped_key = re.sub(r"^(t|tp|tinh|thanh pho)\s+", "", name_key).strip()
    known = KNOWN_PROVINCES.get(name_key) or KNOWN_PROVINCES.get(stripped_key)
    if known:
        return known[0]
    code = _key(name).upper().replace(" ", "_")
    return code[:20] if code else "UNKNOWN"


def normalize_province_name(value: Any) -> str | None:
    if pd.isna(value):
        return None
    raw = str(value).strip()
    if not raw:
        return None

    compact_key = _key(raw)
    compact_key = compact_key.replace("tp hcm", "ho chi minh").replace("tphcm", "ho chi minh")
    stripped_key = re.sub(r"^(t|tp|tinh|thanh pho)\s+", "", compact_key).strip()

    known = KNOWN_PROVINCES.get(stripped_key) or KNOWN_PROVINCES.get(compact_key)
    if known:
        return known[1]

    cleaned = re.sub(
        r"^(T\.|TP\.|Tp\.|tp\.|Tỉnh|tỉnh|Tinh|tinh|Thành phố|thành phố|Thanh pho|thanh pho)\s*",
        "",
        raw,
    ).strip(" .")
    return cleaned or raw


def extract_province_from_full_address(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    parts = [p.strip() for p in text_value.split(",") if p.strip()]
    if not parts:
        return None
    return normalize_province_name(parts[-1])


def _find_province_name(row: pd.Series) -> str | None:
    direct = _find_value(row, PROVINCE_NAME_COLUMNS)
    if direct:
        return normalize_province_name(direct)
    full_address = _find_value(row, FULL_ADDRESS_COLUMNS)
    if full_address:
        return extract_province_from_full_address(full_address)
    return None


def _all_default_rows() -> tuple[list[dict], list[dict], list[dict]]:
    provinces: list[dict] = []
    districts: list[dict] = []
    wards: list[dict] = []

    for p in DEFAULT_AREA_DATA:
        provinces.append({
            "code": p["code"],
            "name": p["name"],
            "latitude": p.get("latitude"),
            "longitude": p.get("longitude"),
            "is_active": True,
            "updated_at": datetime.utcnow(),
        })
        for d in p["districts"]:
            districts.append({
                "code": d["code"],
                "province_code": p["code"],
                "name": d["name"],
                "latitude": d.get("latitude"),
                "longitude": d.get("longitude"),
                "is_active": True,
                "updated_at": datetime.utcnow(),
            })
            for w in d["wards"]:
                wards.append({
                    "code": w["code"],
                    "district_code": d["code"],
                    "province_code": p["code"],
                    "name": w["name"],
                    "latitude": w.get("latitude"),
                    "longitude": w.get("longitude"),
                    "is_active": True,
                    "updated_at": datetime.utcnow(),
                })

    return provinces, districts, wards


def seed_default_areas(db: Session) -> dict[str, int]:
    provinces, districts, wards = _all_default_rows()
    inserted = {"provinces": 0, "districts": 0, "wards": 0}

    for item in provinces:
        existing = db.query(AreaProvince).filter(AreaProvince.code == item["code"]).first()
        if existing:
            existing.name = item["name"]
            existing.latitude = item["latitude"]
            existing.longitude = item["longitude"]
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
        else:
            db.add(AreaProvince(**item))
            inserted["provinces"] += 1
    for item in districts:
        if not db.query(AreaDistrict).filter(AreaDistrict.code == item["code"]).first():
            db.add(AreaDistrict(**item))
            inserted["districts"] += 1
    for item in wards:
        if not db.query(AreaWard).filter(AreaWard.code == item["code"]).first():
            db.add(AreaWard(**item))
            inserted["wards"] += 1

    db.commit()
    return inserted


def sync_areas_from_payload(db: Session, payload: dict[str, Any]) -> dict[str, int]:
    """Upsert area catalog from a JSON payload with provinces/districts/wards arrays."""
    counts = {"provinces": 0, "districts": 0, "wards": 0}

    for item in payload.get("provinces", []):
        code = _normalize_code(item.get("code"))
        if not code:
            continue
        row = db.query(AreaProvince).filter(AreaProvince.code == code).first()
        values = {
            "name": str(item.get("name") or code),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
            "is_active": bool(item.get("is_active", True)),
            "updated_at": datetime.utcnow(),
        }
        if row:
            for k, v in values.items():
                setattr(row, k, v)
        else:
            db.add(AreaProvince(code=code, **values))
        counts["provinces"] += 1

    for item in payload.get("districts", []):
        code = _normalize_code(item.get("code"))
        province_code = _normalize_code(item.get("province_code"))
        if not code or not province_code:
            continue
        row = db.query(AreaDistrict).filter(AreaDistrict.code == code).first()
        values = {
            "province_code": province_code,
            "name": str(item.get("name") or code),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
            "is_active": bool(item.get("is_active", True)),
            "updated_at": datetime.utcnow(),
        }
        if row:
            for k, v in values.items():
                setattr(row, k, v)
        else:
            db.add(AreaDistrict(code=code, **values))
        counts["districts"] += 1

    for item in payload.get("wards", []):
        code = _normalize_code(item.get("code"))
        district_code = _normalize_code(item.get("district_code"))
        province_code = _normalize_code(item.get("province_code"))
        if not code or not district_code or not province_code:
            continue
        row = db.query(AreaWard).filter(AreaWard.code == code).first()
        values = {
            "district_code": district_code,
            "province_code": province_code,
            "name": str(item.get("name") or code),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
            "is_active": bool(item.get("is_active", True)),
            "updated_at": datetime.utcnow(),
        }
        if row:
            for k, v in values.items():
                setattr(row, k, v)
        else:
            db.add(AreaWard(code=code, **values))
        counts["wards"] += 1

    db.commit()
    return counts


def sync_areas_from_url(db: Session, source_url: str) -> dict[str, int]:
    with urllib.request.urlopen(source_url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return sync_areas_from_payload(db, payload)


def get_area_maps(db: Session) -> tuple[dict[str, AreaProvince], dict[str, AreaDistrict], dict[str, AreaWard]]:
    provinces = {p.code: p for p in db.query(AreaProvince).filter(AreaProvince.is_active.is_(True)).all()}
    districts = {d.code: d for d in db.query(AreaDistrict).filter(AreaDistrict.is_active.is_(True)).all()}
    wards = {w.code: w for w in db.query(AreaWard).filter(AreaWard.is_active.is_(True)).all()}
    return provinces, districts, wards


def resolve_area(
    db: Session,
    province_code: str | None = None,
    district_code: str | None = None,
    ward_code: str | None = None,
) -> dict[str, Any]:
    provinces, districts, wards = get_area_maps(db)
    province = provinces.get(province_code or "") if province_code else None
    district = districts.get(district_code or "") if district_code else None
    ward = wards.get(ward_code or "") if ward_code else None

    if ward:
        district = districts.get(ward.district_code)
        province = provinces.get(ward.province_code)
    elif district:
        province = provinces.get(district.province_code)

    return {
        "province": province,
        "district": district,
        "ward": ward,
        "latitude": (
            (ward.latitude if ward else None)
            or (district.latitude if district else None)
            or (province.latitude if province else None)
        ),
        "longitude": (
            (ward.longitude if ward else None)
            or (district.longitude if district else None)
            or (province.longitude if province else None)
        ),
    }


def attach_patient_areas(db: Session, df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract province/city from patient data.
    Current requirement only needs province-level statistics, so full_address is parsed by
    taking the segment after the last comma: "... , T. Dong Nai" -> "Dong Nai".
    """
    fill_known_province_coordinates(db)
    provinces, _, _ = get_area_maps(db)
    province_by_name = {_key(p.name): p for p in provinces.values()}
    assigned: list[dict[str, str | None]] = []

    for idx, row in df.reset_index(drop=True).iterrows():
        province_code = _find_value(row, PROVINCE_CODE_COLUMNS)
        province_name = _find_province_name(row)
        province = provinces.get(province_code or "") if province_code else None

        if not province and province_name:
            province = province_by_name.get(_key(province_name))

        if not province and province_name:
            code = province_code or _province_code_from_name(province_name)
            province = provinces.get(code)

        if province and province_name and province.name != province_name:
            province.name = province_name
            province.updated_at = datetime.utcnow()

        if not province and province_name:
            code = province_code or _province_code_from_name(province_name)
            known = KNOWN_PROVINCES.get(_key(province_name))
            latitude = known[2] if known else None
            longitude = known[3] if known else None
            province = AreaProvince(
                code=code,
                name=province_name,
                latitude=latitude,
                longitude=longitude,
                is_active=True,
                updated_at=datetime.utcnow(),
            )
            db.add(province)
            provinces[code] = province
            province_by_name[_key(province_name)] = province

        assigned.append({
            "province_code": province.code if province else None,
            "province_name": province.name if province else None,
            "district_code": None,
            "district_name": None,
            "ward_code": None,
            "ward_name": None,
        })

    db.flush()

    output = df.copy()
    for key in PATIENT_AREA_COLUMNS.keys():
        output[key] = [item[key] for item in assigned]
    return output


def apply_area_filters(query, model, province_code=None, district_code=None, ward_code=None):
    if province_code:
        query = query.filter(model.province_code == province_code)
    if district_code:
        query = query.filter(model.district_code == district_code)
    if ward_code:
        query = query.filter(model.ward_code == ward_code)
    return query


def area_label(row: PatientRecord, level: str) -> tuple[str | None, str | None]:
    if level == "ward":
        return row.ward_code, row.ward_name
    if level == "district":
        return row.district_code, row.district_name
    return row.province_code, row.province_name
