"""Deterministic citation extraction, identity checks, and linkage findings."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisJob, DocumentIR
from app.models.review import EvidenceAnchor, Finding
from app.models.rubric import CriterionVersion

LINKED = "LINKED"
ORPHAN_MENTION = "ORPHAN_MENTION"
UNCITED_REFERENCE = "UNCITED_REFERENCE"
AMBIGUOUS = "AMBIGUOUS"
AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
VERIFIED = "VERIFIED"
METADATA_MISMATCH = "METADATA_MISMATCH"
UNRESOLVED = "UNRESOLVED"
PARSED = "PARSED"
PARSER_UNCERTAIN = "PARSER_UNCERTAIN"
FRAGMENTED_REFERENCE = "FRAGMENTED_REFERENCE"
BIBLIOGRAPHY_NOT_FOUND = "BIBLIOGRAPHY_NOT_FOUND"
FINDINGS_TRUNCATED = "FINDINGS_TRUNCATED"

type CitationAnchor = tuple[str, int, int | None, int | None]
type CitationIssueRow = tuple[str, str, tuple[CitationAnchor, ...], str]

_CITATION_TYPES = {"CITATION", "CITATION_IDENTITY", "CITATION_LINKAGE"}
_HEADING_WORDS = {
    "reference",
    "references",
    "bibliography",
    "workscited",
    "literaturecited",
    "referencesandbibliography",
    "tailieu",
    "tailieuthamkhao",
    "tailieuthamkhaonguon",
    "nguonthamkhao",
}
_NUMERIC_MENTION = re.compile(r"\[(?P<body>[\d\s,–-]{1,512})\]")
_OVERSIZED_NUMERIC_MENTION = re.compile(r"\[[\d\s,–-]{513}")
_NUMERIC_PART = re.compile(r"\s*(\d{1,6})(?:\s*[-–]\s*(\d{1,6}))?\s*")
_REFERENCE_NUMBER = re.compile(r"^\s*(?:\[\s*(\d+)\s*\]|(\d+)\s*[.)])\s*(.+?)\s*$")
_DOI = re.compile(
    r"(?i)(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)?"
    r'(10\s*\.\s*\d{4,9}\s*/\s*[^\s"]+)'
)
_ARXIV = re.compile(
    r"(?i)(?:arxiv\s*:\s*|arxiv\s*\.\s*org\s*/\s*(?:abs|pdf)\s*/\s*)"
    r"(\d{4}\s*\.\s*\d{4,5}(?:\s*v\s*\d+)?)"
)
_PARENTHETICAL = re.compile(r"\((?P<body>[^()]{3,240})\)")
_AUTHOR_NAME = r"[A-Za-zÀ-ỹ][\wÀ-ỹ'’-]*"
_AUTHOR_GROUP = rf"{_AUTHOR_NAME}(?:\s+(?:et\s+al\.|(?:&|and)\s+{_AUTHOR_NAME}))?"
_AUTHOR_YEAR_PART = re.compile(
    rf"^\s*(?P<author>{_AUTHOR_GROUP}),\s*" r"(?P<year>19\d{2}|20\d{2})[a-z]?\s*$",
    re.IGNORECASE,
)
_NARRATIVE_NAME = r"[A-ZÀ-Ỹ][\wÀ-ỹ'’-]*"
_AFFILIATION_NAME = rf"{_NARRATIVE_NAME}(?:\s+{_NARRATIVE_NAME}){{1,5}}"
_AFFILIATION_INDEX = r"\s+\d{1,3}(?:\s*[,;]\s*\d{1,3})*"
_AFFILIATION_AUTHOR_LINE = re.compile(
    rf"^\s*{_AFFILIATION_NAME}{_AFFILIATION_INDEX}"
    rf"(?:\s*,\s*{_AFFILIATION_NAME}{_AFFILIATION_INDEX})*\s*,?\s*$"
)
_NARRATIVE_AUTHOR_GROUP = (
    rf"{_NARRATIVE_NAME}" rf"(?:\s+(?:et\s+al\.|(?:&|and)\s+{_NARRATIVE_NAME}))?"
)
_NARRATIVE_AUTHOR_YEAR = re.compile(
    rf"\b(?P<author>{_NARRATIVE_AUTHOR_GROUP})\s*"
    r"\((?P<year>19\d{2}|20\d{2})[a-z]?\)",
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

_CACHE_TTL_SECONDS = 300.0
_CACHE_MAX = 256
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_CROSSREF_CONCURRENCY = 8
_CROSSREF_MIN_INTERVAL_SECONDS = 0.1
_MAX_CROSSREF_RESOLUTIONS = 64
_MAX_FINDINGS_PER_CRITERION = 128
_MAX_EVIDENCE_ANCHORS_PER_FINDING = 8
_MAX_REFERENCES = 2048
_MAX_MENTIONS = 4096
_MAX_NUMBERS_PER_MENTION = 64
_MAX_NUMERIC_MARKER_CHARS = 512
_MAX_REFERENCE_ANCHORS = 64
_RATE_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0


async def _resolve_references(
    references: Sequence[CitationReference],
) -> list[dict[str, Any] | None]:
    semaphore = asyncio.Semaphore(_CROSSREF_CONCURRENCY)

    async def resolve(reference: CitationReference) -> dict[str, Any] | None:
        async with semaphore:
            return await asyncio.to_thread(resolve_reference, reference)

    selected: list[tuple[int, CitationReference]] = []
    for index, reference in enumerate(references):
        if (
            reference.parser_status == PARSED
            and not (reference.arxiv_id and not reference.doi)
            and len(selected) < _MAX_CROSSREF_RESOLUTIONS
        ):
            selected.append((index, reference))
    resolved = await asyncio.gather(
        *(resolve(reference) for _index, reference in selected)
    )
    results: list[dict[str, Any] | None] = [None] * len(references)
    for (index, _reference), record in zip(selected, resolved, strict=True):
        results[index] = record
    return results


@dataclass(frozen=True)
class CitationReference:
    id: str
    number: int | None
    raw: str
    page_number: int
    element_id: str
    start: int
    end: int
    snippet: str
    doi: str | None = None
    arxiv_id: str | None = None
    title: str | None = None
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str | None = None
    number_explicit: bool = True
    parser_status: str = PARSED
    anchor_element_ids: tuple[str, ...] = ()
    anchor_pages: tuple[int, ...] = ()
    anchor_line_ranges: tuple[tuple[str, int, int | None, int | None], ...] = ()
    line_start: int | None = None
    line_end: int | None = None
    linkage_status: str = UNCITED_REFERENCE
    identity_status: str = UNRESOLVED
    mismatch_fields: tuple[str, ...] = ()
    provider_record: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["authors"] = list(self.authors)
        result["mismatch_fields"] = list(self.mismatch_fields)
        result["anchor_element_ids"] = list(self.anchor_element_ids)
        result["anchor_pages"] = list(self.anchor_pages)
        result["anchor_line_ranges"] = [
            {
                "element_id": element_id,
                "page_number": page_number,
                "line_start": line_start,
                "line_end": line_end,
            }
            for element_id, page_number, line_start, line_end in self.anchor_line_ranges
        ]
        return result


@dataclass(frozen=True)
class CitationMention:
    id: str
    raw: str
    page_number: int
    element_id: str
    start: int
    end: int
    snippet: str
    numbers: tuple[int, ...] = ()
    author: str | None = None
    year: int | None = None
    status: str = ORPHAN_MENTION
    reference_ids: tuple[str, ...] = ()
    parser_status: str = PARSED
    line_start: int | None = None
    line_end: int | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["numbers"] = list(self.numbers)
        result["reference_ids"] = list(self.reference_ids)
        return result


@dataclass
class CitationReport:
    references: list[CitationReference] = field(default_factory=list)
    mentions: list[CitationMention] = field(default_factory=list)
    duplicate_reference_ids: list[str] = field(default_factory=list)
    parser_status: str = PARSED
    bibliography_status: str = BIBLIOGRAPHY_NOT_FOUND
    parser_warnings: list[str] = field(default_factory=list)

    def as_dict(self, *, include_items: bool = True) -> dict[str, Any]:
        counts = Counter(mention.status for mention in self.mentions)
        identity = Counter(reference.identity_status for reference in self.references)
        linked_count = counts.get(LINKED, 0)
        uncertain_references = sum(
            reference.parser_status != PARSED for reference in self.references
        )
        uncertain_mentions = sum(
            mention.parser_status != PARSED for mention in self.mentions
        )
        ambiguous_count = counts.get(AMBIGUOUS, 0) + counts.get(AMBIGUOUS_MAPPING, 0)
        uncited_count = sum(
            1
            for reference in self.references
            if reference.parser_status == PARSED
            and reference.id not in self.cited_reference_ids
        )
        result: dict[str, Any] = {
            "schema_version": 2,
            "parser_status": self.parser_status,
            "bibliography_status": self.bibliography_status,
            "parser_warnings": self.parser_warnings[:32],
            "counts": {
                "references": len(self.references),
                "mentions": len(self.mentions),
                "linked": linked_count,
                "linkage_rate": (
                    linked_count / len(self.mentions) if self.mentions else 0.0
                ),
                "orphan_mentions": counts.get(ORPHAN_MENTION, 0),
                "ambiguous": ambiguous_count,
                "ambiguous_mapping": counts.get(AMBIGUOUS_MAPPING, 0),
                "uncited_references": uncited_count,
                "verified": identity.get(VERIFIED, 0),
                "verified_rate": (
                    identity.get(VERIFIED, 0) / len(self.references)
                    if self.references
                    else 0.0
                ),
                "metadata_mismatch": identity.get(METADATA_MISMATCH, 0),
                "unresolved": identity.get(UNRESOLVED, 0),
                "parser_uncertain": uncertain_references + uncertain_mentions,
                "fragmented_references": sum(
                    reference.parser_status == FRAGMENTED_REFERENCE
                    for reference in self.references
                ),
                "bibliography_not_found": int(
                    self.bibliography_status == BIBLIOGRAPHY_NOT_FOUND
                ),
                "duplicates": len(self.duplicate_reference_ids),
            },
            "duplicate_reference_ids": self.duplicate_reference_ids[:64],
        }
        if include_items:
            result["references"] = [
                reference.as_dict() for reference in self.references[:64]
            ]
            result["mentions"] = [mention.as_dict() for mention in self.mentions[:128]]
        return result

    @property
    def cited_reference_ids(self) -> set[str]:
        return {
            reference_id
            for mention in self.mentions
            if mention.status == LINKED
            for reference_id in mention.reference_ids
        }


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _tokens(value: str | None) -> set[str]:
    return set(_normalize(value).split())


def _similarity(left: str | None, right: str | None) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def canonicalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    candidate = re.sub(r"\s*\.\s*", ".", value)
    candidate = re.sub(r"\s*/\s*", "/", candidate)
    match = re.search(
        r"(?i)(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)?"
        r'(10\s*\.\s*\d{4,9}\s*/\s*[^\s"]+)',
        candidate,
    )
    if not match:
        return None
    doi = re.sub(r"\s+", "", match.group(1)).rstrip(".,;:")
    closing_pairs = {")": "(", "]": "[", "}": "{", ">": "<"}
    while (
        doi
        and doi[-1] in closing_pairs
        and doi.count(doi[-1]) > doi.count(closing_pairs[doi[-1]])
    ):
        doi = doi[:-1]
    return doi.casefold()


def extract_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    candidate = re.sub(r"\s*\.\s*", ".", value)
    match = re.search(
        r"(?i)(?:arxiv\s*:\s*|arxiv\s*\.\s*org\s*/\s*(?:abs|pdf)\s*/\s*)"
        r"(\d{4}\s*\.\s*\d{4,5}(?:\s*v\s*\d+)?)",
        candidate,
    )
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1)).lower()


def _stable_id(prefix: str, *parts: object) -> str:
    encoded = "|".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:20]}"


def _bounded_snippet(
    text: str, start: int, end: int, limit: int = 240
) -> tuple[int, int, str]:
    left = max(0, start - 80)
    right = min(len(text), max(end, start + 1) + 160)
    snippet = text[left:right].strip()
    if len(snippet) > limit:
        snippet = snippet[:limit].rstrip()
    return start, end, snippet


def _heading_matches(text: str) -> bool:
    normalized = re.sub(
        r"^(?:\d{1,3}(?:\s+\d{1,3})*|[ivxlcdm]+)\s+",
        "",
        _normalize(text),
    )
    return normalized.replace(" ", "") in _HEADING_WORDS


def _reference_heading_pages(content: Mapping[str, Any]) -> set[int]:
    pages = {
        int(section.get("page_number", 0) or 0)
        for section in content.get("sections", ())
        if isinstance(section, Mapping)
        and section.get("page_number") is not None
        and _heading_matches(str(section.get("text", "")))
    }
    for page in content.get("pages", ()):
        if not isinstance(page, Mapping):
            continue
        if any(
            _heading_matches(line) for line in str(page.get("text", "")).splitlines()
        ):
            pages.add(int(page.get("number", 0) or 0))
    return {page for page in pages if page > 0}


def _section_membership(content: Mapping[str, Any]) -> set[str]:
    sections = [
        section
        for section in content.get("sections", ())
        if isinstance(section, Mapping)
    ]
    matches = {
        str(section.get("id"))
        for section in sections
        if section.get("id") and _heading_matches(str(section.get("text", "")))
    }
    if not matches:
        return set()
    by_id = {
        str(section.get("id")): section for section in sections if section.get("id")
    }
    descendants = set(matches)
    for section_id, section in by_id.items():
        parent = section.get("parent_id")
        seen: set[str] = set()
        while isinstance(parent, str) and parent not in seen:
            if parent in matches:
                descendants.add(section_id)
                break
            seen.add(parent)
            parent = by_id.get(parent, {}).get("parent_id")
    return descendants


def _parse_reference_fields(raw: str) -> dict[str, Any]:
    doi = canonicalize_doi(raw)
    arxiv_id = extract_arxiv_id(raw)
    clean = re.sub(r"https?://\S+|www\.\S+", " ", raw)
    clean = _DOI.sub(" ", clean)
    clean = _ARXIV.sub(" ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    year_match = _YEAR.search(clean)
    year = int(year_match.group(0)) if year_match else None
    title_match = re.search(r"[\"“](.+?)[\"”]", clean)
    title = title_match.group(1).strip() if title_match else None
    author_prefix = clean[: title_match.start()] if title_match else clean

    if title is None:
        for boundary in re.finditer(r"\.\s+(?=[A-ZÀ-Ỹ“])", clean):
            left = clean[: boundary.start()].strip()
            if len(left) < 8 or not (
                "," in left or ";" in left or re.search(r"\band\b", left, re.I)
            ):
                continue
            right = clean[boundary.end() :].strip()
            right = re.sub(
                r"^\(?\s*(?:19|20)\d{2}[a-z]?\s*\)?[.,: -]*",
                "",
                right,
                flags=re.I,
            )
            candidate = re.split(
                r"\.\s+(?=(?:in|proceedings|journal|conference|international)\b)",
                right,
                maxsplit=1,
                flags=re.I,
            )[0].strip(" .,:;")
            if 8 <= len(candidate) <= 240:
                title = candidate
                author_prefix = left
                break
    if title is None and year_match:
        tail = clean[year_match.end() :].lstrip(" .,:;()-")
        candidate = re.split(r"\s*[.]\s+|\s+[—–-]\s+", tail, maxsplit=1)[0]
        if 8 <= len(candidate) <= 240:
            title = candidate.strip(' .,:;"“”') or None

    author_prefix = re.sub(r"\(?\s*(?:19|20)\d{2}[a-z]?\s*\)?", "", author_prefix)
    author_prefix = re.sub(r"^[^A-Za-zÀ-ỹ]+", "", author_prefix).strip(" .,:;()")
    authors = tuple(
        part.strip()
        for part in re.split(r"\s*(?:;|\band\b|&)\s*", author_prefix, flags=re.I)
        if part.strip()
    )
    venue = None
    if title_match:
        venue_tail = clean[title_match.end() :].lstrip(" .,:;")
        venue = (
            re.split(r"\s*[.]\s+|\s+\d{1,4}\s*[,(:]", venue_tail, maxsplit=1)[0].strip(
                " .,:;()"
            )[:160]
            or None
        )
    return {
        "doi": doi,
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": authors[:16],
        "year": year,
        "venue": venue,
    }


def _reference_parser_status(raw: str, _number: int | None) -> str:
    text = " ".join(raw.split())
    if len(text.split()) < 5 or text.endswith(("-", "‐", "‑", "...")):
        return FRAGMENTED_REFERENCE
    return PARSED


def _reference_from_paragraph(
    paragraph: Mapping[str, Any],
    number: int | None,
    raw: str,
    marker_start: int,
    *,
    number_explicit: bool = True,
    parser_status: str | None = None,
    anchor_paragraphs: Sequence[Mapping[str, Any]] = (),
) -> CitationReference:
    anchors = (
        paragraph,
        *anchor_paragraphs[: _MAX_REFERENCE_ANCHORS - 1],
    )
    element_id = str(paragraph.get("id", ""))
    page_number = int(paragraph.get("page_number", 0) or 0)
    text = str(paragraph.get("text", ""))
    start, end, snippet = _bounded_snippet(
        text, marker_start, min(len(text), marker_start + len(raw))
    )
    fields = _parse_reference_fields(raw)
    reference_id = (
        f"reference-{number}"
        if number is not None
        else _stable_id("reference", _normalize(raw))
    )
    anchor_ranges = tuple(
        (
            str(anchor.get("id", "")),
            int(anchor.get("page_number", 0) or 0),
            (
                int(anchor["line_start"])
                if anchor.get("line_start") is not None
                else None
            ),
            int(anchor["line_end"]) if anchor.get("line_end") is not None else None,
        )
        for anchor in anchors
        if anchor.get("id") and int(anchor.get("page_number", 0) or 0) > 0
    )
    return CitationReference(
        id=reference_id,
        number=number,
        raw=raw[:2000],
        page_number=page_number,
        element_id=element_id,
        start=start,
        end=end,
        snippet=snippet,
        number_explicit=number_explicit,
        parser_status=parser_status or _reference_parser_status(raw, number),
        anchor_element_ids=tuple(anchor[0] for anchor in anchor_ranges),
        anchor_pages=tuple(anchor[1] for anchor in anchor_ranges),
        anchor_line_ranges=anchor_ranges,
        line_start=anchor_ranges[0][2] if anchor_ranges else None,
        line_end=anchor_ranges[0][3] if anchor_ranges else None,
        **fields,
    )


def _expand_numbers(body: str) -> tuple[int, ...] | None:
    if len(body) > _MAX_NUMERIC_MARKER_CHARS:
        return None
    parts = body.split(",")
    if len(parts) > _MAX_NUMBERS_PER_MENTION:
        return None
    result: list[int] = []
    for part in parts:
        match = _NUMERIC_PART.fullmatch(part)
        if match is None:
            return None
        first = int(match.group(1))
        second = int(match.group(2)) if match.group(2) else None
        if second is None:
            values = (first,)
        elif second < first or second - first > 50:
            return None
        else:
            values = range(first, second + 1)
        if len(result) + len(values) > _MAX_NUMBERS_PER_MENTION:
            return None
        result.extend(values)
    return tuple(dict.fromkeys(result))


def _author_year_mentions(
    text: str,
    *,
    limit: int,
) -> list[tuple[str, int, int, str, int]]:
    if limit <= 0:
        return []
    result: list[tuple[str, int, int, str, int]] = []
    for group in _PARENTHETICAL.finditer(text):
        body_start = group.start("body")
        for part in re.finditer(r"[^;]+", group.group("body")):
            raw_part = part.group(0)
            stripped = raw_part.strip()
            match = _AUTHOR_YEAR_PART.fullmatch(stripped)
            if match is None:
                continue
            leading = len(raw_part) - len(raw_part.lstrip())
            start = body_start + part.start() + leading
            end = start + len(stripped)
            result.append(
                (
                    stripped,
                    start,
                    end,
                    match.group("author"),
                    int(match.group("year")),
                )
            )
            if len(result) >= limit:
                return sorted(result, key=lambda item: (item[1], item[2], item[0]))
    for match in _NARRATIVE_AUTHOR_YEAR.finditer(text):
        result.append(
            (
                match.group(0),
                match.start(),
                match.end(),
                match.group("author"),
                int(match.group("year")),
            )
        )
        if len(result) >= limit:
            break
    return sorted(result, key=lambda item: (item[1], item[2], item[0]))


def _is_title_affiliation_line(text: str, page_number: int) -> bool:
    return page_number == 1 and _AFFILIATION_AUTHOR_LINE.fullmatch(text) is not None


_REFERENCE_START = re.compile(
    r"(?:^|\s)(?:\[\s*(?P<bracket>\d{1,4})\s*\]|(?P<bare>\d{1,3})\s*[.)])\s*"
)
_UNNUMBERED_REFERENCE_START = re.compile(
    r"(?:•\s*|(?:^|\s)\s*-\s+)" r"(?=(?:[A-ZÀ-Ỹ]\.|[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s|,)))"
)
_UNNUMBERED_AUTHOR_YEAR_START = re.compile(
    r"(?=(?:[A-ZÀ-Ỹ][\wÀ-ỹ'’-]+,\s*(?:[A-ZÀ-Ỹ]\.\s*){1,4}"
    r"(?:,\s*[A-ZÀ-Ỹ][\wÀ-ỹ'’-]+,\s*(?:[A-ZÀ-Ỹ]\.\s*){1,4})*"
    r"(?:,?\s+(?:and|&)\s+[A-ZÀ-Ỹ][\wÀ-ỹ'’-]+,\s*"
    r"(?:[A-ZÀ-Ỹ]\.\s*){1,4})?\((?:19|20)\d{2}[a-z]?\)))"
)
_FOOTNOTE_BIBLIOGRAPHY = re.compile(r"^\s*[1-9]\d{0,3}\s+[A-ZÀ-Ỹ]")


def _previous_nonspace(text: str, index: int) -> str | None:
    index -= 1
    while index >= 0 and text[index].isspace():
        index -= 1
    return text[index] if index >= 0 else None


def _unnumbered_author_year_parts(
    text: str,
    *,
    limit: int,
) -> list[tuple[int | None, str, int]]:
    starts: list[int] = []
    for match in _UNNUMBERED_AUTHOR_YEAR_START.finditer(text):
        if match.start() == 0 or _previous_nonspace(text, match.start()) == ".":
            starts.append(match.start())
            if len(starts) >= limit:
                break
    if len(starts) < 2 or starts[0] != 0:
        return []
    return [
        (
            None,
            text[
                start : starts[index + 1] if index + 1 < len(starts) else None
            ].strip(),
            start,
        )
        for index, start in enumerate(starts)
    ]


def _reference_parts(
    text: str,
    *,
    limit: int,
) -> list[tuple[int | None, str, int]]:
    unnumbered_matches = []
    for match in _UNNUMBERED_REFERENCE_START.finditer(text):
        unnumbered_matches.append(match)
        if len(unnumbered_matches) >= limit:
            break
    markers: list[tuple[int, int, int | None]] = [
        (match.start(), match.end(), None) for match in unnumbered_matches
    ]
    for match in _REFERENCE_START.finditer(text):
        if len(markers) >= limit:
            break
        if unnumbered_matches and match.group("bare"):
            continue
        if match.group("bare") and _previous_nonspace(text, match.start()) in {
            ":",
            "/",
        }:
            continue
        number_text = match.group("bracket") or match.group("bare")
        markers.append((match.start(), match.end(), int(number_text)))
    markers.sort()
    if not markers:
        inline_parts = _unnumbered_author_year_parts(text, limit=limit)
        if inline_parts:
            return inline_parts
    parts: list[tuple[int | None, str, int]] = []
    for index, (_marker_start, raw_start, number) in enumerate(markers):
        raw_end = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        raw = text[raw_start:raw_end].strip()
        if raw:
            parts.append((number, raw, raw_start))
    return parts


def _starts_reference(text: str) -> bool:
    return bool(re.match(r"^\s*(?:\[\s*\d+\s*\]|\d{1,3}\s*[.)])", text))


def _looks_bibliographic(text: str) -> bool:
    return (
        len(text.split()) >= 5
        and bool(_YEAR.search(text) or canonicalize_doi(text) or extract_arxiv_id(text))
        and any(mark in text for mark in (".", ",", ":", ";"))
    )


def _looks_unnumbered_reference_start(text: str) -> bool:
    if not _looks_bibliographic(text):
        return False
    year_match = _YEAR.search(text[:200])
    if year_match is None or not re.match(r"^[A-ZÀ-Ỹ]", text):
        return False
    author_prefix = text[: year_match.start()]
    return (
        "," in author_prefix
        or "." in author_prefix
        or bool(re.search(r"\bet\s+al\b|\band\b|&", author_prefix, re.IGNORECASE))
    )


def _reference_table_paragraphs(
    content: Mapping[str, Any],
    reference_sections: set[str],
    heading_pages: set[int],
) -> list[dict[str, Any]]:
    sections = [
        section
        for section in content.get("sections", ())
        if isinstance(section, Mapping)
        and str(section.get("id", "")) in reference_sections
    ]
    candidate_pages = {
        int(section.get("page_number", 0) or 0)
        for section in sections
        if section.get("page_number") is not None
    } | heading_pages
    if not candidate_pages:
        return []
    first_heading_page = min(candidate_pages)
    section_id = next(iter(reference_sections), "bibliography")
    result: list[dict[str, Any]] = []
    for table in content.get("tables", ()):
        if not isinstance(table, Mapping):
            continue
        if int(table.get("page_end", 0) or 0) < first_heading_page:
            continue
        table_id = str(table.get("id", ""))
        for row in table.get("rows", ()):
            if not isinstance(row, Mapping):
                continue
            cells = [
                str(cell.get("text", "")).strip()
                for cell in row.get("cells", ())
                if isinstance(cell, Mapping) and str(cell.get("text", "")).strip()
            ]
            text = " ".join(cells)
            if not text:
                continue
            page_number = int(row.get("page_number", 0) or 0)
            result.append(
                {
                    "id": table_id,
                    "section_id": section_id,
                    "page_number": page_number,
                    "line_start": None,
                    "line_end": None,
                    "text": text,
                    "bbox": row.get("bbox", {}),
                }
            )
    return result


def _reference_paragraphs(
    paragraphs: Sequence[Mapping[str, Any]],
    reference_sections: set[str],
    heading_pages: set[int],
) -> tuple[list[Mapping[str, Any]], str, list[str]]:
    if reference_sections:
        selected = [
            paragraph
            for paragraph in paragraphs
            if paragraph.get("section_id") in reference_sections
            and str(paragraph.get("text", "")).strip()
        ]
        return selected, PARSED, []

    if heading_pages:
        first_heading_page = min(heading_pages)
        selected = [
            paragraph
            for paragraph in paragraphs
            if int(paragraph.get("page_number", 0) or 0) >= first_heading_page
            and str(paragraph.get("text", "")).strip()
        ]
        return selected, PARSED, []

    pages = [
        int(paragraph.get("page_number", 0) or 0)
        for paragraph in paragraphs
        if paragraph.get("page_number") is not None
    ]
    if not pages:
        return (
            [],
            BIBLIOGRAPHY_NOT_FOUND,
            ["No pages available for bibliography fallback."],
        )
    cutoff = max(1, max(pages) - max(2, len(set(pages)) // 3))
    selected: list[Mapping[str, Any]] = []
    active = False
    for paragraph in paragraphs:
        page = int(paragraph.get("page_number", 0) or 0)
        text = str(paragraph.get("text", "")).strip()
        if page < cutoff or not text:
            continue
        is_start = (
            _starts_reference(text)
            or _looks_unnumbered_reference_start(text)
            or bool(canonicalize_doi(text) or extract_arxiv_id(text))
        )
        if is_start or (active and _looks_bibliographic(text)):
            selected.append(paragraph)
            active = True
    if len(selected) < 2:
        return (
            [],
            BIBLIOGRAPHY_NOT_FOUND,
            ["Bibliography heading not detected; no trailing reference cluster."],
        )
    return (
        selected,
        PARSER_UNCERTAIN,
        ["Bibliography heading not detected; trailing reference cluster used."],
    )


def _collect_reference_groups(
    paragraphs: Sequence[Mapping[str, Any]],
    *,
    max_groups: int = _MAX_REFERENCES + 1,
) -> tuple[list[dict[str, Any]], set[str]]:
    groups: list[dict[str, Any]] = []
    reference_paragraph_ids: set[str] = set()
    active: dict[str, Any] | None = None
    for paragraph in paragraphs:
        text = " ".join(str(paragraph.get("text", "")).split())
        if not text:
            continue
        paragraph_id = str(paragraph.get("id", ""))
        reference_paragraph_ids.add(paragraph_id)
        if len(groups) >= max_groups:
            continue
        parts = _reference_parts(text, limit=max_groups - len(groups))
        if parts:
            marker_starts = [
                match.start()
                for pattern in (_REFERENCE_START, _UNNUMBERED_REFERENCE_START)
                if (match := pattern.search(text)) is not None
            ]
            first_start = (
                min(marker_starts) if marker_starts else min(part[2] for part in parts)
            )
            prefix = text[:first_start].strip()
            if prefix and active is not None:
                active["parts"].append(prefix)
                active["anchors"].append(paragraph)
            for number, raw, marker_start in parts:
                active = {
                    "number": number,
                    "parts": [raw],
                    "marker_start": marker_start,
                    "paragraph": paragraph,
                    "anchors": [],
                }
                groups.append(active)
                if len(groups) >= max_groups:
                    break
        elif _looks_unnumbered_reference_start(text) and (
            active is None or active["number"] is None
        ):
            active = {
                "number": None,
                "parts": [text],
                "marker_start": 0,
                "paragraph": paragraph,
                "anchors": [],
            }
            groups.append(active)
        elif active is not None:
            if (
                active["number"] is not None
                and _FOOTNOTE_BIBLIOGRAPHY.match(text)
                and _looks_bibliographic(text)
            ):
                reference_paragraph_ids.discard(paragraph_id)
                continue
            active["parts"].append(text)
            active["anchors"].append(paragraph)
        elif _looks_bibliographic(text):
            active = {
                "number": None,
                "parts": [text],
                "marker_start": 0,
                "paragraph": paragraph,
                "anchors": [],
            }
            groups.append(active)
        else:
            reference_paragraph_ids.discard(paragraph_id)
    return groups, reference_paragraph_ids


def _valid_trailing_reference_cluster(groups: Sequence[Mapping[str, Any]]) -> bool:
    if len(groups) < 2:
        return False
    numbers = [group.get("number") for group in groups]
    if all(number is None for number in numbers):
        return True
    return numbers == list(range(1, len(numbers) + 1))


def _unique_reference(
    reference: CitationReference,
    used_ids: set[str],
) -> CitationReference:
    if reference.id not in used_ids:
        used_ids.add(reference.id)
        return reference
    attempt = 1
    reference_id = ""
    while not reference_id or reference_id in used_ids:
        reference_id = _stable_id(
            "reference",
            reference.number,
            reference.element_id,
            reference.start,
            _normalize(reference.raw),
            attempt,
        )
        attempt += 1
    used_ids.add(reference_id)
    return CitationReference(**{**asdict(reference), "id": reference_id})


def parse_citations(document_ir: DocumentIR | Mapping[str, Any]) -> CitationReport:
    content = (
        document_ir.content
        if isinstance(document_ir, DocumentIR) or hasattr(document_ir, "content")
        else document_ir
    )
    paragraphs = [
        paragraph
        for paragraph in content.get("paragraphs", ())
        if isinstance(paragraph, Mapping)
    ]
    reference_sections = _section_membership(content)
    heading_pages = _reference_heading_pages(content)
    reference_paragraphs, bibliography_status, warnings = _reference_paragraphs(
        paragraphs, reference_sections, heading_pages
    )
    groups, reference_paragraph_ids = _collect_reference_groups(reference_paragraphs)
    if (
        bibliography_status == PARSER_UNCERTAIN
        and not _valid_trailing_reference_cluster(groups)
    ):
        groups = []
        reference_paragraph_ids.clear()
        bibliography_status = BIBLIOGRAPHY_NOT_FOUND
        warnings = ["Trailing reference candidates are not a coherent bibliography."]
    if heading_pages and not groups:
        table_groups, table_reference_ids = _collect_reference_groups(
            _reference_table_paragraphs(content, reference_sections, heading_pages)
        )
        groups = table_groups
        reference_paragraph_ids.update(table_reference_ids)
    if heading_pages and not groups:
        bibliography_status = BIBLIOGRAPHY_NOT_FOUND
        warnings = ["Bibliography heading found but no entries were extracted."]
    references_truncated = len(groups) > _MAX_REFERENCES
    if references_truncated:
        groups = groups[:_MAX_REFERENCES]
        warnings.append(f"Bibliography truncated at {_MAX_REFERENCES} references.")
    references: list[CitationReference] = []
    reference_ids: set[str] = set()
    ordered_number = 1
    for group_index, group in enumerate(groups):
        explicit_number = group["number"]
        number = explicit_number if explicit_number is not None else ordered_number
        ordered_number = max(ordered_number + 1, number + 1)
        raw = " ".join(group["parts"])[:2000]
        parser_status = _reference_parser_status(raw, explicit_number)
        if (
            bibliography_status != PARSED
            or (references_truncated and group_index == len(groups) - 1)
        ) and parser_status == PARSED:
            parser_status = PARSER_UNCERTAIN
        references.append(
            _unique_reference(
                _reference_from_paragraph(
                    group["paragraph"],
                    number,
                    raw,
                    group["marker_start"],
                    number_explicit=explicit_number is not None,
                    parser_status=parser_status,
                    anchor_paragraphs=group["anchors"],
                ),
                reference_ids,
            )
        )

    mentions: list[CitationMention] = []
    mentions_truncated = False

    def append_mention(mention: CitationMention) -> bool:
        nonlocal mentions_truncated
        if len(mentions) >= _MAX_MENTIONS:
            mentions_truncated = True
            return False
        mentions.append(mention)
        return True

    for paragraph in paragraphs:
        element_id = str(paragraph.get("id", ""))
        if element_id in reference_paragraph_ids:
            continue
        text = str(paragraph.get("text", ""))
        line_start = paragraph.get("line_start")
        line_end = paragraph.get("line_end")
        oversized = _OVERSIZED_NUMERIC_MENTION.search(text)
        if oversized is not None:
            raw_start = oversized.start()
            raw_end = min(len(text), raw_start + _MAX_NUMERIC_MARKER_CHARS)
            start, end, snippet = _bounded_snippet(text, raw_start, raw_end)
            if not append_mention(
                CitationMention(
                    id=_stable_id(
                        "mention",
                        paragraph.get("page_number", 0),
                        element_id,
                        raw_start,
                        "oversized-numeric-marker",
                    ),
                    raw=text[raw_start:raw_end],
                    page_number=int(paragraph.get("page_number", 0) or 0),
                    element_id=element_id,
                    start=start,
                    end=end,
                    snippet=snippet,
                    parser_status=PARSER_UNCERTAIN,
                    line_start=int(line_start) if line_start is not None else None,
                    line_end=int(line_end) if line_end is not None else None,
                )
            ):
                break
        for match in _NUMERIC_MENTION.finditer(text):
            numbers = _expand_numbers(match.group("body"))
            if numbers is not None and 0 in numbers:
                continue
            raw = match.group(0)
            start, end, snippet = _bounded_snippet(text, match.start(), match.end())
            if not append_mention(
                CitationMention(
                    id=_stable_id(
                        "mention",
                        paragraph.get("page_number", 0),
                        element_id,
                        match.start(),
                        raw,
                    ),
                    raw=raw,
                    page_number=int(paragraph.get("page_number", 0) or 0),
                    element_id=element_id,
                    start=start,
                    end=end,
                    snippet=snippet,
                    numbers=numbers or (),
                    parser_status=(PARSED if numbers is not None else PARSER_UNCERTAIN),
                    line_start=int(line_start) if line_start is not None else None,
                    line_end=int(line_end) if line_end is not None else None,
                )
            ):
                break
        if mentions_truncated:
            break
        superscript_markers = paragraph.get("superscript_markers", ())
        if not isinstance(superscript_markers, Sequence) or isinstance(
            superscript_markers, (str, bytes)
        ):
            superscript_markers = ()
        if _is_title_affiliation_line(text, int(paragraph.get("page_number", 0) or 0)):
            superscript_markers = ()
        for marker in superscript_markers:
            if not isinstance(marker, Mapping):
                continue
            number = marker.get("number")
            raw_start = marker.get("start")
            raw_end = marker.get("end")
            if (
                type(number) is not int
                or number <= 0
                or type(raw_start) is not int
                or type(raw_end) is not int
                or raw_start < 0
                or raw_end <= raw_start
                or raw_end > len(text)
            ):
                continue
            raw = str(marker.get("raw") or text[raw_start:raw_end])
            start, end, snippet = _bounded_snippet(text, raw_start, raw_end)
            if not append_mention(
                CitationMention(
                    id=_stable_id(
                        "mention",
                        paragraph.get("page_number", 0),
                        element_id,
                        raw_start,
                        raw,
                    ),
                    raw=raw,
                    page_number=int(paragraph.get("page_number", 0) or 0),
                    element_id=element_id,
                    start=start,
                    end=end,
                    snippet=snippet,
                    numbers=(number,),
                    line_start=int(line_start) if line_start is not None else None,
                    line_end=int(line_end) if line_end is not None else None,
                )
            ):
                break
        if mentions_truncated:
            break
        for raw, raw_start, raw_end, author, year in _author_year_mentions(
            text,
            limit=_MAX_MENTIONS - len(mentions) + 1,
        ):
            start, end, snippet = _bounded_snippet(text, raw_start, raw_end)
            if not append_mention(
                CitationMention(
                    id=_stable_id(
                        "mention",
                        paragraph.get("page_number", 0),
                        element_id,
                        raw_start,
                        raw,
                    ),
                    raw=raw,
                    page_number=int(paragraph.get("page_number", 0) or 0),
                    element_id=element_id,
                    start=start,
                    end=end,
                    snippet=snippet,
                    author=author,
                    year=year,
                    line_start=int(line_start) if line_start is not None else None,
                    line_end=int(line_end) if line_end is not None else None,
                )
            ):
                break
        if mentions_truncated:
            break
    if mentions_truncated and mentions:
        mentions[-1] = CitationMention(
            **{**asdict(mentions[-1]), "parser_status": PARSER_UNCERTAIN}
        )
        warnings.append(f"Citation mentions truncated at {_MAX_MENTIONS} items.")

    by_number: dict[int, list[CitationReference]] = {}
    for reference in references:
        if reference.number is not None and reference.number_explicit:
            by_number.setdefault(reference.number, []).append(reference)
    by_author_year: dict[tuple[int, str], dict[str, CitationReference]] = {}
    for reference in references:
        if reference.year is None:
            continue
        for author in reference.authors:
            for token in _tokens(author):
                by_author_year.setdefault((reference.year, token), {})[
                    reference.id
                ] = reference
    parser_uncertain = (
        bibliography_status != PARSED
        or references_truncated
        or mentions_truncated
        or any(reference.parser_status != PARSED for reference in references)
        or any(mention.parser_status != PARSED for mention in mentions)
    )
    for index, mention in enumerate(mentions):
        matched: list[CitationReference]
        if mention.parser_status != PARSED:
            matched = []
            status = AMBIGUOUS_MAPPING
            mentions[index] = CitationMention(
                **{
                    **asdict(mention),
                    "status": status,
                    "reference_ids": (),
                }
            )
            continue
        if mention.numbers:
            number_matches = [by_number.get(number, []) for number in mention.numbers]
            matched = [
                reference
                for references_for_number in number_matches
                for reference in references_for_number
            ]
            if all(
                len(references_for_number) == 1
                for references_for_number in number_matches
            ) and not any(reference.parser_status != PARSED for reference in matched):
                status = LINKED
            elif matched:
                status = AMBIGUOUS_MAPPING if parser_uncertain else AMBIGUOUS
            else:
                status = AMBIGUOUS_MAPPING if parser_uncertain else ORPHAN_MENTION
        else:
            author_tokens = _normalize(mention.author).split()
            candidates = list(
                by_author_year.get(
                    (mention.year, author_tokens[0] if author_tokens else ""),
                    {},
                ).values()
            )
            if len(candidates) == 1 and candidates[0].parser_status == PARSED:
                matched = candidates
                status = LINKED
            elif candidates:
                matched = candidates
                status = AMBIGUOUS_MAPPING if parser_uncertain else AMBIGUOUS
            else:
                matched = []
                status = AMBIGUOUS_MAPPING if parser_uncertain else ORPHAN_MENTION
        mentions[index] = CitationMention(
            **{
                **asdict(mention),
                "status": status,
                "parser_status": (
                    PARSER_UNCERTAIN if status == AMBIGUOUS_MAPPING else PARSED
                ),
                "reference_ids": tuple(reference.id for reference in matched),
            }
        )
    cited_ids = {
        reference_id
        for mention in mentions
        if mention.status == LINKED
        for reference_id in mention.reference_ids
    }
    references = [
        CitationReference(
            **{
                **asdict(reference),
                "linkage_status": (
                    PARSER_UNCERTAIN
                    if reference.parser_status != PARSED
                    else LINKED if reference.id in cited_ids else UNCITED_REFERENCE
                ),
            }
        )
        for reference in references
    ]
    seen_identity: dict[str, str] = {}
    duplicate_ids: list[str] = []
    for reference in references:
        key = reference.doi or _normalize(reference.raw)
        if key and key in seen_identity:
            duplicate_ids.append(reference.id)
        elif key:
            seen_identity[key] = reference.id
    return CitationReport(
        references=references,
        mentions=mentions,
        duplicate_reference_ids=duplicate_ids,
        parser_status=(PARSER_UNCERTAIN if parser_uncertain else PARSED),
        bibliography_status=bibliography_status,
        parser_warnings=warnings,
    )


def _nonstring_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _crossref_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if _nonstring_sequence(value) and value and isinstance(value[0], str):
        return value[0]
    return None


def _crossref_payload(
    payload: Mapping[str, Any], *, query: str | None = None
) -> dict[str, Any] | None:
    message = payload.get("message")
    if isinstance(message, Mapping) and _nonstring_sequence(message.get("items")):
        items = message.get("items")
        message = items[0] if items and isinstance(items[0], Mapping) else None
    if not isinstance(message, Mapping):
        return None
    raw_authors = message.get("author")
    authors = []
    for author in raw_authors if _nonstring_sequence(raw_authors) else ():
        if isinstance(author, Mapping):
            name = " ".join(
                str(author.get(key, "")).strip()
                for key in ("given", "family")
                if author.get(key)
            ).strip()
            if name:
                authors.append(_normalize(name))
    year = None
    for key in ("published-print", "published", "published-online", "issued"):
        raw_date = message.get(key)
        date_parts = (
            raw_date.get("date-parts", ()) if isinstance(raw_date, Mapping) else ()
        )
        if (
            _nonstring_sequence(date_parts)
            and date_parts
            and _nonstring_sequence(date_parts[0])
            and date_parts[0]
        ):
            with suppress(TypeError, ValueError):
                year = int(date_parts[0][0])
            if year:
                break
    title = _crossref_text(message.get("title"))
    venue = _crossref_text(message.get("container-title"))
    return {
        "provider": "crossref",
        "doi": canonicalize_doi(str(message.get("DOI", ""))),
        "query": query[:240] if query else None,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "external_id": str(message.get("DOI", ""))[:256] or None,
        "comparison": {
            "title": _normalize(title) if title else None,
            "authors": authors[:16],
            "year": year,
            "venue": _normalize(venue) if venue else None,
        },
    }


def _crossref_candidates(
    payload: Mapping[str, Any], *, query: str | None = None
) -> list[dict[str, Any]]:
    message = payload.get("message")
    if not isinstance(message, Mapping):
        return []
    items = message.get("items")
    raw_items = (
        [item for item in items if isinstance(item, Mapping)]
        if _nonstring_sequence(items)
        else [message]
    )
    return [
        record
        for item in raw_items
        if (record := _crossref_payload({"message": item}, query=query)) is not None
    ]


def _wait_for_crossref_rate_limit() -> None:
    global _NEXT_REQUEST_AT
    with _RATE_LOCK:
        now = time.monotonic()
        delay = max(0.0, _NEXT_REQUEST_AT - now)
        _NEXT_REQUEST_AT = max(now, _NEXT_REQUEST_AT) + _CROSSREF_MIN_INTERVAL_SECONDS
    if delay:
        time.sleep(delay)


def _crossref_request(url: str) -> dict[str, Any] | None:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "DocGrading/1.0"}
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=4.0) as response:
                raw = response.read(1_000_000)
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, Mapping):
                return dict(payload)
            return None
        except (OSError, urllib.error.URLError, TimeoutError, ValueError, UnicodeError):
            if attempt == 1:
                return None
    return None


def resolve_reference(reference: CitationReference) -> dict[str, Any] | None:
    """Resolve only against Crossref; arXiv intentionally has no adapter."""
    cache_key = f"doi:{reference.doi}" if reference.doi else None
    now = time.monotonic()
    if cache_key is not None:
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and now - cached[0] < _CACHE_TTL_SECONDS:
                return dict(cached[1])
    if reference.arxiv_id and not reference.doi:
        return None
    if reference.doi:
        url = "https://api.crossref.org/works/" + urllib.parse.quote(
            reference.doi, safe=""
        )
    else:
        query = urllib.parse.quote(reference.raw[:240], safe="")
        url = f"https://api.crossref.org/works?query.bibliographic={query}&rows=5"
    _wait_for_crossref_rate_limit()
    payload = _crossref_request(url)
    query_text = None if reference.doi else reference.raw[:240]
    results = _crossref_candidates(payload, query=query_text) if payload else []
    if reference.doi:
        result = next(
            (
                candidate
                for candidate in results
                if candidate.get("doi") == reference.doi
            ),
            None,
        )
    else:
        eligible: list[tuple[float, dict[str, Any]]] = []
        for candidate in results:
            comparison = candidate.get("comparison", {})
            if not isinstance(comparison, Mapping):
                continue
            title_score = _similarity(reference.title, comparison.get("title"))
            if not reference.title or title_score < 0.70:
                continue
            if reference.authors and not _author_match(
                reference, comparison.get("authors", ())
            ):
                continue
            if reference.year is not None and reference.year != comparison.get("year"):
                continue
            eligible.append((title_score, candidate))
        result = max(eligible, key=lambda item: item[0])[1] if eligible else None
    if result is None:
        return None
    comparison = result.get("comparison", {})
    if not isinstance(comparison, Mapping) or not any(
        comparison.get(field) for field in ("title", "authors", "year", "venue")
    ):
        return None
    if cache_key is not None:
        with _CACHE_LOCK:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[cache_key] = (now, result)
    return result


def _author_match(
    reference: CitationReference, provider_authors: Sequence[Any]
) -> bool:
    expected = reference.authors[0].split(",", 1)[0]
    return any(
        _similarity(expected, str(author)) >= 0.45 for author in provider_authors
    )


def _identity(
    reference: CitationReference, record: Mapping[str, Any] | None
) -> tuple[str, tuple[str, ...]]:
    if reference.parser_status != PARSED:
        return PARSER_UNCERTAIN, ()
    if not record:
        return UNRESOLVED, ()
    comparison = record.get("comparison", {})
    if not isinstance(comparison, Mapping):
        return UNRESOLVED, ()
    if not reference.title or not comparison.get("title"):
        return UNRESOLVED, ()
    if reference.year is None or comparison.get("year") is None:
        return UNRESOLVED, ()
    mismatch: list[str] = []
    if _similarity(reference.title, str(comparison["title"])) < 0.55:
        mismatch.append("title")
    if reference.authors:
        provider_authors = comparison.get("authors")
        if not provider_authors:
            return UNRESOLVED, ()
        if not _author_match(reference, provider_authors):
            mismatch.append("author")
    try:
        if int(reference.year) != int(comparison["year"]):
            mismatch.append("year")
    except (TypeError, ValueError):
        return UNRESOLVED, ()
    if (
        reference.venue
        and comparison.get("venue")
        and _similarity(reference.venue, str(comparison["venue"])) < 0.45
    ):
        mismatch.append("venue")
    return (METADATA_MISMATCH, tuple(mismatch)) if mismatch else (VERIFIED, ())


def _criterion_is_citation(criterion: CriterionVersion) -> bool:
    method = str(getattr(criterion, "evaluation_method", "") or "").upper()
    config = getattr(criterion, "evaluator_config", {}) or {}
    config_type = str(config.get("type", "")).upper()
    return bool(getattr(criterion, "is_enabled", True)) and (
        method in _CITATION_TYPES or config_type in _CITATION_TYPES
    )


async def _clear_existing(
    db: AsyncSession, job: AnalysisJob, criteria: Sequence[CriterionVersion]
) -> None:
    criterion_ids = [criterion.id for criterion in criteria]
    if not criterion_ids:
        return
    finding_ids = list(
        (
            await db.execute(
                sa.select(Finding.id).where(
                    Finding.analysis_job_id == job.id,
                    Finding.criterion_version_id.in_(criterion_ids),
                )
            )
        ).scalars()
    )
    if finding_ids:
        await db.execute(
            sa.delete(EvidenceAnchor).where(EvidenceAnchor.finding_id.in_(finding_ids))
        )
        await db.execute(sa.delete(Finding).where(Finding.id.in_(finding_ids)))


def _reference_anchors(reference: CitationReference) -> tuple[CitationAnchor, ...]:
    if reference.anchor_line_ranges:
        return reference.anchor_line_ranges
    return (
        (
            reference.element_id,
            reference.page_number,
            reference.line_start,
            reference.line_end,
        ),
    )


def _mention_anchors(mention: CitationMention) -> tuple[CitationAnchor, ...]:
    return (
        (
            mention.element_id,
            mention.page_number,
            mention.line_start,
            mention.line_end,
        ),
    )


def _issue_rows(report: CitationReport) -> list[CitationIssueRow]:
    rows: list[CitationIssueRow] = []
    for reference in report.references:
        anchors = _reference_anchors(reference)
        if reference.parser_status != PARSED:
            rows.append(
                (
                    reference.id,
                    reference.parser_status,
                    anchors,
                    reference.snippet,
                )
            )
        elif reference.identity_status in {METADATA_MISMATCH, UNRESOLVED}:
            rows.append(
                (
                    reference.id,
                    reference.identity_status,
                    anchors,
                    reference.snippet,
                )
            )
    for mention in report.mentions:
        if mention.status in {ORPHAN_MENTION, AMBIGUOUS, AMBIGUOUS_MAPPING}:
            rows.append(
                (
                    mention.id,
                    mention.status,
                    _mention_anchors(mention),
                    mention.snippet,
                )
            )
    cited_ids = report.cited_reference_ids
    for reference in report.references:
        if reference.parser_status == PARSED and reference.id not in cited_ids:
            rows.append(
                (
                    reference.id,
                    UNCITED_REFERENCE,
                    _reference_anchors(reference),
                    reference.snippet,
                )
            )
    for reference_id in report.duplicate_reference_ids:
        reference = next(
            (item for item in report.references if item.id == reference_id), None
        )
        if reference:
            rows.append(
                (
                    reference.id,
                    "DUPLICATE",
                    _reference_anchors(reference),
                    reference.snippet,
                )
            )
    return rows


def _bounded_issue_rows(
    rows: Sequence[CitationIssueRow],
) -> tuple[list[CitationIssueRow], set[tuple[str, str]]]:
    bounded: list[CitationIssueRow] = []
    seen_issues: set[tuple[str, str]] = set()
    truncated_anchors: set[tuple[str, str]] = set()
    for key, status, anchors, snippet in rows:
        issue_key = (key, status)
        if issue_key in seen_issues:
            continue
        seen_issues.add(issue_key)
        unique_anchors: list[CitationAnchor] = []
        seen_anchors: set[tuple[str, int]] = set()
        for anchor in anchors:
            anchor_key = (anchor[0], anchor[1])
            if not anchor[0] or anchor[1] <= 0 or anchor_key in seen_anchors:
                continue
            seen_anchors.add(anchor_key)
            unique_anchors.append(anchor)
        if not unique_anchors:
            continue
        if len(unique_anchors) > _MAX_EVIDENCE_ANCHORS_PER_FINDING:
            truncated_anchors.add(issue_key)
            unique_anchors = unique_anchors[:_MAX_EVIDENCE_ANCHORS_PER_FINDING]
            snippet = f"{snippet} Additional evidence anchors omitted."
        bounded.append((key, status, tuple(unique_anchors), snippet))
    if len(bounded) > _MAX_FINDINGS_PER_CRITERION:
        omitted = len(bounded) - (_MAX_FINDINGS_PER_CRITERION - 1)
        first_omitted = bounded[_MAX_FINDINGS_PER_CRITERION - 1]
        bounded = [
            *bounded[: _MAX_FINDINGS_PER_CRITERION - 1],
            (
                "citation-findings-truncated",
                FINDINGS_TRUNCATED,
                first_omitted[2][:1],
                f"{omitted} additional citation findings omitted.",
            ),
        ]
    return bounded, truncated_anchors


def _finding_copy(status: str, reference_or_mention: str) -> tuple[str, str, str]:
    if status == FINDINGS_TRUNCATED:
        return (
            "needs_review",
            "Additional citation findings were truncated by the safety limit.",
            "Review the complete bibliography and citation map manually.",
        )
    if status == METADATA_MISMATCH:
        return (
            "error",
            f"Citation reference {reference_or_mention} metadata mismatches Crossref.",
            "Verify title, author, year, and venue against source.",
        )
    if status == UNRESOLVED:
        return (
            "needs_review",
            f"Citation reference {reference_or_mention} could not be resolved.",
            "Verify DOI or bibliography metadata manually.",
        )
    if status == ORPHAN_MENTION:
        return (
            "error",
            f"Citation mention {reference_or_mention} has no matching "
            "bibliography reference.",
            "Add matching bibliography entry or correct citation marker.",
        )
    if status == UNCITED_REFERENCE:
        return (
            "needs_review",
            f"Bibliography reference {reference_or_mention} is not cited "
            "in document text.",
            "Remove unused reference or add an in-text citation.",
        )
    if status == AMBIGUOUS:
        return (
            "needs_review",
            f"Citation mention {reference_or_mention} matches multiple references.",
            "Disambiguate author-year citation or use numeric citation.",
        )
    if status in {PARSER_UNCERTAIN, FRAGMENTED_REFERENCE, AMBIGUOUS_MAPPING}:
        return (
            "needs_review",
            f"Citation item {reference_or_mention} could not be mapped reliably.",
            "Review the anchored PDF text before judging citation correctness.",
        )
    return (
        "needs_review",
        f"Bibliography reference {reference_or_mention} appears duplicated.",
        "Remove duplicate bibliography entry.",
    )


async def evaluate_citations(
    db: AsyncSession, job: AnalysisJob, document_ir: DocumentIR
) -> int:
    """Evaluate enabled citation criteria and persist deterministic evidence
    findings."""
    criteria = list(
        (
            await db.execute(
                sa.select(CriterionVersion).where(
                    CriterionVersion.rubric_version_id == job.rubric_version_id,
                    CriterionVersion.is_enabled.is_(True),
                )
            )
        ).scalars()
    )
    criteria = [
        criterion for criterion in criteria if _criterion_is_citation(criterion)
    ]
    if not criteria:
        return 0
    await _clear_existing(db, job, criteria)
    report = parse_citations(document_ir)
    records = await _resolve_references(report.references)
    enriched: list[CitationReference] = []
    for reference, record in zip(report.references, records, strict=True):
        status, mismatch = _identity(reference, record)
        enriched.append(
            CitationReference(
                **{
                    **asdict(reference),
                    "identity_status": status,
                    "mismatch_fields": mismatch,
                    "provider_record": record,
                }
            )
        )
    report.references = enriched
    issue_rows, truncated_anchors = _bounded_issue_rows(_issue_rows(report))
    created = 0
    pending: list[tuple[Finding, CitationIssueRow]] = []
    for criterion in criteria:
        for issue in issue_rows:
            key = (issue[0], issue[1])
            severity, description, suggestion = _finding_copy(issue[1], issue[0])
            if key in truncated_anchors:
                suggestion += (
                    f" Only first {_MAX_EVIDENCE_ANCHORS_PER_FINDING} "
                    "evidence anchors were retained."
                )
            finding = Finding(
                analysis_job_id=job.id,
                criterion_version_id=criterion.id,
                severity=severity,
                description=description,
                suggestion=suggestion,
                proposed_score=None,
            )
            db.add(finding)
            pending.append((finding, issue))
            created += 1
    if pending:
        await db.flush()
        for finding, (_key, _status, anchors, _snippet) in pending:
            seen_anchors: set[tuple[str, int]] = set()
            for element_id, page_number, _line_start, _line_end in anchors:
                anchor_key = (element_id, page_number)
                if not element_id or page_number <= 0 or anchor_key in seen_anchors:
                    continue
                seen_anchors.add(anchor_key)
                db.add(
                    EvidenceAnchor(
                        finding_id=finding.id,
                        document_ir_id=document_ir.id,
                        element_id=element_id,
                        page_number=page_number,
                    )
                )
    snapshot = report.as_dict(include_items=False)
    snapshot["identity"] = [
        {
            "id": reference.id,
            "status": reference.identity_status,
            "mismatch_fields": list(reference.mismatch_fields),
            "doi": reference.doi,
            "arxiv_id": reference.arxiv_id,
            "provider": (
                {
                    key: reference.provider_record.get(key)
                    for key in (
                        "provider",
                        "query",
                        "retrieved_at",
                        "external_id",
                        "doi",
                    )
                    if reference.provider_record.get(key) is not None
                }
                if reference.provider_record
                else None
            ),
        }
        for reference in report.references[:64]
    ]
    snapshot["issues"] = [
        {
            "id": issue[0],
            "status": issue[1],
            "element_id": issue[2][0][0],
            "page_number": issue[2][0][1],
            "snippet": issue[3][:240],
            "anchors_truncated": (issue[0], issue[1]) in truncated_anchors,
            "anchors": [
                {
                    "element_id": element_id,
                    "page_number": page_number,
                    "line_start": line_start,
                    "line_end": line_end,
                }
                for element_id, page_number, line_start, line_end in issue[2]
            ],
        }
        for issue in issue_rows[:128]
    ]
    job_snapshot = dict(getattr(job, "snapshot", None) or {})
    job_snapshot["citation"] = snapshot
    job.snapshot = job_snapshot
    return created
