from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ALL_COURSES = "all"

ClarificationKind = Literal["course", "assignment", "submission"]


class ChatRequest(BaseModel):
    """A single chat turn from the teacher.

    ``course_id``/``assignment_id`` carry the UI's currently selected context
    (see ``ChatView``). The chatbot never guesses this scope from free text -
    it always relies on explicit, authorization-checked identifiers.
    ``course_id`` can be "all" to aggregate data across all teacher's courses.
    ``submission_id`` narrows content questions (RAG) to one submission, e.g.
    when the chat is opened from the Review workspace.
    ``session_id`` (optional) stores the turn in a saved chat session.
    """

    message: str = Field(min_length=1, max_length=1000)
    # Only a UUID or the literal "all" — any other string is a 422, never a
    # raw value that reaches a UUID column (that used to surface as a 500).
    course_id: uuid.UUID | Literal["all"] | None = None
    assignment_id: uuid.UUID | None = None
    submission_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None

    @field_validator(
        "course_id", "assignment_id", "submission_id", "session_id", mode="before"
    )
    @classmethod
    def _blank_means_unset(cls, value: Any) -> Any:
        # The UI sends "" for an empty <select>; treat it like "not chosen".
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ClarificationOption(BaseModel):
    """One scope the teacher can pick when a question is missing/ambiguous."""

    id: uuid.UUID
    label: str
    detail: str | None = None


class BBox(BaseModel):
    x0: float
    top: float
    x1: float
    bottom: float


class Highlight(BaseModel):
    """A paragraph box to highlight in the PDF viewer (PDF points, top-left)."""

    page: int
    bbox: BBox


class Citation(BaseModel):
    """A passage of a student document backing an answer (RAG)."""

    chunk_id: uuid.UUID
    page: int
    page_end: int
    section_path: str | None = None
    excerpt: str
    submission_id: uuid.UUID | None = None
    student_name: str | None = None
    document_version_id: uuid.UUID | None = None
    file_name: str | None = None
    highlights: list[Highlight] = Field(default_factory=list)


class ChatStats(BaseModel):
    """Live class numbers behind a SUMMARY answer (for the stats card)."""

    total_students: int
    submitted: int
    reviewed: int
    pending_review: int
    errors: int


class OpenDocument(BaseModel):
    """A submission the UI should open (set as scope + show its PDF)."""

    submission_id: uuid.UUID
    document_version_id: uuid.UUID
    label: str
    file_name: str


class ChatResponse(BaseModel):
    reply: str
    intent: str
    # Set when the question needs a narrower scope: the UI shows the options
    # as buttons and re-sends ``pending_message`` with the chosen id. Each
    # request stays stateless — nothing is remembered server-side.
    needs_clarification: ClarificationKind | None = None
    clarification_options: list[ClarificationOption] | None = None
    pending_message: str | None = None
    stats: ChatStats | None = None
    citations: list[Citation] | None = None
    open_document: OpenDocument | None = None
    session_id: uuid.UUID | None = None


class ChatScopeSubmission(BaseModel):
    """A submission the teacher can narrow the chat to ("Phạm vi" picker)."""

    submission_id: uuid.UUID
    document_version_id: uuid.UUID
    student_name: str
    student_email: str
    assignment_title: str
    file_name: str
    submitted_at: datetime


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    title: str
    course_id: uuid.UUID | None
    all_courses: bool
    submission_id: uuid.UUID | None
    is_pinned: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    course_id: uuid.UUID | Literal["all"] | None = None
    submission_id: uuid.UUID | None = None


class ChatSessionUpdate(BaseModel):
    """Only fields present in the body are changed (None clears a scope)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_pinned: bool | None = None
    course_id: uuid.UUID | Literal["all"] | None = None
    submission_id: uuid.UUID | None = None


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    sender: Literal["user", "bot"]
    content: str
    payload: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}
