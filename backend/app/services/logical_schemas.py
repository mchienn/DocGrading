"""Validated LLM response contracts for the logical pipeline."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, create_model


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Decision(StrictModel):
    candidate_index: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=1, max_length=8000)


class SynonymDecision(Decision):
    relation: Literal[
        "same_concept",
        "acronym_expansion",
        "translation_equivalent",
        "instance_of",
        "broader_narrower",
        "same_category",
        "related_but_distinct",
        "different_concept",
        "invalid_definition",
    ]

    @property
    def is_error(self) -> bool:
        return self.relation == "same_concept"


class SynonymReview(StrictModel):
    results: list[SynonymDecision]


class PolysemyDecision(Decision):
    relation: Literal[
        "conflict",
        "same_meaning",
        "role_description",
        "specialization",
        "generalization",
        "related_description",
        "invalid_definition",
    ]

    @property
    def is_error(self) -> bool:
        return self.relation == "conflict"


class PolysemyReview(StrictModel):
    results: list[PolysemyDecision]


class BinaryDecision(Decision):
    is_error: StrictBool


class DataDecision(BinaryDecision):
    relation: Literal[
        "same_fact", "different_context", "insufficient_context", "conflict"
    ]
    severity: Literal["", "minor", "moderate", "major"]


class DataReview(StrictModel):
    results: list[DataDecision]


class LocalDecision(BinaryDecision):
    issue_type: Literal["off_topic", "flow_break", "intrusive_span"]
    severity: Literal["", "minor", "moderate", "major"]


class LocalReview(StrictModel):
    results: list[LocalDecision]


class LogicDecision(StrictModel):
    pair_id: int = Field(ge=0, strict=True)
    status: Literal["VERIFIED", "REJECTED", "UNCERTAIN"]
    type: Literal[
        "CONTRADICTION",
        "DEADLOCK",
        "UNREACHABLE_STATE",
        "PRIVILEGE_ESCALATION",
        "MISSING_PRECONDITION",
        "ORPHAN_ACTION",
        "INVARIANT_VIOLATION",
        "INCOMPLETE_STATE_MACHINE",
        "NONE",
    ]
    severity: Literal["", "minor", "moderate", "major", "critical"]
    reason: str = Field(min_length=1, max_length=8000)
    context: str
    rule_ids: list[str]
    evidence_sufficient: StrictBool
    root_cause: str


class LogicReview(StrictModel):
    results: list[LogicDecision]


class GlobalSummary(StrictModel):
    global_summary: str = Field(min_length=1, max_length=8000)


class GlobalIssue(StrictModel):
    from_section: str
    to_section: str
    issue_type: Literal[
        "topic_discontinuity",
        "missing_dependency",
        "wrong_order",
        "logic_break",
        "orphan_section",
    ]
    severity: Literal["minor", "moderate", "major"]
    reason: str = Field(min_length=1, max_length=8000)


class GlobalTransitionDecision(BinaryDecision):
    issue_type: Literal[
        "",
        "topic_discontinuity",
        "missing_dependency",
        "wrong_order",
        "logic_break",
        "orphan_section",
    ]
    severity: Literal["", "minor", "moderate", "major"]


class GlobalTransitionReview(StrictModel):
    results: list[GlobalTransitionDecision]


class GlobalStructureIssue(StrictModel):
    section: str = Field(min_length=1)
    issue_type: Literal[
        "topic_drift",
        "orphan_section",
        "wrong_order",
        "missing_dependency",
        "discourse_break",
    ]
    severity: Literal["minor", "moderate", "major"]
    reason: str = Field(min_length=1, max_length=8000)


class GlobalStructureReview(StrictModel):
    coherence_issues: list[GlobalStructureIssue]


class Term(StrictModel):
    term: str
    definition: str
    is_acronym: bool


class Statement(StrictModel):
    type: Literal[
        "",
        "PRECONDITION",
        "POSTCONDITION",
        "STATE_TRANSITION",
        "AUTHORIZATION",
        "BUSINESS_RULE",
        "ORDER",
        "TRIGGER_EVENT",
        "EXCEPTION_FLOW",
    ] = ""
    subject: str
    actor: str = ""
    action: str = ""
    condition: str = ""
    result: str = ""
    from_state: str = ""
    to_state: str = ""
    polarity: Literal["", "allow", "deny", "require", "prohibit"] = ""
    relation: Literal["", "before", "after"] = ""
    source_quote: str = ""


class Claim(StrictModel):
    entity: str
    attribute: str
    value: str
    unit: str = ""
    condition: str = ""
    time: str = ""
    population: str = ""
    scope: str = ""
    normalized_value: str | FiniteFloat | None = None
    normalized_unit: str = ""


class MapOutput(StrictModel):
    summary_sentence: str = Field(min_length=1)
    terminology: list[Term] = Field(default_factory=list)
    logic_statements: list[Statement] = Field(default_factory=list)
    data_claims: list[Claim] = Field(default_factory=list)


def map_output_schema(fields):
    """Expose only requested extraction groups, retaining their validation."""
    return create_model(
        "SelectedMapOutput",
        __base__=StrictModel,
        **{
            name: (field.annotation, field)
            for name, field in MapOutput.model_fields.items()
            if name in fields
        },
    )


class Annotation(StrictModel):
    issue_index: int = Field(ge=0)
    description: str = Field(min_length=1, max_length=8000)
    suggestion: str = Field(min_length=1, max_length=2000)
    chunk_indices: list[int]
    quotes: list[str]


class CompactScoredReview(StrictModel):
    score: float = Field(ge=0, le=10, allow_inf_nan=False)
    analysis: str = Field(min_length=1, max_length=8000)


class ScoredReview(CompactScoredReview):
    annotations: list[Annotation] = Field(default_factory=list)
