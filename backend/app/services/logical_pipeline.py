"""Shared logical pipeline: PDF structure, resources, detectors and verification."""

from __future__ import annotations

import asyncio
import importlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from functools import lru_cache, wraps
from itertools import combinations
from statistics import median
from threading import Lock

from app.services import logical_prompts as current_prompts
from app.services.analysis_logging import log_event, timed, timed_step
from app.services.embedding_cache import local_embedding_cache
from app.services.logical_llm import EvaluationUnavailable
from app.services.logical_schemas import (
    DataDecision,
    DataReview,
    GlobalIssue,
    GlobalStructureReview,
    GlobalSummary,
    GlobalTransitionDecision,
    GlobalTransitionReview,
    LocalDecision,
    LocalReview,
    LogicDecision,
    LogicReview,
    PolysemyReview,
    SynonymReview,
)

# --- Resources ---


class _LazyModule:
    def __init__(self, name):
        self.name = name

    def __getattr__(self, name):
        return getattr(importlib.import_module(self.name), name)


def _cached_resource(function):
    """Serialize cache misses so parallel detectors load each model only once."""
    cached = lru_cache(maxsize=1)(function)
    lock = Lock()

    @wraps(function)
    def load():
        # lru_cache alone allows duplicate construction on concurrent misses.
        with lock:
            return cached()

    return load


@_cached_resource
@timed("model.sbert.load")
def _encoder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("keepitreal/vietnamese-sbert")


class _Encoder:
    def encode(self, *args, **kwargs):
        return _encoder().encode(*args, **kwargs)


@_cached_resource
@timed("model.nli.load")
def _nli():
    from transformers import pipeline

    return pipeline(
        "text-classification", model="MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
    )


@_cached_resource
@timed("model.units.load")
def _units():
    from pint import UnitRegistry

    return UnitRegistry()


class _Units:
    def parse_units(self, value):
        return _units().parse_units(value)


def normalize_quantity(parsed_value):
    if parsed_value is None:
        return None
    number = parsed_value["number"]
    unit = parsed_value["unit"]
    if not unit:
        return None
    try:
        return number * ureg.parse_units(unit)
    except Exception:
        return None


model = _Encoder()
util = _LazyModule("sentence_transformers.util")
torch = _LazyModule("torch")
ureg = _Units()


# --- Chunks ---

CHAPTER = re.compile("^Chương\\s+(\\d+)\\s*(?:[.:-]\\s*)?(.*)$", re.I)
SUBSECTION = re.compile("^(\\d+(?:\\.\\d+){1,3})\\.?\\s+(.+)$")
LEADERS = re.compile("(?:\\s*\\.\\s*){3,}\\s*(?:\\d+|[ivxlcdm]+)?\\s*$", re.I)
REF = re.compile("^(?:Tài liệu tham khảo|References?|Phụ lục|Appendix)\\s*$", re.I)
CODE = re.compile("```.*?```", re.S)
COMMENT = re.compile("<!--.*?-->", re.S)
IMAGE = re.compile("!\\[[^\\]]*\\]\\([^\\n)]*\\)|<img\\b[^>]*>", re.I)
PAGE_NUM = re.compile("^(?:\\d{1,4}|[ivxlcdm]{1,8})$", re.I)
CAPTION = re.compile(
    "^(?:Hình|Figure|Fig\\.|Biểu đồ|Sơ đồ)\\s+\\d+(?:\\.\\d+)*\\s+.+$", re.I
)
TABLE_CAPTION = re.compile(
    "^(?:Bảng|Table)\\s+\\d+(?:\\.\\d+)*\\b\\s*[-–—.:]?\\s+\\S.+$", re.I
)


def _plain(text):
    s = re.sub("^\\s*#{1,6}\\s*", "", str(text).strip())
    s = re.sub("</?u>", "", s, flags=re.I)
    return re.sub("\\s+", " ", s.replace("**", "").replace("__", "")).strip()


def _heading(text):
    """Recognize numbered *sections*; never classify numbered list steps."""
    s = _plain(text)
    if not s or len(s) > 125 or LEADERS.search(s):
        return None
    m = CHAPTER.fullmatch(s)
    if m:
        number, title = m.groups()
        return (1, f"Chương {number}" + (f". {title}" if title else ""), number)
    m = SUBSECTION.fullmatch(s)
    if not m:
        return None
    number, title = m.groups()
    if (
        len(title) > 105
        or len(title.split()) > 17
        or title.endswith((".", ";", "!", "?"))
    ):
        return None
    return (min(1 + number.count("."), 4), f"{number}. {title}", number)


def _likely_table(table):
    """Skip one-row figure grids / false positives without losing use-case tables."""
    try:
        rows = table.extract()
    except Exception:
        return False
    nonempty = [r for r in rows if sum(bool(str(x or "").strip()) for x in r) >= 2]
    if table.col_count < 2 or len(nonempty) < 2:
        return False
    first = str((rows[0] or [""])[0] or "").strip()
    top = [str(x or "").strip().casefold() for x in rows[0]]
    if top and all(x.startswith(("hình ", "figure ")) for x in top if x):
        return False
    if table.col_count == 2:
        nums = [str(r[0] or "").strip() for r in rows if r]
        if (
            len(nums) >= 3
            and sum(x.isdigit() for x in nums) >= max(2, len(nums) // 2)
            and (first.casefold() not in {"stt", "id", "số thứ tự"})
        ):
            return False
    return True


def _table_text(rows):
    """Use Case: field: value; ordinary table: column: value (one row per line)."""
    rows = [
        [re.sub("\\s*\\n\\s*", " ", str(v or "")).strip() for v in row] for row in rows
    ]
    if not rows:
        return ""
    use_case = any("tiền điều kiện" in (r[0] or "").casefold() for r in rows if r)
    if use_case and len(rows[0]) == 2:
        return "\n".join(f"{r[0]}: {r[1]}" for r in rows if len(r) > 1 and r[0])
    headers = rows[0]
    body = rows[1:]
    out = []
    for i, row in enumerate(body, 1):
        cells = [
            f"{headers[j] or 'Cột ' + str(j + 1)}: {v}" for j, v in enumerate(row) if v
        ]
        if cells:
            out.append(f"Hàng {i}: " + "; ".join(cells))
    return "\n".join(out)


def _outside_table_lines(page, boxes):
    """Exact geometry: exclude text inside table bboxes, avoid duplicate Use Cases."""
    import fitz

    lines = []
    page_dict = page.get_text("dict", sort=True)
    for block in page_dict.get("blocks", []):
        if "lines" not in block:
            continue
        for line in block["lines"]:
            b = fitz.Rect(line["bbox"])
            if any(
                (b & rect).get_area() >= 0.5 * max(b.get_area(), 1) for rect in boxes
            ):
                continue
            text = "".join(span.get("text", "") for span in line["spans"]).strip()
            if text:
                lines.append((float(b.y0), "text", text))
    return lines


def _markdown_lines(md):
    """Split natural Markdown block boundaries while retaining positions."""
    md = CODE.sub("", COMMENT.sub("", IMAGE.sub("", md)))
    lines = []
    for raw in md.splitlines():
        text = raw.rstrip()
        if not text.strip():
            lines.append((0.0, "blank", ""))
        else:
            lines.append((0.0, "text", text))
    return lines


@timed("pdf.chunking")
def process_pdf_structured_fast(
    pdf_path,
    *,
    chunk_mode="section",
    extract_tables=True,
    extract_images=False,
    include_front_matter=False,
):
    """No max_tokens and no RecursiveCharacterTextSplitter.

    Returns: source, pages, sections, paragraphs, tables, section_map, images.
    extract_tables=False is faster, but Use Case table contents may then be
    mixed into prose: use extract_tables=True for quality checking.
    """
    import fitz
    import pymupdf4llm

    if chunk_mode not in ("section", "paragraph"):
        raise ValueError("chunk_mode must be 'section' or 'paragraph'")
    result = dict(
        source="document",
        pages=[],
        sections=[],
        paragraphs=[],
        tables=[],
        section_map=[],
        images=[],
    )
    with fitz.open(stream=pdf_path, filetype="pdf") as doc:
        pages_md = pymupdf4llm.to_markdown(
            doc,
            page_chunks=True,
            show_progress=False,
            write_images=False,
            embed_images=False,
            ignore_images=True,
            ignore_graphics=True,
            table_strategy=None,
        )
        pages_events = []
        for pno, page in enumerate(doc, 1):
            md = pages_md[pno - 1].get("text", "")
            result["pages"].append({"page": pno, "text": md})
            tables = []
            if extract_tables:
                for tab in page.find_tables():
                    if not _likely_table(tab):
                        continue
                    rows = tab.extract()
                    entry = dict(
                        page=pno,
                        bbox=tuple(tab.bbox),
                        data=rows,
                        text=_table_text(rows),
                        sections={},
                    )
                    result["tables"].append(entry)
                    tables.append((fitz.Rect(tab.bbox), entry))
            if tables:
                events = _outside_table_lines(page, [box for box, _ in tables])
                events += [(float(box.y0), "table", entry) for box, entry in tables]
                events.sort(key=lambda x: (x[0], x[1] == "text"))
            else:
                events = _markdown_lines(md)
            pages_events.append((pno, events))
            if extract_images:
                for im in page.get_image_info(xrefs=True):
                    if im.get("xref") and im.get("bbox"):
                        result["images"].append(
                            dict(
                                page=pno,
                                xref=im["xref"],
                                bbox=im["bbox"],
                                width=im["width"],
                                height=im["height"],
                            )
                        )
    has_start = any(
        (
            _heading(x) and _heading(x)[2] == "1"
            for _, events in pages_events
            for _, kind, x in events
            if kind == "text"
        )
    )
    active = include_front_matter or not has_start
    stop = False
    current, buffer, seen = ({}, [], set())

    def flush():
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        buffer.clear()
        if not text:
            return
        parts = [text] if chunk_mode == "section" else re.split("\\n\\s*\\n+", text)
        for part in parts:
            part = part.strip()
            if len(part.splitlines()) == 1 and TABLE_CAPTION.fullmatch(
                _plain(part)
            ):
                continue
            if len(part) >= 15:
                result["paragraphs"].append(
                    dict(
                        chunk_id=len(result["paragraphs"]) + 1,
                        sections=current.copy(),
                        content=part,
                    )
                )

    for pno, events in pages_events:
        skip_indices = set()
        for ix, (_, kind, val) in enumerate(events):
            if ix in skip_indices:
                continue
            if kind == "table":
                if active:
                    flush()
                    val["sections"] = current.copy()
                continue
            raw = str(val)
            s = _plain(raw)
            if not s:
                if chunk_mode == "paragraph" and buffer and (buffer[-1] != ""):
                    buffer.append("")
                continue
            if REF.fullmatch(s) and active:
                stop = True
                break
            if PAGE_NUM.fullmatch(s) or LEADERS.search(s) or CAPTION.fullmatch(s):
                continue
            h = _heading(raw)
            if h is not None:
                level, title, key = h
                if level == 1 and key == "1":
                    active = True
                if not active:
                    continue
                if level == 1 and title == f"Chương {key}":
                    j = ix + 1
                    while j < len(events) and events[j][1] == "blank":
                        j += 1
                    if j < len(events) and events[j][1] == "text":
                        nxt = events[j][2]
                        nt = _plain(nxt)
                        k = j + 1
                        while k < len(events) and events[k][1] == "blank":
                            k += 1
                        following_heading = (
                            k < len(events)
                            and events[k][1] == "text"
                            and (_heading(events[k][2]) is not None)
                        )
                        if (
                            2 < len(nt) <= 65
                            and len(nt.split()) <= 9
                            and (_heading(nxt) is None)
                            and (not nt.endswith((".", ":", ";")))
                            and (
                                str(nxt).lstrip().startswith("#")
                                or "**" in str(nxt)
                                or following_heading
                            )
                        ):
                            title += ". " + nt
                            skip_indices.add(j)
                flush()
                for k in list(current):
                    if int(k[1:]) >= level:
                        del current[k]
                current[f"H{level}"] = title
                if title not in seen:
                    result["sections"].append(title)
                    result["section_map"].append(
                        dict(key=key, heading=title, page=pno, structural_only=True)
                    )
                    seen.add(title)
                continue
            if not active:
                continue
            clean = re.sub("^\\s*#{1,6}\\s+", "", raw).strip()
            if clean:
                buffer.append(clean)
        if stop:
            break
    flush()
    return result


# --- Structure ---


def section_key(name):
    text = re.sub(r"[*`]", "", str(name))
    matches = re.findall(r"(?<![\w.])(\d+(?:\.\d+)+)\.?(?![\d.])", text)
    if matches:
        return matches[-1].rstrip(".")
    match = re.search(r"\bChương\s+(\d+)\b", text, re.I)
    return match.group(1) if match else None


def restore_sections(sections, section_map):
    """Keep mapped order and insert PDF-only headings, with no title-specific rules."""
    if not section_map:
        return sections
    result = [dict(section) for section in sections]
    items = [item for item in section_map if item.get("key") and item.get("heading")]
    order = {str(item["key"]): i for i, item in enumerate(items)}

    def key_of(section):
        key = section_key(section["name"])
        if key:
            return key
        # Match an unnumbered mapped H1 against an actual PDF chapter title.
        title = re.sub(r"^H\d+:\s*", "", section["name"], flags=re.I).strip().casefold()
        matches = [
            str(item["key"])
            for item in items
            if re.sub(r"^Chương\s+\d+\.\s*", "", item["heading"], flags=re.I)
            .strip()
            .casefold()
            == title
        ]
        return matches[0] if len(matches) == 1 else None

    existing = {key_of(section) for section in result}
    for item in items:
        key = str(item["key"])
        if key in existing:
            continue
        insert_at = next(
            (
                i
                for i, section in enumerate(result)
                if key_of(section) in order and order[key_of(section)] > order[key]
            ),
            len(result),
        )
        result.insert(
            insert_at,
            {
                "name": item["heading"],
                "structural_only": True,
                "chunks": [],
                "page": item.get("page"),
            },
        )
        existing.add(key)
    for index, section in enumerate(result, 1):
        section["id"] = f"S{index}"
    return result


# --- Candidates ---

TERMINOLOGY_SYNONYM_SEMANTIC_THRESHOLD = 0.80
TERMINOLOGY_SYNONYM_LEXICAL_THRESHOLD = 0.80
TERMINOLOGY_COMPAT_SEMANTIC_THRESHOLD = 0.92
TERMINOLOGY_COMPAT_LEXICAL_THRESHOLD = 0.92


def get_sbert_model():
    return _encoder()


def semantic_similarity(text1, text2):
    t1, t2 = normalize_text(text1), normalize_text(text2)
    if not t1 or not t2:
        return 0.0
    if t1 == t2:
        return 1.0
    vectors = model.encode([t1, t2], normalize_embeddings=True)
    return _cosine(vectors[0], vectors[1])


def _similarity(value):
    score = float(value)
    if not math.isfinite(score):
        raise ValueError("Nonfinite semantic similarity")
    return score


def normalize_text(text):
    """Chuẩn hóa hình thức văn bản, không dịch/replace thuật ngữ cụ thể."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.casefold().strip()
    text = re.sub("[‐‑‒–—−]", "-", text)
    text = re.sub("[“”„‟]", '"', text)
    text = re.sub("[‘’‚‛]", "'", text)
    text = re.sub("\\s+", " ", text)
    return text


def normalize_term(term):
    """Chuẩn hóa spelling để so sánh cùng một term, vẫn giữ +/# cho C++, C#..."""
    text = normalize_text(term)
    text = re.sub("[^\\w+#]+", "", text, flags=re.UNICODE)
    return text


def _definition_tokens(text):
    """Token lexical Unicode dùng cho containment/coverage."""
    return re.findall(
        "[^\\W_]+(?:[-'][^\\W_]+)*", normalize_text(text), flags=re.UNICODE
    )


def lexical_coverage(text1, text2):
    """
    Containment lexical đối xứng: phần giao / tập token nhỏ hơn.
    Giá trị 0..1. Không chứa danh sách synonym/domain hard-code.
    """
    s1 = set(_definition_tokens(text1))
    s2 = set(_definition_tokens(text2))
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / min(len(s1), len(s2))


def _cosine(v1, v2):
    if hasattr(v1, "tolist"):
        v1 = v1.tolist()
    if hasattr(v2, "tolist"):
        v2 = v2.tolist()
    v1 = [float(x) for x in v1]
    v2 = [float(x) for x in v2]
    if any(not math.isfinite(x) for x in (*v1, *v2)):
        raise ValueError("Nonfinite semantic embedding")
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum((a * b for a, b in zip(v1, v2, strict=True)))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (n1 * n2)))


