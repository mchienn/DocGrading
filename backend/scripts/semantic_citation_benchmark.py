"""Stage-wise benchmark and candidate validation for Citation Semantic Support."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.services.citation import (  # noqa: E402
    LINKED,
    PARSED,
    VERIFIED,
    CitationMention,
    CitationReference,
    CitationReport,
)
from app.services.semantic_citation import (  # noqa: E402
    AccessType,
    PassageKind,
    SemanticQualityGateResponse,
    SemanticSource,
    SemanticSourcePassage,
    extract_claim_pairs,
    retrieve_passages,
)

_DEFAULT_ANNOTATIONS = (
    _REPO_ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "semantic_citation_annotations.v0.json"
)
_DEFAULT_REPORT = _REPO_ROOT / "docs" / "benchmarks" / "citation-semantic-v1.md"


def _pct(val: float) -> str:
    return f"{val * 100:.2f}%"


_ALLOWED_VERDICTS = {
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "CONTRADICTED",
    "IRRELEVANT",
    "INSUFFICIENT_EVIDENCE",
    "SOURCE_UNAVAILABLE",
}


def _citation_report(candidate: Mapping[str, Any]) -> CitationReport:
    raw = candidate["citation_report"]
    references = [
        CitationReference(
            id=item["id"],
            number=item.get("number"),
            raw=item["raw"],
            page_number=item.get("page_number", 1),
            element_id=item["element_id"],
            start=item.get("start", 0),
            end=item.get("end", len(item["snippet"])),
            snippet=item["snippet"],
            doi=item.get("doi"),
            arxiv_id=item.get("arxiv_id"),
            title=item.get("title"),
            authors=tuple(item.get("authors", ())),
            year=item.get("year"),
            parser_status=item.get("parser_status", PARSED),
            linkage_status=item.get("linkage_status", ""),
            identity_status=item.get("identity_status", ""),
        )
        for item in raw["references"]
    ]
    mentions = [
        CitationMention(
            id=item["id"],
            raw=item["raw"],
            page_number=item.get("page_number", 1),
            element_id=item["element_id"],
            start=item.get("start", 0),
            end=item.get("end", 0),
            snippet=item["snippet"],
            numbers=tuple(item.get("numbers", ())),
            author=item.get("author"),
            year=item.get("year"),
            status=item.get("status", ""),
            reference_ids=tuple(item.get("reference_ids", ())),
            parser_status=item.get("parser_status", PARSED),
            line_start=item.get("line_start"),
            line_end=item.get("line_end"),
            marker_start=item.get("marker_start"),
            marker_end=item.get("marker_end"),
        )
        for item in raw["mentions"]
    ]
    return CitationReport(
        references=references,
        mentions=mentions,
        parser_status=raw["parser_status"],
        bibliography_status=raw["bibliography_status"],
    )


def _semantic_source(candidate: Mapping[str, Any]) -> SemanticSource:
    resolution = candidate["source_resolution"]
    data = candidate["source_data"]
    descriptor = resolution["source_descriptor"]
    source_id = data["source_id"]
    source_hash = data["source_hash"]
    access = AccessType(resolution["access_type"])
    provenance = descriptor.get("retrieval_provenance", "fixture")
    passages = [
        SemanticSourcePassage(
            passage_id=item["passage_id"],
            source_id=source_id,
            source_hash=source_hash,
            text=item["text"],
            page_number=item.get("page_number"),
            section=item.get("section"),
            element_id=item.get("element_id"),
            kind=PassageKind(item.get("kind", "TEXT")),
            retrieval_provenance=provenance,
            access_type=access,
        )
        for item in data["passages"]
    ]
    return SemanticSource(
        source_id=source_id,
        identifier=data.get("doi") or data.get("arxiv_id"),
        doi=data.get("doi"),
        arxiv_id=data.get("arxiv_id"),
        title=data.get("title"),
        authors=list(data.get("authors", ())),
        source_hash=source_hash,
        retrieved_at="fixture",
        retrieval_provenance=provenance,
        access_type=access,
        passages=passages,
    )


def _expected_pair_specs(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    expected = candidate["expected_extraction"]
    raw_pairs = expected.get("expected_pairs")
    if raw_pairs is None:
        raw_pairs = (
            {
                "mention_id": expected["mention_id"],
                "reference_id": expected["reference_id"],
            },
        )
    return [
        {
            **expected,
            "mention_id": pair["mention_id"],
            "reference_id": pair["reference_id"],
        }
        for pair in raw_pairs
    ]


def _pair_signature(pair: Any) -> tuple[Any, ...]:
    anchor = pair.claim_anchor
    return (
        pair.claim,
        pair.mention_id,
        pair.reference_id,
        pair.extraction_method.value,
        anchor.page_number,
        anchor.element_id,
        anchor.start,
        anchor.end,
    )


def _expected_signature(spec: Mapping[str, Any]) -> tuple[Any, ...]:
    anchor = spec["claim_anchor"]
    return (
        spec["claim_text"],
        spec["mention_id"],
        spec["reference_id"],
        spec["extraction_method"],
        anchor["page_number"],
        anchor["element_id"],
        anchor["start"],
        anchor["end"],
    )


def _multiset_counts(values: Sequence[tuple[Any, ...]]) -> dict[tuple[Any, ...], int]:
    counts: dict[tuple[Any, ...], int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _expected_pairs_for_validation(
    expected: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], bool]:
    raw_pairs = expected.get("expected_pairs")
    if raw_pairs is None:
        return [
            {
                "mention_id": expected.get("mention_id"),
                "reference_id": expected.get("reference_id"),
            }
        ], False
    if (
        not isinstance(raw_pairs, Sequence)
        or isinstance(raw_pairs, (str, bytes))
        or not raw_pairs
        or any(not isinstance(pair, Mapping) for pair in raw_pairs)
    ):
        raise ValueError("expected_extraction.expected_pairs must be a non-empty list")
    return list(raw_pairs), True


def _attribution_metrics(
    correct: int, predicted: int, expected: int
) -> tuple[float, float, float]:
    false_positive = max(0, predicted - correct)
    false_negative = max(0, expected - correct)
    precision_denominator = correct + false_positive
    recall_denominator = correct + false_negative
    precision = correct / precision_denominator if precision_denominator else 0.0
    recall = correct / recall_denominator if recall_denominator else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def validate_fixture(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate checked-in candidate fixture against production contracts."""
    if not isinstance(data, Mapping):
        raise ValueError("Fixture root must be a mapping")
    if data.get("schema_version") != 1:
        raise ValueError(f"Expected schema_version=1, got {data.get('schema_version')}")

    ann_set = data.get("annotation_set")
    if not isinstance(ann_set, Mapping):
        raise ValueError("Missing 'annotation_set' metadata block")
    if ann_set.get("annotation_status") not in {"AI_DRAFT", "SYNTHETIC_DRAFT"}:
        raise ValueError("Invalid annotation_status")
    if ann_set.get("independent_human_review") is not False:
        raise ValueError("independent_human_review must be false in draft fixture")
    if ann_set.get("human_gold_pairs") != 0:
        raise ValueError(
            "human_gold_pairs must be strictly 0, got "
            f"{ann_set.get('human_gold_pairs')}"
        )

    candidates = data.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise ValueError("Missing or invalid 'candidates' list")
    total = len(candidates)
    if not 100 <= total <= 150:
        raise ValueError(f"Candidate count {total} outside required range 100..150")

    seen_ids: set[str] = set()
    seen_passages: set[str] = set()
    vi_en_count = double_review_count = expected_pair_count = 0
    multi_pair_count = 0
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"Candidate item {index} must be a mapping")
        pair_id = candidate.get("pair_id")
        if not isinstance(pair_id, str) or not pair_id.strip():
            raise ValueError(f"Candidate {index} missing valid 'pair_id'")
        if pair_id in seen_ids:
            raise ValueError(f"Duplicate pair_id='{pair_id}' in candidate fixture")
        seen_ids.add(pair_id)
        language_pair = candidate.get("language_pair")
        if language_pair not in {"vi_en", "en_en"}:
            raise ValueError(f"Candidate {pair_id} invalid language_pair")
        if language_pair == "vi_en":
            vi_en_count += 1
        if candidate.get("double_review_required") is True:
            double_review_count += 1

        draft = candidate.get("draft_annotation")
        if not isinstance(draft, Mapping):
            raise ValueError(f"Candidate {pair_id} missing draft_annotation mapping")
        if draft.get("status") != "AI_DRAFT" or not draft.get("provenance"):
            raise ValueError(f"Candidate {pair_id} invalid draft status/provenance")
        if draft.get("verdict") not in _ALLOWED_VERDICTS or not draft.get(
            "reason_code"
        ):
            raise ValueError(f"Candidate {pair_id} invalid draft verdict")

        report = candidate.get("citation_report")
        if not isinstance(report, Mapping):
            raise ValueError(f"Candidate {pair_id} missing citation_report mapping")
        if (
            report.get("parser_status") != PARSED
            or report.get("bibliography_status") != PARSED
        ):
            raise ValueError(f"Candidate {pair_id} citation report not parsed")
        mentions = report.get("mentions")
        references = report.get("references")
        if (
            not isinstance(mentions, Sequence)
            or isinstance(mentions, (str, bytes))
            or not isinstance(references, Sequence)
            or isinstance(references, (str, bytes))
            or any(
                not isinstance(item, Mapping) or not item.get("id") for item in mentions
            )
            or any(
                not isinstance(item, Mapping) or not item.get("id")
                for item in references
            )
        ):
            raise ValueError(f"Candidate {pair_id} citation items invalid")
        refs = {item["id"]: item for item in references}
        if not refs:
            raise ValueError(f"Candidate {pair_id} has no citation references")
        for mention in mentions:
            if (
                not isinstance(mention, Mapping)
                or mention.get("status") != LINKED
                or mention.get("parser_status") != PARSED
                or not mention.get("reference_ids")
            ):
                raise ValueError(f"Candidate {pair_id} has invalid citation mention")
            if any(
                ref_id not in refs
                or refs[ref_id].get("parser_status") != PARSED
                or refs[ref_id].get("identity_status") != VERIFIED
                or refs[ref_id].get("linkage_status") != LINKED
                for ref_id in mention["reference_ids"]
            ):
                raise ValueError(f"Candidate {pair_id} has unverified citation link")

        expected = candidate.get("expected_extraction")
        if not isinstance(expected, Mapping):
            raise ValueError(f"Candidate {pair_id} missing expected_extraction")
        anchor = expected.get("claim_anchor")
        if (
            not isinstance(anchor, Mapping)
            or not expected.get("claim_text")
            or not expected.get("claim_id")
            or expected.get("extraction_method") not in {"SENTENCE", "CLAUSE", "MODEL"}
        ):
            raise ValueError(f"Candidate {pair_id} expected extraction invalid")
        expected_pairs, has_explicit_pairs = _expected_pairs_for_validation(expected)
        if (
            candidate.get("scenario") == "multiple_citations_one_claim"
            and not has_explicit_pairs
        ):
            raise ValueError(
                f"Candidate {pair_id} multi-citation scenario must declare "
                "expected_pairs"
            )
        expected_pair_keys: set[tuple[str, str]] = set()
        for expected_pair in expected_pairs:
            mention_id = expected_pair.get("mention_id")
            reference_id = expected_pair.get("reference_id")
            if (
                not isinstance(mention_id, str)
                or mention_id not in {m.get("id") for m in mentions}
                or not isinstance(reference_id, str)
                or reference_id not in refs
            ):
                raise ValueError(f"Candidate {pair_id} expected pair invalid")
            pair_key = (mention_id, reference_id)
            if pair_key in expected_pair_keys:
                raise ValueError(f"Candidate {pair_id} duplicate expected pair")
            expected_pair_keys.add(pair_key)
        primary_pair = (expected.get("mention_id"), expected.get("reference_id"))
        if primary_pair not in expected_pair_keys:
            raise ValueError(
                f"Candidate {pair_id} primary expected pair missing from expected_pairs"
            )
        if candidate.get("scenario") == "multiple_citations_one_claim":
            linked_pairs = {
                (mention["id"], reference_id)
                for mention in mentions
                for reference_id in mention["reference_ids"]
            }
            if expected_pair_keys != linked_pairs:
                raise ValueError(
                    f"Candidate {pair_id} expected_pairs must cover every linked pair"
                )
        expected_pair_count += len(expected_pairs)
        if len(expected_pairs) > 1:
            multi_pair_count += 1
        for key in ("page_number", "element_id", "start", "end"):
            if key not in anchor:
                raise ValueError(f"Candidate {pair_id} expected anchor missing {key}")
        if (
            not isinstance(anchor["page_number"], int)
            or not isinstance(anchor["element_id"], str)
            or not isinstance(anchor["start"], int)
            or not isinstance(anchor["end"], int)
            or anchor["start"] < 0
            or anchor["end"] <= anchor["start"]
        ):
            raise ValueError(f"Candidate {pair_id} expected anchor invalid")
        expected_retrieval = candidate.get("expected_retrieval")
        evidence_ids = (
            expected_retrieval.get("evidence_passage_ids")
            if isinstance(expected_retrieval, Mapping)
            else None
        )
        draft_evidence = draft.get("evidence_passage_ids", ())
        if (
            not isinstance(evidence_ids, Sequence)
            or isinstance(evidence_ids, (str, bytes))
            or not isinstance(draft_evidence, Sequence)
            or isinstance(draft_evidence, (str, bytes))
            or any(not isinstance(item, str) or not item for item in evidence_ids)
            or any(not isinstance(item, str) or not item for item in draft_evidence)
            or len(evidence_ids) != len(set(evidence_ids))
            or len(draft_evidence) != len(set(draft_evidence))
        ):
            raise ValueError(f"Candidate {pair_id} evidence IDs invalid")

        resolution = candidate.get("source_resolution")
        if not isinstance(resolution, Mapping) or not isinstance(
            resolution.get("source_available"), bool
        ):
            raise ValueError(f"Candidate {pair_id} source_resolution invalid")
        if not resolution["source_available"] and (
            resolution.get("access_type") is not None
            or resolution.get("source_id") is not None
        ):
            raise ValueError(f"Candidate {pair_id} unavailable source metadata invalid")
        source_data = candidate.get("source_data")
        if resolution["source_available"]:
            access = resolution.get("access_type")
            descriptor = resolution.get("source_descriptor")
            if access not in {
                "FULL_TEXT",
                "ABSTRACT_ONLY",
                "USER_PROVIDED",
            } or not isinstance(descriptor, Mapping):
                raise ValueError(f"Candidate {pair_id} source descriptor invalid")
            if (
                descriptor.get("reference_id") != expected["reference_id"]
                or descriptor.get("source_id") != resolution.get("source_id")
                or descriptor.get("access_type") != access
                or not isinstance(source_data, Mapping)
            ):
                raise ValueError(f"Candidate {pair_id} source identity mismatch")
            if (
                source_data.get("source_id") != resolution.get("source_id")
                or source_data.get("access_type") != access
                or not isinstance(source_data.get("passages"), Sequence)
            ):
                raise ValueError(f"Candidate {pair_id} source data invalid")
            source_hash = source_data.get("source_hash")
            if (
                not isinstance(source_hash, str)
                or len(source_hash) != 64
                or any(char not in "0123456789abcdef" for char in source_hash)
            ):
                raise ValueError(f"Candidate {pair_id} source hash invalid")
            local_ids: set[str] = set()
            for passage in source_data["passages"]:
                if (
                    not isinstance(passage, Mapping)
                    or not passage.get("passage_id")
                    or not passage.get("text")
                ):
                    raise ValueError(f"Candidate {pair_id} source passage invalid")
                passage_id = passage["passage_id"]
                if passage_id in local_ids or passage_id in seen_passages:
                    raise ValueError(f"Duplicate source passage_id='{passage_id}'")
                local_ids.add(passage_id)
                seen_passages.add(passage_id)
            evidence = set(evidence_ids) | set(draft_evidence)
            passage_ids = {p["passage_id"] for p in source_data["passages"]}
            for evidence_id in evidence:
                if evidence_id not in passage_ids:
                    raise ValueError(
                        f"Candidate {pair_id} evidence passage "
                        f"'{evidence_id}' not found"
                    )
        elif source_data not in (None, {}):
            raise ValueError(f"Candidate {pair_id} unavailable source has data")

    vi_en_ratio = vi_en_count / total
    double_review_ratio = double_review_count / total
    if vi_en_ratio < 0.80:
        raise ValueError("Vietnamese-English ratio below minimum required 80.0%")
    if double_review_ratio < 0.20 or double_review_count < 24:
        raise ValueError("Double review target below required >=20% (min 24)")
    return {
        "total": total,
        "expected_pair_count": expected_pair_count,
        "multi_pair_candidate_count": multi_pair_count,
        "vi_en_count": vi_en_count,
        "vi_en_ratio": vi_en_ratio,
        "double_review_count": double_review_count,
        "double_review_ratio": double_review_ratio,
    }


