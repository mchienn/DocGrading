from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import check_course_ownership
from app.api.schemas_course import (
    CourseMemberAddRequest,
    CourseMemberAddResponse,
    CourseMemberRemoveRequest,
    CourseMemberResponse,
)
from app.core.config import get_settings
from app.main import create_app
from app.models.analysis import AnalysisJob
from app.models.course import Course, Membership
from app.models.enums import (
    CourseStatus,
    MembershipAddOutcome,
    MembershipJoinedVia,
    MembershipRole,
    MembershipStatus,
    NotificationType,
    UserRole,
)
from app.models.identity import User
from app.models.submission import Submission
from app.services import analysis_job as job_service
from app.services import course as course_service
from app.services import notification as notification_service
from app.services import review as review_service
from app.services import submission as submission_service
from app.services.operations import _AUDIT_SAFE_FIELDS
from tests.test_t011_review_workspace import (
    _actor,
    _cleanup_graph,
    _ids,
    _seed_graph,
)


class _Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalar_one(self) -> object:
        return self.value

    def all(self) -> list[object]:
        return self.value  # type: ignore[return-value]


class _DB:
    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.added: list[object] = []

    async def execute(self, _statement: object) -> _Result:
        return _Result(self.results.pop(0))

    async def flush(self) -> None:
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def delete(self, _value: object) -> None:
        return None


def _course(course_id: uuid.UUID) -> Course:
    return Course(
        id=course_id,
        code="CS101",
        name="Course",
        term="2026",
        status=CourseStatus.ACTIVE,
        owner_teacher_id=uuid.uuid4(),
    )


def _user(email: str, *, student: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        display_name="Student",
        password_hash="hash",
        roles=[UserRole.STUDENT] if student else [UserRole.TEACHER],
    )


def test_roster_openapi_and_request_contract() -> None:
    schema = create_app().openapi()
    path = schema["paths"]["/api/v1/courses/{course_id}/members"]
    assert set(path) >= {"get", "post"}
    delete = schema["paths"]["/api/v1/courses/{course_id}/members/{user_id}"]["delete"]
    assert "requestBody" in delete
    assert all(
        parameter["name"] != "reason" for parameter in delete.get("parameters", [])
    )
    member = schema["components"]["schemas"]["CourseMemberResponse"]
    assert set(member["properties"]) == {
        "id",
        "user_id",
        "email",
        "display_name",
        "status",
        "joined_at",
        "joined_via",
    }
    body = CourseMemberAddRequest(email="  STUDENT@Example.test ", reason="  note  ")
    assert body.email == "student@example.test"
    assert body.reason == "note"
    remove_body = CourseMemberRemoveRequest(reason="  reason stays out of URLs  ")
    assert remove_body.reason == "reason stays out of URLs"


def test_roster_authorization_uses_owned_course_contract() -> None:
    course = _course(uuid.uuid4())
    teacher = _user("teacher@example.test", student=False)
    with pytest.raises(HTTPException) as error:
        check_course_ownership(teacher, course)
    assert error.value.status_code == 404

    admin = User(
        id=uuid.uuid4(),
        email="admin@example.test",
        display_name="Admin",
        password_hash="hash",
        roles=[UserRole.ADMIN],
    )
    check_course_ownership(admin, course)


def test_add_existing_student_records_audit() -> None:
    async def scenario() -> None:
        course_id = uuid.uuid4()
        user = _user("student@example.test")
        db = _DB(_course(course_id), user, None, None)
        outcome, membership, invite = await course_service.add_member(
            db,
            course_id=course_id,
            email=" STUDENT@EXAMPLE.TEST ",
            actor_user_id=uuid.uuid4(),
            reason=None,
        )
        assert outcome is MembershipAddOutcome.ADDED
        assert invite is None
        assert membership is not None
        assert membership.status is MembershipStatus.ACTIVE
        assert membership.joined_via is MembershipJoinedVia.MANUAL
        audit = db.added[-1]
        assert audit.action == "ADD_MEMBER"  # type: ignore[attr-defined]
        assert audit.after["user_id"] == str(user.id)  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_missing_user_creates_pending_invite_and_duplicate_rejected() -> None:
    async def scenario() -> None:
        course_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        db = _DB(_course(course_id), None, None)
        outcome, membership, invite = await course_service.add_member(
            db,
            course_id=course_id,
            email="new@example.test",
            actor_user_id=actor_id,
            reason=None,
        )
        assert outcome is MembershipAddOutcome.INVITED
        assert membership is None
        assert invite is not None
        assert invite.email == "new@example.test"
        assert db.added[-1].action == "CREATE_INVITE"  # type: ignore[attr-defined]
        assert db.added[-1].after == {  # type: ignore[attr-defined]
            "course_id": str(course_id),
            "status": "PENDING",
        }

        duplicate_db = _DB(_course(course_id), None, invite)
        with pytest.raises(HTTPException) as error:
            await course_service.add_member(
                duplicate_db,
                course_id=course_id,
                email="NEW@EXAMPLE.TEST",
                actor_user_id=actor_id,
                reason=None,
            )
        assert error.value.status_code == 409

    asyncio.run(scenario())


