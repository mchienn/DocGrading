from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.services import citation
from app.services.document_ir import PARSER_VERSION, parse_document_ir
from app.services.pdf_validation import validate_pdf

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ANNOTATIONS = (
    _REPO_ROOT / "backend" / "tests" / "fixtures" / "citation_annotations.v0.json"
)
_DEFAULT_REPORT = _REPO_ROOT / "docs" / "benchmarks" / "citation-v0.md"
_REFERENCE_MATCH_THRESHOLD = 0.82


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _score(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalize(left), _normalize(right)).ratio()


def _metric(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        ),
    }


def _binary_metric(
    pairs: Iterable[tuple[str | None, str | None]], target: str
) -> dict[str, float | int]:
    pairs = list(pairs)
    return _metric(
        sum(expected == target and actual == target for expected, actual in pairs),
        sum(expected != target and actual == target for expected, actual in pairs),
        sum(expected == target and actual != target for expected, actual in pairs),
    )


def _ambiguous_status(status: str | None) -> str | None:
    return (
        citation.AMBIGUOUS
        if status in {citation.AMBIGUOUS, citation.AMBIGUOUS_MAPPING}
        else status
    )


def _reference_pages(reference: citation.CitationReference) -> set[int]:
    return set(reference.anchor_pages) or {reference.page_number}


