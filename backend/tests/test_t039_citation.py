from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import citation
from app.services.document_ir import parse_document_ir

_PDF_FIXTURES = Path(__file__).parent / "fixtures" / "citation_pdfs"


def _parse_pdf_fixture(filename: str):
    document = parse_document_ir((_PDF_FIXTURES / filename).read_bytes())
    return document, citation.parse_citations(document)


def _document() -> dict[str, object]:
    return {
        "schema_version": 2,
        "source": {"sha256": "0" * 64, "size_bytes": 1, "page_count": 2},
        "pages": [],
        "sections": [
            {
                "id": "section-1",
                "text": "References",
                "level": 1,
                "parent_id": None,
                "page_number": 2,
            }
        ],
        "paragraphs": [
            {
                "id": "paragraph-1",
                "section_id": None,
                "page_number": 1,
                "text": "Prior work [1, 9]. (Nguyen, 2024) supports this result.",
            },
            {
                "id": "paragraph-2",
                "section_id": "section-1",
                "page_number": 2,
                "text": (
                    '[1] Nguyen, A. (2024). "First study". Journal. '
                    "doi:10.1000/ABC.1"
                ),
            },
            {
                "id": "paragraph-3",
                "section_id": "section-1",
                "page_number": 2,
                "text": "[2] Uncited, B. (2020). Second study. Journal.",
            },
        ],
        "tables": [],
        "links": [],
    }


def test_citation_ids_and_linkage_are_deterministic() -> None:
    first = citation.parse_citations(_document())
    second = citation.parse_citations(_document())

    assert [item.id for item in first.references] == [
        item.id for item in second.references
    ]
    assert [item.id for item in first.mentions] == [item.id for item in second.mentions]
    assert first.references[0].doi == "10.1000/abc.1"
    assert any(item.status == citation.LINKED for item in first.mentions)
    assert any(item.status == citation.AMBIGUOUS for item in first.mentions)
    assert first.references[1].linkage_status == citation.UNCITED_REFERENCE


def test_crossref_field_comparison_keeps_unknown_unresolved() -> None:
    reference = citation.parse_citations(_document()).references[0]
    matching = {
        "comparison": {
            "title": "first study",
            "authors": ["nguyen a"],
            "year": 2024,
            "venue": reference.venue,
        }
    }
    mismatch = {
        "comparison": {
            "title": "different study",
            "authors": ["nguyen a"],
            "year": 2024,
            "venue": reference.venue,
        }
    }

    assert citation._identity(reference, matching) == (citation.VERIFIED, ())
    assert citation._identity(reference, mismatch) == (
        citation.METADATA_MISMATCH,
        ("title",),
    )
    assert citation._identity(reference, None) == (citation.UNRESOLVED, ())


def test_identity_accepts_crossref_full_author_list() -> None:
    reference = citation.CitationReference(
        id="reference-real",
        number=1,
        raw="",
        page_number=1,
        element_id="paragraph-1",
        start=0,
        end=0,
        snippet="",
        title="Array programming with NumPy",
        authors=("Harris, C. R., Millman, K. J.",),
        year=2020,
        venue="Nature",
    )
    record = {
        "comparison": {
            "title": "array programming with numpy",
            "authors": ["charles r harris", "k jarrod millman"],
            "year": 2020,
            "venue": "nature",
        }
    }

    assert citation._identity(reference, record) == (citation.VERIFIED, ())


def test_candidate_search_selects_matching_record(monkeypatch) -> None:
    reference = citation.CitationReference(
        id="reference-search",
        number=None,
        raw="Harris, C. R. (2020). Array programming with NumPy.",
        page_number=1,
        element_id="paragraph-search",
        start=0,
        end=52,
        snippet="Array programming with NumPy.",
        title="Array programming with NumPy",
        authors=("Harris, C. R.",),
        year=2020,
        venue="Nature",
    )
    monkeypatch.setattr(citation, "_wait_for_crossref_rate_limit", lambda: None)
    monkeypatch.setattr(
        citation,
        "_crossref_request",
        lambda _url: {
            "message": {
                "items": [
                    {
                        "DOI": "10.0000/wrong",
                        "title": ["Review of array programming with NumPy"],
                        "author": [{"given": "Ajit", "family": "Singh"}],
                        "published": {"date-parts": [[2021]]},
                        "container-title": ["Other"],
                    },
                    {
                        "DOI": "10.0000/right",
                        "title": ["Array programming with NumPy"],
                        "author": [{"given": "Charles R.", "family": "Harris"}],
                        "published": {"date-parts": [[2020]]},
                        "container-title": ["Nature"],
                    },
                ]
            }
        },
    )

    record = citation.resolve_reference(reference)

    assert record is not None
    assert record["doi"] == "10.0000/right"