def test_remove_then_reactivate_preserves_membership_and_resets_join_data() -> None:
    async def scenario() -> None:
        course_id = uuid.uuid4()
        user = _user("student@example.test")
        joined_at = datetime(2026, 1, 1, tzinfo=UTC)
        membership = Membership(
            id=uuid.uuid4(),
            course_id=course_id,
            user_id=user.id,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.ACTIVE,
            joined_via=MembershipJoinedVia.CODE,
            joined_at=joined_at,
        )
        db = _DB(_course(course_id), membership)
        await course_service.remove_member(
            db,
            course_id=course_id,
            user_id=user.id,
            actor_user_id=uuid.uuid4(),
            reason="manual removal",
        )
        assert membership.status is MembershipStatus.REMOVED
        assert db.added[-1].action == "REMOVE_MEMBER"  # type: ignore[attr-defined]

        reactivate_db = _DB(_course(course_id), user, membership, None)
        outcome, restored, _ = await course_service.add_member(
            reactivate_db,
            course_id=course_id,
            email=user.email,
            actor_user_id=uuid.uuid4(),
            reason=None,
        )
        assert outcome is MembershipAddOutcome.REACTIVATED
        assert restored is membership
        assert membership.status is MembershipStatus.ACTIVE
        assert membership.joined_via is MembershipJoinedVia.MANUAL
        assert membership.joined_at > joined_at
        assert (
            reactivate_db.added[-1].action  # type: ignore[attr-defined]
            == "REACTIVATE_MEMBER"
        )

    asyncio.run(scenario())


