from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from app.medical_knowledge_models import MedicalKnowledgeTopic
from app.services.pubmed_query_builder import AUTO_FACTOR_SEARCH_TERMS


_LEADING_CATALOG_QUALIFIERS = re.compile(
    r"^(?:other|specified|unspecified)\s+", re.IGNORECASE
)
_TRAILING_CATALOG_QUALIFIERS = re.compile(
    r",?\s+(?:not elsewhere classified|unspecified)$", re.IGNORECASE
)
_GENERIC_DISEASE_ALIASES = frozenset(
    {
        "other arthropod",
        "other viral diseases",
        "other infections",
        "infection",
        "infections",
        "respiratory",
        "disease",
        "diseases",
        "virus",
        "viral",
    }
)

PEDIATRIC_TERMS = (
    "pediatric",
    "paediatric",
    "child",
    "children",
    "infant",
    "adolescent",
    "preschool",
    "school-aged",
    "boy",
    "girl",
)

_AGE_BUCKET_QUERY_HINTS = {
    "Dưới 1 tuổi": ("infant", "infancy"),
    "1-5 tuổi": ("preschool child", "young child"),
    "6-10 tuổi": ("school-aged child",),
    "11-15 tuổi": ("adolescent",),
    "Trên 15 tuổi": ("adolescent", "older child"),
    "Không rõ": ("pediatric age",),
}


def normalize_phrase(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def phrase_present(text: str, phrase: str) -> bool:
    """Match whole normalized phrases, never arbitrary substrings."""
    normalized_text = normalize_phrase(text)
    normalized_phrase = normalize_phrase(phrase)
    if not normalized_phrase:
        return False
    return re.search(
        rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])",
        normalized_text,
    ) is not None


def phrase_count(text: str, phrase: str) -> int:
    normalized_text = normalize_phrase(text)
    normalized_phrase = normalize_phrase(phrase)
    if not normalized_phrase:
        return 0
    return len(
        re.findall(
            rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])",
            normalized_text,
        )
    )


@dataclass(frozen=True)
class DiseaseAliasSet:
    strict: tuple[str, ...]
    broad: tuple[str, ...]


@dataclass(frozen=True)
class RelevanceSignals:
    disease: int
    factor: int
    pediatric: int


def _safe_alias(value: str | None) -> str | None:
    value = " ".join((value or "").strip().split())
    if not value or normalize_phrase(value) in _GENERIC_DISEASE_ALIASES:
        return None
    tokens = normalize_phrase(value).split()
    if len(tokens) < 2 and value.lower() not in {"influenza", "pneumonia", "leukaemia", "leukemia"}:
        return None
    return value


def build_disease_aliases(
    disease_group_name: str,
    child_english_names: list[str] | tuple[str, ...] = (),
) -> DiseaseAliasSet:
    """Use only deployed group/ICD catalog truth; never invent synonyms."""
    suffix = (
        disease_group_name.split(" - ", 1)[1].strip()
        if " - " in disease_group_name
        else disease_group_name.strip()
    )
    group_alias = _safe_alias(suffix)
    children: list[str] = []
    seen: set[str] = set()
    for raw in child_english_names:
        candidate = _safe_alias(raw)
        if candidate is None:
            continue
        key = normalize_phrase(candidate)
        if key not in seen:
            seen.add(key)
            children.append(candidate)

    # A complete, specific group label is the best strict representation.  An
    # incomplete catalog suffix such as "Other arthropod" is rejected and the
    # exact child diagnoses become the source of truth instead.
    strict: list[str] = []
    if group_alias:
        strict.append(group_alias)
    strict.extend(children[:4] if not strict else children[:3])
    broad = [*strict]
    broad.extend(child for child in children if normalize_phrase(child) not in {
        normalize_phrase(item) for item in broad
    })
    # Bound PubMed query size while retaining a useful cross-section of exact
    # child diagnoses from the deployed catalog.
    return DiseaseAliasSet(tuple(strict[:5]), tuple(broad[:20]))