def test_crossref_search_results_are_not_shared_between_documents(monkeypatch) -> None:
    raw_prefix = "A" * 260
    references = [
        citation.CitationReference(
            id=f"reference-{suffix}",
            number=1,
            raw=raw_prefix + suffix,
            page_number=1,
            element_id="paragraph-1",
            start=0,
            end=1,
            snippet="Study",
            title="Study",
        )
        for suffix in ("one", "two")
    ]
    calls: list[str] = []
    monkeypatch.setattr(citation, "_wait_for_crossref_rate_limit", lambda: None)
    monkeypatch.setattr(
        citation,
        "_crossref_request",
        lambda url: calls.append(url)
        or {
            "message": {
                "items": [
                    {
                        "DOI": "10.0000/study",
                        "title": ["Study"],
                        "published": {"date-parts": [[2024]]},
                    }
                ]
            }
        },
    )
    with citation._CACHE_LOCK:
        citation._CACHE.clear()
    try:
        assert all(citation.resolve_reference(reference) for reference in references)
        with citation._CACHE_LOCK:
            assert citation._CACHE == {}
    finally:
        with citation._CACHE_LOCK:
            citation._CACHE.clear()

    assert len(calls) == 2


def test_crossref_resolution_count_is_bounded(monkeypatch) -> None:
    references = [
        citation.CitationReference(
            id=f"reference-{index}",
            number=index,
            raw=f"Author, A. (2024). Study {index}. Journal.",
            page_number=1,
            element_id=f"paragraph-{index}",
            start=0,
            end=1,
            snippet=f"Study {index}",
        )
        for index in range(citation._MAX_CROSSREF_RESOLUTIONS + 2)
    ]
    resolved: list[str] = []
    monkeypatch.setattr(
        citation,
        "resolve_reference",
        lambda reference: resolved.append(reference.id) or {"id": reference.id},
    )

    records = asyncio.run(citation._resolve_references(references))

    assert len(resolved) == citation._MAX_CROSSREF_RESOLUTIONS
    assert len(records) == len(references)
    assert records[-2:] == [None, None]


def test_arxiv_only_references_do_not_consume_crossref_budget(monkeypatch) -> None:
    references = [
        citation.CitationReference(
            id=f"arxiv-{index}",
            number=index,
            raw=f"arXiv:{index:04d}.12345",
            page_number=1,
            element_id=f"paragraph-{index}",
            start=0,
            end=1,
            snippet="arXiv",
            arxiv_id=f"{index:04d}.12345",
        )
        for index in range(citation._MAX_CROSSREF_RESOLUTIONS)
    ]
    doi_reference = citation.CitationReference(
        id="doi-reference",
        number=100,
        raw="doi:10.1000/test",
        page_number=2,
        element_id="paragraph-doi",
        start=0,
        end=1,
        snippet="DOI",
        doi="10.1000/test",
    )
    resolved: list[str] = []
    monkeypatch.setattr(
        citation,
        "resolve_reference",
        lambda reference: resolved.append(reference.id) or {"id": reference.id},
    )

    records = asyncio.run(citation._resolve_references([*references, doi_reference]))

    assert resolved == ["doi-reference"]
    assert records[-1] == {"id": "doi-reference"}


def test_crossref_payload_rejects_malformed_nested_fields_without_raising() -> None:
    record = citation._crossref_payload(
        {
            "message": {
                "author": None,
                "title": {},
                "container-title": None,
                "published": {"date-parts": None},
            }
        }
    )

    assert record is not None
    assert record["comparison"] == {
        "title": None,
        "authors": [],
        "year": None,
        "venue": None,
    }