def definitions_compatible(definition1, definition2):
    """
    Filter bảo thủ: chỉ bỏ qua cặp gần như chắc chắn tương thích.
    Cặp còn nghi ngờ vẫn được gửi LLM verify ở STEP 5.
    """
    d1 = normalize_text(definition1)
    d2 = normalize_text(definition2)
    if not d1 or not d2:
        return False
    if d1 == d2:
        return True
    coverage = lexical_coverage(d1, d2)
    if coverage >= TERMINOLOGY_COMPAT_LEXICAL_THRESHOLD:
        return True
    similarity = semantic_similarity(d1, d2)
    return similarity >= TERMINOLOGY_COMPAT_SEMANTIC_THRESHOLD


def is_invalid_definition(definition: str):
    text = normalize_text(definition)
    if not text:
        return True
    bad_patterns = {
        "chưa định nghĩa",
        "không rõ nghĩa",
        "không rõ",
        "undefined",
        "unknown",
        "n/a",
        "null",
        "none",
        "trống",
    }
    if any(pattern in text for pattern in bad_patterns):
        return True
    words = re.findall("\\w+", text)
    return len(words) <= 1


def parse_claim_value(claim):
    normalized = claim.get("normalized_value")
    value = normalized if normalized not in (None, "") else claim.get("value")
    unit = str(
        claim.get("normalized_unit", "")
        if normalized not in (None, "")
        else claim.get("unit", "")
    ).strip()
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip()
    if unit.casefold() == "date" or re.fullmatch(
        r"(?:\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})", raw
    ):
        try:
            if "/" in raw:
                day, month, year = map(int, raw.split("/"))
                parsed = date(year, month, day)
            else:
                parsed = date.fromisoformat(raw)
        except ValueError:
            return None
        return {"value": parsed.isoformat(), "unit": "date", "kind": "date"}
    if raw.endswith("%"):
        raw = raw[:-1].strip()
        unit = unit or "percent"
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    try:
        number = float(raw)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(number):
        return None
    return {"number": number, "unit": unit, "kind": "number"}


def compare_values(v1, v2, rel_tol=1e-09, abs_tol=1e-12):
    if v1 is None or v2 is None:
        return {"status": "unknown"}
    kind1, kind2 = v1.get("kind", "number"), v2.get("kind", "number")
    if kind1 != kind2:
        return {"status": "incomparable"}
    if kind1 == "date":
        return {
            "status": "same" if v1["value"] == v2["value"] else "conflict",
            "value_1_normalized": v1["value"],
            "value_2_normalized": v2["value"],
            "unit": "date",
        }
    unit1 = str(v1.get("unit", "")).strip()
    unit2 = str(v2.get("unit", "")).strip()
    if unit1 == unit2:
        n1 = v1["number"]
        n2 = v2["number"]
        if math.isclose(n1, n2, rel_tol=rel_tol, abs_tol=abs_tol):
            return {
                "status": "same",
                "value_1_normalized": n1,
                "value_2_normalized": n2,
                "unit": unit1,
            }
        return {
            "status": "conflict",
            "value_1_normalized": n1,
            "value_2_normalized": n2,
            "unit": unit1,
        }
    if bool(unit1) != bool(unit2):
        return {"status": "incomparable"}
    q1 = normalize_quantity(v1)
    q2 = normalize_quantity(v2)
    if q1 is None or q2 is None:
        return {"status": "unknown"}
    try:
        q2_converted = q2.to(q1.units)
    except Exception:
        return {"status": "incomparable"}
    if math.isclose(
        q1.magnitude, q2_converted.magnitude, rel_tol=rel_tol, abs_tol=abs_tol
    ):
        return {
            "status": "same",
            "value_1_normalized": q1.magnitude,
            "value_2_normalized": q2_converted.magnitude,
            "unit": str(q1.units),
        }
    return {
        "status": "conflict",
        "value_1_normalized": q1.magnitude,
        "value_2_normalized": q2_converted.magnitude,
        "unit": str(q1.units),
    }


