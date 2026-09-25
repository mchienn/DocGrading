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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_course_ownership
from app.api.schemas_chat import ALL_COURSES, ChatResponse, Citation
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
from app.services.embeddings import (
    EmbeddingNotConfiguredError,
    EmbeddingProvider,
    get_embedding_provider,
)
from app.services.rag import (
    LLMClient,
    LLMNotConfiguredError,
    RetrievedChunk,
    answer_with_citations,
    get_llm_client,
    make_excerpt,
    retrieve_chunks,
    summarize_document,
)
from app.services.review import _ERROR_STATUSES, _REVIEWED_STATUSES


class Intent(StrEnum):
    SUMMARY = "SUMMARY"
    UNREVIEWED = "UNREVIEWED"
    ERRORS = "ERRORS"
    NOT_SUBMITTED = "NOT_SUBMITTED"
    NEW_REVIEW_REQUESTS = "NEW_REVIEW_REQUESTS"
    SEARCH_CONTENT = "SEARCH_CONTENT"
    ASK_ABOUT_REQUIREMENT = "ASK_ABOUT_REQUIREMENT"
    SUMMARIZE_SUBMISSION = "SUMMARIZE_SUBMISSION"
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
    '- "Tìm đoạn nói về kiểm thử đơn vị" (tìm trong nội dung bài nộp)\n'
    '- "Bài này có đề cập đến kiểm thử bảo mật không?" (hỏi về nội dung)\n'
    '- "Tóm tắt bài này" (khi đang mở một bài nộp)\n'
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
# SEARCH_CONTENT goes first: its trigger ("tìm đoạn ...") is explicit, while the
# topic that follows is free text that may contain other intents' keywords
# (e.g. "tìm đoạn nói về xử lý lỗi" must not become ERRORS).
_INTENT_KEYWORDS: list[tuple[Intent, tuple[str, ...]]] = [
    (
        Intent.SEARCH_CONTENT,
        (
            "tim doan",
            "tim cac doan",
            "tim noi dung",
            "tim trong bai",
            "doan nao noi",
            "trang nao noi",
            "cho nao noi",
            "trich doan",
        ),
    ),
    # Content questions answered by the LLM composer; after SEARCH_CONTENT so
    # "tìm đoạn nói về ..." stays a cheap, LLM-free search.
    (
        Intent.ASK_ABOUT_REQUIREMENT,
        (
            "co de cap",
            "co noi ve",
            "co nhac den",
            "co trinh bay",
            "co mo ta",
            "co dap ung",
            "dap ung yeu cau",
            "trinh bay nhu the nao",
            "trinh bay the nao",
            "mo ta nhu the nao",
            "giai thich nhu the nao",
            "su dung phuong phap",
            "dung phuong phap",
            "su dung cong nghe",
            "dung cong nghe",
            "bai nay noi gi",
        ),
    ),
    # One-submission summary; must precede SUMMARY, whose bare "tóm tắt" would
    # otherwise turn "tóm tắt bài này" into a class-status summary.
    (
        Intent.SUMMARIZE_SUBMISSION,
        (
            "tom tat bai nay",
            "tom tat bai nop",
            "tom tat bai lam",
            "tom tat bao cao nay",
            "tom tat noi dung",
            "tom tat tai lieu",
        ),
    ),
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


# Phrases that introduce the topic of a content search; everything after the
# first match is the topic ("tìm đoạn nói về <topic>").
_TOPIC_MARKERS: tuple[tuple[str, ...], ...] = (
    ("noi", "ve"),
    ("lien", "quan", "den"),
    ("lien", "quan", "toi"),
    ("de", "cap", "den"),
    ("de", "cap", "toi"),
    ("nhac", "den"),
    ("nhac", "toi"),
    ("ve",),
)
# Trigger words stripped from the front when no marker is present.
_SEARCH_FILLER = frozenset(
    {"tim", "cac", "doan", "noi", "dung", "trong", "bai", "trich", "nao",
     "trang", "cho", "giup", "minh", "hay", "hon"}
)  # fmt: skip
# Trailing scope words ("... trong bài này") that are not part of the topic.
_TRAILING_SCOPE = frozenset(
    {"trong", "cua", "bai", "nay", "do", "lop", "sinh", "vien",
     "khong", "chua", "nhu", "the", "nao"}
)  # fmt: skip
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def extract_search_topic(message: str) -> str:
    """Pull the searched-for topic out of a SEARCH_CONTENT question.

    Works on the original words (keeping diacritics, which full-text search
    needs) while matching markers on their diacritics-stripped form.
    """
    words = _WORD_RE.findall(message)
    folded = [_normalize(word) for word in words]
    start: int | None = None
    for marker in _TOPIC_MARKERS:
        size = len(marker)
        for index in range(len(folded) - size + 1):
            if tuple(folded[index : index + size]) == marker:
                start = index + size
                break
        if start is not None:
            break
    if start is None:
        start = 0
        while start < len(folded) and folded[start] in _SEARCH_FILLER:
            start += 1
    end = len(words)
    while end > start and folded[end - 1] in _TRAILING_SCOPE:
        end -= 1
    return " ".join(words[start:end])


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
                ReviewRequest.status == ReviewRequestStatus.OPEN,
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


# Long rosters are cut so one chat bubble stays readable.
NOT_SUBMITTED_NAME_LIMIT = 30


@dataclass(frozen=True)
class MissingSubmissions:
    assignment_title: str
    closed: bool
    student_names: list[str]


def format_not_submitted(
    course_name: str, student_count: int, rows: list[MissingSubmissions]
) -> str:
    """Per-assignment list of active students with no submission yet."""
    if not rows:
        return f'Lớp "{course_name}" chưa có bài tập nào được giao.'
    lines = [f'Lớp "{course_name}" ({student_count} sinh viên đang hoạt động):']
    for row in rows:
        label = f'Bài tập "{row.assignment_title}"' + (
            " (đã đóng)" if row.closed else ""
        )
        missing = len(row.student_names)
        if missing == 0:
            lines.append(f"• {label}: tất cả sinh viên đã nộp.")
            continue
        lines.append(f"• {label}: {missing}/{student_count} sinh viên chưa nộp:")
        shown = row.student_names[:NOT_SUBMITTED_NAME_LIMIT]
        lines.extend(f"   - {name}" for name in shown)
        if missing > len(shown):
            lines.append(f"   … và {missing - len(shown)} sinh viên khác.")
    return "\n".join(lines)


async def _active_students(db: AsyncSession, course_id: uuid.UUID) -> list[User]:
    stmt = (
        sa.select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(_active_student_filter(course_id))
        .order_by(User.display_name, User.email)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _not_submitted_reply(
    db: AsyncSession, course: Course, assignment: Assignment | None
) -> str:
    if assignment is not None:
        assignments = [assignment]
    else:
        assignments = await _open_assignments(db, course.id)
    students = await _active_students(db, course.id)
    rows = []
    for item in assignments:
        submitted = {r[2] for r in await _latest_versions(db, course.id, item.id)}
        rows.append(
            MissingSubmissions(
                assignment_title=item.title,
                closed=item.status is AssignmentStatus.CLOSED,
                student_names=[
                    f"{student.display_name} ({student.email})"
                    for student in students
                    if student.id not in submitted
                ],
            )
        )
    return format_not_submitted(course.name, len(students), rows)


async def _handle_not_submitted(
    db: AsyncSession, course: Course, assignment: Assignment | None
) -> ChatResponse:
    reply = await _not_submitted_reply(db, course, assignment)
    return ChatResponse(reply=reply, intent=Intent.NOT_SUBMITTED)


async def _handle_not_submitted_all_courses(
    db: AsyncSession, courses: list[Course]
) -> str:
    if not courses:
        return "Bạn chưa có lớp nào."
    return "\n\n".join([await _not_submitted_reply(db, c, None) for c in courses])


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


_RAG_INTENTS = frozenset(
    {
        Intent.SEARCH_CONTENT,
        Intent.ASK_ABOUT_REQUIREMENT,
        Intent.SUMMARIZE_SUBMISSION,
    }
)


class RagScope:
    """Authorized set of document versions a content question may read."""

    def __init__(
        self,
        course: Course,
        version_ids: list[uuid.UUID],
        submission: Submission | None,
    ) -> None:
        self.course = course
        self.version_ids = version_ids
        self.submission = submission

    @property
    def label(self) -> str:
        return "bài nộp này" if self.submission else f'lớp "{self.course.name}"'


async def _latest_version_id(
    db: AsyncSession, submission_id: uuid.UUID
) -> uuid.UUID | None:
    stmt = (
        sa.select(DocumentVersion.id)
        .where(DocumentVersion.submission_id == submission_id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


async def _resolve_rag_scope(
    db: AsyncSession,
    *,
    user: User,
    course_id: uuid.UUID | str | None,
    assignment_id: uuid.UUID | None,
    submission_id: uuid.UUID | None,
) -> RagScope | ChatResponse:
    """Narrowest scope wins: submission > assignment > course.

    Every branch goes through ``_authorize`` (course ownership) — a teacher
    guessing a submission_id from another course gets the same 404 as for a
    missing one. Returns a ChatResponse when the UI has not given enough scope.
    """
    if submission_id is not None:
        submission = await db.get(Submission, submission_id)
        if submission is None:
            raise HTTPException(status_code=404, detail="Submission not found")
        assignment = await db.get(Assignment, submission.assignment_id)
        course = _authorize(
            user, await db.get(Course, assignment.course_id) if assignment else None
        )
        if isinstance(course_id, uuid.UUID) and course_id != course.id:
            raise HTTPException(status_code=404, detail="Submission not found")
        if assignment_id is not None and assignment_id != submission.assignment_id:
            raise HTTPException(status_code=404, detail="Submission not found")
        latest = await _latest_version_id(db, submission.id)
        return RagScope(course, [latest] if latest else [], submission)

    if course_id is None or course_id == ALL_COURSES:
        return ChatResponse(
            reply=(
                "Câu hỏi về nội dung bài nộp cần một lớp cụ thể (hoặc mở một bài "
                "nộp) — chọn lớp ở phía trên rồi hỏi lại nhé."
            ),
            intent=Intent.NEEDS_COURSE,
        )
    course = _authorize(user, await db.get(Course, course_id))
    if assignment_id is not None:
        assignment = await db.get(Assignment, assignment_id)
        if assignment is None or assignment.course_id != course.id:
            raise HTTPException(status_code=404, detail="Assignment not found")
    latest = _latest_version_subquery(course.id, assignment_id)
    stmt = sa.select(DocumentVersion.id).join(
        latest,
        sa.and_(
            DocumentVersion.submission_id == latest.c.submission_id,
            DocumentVersion.version_number == latest.c.version_number,
        ),
    )
    version_ids = list((await db.execute(stmt)).scalars().all())
    return RagScope(course, version_ids, None)


def _rag_embedding_provider() -> EmbeddingProvider | None:
    try:
        return get_embedding_provider()
    except EmbeddingNotConfiguredError:
        return None


async def _citations_for(
    db: AsyncSession, chunks: list[RetrievedChunk], query: str
) -> list[Citation]:
    version_ids = {chunk.document_version_id for chunk in chunks}
    owners = {
        row[0]: (row[1], row[2])
        for row in (
            await db.execute(
                sa.select(DocumentVersion.id, Submission.id, User.display_name)
                .join(Submission, Submission.id == DocumentVersion.submission_id)
                .join(User, User.id == Submission.student_id)
                .where(DocumentVersion.id.in_(version_ids))
            )
        ).all()
    }
    citations = []
    for chunk in chunks:
        submission_id, student_name = owners.get(
            chunk.document_version_id, (None, None)
        )
        citations.append(
            Citation(
                chunk_id=chunk.id,
                page=chunk.page_start,
                page_end=chunk.page_end,
                section_path=chunk.section_path,
                excerpt=make_excerpt(chunk.text, query),
                submission_id=submission_id,
                student_name=student_name,
            )
        )
    return citations


def _page_label(citation: Citation) -> str:
    if citation.page_end != citation.page:
        return f"Trang {citation.page}–{citation.page_end}"
    return f"Trang {citation.page}"


async def _handle_search_content(
    db: AsyncSession, scope: RagScope, message: str
) -> ChatResponse:
    topic = extract_search_topic(message)
    if not topic:
        return ChatResponse(
            reply='Bạn muốn tìm đoạn nói về gì? Ví dụ: "Tìm đoạn nói về kiểm thử".',
            intent=Intent.SEARCH_CONTENT,
        )
    if not scope.version_ids:
        return ChatResponse(
            reply=f"Chưa có bài nộp nào trong {scope.label} để tìm.",
            intent=Intent.SEARCH_CONTENT,
        )
    chunks = await retrieve_chunks(
        db, scope.version_ids, topic, provider=_rag_embedding_provider()
    )
    if not chunks:
        return ChatResponse(
            reply=f'Không tìm thấy đoạn nào nói về "{topic}" trong {scope.label}.',
            intent=Intent.SEARCH_CONTENT,
            citations=[],
        )
    citations = await _citations_for(db, chunks, topic)
    lines = [f'Các đoạn liên quan đến "{topic}" trong {scope.label}:']
    for position, citation in enumerate(citations, start=1):
        where = _page_label(citation)
        if citation.section_path:
            where += f", mục “{citation.section_path}”"
        if scope.submission is None and citation.student_name:
            where = f"{citation.student_name} — {where}"
        lines.append(f"{position}. {where}:\n   “{citation.excerpt}”")
    return ChatResponse(
        reply="\n".join(lines),
        intent=Intent.SEARCH_CONTENT,
        citations=citations,
    )


def _rag_llm_client() -> LLMClient:
    return get_llm_client()


def _fallback_excerpt_lines(citations: list[Citation]) -> list[str]:
    return [
        f"{position}. {_page_label(citation)}: “{citation.excerpt}”"
        for position, citation in enumerate(citations, start=1)
    ]


async def _handle_ask_about_requirement(
    db: AsyncSession, scope: RagScope, message: str
) -> ChatResponse:
    intent = Intent.ASK_ABOUT_REQUIREMENT
    if not scope.version_ids:
        return ChatResponse(
            reply=f"Chưa có bài nộp nào trong {scope.label} để trả lời.",
            intent=intent,
        )
    query = extract_search_topic(message) or message
    chunks = await retrieve_chunks(
        db, scope.version_ids, query, provider=_rag_embedding_provider()
    )
    if not chunks:
        return ChatResponse(
            reply=f"Không tìm thấy nội dung liên quan trong {scope.label}.",
            intent=intent,
            citations=[],
        )
    try:
        answer = await answer_with_citations(message, chunks, _rag_llm_client())
    except LLMNotConfiguredError as exc:
        # No key yet: still useful — hand back the retrieved passages verbatim.
        citations = await _citations_for(db, chunks, query)
        reply = "\n".join(
            [
                f"Chưa soạn được câu trả lời tự động ({exc}). "
                "Các đoạn liên quan nhất:",
                *_fallback_excerpt_lines(citations),
            ]
        )
        return ChatResponse(reply=reply, intent=intent, citations=citations)
    citations = await _citations_for(db, answer.citations, query)
    return ChatResponse(reply=answer.text, intent=intent, citations=citations)


async def _handle_summarize_submission(
    db: AsyncSession, scope: RagScope
) -> ChatResponse:
    intent = Intent.SUMMARIZE_SUBMISSION
    if not scope.version_ids:
        return ChatResponse(reply="Bài nộp này chưa có tài liệu nào.", intent=intent)
    try:
        summary = await summarize_document(
            db, scope.version_ids[0], _rag_llm_client()
        )
    except LLMNotConfiguredError as exc:
        return ChatResponse(
            reply=f"Chưa tóm tắt được bài này: {exc}.",
            intent=intent,
        )
    if summary is None:
        return ChatResponse(
            reply=(
                "Bài nộp này chưa được xử lý xong (chưa có nội dung để tóm tắt). "
                "Thử lại sau ít phút nhé."
            ),
            intent=intent,
        )
    return ChatResponse(reply=summary.text, intent=intent)


def normalize_course_id(
    course_id: uuid.UUID | str | None,
) -> uuid.UUID | Literal["all"] | None:
    """Blank -> None, "all" stays, anything else must be a UUID (else 422)."""
    if course_id is None or isinstance(course_id, uuid.UUID):
        return course_id
    value = course_id.strip()
    if not value:
        return None
    if value.lower() == ALL_COURSES:
        return ALL_COURSES
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid course_id") from None


async def handle_chat(
    db: AsyncSession,
    *,
    user: User,
    message: str,
    course_id: uuid.UUID | str | None,
    assignment_id: uuid.UUID | None,
    submission_id: uuid.UUID | None = None,
) -> ChatResponse:
    """Classify *message* and answer it, scoped to an owned course.

    Numbers always come from a live, authorization-checked query — the
    classifier only decides *which* query to run, never the answer itself.
    If course_id is "all", aggregate data from all teacher's courses.
    """
    course_id = normalize_course_id(course_id)
    intent = classify_intent(message)

    if intent is Intent.GREETING:
        return ChatResponse(
            reply="Chào bạn! Mình là trợ lý hỏi-đáp tình hình chấm bài.\n" + _HELP_TEXT,
            intent=intent,
        )
    if intent in (Intent.HELP, Intent.UNKNOWN):
        prefix = "" if intent is Intent.HELP else "Mình chưa hiểu câu hỏi này.\n"
        return ChatResponse(reply=prefix + _HELP_TEXT, intent=intent)

    if intent is Intent.SUMMARIZE_SUBMISSION and submission_id is None:
        return ChatResponse(
            reply=(
                "Để tóm tắt, mình cần biết bài nộp nào — mở bài đó trong màn hình "
                "duyệt bài rồi hỏi lại nhé."
            ),
            intent=intent,
            needs_submission=True,
        )

    if intent in _RAG_INTENTS:
        scope = await _resolve_rag_scope(
            db,
            user=user,
            course_id=course_id,
            assignment_id=assignment_id,
            submission_id=submission_id,
        )
        if isinstance(scope, ChatResponse):
            return scope
        if intent is Intent.ASK_ABOUT_REQUIREMENT:
            return await _handle_ask_about_requirement(db, scope, message)
        if intent is Intent.SUMMARIZE_SUBMISSION:
            return await _handle_summarize_submission(db, scope)
        return await _handle_search_content(db, scope, message)

    if course_id is None:
        return ChatResponse(
            reply=(
                "Bạn chọn một lớp ở phía trên rồi hỏi lại nhé — mỗi câu trả lời cần "
                "gắn với một lớp cụ thể."
            ),
            intent=Intent.NEEDS_COURSE,
        )

    # Handle "all" - aggregate across all teacher's courses
    if course_id == ALL_COURSES:
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
        if intent is Intent.NOT_SUBMITTED:
            reply = await _handle_not_submitted_all_courses(db, courses)
            return ChatResponse(reply=reply, intent=intent)
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