def test_issue_anchor_count_is_bounded() -> None:
    rows = [
        (
            "reference-1",
            citation.UNRESOLVED,
            tuple(
                (f"paragraph-{index}", index + 1, None, None)
                for index in range(citation._MAX_EVIDENCE_ANCHORS_PER_FINDING + 2)
            ),
            "Reference",
        )
    ]

    bounded, truncated = citation._bounded_issue_rows(rows)

    assert len(bounded[0][2]) == citation._MAX_EVIDENCE_ANCHORS_PER_FINDING
    assert ("reference-1", citation.UNRESOLVED) in truncated
    assert "anchors omitted" in bounded[0][3]


def test_evaluator_persists_issue_findings_and_bounded_snapshot(
    monkeypatch,
) -> None:
    criterion = SimpleNamespace(
        id=uuid.uuid4(),
        rubric_version_id=uuid.uuid4(),
        is_enabled=True,
        evaluation_method="CITATION_IDENTITY",
        evaluator_config={},
    )
    job = SimpleNamespace(
        id=uuid.uuid4(),
        rubric_version_id=criterion.rubric_version_id,
        snapshot={},
    )
    document_ir = SimpleNamespace(id=uuid.uuid4(), content=_document())
    monkeypatch.setattr(citation, "resolve_reference", lambda _reference: None)
    monkeypatch.setattr(citation, "_MAX_FINDINGS_PER_CRITERION", 2)

    class ScalarResult:
        def __init__(self, values):
            self.values = values

        def __iter__(self):
            return iter(self.values)

    class Result:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return ScalarResult(self.values)

    class DB:
        def __init__(self):
            self.results = [Result([criterion]), Result([])]
            self.added = []
            self.flush = AsyncMock()

        async def execute(self, _statement):
            return self.results.pop(0)

        def add(self, value):
            self.added.append(value)

    db = DB()
    created = asyncio.run(citation.evaluate_citations(db, job, document_ir))

    assert created == 2
    assert len(db.added) >= created
    assert job.snapshot["citation"]["counts"]["unresolved"] == 2
    assert len(job.snapshot["citation"]["issues"]) == 2
    assert job.snapshot["citation"]["issues"][-1]["status"] == (
        citation.FINDINGS_TRUNCATED
    )


def test_identifier_normalization_and_arxiv_stay_local() -> None:
    assert citation.canonicalize_doi("https://doi.org/10.1234/ABC.") == "10.1234/abc"
    assert citation.extract_arxiv_id("arXiv:2401.01234v2") == "2401.01234v2"
    assert (
        citation.resolve_reference(
            citation.CitationReference(
                id="reference-1",
                number=1,
                raw="arXiv:2401.01234v2",
                page_number=1,
                element_id="paragraph-1",
                start=0,
                end=18,
                snippet="arXiv:2401.01234v2",
                arxiv_id="2401.01234v2",
            )
        )
        is None
    )


def test_continued_reference_stitches_pages_and_preserves_anchors() -> None:
    document = {
        "sections": [
            {
                "id": "section-references",
                "text": "References",
                "level": 1,
                "parent_id": None,
                "page_number": 2,
            }
        ],
        "paragraphs": [
            {
                "id": "paragraph-body",
                "section_id": None,
                "page_number": 1,
                "text": "The method is cited [1].",
            },
            {
                "id": "paragraph-reference-1",
                "section_id": "section-references",
                "page_number": 2,
                "line_start": 3,
                "line_end": 4,
                "text": "[1] Nguyen, A. (2024). A first study",
            },
            {
                "id": "paragraph-reference-2",
                "section_id": "section-references",
                "page_number": 3,
                "line_start": 1,
                "line_end": 2,
                "text": "with a continued title. doi : 10 . 1000 / ABC . 1",
            },
        ],
    }

    report = citation.parse_citations(document)

    assert len(report.references) == 1
    reference = report.references[0]
    assert reference.doi == "10.1000/abc.1"
    assert reference.anchor_element_ids == (
        "paragraph-reference-1",
        "paragraph-reference-2",
    )
    assert reference.anchor_pages == (2, 3)
    assert (reference.line_start, reference.line_end) == (3, 4)
    assert reference.anchor_line_ranges == (
        ("paragraph-reference-1", 2, 3, 4),
        ("paragraph-reference-2", 3, 1, 2),
    )
    assert report.mentions[0].status == citation.LINKED


