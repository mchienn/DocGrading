from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """A single chat turn from the teacher.

    ``course_id``/``assignment_id`` carry the UI's currently selected context
    (see ``ChatView``). The chatbot never guesses this scope from free text -
    it always relies on explicit, authorization-checked identifiers.
    """

    message: str = Field(min_length=1, max_length=1000)
    course_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None


class ChatAssignmentOption(BaseModel):
    id: uuid.UUID
    title: str


class ChatResponse(BaseModel):
    reply: str
    intent: str
    needs_assignment: bool = False
    assignment_options: list[ChatAssignmentOption] | None = None