def factor_vocabulary(
    topic: MedicalKnowledgeTopic, *, expanded: bool
) -> tuple[str, ...]:
    key = topic.factor_key if topic.factor_type == "WEATHER" else topic.factor_type
    strict, broad = AUTO_FACTOR_SEARCH_TERMS[key]
    terms = list(broad if expanded else strict)
    if topic.factor_type == "AGE" and topic.factor_value:
        terms.extend(_AGE_BUCKET_QUERY_HINTS.get(topic.factor_value, ()))
    # Male/female are useful query hints but are intentionally not sufficient
    # for the deterministic SEX relevance gate.
    if topic.factor_type == "SEX" and expanded and topic.factor_value:
        terms.extend(("male", "boys") if topic.factor_value == "Nam" else ("female", "girls"))
    return tuple(dict.fromkeys(terms))


def _environmental_temperature_match(text: str) -> int:
    strong = (
        "ambient temperature",
        "air temperature",
        "environmental temperature",
        "hot weather",
        "cold weather",
        "meteorological temperature",
        "outdoor temperature",
        "heat exposure",
        "environmental cold exposure",
    )
    if any(phrase_present(text, term) for term in strong):
        return 3
    # Plain temperature is accepted only alongside an environmental context.
    if phrase_present(text, "temperature") and any(
        phrase_present(text, context)
        for context in ("weather", "meteorological", "climate", "ambient", "outdoor")
    ):
        return 2
    return 0


def _environmental_humidity_match(text: str) -> int:
    if not any(
        phrase_present(text, term)
        for term in ("humidity", "relative humidity", "absolute humidity")
    ):
        return 0
    if any(
        phrase_present(text, context)
        for context in (
            "weather", "meteorological", "climate", "climatic", "ambient",
            "outdoor", "rainfall", "air temperature", "seasonal pattern",
        )
    ):
        return 3
    return 0


_RELATIONSHIP_TERMS = (
    "association", "associated", "relationship", "effect", "impact",
    "correlation", "correlated", "risk", "incidence", "increase", "increased",
    "decrease", "decreased", "higher", "lower", "revealed", "linked",
)
_COVARIATE_ONLY_TERMS = (
    "adjusting for", "adjusted for", "after adjustment", "confounding factor",
    "confounding factors", "covariate", "covariates", "controlled for",
    "eliminating", "potential confounder", "potential confounders",
)


def _outcome_text(abstract: str) -> str:
    normalized = abstract or ""
    markers = [
        position
        for label in ("RESULTS:", "RESULT:", "CONCLUSIONS:", "CONCLUSION:")
        if (position := normalized.upper().find(label)) >= 0
    ]
    return normalized[min(markers):] if markers else normalized


def _factor_mentioned_in_relationship_sentence(
    sentence: str, topic: MedicalKnowledgeTopic
) -> bool:
    if any(phrase_present(sentence, term) for term in _COVARIATE_ONLY_TERMS):
        return False
    if not any(phrase_present(sentence, term) for term in _RELATIONSHIP_TERMS):
        return False
    if topic.factor_type == "WEATHER" and topic.factor_key == "humidity":
        return any(
            phrase_present(sentence, term)
            for term in ("humidity", "relative humidity", "absolute humidity")
        )
    return factor_relevance(sentence, topic) > 0


def disease_factor_linked(
    *, title: str, abstract: str, topic: MedicalKnowledgeTopic, aliases: DiseaseAliasSet
) -> bool:
    title_has_disease = any(phrase_present(title, alias) for alias in aliases.broad)
    title_linked = (
        title_has_disease
        and _factor_mentioned_in_relationship_sentence(title, topic)
    )
    if title_linked:
        return True
    sentences = re.split(r"(?<=[.!?;])\s+", _outcome_text(abstract))
    for sentence in sentences:
        if not _factor_mentioned_in_relationship_sentence(sentence, topic):
            continue
        if title_has_disease or any(
            phrase_present(sentence, alias) for alias in aliases.broad
        ):
            return True
    return False


def disease_relevance(text: str, aliases: DiseaseAliasSet) -> int:
    matches = [alias for alias in aliases.broad if phrase_present(text, alias)]
    if not matches:
        return 0
    longest = max(len(normalize_phrase(alias).split()) for alias in matches)
    return 3 if longest >= 3 else 2


