from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import WEATHER_AI_V3_CATEGORY_MAPPINGS


FACTOR_TYPES = ("WEATHER", "AGE", "SEX", "SEASONALITY")
WEATHER_FACTORS = (
    "temperature",
    "humidity",
    "precipitation",
    "wind",
    "weather_condition",
)
FACTOR_KEYS = {
    "WEATHER": WEATHER_FACTORS,
    "AGE": ("age_group",),
    "SEX": ("gender",),
    "SEASONALITY": ("time_of_year",),
}
FACTOR_LABELS_VI = {
    ("AGE", "age_group"): "Độ tuổi",
    ("SEX", "gender"): "Giới tính",
    ("SEASONALITY", "time_of_year"): "Thời điểm trong năm / tính mùa vụ",
    ("WEATHER", "temperature"): "Nhiệt độ",
    ("WEATHER", "humidity"): "Độ ẩm",
    ("WEATHER", "precipitation"): "Mưa / lượng mưa",
    ("WEATHER", "wind"): "Gió",
    ("WEATHER", "weather_condition"): "Điều kiện thời tiết",
}


@dataclass(frozen=True)
class CanonicalFactor:
    factor_type: str
    factor_key: str
    factor_value: str | None
    weather_factor: str | None


@lru_cache(maxsize=4)
def load_factor_values(path: str | None = None) -> dict[str, tuple[str, ...]]:
    mapping_path = Path(path or WEATHER_AI_V3_CATEGORY_MAPPINGS)
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
        age_values = tuple(str(value) for value in payload["age_group"])
        sex_values = tuple(str(value) for value in payload["gender"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Weather AI category mappings are unavailable") from exc
    if not age_values or not sex_values:
        raise RuntimeError("Weather AI category mappings are incomplete")
    return {"AGE": age_values, "SEX": sex_values}


def normalize_factor(
    *,
    factor_type: str | None = None,
    factor_key: str | None = None,
    factor_value: str | None = None,
    weather_factor: str | None = None,
) -> CanonicalFactor:
    """Validate one reusable Medical Knowledge topic selector.

    Legacy callers may provide only ``weather_factor``. Generic fields are always
    returned and are the canonical identity used by new code.
    """

    if factor_type is None and factor_key is None and weather_factor:
        factor_type, factor_key = "WEATHER", weather_factor
    normalized_type = str(factor_type or "").strip().upper()
    normalized_key = str(factor_key or "").strip()
    normalized_value = factor_value.strip() if isinstance(factor_value, str) else None
    normalized_value = normalized_value or None

    if normalized_type not in FACTOR_TYPES:
        raise ValueError(f"factor_type must be one of: {', '.join(FACTOR_TYPES)}")
    if normalized_key not in FACTOR_KEYS[normalized_type]:
        raise ValueError(f"Unsupported factor_key for {normalized_type}")

    if normalized_type in {"AGE", "SEX"}:
        if normalized_value is None:
            message = (
                "Vui lòng chọn nhóm tuổi cần giải thích."
                if normalized_type == "AGE"
                else "Vui lòng chọn giới tính cần giải thích."
            )
            raise ValueError(message)
        if normalized_value not in load_factor_values()[normalized_type]:
            raise ValueError(f"Unsupported factor_value for {normalized_type}")
    elif normalized_value is not None:
        raise ValueError(f"factor_value must be null for {normalized_type}")

    legacy_weather = normalized_key if normalized_type == "WEATHER" else None
    if weather_factor is not None and weather_factor != legacy_weather:
        raise ValueError("weather_factor does not match the generic factor selector")
    return CanonicalFactor(normalized_type, normalized_key, normalized_value, legacy_weather)


def factor_catalog() -> list[dict]:
    values = load_factor_values()
    catalog: list[dict] = []
    for factor_type, keys in FACTOR_KEYS.items():
        for key in keys:
            catalog.append(
                {
                    "type": factor_type,
                    "key": key,
                    "label_vi": FACTOR_LABELS_VI[(factor_type, key)],
                    "values": list(values.get(factor_type, ())),
                }
            )
    return catalog
