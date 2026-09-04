from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable, Literal, Mapping
import unicodedata

from app.auto_medical_knowledge_schemas import (
    AutoNumericClaimProposal,
    NumericClaimKind,
)


_SPACE_GROUP = " \u00a0\u202f"
_NUMBER_BODY = rf"(?:\d{{1,3}}(?:[{_SPACE_GROUP}]\d{{3}})+|\d+(?:[.,·]\d+)*)"
_NUMBER_ATOM = rf"[+\-−]?{_NUMBER_BODY}"
_RANGE_RE = re.compile(
    rf"(?<![\w])(?P<left>{_NUMBER_ATOM})\s*(?:[–—]|-|\bto\b|\bđến\b)\s*"
    rf"(?P<right>{_NUMBER_ATOM})(?![\w])",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(rf"(?<![\w])(?P<number>{_NUMBER_ATOM})(?![\w])")
_YEAR = r"(?:18\d{2}|19\d{2}|20\d{2}|2100)"
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\.?"
)
_TEMPORAL_YEAR_RANGE_RE = re.compile(
    rf"(?<![\w])(?:(?P<left_month>{_MONTH})\s+)?(?P<left>{_YEAR})"
    rf"(?:\s+(?P<left_month_after>{_MONTH}))?\s*"
    rf"(?P<connector>[–—-]|\bto\b|\band\b|\bđến\b)\s*"
    rf"(?:(?P<right_month>{_MONTH})\s+)?(?P<right>{_YEAR})"
    rf"(?:\s+(?P<right_month_after>{_MONTH}))?(?![\w])",
    re.IGNORECASE,
)
_COUNT_TERMS_RE = re.compile(
    r"\b(?:ca|trường\s+hợp|bệnh\s+nhân|trẻ(?:\s+em)?|người|mẫu|"
    r"cases?|patients?|children|participants?|subjects?|admissions?|hospitali[sz]ed)\b",
    re.IGNORECASE,
)
_AGE_TERMS_RE = re.compile(
    r"\b(?:tuổi|tháng\s+tuổi|nhóm\s+tuổi|độ\s+tuổi|years?\s+old|months?\s+old|age)\b",
    re.IGNORECASE,
)
_TEMPORAL_SIGNAL_RE = re.compile(
    r"(?:study\s+period|data\s+collected|study\s+was\s+conducted|"
    r"conducted|enrolled\s+between|during|between|from|years|"
    r"giai\s+đoạn|từ\s+năm|trong\s+khoảng|trong\s+các\s+năm|"
    r"nghiên\s+cứu\s+từ|dữ\s+liệu\s+từ)",
    re.IGNORECASE,
)
_MEDICAL_RANGE_SUFFIX_RE = re.compile(
    r"^\s*(?:%|‰|°\s*[cf]|mg|g|kg|ml|l|mm|cm|m|km(?:/h)?|"
    r"years?\s+old|months?\s+old|tuổi)\b|^\s*(?:%|‰)",
    re.IGNORECASE,
)
_GROUP_COUNT_TERMS_RE = re.compile(r"\b(?:groups?|nh\u00f3m)\b", re.IGNORECASE)


@dataclass(frozen=True)
class NumericMetadata:
    pmids: tuple[str, ...] = ()
    publication_years: tuple[int, ...] = ()
    source_ids: tuple[int, ...] = ()
    dois: tuple[str, ...] = ()
    disease_group_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnsupportedNumericClaim:
    field: str
    value: str


@dataclass(frozen=True)
class NumericEvidenceSnapshot:
    source_id: int
    evidence_content_id: int
    evidence_text: str


@dataclass(frozen=True)
class VerifiedNumericClaim:
    claim_order: int
    claim_kind: str
    value_text: str
    unit: str | None
    source_id: int
    evidence_content_id: int
    support_start: int
    support_end: int
    support_sha256: str


NumericKindClassificationOutcome = Literal[
    "VALID", "TAXONOMY_MISMATCH", "SEMANTIC_INVALID"
]