def disease_relevance_fields(
    *, title: str, abstract: str, mesh_text: str, aliases: DiseaseAliasSet
) -> int:
    if any(phrase_present(title, alias) for alias in aliases.broad):
        return 4
    if any(phrase_present(mesh_text, alias) for alias in aliases.broad):
        return 3
    # A single incidental mention in an abstract is not enough to establish
    # that the paper studies the disease topic.
    if any(phrase_count(abstract, alias) >= 2 for alias in aliases.broad):
        return 2
    return 0


def factor_relevance(text: str, topic: MedicalKnowledgeTopic) -> int:
    if topic.factor_type == "WEATHER":
        if topic.factor_key == "temperature":
            return _environmental_temperature_match(text)
        if topic.factor_key == "humidity":
            return _environmental_humidity_match(text)
        terms = factor_vocabulary(topic, expanded=True)
        return 3 if any(phrase_present(text, term) for term in terms) else 0
    if topic.factor_type == "AGE":
        comparison_terms = (
            "age-specific", "age specific", "age distribution", "age group",
            "age-stratified", "age stratified", "by age", "across age groups",
        )
        return 3 if any(phrase_present(text, term) for term in comparison_terms) else 0
    if topic.factor_type == "SEX":
        comparison_terms = (
            "sex differences", "sex difference", "sex-specific", "sex specific",
            "gender differences", "gender difference", "gender-specific",
            "by sex", "between boys and girls", "male-to-female",
        )
        return 3 if any(phrase_present(text, term) for term in comparison_terms) else 0
    terms = factor_vocabulary(topic, expanded=True)
    return 3 if any(phrase_present(text, term) for term in terms) else 0


def factor_relevance_fields(
    *, title: str, abstract: str, mesh_text: str, topic: MedicalKnowledgeTopic
) -> int:
    if factor_relevance(title, topic):
        return 4
    if factor_relevance(mesh_text, topic):
        return 3
    base = factor_relevance(abstract, topic)
    if not base:
        return 0
    terms = factor_vocabulary(topic, expanded=True)
    repeated = any(phrase_count(abstract, term) >= 2 for term in terms)
    if repeated or any(phrase_present(abstract, term) for term in _RELATIONSHIP_TERMS):
        return 3
    return 0


def pediatric_relevance(text: str) -> int:
    matches = sum(phrase_present(text, term) for term in PEDIATRIC_TERMS)
    return min(3, matches)


def pediatric_relevance_fields(*, title: str, abstract: str, mesh_text: str) -> int:
    if any(phrase_present(title, term) for term in PEDIATRIC_TERMS):
        return 3
    if any(phrase_present(mesh_text, term) for term in PEDIATRIC_TERMS):
        return 2
    if any(phrase_present(abstract, term) for term in PEDIATRIC_TERMS):
        return 2
    return 0


def record_relevance_signals(
    *, title: str, abstract: str, mesh_terms: list[str],
    topic: MedicalKnowledgeTopic, aliases: DiseaseAliasSet
) -> RelevanceSignals:
    mesh_text = " ".join(mesh_terms)
    disease = disease_relevance_fields(
        title=title, abstract=abstract, mesh_text=mesh_text, aliases=aliases
    )
    factor = factor_relevance_fields(
        title=title, abstract=abstract, mesh_text=mesh_text, topic=topic
    )
    if disease and factor and not disease_factor_linked(
        title=title, abstract=abstract, topic=topic, aliases=aliases
    ):
        factor = 0
    return RelevanceSignals(
        disease=disease,
        factor=factor,
        pediatric=pediatric_relevance_fields(
            title=title, abstract=abstract, mesh_text=mesh_text
        ),
    )


def relevance_signals(
    *, text: str, topic: MedicalKnowledgeTopic, aliases: DiseaseAliasSet
) -> RelevanceSignals:
    return RelevanceSignals(
        disease=disease_relevance(text, aliases),
        factor=factor_relevance(text, topic),
        pediatric=pediatric_relevance(text),
    )
