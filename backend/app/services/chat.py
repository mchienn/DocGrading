"""Rule-based intent engine for the basic teacher chatbot (no RAG, no LLM yet).

Every number the chatbot reports comes straight from a scoped SQL query,
never from free-text "reasoning" by a model, so answers stay exact and
auditable (mirrors the same aggregation used by the submission queue view).
Intent matching is plain keyword/substring matching on a diacritics-stripped,
lowercased copy of the message — there is no external LLM call in this
first version, which keeps it free to run and instant to respond.

Swapping this for an LLM-backed router later only needs a new
``classify_intent``/composer pair; ``handle_chat`` and the DB helpers below
stay the source of truth for numbers either way.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_course_ownership
from app.api.schemas_chat import ChatAssignmentOption, ChatResponse
from app.models.assignment import Assignment
from app.models.course import Course, Membership
from app.models.enums import (
    AssignmentStatus,
    DocumentStatus,
    MembershipRole,
    MembershipStatus,
    ReviewRequestStatus,
)
from app.models.identity import User
from app.models.review import ReviewRequest
from app.models.submission import DocumentVersion, Submission
from app.services.review import _ERROR_STATUSES, _REVIEWED_STATUSES


class Intent(StrEnum):
    SUMMARY = "SUMMARY"
    UNREVIEWED = "UNREVIEWED"
    ERRORS = "ERRORS"
    NOT_SUBMITTED = "NOT_SUBMITTED"
    NEW_REVIEW_REQUESTS = "NEW_REVIEW_REQUESTS"
    GREETING = "GREETING"
    HELP = "HELP"
    NEEDS_COURSE = "NEEDS_COURSE"
    UNKNOWN = "UNKNOWN"


_HELP_TEXT = (
    "Hiện tại mình trả lời được các câu hỏi kiểu:\n"
    '- "Tình hình báo cáo lớp thế nào?"\n'
    '- "Còn bao nhiêu bài chưa duyệt?"\n'
    '- "Những bài nào đang lỗi?"\n'
    '- "Bao nhiêu sinh viên chưa nộp?"\n'
    '- "Hôm nay có yêu cầu xem lại nào mới không?"\n'
    "Chọn lớp (và bài tập nếu cần) ở phía trên rồi hỏi lại nhé."
)


def _strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return without_marks.replace("đ", "d").replace("Đ", "D")


def _normalize(text: str) -> str:
    return _strip_diacritics(text).lower().strip()


# Ordered most-specific-first: NOT_SUBMITTED / NEW_REVIEW_REQUESTS phrases are
# checked before the broader SUMMARY/UNREVIEWED ones so e.g. "chưa nộp" never
# gets swallowed by a looser "chưa duyệt"-style match.
_INTENT_KEYWORDS: list[tuple[Intent, tuple[str, ...]]] = [
    (
        Intent.NOT_SUBMITTED,
        ("chua nop", "sinh vien nao chua nop", "ai chua nop"),
    ),
    (
        Intent.NEW_REVIEW_REQUESTS,
        ("yeu cau xem lai", "xem lai moi", "review request"),
    ),
    (
        Intent.ERRORS,
        ("dang loi", "bi loi", "loi gi", "nhung bai nao loi", "xu ly loi"),
    ),
    (
        Intent.UNREVIEWED,
        ("chua duyet", "can duyet", "chua cham", "chua xem xet"),
    ),
    (
        Intent.SUMMARY,
        (
            "tinh hinh",
            "tong quan",
            "ty le hoan thanh",
            "bao cao lop the nao",
            "tom tat",
        ),
    ),
    (
        Intent.GREETING,
        ("xin chao", "chao ban", "hello", "hi"),
    ),
    (
        Intent.HELP,
        ("giup", "help", "lam duoc gi", "huong dan"),
    ),
]


def _phrase_matches(phrase: str, normalized_text: str) -> bool:
    """Match *phrase* as a whole word/phrase, not as a substring of another word.

    Plain substring matching lets short phrases like "hi" match inside
    unrelated Vietnamese words once diacritics are stripped (e.g. "nghỉ" ->
    "nghi", which contains "hi").
    """
    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
    return re.search(pattern, normalized_text) is not None


def classify_intent(message: str) -> Intent:
    """Map free-text (Vietnamese, diacritics optional) to a fixed intent."""
    normalized = _normalize(message)
    for intent, phrases in _INTENT_KEYWORDS:
        if any(_phrase_matches(phrase, normalized) for phrase in phrases):
            return intent
    return Intent.UNKNOWN


def _authorize(user: User, course: Course | None) -> Course:
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    check_course_ownership(user, course)
    return course


async def _get_teacher_courses(db: AsyncSession, user: User) -> list[Course]:
    """Get all courses owned by teacher."""
    stmt = sa.select(Course).where(Course.owner_teacher_id == user.id)
    return list((await db.execute(stmt)).scalars().all())


async def _handle_summary_all_courses(db: AsyncSession, courses: list[Course]) -> str:
    """Summary across all courses."""
    if not courses:
        return "Bạn chưa có lớp nào."

    parts = []
    for course in courses:
        rows = await _latest_versions(db, course.id, None)
        total = len(rows)
        reviewed = sum(1 for _, status, _ in rows if status in _REVIEWED_STATUSES)
        error = sum(1 for _, status, _ in rows if status in _ERROR_STATUSES)
        students = await _active_student_count(db, course.id)

        if total == 0:
            parts.append(f'Lớp "{course.name}" chưa có bài nộp.')
        else:
            rate = round(reviewed / total * 100)
            parts.append(
                f'Lớp "{course.name}": {rate}% ({reviewed}/{total}) chấm xong, {students} sinh viên hoạt động.'
            )

    return "\n".join(parts)


async def _handle_unreviewed_all_courses(db: AsyncSession, courses: list[Course]) -> str:
    """Unreviewed submissions across all courses."""
    if not courses:
        return "Bạn chưa có lớp nào."

    parts = []
    for course in courses:
        rows = await _latest_versions(db, course.id, None)
        unreviewed = sum(1 for _, status, _ in rows if status not in _REVIEWED_STATUSES and status not in _ERROR_STATUSES)
        parts.append(f'Lớp "{course.name}": {unreviewed} bài chờ duyệt')

    total_unreviewed = sum(int(p.split(": ")[1].split(" ")[0]) for p in parts)
    return f"Tổng cộng {total_unreviewed} bài chờ duyệt:\n" + "\n".join(parts)


async def _handle_errors_all_courses(db: AsyncSession, courses: list[Course]) -> str:
    """Error submissions across all courses."""
    if not courses:
        return "Bạn chưa có lớp nào."

    parts = []
    for course in courses:
        rows = await _latest_versions(db, course.id, None)
        errors = sum(1 for _, status, _ in rows if status in _ERROR_STATUSES)
        if errors > 0:
            parts.append(f'Lớp "{course.name}": {errors} bài lỗi')

    if not parts:
        return "Không có bài nộp nào bị lỗi."

    return "Các bài nộp bị lỗi:\n" + "\n".join(parts)


async def _handle_new_review_requests_all_courses(db: AsyncSession, courses: list[Course]) -> str:
    """New review requests across all courses."""
    if not courses:
        return "Bạn chưa có lớp nào."

    parts = []
    cutoff = datetime.now(UTC) - timedelta(days=1)

    for course in courses:
        stmt = (
            sa.select(sa.func.count())
            .select_from(ReviewRequest)
            .join(Submission, Submission.id == ReviewRequest.submission_id)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(
                Assignment.course_id == course.id,
                ReviewRequest.status == ReviewRequestStatus.SUBMITTED,
                ReviewRequest.created_at >= cutoff,
            )
        )
        count = int(await db.scalar(stmt) or 0)
        if count > 0:
            parts.append(f'Lớp "{course.name}": {count} yêu cầu xem lại mới')

    if not parts:
        return "Không có yêu cầu xem lại mới nào trong 24 giờ qua."

    return "Yêu cầu xem lại mới hôm nay:\n" + "\n".join(parts)


def _latest_version_subquery(
    course_id: uuid.UUID, assignment_id: uuid.UUID | None
) -> sa.Subquery:
    stmt = (
        sa.select(
            DocumentVersion.submission_id,
            sa.func.max(DocumentVersion.version_number).label("version_number"),
        )
        .join(Submission, Submission.id == DocumentVersion.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .where(Assignment.course_id == course_id)
    )
    if assignment_id is not None:
        stmt = stmt.where(Assignment.id == assignment_id)
    return stmt.group_by(DocumentVersion.submission_id).subquery()


async def _latest_versions(
    db: AsyncSession, course_id: uuid.UUID, assignment_id: uuid.UUID | None
) -> list[tuple[uuid.UUID, DocumentStatus, uuid.UUID]]:
    """Return (submission_id, status, student_id) for each latest document version."""
    latest = _latest_version_subquery(course_id, assignment_id)
    stmt = (
        sa.select(Submission.id, DocumentVersion.status, Submission.student_id)
        .join(latest, latest.c.submission_id == Submission.id)
        .join(
            DocumentVersion,
            sa.and_(
                DocumentVersion.submission_id == Submission.id,
                DocumentVersion.version_number == latest.c.version_number,
            ),
        )
    )
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1], row[2]) for row in rows]


def _active_student_filter(course_id: uuid.UUID) -> sa.ColumnElement[bool]:
    return sa.and_(
        Membership.course_id == course_id,
        Membership.role == MembershipRole.STUDENT,
        Membership.status == MembershipStatus.ACTIVE,
    )


async def _active_student_count(db: AsyncSession, course_id: uuid.UUID) -> int:
    stmt = sa.select(sa.func.count()).where(_active_student_filter(course_id))
    return int(await db.scalar(stmt) or 0)


async def _active_student_ids(db: AsyncSession, course_id: uuid.UUID) -> set[uuid.UUID]:
    stmt = sa.select(Membership.user_id).where(_active_student_filter(course_id))
    return set((await db.execute(stmt)).scalars().all())


async def _open_assignments(db: AsyncSession, course_id: uuid.UUID) -> list[Assignment]:
    stmt = (
        sa.select(Assignment)
        .where(
            Assignment.course_id == course_id,
            Assignment.status.in_((AssignmentStatus.OPEN, AssignmentStatus.CLOSED)),
        )
        .order_by(Assignment.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _handle_summary(
    db: AsyncSession, course: Course, assignment_id: uuid.UUID | None
) -> str:
    rows = await _latest_versions(db, course.id, assignment_id)
    total = len(rows)
    reviewed = sum(1 for _, status, _ in rows if status in _REVIEWED_STATUSES)
    error = sum(1 for _, status, _ in rows if status in _ERROR_STATUSES)
    pending = total - reviewed - error
    students = await _active_student_count(db, course.id)
    scope = "lớp" if assignment_id is None else "bài tập đã chọn"
    if total == 0:
        return (
            f'{scope.capitalize()} "{course.name}" chưa có bài nộp nào. '
            f"Lớp có {students} sinh viên đang hoạt động."
        )
    rate = round(reviewed / total * 100)
    return (
        f'Tình hình {scope} "{course.name}":\n'
        f"- Tổng số bài đã nộp: {total} (trên {students} sinh viên đang hoạt động)\n"
        f"- Đã duyệt (approved/published): {reviewed} ({rate}%)\n"
        f"- Đang chờ duyệt/xử lý: {pending}\n"
        f"- Đang lỗi: {error}"
    )


async def _handle_unreviewed(
    db: AsyncSession, course: Course, assignment_id: uuid.UUID | None
) -> str:
    rows = await _latest_versions(db, course.id, assignment_id)
    pending = [
        r
        for r in rows
        if r[1] not in _REVIEWED_STATUSES and r[1] not in _ERROR_STATUSES
    ]
    if not pending:
        return f'Lớp "{course.name}" hiện không còn bài nào chờ duyệt.'
    return (
        f'Còn {len(pending)} bài chưa duyệt ở lớp "{course.name}". '
        "Mở hàng đợi duyệt bài để xử lý tiếp."
    )


async def _handle_errors(
    db: AsyncSession, course: Course, assignment_id: uuid.UUID | None
) -> str:
    rows = await _latest_versions(db, course.id, assignment_id)
    errored = [r for r in rows if r[1] in _ERROR_STATUSES]
    if not errored:
        return f'Không có bài nào đang lỗi ở lớp "{course.name}".'
    return (
        f"Có {len(errored)} bài đang ở trạng thái lỗi (PDF không hợp lệ hoặc xử lý "
        f'thất bại) ở lớp "{course.name}". Mở hàng đợi duyệt bài, lọc theo trạng thái '
        "lỗi để xem chi tiết."
    )


async def _handle_not_submitted(
    db: AsyncSession, course: Course, assignment: Assignment | None
) -> ChatResponse:
    if assignment is None:
        options = await _open_assignments(db, course.id)
        if not options:
            return ChatResponse(
                reply=f'Lớp "{course.name}" chưa có bài tập nào đang mở.',
                intent=Intent.NOT_SUBMITTED,
            )
        return ChatResponse(
            reply=(
                "Câu này cần biết đang hỏi về bài tập nào — chọn một bài tập ở "
                "phía trên rồi hỏi lại nhé."
            ),
            intent=Intent.NOT_SUBMITTED,
            needs_assignment=True,
            assignment_options=[
                ChatAssignmentOption(id=a.id, title=a.title) for a in options
            ],
        )
    rows = await _latest_versions(db, course.id, assignment.id)
    submitted_student_ids = {r[2] for r in rows}
    active_student_ids = await _active_student_ids(db, course.id)
    submitted_active_ids = submitted_student_ids & active_student_ids
    students = len(active_student_ids)
    not_submitted = len(active_student_ids - submitted_active_ids)
    reply = (
        f'Bài tập "{assignment.title}": {not_submitted} trên {students} sinh viên '
        f"chưa nộp bài ({len(submitted_active_ids)} đã nộp)."
    )
    return ChatResponse(reply=reply, intent=Intent.NOT_SUBMITTED)


async def _handle_new_review_requests(db: AsyncSession, course: Course) -> str:
    since = datetime.now(UTC) - timedelta(hours=24)
    stmt = (
        sa.select(sa.func.count())
        .select_from(ReviewRequest)
        .join(Submission, Submission.id == ReviewRequest.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .where(
            Assignment.course_id == course.id,
            ReviewRequest.status == ReviewRequestStatus.OPEN,
            ReviewRequest.created_at >= since,
        )
    )
    count = int(await db.scalar(stmt) or 0)
    if count == 0:
        return (
            f'Không có yêu cầu xem lại mới nào trong 24 giờ qua ở lớp "{course.name}".'
        )
    return (
        f"Có {count} yêu cầu xem lại mới (còn mở) trong 24 giờ qua ở "
        f'lớp "{course.name}".'
    )


async def handle_chat(
    db: AsyncSession,
    *,
    user: User,
    message: str,
    course_id: uuid.UUID | str | None,
    assignment_id: uuid.UUID | None,
) -> ChatResponse:
    """Classify *message* and answer it, scoped to an owned course.

    Numbers always come from a live, authorization-checked query — the
    classifier only decides *which* query to run, never the answer itself.
    If course_id is "all", aggregate data from all teacher's courses.
    """
    intent = classify_intent(message)

    if intent is Intent.GREETING:
        return ChatResponse(
            reply="Chào bạn! Mình là trợ lý hỏi-đáp tình hình chấm bài.\n" + _HELP_TEXT,
            intent=intent,
        )
    if intent in (Intent.HELP, Intent.UNKNOWN):
        prefix = "" if intent is Intent.HELP else "Mình chưa hiểu câu hỏi này.\n"
        return ChatResponse(reply=prefix + _HELP_TEXT, intent=intent)

    if course_id is None:
        return ChatResponse(
            reply=(
                "Bạn chọn một lớp ở phía trên rồi hỏi lại nhé — mỗi câu trả lời cần "
                "gắn với một lớp cụ thể."
            ),
            intent=Intent.NEEDS_COURSE,
        )

    # Handle "all" - aggregate across all teacher's courses
    if course_id == "all":
        courses = await _get_teacher_courses(db, user)
        if not courses:
            return ChatResponse(
                reply="Bạn chưa có lớp nào. Vui lòng tạo lớp trước rồi hỏi lại nhé.",
                intent=Intent.UNKNOWN,
            )
        # Return aggregate summary for all courses
        if intent is Intent.SUMMARY:
            reply = await _handle_summary_all_courses(db, courses)
            return ChatResponse(reply=reply, intent=intent)
        if intent is Intent.UNREVIEWED:
            reply = await _handle_unreviewed_all_courses(db, courses)
            return ChatResponse(reply=reply, intent=intent)
        if intent is Intent.ERRORS:
            reply = await _handle_errors_all_courses(db, courses)
            return ChatResponse(reply=reply, intent=intent)
        if intent is Intent.NEW_REVIEW_REQUESTS:
            reply = await _handle_new_review_requests_all_courses(db, courses)
            return ChatResponse(reply=reply, intent=intent)
        # NOT_SUBMITTED requires specific course
        if intent is Intent.NOT_SUBMITTED:
            return ChatResponse(
                reply="Để kiểm tra sinh viên chưa nộp, bạn cần chọn một lớp cụ thể nhé.",
                intent=Intent.UNKNOWN,
            )
        return ChatResponse(reply=_HELP_TEXT, intent=Intent.UNKNOWN)

    # Single course mode
    course = _authorize(user, await db.get(Course, course_id))

    assignment: Assignment | None = None
    if assignment_id is not None:
        assignment = await db.get(Assignment, assignment_id)
        if assignment is None or assignment.course_id != course.id:
            raise HTTPException(status_code=404, detail="Assignment not found")

    if intent is Intent.SUMMARY:
        reply = await _handle_summary(db, course, assignment_id)
        return ChatResponse(reply=reply, intent=intent)
    if intent is Intent.UNREVIEWED:
        reply = await _handle_unreviewed(db, course, assignment_id)
        return ChatResponse(reply=reply, intent=intent)
    if intent is Intent.ERRORS:
        reply = await _handle_errors(db, course, assignment_id)
        return ChatResponse(reply=reply, intent=intent)
    if intent is Intent.NOT_SUBMITTED:
        return await _handle_not_submitted(db, course, assignment)
    if intent is Intent.NEW_REVIEW_REQUESTS:
        reply = await _handle_new_review_requests(db, course)
        return ChatResponse(reply=reply, intent=intent)

    return ChatResponse(reply=_HELP_TEXT, intent=Intent.UNKNOWN)