@dataclass(frozen=True)
class NumericKindClassification:
    """Provider-independent result for one exact numeric declaration.

    A taxonomy mismatch is returned only when the selected evidence and the
    Parent-facing prose independently resolve to one identical bounded kind.
    Ambiguous or conflicting meaning remains a non-repairable semantic error.
    """

    outcome: NumericKindClassificationOutcome
    supported_kind: NumericClaimKind | None


class NumericClaimContractViolation(ValueError):
    def __init__(
        self,
        code: str,
        safe_detail: str,
        *,
        field: str | None = None,
        source_id: int | None = None,
        numeric_value: str | None = None,
    ) -> None:
        super().__init__(safe_detail)
        self.code = code
        self.safe_detail = safe_detail
        self.field = field
        self.source_id = source_id
        self.numeric_value = numeric_value


@dataclass(frozen=True)
class _Occurrence:
    raw: str
    start: int
    end: int
    keys: frozenset[str]
    count_context: bool
    age_context: bool
    range_parts: tuple["_Occurrence", "_Occurrence"] | None = None
    temporal_explicit: bool = False


def _window_has(pattern: re.Pattern[str], text: str, start: int, end: int) -> bool:
    return bool(pattern.search(text[max(0, start - 36) : min(len(text), end + 36)]))


def _literal_key(raw: str) -> str:
    value = raw.replace("−", "-").replace("\u00a0", " ").replace("\u202f", " ")
    return "literal:" + re.sub(r"\s+", " ", value.strip())


def _canonical_keys(raw: str, *, count_context: bool) -> frozenset[str]:
    """Return only interpretations that are deterministic from syntax/context.

    A single separator followed by exactly three digits is intentionally
    ambiguous. It only receives a grouping interpretation when both evidence
    and generated prose identify a count population; otherwise only identical
    formatting can match.
    """

    compact = raw.replace("−", "-").replace("\u00a0", " ").replace("\u202f", " ")
    compact = compact.strip()
    sign = ""
    if compact[:1] in {"+", "-"}:
        sign, compact = compact[0], compact[1:]
    keys = {_literal_key(raw)}

    if " " in compact:
        groups = compact.split(" ")
        if (
            groups[0].isdigit()
            and 1 <= len(groups[0]) <= 3
            and all(group.isdigit() and len(group) == 3 for group in groups[1:])
        ):
            integer_value = f"{sign}{''.join(groups)}"
            keys.add(f"integer:{integer_value}")
            if count_context:
                keys.add(f"count-integer:{integer_value}")
        return frozenset(keys)

    separators = [(index, char) for index, char in enumerate(compact) if char in ".,·"]
    if not separators:
        if compact.isdigit():
            integer_value = f"{sign}{int(compact)}"
            keys.add(f"integer:{integer_value}")
            if count_context:
                keys.add(f"count-integer:{integer_value}")
        return frozenset(keys)

    segments = re.split(r"[.,·]", compact)
    if not all(segment.isdigit() and segment for segment in segments):
        return frozenset(keys)

    if len(separators) == 1:
        whole, tail = segments
        if len(tail) == 3 and whole != "0":
            if count_context:
                keys.add(f"count-integer:{sign}{int(whole + tail)}")
            return frozenset(keys)
        keys.add(f"decimal:{sign}{int(whole)}.{tail.rstrip('0') or '0'}")
        return frozenset(keys)

    separator_chars = [char for _, char in separators]
    if len(set(separator_chars)) == 1 and all(len(part) == 3 for part in segments[1:]):
        keys.add(f"integer:{sign}{int(''.join(segments))}")
        return frozenset(keys)

    tail = segments[-1]
    leading = segments[:-1]
    if len(tail) in {1, 2} and all(
        part.isdigit() and (index == 0 or len(part) == 3)
        for index, part in enumerate(leading)
    ):
        keys.add(
            f"decimal:{sign}{int(''.join(leading))}.{tail.rstrip('0') or '0'}"
        )
    return frozenset(keys)


