from __future__ import annotations

from dataclasses import dataclass
import re
from xml.etree import ElementTree

from defusedxml import ElementTree as DefusedElementTree
from defusedxml.common import DefusedXmlException

from app.services.pmc_client import PmcParseError


_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_SPACE = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class PmcSection:
    heading: str
    text: str
    order: int


@dataclass(frozen=True)
class ParsedPmcArticle:
    sections: tuple[PmcSection, ...]
    has_body_content: bool
    license_name: str | None
    license_url: str | None


@dataclass(frozen=True)
class SelectedPmcContent:
    text: str
    is_excerpt: bool


def normalize_text(value: str) -> str:
    return _SPACE.sub(" ", value).strip()


def _element_text(element: ElementTree.Element | None) -> str:
    if element is None:
        return ""
    return normalize_text(" ".join(element.itertext()))


def _section_paragraphs(section: ElementTree.Element) -> str:
    # Only direct paragraphs belong to this section. Nested sections are visited
    # separately, avoiding duplicated text and excluding tables/figures/scripts.
    return normalize_text(" ".join(_element_text(node) for node in section.findall("./p")))


def _license(article: ElementTree.Element) -> tuple[str | None, str | None]:
    license_node = article.find("./front/article-meta/permissions/license")
    if license_node is None:
        return None, None
    name = normalize_text(license_node.get("license-type") or "") or None
    url = license_node.get(_XLINK_HREF) or license_node.get("href")
    if not url:
        external = license_node.find(".//ext-link")
        if external is not None:
            url = external.get(_XLINK_HREF) or external.get("href") or _element_text(external)
    return name, normalize_text(url or "") or None


def parse_pmc_article(xml_content: bytes | str) -> ParsedPmcArticle:
    raw = xml_content if isinstance(xml_content, bytes) else xml_content.encode("utf-8")
    try:
        # PMC JATS commonly includes a legitimate external DTD declaration.
        # DefusedXML permits that declaration but blocks entity expansion and
        # external-resource resolution, so article XML remains untrusted data.
        root = DefusedElementTree.fromstring(
            raw, forbid_dtd=False, forbid_entities=True, forbid_external=True
        )
    except (ElementTree.ParseError, DefusedXmlException, ValueError) as exc:
        raise PmcParseError("PMC EFetch returned invalid XML") from exc

    article = root if root.tag.rsplit("}", 1)[-1] == "article" else root.find(".//article")
    if article is None:
        raise PmcParseError("PMC EFetch response contains no article")

    sections: list[PmcSection] = []
    order = 0
    abstract_parts = [
        _element_text(node)
        for node in article.findall("./front/article-meta/abstract")
        if _element_text(node)
    ]
    if abstract_parts:
        sections.append(PmcSection("Abstract", normalize_text(" ".join(abstract_parts)), order))
        order += 1

    body = article.find("./body")
    has_body_content = False
    if body is not None:
        direct_body = normalize_text(" ".join(_element_text(node) for node in body.findall("./p")))
        if direct_body:
            has_body_content = True
            sections.append(PmcSection("Body", direct_body, order))
            order += 1
        for section in body.iterfind(".//sec"):
            text = _section_paragraphs(section)
            if not text:
                continue
            has_body_content = True
            heading = _element_text(section.find("./title")) or "Untitled section"
            sections.append(PmcSection(heading, text, order))
            order += 1

    if not sections:
        raise PmcParseError("PMC article has no usable abstract or body text")
    license_name, license_url = _license(article)
    return ParsedPmcArticle(tuple(sections), has_body_content, license_name, license_url)


def _priority(heading: str) -> int:
    value = heading.casefold()
    if "method" in value or "material" in value:
        return 0
    if "result" in value or "finding" in value:
        return 1
    if "discussion" in value:
        return 2
    if "conclusion" in value:
        return 3
    if "abstract" in value or "summary" in value:
        return 4
    if "introduction" in value or "background" in value:
        return 5
    return 6


def _bounded_sentence_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    sentences = _SENTENCE_END.split(text)
    selected: list[str] = []
    used = 0
    for sentence in sentences:
        candidate = sentence.strip()
        if not candidate:
            continue
        added = len(candidate) + (1 if selected else 0)
        if used + added > max_chars:
            break
        selected.append(candidate)
        used += added
    return " ".join(selected)


def select_bounded_pmc_content(
    article: ParsedPmcArticle, *, max_chars: int
) -> SelectedPmcContent:
    if max_chars < 200:
        raise ValueError("PMC content bound must be at least 200 characters")
    ordered = sorted(article.sections, key=lambda item: (_priority(item.heading), item.order))
    all_blocks = [f"[{section.heading}]\n{section.text}" for section in ordered]
    complete = "\n\n".join(all_blocks)
    if len(complete) <= max_chars:
        return SelectedPmcContent(complete, is_excerpt=False)

    selected: list[str] = []
    used = 0
    for section in ordered:
        prefix = f"[{section.heading}]\n"
        separator = 2 if selected else 0
        available = max_chars - used - separator - len(prefix)
        if available < 80:
            continue
        body = _bounded_sentence_text(section.text, available)
        if not body:
            continue
        block = f"{prefix}{body}"
        selected.append(block)
        used += separator + len(block)
        if used >= max_chars - 80:
            break
    if not selected:
        raise PmcParseError("PMC article cannot be bounded without cutting unusable text")
    return SelectedPmcContent("\n\n".join(selected), is_excerpt=True)