def test_missing_heading_uses_uncertain_trailing_reference_fallback() -> None:
    document = {
        "sections": [],
        "paragraphs": [
            {
                "id": "paragraph-body",
                "section_id": None,
                "page_number": 1,
                "text": "The method is cited [1].",
            },
            {
                "id": "paragraph-reference-1",
                "section_id": None,
                "page_number": 3,
                "text": "1. Nguyen, A. (2024). A first study.",
            },
            {
                "id": "paragraph-reference-2",
                "section_id": None,
                "page_number": 3,
                "text": "2. Tran, B. (2023). A second study. arxiv: 2401 . 01234 v 2",
            },
        ],
    }

    report = citation.parse_citations(document)

    assert report.parser_status == citation.PARSER_UNCERTAIN
    assert report.bibliography_status == citation.PARSER_UNCERTAIN
    assert len(report.references) == 2
    assert report.references[1].arxiv_id == "2401.01234v2"
    assert all(
        reference.parser_status == citation.PARSER_UNCERTAIN
        for reference in report.references
    )
    assert report.mentions[0].status == citation.AMBIGUOUS_MAPPING
    assert report.as_dict()["counts"]["bibliography_not_found"] == 0


def test_missing_heading_rejects_numbered_document_structure() -> None:
    report = citation.parse_citations(
        {
            "sections": [],
            "paragraphs": [
                {
                    "id": "dataset",
                    "section_id": None,
                    "page_number": 2,
                    "text": "2. Dataset uses public observations from 2021, 2022.",
                },
                {
                    "id": "source-code",
                    "section_id": None,
                    "page_number": 3,
                    "text": (
                        "3. Source code libraries: "
                        "1. Numpy v1.16.5 2. Pandas v0.25.1"
                    ),
                },
            ],
        }
    )

    assert report.bibliography_status == citation.BIBLIOGRAPHY_NOT_FOUND
    assert report.references == []


def test_zero_based_numeric_intervals_are_not_citation_mentions() -> None:
    report = citation.parse_citations(
        {
            "sections": [{"id": "references", "text": "References", "page_number": 2}],
            "paragraphs": [
                {
                    "id": "body",
                    "section_id": None,
                    "page_number": 1,
                    "text": "Probability w is in [0, 1]. Prior work [1, 2].",
                },
                {
                    "id": "references-body",
                    "section_id": "references",
                    "page_number": 2,
                    "text": (
                        "[1] Nguyen, A. (2024). First study. "
                        "[2] Tran, B. (2023). Second study."
                    ),
                },
            ],
        }
    )

    assert [mention.raw for mention in report.mentions] == ["[1, 2]"]
    assert report.mentions[0].status == citation.LINKED


def test_numeric_marker_bounds_reject_oversized_values_and_ranges() -> None:
    assert citation._expand_numbers("9" * 10_000) is None
    assert citation._expand_numbers("1-100") is None
    assert citation._expand_numbers("9-1") is None
    assert citation._expand_numbers("1-3") == (1, 2, 3)


def test_unsupported_numeric_range_is_parser_uncertain() -> None:
    report = citation.parse_citations(
        {
            "sections": [{"id": "references", "text": "References", "page_number": 2}],
            "paragraphs": [
                {
                    "id": "body",
                    "section_id": None,
                    "page_number": 1,
                    "text": "Prior work [1-100].",
                },
                {
                    "id": "reference",
                    "section_id": "references",
                    "page_number": 2,
                    "text": "[1] Nguyen, A. (2024). First study. Journal.",
                },
            ],
        }
    )

    assert report.mentions[0].parser_status == citation.PARSER_UNCERTAIN
    assert report.mentions[0].status == citation.AMBIGUOUS_MAPPING