def build_embeddings(claims, field):
    texts = list(dict.fromkeys(c[field] for c in claims if c.get(field)))
    if not texts:
        return {}
    embeddings = model.encode(
        texts,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return dict(zip(texts, embeddings, strict=True))


def field_similarity(value1, value2, embedding_map):
    if not value1 or not value2:
        return None
    if value1 == value2:
        return 1.0
    if value1 not in embedding_map or value2 not in embedding_map:
        return None
    return _similarity(
        torch.dot(embedding_map[value1], embedding_map[value2]).item()
    )


def ann_synonym_candidates(
    records, encoder, k=30, threshold=TERMINOLOGY_SYNONYM_SEMANTIC_THRESHOLD
):
    import numpy as np

    definitions = list(dict.fromkeys(r["def"] for r in records))
    if len(definitions) < 1:
        return []
    vectors = np.asarray(
        encoder.encode(
            definitions, batch_size=64, normalize_embeddings=True, convert_to_numpy=True
        ),
        dtype=np.float32,
    )
    if not np.isfinite(vectors).all():
        raise ValueError("Nonfinite terminology embedding")
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    def_ids = {d: i for i, d in enumerate(definitions)}
    groups = [[] for _ in definitions]
    seen_records = set()
    for i, r in enumerate(records):
        key = (normalize_term(r["term"]), r["def"])
        if key not in seen_records:
            groups[def_ids[r["def"]]].append(i)
            seen_records.add(key)
    pairs = set()
    for group in groups:
        for a, i in enumerate(group):
            for j in group[a + 1 :]:
                pairs.add((min(i, j), max(i, j)))
    n = len(definitions)
    if n > 1:
        query_k = min(n, k + 1)
        neighbors = _definition_neighbors(vectors, query_k)
        def_pairs = set()
        for i, row in enumerate(neighbors):
            for j in row:
                j = int(j)
                if i != j:
                    def_pairs.add((min(i, j), max(i, j)))
        token_index = {}
        for i, d in enumerate(definitions):
            for token in set(_definition_tokens(d)):
                token_index.setdefault(token, []).append(i)
        for ids in token_index.values():
            for a, i in enumerate(ids):
                for j in ids[a + 1 :]:
                    def_pairs.add((i, j))
        for i, j in def_pairs:
            sim = float(vectors[i] @ vectors[j])
            coverage = lexical_coverage(definitions[i], definitions[j])
            if sim < threshold and coverage < TERMINOLOGY_SYNONYM_LEXICAL_THRESHOLD:
                continue
            for a in groups[i]:
                for b in groups[j]:
                    pairs.add((min(a, b), max(a, b)))
    candidates = []
    for a, b in sorted(pairs):
        x, y = records[a], records[b]
        if normalize_term(x["term"]) == normalize_term(y["term"]):
            continue
        sim = float(vectors[def_ids[x["def"]]] @ vectors[def_ids[y["def"]]])
        coverage = lexical_coverage(x["def"], y["def"])
        candidates.append(
            {
                "record_index_1": a,
                "record_index_2": b,
                "term_1": x["term"],
                "definition_1": x["def"],
                "location_1": x["loc"],
                "term_2": y["term"],
                "definition_2": y["def"],
                "location_2": y["loc"],
                "semantic_similarity": round(sim, 4),
                "lexical_coverage": round(coverage, 4),
            }
        )
    return candidates


def _definition_neighbors(vectors, query_k):
    """HNSW retrieval, with exact neighbors when HNSW is not installed (Windows)."""
    try:
        import hnswlib
    except ImportError:
        from sklearn.neighbors import NearestNeighbors

        search = NearestNeighbors(n_neighbors=query_k, metric="cosine")
        search.fit(vectors)
        return search.kneighbors(vectors, return_distance=False)
    index = hnswlib.Index(space="cosine", dim=vectors.shape[1])
    index.init_index(
        max_elements=len(vectors), ef_construction=200, M=16, random_seed=42
    )
    index.add_items(vectors)
    index.set_ef(max(100, query_k))
    neighbors, _ = index.knn_query(vectors, k=query_k)
    return neighbors


def group_numeric_claims(claims, group_size=12, random_state=42):
    """Notebook MiniBatchKMeans on entity + attribute, before pair comparison."""
    if len(claims) <= max(2, group_size):
        return [list(range(len(claims)))]
    import numpy as np
    from sklearn.cluster import MiniBatchKMeans

    vectors = np.asarray(
        model.encode(
            [
                f"Đối tượng: {c['entity_norm']}; đại lượng: {c['attribute_norm']}"
                for c in claims
            ],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ),
        dtype=np.float32,
    )
    if not np.isfinite(vectors).all():
        raise ValueError("Nonfinite numeric grouping embedding")
    n_groups = max(1, min(len(claims), math.ceil(len(claims) / max(2, group_size))))
    labels = MiniBatchKMeans(
        n_clusters=n_groups,
        random_state=random_state,
        batch_size=max(256, n_groups * 3),
        n_init=3,
    ).fit_predict(vectors)
    groups = {}
    for index, label in enumerate(labels):
        groups.setdefault(int(label), []).append(index)
    return list(groups.values())


def find_data_conflict_candidates(
    all_data_claims,
    entity_threshold=0.65,
    attribute_threshold=0.6,
    scope_threshold=0.6,
    *,
    group_size=12,
    random_state=42,
):
    claims = []

    for item in all_data_claims:
        c = item.get("**dc", item)
        entity = normalize_text(c.get("entity", ""))
        attribute = normalize_text(c.get("attribute", ""))
        parsed = parse_claim_value(c)

        if not entity or not attribute or parsed is None:
            continue

        claims.append(
            {
                **c,
                "entity_norm": entity,
                "attribute_norm": attribute,
                "condition_norm": normalize_text(c.get("condition", "")),
                "time_norm": normalize_text(c.get("time", "")),
                "population_norm": normalize_text(c.get("population", "")),
                "scope_norm": normalize_text(c.get("scope", "")),
                "parsed_value": parsed,
                "chunk_idx": item.get("chunk_idx", -1),
                "sections": item.get("sections", ""),
            }
        )

    if len(claims) < 2:
        return []

    entity_emb = build_embeddings(claims, "entity_norm")
    attr_emb = build_embeddings(claims, "attribute_norm")
    context_emb = {
        f: build_embeddings(claims, f"{f}_norm")
        for f in ("condition", "time", "population", "scope")
    }

    candidates = []

    groups = group_numeric_claims(claims, group_size, random_state)
    for group in groups:
        for pos, i in enumerate(group):
            for j in group[pos + 1 :]:
                a, b = claims[i], claims[j]

                es = field_similarity(a["entity_norm"], b["entity_norm"], entity_emb)
                ats = field_similarity(
                    a["attribute_norm"], b["attribute_norm"], attr_emb
                )
                ss = field_similarity(
                    a["scope_norm"], b["scope_norm"], context_emb["scope"]
                )

                entity_match = es is not None and es >= entity_threshold
                attr_match = ats is not None and ats >= attribute_threshold
                scope_match = ss is not None and ss >= scope_threshold
                same_section = bool(a["sections"]) and a["sections"] == b["sections"]

                u1 = str(a["parsed_value"].get("unit", "")).lower()
                u2 = str(b["parsed_value"].get("unit", "")).lower()
                same_unit = bool(u1) and u1 == u2

                related = (
                    (entity_match and (attr_match or same_section))
                    or (attr_match and (same_section or scope_match))
                    or (
                        same_unit
                        and same_section
                        and (entity_match or attr_match or scope_match)
                    )
                )

                if not related:
                    continue

                value_result = compare_values(a["parsed_value"], b["parsed_value"])
                if value_result["status"] != "conflict":
                    continue

                context_scores = {}
                missing_context_fields = []

                for field in ("condition", "time", "population", "scope"):
                    v1, v2 = a[f"{field}_norm"], b[f"{field}_norm"]
                    if v1 and v2:
                        context_scores[field] = field_similarity(
                            v1, v2, context_emb[field]
                        )
                    elif bool(v1) != bool(v2):
                        missing_context_fields.append(field)

                candidates.append(
                    {
                        "entity_1": a.get("entity", ""),
                        "entity_2": b.get("entity", ""),
                        "attribute_1": a.get("attribute", ""),
                        "attribute_2": b.get("attribute", ""),
                        "value_1": a.get("value"),
                        "unit_1": a.get("unit", ""),
                        "value_2": b.get("value"),
                        "unit_2": b.get("unit", ""),
                        "condition_1": a.get("condition", ""),
                        "condition_2": b.get("condition", ""),
                        "time_1": a.get("time", ""),
                        "time_2": b.get("time", ""),
                        "population_1": a.get("population", ""),
                        "population_2": b.get("population", ""),
                        "scope_1": a.get("scope", ""),
                        "scope_2": b.get("scope", ""),
                        "normalized_value_1": value_result["value_1_normalized"],
                        "normalized_value_2": value_result["value_2_normalized"],
                        "normalized_unit": value_result["unit"],
                        "entity_similarity": round(es, 4) if es is not None else None,
                        "attribute_similarity": (
                            round(ats, 4) if ats is not None else None
                        ),
                        "context_scores": {
                            k: round(v, 4) if v is not None else None
                            for k, v in context_scores.items()
                        },
                        "missing_context_fields": missing_context_fields,
                        "chunk_1": a["chunk_idx"],
                        "chunk_2": b["chunk_idx"],
                        "sections_1": a["sections"],
                        "sections_2": b["sections"],
                    }
                )

    return candidates


# --- Graph ---

nx = _LazyModule("networkx")
fuzz = _LazyModule("rapidfuzz.fuzz")
FIELDS = (
    "type",
    "subject",
    "actor",
    "action",
    "condition",
    "result",
    "from_state",
    "to_state",
    "polarity",
    "relation",
)
NEG = (
    {"allow", "deny"},
    {"allow", "prohibit"},
    {"require", "deny"},
    {"require", "prohibit"},
)


def norm(x):
    s = unicodedata.normalize("NFKC", str(x or "")).casefold()
    return re.sub(r"\s+", " ", s).strip(" .,;:!?")


def prepare(logic):
    if isinstance(logic, dict):
        logic = logic.get("logic_statements", [])
    out, seen = [], {}
    for i, s in enumerate(logic):
        if not isinstance(s, dict):
            continue
        r = {f: norm(s.get(f)) for f in FIELDS}
        r.update(
            id=str(s.get("id") or f"L{i}"),
            evidence=str(s.get("evidence") or s.get("source_quote") or ""),
            section=str(s.get("section") or ""),
            chunk_idx=s.get("chunk_idx", i),
        )
        r["sources"] = [{k: r[k] for k in ("id", "evidence", "section", "chunk_idx")}]
        key = tuple(r[f] for f in FIELDS)
        if key in seen:
            out[seen[key]]["sources"] += r["sources"]
        else:
            seen[key] = len(out)
            out.append(r)
    return out


def resolve_entities(rules, use_nli=False, fuzzy_cutoff=96):
    # NLI intentionally omitted from graph construction for speed.
    maps = {}
    for field in ("subject", "actor", "action"):
        names = sorted({r[field] for r in rules if r[field]})
        parent = {x: x for x in names}

        def root(x, parent=parent):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                # Only merge near-identical strings; no unverified semantic merge.
                if min(len(a), len(b)) >= 8 and fuzz.ratio(a, b) >= fuzzy_cutoff:
                    ra, rb = root(a), root(b)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
        maps[field] = {x: root(x) for x in names}
    for r in rules:
        for f in maps:
            r[f + "_id"] = maps[f].get(r[f], "")
    return rules, maps


def _contains(text, token):
    return bool(
        token
        and re.search(
            r"(?<!\w)" + re.escape(token) + r"(?!\w)", norm(text)
        )
    )


def _text(r):
    return " ".join(
        r.get(k, "")
        for k in (
            "subject",
            "actor",
            "action",
            "condition",
            "result",
            "from_state",
            "to_state",
            "evidence",
        )
    ).casefold()


def _operation(r):
    # Semantic blocking features, not a final truth label.
    text = _text(r)
    ops = set()
    patterns = {
        "APPROVAL": r"phê duyệt|chấp thuận|quyết định duyệt|quyết định.*từ chối|approve",
        "SCHEDULING": r"xếp lịch|lập lịch|đặt lịch|scheduled|clear_for_schedule|bộ lập lịch",
        "CLOSING": r"\bclosed\b|đóng yêu cầu|đóng hồ sơ|khôi phục.*hoàn tất",
        "EXECUTION": r"\bexecuting\b|triển khai|worker",
        "AUDIT": r"kiểm toán|nhật ký|lịch sử thao tác",
    }
    for name, pat in patterns.items():
        if re.search(pat, text):
            ops.add(name)
    if r.get("to_state"):
        ops.add("STATE:" + r["to_state"])
    if r.get("from_state"):
        ops.add("STATE:" + r["from_state"])
    return ops


def relation_candidates(rules):
    idx = defaultdict(set)
    for i, r in enumerate(rules):
        for field in ("subject_id", "action_id", "from_state", "to_state"):
            if r.get(field):
                idx[(field, r[field])].add(i)
        for op in _operation(r):
            idx[("operation", op)].add(i)
    pairs = set()
    for ids in idx.values():
        pairs.update(combinations(sorted(ids), 2))
    return sorted(pairs)


def same_operation(a, b):
    return bool(
        a.get("action_id")
        and a["action_id"] == b.get("action_id")
        and a.get("subject_id") == b.get("subject_id")
    )


def inspect_pair(a, b):
    if (
        same_operation(a, b)
        and {a["polarity"], b["polarity"]} in NEG
        and (
            a.get("actor_id") == b.get("actor_id")
            or not a.get("actor_id")
            or not b.get("actor_id")
        )
    ):
        return "POLARITY_CONFLICT"
    if (
        a["type"] == b["type"] == "state_transition"
        and a["subject_id"] == b["subject_id"]
        and a["from_state"]
        and a["from_state"] == b["from_state"]
        and a["to_state"]
        and a["to_state"] == b["to_state"]
        and (a["polarity"] == "prohibit") != (b["polarity"] == "prohibit")
    ):
        return "STATE_CONFLICT"
    return None


def generate_graph_candidates(rules):
    """Indexed constraint checking. Candidates are NOT conclusions."""
    candidates = {}
    known_states = {s for r in rules for s in (r["from_state"], r["to_state"]) if s}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for i, r in enumerate(rules):
        if r["type"] == "state_transition" and r["polarity"] not in (
            "deny",
            "prohibit",
        ):
            if r["from_state"]:
                outgoing[r["from_state"]].append(i)
            if r["to_state"]:
                incoming[r["to_state"]].append(i)

    def add(ids, typ, reason, path=None):
        ids = tuple(sorted(set(ids)))
        if len(ids) < 2:
            return
        key = (ids, typ)
        if key in candidates:
            return
        candidates[key] = {
            "pair_id": len(candidates),
            "type": typ,
            "rule_ids": [rules[i]["id"] for i in ids],
            "statements": [rules[i] for i in ids],
            "statement_a": rules[ids[0]],
            "statement_b": rules[ids[1]],
            "status": "UNCERTAIN",
            "severity": "",
            "reason": reason,
            "reasoning_path": path or [rules[i]["id"] for i in ids],
        }

    for i, j in relation_candidates(rules):
        kind = inspect_pair(rules[i], rules[j])
        if kind:
            add([i, j], kind, "Opposing constraints on the same operation/transition")
    for pi, pre in enumerate(rules):
        if pre["type"] not in (
            "precondition",
            "authorization",
            "business_rule",
            "state_transition",
        ):
            continue
        snippet = _text(pre)
        if not re.search(
            r"only_if|chỉ khi|chỉ sau khi|chỉ tiếp nhận|chỉ cấp|chỉ được|chỉ chuyển|duy nhất khi",
            snippet,
        ):
            continue
        required = {s for s in known_states if _contains(pre["condition"], s)}
        if not required:
            continue
        pre_ops = {op for op in _operation(pre) if not op.startswith("STATE:")}
        for req in sorted(required):
            for bi in outgoing.get(req, []):
                base = rules[bi]
                dst = base["to_state"]
                if not dst or bi == pi:
                    continue
                base_ops = {
                    op
                    for op in _operation(base)
                    if not op.startswith("STATE:")
                }
                if not (pre_ops & base_ops) and not _contains(snippet, dst):
                    continue
                for ai in incoming.get(dst, []):
                    alt = rules[ai]
                    if (
                        ai in (pi, bi)
                        or not alt["from_state"]
                        or alt["from_state"] == req
                    ):
                        continue
                    alt_ops = {
                        op
                        for op in _operation(alt)
                        if not op.startswith("STATE:")
                    }
                    if not ((base_ops & alt_ops) or (pre_ops & alt_ops)):
                        continue
                    typ = (
                        "AUTHORIZATION_STATE_BYPASS"
                        if pre["type"] == "authorization"
                        else "PRECONDITION_BYPASS"
                    )
                    add(
                        [pi, bi, ai],
                        typ,
                        f"Possible bypass: required {req} before {dst}, alternate {alt['from_state']}->{dst}",
                        [
                            pre["id"],
                            f"REQUIRES:{req}",
                            base["id"],
                            f"TARGET:{dst}",
                            alt["id"],
                        ],
                    )
    for pi, pre in enumerate(rules):
        if pre["type"] not in ("precondition", "business_rule", "state_transition"):
            continue
        snippet = _text(pre)
        if not re.search(
            r"only_if|chỉ khi|chỉ sau khi|chỉ tiếp nhận|chỉ được|chỉ chuyển", snippet
        ):
            continue
        required = {s for s in known_states if _contains(pre["condition"], s)}
        for req in sorted(required):
            for ai, alt in enumerate(rules):
                if alt["type"] != "state_transition" or alt["polarity"] in (
                    "deny",
                    "prohibit",
                ):
                    continue
                if not alt["to_state"] or alt["from_state"] in ("", req):
                    continue
                candidates_dst = {
                    r["to_state"]
                    for r in rules
                    if r["type"] == "state_transition"
                    and r["from_state"] == req
                    and r["to_state"]
                    and (
                        (_operation(pre) & _operation(r))
                        or _contains(snippet, r["to_state"])
                    )
                }
                if alt["to_state"] not in candidates_dst:
                    continue
                add(
                    [pi, ai],
                    "PRECONDITION_BYPASS",
                    f"Required source {req} vs {alt['from_state']}->{alt['to_state']}",
                    [pre["id"], f"REQUIRES:{req}", alt["id"]],
                )
    approvals = [
        (i, r)
        for i, r in enumerate(rules)
        if r["type"] == "authorization" and "APPROVAL" in _operation(r)
    ]
    self_ref = re.compile(
        r"requester_id|requester|người đề xuất|chính mình|do mình tạo|tự phê duyệt|trùng với.*người"
    )
    for (i, a), (j, b) in combinations(approvals, 2):
        if a["polarity"] == b["polarity"]:
            continue
        denied, allowed = (a, b) if a["polarity"] in ("deny", "prohibit") else (b, a)
        if (
            denied["polarity"] not in ("deny", "prohibit")
            or allowed["polarity"] != "allow"
        ):
            continue
        if not (
            self_ref.search(_text(denied))
            and self_ref.search(_text(allowed))
        ):
            continue
        if (
            a.get("subject_id")
            and b.get("subject_id")
            and a["subject_id"] != b["subject_id"]
        ):
            if not (
                re.search(r"yêu cầu|hồ sơ|quyết định", a["subject"])
                and re.search(r"yêu cầu|hồ sơ|quyết định", b["subject"])
            ):
                continue
        add(
            [i, j],
            "AUTHORIZATION_OVERRIDE",
            "A general self-approval prohibition may conflict with a narrower permission",
            [a["id"], "SAME_PERSON:actor=requester", b["id"]],
        )
    for pi, pre in enumerate(rules):
        if pre["type"] not in ("precondition", "state_transition"):
            continue
        snippet = _text(pre)
        if not re.search(r"only_if|chỉ khi|chỉ sau khi|chỉ chuyển", snippet):
            continue
        dst = pre["to_state"]
        if not dst and re.search(r"đóng\s+(yêu cầu|hồ sơ)", pre["action"]):
            dst = "closed"
        if not dst:
            continue
        for ai in incoming.get(dst, []):
            if ai == pi:
                continue
            add(
                [pi, ai],
                "TARGET_PRECONDITION_CHECK",
                f"Necessary condition for entering {dst}",
                [
                    pre["id"],
                    f"REQUIRES:{pre['condition']}",
                    f"TARGET:{dst}",
                    rules[ai]["id"],
                ],
            )
    for pi, r in enumerate(rules):
        if r["type"] not in ("exception_flow", "business_rule", "precondition"):
            continue
        snippet = _text(r)
        if not re.search(r"giữ nguyên|tiếp tục giữ|duy trì", snippet):
            continue
        kept = [s for s in known_states if _contains(snippet, s)]
        for state in sorted(kept):
            for ai in outgoing.get(state, []):
                alt = rules[ai]
                if (
                    r["subject_id"]
                    and alt["subject_id"]
                    and r["subject_id"] != alt["subject_id"]
                ):
                    continue
                add(
                    [pi, ai],
                    "STATE_PERSISTENCE_CHECK",
                    f"Preserve {state} versus transition to {alt['to_state']}",
                )
    order_graph = nx.DiGraph()
    edge_rule = defaultdict(list)
    for i, r in enumerate(rules):
        if r["type"] != "order" or r["relation"] not in ("before", "after"):
            continue
        a, b = r["subject"], r["result"]
        if not a or not b:
            continue
        if r["relation"] == "after":
            a, b = b, a
        order_graph.add_edge(a, b)
        edge_rule[(a, b)].append(i)
    for comp in nx.strongly_connected_components(order_graph):
        if len(comp) < 2:
            continue
        ids = [
            i for a, b in order_graph.subgraph(comp).edges() for i in edge_rule[(a, b)]
        ]
        add(ids, "ORDER_CYCLE", "Ordering requirements may form a cycle")
    return list(candidates.values())


def _rule_blob(r):
    return norm(
        " ".join(
            str(r.get(k, ""))
            for k in ("subject", "actor", "action", "condition", "result", "evidence")
        )
    )


def _is_self_identity(text):
    # Recognizes structural identity of approver and owner/creator/requester,
    # including variable names and natural-language self-approval.
    ids = re.findall(r"\b[\w]+_id\b", text)
    identity = bool(re.search(r"\b(?:trùng|bằng|giống|same|equals|==|=)\b", text))
    identity = identity and len(set(ids)) >= 2
    self_action = bool(
        re.search(
            r"tự\s*(?:phê duyệt|duyệt|chấp thuận)|"
            r"(?:do\s+(?:chính\s+)?mình\s+tạo|chính\s+(?:mình|người đó)|"
            r"đồng thời\s+là\s+người\s+tạo|own\s+(?:request|order))",
            text,
        )
    )
    return identity or self_action


def _approval_related(text):
    return bool(
        re.search(r"phê duyệt|duyệt|chấp thuận|approve|approval|authorization", text)
    )


def _reservation_related(text):
    return bool(
        re.search(r"đặt giữ|giữ hàng|dự trữ|reserve|reservation|reserved", text)
    )


def _necessary_capacity(text):
    return bool(
        re.search(
            r"chỉ\s+(?:được|khi)|không\s+(?:được|lớn hơn|vượt)|"
            r"không\s+vượt|must not|only if|at most|<=|≤",
            text,
        )
    )


def _numbers_in_rule(text):
    # Detect numerical comparison with quantities expressed in natural language.
    # A candidate needs at least two comparable quantities; LLM confirms semantics.
    return [
        float(v.replace(",", "."))
        for v in re.findall(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w.])", text)
    ]


