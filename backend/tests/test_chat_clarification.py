from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.schemas_chat import ChatScopeSubmission
from app.core.config import get_settings
from app.models.enums import UserRole
from app.services import chat as chat_service
from app.services.chat import (
    Intent,
    find_named_submissions,
    handle_chat,
    paragraph_highlights,
    submission_option,
)
from app.services.rag import FakeLLMClient
from app.workers.index_document_chunks import index_document_version
from tests.test_t011_review_workspace import _actor, _ids, _seed_graph


def _candidate(name: str, assignment: str = "SRS") -> ChatScopeSubmission:
    return ChatScopeSubmission(
        submission_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        student_name=name,
        student_email=f"{uuid.uuid4().hex[:6]}@x",
        assignment_title=assignment,
        file_name="bao-cao.pdf",
        submitted_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
    )


NGUYEN_AN = _candidate("Nguyễn Văn An")
TRAN_AN = _candidate("Trần Thị An")
BINH = _candidate("Lê Bình")
CANDIDATES = [NGUYEN_AN, TRAN_AN, BINH]


def test_two_students_with_same_given_name_are_ambiguous() -> None:
    matches = find_named_submissions("Tóm tắt bài của An", CANDIDATES)
    assert matches == [NGUYEN_AN, TRAN_AN]


def test_full_name_picks_exactly_one_student() -> None:
    assert find_named_submissions("tóm tắt bài của nguyen van an", CANDIDATES) == [
        NGUYEN_AN
    ]


def test_cued_given_name_without_diacritics_matches() -> None:
    assert find_named_submissions(
        "tim doan noi ve test cua sinh vien Binh", CANDIDATES
    ) == [BINH]


def test_given_name_inside_ordinary_words_is_not_a_match() -> None:
    # "an toàn" contains the word "an" but names nobody.
    assert find_named_submissions("Tìm đoạn nói về an toàn thông tin", CANDIDATES) == []
    assert find_named_submissions("Tóm tắt bài này", CANDIDATES) == []


def test_same_student_in_two_assignments_is_ambiguous_too() -> None:
    srs = _candidate("Phạm Minh", "SRS")
    design = _candidate("Phạm Minh", "Thiết kế")
    assert find_named_submissions("tóm tắt bài của Phạm Minh", [srs, design]) == [
        srs,
        design,
    ]


def test_submission_option_label_tells_candidates_apart() -> None:
    option = submission_option(NGUYEN_AN)
    assert option.id == NGUYEN_AN.submission_id
    assert option.label == "Nguyễn Văn An — SRS"
    assert option.detail == "Nộp 20/09/2026 · bao-cao.pdf"


def test_paragraph_highlights_uses_ir_boxes_and_skips_bad_ones() -> None:
    content = {
        "paragraphs": [
            {"id": "p1", "page_number": 2,
             "bbox": {"x0": 1, "top": 2, "x1": 3, "bottom": 4}},
            {"id": "p2", "page_number": 2, "bbox": {}},
            {"id": "p3", "page_number": "x", "bbox": {"x0": 1, "top": 2,
                                                      "x1": 3, "bottom": 4}},
        ]
    }  # fmt: skip
    highlights = paragraph_highlights(content, ["p1", "p2", "p3", "missing"])
    assert [(h.page, h.bbox.x0, h.bbox.bottom) for h in highlights] == [(2, 1.0, 4.0)]


requires_db = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


def _run(scenario) -> None:
    async def wrapper() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            ids = _ids()
            await _seed_graph(connection, ids)
            # A second teacher's course must never show up as an option.
            await connection.execute(
                text("""
                    INSERT INTO public.courses (
                        id, code, name, term, owner_teacher_id, revision
                    ) VALUES (:id, 'OTHER', 'Lớp khác', '2026', :owner, 1)
                """),
                {"id": uuid.uuid4(), "owner": ids["other_teacher"]},
            )
            await scenario(session, ids)
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(wrapper())


async def _ask(session, ids, message, **scope):
    teacher = _actor(ids["teacher"], "Teacher A", UserRole.TEACHER)
    scope.setdefault("course_id", None)
    scope.setdefault("assignment_id", None)
    return await handle_chat(session, user=teacher, message=message, **scope)


