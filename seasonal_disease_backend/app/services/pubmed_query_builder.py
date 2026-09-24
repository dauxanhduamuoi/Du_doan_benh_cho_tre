from __future__ import annotations

from app.medical_knowledge_factors import WEATHER_FACTORS, normalize_factor


WEATHER_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "temperature": ("temperature", "heat", "cold"),
    "humidity": ("humidity",),
    "precipitation": ("rainfall", "precipitation", "flood", "flooding"),
    "wind": ("wind", "wind speed"),
    "weather_condition": ("weather", "meteorological conditions"),
}

PEDIATRIC_SEARCH_COMPONENT = (
    '("Infant"[MeSH Terms] OR "Child"[MeSH Terms] OR "Adolescent"[MeSH Terms] '
    'OR "pediatric"[Title/Abstract] OR "paediatric"[Title/Abstract])'
)

if tuple(WEATHER_SEARCH_TERMS) != WEATHER_FACTORS:
    raise RuntimeError("PubMed weather search vocabulary is out of sync with Medical Knowledge V1")


def _or_component(terms: list[str] | tuple[str, ...]) -> str:
    return "(" + " OR ".join(f'"{term}"[Title/Abstract]' for term in terms) + ")"


FACTOR_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "AGE": ("age factors", "age distribution", "age-specific"),
    "SEX": ("sex factors", "sex differences", "male", "female"),
    "SEASONALITY": ("seasonality", "seasonal variation", "seasonal incidence", "seasonal pattern"),
}

# Auto discovery deliberately has a richer, phrase-oriented vocabulary than the
# existing Guided Search.  Keeping this additive preserves the exact query made
# by the Reviewed workflow while giving both workflows one authoritative module
# for factor terminology.
AUTO_FACTOR_SEARCH_TERMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "temperature": (
        ("ambient temperature", "air temperature", "hot weather", "cold weather"),
        ("temperature", "heat exposure", "environmental cold exposure"),
    ),
    "humidity": (
        ("humidity", "relative humidity"),
        ("humidity", "relative humidity", "absolute humidity"),
    ),
    "precipitation": (
        ("rainfall", "precipitation"),
        ("rainfall", "precipitation", "flood", "flooding"),
    ),
    "wind": (
        ("wind speed", "wind velocity"),
        ("wind speed", "wind velocity", "meteorological wind"),
    ),
    "weather_condition": (
        ("weather condition", "meteorological condition"),
        ("weather", "meteorological", "climate condition"),
    ),
    "AGE": (
        ("age-specific", "age distribution", "age group"),
        ("age-specific", "age distribution", "age group", "age-stratified", "pediatric age"),
    ),
    "SEX": (
        ("sex differences", "sex-specific"),
        ("sex differences", "sex-specific", "gender differences", "gender-specific", "by sex"),
    ),
    "SEASONALITY": (
        ("seasonality", "seasonal pattern", "seasonal variation"),
        ("seasonality", "seasonal pattern", "seasonal variation", "time of year", "monthly pattern"),
    ),
}


def build_pubmed_query(
    disease_terms: list[str],
    weather_factor: str | None = None,
    *,
    factor_type: str | None = None,
    factor_key: str | None = None,
    factor_value: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> str:
    return build_pubmed_query_variant(
        disease_terms,
        weather_factor,
        factor_type=factor_type,
        factor_key=factor_key,
        factor_value=factor_value,
        year_from=year_from,
        year_to=year_to,
        include_factor=True,
        include_pediatric=True,
    )


def build_pubmed_query_variant(
    disease_terms: list[str],
    weather_factor: str | None = None,
    *,
    factor_type: str | None = None,
    factor_key: str | None = None,
    factor_value: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    include_factor: bool,
    include_pediatric: bool,
) -> str:
    factor = normalize_factor(
        factor_type=factor_type,
        factor_key=factor_key,
        factor_value=factor_value,
        weather_factor=weather_factor,
    )
    if not disease_terms:
        raise ValueError("At least one disease term is required")

    components = [_or_component(disease_terms)]
    if include_factor:
        if factor.factor_type == "WEATHER":
            factor_terms = WEATHER_SEARCH_TERMS[factor.factor_key]
        else:
            factor_terms = FACTOR_SEARCH_TERMS[factor.factor_type]
            if factor.factor_value is not None:
                factor_terms = (*factor_terms, factor.factor_value)
        components.append(_or_component(factor_terms))
    if include_pediatric:
        components.append(PEDIATRIC_SEARCH_COMPONENT)
    query = " AND ".join(components)
    if year_from is not None or year_to is not None:
        lower = year_from if year_from is not None else 1800
        upper = year_to if year_to is not None else 2100
        if lower > upper:
            raise ValueError("year_from must be less than or equal to year_to")
        query += f' AND ("{lower}"[Date - Publication] : "{upper}"[Date - Publication])'
    return query


def build_auto_pubmed_query(
    disease_terms: list[str] | tuple[str, ...],
    factor_terms: list[str] | tuple[str, ...],
) -> str:
    """Build a bounded Auto query without changing Guided Search semantics."""
    if not disease_terms:
        raise ValueError("At least one disease term is required")
    if not factor_terms:
        raise ValueError("At least one factor term is required")
    return (
        f"{_or_component(disease_terms)} AND "
        f"{_or_component(factor_terms)} AND "
        f"{PEDIATRIC_SEARCH_COMPONENT}"
    )