def generate_constraint_candidates(rules, max_candidates=40):
    """High-recall hypotheses. Domain-specific truth remains LLM Verify's task.
    Deterministic rules: identity/permission conflicts and numerical guard
    violations. No additional LLM call; no hardcoded document rule IDs.
    """
    result = []
    seen = set()

    def add(i, j, typ, reason):
        ids = tuple(sorted((rules[i]["id"], rules[j]["id"])))
        if ids in seen or (
            max_candidates is not None and len(result) >= max_candidates
        ):
            return
        seen.add(ids)
        pair = [rules[i], rules[j]]
        result.append(
            {
                "pair_id": -1,
                "type": typ,
                "rule_ids": list(ids),
                "statements": pair,
                "statement_a": pair[0],
                "statement_b": pair[1],
                "status": "UNCERTAIN",
                "severity": "",
                "reason": reason,
                "reasoning_path": [ids[0], typ, ids[1]],
            }
        )

    blobs = [_rule_blob(r) for r in rules]
    # Identity conflict: permission denial vs permission granting on the same
    # individual's own transaction. Scope is validated later, never assumed.
    denied = [
        i
        for i, r in enumerate(rules)
        if r["type"] == "authorization"
        and r["polarity"] in ("deny", "prohibit")
        and _approval_related(blobs[i])
        and _is_self_identity(blobs[i])
    ]
    allowed = [
        i
        for i, r in enumerate(rules)
        if r["type"] == "authorization"
        and r["polarity"] == "allow"
        and _approval_related(blobs[i])
        and _is_self_identity(blobs[i])
    ]
    for i in denied:
        for j in allowed:
            add(
                i,
                j,
                "AUTHORIZATION_OVERRIDE",
                "Possible self-approval permission override; check actor identity and scope",
            )
    # Numeric-guard rule vs explicit exception with an over-limit quantity.
    # Restrict candidate pool by operation family and textual quantification;
    # do not mark contradiction until LLM verifies shared variable/time/scope.
    constraints = [
        i
        for i, r in enumerate(rules)
        if r["type"] in ("precondition", "business_rule")
        and _reservation_related(blobs[i])
        and _necessary_capacity(blobs[i])
    ]
    examples = []
    for j, r in enumerate(rules):
        if r["type"] not in ("business_rule", "authorization", "postcondition"):
            continue
        text = blobs[j]
        if not _reservation_related(text):
            continue
        nums = _numbers_in_rule(text)
        if len(nums) < 2:
            continue
        if not re.search(
            r"dù|mặc dù|despite|even though|vượt|lớn hơn|quá|more than|exceed", text
        ):
            continue
        examples.append(j)
    for i in constraints:
        for j in examples:
            if i == j:
                continue
            add(
                i,
                j,
                "NUMERIC_INVARIANT_CHECK",
                "Possible quantitative guard violation; compare requested amount against available capacity at the same scope/time",
            )
    return result