def test_citation_entity_counts_are_bounded(monkeypatch) -> None:
    monkeypatch.setattr(citation, "_MAX_MENTIONS", 2)
    monkeypatch.setattr(citation, "_MAX_REFERENCES", 2)
    report = citation.parse_citations(
        {
            "sections": [{"id": "references", "text": "References", "page_number": 2}],
            "paragraphs": [
                {
                    "id": "body",
                    "section_id": None,
                    "page_number": 1,
                    "text": "Prior work [1], [1], and [1].",
                },
                *[
                    {
                        "id": f"reference-{number}",
                        "section_id": "references",
                        "page_number": 2,
                        "text": (
                            f"[{number}] Author, A. (2024). "
                            f"Study {number}. Journal."
                        ),
                    }
                    for number in range(1, 4)
                ],
            ],
        }
    )

    assert len(report.references) == 2
    assert len(report.mentions) == 2
    assert report.parser_status == citation.PARSER_UNCERTAIN
    assert report.references[-1].parser_status != citation.PARSED
    assert report.mentions[-1].parser_status == citation.PARSER_UNCERTAIN
    assert any("truncated" in warning.lower() for warning in report.parser_warnings)


def test_author_year_mentions_report_entity_truncation(monkeypatch) -> None:
    monkeypatch.setattr(citation, "_MAX_MENTIONS", 1)
    report = citation.parse_citations(
        {
            "sections": [{"id": "references", "text": "References", "page_number": 2}],
            "paragraphs": [
                {
                    "id": "body",
                    "section_id": None,
                    "page_number": 1,
                    "text": "Smith (2024) agrees. Smith (2024) confirms.",
                },
                {
                    "id": "reference",
                    "section_id": "references",
                    "page_number": 2,
                    "text": "[1] Smith, A. (2024). First study. Journal.",
                },
            ],
        }
    )

    assert len(report.mentions) == 1
    assert report.mentions[0].parser_status == citation.PARSER_UNCERTAIN
    assert any(
        "mentions truncated" in warning.lower() for warning in report.parser_warnings
    )


def test_numeric_mentions_do_not_link_generated_unnumbered_ordinals() -> None:
    report = citation.parse_citations(
        {
            "sections": [{"id": "references", "text": "References", "page_number": 2}],
            "paragraphs": [
                {
                    "id": "body",
                    "section_id": None,
                    "page_number": 1,
                    "text": "Prior work [1].",
                },
                {
                    "id": "reference",
                    "section_id": "references",
                    "page_number": 2,
                    "text": "Nguyen, A. (2024). First study. Journal.",
                },
            ],
        }
    )

    assert report.references[0].number_explicit is False
    assert report.mentions[0].status == citation.ORPHAN_MENTION


def test_duplicate_explicit_reference_numbers_are_ambiguous() -> None:
    report = citation.parse_citations(
        {
            "sections": [{"id": "references", "text": "References", "page_number": 2}],
            "paragraphs": [
                {
                    "id": "body",
                    "section_id": None,
                    "page_number": 1,
                    "text": "Prior work [1].",
                },
                {
                    "id": "reference-a",
                    "section_id": "references",
                    "page_number": 2,
                    "text": "[1] Nguyen, A. (2024). First study. Journal.",
                },
                {
                    "id": "reference-b",
                    "section_id": "references",
                    "page_number": 2,
                    "text": "[1] Tran, B. (2023). Second study. Journal.",
                },
            ],
        }
    )

    assert report.mentions[0].status == citation.AMBIGUOUS
    assert len(report.mentions[0].reference_ids) == 2


def test_identifier_normalization_accepts_layout_whitespace() -> None:
    assert citation.canonicalize_doi("doi : 10 . 1234 / ABC . 7") == "10.1234/abc.7"
    assert citation.extract_arxiv_id("arxiv . org / abs / 2401 . 01234 v 2") == (
        "2401.01234v2"
    )


def test_doi_canonicalization_preserves_balanced_legacy_punctuation() -> None:
    doi = "10.1002/(SICI)1520-6300(199907/08)11:4<209::AID-AJHB3>3.0.CO;2-C"

    assert citation.canonicalize_doi(f"https://doi.org/{doi}") == doi.casefold()
    assert citation.canonicalize_doi(f"({doi}).") == doi.casefold()


def test_synthetic_fixture_matches_parser_contract() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "citation_parser_fixture.json"
    document = json.loads(fixture_path.read_text(encoding="utf-8"))

    report = citation.parse_citations(document)

    assert report.bibliography_status == citation.PARSED
    assert len(report.references) == 1
    assert report.references[0].anchor_element_ids == (
        "paragraph-2",
        "paragraph-3",
    )


