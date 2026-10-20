"""Trusted semantic quality gate (design spec section 7).

Approvals live in a code-owned artifact shipped with the image and changed only by
pull request: never by Admin, API or criterion config. An approval covers one exact
run configuration. Thresholds are re-checked here, so an entry that claims more than
its metrics support never passes. Pure module: no import from semantic_citation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

ARTIFACT_PATH = Path(__file__).with_name("semantic_quality_gates.json")

# Single definition; the benchmark script imports it.
GATE = {
    "human_gold_pairs": 100,
    "double_annotated_fraction": 0.2,
    "pairs": 800,
    "heldout_agreement": 0.95,
    "macro_f1": 0.80,
    "false_accusation": 0.02,
    "hit_at_3": 0.90,
    "structured": 0.99,
}

_Fraction = Annotated[float, Field(ge=0, le=1)]


class RunConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    evaluator_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    prompt_fingerprint: str = Field(min_length=1, max_length=128)
    retrieval_version: str = Field(min_length=1, max_length=128)
    source_ir_version: int = Field(gt=0)
    provider: str = Field(min_length=1, max_length=64)
    protocol: str = Field(min_length=1, max_length=64)
    model_id: str = Field(min_length=1, max_length=256)
    encoder_model: str = Field(min_length=1, max_length=256)
    encoder_fingerprint: str = Field(min_length=1, max_length=128)
    # Query vectors depend on the prefix; the fingerprint covers documents only.
    encoder_query_prefix: str = Field(max_length=256)
    reranker: bool
    # Output budget: a smaller one truncates verdict JSON into manual review.
    max_tokens: int = Field(ge=1, le=1024)


class Benchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture: str = Field(min_length=1, max_length=256)
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_status: str = Field(min_length=1, max_length=64)
    pairs: int = Field(ge=0)
    human_gold_pairs: int = Field(ge=0)
    double_annotated_fraction: _Fraction
    heldout_agreement: _Fraction
    anchor_completeness: _Fraction
    structured_success_rate: _Fraction
    macro_f1: _Fraction
    false_accusation_rate: _Fraction
    hit_at_3: _Fraction
    measured_with: str = Field(min_length=1, max_length=512)
    report: str = Field(min_length=1, max_length=256)
    measured_at: date


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1, max_length=128)
    configuration: RunConfiguration
    benchmark: Benchmark
    approved_by: str | None = Field(default=None, max_length=256)
    approved_at: date | None = None

    @property
    def approved(self) -> bool:
        return bool((self.approved_by or "").strip()) and self.approved_at is not None

    @property
    def meets_thresholds(self) -> bool:
        b = self.benchmark
        verified = (
            b.human_gold_pairs >= GATE["human_gold_pairs"]
            and b.double_annotated_fraction >= GATE["double_annotated_fraction"]
        ) or (
            b.annotation_status == "AI_CONSENSUS"
            and b.pairs >= GATE["pairs"]
            and b.heldout_agreement >= GATE["heldout_agreement"]
        )
        return (
            verified
            and b.anchor_completeness == 1.0
            and b.structured_success_rate >= GATE["structured"]
            and b.macro_f1 >= GATE["macro_f1"]
            and b.false_accusation_rate <= GATE["false_accusation"]
            and b.hit_at_3 >= GATE["hit_at_3"]
        )


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    approvals: list[Any]


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    reason: str
    approval: Approval | None = None


def load_approvals(path: Path | None = None) -> list[Approval]:
    """Valid entries only; a malformed artifact or entry grants nothing."""
    path = path or ARTIFACT_PATH
    try:
        envelope = _Envelope.model_validate(json.loads(path.read_text("utf-8")))
    except (OSError, ValueError):
        logger.warning("semantic gate artifact unreadable or malformed")
        return []
    approvals = []
    for index, raw in enumerate(envelope.approvals):
        try:
            approvals.append(Approval.model_validate(raw))
        except ValidationError:
            logger.warning("semantic gate artifact entry %d is malformed", index)
    return approvals


def decide(
    run: RunConfiguration | None,
    *,
    has_model: bool,
    encoder_failures: int | None,
) -> GateDecision:
    """Gate for one job; encoder_failures is None when no encoder ran."""
    if not has_model:
        return GateDecision(False, "quality gate blocked: no model route for this job")
    if encoder_failures is None:
        return GateDecision(False, "quality gate blocked: encoder missing")
    matches = [a for a in load_approvals() if a.configuration == run]
    entry = next((a for a in matches if a.approved), matches[0] if matches else None)
    if entry is None:
        return GateDecision(
            False, "quality gate blocked: no approved benchmark for this configuration"
        )
    if not entry.approved:
        return GateDecision(
            False, "quality gate blocked: approval pending owner sign-off", entry
        )
    if not entry.meets_thresholds:
        return GateDecision(
            False, "quality gate blocked: benchmark below thresholds", entry
        )
    if encoder_failures:
        return GateDecision(
            False,
            f"quality gate blocked: encoder fell back for {encoder_failures} claims",
            entry,
        )
    return GateDecision(True, f"approved benchmark {entry.approval_id}", entry)