def merge_candidates(graph_candidates, constraint_candidates):
    """Giữ tất cả candidate cũ; không tính trùng cùng rule pair."""
    out = list(graph_candidates)
    existing = {frozenset(c["rule_ids"]) for c in out}
    for c in constraint_candidates:
        key = frozenset(c["rule_ids"])
        if key in existing:
            continue
        existing.add(key)
        c["pair_id"] = len(out)
        out.append(c)
    return out


def retrieve_graph(candidates, rules, top_k=3):
    """Retrieve context rules via typed rule--chunk--rule paths.
    Supporting rules provide evidence, never become conflict rule_ids.
    Only candidate categories likely to need cross-rule scope are enriched.
    """
    context_types = {
        "PRECONDITION_BYPASS",
        "AUTHORIZATION_STATE_BYPASS",
        "CONSTRAINT_CONFLICT",
    }
    graph = nx.Graph()
    by_id = {r["id"]: r for r in rules}
    context_marker = re.compile(
        r"dùng chung|sử dụng cùng|cùng dịch vụ|cùng kiểm soát|"
        r"kế thừa|áp dụng chung|shared|same service|inherit",
        re.I,
    )
    for r in rules:
        rid = r["id"]
        graph.add_node(rid, kind="RULE")
        for source in r.get("sources", [r]):
            chunk = source.get("chunk_idx")
            if chunk is None:
                continue
            # All merged occurrences remain eligible as context sources.
            chunk_node = ("CHUNK", str(chunk))
            graph.add_node(chunk_node, kind="CHUNK")
            graph.add_edge(rid, chunk_node, relation="IN_CHUNK")
    for c in candidates:
        c["supporting_rules"] = []
        c["supporting_paths"] = []
        if c["type"] not in context_types:
            continue
        selected = set(c["rule_ids"])
        scores, paths = defaultdict(float), {}
        for rid in sorted(selected):
            if rid not in graph:
                continue
            for chunk_node in graph.neighbors(rid):
                if graph.nodes[chunk_node].get("kind") != "CHUNK":
                    continue
                for other in graph.neighbors(chunk_node):
                    if other in selected:
                        continue
                    rule = by_id[other]
                    context = " ".join(
                        str(rule.get(k, ""))
                        for k in (
                            "subject",
                            "action",
                            "condition",
                            "result",
                            "evidence",
                        )
                    )
                    # Rank relations above generic statements in the same chunk.
                    score = 1.0 + (4.0 if context_marker.search(context) else 0.0)
                    scores[other] += score
                    paths.setdefault(other, [rid, chunk_node, other])
        ranked = sorted(scores, key=lambda rid: (-scores[rid], rid))[:top_k]
        c["supporting_rules"] = [by_id[rid] for rid in ranked]
        c["supporting_paths"] = [
            {"rule_id": rid, "score": scores[rid], "path": paths[rid]} for rid in ranked
        ]
    return candidates


# --- Findings ---


def score_bounds(issues):
    """Notebook severity bands, applied only without teacher-defined levels."""
    counts = Counter(issue["severity"] for issue in issues)
    if counts["critical"] >= 2:
        return 0, 2.9
    if counts["critical"] or counts["major"] >= 2:
        return 3, 5.4
    if counts["major"]:
        return 5.5, 7.4
    if counts["moderate"]:
        return 7.5, 8.9
    return 9, 9.9


def state_graph_candidates(rules):
    graphs = defaultdict(nx.DiGraph)
    starts = defaultdict(set)
    for r in rules:
        if r["type"] != "state_transition":
            continue
        sub = r.get("subject_id") or r["subject"]
        a, b = r["from_state"], r["to_state"]
        if a:
            graphs[sub].add_node(a)
        if b:
            graphs[sub].add_node(b)
        if a and b and r["polarity"] not in ("deny", "prohibit"):
            graphs[sub].add_edge(a, b)
        if a in ("draft", "initial", "created", "new"):
            starts[sub].add(a)
    warnings = []
    for sub, g in graphs.items():
        if not starts[sub]:
            continue
        visited = set(starts[sub])
        for state in starts[sub]:
            visited.update(nx.descendants(g, state))
        for s in sorted(set(g) - visited):
            warnings.append(
                {
                    "type": "POSSIBLE_UNREACHABLE_STATE",
                    "subject": sub,
                    "state": s,
                    "status": "UNCERTAIN",
                    "note": "May be missing from MAP; not a verified inconsistency.",
                }
            )
    return warnings


def cluster_issues(candidates):
    """Cluster by a shared offending transition + same logical consequence.
    This avoids counting one early transition multiple times; it does not merge
    unrelated issues simply because they share any rule ID.
    """
    verified = [c for c in candidates if c.get("status") == "CONFIRMED"]
    rank = {"minor": 1, "moderate": 2, "major": 3, "critical": 4}
    groups = []

    def effect(c):
        # A repeated offending edge is strong evidence for a shared cause.
        edges = {}
        for r in c["statements"]:
            if (
                r["id"] in c["rule_ids"]
                and r["type"] == "state_transition"
                and r["from_state"]
                and r["to_state"]
            ):
                edges[r["id"]] = (r["from_state"], r["to_state"])
        return edges

    def compatible(c, group):
        if c["type"] != group["type"]:
            return False
        cedges = effect(c)
        for old in group["_members"]:
            oedges = effect(old)
            # Same identified offending state transition, and both findings
            # explicitly discuss its target/state constraint.
            shared = set(cedges) & set(oedges)
            if any(cedges[x] == oedges[x] for x in shared):
                return True
            if tuple(sorted(c["rule_ids"])) == tuple(sorted(old["rule_ids"])):
                return True
        return False

    for c in verified:
        hits = [g for g in groups if compatible(c, g)]
        if len(hits) == 1:
            group = hits[0]
        else:
            group = {
                "type": c["type"],
                "severity": c["severity"],
                "reason": c["reason"],
                "context": c.get("context", ""),
                "root_cause": c.get("root_cause", ""),
                "rule_ids": [],
                "evidence": [],
                "related_findings": [],
                "_members": [],
            }
            groups.append(group)
        group["_members"].append(c)
        if rank.get(c["severity"], 0) > rank.get(group["severity"], 0):
            group["severity"] = c["severity"]
        group["rule_ids"] = list(dict.fromkeys(group["rule_ids"] + c["rule_ids"]))
        group["related_findings"].append(
            {"rule_ids": c["rule_ids"], "reason": c["reason"]}
        )
        seen = {e["id"] for e in group["evidence"]}
        for r in c["statements"]:
            if r["id"] not in c["rule_ids"]:
                continue
            for source in r.get("sources", []):
                if source["id"] not in seen:
                    group["evidence"].append(source)
                    seen.add(source["id"])
    for g in groups:
        g.pop("_members", None)
    return groups


@_cached_resource
@timed("model.local_sbert.load")
def _local_encoder():
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    encoder = SentenceTransformer(
        "sentence-transformers/distiluse-base-multilingual-cased-v2", device=device
    )
    encoder.max_seq_length = 128
    if device == "cuda":
        encoder.half()
    return encoder


# --- Coherence ---


@_cached_resource
@timed("model.preload")
def preload_models():
    """Load and warm resources in the pool child that will execute analysis jobs."""
    sample = "This document describes the system requirements."
    _encoder().encode([sample], show_progress_bar=False)
    _local_encoder().encode([sample], show_progress_bar=False)
    _nli()(
        {"text": sample, "text_pair": sample}, truncation=True, max_length=512
    )
    _units()
    log_event("models.ready")