def _match_references(
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[citation.CitationReference],
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    matches: dict[int, int] = {}
    failures: list[dict[str, Any]] = []
    unused = set(range(len(actual)))
    for expected_index, gold in enumerate(expected):
        pages = {int(page) for page in gold.get("pages", ())}
        candidates = [
            (index, _score(str(gold.get("raw", "")), actual[index].raw))
            for index in unused
            if pages & _reference_pages(actual[index])
        ]
        if not candidates:
            failures.append({"kind": "reference_fn", "gold_id": gold.get("id")})
            continue
        actual_index, score = max(candidates, key=lambda item: item[1])
        if score < _REFERENCE_MATCH_THRESHOLD:
            failures.append(
                {
                    "kind": "reference_fn",
                    "gold_id": gold.get("id"),
                    "best_similarity": round(score, 4),
                }
            )
            continue
        matches[expected_index] = actual_index
        unused.remove(actual_index)
    failures.extend(
        {"kind": "reference_fp", "actual_id": actual[index].id}
        for index in sorted(unused)
    )
    return matches, failures


def _match_mentions(
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[citation.CitationMention],
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    matches: dict[int, int] = {}
    failures: list[dict[str, Any]] = []
    unused = set(range(len(actual)))
    for expected_index, gold in enumerate(expected):
        candidates = [
            index
            for index in unused
            if actual[index].page_number == int(gold.get("page", 0))
            and _normalize(actual[index].raw) == _normalize(str(gold.get("raw", "")))
        ]
        if not candidates:
            failures.append({"kind": "mention_fn", "gold_id": gold.get("id")})
            continue
        line_start = gold.get("line_start")
        element_id = str(gold.get("element_id", ""))
        actual_index = min(
            candidates,
            key=lambda index: (
                actual[index].element_id != element_id,
                abs((actual[index].line_start or 0) - (line_start or 0)),
            ),
        )
        matches[expected_index] = actual_index
        unused.remove(actual_index)
    failures.extend(
        {"kind": "mention_fp", "actual_id": actual[index].id}
        for index in sorted(unused)
    )
    return matches, failures


def _unique_documents(
    documents: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    unique: list[Mapping[str, Any]] = []
    for document in documents:
        digest = str(document["document"]["source_sha256"])
        if digest not in seen:
            seen.add(digest)
            unique.append(document)
    return unique


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _corpus_sources_by_hash() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted((_REPO_ROOT / "test_submissions").rglob("*.pdf")):
        result.setdefault(_sha256_file(path), path)
    return result


def _run_corpus(expected_hashes: Sequence[str]) -> dict[str, Any]:
    files = sorted((_REPO_ROOT / "test_submissions").rglob("*.pdf"))
    actual_hashes = [_sha256_file(path) for path in files]
    if Counter(actual_hashes) != Counter(expected_hashes):
        raise ValueError(
            "Issue #36 corpus SHA-256 multiset does not match gold manifest"
        )
    failures: list[dict[str, str]] = []
    citation_counts = Counter()
    started = time.perf_counter()
    for path, digest in zip(files, actual_hashes, strict=True):
        data = path.read_bytes()
        try:
            validate_pdf(data)
            report = citation.parse_citations(parse_document_ir(data))
        except Exception as error:  # benchmark must retain every corpus failure
            failures.append(
                {
                    "sha256_prefix": digest[:12],
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            continue
        citation_counts["references"] += len(report.references)
        citation_counts["mentions"] += len(report.mentions)
        citation_counts["parser_uncertain_documents"] += (
            report.parser_status != citation.PARSED
        )
    return {
        "files": len(files),
        "passed": len(files) - len(failures),
        "failed": len(failures),
        "seconds": time.perf_counter() - started,
        "citation_counts": dict(citation_counts),
        "failures": failures,
    }


def _run_gold(documents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reference_tp = reference_fp = reference_fn = 0
    mention_tp = mention_fp = mention_fn = 0
    bibliography_correct = identifier_correct = identifier_total = 0
    doi_positive = doi_positive_correct = 0
    arxiv_positive = arxiv_positive_correct = 0
    mapping_correct = mapping_total = 0
    mention_status_pairs: list[tuple[str | None, str | None]] = []
    reference_status_pairs: list[tuple[str | None, str | None]] = []
    failures: list[dict[str, Any]] = []
    parse_seconds = 0.0

    unique = _unique_documents(documents)
    sources_by_hash = _corpus_sources_by_hash()
    for document in unique:
        metadata = document["document"]
        digest = str(metadata["source_sha256"])
        path = sources_by_hash.get(digest)
        if path is None:
            raise ValueError(f"Gold source hash missing from corpus: {digest[:12]}")
        data = path.read_bytes()
        started = time.perf_counter()
        actual = citation.parse_citations(parse_document_ir(data))
        parse_seconds += time.perf_counter() - started
        expected_references = document.get("references", ())
        expected_mentions = document.get("mentions", ())
        reference_matches, reference_failures = _match_references(
            expected_references, actual.references
        )
        mention_matches, mention_failures = _match_mentions(
            expected_mentions, actual.mentions
        )
        failures.extend(
            {**failure, "sha256_prefix": digest[:12]}
            for failure in (*reference_failures, *mention_failures)
        )
        reference_tp += len(reference_matches)
        reference_fn += len(expected_references) - len(reference_matches)
        reference_fp += len(actual.references) - len(reference_matches)
        mention_tp += len(mention_matches)
        mention_fn += len(expected_mentions) - len(mention_matches)
        mention_fp += len(actual.mentions) - len(mention_matches)
        bibliography_correct += (
            actual.bibliography_status == document["bibliography"]["status"]
        )

        predicted_to_gold = {
            actual.references[actual_index].id: str(
                expected_references[gold_index]["id"]
            )
            for gold_index, actual_index in reference_matches.items()
        }
        cited_gold_ids = {
            str(reference_id)
            for mention in expected_mentions
            if mention.get("status") == citation.LINKED
            for reference_id in mention.get("reference_ids", ())
        }
        for gold_index, gold_reference in enumerate(expected_references):
            expected_identifiers = gold_reference["expected_identifiers"]
            identifier_total += 1
            doi_positive += expected_identifiers["doi"] is not None
            arxiv_positive += expected_identifiers["arxiv_id"] is not None
            actual_index = reference_matches.get(gold_index)
            if actual_index is None:
                reference_status_pairs.append(
                    (
                        (
                            citation.LINKED
                            if gold_reference["id"] in cited_gold_ids
                            else citation.UNCITED_REFERENCE
                        ),
                        None,
                    )
                )
                continue
            actual_reference = actual.references[actual_index]
            identifiers_match = (
                actual_reference.doi == expected_identifiers["doi"]
                and actual_reference.arxiv_id == expected_identifiers["arxiv_id"]
            )
            identifier_correct += identifiers_match
            doi_positive_correct += (
                expected_identifiers["doi"] is not None
                and actual_reference.doi == expected_identifiers["doi"]
            )
            arxiv_positive_correct += (
                expected_identifiers["arxiv_id"] is not None
                and actual_reference.arxiv_id == expected_identifiers["arxiv_id"]
            )
            reference_status_pairs.append(
                (
                    (
                        citation.LINKED
                        if gold_reference["id"] in cited_gold_ids
                        else citation.UNCITED_REFERENCE
                    ),
                    actual_reference.linkage_status,
                )
            )
        matched_reference_indexes = set(reference_matches.values())
        reference_status_pairs.extend(
            (None, reference.linkage_status)
            for index, reference in enumerate(actual.references)
            if index not in matched_reference_indexes
        )

        for gold_index, gold_mention in enumerate(expected_mentions):
            mapping_total += 1
            actual_index = mention_matches.get(gold_index)
            if actual_index is None:
                mention_status_pairs.append((str(gold_mention["status"]), None))
                continue
            actual_mention = actual.mentions[actual_index]
            mention_status_pairs.append(
                (str(gold_mention["status"]), actual_mention.status)
            )
            mapped_ids = {
                predicted_to_gold.get(reference_id)
                for reference_id in actual_mention.reference_ids
            }
            mapped_ids.discard(None)
            mapping_correct += mapped_ids == set(gold_mention.get("reference_ids", ()))
        matched_mention_indexes = set(mention_matches.values())
        mention_status_pairs.extend(
            (None, mention.status)
            for index, mention in enumerate(actual.mentions)
            if index not in matched_mention_indexes
        )

    return {
        "document_entries": len(documents),
        "unique_documents": len(unique),
        "references": sum(len(document.get("references", ())) for document in unique),
        "mentions": sum(len(document.get("mentions", ())) for document in unique),
        "bibliography_accuracy": bibliography_correct / len(unique) if unique else 0.0,
        "reference_extraction": _metric(reference_tp, reference_fp, reference_fn),
        "mention_extraction": _metric(mention_tp, mention_fp, mention_fn),
        "identifier_exact_accuracy": (
            identifier_correct / identifier_total if identifier_total else 0.0
        ),
        "doi_positive_recall": (
            doi_positive_correct / doi_positive if doi_positive else 0.0
        ),
        "doi_positive_count": doi_positive,
        "arxiv_positive_recall": (
            arxiv_positive_correct / arxiv_positive if arxiv_positive else 0.0
        ),
        "arxiv_positive_count": arxiv_positive,
        "mapping_accuracy": mapping_correct / mapping_total if mapping_total else 0.0,
        "mention_status_pairs": mention_status_pairs,
        "reference_status_pairs": reference_status_pairs,
        "parse_seconds": parse_seconds,
        "failures": failures,
    }


def _reference_from_case(case: Mapping[str, Any]) -> citation.CitationReference:
    raw = str(case["reference"]["raw"])
    return citation.CitationReference(
        id=str(case["name"]),
        number=None,
        raw=raw,
        page_number=1,
        element_id="identity-gold",
        start=0,
        end=len(raw),
        snippet=raw[:240],
        **citation._parse_reference_fields(raw),
    )


def _run_identity(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    status_correct = identifiers_correct = 0
    field_tp = field_fp = field_fn = 0
    status_pairs: list[tuple[str, str | None]] = []
    rows: list[dict[str, Any]] = []
    for case in cases:
        reference = _reference_from_case(case)
        expected = case["expected"]
        actual_status, actual_fields = citation._identity(
            reference, case.get("provider_record")
        )
        expected_fields = set(expected.get("mismatch_fields", ()))
        actual_field_set = set(actual_fields)
        status_correct += actual_status == expected["identity_status"]
        identifiers_match = (
            reference.doi == expected["doi"]
            and reference.arxiv_id == expected["arxiv_id"]
        )
        identifiers_correct += identifiers_match
        field_tp += len(expected_fields & actual_field_set)
        field_fp += len(actual_field_set - expected_fields)
        field_fn += len(expected_fields - actual_field_set)
        status_pairs.append((str(expected["identity_status"]), actual_status))
        rows.append(
            {
                "name": case["name"],
                "expected": expected["identity_status"],
                "actual": actual_status,
                "fields_match": expected_fields == actual_field_set,
                "identifiers_match": identifiers_match,
            }
        )
    mismatch = _binary_metric(status_pairs, citation.METADATA_MISMATCH)
    non_mismatch = sum(
        expected != citation.METADATA_MISMATCH for expected, _ in status_pairs
    )
    mismatch_false_positives = sum(
        expected != citation.METADATA_MISMATCH and actual == citation.METADATA_MISMATCH
        for expected, actual in status_pairs
    )
    return {
        "cases": len(cases),
        "identifier_accuracy": identifiers_correct / len(cases) if cases else 0.0,
        "status_accuracy": status_correct / len(cases) if cases else 0.0,
        "metadata_mismatch": mismatch,
        "field_mismatch": _metric(field_tp, field_fp, field_fn),
        "unresolved_rate": (
            sum(actual == citation.UNRESOLVED for _, actual in status_pairs)
            / len(cases)
            if cases
            else 0.0
        ),
        "metadata_mismatch_false_positive_rate": (
            mismatch_false_positives / non_mismatch if non_mismatch else 0.0
        ),
        "rows": rows,
    }


def _run_linkage_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    mention_pairs: list[tuple[str | None, str | None]] = []
    reference_pairs: list[tuple[str | None, str | None]] = []
    mapping_correct = mapping_total = 0
    rows: list[dict[str, Any]] = []
    for case in cases:
        report = citation.parse_citations(case["document_ir"])
        expected = case["expected"]
        actual_mentions = list(report.mentions)
        for gold in expected["mentions"]:
            mapping_total += 1
            actual = next(
                (
                    mention
                    for mention in actual_mentions
                    if _normalize(mention.raw) == _normalize(str(gold["raw"]))
                ),
                None,
            )
            if actual is not None:
                actual_mentions.remove(actual)
            mention_pairs.append(
                (str(gold["status"]), actual.status if actual is not None else None)
            )
            numbers = sorted(
                reference.number
                for reference in report.references
                if actual is not None and reference.id in actual.reference_ids
            )
            mapping_correct += actual is not None and numbers == sorted(
                gold["reference_numbers"]
            )
        mention_pairs.extend((None, mention.status) for mention in actual_mentions)
        expected_references = list(expected["references"])
        actual_references = list(report.references)
        for gold in expected_references:
            actual = next(
                (
                    reference
                    for reference in actual_references
                    if reference.number == gold["number"]
                ),
                None,
            )
            if actual is not None:
                actual_references.remove(actual)
            reference_pairs.append(
                (
                    str(gold["linkage_status"]),
                    actual.linkage_status if actual is not None else None,
                )
            )
        reference_pairs.extend(
            (None, reference.linkage_status) for reference in actual_references
        )
        rows.append(
            {
                "name": case["name"],
                "parser_status": report.parser_status,
                "mentions": len(report.mentions),
                "references": len(report.references),
            }
        )
    return {
        "mention_status_pairs": mention_pairs,
        "reference_status_pairs": reference_pairs,
        "mapping_correct": mapping_correct,
        "mapping_total": mapping_total,
        "rows": rows,
    }


def _probe_crossref(case: Mapping[str, Any]) -> dict[str, Any]:
    reference = _reference_from_case(case)
    original = citation._crossref_request
    adapter_calls = 0

    def counted(url: str) -> dict[str, Any] | None:
        nonlocal adapter_calls
        adapter_calls += 1
        return original(url)

    with citation._CACHE_LOCK:
        citation._CACHE.clear()
    citation._crossref_request = counted
    started = time.perf_counter()
    try:
        first = citation.resolve_reference(reference)
        first_seconds = time.perf_counter() - started
        second_started = time.perf_counter()
        second = citation.resolve_reference(reference)
        second_seconds = time.perf_counter() - second_started
    finally:
        citation._crossref_request = original
    attempts = 2
    status, fields = citation._identity(reference, first)
    return {
        "case": case["name"],
        "doi": reference.doi,
        "adapter_calls": adapter_calls,
        "resolution_attempts": attempts,
        "cache_hits": max(0, attempts - adapter_calls),
        "cache_hit_rate": max(0, attempts - adapter_calls) / attempts,
        "first_seconds": first_seconds,
        "second_seconds": second_seconds,
        "identity_status": status,
        "mismatch_fields": list(fields),
        "same_external_id": bool(
            first and second and first.get("external_id") == second.get("external_id")
        ),
    }


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _prf_line(name: str, metric: Mapping[str, Any]) -> str:
    return (
        f"| {name} | {metric['tp']} | {metric['fp']} | {metric['fn']} | "
        f"{_pct(metric['precision'])} | {_pct(metric['recall'])} | "
        f"{_pct(metric['f1'])} |"
    )


def _render_report(
    annotations: Mapping[str, Any],
    corpus: Mapping[str, Any],
    gold: Mapping[str, Any],
    identity: Mapping[str, Any],
    linkage: Mapping[str, Any],
    crossref: Mapping[str, Any] | None,
) -> str:
    mention_pairs = [*gold["mention_status_pairs"], *linkage["mention_status_pairs"]]
    reference_pairs = [
        *gold["reference_status_pairs"],
        *linkage["reference_status_pairs"],
    ]
    mapping_correct = (
        gold["mapping_accuracy"] * gold["mentions"] + linkage["mapping_correct"]
    )
    mapping_total = gold["mentions"] + linkage["mapping_total"]
    orphan = _binary_metric(mention_pairs, citation.ORPHAN_MENTION)
    ambiguous = _binary_metric(
        (
            (_ambiguous_status(expected), _ambiguous_status(actual))
            for expected, actual in mention_pairs
        ),
        citation.AMBIGUOUS,
    )
    uncited = _binary_metric(reference_pairs, citation.UNCITED_REFERENCE)
    mention_status_accuracy = (
        sum(expected == actual for expected, actual in mention_pairs)
        / len(mention_pairs)
        if mention_pairs
        else 0.0
    )
    runtime = (
        f"Runtime: Python {platform.python_version()} on "
        f"{platform.system()} {platform.release()}"
    )
    gold_scope = (
        f"- Gold corpus: {gold['document_entries']} file entries, "
        f"{gold['unique_documents']} unique PDF byte sets, "
        f"{gold['references']} bibliography entries, "
        f"{gold['mentions']} citation mentions."
    )
    annotation_note = (
        "- Annotation review: AI-assisted manual; "
        "`independent_human_review=false`. Regression baseline only; "
        "not evaluator activation or domain-review sign-off."
    )
    corpus_result = (
        "- Validation + Document IR + citation parse: "
        f"**{corpus['passed']}/{corpus['files']} passed** "
        f"in {corpus['seconds']:.2f}s."
    )
    corpus_counts = (
        "- Extracted across all corpus files: "
        f"{corpus['citation_counts'].get('references', 0)} references, "
        f"{corpus['citation_counts'].get('mentions', 0)} mentions."
    )
    parser_uncertain = corpus["citation_counts"].get("parser_uncertain_documents", 0)
    identifier_accuracy = _pct(gold["identifier_exact_accuracy"])
    doi_recall = _pct(gold["doi_positive_recall"])
    arxiv_recall = _pct(gold["arxiv_positive_recall"])
    mapping_accuracy = _pct(mapping_correct / mapping_total if mapping_total else 0.0)
    corpus_failures = json.dumps(corpus["failures"], ensure_ascii=False)
    gold_failures = json.dumps(gold["failures"], ensure_ascii=False)
    lines = [
        "# Citation v0 benchmark report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        runtime,
        f"Document IR parser: `{PARSER_VERSION}`",
        "",
        "## Scope",
        "",
        f"- Issue #36 corpus: {corpus['files']} PDF files.",
        gold_scope,
        f"- Identity gold: {identity['cases']} fixed provider cases.",
        (
            f"- Linkage edge gold: {len(annotations['linkage_cases'])} "
            "deterministic cases."
        ),
        annotation_note,
        (
            "- Duplicate PDF bytes count for corpus integration but are "
            "deduplicated by SHA-256 for quality metrics."
        ),
        "- Gold annotations identify source PDFs by SHA-256 only; no paths stored.",
        "",
        "## Corpus integration",
        "",
        corpus_result,
        f"- Failed: {corpus['failed']}.",
        corpus_counts,
        f"- Parser-uncertain documents: {parser_uncertain}.",
        "",
        "## Extraction metrics",
        "",
        (
            "Reference matching requires page overlap and normalized text "
            "similarity >= 0.82. Mention matching requires exact page and "
            "normalized marker text; element ID and line prefer duplicate matches."
        ),
        "",
        "| Metric | TP | FP | FN | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        _prf_line("Bibliography entries", gold["reference_extraction"]),
        _prf_line("Citation mentions", gold["mention_extraction"]),
        "",
        (
            "- Bibliography status accuracy: "
            f"**{_pct(gold['bibliography_accuracy'])}**."
        ),
        f"- DOI/arXiv exact identifier accuracy: **{identifier_accuracy}**.",
        (
            f"- DOI positive recall: **{doi_recall}** "
            f"({gold['doi_positive_count']} positive labels)."
        ),
        (
            f"- arXiv positive recall: **{arxiv_recall}** "
            f"({gold['arxiv_positive_count']} positive labels)."
        ),
        f"- Gold parse time: {gold['parse_seconds']:.2f}s.",
        "",
        "## Identity metrics",
        "",
        (
            "- Identifier extraction accuracy: "
            f"**{_pct(identity['identifier_accuracy'])}**."
        ),
        ("- Identity status accuracy: " f"**{_pct(identity['status_accuracy'])}**."),
        f"- Unresolved rate: **{_pct(identity['unresolved_rate'])}**.",
        (
            "- `METADATA_MISMATCH` false-positive rate: "
            f"**{_pct(identity['metadata_mismatch_false_positive_rate'])}**."
        ),
        "",
        "| Metric | TP | FP | FN | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        _prf_line("Metadata mismatch cases", identity["metadata_mismatch"]),
        _prf_line("Field-level mismatches", identity["field_mismatch"]),
        "",
        "## Linkage metrics",
        "",
        (
            "- Mention-to-reference exact mapping accuracy: "
            f"**{mapping_accuracy}** "
            f"({int(mapping_correct)}/{mapping_total})."
        ),
        ("- Mention linkage-status accuracy: " f"**{_pct(mention_status_accuracy)}**."),
        "",
        "| Metric | TP | FP | FN | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        _prf_line("Orphan mentions", orphan),
        _prf_line("Uncited references", uncited),
        _prf_line("Ambiguous / uncertain mappings", ambiguous),
        "",
        "## Crossref probe",
        "",
    ]
    if crossref is None:
        lines.append(
            "Not run. Use `--live-crossref` for bounded live-provider telemetry."
        )
    else:
        lines.extend(
            [
                f"- DOI: `{crossref['doi']}`.",
                (
                    f"- Adapter calls: {crossref['adapter_calls']} for "
                    f"{crossref['resolution_attempts']} resolver attempts."
                ),
                (
                    f"- Cache hits/rate: {crossref['cache_hits']} / "
                    f"{_pct(crossref['cache_hit_rate'])}."
                ),
                (
                    "- First resolution latency: "
                    f"{crossref['first_seconds']:.3f}s; "
                    f"{'cached' if crossref['cache_hits'] else 'second'} latency: "
                    f"{crossref['second_seconds']:.3f}s."
                ),
                (
                    f"- Live identity result: `{crossref['identity_status']}`; "
                    "cached external ID stable: "
                    f"`{str(crossref['same_external_id']).lower()}`."
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Errors and limits",
            "",
            f"- Corpus failures: {corpus_failures}",
            (
                f"- Gold extraction mismatches: {len(gold['failures'])}; "
                f"SHA-256-prefix details: `{gold_failures}`"
            ),
            (
                "- Live Crossref result is an operational probe, not gold "
                "truth. Offline identity metrics use fixed records."
            ),
            (
                "- No OCR, arbitrary URL fetching, semantic claim support, "
                "or style grading is included."
            ),
            "",
            "## Reproduce",
            "",
            "```bash",
            "cd backend",
            (
                "uv run python scripts/citation_benchmark.py --write-report"
                + (" --live-crossref" if crossref is not None else "")
            ),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def run(*, annotations_path: Path, live_crossref: bool) -> tuple[str, dict[str, Any]]:
    annotations = json.loads(annotations_path.read_text(encoding="utf-8"))
    if annotations.get("schema_version") != 2:
        raise ValueError("citation annotation schema_version must be 2")
    corpus = _run_corpus(annotations["corpus"]["source_sha256"])
    gold = _run_gold(annotations["documents"])
    identity = _run_identity(annotations["identity_cases"])
    linkage = _run_linkage_cases(annotations["linkage_cases"])
    crossref = (
        _probe_crossref(annotations["identity_cases"][0]) if live_crossref else None
    )
    report = _render_report(annotations, corpus, gold, identity, linkage, crossref)
    return report, {
        "corpus": corpus,
        "gold": gold,
        "identity": identity,
        "linkage": linkage,
        "crossref": crossref,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic citation benchmark")
    parser.add_argument("--annotations", type=Path, default=_DEFAULT_ANNOTATIONS)
    parser.add_argument("--report", type=Path, default=_DEFAULT_REPORT)
    parser.add_argument("--live-crossref", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    report, results = run(
        annotations_path=args.annotations.resolve(),
        live_crossref=args.live_crossref,
    )
    if args.write_report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(args.report.resolve())
    else:
        print(report)
    print(
        json.dumps(
            {
                "corpus": {
                    "passed": results["corpus"]["passed"],
                    "files": results["corpus"]["files"],
                },
                "reference_f1": results["gold"]["reference_extraction"]["f1"],
                "mention_f1": results["gold"]["mention_extraction"]["f1"],
                "identity_accuracy": results["identity"]["status_accuracy"],
            },
            sort_keys=True,
        )
    )
    return 0 if results["corpus"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