def _single_occurrence(text: str, raw: str, start: int, end: int) -> _Occurrence:
    count_context = _window_has(_COUNT_TERMS_RE, text, start, end) or _window_has(
        _GROUP_COUNT_TERMS_RE, text, start, end
    )
    return _Occurrence(
        raw=raw,
        start=start,
        end=end,
        keys=_canonical_keys(raw, count_context=count_context),
        count_context=count_context,
        age_context=_window_has(_AGE_TERMS_RE, text, start, end),
    )


def _temporal_year_range_occurrence(
    text: str, match: re.Match[str]
) -> _Occurrence | None:
    """Classify a bounded four-digit range without treating all ranges as dates."""

    connector = match.group("connector").lower()
    before = text[max(0, match.start() - 48) : match.start()]
    after = text[match.end() : min(len(text), match.end() + 32)]
    has_month = any(
        match.group(name)
        for name in (
            "left_month",
            "left_month_after",
            "right_month",
            "right_month_after",
        )
    )
    has_signal = bool(_TEMPORAL_SIGNAL_RE.search(before))
    explicit = has_month or has_signal or connector in {"to", "đến"}
    if connector == "and" and not explicit:
        # Two unrelated years must never be joined into a study period.
        return None
    if _MEDICAL_RANGE_SUFFIX_RE.search(after):
        return None

    left = _single_occurrence(
        text, match.group("left"), match.start("left"), match.end("left")
    )
    right = _single_occurrence(
        text, match.group("right"), match.start("right"), match.end("right")
    )
    if left.age_context or right.age_context:
        return None
    start_year = int(match.group("left"))
    end_year = int(match.group("right"))
    if start_year > end_year:
        return None
    return _Occurrence(
        raw=match.group(0),
        start=match.start(),
        end=match.end(),
        keys=frozenset({f"temporal-year-range:{start_year}:{end_year}"}),
        count_context=False,
        age_context=False,
        range_parts=(left, right),
        temporal_explicit=explicit,
    )


def _extract_occurrences(text: str) -> list[_Occurrence]:
    ranges: list[_Occurrence] = []
    occupied: list[tuple[int, int]] = []
    for match in _TEMPORAL_YEAR_RANGE_RE.finditer(text):
        occurrence = _temporal_year_range_occurrence(text, match)
        if occurrence is None:
            continue
        ranges.append(occurrence)
        occupied.append((match.start(), match.end()))
    for match in _RANGE_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in occupied):
            continue
        left = _single_occurrence(
            text, match.group("left"), match.start("left"), match.end("left")
        )
        right = _single_occurrence(
            text, match.group("right"), match.start("right"), match.end("right")
        )
        range_keys = {
            f"range:{left_key}|{right_key}"
            for left_key in left.keys
            for right_key in right.keys
        }
        ranges.append(
            _Occurrence(
                raw=match.group(0),
                start=match.start(),
                end=match.end(),
                keys=frozenset(range_keys),
                count_context=left.count_context or right.count_context,
                age_context=left.age_context or right.age_context,
                range_parts=(left, right),
            )
        )
        occupied.append((match.start(), match.end()))

    singles = []
    for match in _NUMBER_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in occupied):
            continue
        singles.append(
            _single_occurrence(
                text, match.group("number"), match.start("number"), match.end("number")
            )
        )
    return [*ranges, *singles]