@requires_db
@pytest.mark.parametrize(
    ("message", "course_id"),
    [
        ("Tình hình báo cáo lớp thế nào?", None),
        ("Hôm nay có yêu cầu xem lại nào mới không?", ""),
        ("Tìm đoạn nói về kiểm thử", "all"),
        ("Tóm tắt bài này", None),
    ],
)
def test_missing_course_asks_which_course(message: str, course_id: str | None) -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        response = await _ask(session, ids, message, course_id=course_id)
        assert response.needs_clarification == "course"
        assert response.pending_message == message
        # Only the course this teacher owns — not the other teacher's "OTHER".
        assert [o.id for o in response.clarification_options] == [ids["course"]]

    _run(scenario)


@requires_db
def test_summarize_without_submission_asks_which_submission() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        response = await _ask(session, ids, "Tóm tắt bài này", course_id=ids["course"])
        assert response.needs_clarification == "submission"
        labels = [o.label for o in response.clarification_options]
        assert labels == [
            "Student 1 — Review Assignment",
            "Student 2 — Review Assignment",
            "Student 3 — Review Assignment",
        ]
        assert all(o.detail.startswith("Nộp ") for o in response.clarification_options)

    _run(scenario)


async def _rename_students(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
    for key, name in (("student_1", "Nguyễn Văn An"), ("student_2", "Trần Thị An")):
        await session.execute(
            text("UPDATE public.users SET display_name = :n WHERE id = :id"),
            {"n": name, "id": ids[key]},
        )


@requires_db
def test_duplicate_given_names_ask_which_submission() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await _rename_students(session, ids)
        response = await _ask(
            session, ids, "Tóm tắt bài của An", course_id=ids["course"]
        )
        assert response.needs_clarification == "submission"
        assert {o.id for o in response.clarification_options} == {
            ids["submission_1"],
            ids["submission_2"],
        }
        assert response.pending_message == "Tóm tắt bài của An"

    _run(scenario)


@requires_db
def test_single_match_answers_directly_without_asking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeLLMClient("**Mục tiêu:** ...")
    monkeypatch.setattr(chat_service, "_rag_llm_client", lambda: client)

    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        await _rename_students(session, ids)
        await index_document_version(session, ids["document_1"], None)
        response = await _ask(
            session, ids, "Tóm tắt bài của Nguyễn Văn An", course_id=ids["course"]
        )
        assert response.needs_clarification is None
        assert response.intent == Intent.SUMMARIZE_SUBMISSION
        assert response.reply == "**Mục tiêu:** ..."
        assert len(client.calls) == 1

        # The chosen option re-sent with its id also answers straight away.
        again = await _ask(
            session,
            ids,
            "Tóm tắt bài này",
            course_id=ids["course"],
            submission_id=ids["submission_1"],
        )
        assert again.needs_clarification is None

    _run(scenario)


@requires_db
def test_summary_returns_structured_stats() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        response = await _ask(
            session, ids, "Tình hình báo cáo lớp thế nào?", course_id=ids["course"]
        )
        assert response.needs_clarification is None
        assert response.stats is not None
        assert response.stats.total_students == 3
        assert response.stats.submitted == 3

    _run(scenario)


@requires_db
def test_citations_carry_pdf_highlights() -> None:
    async def scenario(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
        content = json.loads(
            await session.scalar(
                text(
                    "SELECT content::text FROM public.document_irs "
                    "WHERE document_version_id = :v"
                ),
                {"v": ids["document_1"]},
            )
        )
        assert content["paragraphs"][0]["bbox"]
        await index_document_version(session, ids["document_1"], None)
        response = await _ask(
            session,
            ids,
            "Tìm đoạn nói về sensitive",
            submission_id=ids["submission_1"],
        )
        [citation] = response.citations
        assert citation.document_version_id == ids["document_1"]
        assert citation.file_name == "one.pdf"
        assert [(h.page, h.bbox.x0, h.bbox.top) for h in citation.highlights] == [
            (1, 10.0, 20.0)
        ]

    _run(scenario)