COHERENCE_MODEL = model
MIN_SENTENCE_CHARS = 20
INTRUSIVE_REFERENCE_THRESHOLD = 0.35
FLOW_ABS_THRESHOLD = 0.30
OFF_TOPIC_THRESHOLD = 0.18
MAD_MULTIPLIER = 1.5
DEBUG = False
np = _LazyModule("numpy")
SUMMARY_ENTAILMENT_THRESHOLD = 0.45
SEMANTIC_ABSOLUTE_THRESHOLD = 0.30
ROBUST_MAD_MULTIPLIER = 1.5


def nli_predict(premise, hypothesis):
    predictions = _nli()(
        {"text": premise, "text_pair": hypothesis},
        top_k=None,
        truncation=True,
        max_length=512,
    )
    if predictions and isinstance(predictions[0], list):
        predictions = predictions[0]
    scores = {str(p["label"]).lower(): float(p["score"]) for p in predictions}
    if set(scores) != {"entailment", "neutral", "contradiction"} or any(
        not math.isfinite(score) or not 0 <= score <= 1 for score in scores.values()
    ):
        raise ValueError("Unexpected NLI labels")
    return scores


def _skip_section(location):
    return bool(
        re.search(
            "lời cam đoan|tài liệu tham khảo|references|mục lục|cấu trúc của báo cáo|danh mục",
            location,
            re.I,
        )
    )


def _is_nonprose_line(line):
    s = line.strip()
    if not s:
        return False
    if re.match("^(?:#{1,6}\\s|[-*•‣]\\s|\\d+[.)]\\s|[|>`{}\\[\\]])", s):
        return True
    if re.match("^(?:<[/!]?[a-z]|\\w+\\s*=\\s*\\{|\\w+\\s*=\\s*\\[)", s, re.I):
        return True
    if s.count("|") >= 2 or re.match("^(?:ID:|SCORE\\b|_node_|file_name:)", s, re.I):
        return True
    return bool(re.match("^(?:Hình|Bảng|Figure|Table)\\s+\\d+", s, re.I))


def _local_threshold(scores):
    if len(scores) < 3:
        return None
    arr = np.asarray(scores, dtype=np.float32)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    return med - MAD_MULTIPLIER * mad if mad > 1e-06 else med - 0.08


def split_into_sentences(text):
    segments, lines = ([], [])

    def flush():
        if not lines:
            return
        joined = " ".join(lines)
        sentences = [
            s.strip()
            for s in re.split("(?<=[.!?])\\s+", joined)
            if len(s.strip()) >= MIN_SENTENCE_CHARS
        ]
        if sentences:
            segments.append(sentences)
        lines.clear()

    for line in text.splitlines():
        if _is_nonprose_line(line):
            flush()
        elif line.strip():
            lines.append(line.strip())
    flush()
    return segments


def _section_sort_key(item):
    key = str(item[0]).strip()
    match = re.fullmatch("[Hh](\\d+)", key)
    if match:
        return (0, int(match.group(1)))
    return (1, key.lower())


def build_section_context(sections_dict):
    if not isinstance(sections_dict, dict) or not sections_dict:
        return ("[Văn bản chung / Không có Tiêu đề]", "")
    ordered = sorted(sections_dict.items(), key=_section_sort_key)
    cleaned = [
        (str(key).strip(), str(value).strip())
        for key, value in ordered
        if str(value).strip()
    ]
    if not cleaned:
        return ("[Văn bản chung / Không có Tiêu đề]", "")
    full_section_path = " > ".join((f"{key}: {value}" for key, value in cleaned))
    section_context = ". ".join((value for _, value in cleaned))
    return (full_section_path, section_context)


def remove_repeated_headers_footers(paragraphs, min_repeat=3):
    """Clean repeated short PDF lines without modifying input or losing chunk IDs."""

    def norm(line):
        return re.sub(r"\s+", " ", line).strip().casefold()

    frequency = Counter()
    for paragraph in paragraphs:
        frequency.update(
            {
                norm(line)
                for line in paragraph.get("content", "").splitlines()
                if line.strip()
                and len(line.strip()) <= 120
                and not line.lstrip().startswith("#")
            }
        )
    noise = {line for line, count in frequency.items() if count >= min_repeat}
    cleaned = []
    for index, paragraph in enumerate(paragraphs):
        content = "\n".join(
            line
            for line in paragraph.get("content", "").splitlines()
            if line.lstrip().startswith("#") or norm(line) not in noise
        ).strip()
        if content:
            cleaned.append(
                {
                    **paragraph,
                    "chunk_id": paragraph.get("chunk_id", index + 1),
                    "content": content,
                }
            )
    return cleaned


def robust_threshold(scores, k=ROBUST_MAD_MULTIPLIER, fallback=0.08):
    if not scores:
        return None
    values = [_similarity(score) for score in scores]
    center = median(values)
    mad = median(abs(score - center) for score in values)
    return center - k * mad if mad > 1e-6 else center - fallback


def batch_embedding_cache(paragraphs, encoder):
    prepared, texts = ([], [])
    for index, paragraph in enumerate(paragraphs):
        location, heading = build_section_context(paragraph.get("sections", {}))
        if _skip_section(location):
            continue
        groups = split_into_sentences(paragraph.get("content", ""))
        if not groups:
            continue
        prepared.append(
            (paragraph.get("chunk_id", index + 1), location, heading, groups)
        )
        texts.extend(sentence for group in groups for sentence in group)
        if heading:
            texts.append(heading)
    unique = list(dict.fromkeys(texts))
    if not unique:
        return (prepared, {}, 0)
    with timed_step("local.embedding", sentences=len(unique), batch_size=64):
        vectors, misses = local_embedding_cache.encode(unique, encoder)
        log_event("embedding.cache", hits=len(unique) - misses, misses=misses)
    return (prepared, vectors, misses)


def _region_candidates(E, heading=None, debug=False):
    n = len(E)
    if n < 2:
        return []
    reference, start, min_score = (0, None, 1.0)
    spans = []
    for i in range(1, n):
        score = float(np.dot(E[reference], E[i]))
        if score >= INTRUSIVE_REFERENCE_THRESHOLD:
            if start is not None:
                spans.append(
                    dict(start=start, end=i, semantic_score=round(min_score, 4))
                )
                start, min_score = (None, 1.0)
            reference = i
        else:
            if start is None:
                start = i
            min_score = min(min_score, score)
    if start is not None:
        spans.append(dict(start=start, end=n, semantic_score=round(min_score, 4)))
    return spans


def generate_local_coherence_candidates(paragraphs, debug=DEBUG):
    model = _local_encoder()
    prepared, cache, n_encoded = batch_embedding_cache(paragraphs, model)
    candidates = []
    for chunk_id, location, section_context, groups in prepared:
        sentences_all = [s for g in groups for s in g]
        head = cache.get(section_context)
        if head is not None and len(sentences_all) >= 3:
            Eall = np.stack([cache[s] for s in sentences_all])
            avg = Eall.mean(axis=0)
            avg /= np.linalg.norm(avg) + 1e-09
            hscore = float(avg @ head)
            per_sentence = Eall @ head
            if hscore < OFF_TOPIC_THRESHOLD and np.mean(per_sentence < 0.25) >= 0.65:
                candidates.append(
                    dict(
                        candidate_type="off_topic",
                        chunk_id=chunk_id,
                        location=location,
                        section_context=section_context,
                        text=" ".join(sentences_all),
                        semantic_score=round(hscore, 4),
                    )
                )
        for gi, sentences in enumerate(groups):
            if len(sentences) < 2:
                continue
            E = np.stack([cache[s] for s in sentences])
            spans = _region_candidates(E, heading=head, debug=debug)
            for span in spans:
                a, b = (span["start"], span["end"])
                candidates.append(
                    dict(
                        candidate_type="intrusive_span",
                        chunk_id=chunk_id,
                        group_index=gi,
                        location=location,
                        section_context=section_context,
                        start_sentence=a,
                        end_sentence_exclusive=b,
                        text=" ".join(sentences[a:b]),
                        previous_context=" ".join(sentences[max(0, a - 2) : a]),
                        next_context=" ".join(
                            sentences[b : min(len(sentences), b + 2)]
                        ),
                        semantic_score=span["semantic_score"],
                    )
                )
            adjacent = np.einsum("ij,ij->i", E[:-1], E[1:])
            thr = _local_threshold(adjacent)
            if thr is not None:
                thr = min(thr, FLOW_ABS_THRESHOLD)
                covered = {
                    pos for span in spans for pos in (span["start"], span["end"])
                }
                for boundary, score in enumerate(adjacent, 1):
                    if score >= thr or boundary in covered:
                        continue
                    candidates.append(
                        dict(
                            candidate_type="flow_break",
                            chunk_id=chunk_id,
                            group_index=gi,
                            location=location,
                            section_context=section_context,
                            boundary_index=boundary,
                            previous_context=(
                                sentences[boundary - 2] if boundary > 1 else ""
                            ),
                            sentence_1=sentences[boundary - 1],
                            sentence_2=sentences[boundary],
                            next_context=(
                                sentences[boundary + 1]
                                if boundary + 1 < len(sentences)
                                else ""
                            ),
                            semantic_score=round(float(score), 4),
                            flow_threshold=round(thr, 4),
                        )
                    )
    for i, c in enumerate(candidates):
        c["candidate_id"] = f"LC_{i:04d}"
    return candidates


def get_chunk_content(chunk: dict) -> str:
    for key in ["content", "page_content", "text", "chunk_text", "original_content"]:
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def validate_chunk_summaries(summaries_by_section: dict):
    validated_sections = []
    bad_summary_chunks = []
    section_counter = 1
    for sec_name, chunks in summaries_by_section.items():
        trusted_chunks = []
        for chunk_position, chunk in enumerate(chunks):
            chunk_idx = chunk.get("chunk_idx", chunk_position)
            summary = str(chunk.get("summary_sentence", "")).strip()
            if not summary:
                continue
            content = get_chunk_content(chunk)
            if not content:
                bad_summary_chunks.append(
                    {
                        "section": f"S{section_counter}",
                        "section_name": str(sec_name),
                        "chunk_idx": chunk_idx,
                        "summary": summary,
                        "content": "",
                        "entailment": None,
                        "reason": "missing_source",
                    }
                )
                continue
            prediction = nli_predict(premise=content, hypothesis=summary)
            entailment = prediction["entailment"]
            if entailment >= SUMMARY_ENTAILMENT_THRESHOLD:
                trusted_chunks.append(
                    {
                        "chunk_idx": chunk_idx,
                        "summary": summary,
                        "content": content,
                        "entailment": round(entailment, 4),
                    }
                )
            else:
                bad_summary_chunks.append(
                    {
                        "section": f"S{section_counter}",
                        "section_name": str(sec_name),
                        "chunk_idx": chunk_idx,
                        "summary": summary,
                        "content": content,
                        "entailment": round(prediction["entailment"], 4),
                        "neutral": round(prediction["neutral"], 4),
                        "contradiction": round(prediction["contradiction"], 4),
                    }
                )
        if not trusted_chunks:
            section_counter += 1
            continue
        validated_sections.append(
            {
                "id": f"S{section_counter}",
                "name": str(sec_name).strip(),
                "chunks": trusted_chunks,
            }
        )
        section_counter += 1
    return (validated_sections, bad_summary_chunks)