def run_stage1_extraction(
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    expected_pair_count = predicted_pair_count = tp = fp = fn = 0
    attribution_correct = 0
    for candidate in candidates:
        expected_specs = _expected_pair_specs(candidate)
        expected_signatures = [_expected_signature(spec) for spec in expected_specs]
        pairs = extract_claim_pairs(
            _citation_report(candidate), candidate["document_ir"]
        )
        predicted_signatures = [_pair_signature(pair) for pair in pairs]
        expected_counts = _multiset_counts(expected_signatures)
        predicted_counts = _multiset_counts(predicted_signatures)
        matches = sum(
            min(expected_counts.get(signature, 0), count)
            for signature, count in predicted_counts.items()
        )
        candidate_expected_count = len(expected_signatures)
        candidate_predicted_count = len(predicted_signatures)
        expected_pair_count += candidate_expected_count
        predicted_pair_count += candidate_predicted_count
        tp += matches
        fp += candidate_predicted_count - matches
        fn += candidate_expected_count - matches
        attribution_correct += matches

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    attribution_precision, attribution_recall, attribution_f1 = _attribution_metrics(
        attribution_correct, predicted_pair_count, expected_pair_count
    )
    return {
        "stage": 1,
        "name": "claim_extraction_and_attribution",
        "candidate_count": len(candidates),
        "total": expected_pair_count,
        "expected_pair_count": expected_pair_count,
        "predicted_pair_count": predicted_pair_count,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "attribution_correct": attribution_correct,
        "attribution_total": expected_pair_count,
        "attribution_precision": attribution_precision,
        "attribution_recall": attribution_recall,
        "attribution_f1": attribution_f1,
        "attribution_accuracy": (
            attribution_correct / expected_pair_count if expected_pair_count else 0.0
        ),
    }


def run_stage2_resolution(
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Stage 2: validate fixture source resolution descriptors."""
    full_text_count = abstract_only_count = unavailable_count = 0
    available_count = correct_source_count = 0
    for candidate in candidates:
        resolution = candidate["source_resolution"]
        if not resolution["source_available"]:
            unavailable_count += 1
            continue
        available_count += 1
        source = _semantic_source(candidate)
        expected = candidate["expected_extraction"]
        reference = next(
            item
            for item in _citation_report(candidate).references
            if item.id == expected["reference_id"]
        )
        descriptor = resolution["source_descriptor"]
        identity_ok = (
            descriptor["reference_id"] == reference.id
            and descriptor["source_id"] == source.source_id
            and descriptor["access_type"] == source.access_type.value
            and source.source_id == resolution["source_id"]
            and source.access_type.value == resolution["access_type"]
        )
        if identity_ok:
            correct_source_count += 1
        if source.access_type is AccessType.FULL_TEXT:
            full_text_count += 1
        elif source.access_type is AccessType.ABSTRACT_ONLY:
            abstract_only_count += 1

    total = len(candidates)
    return {
        "stage": 2,
        "name": "source_resolution_and_availability",
        "total": total,
        "available_count": available_count,
        "correct_source_count": correct_source_count,
        "full_text_count": full_text_count,
        "abstract_only_count": abstract_only_count,
        "unavailable_count": unavailable_count,
        "precision": correct_source_count / available_count if available_count else 1.0,
        "full_text_coverage": full_text_count / total if total else 0.0,
        "abstract_only_rate": abstract_only_count / total if total else 0.0,
        "unavailable_rate": unavailable_count / total if total else 0.0,
    }


def run_stage3_retrieval(
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Stage 3: BM25 retrieval over valid full-text sources."""
    evaluated_count = hit_at_3_count = anchor_top1_correct = 0
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    groups = {
        "cross_lingual": {
            "count": 0,
            "hits": 0,
            "recalls": [],
            "rrs": [],
            "anchors": 0,
        },
        "monolingual": {
            "count": 0,
            "hits": 0,
            "recalls": [],
            "rrs": [],
            "anchors": 0,
        },
    }
    for candidate in candidates:
        resolution = candidate["source_resolution"]
        if (
            not resolution["source_available"]
            or resolution["access_type"] != "FULL_TEXT"
        ):
            continue
        source = _semantic_source(candidate)
        gold_ids = candidate["expected_retrieval"]["evidence_passage_ids"]
        if not gold_ids:
            continue
        evaluated_count += 1
        group = groups[
            "cross_lingual" if candidate["language_pair"] == "vi_en" else "monolingual"
        ]
        group["count"] += 1
        retrieved_ids = [
            item[0].passage_id
            for item in retrieve_passages(
                candidate["expected_extraction"]["claim_text"], source, top_k=3
            )
        ]
        gold = set(gold_ids)
        hit = any(item in gold for item in retrieved_ids)
        if hit:
            hit_at_3_count += 1
            group["hits"] += 1
        recall = len(gold & set(retrieved_ids)) / len(gold)
        recalls.append(recall)
        group["recalls"].append(recall)
        rr = next(
            (1.0 / rank for rank, item in enumerate(retrieved_ids, 1) if item in gold),
            0.0,
        )
        reciprocal_ranks.append(rr)
        group["rrs"].append(rr)
        if retrieved_ids and retrieved_ids[0] in gold:
            anchor_top1_correct += 1
            group["anchors"] += 1

    def mean(values: Sequence[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def group_metrics(group: Mapping[str, Any]) -> dict[str, Any]:
        count = group["count"]
        return {
            "count": count,
            "hit_at_3": group["hits"] / count if count else 0.0,
            "recall_at_3": mean(group["recalls"]),
            "mrr_at_3": mean(group["rrs"]),
            "anchor_top1_accuracy": group["anchors"] / count if count else 0.0,
        }

    return {
        "stage": 3,
        "name": "lexical_passage_retrieval_bm25",
        "evaluated_count": evaluated_count,
        "hit_at_3": hit_at_3_count / evaluated_count if evaluated_count else 0.0,
        "hit_at_3_count": hit_at_3_count,
        "recall_at_3": mean(recalls),
        "mrr_at_3": mean(reciprocal_ranks),
        "anchor_top1_accuracy": (
            anchor_top1_correct / evaluated_count if evaluated_count else 0.0
        ),
        "cross_lingual": group_metrics(groups["cross_lingual"]),
        "monolingual": group_metrics(groups["monolingual"]),
        "note": (
            "Stage 3 measures the BM25 fallback. On this synthetic corpus (five"
            " passages per source) BGE-M3 dense measured lower Hit@3; on real"
            " papers it measured far higher for Vietnamese claims."
        ),
    }


def compute_prediction_metrics(
    candidates: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute accuracy, macro-F1, per-class metrics, confusion matrix, and FAR."""
    gold_map = {
        cand["pair_id"]: cand["draft_annotation"]["verdict"] for cand in candidates
    }
    missing_ids = set(gold_map) - set(predictions)
    extra_ids = set(predictions) - set(gold_map)
    if missing_ids:
        raise ValueError(
            f"Predictions missing {len(missing_ids)} candidate IDs (e.g."
            f" {sorted(missing_ids)[:3]})"
        )
    if extra_ids:
        raise ValueError(f"Predictions contain {len(extra_ids)} unknown candidate IDs")

    gold_labels: list[str] = []
    pred_labels: list[str] = []

    for pair_id, gold_verdict in gold_map.items():
        raw_pred = predictions[pair_id]
        if isinstance(raw_pred, Mapping):
            pred_verdict = str(raw_pred.get("verdict", ""))
        else:
            pred_verdict = str(raw_pred)
        if not pred_verdict:
            raise ValueError(f"Empty prediction verdict for pair_id='{pair_id}'")
        if pred_verdict not in _ALLOWED_VERDICTS:
            raise ValueError(
                f"Invalid prediction verdict '{pred_verdict}' for pair_id='{pair_id}'"
            )
        gold_labels.append(gold_verdict)
        pred_labels.append(pred_verdict)

    classes = sorted(list(set(gold_labels) | set(pred_labels)))
    per_class: dict[str, Any] = {}

    for cls in classes:
        tp = sum(
            g == cls and p == cls for g, p in zip(gold_labels, pred_labels, strict=True)
        )
        fp = sum(
            g != cls and p == cls for g, p in zip(gold_labels, pred_labels, strict=True)
        )
        fn = sum(
            g == cls and p != cls for g, p in zip(gold_labels, pred_labels, strict=True)
        )
        support = sum(g == cls for g in gold_labels)

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

        per_class[cls] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "support": support,
        }

    gold_classes = [cls for cls in classes if per_class[cls]["support"] > 0]
    macro_f1 = (
        sum(per_class[cls]["f1"] for cls in gold_classes) / len(gold_classes)
        if gold_classes
        else 0.0
    )
    accuracy = (
        sum(g == p for g, p in zip(gold_labels, pred_labels, strict=True))
        / len(gold_labels)
        if gold_labels
        else 0.0
    )

    # Confusion matrix
    matrix = {g_cls: {p_cls: 0 for p_cls in classes} for g_cls in classes}
    for g, p in zip(gold_labels, pred_labels, strict=True):
        matrix[g][p] += 1

    # False accusation rate: actual SUPPORTED or PARTIALLY_SUPPORTED
    # predicted as CONTRADICTED or IRRELEVANT
    supported_actual = sum(
        g in {"SUPPORTED", "PARTIALLY_SUPPORTED"} for g in gold_labels
    )
    false_accusations = sum(
        g in {"SUPPORTED", "PARTIALLY_SUPPORTED"}
        and p in {"CONTRADICTED", "IRRELEVANT"}
        for g, p in zip(gold_labels, pred_labels, strict=True)
    )
    false_acc_rate = (
        false_accusations / supported_actual if supported_actual > 0 else 0.0
    )

    return {
        "status": "MEASURED_AGAINST_DRAFT_LABELS",
        "total": len(gold_labels),
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "false_accusation_rate": false_acc_rate,
        "per_class": per_class,
        "confusion_matrix": matrix,
        "classes": classes,
    }


def evaluate_quality_gate(
    fixture_summary: Mapping[str, Any],
    stage1: Mapping[str, Any],
    stage2: Mapping[str, Any],
    stage3: Mapping[str, Any],
    stage4: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Quality gate decision and blocker ledger."""
    human_gold = 0
    double_annotated_fraction = 0.0
    domain_approved = False

    blockers: list[str] = [
        (
            "human_gold_pairs=0 (<100 threshold required for production"
            " promotion). Current set is synthetic draft candidates."
        ),
        (
            "double_annotated_fraction=0.0% (<20.0% threshold required). Double"
            " review target designated but not completed."
        ),
        (
            "domain_approved=false. Expert domain review and signed off criteria"
            " required."
        ),
        "verdict / e2e accuracy is unmeasured against human ground truth.",
    ]

    gate = SemanticQualityGateResponse(
        passed=False,
        reason=(
            "quality gate blocked: human_gold_pairs=0 (<100),"
            " double_annotated_fraction=0.0 (<0.20), domain_approved=false,"
            " verdict unmeasured"
        ),
        human_gold_pairs=human_gold,
        double_annotated_fraction=double_annotated_fraction,
        anchor_completeness=stage1.get("attribution_accuracy", 0.0),
        domain_approved=domain_approved,
    )

    return {
        "passed": False,
        "gate": gate.model_dump(mode="json"),
        "blockers": blockers,
        "verdict_evaluation_status": stage4.get("status") if stage4 else "NOT_MEASURED",
    }


def render_markdown_report(
    ann_set: Mapping[str, Any],
    fixture_summary: Mapping[str, Any],
    scenario_counts: Mapping[str, int],
    stage1: Mapping[str, Any],
    stage2: Mapping[str, Any],
    stage3: Mapping[str, Any],
    stage4: Mapping[str, Any] | None,
    stage5: Mapping[str, Any],
    gate_result: Mapping[str, Any],
    predictions_path: Path | None = None,
) -> str:
    """Render comprehensive baseline benchmark report."""
    lines = [
        "# Citation Semantic Support v1 Benchmark Report",
        "",
        f"Generated: {stage5['timestamp']}",
        f"Runtime: Python {platform.python_version()} on {platform.system()}"
        f" {platform.release()}",
        "Benchmark Suite: `backend/scripts/semantic_citation_benchmark.py`",
        "",
        "## Quality Gate Outcome",
        "",
        "- Status: **BLOCKED**",
        "- Passed: `false`",
        f"- Reason: `{gate_result['gate']['reason']}`",
        "",
        "### Quality Gate Blockers",
        "",
    ]

    for idx, blocker in enumerate(gate_result["blockers"], 1):
        lines.append(f"{idx}. **{blocker.split('.')[0]}**: {blocker}")

    lines.extend(
        [
            "",
            "## Candidate Dataset Composition",
            "",
            f"- Total Candidate Pairs: **{fixture_summary['total']}**",
            (
                "- Annotation Status:"
                f" `{ann_set.get('annotation_status', 'AI_DRAFT')}`"
                " (Candidate set for annotation workbook; not human ground"
                " truth)."
            ),
            (
                "- Independent Human Review:"
                f" `{str(ann_set.get('independent_human_review', False)).lower()}`"
            ),
            f"- Human Gold Pairs: **{ann_set.get('human_gold_pairs', 0)}**",
            "- Language Distribution:",
            (
                "  - Vietnamese Claim / English Source (`vi_en`):"
                f" **{fixture_summary['vi_en_count']} /"
                f" {fixture_summary['total']}**"
                f" ({_pct(fixture_summary['vi_en_ratio'])} - target >="
                " 80.0%)."
            ),
            (
                "  - Monolingual English (`en_en`):"
                f" **{fixture_summary['total'] - fixture_summary['vi_en_count']} /"
                f" {fixture_summary['total']}**"
                f" ({_pct(1.0 - fixture_summary['vi_en_ratio'])})."
            ),
            (
                "- Double Review Flagged:"
                f" **{fixture_summary['double_review_count']} /"
                f" {fixture_summary['total']}**"
                f" ({_pct(fixture_summary['double_review_ratio'])} - target >="
                " 20.0%)."
            ),
            "",
            "### Scenario Breakdown",
            "",
            "| Scenario | Description / Fault Injected | Candidate Count |",
            "|---|---|---:|",
        ]
    )

    scenario_descs = {
        "direct_support": "Direct semantic alignment and textual support",
        "can_cannot_negation": "Polarity inversion / can vs cannot negation",
        "numeric_mismatch": ("Discrepancy in numeric metrics or quantitative results"),
        "added_unsupported_fact": ("True statement bundled with unverified assertion"),
        "concept_switch": "Swapped entity, algorithm, or metric definition",
        "partial_to_whole_exaggeration": (
            "Overgeneralization from narrow benchmark to universal claim"
        ),
        "omitted_condition": (
            "Omission of prerequisite hardware, dataset, or assumption"
        ),
        "suggests_to_proves": (
            "Upgrading preliminary correlation/hypothesis to absolute proof"
        ),
        "related_unsupported": (
            "Domain overlap without support for specific assertion"
        ),
        "irrelevant": "Completely unrelated research domain or topic",
        "multiple_citations_one_claim": (
            "Multiple citation markers within single sentence scope"
        ),
        "multiple_claims_one_citation": (
            "Multiple sentences referencing single citation source"
        ),
        "table_evidence": (
            "Evidence situated in structured table row rather than prose"
        ),
        "abstract_only": (
            "Source restricted to abstract-only metadata (fails verification)"
        ),
        "source_unavailable": "Source unindexed, proprietary, or unavailable",
    }

    for sc_name, count in scenario_counts.items():
        desc = scenario_descs.get(sc_name, sc_name)
        lines.append(f"| `{sc_name}` | {desc} | {count} |")

    lines.extend(
        [
            "",
            "## Stage 1: Claim Extraction & Citation Scope Attribution",
            "",
            (
                f"- Expected claim-reference pairs: **{stage1['expected_pair_count']}**"
                f" across {stage1['candidate_count']} candidates"
            ),
            (
                "*Note: Evaluated against candidate draft spans"
                " [DRAFT/SYNTHETIC - NOT HUMAN VALIDATED]*"
            ),
            "",
            (
                "- Claim extraction precision:"
                f" **{_pct(stage1['precision'])}**"
                f" ({stage1['tp']}/{stage1['tp'] + stage1['fp']})"
            ),
            (
                "- Claim extraction recall:"
                f" **{_pct(stage1['recall'])}**"
                f" ({stage1['tp']}/{stage1['tp'] + stage1['fn']})"
            ),
            f"- Claim extraction F1: **{_pct(stage1['f1'])}**",
            (
                "- Citation-scope attribution accuracy:"
                f" **{_pct(stage1['attribution_accuracy'])}**"
                f" ({stage1['attribution_correct']}/{stage1['attribution_total']})"
            ),
            "",
            "| Metric | TP | FP | FN | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|---:|---:|",
            (
                f"| Claim Extraction | {stage1['tp']} | {stage1['fp']} |"
                f" {stage1['fn']} | {_pct(stage1['precision'])} |"
                f" {_pct(stage1['recall'])} | {_pct(stage1['f1'])} |"
            ),
            (
                f"| Citation Attribution | {stage1['attribution_correct']} |"
                f" {stage1['predicted_pair_count'] - stage1['attribution_correct']} |"
                f" {stage1['expected_pair_count'] - stage1['attribution_correct']} |"
                f" {_pct(stage1['attribution_precision'])} |"
                f" {_pct(stage1['attribution_recall'])} |"
                f" {_pct(stage1['attribution_f1'])} |"
            ),
            "",
            "## Stage 2: Source Resolution & Availability",
            "",
            (
                "*Note: Offline resolution from self-contained candidate"
                " descriptors without live network or external resolvers.*"
            ),
            "",
            (
                "- Available Sources Resolved:"
                f" **{stage2['correct_source_count']} /"
                f" {stage2['available_count']}** ({_pct(stage2['precision'])})"
            ),
            (
                "- Full-text access coverage:"
                f" **{_pct(stage2['full_text_coverage'])}**"
                f" ({stage2['full_text_count']}/{stage2['total']})"
            ),
            (
                "- Abstract-only rate:"
                f" **{_pct(stage2['abstract_only_rate'])}**"
                f" ({stage2['abstract_only_count']}/{stage2['total']})"
            ),
            (
                "- Source unavailable rate:"
                f" **{_pct(stage2['unavailable_rate'])}**"
                f" ({stage2['unavailable_count']}/{stage2['total']})"
            ),
            "",
            "| Source Category | Count | Proportion | Resolution Outcome |",
            "|---|---:|---:|---|",
            (
                f"| Full-Text Indexed | {stage2['full_text_count']} |"
                f" {_pct(stage2['full_text_coverage'])} | Resolved (passages"
                " indexed) |"
            ),
            (
                f"| Abstract-Only | {stage2['abstract_only_count']} |"
                f" {_pct(stage2['abstract_only_rate'])} | Resolved (abstract"
                " paragraph) |"
            ),
            (
                f"| Unavailable / Unindexed | {stage2['unavailable_count']} |"
                f" {_pct(stage2['unavailable_rate'])} | Handled"
                " (`SOURCE_UNAVAILABLE`) |"
            ),
            "",
            "## Stage 3: Lexical Passage Retrieval (BM25)",
            "",
            (
                "*Note: Evaluated on 104 full-text candidates with anchored"
                " source passages. This stage measures the BM25 fallback used"
                " when no encoder is configured. BGE-M3 dense measured 91.35%"
                " Hit@3 here versus 93.27% for BM25, but each synthetic source has"
                " only five passages; on real arXiv papers dense retrieval is far"
                " ahead for Vietnamese claims (see"
                " `docs/benchmarks/bge-m3-retrieval-2026-09-24.md`).*"
            ),
            "",
            f"- Evaluated Candidates: **{stage3['evaluated_count']}**",
            (
                f"- Hit@3: **{_pct(stage3['hit_at_3'])}**"
                f" ({stage3['hit_at_3_count']}/{stage3['evaluated_count']})"
            ),
            f"- Recall@3: **{_pct(stage3['recall_at_3'])}**",
            f"- Mean Reciprocal Rank (MRR@3): **{stage3['mrr_at_3']:.3f}**",
            (
                "- Evidence Anchor Top-1 Accuracy:"
                f" **{_pct(stage3['anchor_top1_accuracy'])}**"
            ),
            "",
            "### Subgroup Analysis",
            "",
            "| Subset | Count | Hit@3 | Recall@3 | MRR@3 | Anchor Top-1 Acc |",
            "|---|---:|---:|---:|---:|---:|",
            (
                f"| Overall Full-Text | {stage3['evaluated_count']} |"
                f" {_pct(stage3['hit_at_3'])} | {_pct(stage3['recall_at_3'])} |"
                f" {stage3['mrr_at_3']:.3f} |"
                f" {_pct(stage3['anchor_top1_accuracy'])} |"
            ),
            (
                f"| Cross-Lingual (`vi_en`) | {stage3['cross_lingual']['count']} |"
                f" {_pct(stage3['cross_lingual']['hit_at_3'])} |"
                f" {_pct(stage3['cross_lingual']['recall_at_3'])} |"
                f" {stage3['cross_lingual']['mrr_at_3']:.3f} |"
                f" {_pct(stage3['cross_lingual']['anchor_top1_accuracy'])} |"
            ),
            (
                f"| Monolingual (`en_en`) | {stage3['monolingual']['count']} |"
                f" {_pct(stage3['monolingual']['hit_at_3'])} |"
                f" {_pct(stage3['monolingual']['recall_at_3'])} |"
                f" {stage3['monolingual']['mrr_at_3']:.3f} |"
                f" {_pct(stage3['monolingual']['anchor_top1_accuracy'])} |"
            ),
            "",
            "## Stage 4: Prediction & Verdict Classification",
            "",
        ]
    )

    if stage4 is None or stage4.get("status") == "NOT_MEASURED":
        lines.extend(
            [
                "- Status: `NOT_MEASURED`",
                "- Predictions file: None supplied (`--predictions` not specified).",
                (
                    "- Note: Verdict accuracy, Macro-F1, Confusion Matrix, and"
                    " False Accusation Rate are strictly NOT_MEASURED without"
                    " predictions. Metrics are never fabricated."
                ),
            ]
        )
    else:
        lines.extend(
            [
                f"- Status: `{stage4['status']}`",
                f"- Evaluated Pairs: **{stage4['total']}**",
                f"- Overall Accuracy: **{_pct(stage4['accuracy'])}**",
                f"- Macro-F1: **{_pct(stage4['macro_f1'])}**",
                f"- False Accusation Rate: **{_pct(stage4['false_accusation_rate'])}**",
                "",
                "### Per-Class Performance",
                "",
                "| Class | Support | TP | FP | FN | Precision | Recall | F1 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for cls, m in stage4["per_class"].items():
            lines.append(
                f"| `{cls}` | {m['support']} | {m['tp']} | {m['fp']} |"
                f" {m['fn']} | {_pct(m['precision'])} | {_pct(m['recall'])} |"
                f" {_pct(m['f1'])} |"
            )

        lines.extend(
            [
                "",
                "### Confusion Matrix",
                "",
                f"| Gold \\ Pred | {' | '.join(f'`{c}`' for c in stage4['classes'])} |",
                f"|---|{'---:|' * len(stage4['classes'])}",
            ]
        )
        for g_cls in stage4["classes"]:
            row_vals = [
                str(stage4["confusion_matrix"][g_cls][p_cls])
                for p_cls in stage4["classes"]
            ]
            lines.append(f"| `{g_cls}` | {' | '.join(row_vals)} |")

    lines.extend(
        [
            "",
            "## Stage 5: End-to-End System Performance & Telemetry",
            "",
            "- Verdict E2E Accuracy: **NOT_MEASURED**",
            "- Teacher Acceptance Rate: **NOT_MEASURED**",
            "- Teacher Override Rate: **NOT_MEASURED**",
            (
                "- Benchmark Execution Latency:"
                f" **{stage5['elapsed_seconds']:.3f}s**"
                f" ({stage5['ms_per_pair']:.2f} ms/candidate pair across"
                " Stages 1-3)"
            ),
            f"- Model API Calls: **{stage5['model_calls']}**",
            f"- Input Tokens: **{stage5['input_tokens']}**",
            f"- Output Tokens: **{stage5['output_tokens']}**",
            "- Model Cost: **null** ($0.00)",
            "",
            "## Errors and Known Limits",
            "",
            (
                "1. **No Human Semantic Gold**: Current dataset is a synthetic"
                " AI draft set (`human_gold_pairs=0`). Accuracy numbers must"
                " not be claimed until independent double annotation by"
                " domain experts is conducted."
            ),
            (
                "2. **Encoder Retrieval Not Scored Here**: Configured deployments"
                " rank passages with the shared encoder instead of BM25. Its"
                " measurements on this corpus and on real papers are in"
                " `docs/benchmarks/bge-m3-retrieval-2026-09-24.md`."
            ),
            (
                "3. **Abstract-Only Denial**: Under security policy,"
                " abstract-only sources fail semantic verification"
                " (`INSUFFICIENT_EVIDENCE`), denying ungrounded claims by"
                " default."
            ),
            (
                "4. **No Live Network / AWS**: Benchmark executes 100% offline"
                " without live network, PDF parser subprocesses, or Bedrock"
                " API calls."
            ),
            "",
            "## Reproduce",
            "",
            "```bash",
            "cd backend",
            "uv run python scripts/semantic_citation_benchmark.py --write-report",
            "```",
            "",
            "With predictions:",
            "",
            "```bash",
            "cd backend",
            (
                "uv run python scripts/semantic_citation_benchmark.py"
                " --predictions path/to/predictions.json --write-report"
            ),
            "```",
            "",
        ]
    )

    return "\n".join(lines)


def run_benchmark(
    annotations_path: Path,
    predictions_path: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run full stage-wise benchmark and return report and results dict."""
    start_time = time.perf_counter()

    if not annotations_path.exists():
        raise FileNotFoundError(f"Annotations file not found: {annotations_path}")

    raw_data = json.loads(annotations_path.read_text(encoding="utf-8"))
    fixture_summary = validate_fixture(raw_data)
    candidates = raw_data["candidates"]
    ann_set = raw_data["annotation_set"]

    scenario_counts: dict[str, int] = {}
    for c in candidates:
        sc = c.get("scenario", "direct_support")
        scenario_counts[sc] = scenario_counts.get(sc, 0) + 1

    stage1 = run_stage1_extraction(candidates)
    stage2 = run_stage2_resolution(candidates)
    stage3 = run_stage3_retrieval(candidates)

    stage4 = None
    if predictions_path is not None:
        if not predictions_path.exists():
            raise FileNotFoundError(f"Predictions file not found: {predictions_path}")
        raw_preds = json.loads(predictions_path.read_text(encoding="utf-8"))
        stage4 = compute_prediction_metrics(candidates, raw_preds)

    elapsed = time.perf_counter() - start_time
    ms_per_pair = (elapsed / len(candidates) * 1000.0) if candidates else 0.0
    stage5 = {
        "stage": 5,
        "name": "system_performance_and_telemetry",
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "elapsed_seconds": elapsed,
        "ms_per_pair": ms_per_pair,
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "model_cost": None,
    }

    gate_result = evaluate_quality_gate(fixture_summary, stage1, stage2, stage3, stage4)

    report = render_markdown_report(
        ann_set,
        fixture_summary,
        scenario_counts,
        stage1,
        stage2,
        stage3,
        stage4,
        stage5,
        gate_result,
        predictions_path=predictions_path,
    )

    results = {
        "schema_version": 1,
        "timestamp": stage5["timestamp"],
        "fixture_summary": fixture_summary,
        "scenario_counts": scenario_counts,
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "stage4": stage4 or {"status": "NOT_MEASURED"},
        "stage5": stage5,
        "stages": {
            "stage1": stage1,
            "stage2": stage2,
            "stage3": stage3,
            "stage4": stage4,
            "stage5": stage5,
        },
        "quality_gate": gate_result,
    }

    return report, results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Citation Semantic Support benchmark and candidate validation"
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        default=_DEFAULT_ANNOTATIONS,
        help="Path to semantic citation annotations JSON fixture",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="Optional path to model predictions JSON mapping pair_id to verdict",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to save full results JSON",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help=f"Write output markdown report to default {_DEFAULT_REPORT}",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=_DEFAULT_REPORT,
        help="Path to write report markdown if --write-report is set",
    )

    args = parser.parse_args()

    try:
        report_md, results = run_benchmark(
            annotations_path=args.annotations,
            predictions_path=args.predictions,
        )
    except Exception as exc:
        print(f"Benchmark run failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(report_md)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nWrote full results JSON to: {args.output_json}")

    if args.write_report:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(report_md, encoding="utf-8")
        print(f"\nWrote benchmark report markdown to: {args.report_path}")


if __name__ == "__main__":
    main()