def test_member_response_requires_one_result_and_audit_allowlist_is_non_email() -> None:
    member = CourseMemberResponse(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        email="student@example.test",
        display_name="Student",
        status=MembershipStatus.ACTIVE,
        joined_at=datetime.now(UTC),
        joined_via=MembershipJoinedVia.MANUAL,
    )
    with pytest.raises(ValueError):
        CourseMemberAddResponse(outcome=MembershipAddOutcome.ADDED)
    response = CourseMemberAddResponse(
        outcome=MembershipAddOutcome.ADDED,
        member=member,
    )
    assert response.member is member
    assert "email" not in _AUDIT_SAFE_FIELDS["Membership"]
    assert "email" not in _AUDIT_SAFE_FIELDS["CourseInvite"]


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_removed_student_loses_access_without_deleting_history() -> None:
    async def scenario() -> None:
        ids = _ids()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            await _seed_graph(connection, ids)
            student = _actor(ids["student_1"], "Student 1", UserRole.STUDENT)
            await course_service.remove_member(
                session,
                course_id=ids["course"],
                user_id=student.id,
                actor_user_id=ids["teacher"],
                reason="access regression",
            )

            with pytest.raises(HTTPException) as upload_error:
                await submission_service.initiate_upload(
                    session,
                    assignment_id=ids["assignment"],
                    user=student,
                    idempotency_key="removed-student",
                    filename="removed.pdf",
                    content_type="application/pdf",
                    size_bytes=1,
                    sha256="0" * 64,
                )
            assert upload_error.value.status_code == 404
            notification = await notification_service.add_student_course_notification(
                session,
                recipient_id=student.id,
                course_id=ids["course"],
                notification_type=NotificationType.ANALYSIS_JOB_ERROR,
                payload={"analysis_job_id": str(ids["job"])},
            )
            assert notification is None

            with pytest.raises(HTTPException) as masked_error:
                await submission_service.initiate_upload(
                    session,
                    assignment_id=ids["assignment"],
                    user=student,
                    idempotency_key="removed-student-invalid",
                    filename="removed.txt",
                    content_type="text/plain",
                    size_bytes=1,
                    sha256="invalid",
                )
            assert masked_error.value.status_code == 404

            with pytest.raises(HTTPException) as versions_error:
                await review_service.list_submission_versions(
                    session,
                    submission_id=ids["submission_1"],
                    user=student,
                )
            assert versions_error.value.status_code == 404

            job = await session.get(AnalysisJob, ids["job"])
            assert job is not None
            with pytest.raises(HTTPException) as job_error:
                await job_service.authorize_job(session, job, student)
            assert job_error.value.status_code == 404

            assert await session.get(Submission, ids["submission_1"]) is not None
            assert await session.get(AnalysisJob, ids["job"]) is not None
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_upload_membership_lock_serializes_removal() -> None:
    async def scenario() -> None:
        ids = _ids()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        idempotency_key = f"doc34-lock-{uuid.uuid4()}"
        sha256_hint = uuid.uuid4().hex * 2
        lock_held = asyncio.Event()
        release_upload = asyncio.Event()
        upload_task: asyncio.Task[None] | None = None
        removal_task: asyncio.Task[None] | None = None
        setup_complete = False

        async def upload() -> None:
            async with sessions() as session:
                await submission_service.initiate_upload(
                    session,
                    assignment_id=ids["assignment"],
                    user=_actor(ids["student_1"], "Student 1", UserRole.STUDENT),
                    idempotency_key=idempotency_key,
                    filename="locked.pdf",
                    content_type="application/pdf",
                    size_bytes=1,
                    sha256=sha256_hint,
                    storage=SimpleNamespace(
                        expiry_seconds=300,
                        create_presigned_post=lambda key, _limit: {
                            "url": "http://storage.test",
                            "fields": {"key": key},
                        },
                    ),
                )
                lock_held.set()
                await release_upload.wait()
                await session.commit()

        async def remove() -> None:
            async with sessions() as session:
                await session.execute(
                    text(
                        "UPDATE public.memberships "
                        "SET status = 'REMOVED'::public.membership_status "
                        "WHERE course_id = :course_id AND user_id = :user_id "
                        "AND role = 'STUDENT'::public.membership_role"
                    ),
                    {
                        "course_id": ids["course"],
                        "user_id": ids["student_1"],
                    },
                )
                await session.commit()

        try:
            async with engine.begin() as connection:
                await _seed_graph(connection, ids)
            setup_complete = True

            upload_task = asyncio.create_task(upload())
            await asyncio.wait_for(lock_held.wait(), timeout=5)
            removal_task = asyncio.create_task(remove())
            blocked = False
            try:
                await asyncio.wait_for(asyncio.shield(removal_task), timeout=0.25)
            except TimeoutError:
                blocked = True
            finally:
                release_upload.set()

            await upload_task
            await removal_task
            assert blocked

            async with sessions() as session:
                status_value = await session.scalar(
                    text(
                        "SELECT status::text FROM public.memberships "
                        "WHERE course_id = :course_id AND user_id = :user_id "
                        "AND role = 'STUDENT'::public.membership_role"
                    ),
                    {
                        "course_id": ids["course"],
                        "user_id": ids["student_1"],
                    },
                )
                version_count = await session.scalar(
                    text(
                        "SELECT count(*) FROM public.document_versions "
                        "WHERE idempotency_key = :idempotency_key"
                    ),
                    {"idempotency_key": idempotency_key},
                )
            assert status_value == "REMOVED"
            assert version_count == 1
        finally:
            release_upload.set()
            tasks = [
                task
                for task in (upload_task, removal_task)
                if task is not None and not task.done()
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if setup_complete:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "DELETE FROM public.document_versions "
                            "WHERE idempotency_key = :idempotency_key"
                        ),
                        {"idempotency_key": idempotency_key},
                    )
                    await _cleanup_graph(connection, ids)
            await engine.dispose()

    asyncio.run(scenario())