def _doi_spans(text: str, dois: Iterable[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    lowered = text.lower()
    for doi in dois:
        needle = (doi or "").strip().lower()
        if not needle:
            continue
        start = 0
        while (index := lowered.find(needle, start)) >= 0:
            spans.append((index, index + len(needle)))
            start = index + len(needle)
    return spans


def _digits(raw: str) -> str | None:
    value = raw.replace("+", "").replace("-", "").replace("−", "")
    return value if value.isdigit() else None


def _is_metadata_occurrence(
    text: str,
    occurrence: _Occurrence,
    metadata: NumericMetadata,
    *,
    doi_spans: list[tuple[int, int]],
) -> bool:
    if occurrence.range_parts is not None:
        return False
    if any(start <= occurrence.start and occurrence.end <= end for start, end in doi_spans):
        return True
    value = _digits(occurrence.raw)
    if value is None:
        return False
    before = text[max(0, occurrence.start - 32) : occurrence.start].lower()
    after = text[occurrence.end : min(len(text), occurrence.end + 16)].lower()
    immediate_before = text[: occurrence.start].rstrip()
    immediate_after = text[occurrence.end :].lstrip()
    if re.match(r"\s*(?:%|‰)", after):
        return False
    if value in metadata.pmids and re.search(r"(?:pmid|pubmed)\s*[:#]?\s*$", before):
        return True
    if value in {str(year) for year in metadata.publication_years}:
        if re.search(r"(?:năm|year|published|publication|xuất\s+bản)\s*[:#]?\s*$", before):
            return True
        if immediate_before.endswith("(") and immediate_after.startswith(")"):
            return True
    if value in {str(source_id) for source_id in metadata.source_ids}:
        if re.search(r"(?:source(?:_id)?|nguồn|mã\s+nguồn)\s*[:#]?\s*$", before):
            return True
        if immediate_before.endswith("[") and immediate_after.startswith("]"):
            return True
    if value in metadata.disease_group_ids and re.search(
        r"(?:disease\s+group|group\s+id|nhóm\s+bệnh|mã\s+nhóm)\s*[:#]?\s*$",
        before,
    ):
        return True
    return False


def _matches_supported(
    candidate: _Occurrence,
    supported: Iterable[_Occurrence],
    *,
    require_age_context: bool = False,
) -> bool:
    for item in supported:
        if require_age_context and not (candidate.age_context and item.age_context):
            continue
        shared = candidate.keys & item.keys
        if not shared:
            continue
        if any("count-integer:" in key for key in shared):
            if not (candidate.count_context and item.count_context):
                continue
        if any(key.startswith("temporal-year-range:") for key in shared):
            # A bare year-looking output may match, but persisted evidence must
            # actually encode a temporal interval rather than two values.
            if not item.temporal_explicit:
                continue
        return True
    return False


def find_unsupported_numeric_claim(
    fields: Mapping[str, str],
    evidence_texts: Iterable[str],
    *,
    context_text: str = "",
    metadata: NumericMetadata | None = None,
) -> UnsupportedNumericClaim | None:
    """Return the first unsupported numeric claim without changing any prose."""

    metadata = metadata or NumericMetadata()
    evidence_occurrences = [
        occurrence
        for text in evidence_texts
        for occurrence in _extract_occurrences(text)
    ]
    context_occurrences = _extract_occurrences(context_text)
    for field, text in fields.items():
        spans = _doi_spans(text, metadata.dois)
        for occurrence in _extract_occurrences(text):
            if _is_metadata_occurrence(text, occurrence, metadata, doi_spans=spans):
                continue
            if _matches_supported(occurrence, evidence_occurrences):
                continue
            if _matches_supported(
                occurrence,
                context_occurrences,
                require_age_context=any(item.age_context for item in context_occurrences),
            ):
                continue
            return UnsupportedNumericClaim(field=field, value=occurrence.raw)
    return None


_PERCENT_SIGNAL_RE = re.compile(
    r"(?:%|\u2030|\bpercent(?:age)?\b|ph\u1ea7n\s+tr\u0103m)", re.IGNORECASE
)
_RATE_SIGNAL_RE = re.compile(
    r"(?:\brate\b|\bper\b|/\s*\d|tr\u00ean\s+m\u1ed7i|t\u1ef7\s+su\u1ea5t)",
    re.IGNORECASE,
)
_RATIO_SIGNAL_RE = re.compile(
    r"(?:\bratio\b|odds\s+ratio|risk\s+ratio|relative\s+risk|hazard\s+ratio|"
    r"(?-i:\b(?:RR|OR|HR)\b)|\btimes?\b|l\u1ea7n)",
    re.IGNORECASE,
)
_MEASUREMENT_SIGNAL_RE = re.compile(
    r"(?:\u00b0\s*[cf]|\b(?:mg|g|kg|ml|l|mm|cm|m|km|mmhg|kpa|mmol/l|mg/dl)\b)",
    re.IGNORECASE,
)
_AGE_SIGNAL_RE = re.compile(
    r"(?:\baged?\b|\byears?\s+old\b|\bmonths?\s+old\b|"
    r"tu\u1ed5i|nh\u00f3m\s+tu\u1ed5i|\u0111\u1ed9\s+tu\u1ed5i)",
    re.IGNORECASE,
)
_DURATION_SIGNAL_RE = re.compile(
    r"\b(?:days?|weeks?|months?|years?|hours?|ng\u00e0y|tu\u1ea7n|th\u00e1ng|n\u0103m|gi\u1edd)\b",
    re.IGNORECASE,
)
_DASH_TRANSLATION = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2212": "-",
})
_DETERMINISTIC_KINDS: tuple[NumericClaimKind, ...] = (
    "COUNT",
    "PERCENTAGE",
    "RATE",
    "RATIO_OR_EFFECT",
    "MEASUREMENT",
    "AGE",
    "DURATION",
    "TEMPORAL_PERIOD",
)


