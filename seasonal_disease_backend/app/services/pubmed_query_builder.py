from __future__ import annotations

from app.medical_knowledge_models import WEATHER_FACTORS


WEATHER_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "temperature": ("temperature", "heat", "cold"),
    "humidity": ("humidity",),
    "precipitation": ("rainfall", "precipitation", "flood", "flooding"),
    "wind": ("wind", "wind speed"),
    "weather_condition": ("weather", "meteorological conditions"),
}

if tuple(WEATHER_SEARCH_TERMS) != WEATHER_FACTORS:
    raise RuntimeError("PubMed weather search vocabulary is out of sync with Medical Knowledge V1")


def _or_component(terms: list[str] | tuple[str, ...]) -> str:
    return "(" + " OR ".join(f'"{term}"[Title/Abstract]' for term in terms) + ")"


def build_pubmed_query(
    disease_terms: list[str],
    weather_factor: str,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
) -> str:
    if weather_factor not in WEATHER_SEARCH_TERMS:
        raise ValueError(f"Unsupported weather factor: {weather_factor}")
    if not disease_terms:
        raise ValueError("At least one disease term is required")

    query = f"{_or_component(disease_terms)} AND {_or_component(WEATHER_SEARCH_TERMS[weather_factor])}"
    if year_from is not None or year_to is not None:
        lower = year_from if year_from is not None else 1800
        upper = year_to if year_to is not None else 2100
        if lower > upper:
            raise ValueError("year_from must be less than or equal to year_to")
        query += f' AND ("{lower}"[Date - Publication] : "{upper}"[Date - Publication])'
    return query