def section_to_text(section: dict) -> str:
    return " ".join(
        chunk["summary"] for chunk in section["chunks"] if chunk.get("summary")
    ).strip()


def detect_semantic_coherence_candidates(sections):
    pairs = [
        (a, b)
        for a, b in zip(sections, sections[1:], strict=False)
        if not a.get("structural_only")
        and not b.get("structural_only")
        and section_to_text(a)
        and section_to_text(b)
    ]
    if not pairs:
        return [], []
    unique = {s["id"]: s for pair in pairs for s in pair}
    ids = list(unique)
    embeddings = COHERENCE_MODEL.encode(
        [section_to_text(unique[sid]) for sid in ids],
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    vectors = dict(zip(ids, embeddings, strict=True))
    transitions, scores = [], []
    for a, b in pairs:
        score = _similarity(
            util.cos_sim(vectors[a["id"]], vectors[b["id"]]).item()
        )
        scores.append(score)
        transitions.append(
            {
                "from_section": a["id"],
                "to_section": b["id"],
                "from_name": a["name"],
                "to_name": b["name"],
                "from_text": section_to_text(a),
                "to_text": section_to_text(b),
                "semantic_score": round(score, 4),
            }
        )
    threshold = robust_threshold(scores, fallback=0.1)
    retrieved = []
    for transition, score in zip(transitions, scores, strict=True):
        is_candidate = score < threshold
        transition.update(
            robust_threshold=round(threshold, 4),
            absolute_threshold=SEMANTIC_ABSOLUTE_THRESHOLD,
            candidate=is_candidate,
            candidate_strength=(
                "strong"
                if score < SEMANTIC_ABSOLUTE_THRESHOLD
                else "moderate"
                if is_candidate
                else None
            ),
        )
        if is_candidate:
            retrieved.append(transition.copy())
    return transitions, sorted(retrieved, key=lambda c: c["semantic_score"])


def deduplicate_local_issues(issues):
    spans = {}
    for x in issues:
        if x.get("issue_type") == "intrusive_span":
            key = (x.get("chunk_id"), x.get("group_index", 0))
            spans.setdefault(key, set()).update(
                (x["start_sentence"], x["end_sentence_exclusive"])
            )
    return [
        x
        for x in issues
        if not (
            x.get("issue_type") == "flow_break"
            and x.get("boundary_index")
            in spans.get((x.get("chunk_id"), x.get("group_index", 0)), set())
        )
    ]


# --- Verification ---


def terminology_candidates(blocks):
    """Notebook cell 8: defined terms only, ANN synonymy and hashed polysemy."""
    unique = {}
    for block in blocks:
        for item in block.get("data", []):
            term = str(item.get("term", "")).strip()
            definition = str(item.get("definition", "")).strip()
            if not term or is_invalid_definition(definition):
                continue
            key = (
                normalize_term(term),
                normalize_text(definition),
            )
            record = unique.setdefault(
                key,
                {
                    "term": term,
                    "def": key[1],
                    "loc": block.get("sections", "Unknown"),
                    "chunk_indices": [],
                    "locations": [],
                },
            )
            if block["chunk_idx"] not in record["chunk_indices"]:
                record["chunk_indices"].append(block["chunk_idx"])
            if block.get("sections", "Unknown") not in record["locations"]:
                record["locations"].append(block.get("sections", "Unknown"))
    records = list(unique.values())
    if len(records) < 2:
        return [], [], []
    synonyms = ann_synonym_candidates(records, get_sbert_model())
    for pair in synonyms:
        a, b = (records[pair[key]] for key in ("record_index_1", "record_index_2"))
        pair.update(
            chunk_indices=sorted(set(a["chunk_indices"] + b["chunk_indices"])),
            locations_1=a["locations"],
            locations_2=b["locations"],
            quotes=[],
        )
    by_term = {}
    for index, record in enumerate(records):
        by_term.setdefault(normalize_term(record["term"]), []).append(index)
    polysemy = []
    for indices in by_term.values():
        for i, j in combinations(indices, 2):
            a, b = records[i], records[j]
            if definitions_compatible(a["def"], b["def"]):
                continue
            polysemy.append(
                {
                    "record_index_1": i,
                    "record_index_2": j,
                    "term": a["term"],
                    "definition_1": a["def"],
                    "definition_2": b["def"],
                    "location_1": a["loc"],
                    "location_2": b["loc"],
                    "locations_1": a["locations"],
                    "locations_2": b["locations"],
                    "semantic_similarity": semantic_similarity(a["def"], b["def"]),
                    "lexical_coverage": lexical_coverage(a["def"], b["def"]),
                    "chunk_indices": sorted(
                        set(a["chunk_indices"] + b["chunk_indices"])
                    ),
                    "quotes": [],
                }
            )
    return [], synonyms, polysemy


def group_synonym_errors(errors):
    """Count connected, verified names for one concept as one naming issue."""
    parent = {}

    def root(index):
        parent.setdefault(index, index)
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for error in errors:
        left, right = root(error["record_index_1"]), root(error["record_index_2"])
        parent[right] = left
    groups = {}
    for error in errors:
        groups.setdefault(root(error["record_index_1"]), []).append(error)
    result = []
    for pairs in groups.values():
        terms = list(
            dict.fromkeys(pair[key] for pair in pairs for key in ("term_1", "term_2"))
        )
        result.append(
            {
                "type": "synonymy",
                "terms": terms,
                "description": "Nhiều cách gọi cho cùng một khái niệm: "
                + ", ".join(terms)
                + ". "
                + " ".join(dict.fromkeys(pair["reason"] for pair in pairs)),
                "confirmed_pairs": pairs,
                "chunk_indices": sorted(
                    {i for pair in pairs for i in pair["chunk_indices"]}
                ),
                "quotes": [],
            }
        )
    return result


@timed("detector.verify")
async def verify(llm, retrieved, prompt, schema, *, context=None):
    if not retrieved:
        return [], []
    # Bound response size; each batch requires a decision for every local index.
    if len(retrieved) > 15:
        errors, decisions = [], []
        for start in range(0, len(retrieved), 15):
            batch_errors, batch_decisions = await verify(
                llm,
                retrieved[start : start + 15],
                prompt,
                schema,
                context=context,
            )
            errors.extend(
                {**e, "candidate_index": e["candidate_index"] + start}
                for e in batch_errors
            )
            decisions.extend(
                {**d, "candidate_index": d["candidate_index"] + start}
                for d in batch_decisions
            )
        return errors, decisions
    decisions = await _verify_decisions(llm, retrieved, prompt, schema, context)
    errors = []
    for decision in decisions:
        # Notebook cell 9 accepts only explicit, valid conflicts. Terminology
        # cells derive is_error from relation directly (no redundant LLM flag).
        if isinstance(decision, DataDecision):
            decision.is_error = bool(
                decision.is_error
                and decision.relation == "conflict"
                and decision.severity
            )
        if decision.is_error:
            if hasattr(decision, "severity") and not decision.severity:
                raise EvaluationUnavailable("Missing verified issue severity")
            if (
                isinstance(decision, GlobalTransitionDecision)
                and not decision.issue_type
            ):
                raise EvaluationUnavailable("Missing global transition issue type")
            source = retrieved[decision.candidate_index]
            if (
                isinstance(decision, LocalDecision)
                and decision.issue_type != source["candidate_type"]
            ):
                raise EvaluationUnavailable("Verification changed candidate type")
            errors.append(
                {
                    **source,
                    **decision.model_dump(),
                    "description": decision.reason,
                }
            )
    return errors, [{**d.model_dump(), "is_error": d.is_error} for d in decisions]


async def _verify_decisions(llm, candidates, prompt, schema, context):
    """Retry missing/duplicate decisions once without rechecking valid results."""
    pending = set(range(len(candidates)))
    checked = {}
    for attempt in range(2):
        payload = [{**candidates[i], "candidate_index": i} for i in sorted(pending)]
        review = await llm.call(
            prompt + current_prompts.VERIFY_FORMAT,
            json.dumps({**(context or {}), "candidates": payload}, ensure_ascii=False),
            schema,
        )
        counts = Counter(d.candidate_index for d in review.results)
        checked.update(
            (d.candidate_index, d)
            for d in review.results
            if d.candidate_index in pending and counts[d.candidate_index] == 1
        )
        pending.difference_update(checked)
        if not pending:
            return [checked[i] for i in range(len(candidates))]
        log_event(
            "verification.incomplete",
            schema=schema.__name__,
            attempt=attempt + 1,
            expected=len(candidates),
            received=len(checked),
            unresolved=len(pending),
        )
    raise EvaluationUnavailable("Incomplete or duplicate candidate decisions")


async def detect_logic(statements, chunks, llm, diagnostics):
    # Verify against original source even when MAP paraphrases its source_quote.
    statements = [dict(statement) for statement in statements]
    diagnostics["source_quote_fallback_count"] = 0
    for statement in statements:
        index = statement.get("chunk_idx")
        quote = " ".join(str(statement.get("evidence", "")).split())
        if type(index) is not int or not 0 <= index < len(chunks):
            raise EvaluationUnavailable("Ungrounded logical source index")
        content = " ".join(chunks[index]["content"].split())
        if not quote or quote not in content:
            if not content:
                raise EvaluationUnavailable("Empty logical source")
            statement["evidence"] = chunks[index]["content"]
            statement["source_quote"] = ""
            diagnostics["source_quote_fallback_count"] += 1

    def retrieve():
        with timed_step("logical.normalize", statements=len(statements)):
            rules, entities = resolve_entities(
                prepare(statements)
            )
        with timed_step("logical.candidates.graph", rules=len(rules)):
            direct = generate_graph_candidates(rules)
        with timed_step("logical.candidates.constraints", rules=len(rules)):
            constraints = generate_constraint_candidates(rules, max_candidates=None)
        with timed_step(
            "logical.retrieve", direct=len(direct), constraints=len(constraints)
        ):
            retrieved = retrieve_graph(
                merge_candidates(direct, constraints), rules, top_k=3
            )
        with timed_step("logical.state_graph", rules=len(rules)):
            warnings = state_graph_candidates(rules)
        return rules, entities, retrieved, warnings

    rules, entities, retrieved, warnings = await asyncio.to_thread(retrieve)
    diagnostics.update(
        logic_statements=rules,
        entity_map=entities,
        candidates=retrieved,
        state_warnings=warnings,
        verification_decisions=[],
        confirmed_logic_issues=[],
    )

    def pack_rule(rule):
        return {
            key: rule[key]
            for key in (
                "id",
                *FIELDS,
                "evidence",
                "section",
                "chunk_idx",
                "sources",
            )
        }

    async def verify_batch(batch):
        with timed_step(
            "logical.verify.batch",
            first_pair_id=batch[0]["pair_id"],
            candidates=len(batch),
        ):
            return await verify_batch_decisions(batch)

    async def verify_batch_decisions(batch):
        payload = {
            "candidates": [
                {
                    "pair_id": c["pair_id"],
                    "candidate_type": c["type"],
                    "hypothesis": c["reason"],
                    "reasoning_path": c["reasoning_path"],
                    "rules": [pack_rule(r) for r in c["statements"]],
                    "supporting_rules": [pack_rule(r) for r in c["supporting_rules"]],
                    "supporting_paths": c["supporting_paths"],
                }
                for c in batch
            ]
        }
        review = await llm.call(
            current_prompts.BATCH_VERIFY_SYSTEM
            + "\nViết reason, context, root_cause bằng tiếng Việt.",
            json.dumps(payload, ensure_ascii=False),
            LogicReview,
        )
        if sorted(d.pair_id for d in review.results) != [b["pair_id"] for b in batch]:
            raise EvaluationUnavailable("Incomplete or duplicate logic decisions")
        checked = []
        for decision in sorted(review.results, key=lambda d: d.pair_id):
            source = retrieved[decision.pair_id]
            ids = decision.rule_ids
            if len(ids) != len(set(ids)) or not set(ids) <= set(source["rule_ids"]):
                raise EvaluationUnavailable("Invalid conflicting rule IDs")
            if decision.status == "VERIFIED" and (
                not decision.evidence_sufficient
                or decision.type == "NONE"
                or not decision.severity
                or len(ids) < 2
            ):
                raise EvaluationUnavailable("Insufficient verified logical evidence")
            checked.append(
                {
                    **source,
                    **decision.model_dump(),
                    "status": (
                        "CONFIRMED"
                        if decision.status == "VERIFIED"
                        else decision.status
                    ),
                }
            )
        return checked

    # Four candidates/request as in the notebook; the shared LLM limits concurrency.
    with timed_step("logical.verify", candidates=len(retrieved)):
        batches = await asyncio.gather(
            *(verify_batch(retrieved[i : i + 4]) for i in range(0, len(retrieved), 4)),
            return_exceptions=True,
        )
    checked = sorted(
        [c for batch in batches if isinstance(batch, list) for c in batch],
        key=lambda c: c["pair_id"],
    )
    diagnostics["verification_decisions"] = [
        {key: c[key] for key in LogicDecision.model_fields} for c in checked
    ]
    with timed_step("logical.cluster", decisions=len(checked)):
        errors = cluster_issues(checked)
    for error in errors:
        error.update(
            description=error["reason"],
            chunk_indices=sorted({s["chunk_idx"] for s in error["evidence"]}),
            quotes=list(dict.fromkeys(s["evidence"] for s in error["evidence"])),
        )
    diagnostics["confirmed_logic_issues"] = errors
    diagnostics["uncertain_count"] = sum(c["status"] == "UNCERTAIN" for c in checked)
    with timed_step("logical.verify.completeness"):
        failed_batches = sum(isinstance(batch, BaseException) for batch in batches)
        log_event(
            "verification.result",
            candidates=len(retrieved),
            decisions=len(checked),
            confirmed=sum(c["status"] == "CONFIRMED" for c in checked),
            rejected=sum(c["status"] == "REJECTED" for c in checked),
            uncertain=diagnostics["uncertain_count"],
            issues=len(errors),
            failed_batches=failed_batches,
        )
        if failed_batches:
            log_event("scoring.blocked", reason="incomplete_verification")
            raise EvaluationUnavailable("Incomplete logic verification")
        if diagnostics["uncertain_count"]:
            # Notebook cell 7 scores CONFIRMED clusters; UNCERTAIN stays diagnostic.
            log_event("scoring.partial", uncertain=diagnostics["uncertain_count"])
    return errors


async def detect(kind, terminology, claims, chunks, llm, diagnostics):
    if kind == "TERMINOLOGY_CONSISTENCY":
        with timed_step("terminology.candidates", blocks=len(terminology)):
            undefined, synonyms, polysemy = await asyncio.to_thread(
                terminology_candidates, terminology
            )
        diagnostics.update(
            candidates={
                "undefined": undefined,
                "synonymy": synonyms,
                "polysemy": polysemy,
            },
        )
        # Notebook 2 grades defined-term synonymy/polysemy only. Keep empty
        # legacy diagnostic keys for existing snapshot readers.
        diagnostics.update(undefined_errors=[], undefined_decisions=[])
        naming, naming_decisions = await verify(
            llm,
            synonyms,
            current_prompts.SYS_VERIFY_SYNONYM,
            SynonymReview,
        )
        diagnostics["synonymy_decisions"] = naming_decisions
        definitions, definition_decisions = await verify(
            llm,
            polysemy,
            current_prompts.SYS_VERIFY_POLYSEMY,
            PolysemyReview,
        )
        diagnostics["polysemy_decisions"] = definition_decisions
        return [
            *group_synonym_errors(naming),
            *[{**e, "type": "polysemy"} for e in definitions],
        ]
    if kind == "DATA_CONSISTENCY":
        with timed_step("data.candidates", claims=len(claims)):
            retrieved = await asyncio.to_thread(find_data_conflict_candidates, claims)
        diagnostics["candidates"] = retrieved
        errors, decisions = await verify(
            llm, retrieved, current_prompts.SYS_VERIFY_DATA, DataReview
        )
        for error in errors:
            error.update(
                type="data_conflict",
                chunk_indices=sorted({error["chunk_1"], error["chunk_2"]}),
                quotes=[],
            )
    elif kind == "LOCAL_COHERENCE":
        with timed_step("local.candidates", chunks=len(chunks)):
            cleaned = remove_repeated_headers_footers(chunks)
            retrieved = await asyncio.to_thread(
                generate_local_coherence_candidates, cleaned
            )
        # Candidate indices refer to the original input, including short chunks.
        diagnostics["candidates"] = retrieved
        errors, decisions = await verify(
            llm,
            retrieved,
            current_prompts.SYS_VERIFY_LOCAL.split("Trả đúng JSON", 1)[0]
            + "\nThay định dạng KEEP/DROP bằng results theo schema cuối: "
            "candidate_index là chỉ số trong danh sách, is_error=true cho KEEP, "
            "false cho DROP. Phải trả issue_type đúng bằng candidate_type, "
            "kể cả candidate bị loại. Không trả candidate_id hoặc decision.",
            LocalReview,
        )
        errors = deduplicate_local_issues(errors)
        for error in errors:
            error["chunk_indices"] = [
                i
                for i, c in enumerate(chunks)
                if c.get("chunk_id", i + 1) == error["chunk_id"]
            ]
            error["quotes"] = [
                error[k]
                for k in ("text", "sentence", "sentence_1", "sentence_2")
                if error.get(k)
            ]
    else:
        raise EvaluationUnavailable("Unknown detector")
    diagnostics["verification_decisions"] = decisions
    return errors


async def detect_global(
    summaries, llm, diagnostics, *, section_map=None
):
    with timed_step("global.validate_summaries", sections=len(summaries)):
        sections, drift = await asyncio.to_thread(validate_chunk_summaries, summaries)
    diagnostics["summary_drift"] = drift
    if not sections:
        raise EvaluationUnavailable("No grounded summaries for global assessment")
    sections = restore_sections(sections, section_map)
    diagnostics["restored_sections"] = [
        {"id": s["id"], "name": s["name"], "page": s.get("page")}
        for s in sections
        if s.get("structural_only")
    ]
    structural_instruction = (
        "\nSTRUCTURAL_ONLY/structural_only=true là mục có thật trong PDF nhưng "
        "chưa phân tích được nội dung ảnh/bảng. Không coi mục đó là bị thiếu, "
        "không suy diễn nội dung và không báo lỗi do khoảng trống tiền xử lý."
    )
    with timed_step("global.candidates", sections=len(sections)):
        transitions, retrieved = await asyncio.to_thread(
            detect_semantic_coherence_candidates, sections
        )
    diagnostics.update(transition_scores=transitions, semantic_candidates=retrieved)
    summary = await llm.call(
        current_prompts.SYS_GLOBAL_SUMMARY
        + structural_instruction
        + "\nViết bằng tiếng Việt.",
        json.dumps({"sections": sections}, ensure_ascii=False),
        GlobalSummary,
    )
    if not isinstance(summary, GlobalSummary):
        raise EvaluationUnavailable("Invalid global summary response")
    diagnostics["global_summary"] = summary.global_summary
    section_ids = {s["id"] for s in sections}
    for candidate in retrieved:
        if not {candidate["from_section"], candidate["to_section"]} <= section_ids:
            raise EvaluationUnavailable("Global issue references an unknown transition")
    transition_errors, decisions = await verify(
        llm,
        retrieved,
        current_prompts.SYS_GLOBAL_TRANSITIONS
        + "\nSchema cuối: results chứa quyết định cho từng candidate_index; "
        "is_error=false nếu transition hợp lý, issue_type và severity có thể rỗng.",
        GlobalTransitionReview,
        context={"sections": sections},
    )
    diagnostics["transition_decisions"] = decisions
    issues = [
        GlobalIssue.model_validate(
            {key: error[key] for key in GlobalIssue.model_fields}
        ).model_dump()
        for error in transition_errors
    ]
    # Keep confirmed findings available if structure verification or grading fails.
    diagnostics["confirmed_global_issues"] = _global_findings(issues, sections)
    structure = await llm.call(
        current_prompts.SYS_GLOBAL_STRUCTURE
        + structural_instruction
        + "\nViết reason bằng tiếng Việt; section phải "
        "là ID trong sections. Không có lỗi thì coherence_issues=[].",
        json.dumps({"sections": sections}, ensure_ascii=False),
        GlobalStructureReview,
    )
    if not isinstance(structure, GlobalStructureReview):
        raise EvaluationUnavailable("Invalid global structure response")
    for issue in structure.coherence_issues:
        if issue.section not in section_ids:
            raise EvaluationUnavailable("Global issue references an unknown section")
    diagnostics["structure_issues"] = [
        issue.model_dump()
        for issue in structure.coherence_issues
        if not next(s for s in sections if s["id"] == issue.section).get(
            "structural_only"
        )
    ]
    issues = _deduplicate_global_issues(issues + diagnostics["structure_issues"])
    issues = _global_findings(issues, sections)
    diagnostics["confirmed_global_issues"] = issues
    return issues


def _deduplicate_global_issues(issues):
    """Notebook identity deduplication; retain the strongest confirmed severity."""
    unique = {}
    rank = {"minor": 0, "moderate": 1, "major": 2}
    for issue in issues:
        key = tuple(
            issue.get(k, "")
            for k in ("issue_type", "section", "from_section", "to_section")
        )
        if key not in unique or rank[issue["severity"]] > rank[unique[key]["severity"]]:
            unique[key] = issue
    return list(unique.values())


def _global_findings(issues, sections):
    return [
        {
            **issue,
            "description": issue["reason"],
            "suggestion": "Kiểm tra và bổ sung liên kết giữa các phần được nêu.",
            "chunk_indices": sorted(
                {
                    chunk["chunk_idx"]
                    for section in sections
                    if section["id"]
                    in {
                        issue.get("section"),
                        issue.get("from_section"),
                        issue.get("to_section"),
                    }
                    for chunk in section["chunks"]
                }
            ),
            "quotes": [],
        }
        for issue in issues
    ]