def _normalized_text_with_offsets(text: str) -> tuple[str, list[int]]:
    """Apply only harmless quote normalization while preserving source offsets."""

    output: list[str] = []
    offsets: list[int] = []
    for original_index, original_char in enumerate(text):
        expanded = unicodedata.normalize("NFKC", original_char).translate(_DASH_TRANSLATION)
        for char in expanded:
            if char.isspace():
                if output and output[-1] != " ":
                    output.append(" ")
                    offsets.append(original_index)
                continue
            output.append(char)
            offsets.append(original_index)
    if output and output[-1] == " ":
        output.pop()
        offsets.pop()
    return "".join(output), offsets


def _verified_support_location(evidence: str, supporting_text: str) -> tuple[int, int] | None:
    normalized_evidence, offsets = _normalized_text_with_offsets(evidence)
    normalized_support, _ = _normalized_text_with_offsets(supporting_text)
    if not normalized_support:
        return None
    normalized_start = normalized_evidence.find(normalized_support)
    if normalized_start < 0:
        return None
    normalized_end = normalized_start + len(normalized_support)
    return offsets[normalized_start], offsets[normalized_end - 1] + 1


def _kind_window(text: str, occurrence: _Occurrence) -> str:
    return text[max(0, occurrence.start - 28) : min(len(text), occurrence.end + 32)]


def _occurrence_has_kind(
    text: str,
    occurrence: _Occurrence,
    kind: NumericClaimKind,
    *,
    unit: str | None = None,
) -> bool:
    window = _kind_window(text, occurrence)
    if kind == "COUNT":
        return occurrence.count_context
    if kind == "PERCENTAGE":
        return bool(_PERCENT_SIGNAL_RE.search(window))
    if kind == "RATE":
        return bool(_RATE_SIGNAL_RE.search(window))
    if kind == "RATIO_OR_EFFECT":
        return bool(_RATIO_SIGNAL_RE.search(window))
    if kind == "MEASUREMENT":
        if _MEASUREMENT_SIGNAL_RE.search(window):
            return True
        return bool(unit and unicodedata.normalize("NFKC", unit).lower() in window.lower())
    if kind == "AGE":
        return occurrence.age_context or bool(_AGE_SIGNAL_RE.search(window))
    if kind == "DURATION":
        return not occurrence.age_context and bool(_DURATION_SIGNAL_RE.search(window))
    if kind == "TEMPORAL_PERIOD":
        return any(key.startswith("temporal-year-range:") for key in occurrence.keys)
    return False


def _claim_value_occurrences(claim: AutoNumericClaimProposal) -> list[_Occurrence]:
    occurrences = _extract_occurrences(claim.value_text)
    if not 1 <= len(occurrences) <= 2:
        return []
    return occurrences


def _kind_shape_is_valid(
    kind: NumericClaimKind, occurrences: list[_Occurrence]
) -> bool:
    if kind in {"RATE", "RATIO_OR_EFFECT"}:
        return 1 <= len(occurrences) <= 2
    if len(occurrences) != 1:
        return False
    occurrence = occurrences[0]
    if kind == "COUNT":
        return occurrence.range_parts is None and any(
            key.startswith("integer:") for key in occurrence.keys
        )
    if kind == "TEMPORAL_PERIOD":
        return any(
            key.startswith("temporal-year-range:") for key in occurrence.keys
        )
    return True


