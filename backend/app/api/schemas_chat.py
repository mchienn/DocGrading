from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ALL_COURSES = "all"


class ChatRequest(BaseModel):
    """A single chat turn from the teacher.

    ``course_id``/``assignment_id`` carry the UI's currently selected context
    (see ``ChatView``). The chatbot never guesses this scope from free text -
    it always relies on explicit, authorization-checked identifiers.
    ``course_id`` can be "all" to aggregate data across all teacher's courses.
    ``submission_id`` narrows content questions (RAG) to one submission, e.g.
    when the chat is opened from the Review workspace.
    """

    message: str = Field(min_length=1, max_length=1000)
    # Only a UUID or the literal "all" — any other string is a 422, never a
    # raw value that reaches a UUID column (that used to surface as a 500).
    course_id: uuid.UUID | Literal["all"] | None = None
    assignment_id: uuid.UUID | None = None
    submission_id: uuid.UUID | None = None

    @field_validator("course_id", "assignment_id", "submission_id", mode="before")
    @classmethod
    def _blank_means_unset(cls, value: Any) -> Any:
        # The UI sends "" for an empty <select>; treat it like "not chosen".
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ChatAssignmentOption(BaseModel):
    id: uuid.UUID
    title: str


class Citation(BaseModel):
    """A passage of a student document backing an answer (RAG)."""

    chunk_id: uuid.UUID
    page: int
    page_end: int
    section_path: str | None = None
    excerpt: str
    submission_id: uuid.UUID | None = None
    student_name: str | None = None


class ChatResponse(BaseModel):
    reply: str
    intent: str
    needs_assignment: bool = False
    assignment_options: list[ChatAssignmentOption] | None = None
    # Set when the question is about one submission but none is selected yet.
    needs_submission: bool = False
    citations: list[Citation] | None = None