def test_author_year_pdf_splits_merged_bibliography_entries() -> None:
    _document, report = _parse_pdf_fixture("03_author_year.pdf")

    assert [reference.year for reference in report.references] == [2024, 2023, 2022]
    assert len(report.mentions) == 4
    assert all(mention.status == citation.LINKED for mention in report.mentions)


def test_footnote_pdf_preserves_superscript_citation_identity() -> None:
    document, report = _parse_pdf_fixture("04_footnote_citation.pdf")

    body = next(
        paragraph
        for paragraph in document.content["paragraphs"]
        if paragraph.get("superscript_markers")
    )
    marker = body["superscript_markers"][0]
    assert marker["number"] == 1
    assert body["text"][marker["start"] : marker["end"]] == "1"
    assert len(report.references) == 1
    assert report.references[0].raw.startswith("Nguyen, A.")
    assert len(report.mentions) == 1
    assert report.mentions[0].status == citation.LINKED
    assert report.mentions[0].reference_ids == (report.references[0].id,)


def test_complex_layout_pdf_keeps_body_mentions_outside_table() -> None:
    document, report = _parse_pdf_fixture("06_complex_layout.pdf")

    assert len(document.content["tables"]) == 1
    page_one_text = " ".join(
        paragraph["text"]
        for paragraph in document.content["paragraphs"]
        if paragraph["page_number"] == 1
    )
    assert all(marker in page_one_text for marker in ("[1]", "[2]", "[3]"))
    assert len(report.references) == 3
    assert len(report.mentions) == 3
    assert all(mention.status == citation.LINKED for mention in report.mentions)


def test_bibliography_rows_from_layout_table_remain_extractable() -> None:
    document = {
        "sections": [
            {
                "id": "references",
                "text": "References",
                "page_number": 2,
            }
        ],
        "paragraphs": [
            {
                "id": "body",
                "section_id": None,
                "page_number": 1,
                "text": "Prior work [1].",
            }
        ],
        "tables": [
            {
                "id": "table-1",
                "page_start": 2,
                "page_end": 2,
                "rows": [
                    {
                        "page_number": 2,
                        "bbox": {"top": 100},
                        "cells": [{"text": "[1] Author, A. (2024). First study."}],
                    },
                    {
                        "page_number": 2,
                        "bbox": {"top": 120},
                        "cells": [{"text": "[2] Author, B. (2023). Second study."}],
                    },
                ],
            }
        ],
    }

    report = citation.parse_citations(document)

    assert [reference.number for reference in report.references] == [1, 2]
    assert report.mentions[0].status == citation.LINKED
    assert all(reference.element_id == "table-1" for reference in report.references)


def test_unnumbered_bibliography_keeps_separate_entries() -> None:
    document = {
        "sections": [{"id": "references", "text": "Bibliography", "page_number": 2}],
        "paragraphs": [
            {
                "id": "reference-a",
                "section_id": "references",
                "page_number": 2,
                "text": "Nguyen, A. (2024). First study. Journal A.",
            },
            {
                "id": "reference-b",
                "section_id": "references",
                "page_number": 2,
                "text": "Tran, B. (2023). Second study. Journal B.",
            },
        ],
    }

    report = citation.parse_citations(document)

    assert len(report.references) == 2
    assert [reference.year for reference in report.references] == [2024, 2023]
    assert [reference.anchor_element_ids for reference in report.references] == [
        ("reference-a",),
        ("reference-b",),
    ]


def test_grouped_and_narrative_author_year_mentions_link() -> None:
    document = {
        "sections": [{"id": "references", "text": "References", "page_number": 2}],
        "paragraphs": [
            {
                "id": "body",
                "section_id": None,
                "page_number": 1,
                "text": (
                    "(Nguyen & Tran, 2024; Tran, 2023). "
                    "Nguyen and Tran (2024) agree."
                ),
            },
            {
                "id": "reference-a",
                "section_id": "references",
                "page_number": 2,
                "text": "[1] Nguyen, A. (2024). First study.",
            },
            {
                "id": "reference-b",
                "section_id": "references",
                "page_number": 2,
                "text": "[2] Tran, B. (2023). Second study.",
            },
        ],
    }

    report = citation.parse_citations(document)

    author_mentions = [mention for mention in report.mentions if mention.author]
    assert [mention.raw for mention in author_mentions] == [
        "Nguyen & Tran, 2024",
        "Tran, 2023",
        "Nguyen and Tran (2024)",
    ]
    assert all(mention.status == citation.LINKED for mention in author_mentions)