def _unit_semantic_kinds(unit: str | None) -> frozenset[NumericClaimKind]:
    """Return only meanings made explicit by a unit; empty/ambiguous is neutral."""

    if not unit:
        return frozenset()
    normalized = unicodedata.normalize("NFKC", unit).strip()
    kinds: set[NumericClaimKind] = set()
    if _PERCENT_SIGNAL_RE.search(normalized):
        kinds.add("PERCENTAGE")
    if _RATE_SIGNAL_RE.search(normalized):
        kinds.add("RATE")
    if _RATIO_SIGNAL_RE.search(normalized):
        kinds.add("RATIO_OR_EFFECT")
    if _MEASUREMENT_SIGNAL_RE.search(normalized):
        kinds.add("MEASUREMENT")
    if _COUNT_TERMS_RE.search(normalized) or _GROUP_COUNT_TERMS_RE.search(normalized):
        kinds.add("COUNT")
    return frozenset(kinds)


def _unit_allows_kind(unit: str | None, kind: NumericClaimKind) -> bool:
    explicit = _unit_semantic_kinds(unit)
    return not explicit or kind in explicit


def _occurrences_match_for_any_kind(
    declared: _Occurrence, candidate: _Occurrence
) -> bool:
    if declared.keys & candidate.keys:
        return True
    declared_count = _canonical_keys(declared.raw, count_context=True)
    candidate_count = _canonical_keys(candidate.raw, count_context=True)
    return any(
        key.startswith("count-integer:")
        for key in declared_count & candidate_count
    )


def _candidate_kinds_for_text(
    value_occurrences: list[_Occurrence],
    text_occurrences: list[tuple[str, _Occurrence]],
    *,
    unit: str | None,
) -> frozenset[NumericClaimKind]:
    candidates: set[NumericClaimKind] = set()
    for kind in _DETERMINISTIC_KINDS:
        if not _kind_shape_is_valid(kind, value_occurrences):
            continue
        if not _unit_allows_kind(unit, kind):
            continue
        if all(
            any(
                _numeric_occurrences_equivalent(kind, value_occurrence, occurrence)
                and _occurrence_has_kind(text, occurrence, kind, unit=unit)
                for text, occurrence in text_occurrences
            )
            for value_occurrence in value_occurrences
        ):
            candidates.add(kind)
    return frozenset(candidates)


def classify_numeric_claim_kind(
    claim: AutoNumericClaimProposal,
    value_occurrences: list[_Occurrence],
    support_occurrences: list[_Occurrence],
    prose_occurrences: list[tuple[str, _Occurrence]],
) -> NumericKindClassification:
    """Classify evidence/prose meaning without trusting the declared enum."""

    support_items = [(claim.supporting_text, item) for item in support_occurrences]
    support_kinds = _candidate_kinds_for_text(
        value_occurrences, support_items, unit=claim.unit
    )
    prose_has_every_value = all(
        any(
            _occurrences_match_for_any_kind(value_occurrence, occurrence)
            for _text, occurrence in prose_occurrences
        )
        for value_occurrence in value_occurrences
    )
    if prose_has_every_value:
        prose_kinds = _candidate_kinds_for_text(
            value_occurrences, prose_occurrences, unit=claim.unit
        )
        compatible = support_kinds & prose_kinds
    else:
        # Preserve the established UNUSED path when a declaration never appears
        # in Parent prose; it is not enough evidence for taxonomy-only repair.
        compatible = support_kinds

    if len(compatible) != 1:
        return NumericKindClassification("SEMANTIC_INVALID", None)
    supported_kind = next(iter(compatible))
    if claim.claim_kind == supported_kind:
        return NumericKindClassification("VALID", supported_kind)
    if prose_has_every_value:
        return NumericKindClassification("TAXONOMY_MISMATCH", supported_kind)
    return NumericKindClassification("SEMANTIC_INVALID", supported_kind)