def test_vietnamese_bibliography_heading_variants_are_recognized() -> None:
    headings = (
        "6. TÀI LIỆU THAM KHẢO",
        "Tàiliệuthamkhảo",
        "VII. Nguồn tham khảo:",
        "TÀI LIỆU THAM KHẢO – NGUỒN",
        "Tài liệu",
    )

    for heading in headings:
        report = citation.parse_citations(
            {
                "sections": [{"id": "references", "text": heading, "page_number": 2}],
                "paragraphs": [
                    {
                        "id": "body",
                        "section_id": None,
                        "page_number": 1,
                        "text": "Prior work [1].",
                    },
                    {
                        "id": "reference",
                        "section_id": "references",
                        "page_number": 2,
                        "text": "[1] Nguyen, A. (2024). First study.",
                    },
                ],
            }
        )

        assert report.bibliography_status == citation.PARSED
        assert [reference.number for reference in report.references] == [1]
        assert report.mentions[0].status == citation.LINKED


def test_inline_bullets_and_dashes_split_unnumbered_references() -> None:
    bibliography_rows = (
        (
            "• Amazon, A. (2024). First study. Journal A. "
            "• Sun, B. (2023). Second study. Journal B."
        ),
        (
            "- Poeplau, A. (2021). First study. ACM SIGARCH, vol. 39, no. 1. "
            "ACM, 2011, pp. 265–278. "
            "- Bellard, F. (2005). Second study. USENIX Security 18), 2018."
        ),
    )

    for text in bibliography_rows:
        report = citation.parse_citations(
            {
                "sections": [
                    {"id": "references", "text": "References", "page_number": 2}
                ],
                "paragraphs": [
                    {
                        "id": "references-body",
                        "section_id": "references",
                        "page_number": 2,
                        "text": text,
                    }
                ],
            }
        )

        assert [reference.number for reference in report.references] == [1, 2]
        assert all(
            reference.parser_status == citation.PARSED
            for reference in report.references
        )


def test_page_heading_recovers_bibliography_from_layout_table() -> None:
    report = citation.parse_citations(
        {
            "pages": [
                {"number": 1, "text": "Prior work [1]."},
                {
                    "number": 2,
                    "text": (
                        "Tài liệu tham khảo\n"
                        "[1] Sarmah, B. (2024). Hybrid retrieval."
                    ),
                },
            ],
            "sections": [],
            "paragraphs": [
                {
                    "id": "body",
                    "section_id": None,
                    "page_number": 1,
                    "text": "Prior work [1].",
                }
            ],
            "tables": [
                {
                    "id": "table-1",
                    "page_start": 2,
                    "page_end": 2,
                    "rows": [
                        {
                            "page_number": 2,
                            "cells": [{"text": "Tài liệu tham khảo"}],
                        },
                        {
                            "page_number": 2,
                            "cells": [
                                {"text": ("[1] Sarmah, B. (2024). Hybrid retrieval.")}
                            ],
                        },
                    ],
                }
            ],
        }
    )

    assert report.bibliography_status == citation.PARSED
    assert len(report.references) == 1
    assert report.references[0].element_id == "table-1"
    assert report.mentions[0].status == citation.LINKED


def test_issue_rows_keep_all_continuation_anchors() -> None:
    document = {
        "sections": [{"id": "references", "text": "References", "page_number": 2}],
        "paragraphs": [
            {
                "id": "reference-a",
                "section_id": "references",
                "page_number": 2,
                "line_start": 3,
                "line_end": 4,
                "text": "[1] Nguyen, A. (2024). First study",
            },
            {
                "id": "reference-b",
                "section_id": "references",
                "page_number": 3,
                "line_start": 1,
                "line_end": 2,
                "text": "continued on the next page.",
            },
        ],
    }

    report = citation.parse_citations(document)
    rows = citation._issue_rows(report)

    assert rows
    assert all(
        row[2]
        == (
            ("reference-a", 2, 3, 4),
            ("reference-b", 3, 1, 2),
        )
        for row in rows
    )