def _numeric_occurrences_equivalent(
    kind: NumericClaimKind, declared: _Occurrence, candidate: _Occurrence
) -> bool:
    if kind == "COUNT":
        declared_keys = _canonical_keys(declared.raw, count_context=True)
        candidate_keys = _canonical_keys(candidate.raw, count_context=True)
        return any(
            key.startswith("count-integer:")
            for key in declared_keys & candidate_keys
        )
    if kind == "TEMPORAL_PERIOD":
        return any(
            key.startswith("temporal-year-range:")
            for key in declared.keys & candidate.keys
        )
    return bool(declared.keys & candidate.keys)


def _raise_contract(
    code: str,
    safe_detail: str,
    *,
    field: str | None = None,
    source_id: int | None = None,
    numeric_value: str | None = None,
) -> None:
    raise NumericClaimContractViolation(
        code,
        safe_detail,
        field=field,
        source_id=source_id,
        numeric_value=numeric_value,
    )


def validate_numeric_claim_contract(
    fields: Mapping[str, str],
    claims: Iterable[AutoNumericClaimProposal],
    snapshots: Iterable[NumericEvidenceSnapshot],
    *,
    context_text: str = "",
    metadata: NumericMetadata | None = None,
) -> tuple[VerifiedNumericClaim, ...]:
    """Validate V2 declarations against exact selected immutable snapshots."""

    metadata = metadata or NumericMetadata()
    snapshot_by_source = {snapshot.source_id: snapshot for snapshot in snapshots}
    claim_list = list(claims)
    signatures: set[tuple[str, str, str, int, str]] = set()
    verified: list[VerifiedNumericClaim] = []
    declared_occurrences: list[list[_Occurrence]] = []
    context_occurrences = _extract_occurrences(context_text)
    parent_occurrences: list[tuple[str, _Occurrence]] = []
    for _field, text in fields.items():
        doi_spans = _doi_spans(text, metadata.dois)
        for occurrence in _extract_occurrences(text):
            if _is_metadata_occurrence(text, occurrence, metadata, doi_spans=doi_spans):
                continue
            if _matches_supported(
                occurrence,
                context_occurrences,
                require_age_context=any(item.age_context for item in context_occurrences),
            ):
                continue
            parent_occurrences.append((text, occurrence))

    for index, claim in enumerate(claim_list):
        signature = (
            claim.claim_kind,
            claim.value_text,
            claim.unit or "",
            claim.source_id,
            claim.supporting_text,
        )
        if signature in signatures:
            _raise_contract(
                "AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE",
                "Generated output contains a duplicate numeric claim declaration.",
                field=f"numeric_claims.{index}",
                source_id=claim.source_id,
                numeric_value=claim.value_text,
            )
        signatures.add(signature)
        snapshot = snapshot_by_source.get(claim.source_id)
        if snapshot is None:
            _raise_contract(
                "AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID",
                "Declared numeric support is not in the exact selected source set.",
                field=f"numeric_claims.{index}.source_id",
                source_id=claim.source_id,
                numeric_value=claim.value_text,
            )
        location = _verified_support_location(
            snapshot.evidence_text, claim.supporting_text
        )
        if location is None:
            _raise_contract(
                "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH",
                "Declared supporting text is not an exact excerpt of the selected evidence snapshot.",
                field=f"numeric_claims.{index}.supporting_text",
                source_id=claim.source_id,
                numeric_value=claim.value_text,
            )
        value_occurrences = _claim_value_occurrences(claim)
        if not value_occurrences:
            _raise_contract(
                "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID",
                "Numeric claim value shape cannot be classified safely.",
                field=f"numeric_claims.{index}.claim_kind",
                source_id=claim.source_id,
                numeric_value=claim.value_text,
            )
        support_occurrences = _extract_occurrences(claim.supporting_text)
        if not all(
            any(
                _occurrences_match_for_any_kind(value_occurrence, support_occurrence)
                for support_occurrence in support_occurrences
            )
            for value_occurrence in value_occurrences
        ):
            _raise_contract(
                "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH",
                "Selected evidence excerpt does not contain the declared numeric value.",
                field=f"numeric_claims.{index}.value_text",
                source_id=claim.source_id,
                numeric_value=claim.value_text,
            )
        classification = classify_numeric_claim_kind(
            claim,
            value_occurrences,
            support_occurrences,
            parent_occurrences,
        )
        if classification.outcome == "TAXONOMY_MISMATCH":
            _raise_contract(
                "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH",
                "Evidence and Parent prose agree on one numeric meaning, but the declared claim kind differs.",
                field=f"numeric_claims.{index}.claim_kind",
                source_id=claim.source_id,
                numeric_value=claim.value_text,
            )
        if classification.outcome == "SEMANTIC_INVALID":
            _raise_contract(
                "AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID",
                "Numeric meaning is ambiguous or conflicts between evidence, unit, and Parent prose.",
                field=f"numeric_claims.{index}.claim_kind",
                source_id=claim.source_id,
                numeric_value=claim.value_text,
            )
        if not all(
            any(
                _numeric_occurrences_equivalent(
                    claim.claim_kind, value_occurrence, support_occurrence
                )
                and _occurrence_has_kind(
                    claim.supporting_text,
                    support_occurrence,
                    claim.claim_kind,
                    unit=claim.unit,
                )
                for support_occurrence in support_occurrences
            )
            for value_occurrence in value_occurrences
        ):
            _raise_contract(
                "AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH",
                "Selected evidence excerpt does not support the declared numeric value and kind.",
                field=f"numeric_claims.{index}.value_text",
                source_id=claim.source_id,
                numeric_value=claim.value_text,
            )
        support_start, support_end = location
        exact_excerpt = snapshot.evidence_text[support_start:support_end]
        verified.append(
            VerifiedNumericClaim(
                claim_order=index,
                claim_kind=claim.claim_kind,
                value_text=claim.value_text,
                unit=claim.unit,
                source_id=claim.source_id,
                evidence_content_id=snapshot.evidence_content_id,
                support_start=support_start,
                support_end=support_end,
                support_sha256=hashlib.sha256(exact_excerpt.encode("utf-8")).hexdigest(),
            )
        )
        declared_occurrences.append(value_occurrences)

    used_value_indexes: list[set[int]] = [set() for _ in claim_list]
    for field, text in fields.items():
        doi_spans = _doi_spans(text, metadata.dois)
        for occurrence in _extract_occurrences(text):
            if _is_metadata_occurrence(text, occurrence, metadata, doi_spans=doi_spans):
                continue
            if _matches_supported(
                occurrence,
                context_occurrences,
                require_age_context=any(item.age_context for item in context_occurrences),
            ):
                continue
            matches: list[tuple[int, int]] = []
            for claim_index, claim in enumerate(claim_list):
                if not _occurrence_has_kind(
                    text, occurrence, claim.claim_kind, unit=claim.unit
                ):
                    continue
                for value_index, value_occurrence in enumerate(
                    declared_occurrences[claim_index]
                ):
                    if _numeric_occurrences_equivalent(
                        claim.claim_kind, value_occurrence, occurrence
                    ):
                        matches.append((claim_index, value_index))
            matched_claims = {claim_index for claim_index, _ in matches}
            if not matches:
                _raise_contract(
                    "AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED",
                    "Parent-facing prose contains a medical number without a declared source-backed numeric claim.",
                    field=field,
                    numeric_value=occurrence.raw,
                )
            if len(matched_claims) != 1:
                _raise_contract(
                    "AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE",
                    "Multiple numeric declarations match the same Parent-facing number.",
                    field=field,
                    numeric_value=occurrence.raw,
                )
            claim_index = next(iter(matched_claims))
            used_value_indexes[claim_index].update(
                value_index
                for matched_claim_index, value_index in matches
                if matched_claim_index == claim_index
            )

    for index, claim in enumerate(claim_list):
        if len(used_value_indexes[index]) != len(declared_occurrences[index]):
            _raise_contract(
                "AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED",
                "Declared numeric claim is not fully used in Parent-facing prose.",
                field=f"numeric_claims.{index}",
                source_id=claim.source_id,
                numeric_value=claim.value_text,
            )
    return tuple(verified)
