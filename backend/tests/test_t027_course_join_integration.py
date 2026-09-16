from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.enums import CourseJoinOutcome, MembershipJoinedVia, MembershipStatus
from app.models.identity import User
from app.services.course_join import _rate_limit_subject_digest, join_course
from tests.test_t011_review_workspace import _ids, _seed_graph
from tests.test_t019_security_adversarial import _authenticated_client

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)


def _request(ip: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/course-joins",
            "headers": [],
            "client": (ip, 12345),
        }
    )


def test_join_code_lifecycle_errors_ownership_audit_and_privacy() -> None:
    async def scenario() -> None:
        ids = _ids()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await _seed_graph(connection, ids)
                expires_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
                body = {"expires_at": expires_at}
                path = f"/api/v1/courses/{ids['course']}/join-code"

                async with _authenticated_client(
                    connection, ids["other_teacher"]
                ) as other_teacher:
                    denied = await other_teacher.post(path, json=body)
                    assert denied.status_code == 404

                async with _authenticated_client(
                    connection, ids["student_1"]
                ) as student:
                    denied = await student.post(path, json=body)
                    assert denied.status_code == 403

                async with _authenticated_client(connection, ids["teacher"]) as teacher:
                    created = await teacher.post(path, json=body)
                    assert created.status_code == 201, created.text
                    first = created.json()
                    first_code = first["code"]
                    assert first["status"] == "ACTIVE"
                    parsed_join_url = urlparse(first["join_url"])
                    assert parsed_join_url.path == "/student/join"
                    assert parse_qs(parsed_join_url.query) == {"code": [first_code]}
                    assert str(ids["course"]) not in first["join_url"]

                    qr = await teacher.get(f"{path}/qr")
                    assert qr.status_code == 200
                    assert qr.headers["content-type"].startswith("image/svg+xml")
                    assert "<svg" in qr.text
                    assert qr.headers["cache-control"] == "no-store"

                async with _authenticated_client(connection, ids["admin"]) as admin:
                    visible = await admin.get(path)
                    assert visible.status_code == 200
                    updated = await admin.put(
                        path,
                        json={
                            "expires_at": (
                                datetime.now(UTC) + timedelta(days=2)
                            ).isoformat()
                        },
                    )
                    assert updated.status_code == 200

                async with _authenticated_client(
                    connection, ids["student_1"]
                ) as student:
                    joined = await student.post(
                        "/api/v1/course-joins", json={"code": first_code.lower()}
                    )
                    assert joined.status_code == 200, joined.text
                    assert joined.json()["outcome"] == "ALREADY_MEMBER"

                membership_before = (
                    await connection.execute(
                        text(
                            "SELECT id, status::text, joined_via::text, joined_at "
                            "FROM public.memberships WHERE course_id = :course "
                            "ORDER BY id"
                        ),
                        {"course": ids["course"]},
                    )
                ).all()

                async with _authenticated_client(connection, ids["teacher"]) as teacher:
                    revoked = await teacher.delete(path)
                    assert revoked.status_code == 200
                    assert revoked.json()["status"] == "REVOKED"

                async with _authenticated_client(
                    connection, ids["student_2"]
                ) as student:
                    rejected = await student.post(
                        "/api/v1/course-joins", json={"code": first_code}
                    )
                    assert rejected.status_code == 410
                    assert rejected.json()["detail"]["code"] == "JOIN_CODE_REVOKED"

                async with _authenticated_client(connection, ids["teacher"]) as teacher:
                    regenerated = await teacher.post(f"{path}/regenerate", json=body)
                    assert regenerated.status_code == 200, regenerated.text
                    second_code = regenerated.json()["code"]
                    assert second_code != first_code

                await connection.execute(
                    text(
                        "UPDATE public.course_join_codes "
                        "SET created_at = ("
                        "SELECT created_at + interval '1 second' "
                        "FROM public.course_join_codes WHERE code = :active"
                        ") WHERE code = :revoked"
                    ),
                    {"active": second_code, "revoked": first_code},
                )
                async with _authenticated_client(connection, ids["admin"]) as admin:
                    current = await admin.get(path)
                    assert current.status_code == 200
                    assert current.json()["code"] == second_code

                membership_after = (
                    await connection.execute(
                        text(
                            "SELECT id, status::text, joined_via::text, joined_at "
                            "FROM public.memberships WHERE course_id = :course "
                            "ORDER BY id"
                        ),
                        {"course": ids["course"]},
                    )
                ).all()
                assert membership_after == membership_before

                await connection.execute(
                    text(
                        "UPDATE public.course_join_codes "
                        "SET created_at = now() - interval '2 days', "
                        "expires_at = now() - interval '1 day' "
                        "WHERE code = :code"
                    ),
                    {"code": second_code},
                )
                async with _authenticated_client(
                    connection, ids["student_3"]
                ) as student:
                    invalid = await student.post(
                        "/api/v1/course-joins", json={"code": "0" * 20}
                    )
                    assert invalid.status_code == 404
                    assert invalid.json()["detail"]["code"] == "JOIN_CODE_INVALID"
                    expired = await student.post(
                        "/api/v1/course-joins", json={"code": second_code}
                    )
                    assert expired.status_code == 410
                    assert expired.json()["detail"]["code"] == "JOIN_CODE_EXPIRED"

                async with _authenticated_client(connection, ids["teacher"]) as teacher:
                    revoked_expired = await teacher.delete(path)
                    assert revoked_expired.status_code == 200
                    assert revoked_expired.json()["code"] == second_code
                    latest_revoked = await teacher.get(path)
                    assert latest_revoked.status_code == 200
                    assert latest_revoked.json()["code"] == second_code

                audits = (
                    await connection.execute(
                        text(
                            "SELECT action, before, after FROM public.audit_events "
                            "WHERE resource_type = 'CourseJoinCode' "
                            "AND after->>'course_id' = :course"
                        ),
                        {"course": str(ids["course"])},
                    )
                ).all()
                assert {row.action for row in audits} == {
                    "CREATE_JOIN_CODE",
                    "UPDATE_JOIN_CODE",
                    "REVOKE_JOIN_CODE",
                    "REGENERATE_JOIN_CODE",
                }
                serialized = repr(audits)
                assert first_code not in serialized and second_code not in serialized
                assert "join_url" not in serialized and "@test.local" not in serialized
            finally:
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(scenario())


def test_join_endpoint_rate_limit_returns_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        ids = _ids()
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await _seed_graph(connection, ids)
                stale_digests = [f"{index:064x}" for index in range(101)]
                await connection.execute(
                    text(
                        "INSERT INTO public.join_rate_limits "
                        "(id, subject_hash, window_started_at, request_count) "
                        "VALUES (:id, :digest, now() - interval '2 minutes', 1)"
                    ),
                    [
                        {"id": uuid.uuid4(), "digest": digest}
                        for digest in stale_digests
                    ],
                )
                async with _authenticated_client(
                    connection, ids["student_1"]
                ) as student:
                    response = await student.post(
                        "/api/v1/course-joins", json={"code": "0" * 20}
                    )
                    assert response.status_code == 404
                    assert (
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM public.join_rate_limits "
                                "WHERE window_started_at "
                                "< now() - interval '1 minute'"
                            )
                        )
                        == 1
                    )
                    response = await student.post(
                        "/api/v1/course-joins", json={"code": "0" * 20}
                    )
                    assert response.status_code == 404
                    assert (
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM public.join_rate_limits "
                                "WHERE window_started_at "
                                "< now() - interval '1 minute'"
                            )
                        )
                        == 0
                    )
                    limited = await student.post(
                        "/api/v1/course-joins", json={"code": "0" * 20}
                    )
                    assert limited.status_code == 429
                    assert (
                        await connection.scalars(
                            text(
                                "SELECT request_count "
                                "FROM public.join_rate_limits "
                                "ORDER BY subject_hash"
                            )
                        )
                    ).all() == [3, 3]
                    assert limited.json()["detail"]["code"] == "JOIN_RATE_LIMITED"
                    assert int(limited.headers["Retry-After"]) >= 1
            finally:
                await transaction.rollback()
        await engine.dispose()

    monkeypatch.setenv("JOIN_RATE_LIMIT_MAX_REQUESTS", "2")
    get_settings.cache_clear()
    try:
        asyncio.run(scenario())
    finally:
        get_settings.cache_clear()


def test_concurrent_join_creates_one_membership_and_idempotent_replay() -> None:
    async def scenario() -> None:
        settings = get_settings()
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        course_id = uuid.uuid4()
        code_id = uuid.uuid4()
        code = "ABCDEFGHJKMNPQRSTUV0"
        membership_id: uuid.UUID | None = None
        ips = ("203.0.113.10", "203.0.113.11")
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO public.users "
                        "(id, email, display_name, password_hash, "
                        "roles, status, revision) "
                        "VALUES (:teacher, :teacher_email, 'T027 Teacher', 'hash', "
                        "ARRAY['TEACHER']::public.user_role[], "
                        "'ACTIVE'::public.user_status, 1), "
                        "(:student, :student_email, 'T027 Student', 'hash', "
                        "ARRAY['STUDENT']::public.user_role[], "
                        "'ACTIVE'::public.user_status, 1)"
                    ),
                    {
                        "teacher": teacher_id,
                        "teacher_email": f"{teacher_id}@test.local",
                        "student": student_id,
                        "student_email": f"{student_id}@test.local",
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO public.courses "
                        "(id, code, name, term, owner_teacher_id, revision) "
                        "VALUES (:id, :code, 'T027 Race', '2026A', :teacher, 1)"
                    ),
                    {
                        "id": course_id,
                        "code": f"T027-{course_id}",
                        "teacher": teacher_id,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO public.course_join_codes "
                        "(id, course_id, code, expires_at) "
                        "VALUES (:id, :course, :code, now() + interval '1 day')"
                    ),
                    {"id": code_id, "course": course_id, "code": code},
                )

            async def attempt(ip: str) -> tuple[CourseJoinOutcome, uuid.UUID]:
                async with sessions() as session:
                    user = await session.get(User, student_id)
                    assert user is not None
                    outcome, membership, _course = await join_course(
                        session, code=code, user=user, request=_request(ip)
                    )
                    await session.commit()
                    return outcome, membership.id

            first, second = await asyncio.gather(*(attempt(ip) for ip in ips))
            assert {first[0], second[0]} == {
                CourseJoinOutcome.JOINED,
                CourseJoinOutcome.ALREADY_MEMBER,
            }
            assert first[1] == second[1]
            membership_id = first[1]

            async with engine.connect() as connection:
                row = (
                    await connection.execute(
                        text(
                            "SELECT id, status::text, joined_via::text "
                            "FROM public.memberships WHERE course_id = :course "
                            "AND user_id = :student"
                        ),
                        {"course": course_id, "student": student_id},
                    )
                ).one()
                assert row.id == membership_id
                assert row.status == MembershipStatus.ACTIVE.value
                assert row.joined_via == MembershipJoinedVia.CODE.value
                audit_count = await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.audit_events "
                        "WHERE resource_type = 'Membership' "
                        "AND resource_id = :membership AND action = 'JOIN_MEMBER'"
                    ),
                    {"membership": membership_id},
                )
                assert audit_count == 1
        finally:
            async with engine.begin() as connection:
                await connection.execute(
                    text("SET LOCAL session_replication_role = 'replica'")
                )
                if membership_id is not None:
                    await connection.execute(
                        text(
                            "DELETE FROM public.audit_events "
                            "WHERE resource_type = 'Membership' AND resource_id = :id"
                        ),
                        {"id": membership_id},
                    )
                await connection.execute(
                    text("SET LOCAL session_replication_role = 'origin'")
                )
                await connection.execute(
                    text("DELETE FROM public.courses WHERE id = :id"),
                    {"id": course_id},
                )
                digests = {
                    "account": _rate_limit_subject_digest(f"account:{student_id}"),
                    "ip_1": _rate_limit_subject_digest(f"ip:{ips[0]}"),
                    "ip_2": _rate_limit_subject_digest(f"ip:{ips[1]}"),
                }
                await connection.execute(
                    text(
                        "DELETE FROM public.join_rate_limits "
                        "WHERE subject_hash IN (:account, :ip_1, :ip_2)"
                    ),
                    digests,
                )
                await connection.execute(
                    text("DELETE FROM public.users WHERE id IN (:teacher, :student)"),
                    {"teacher": teacher_id, "student": student_id},
                )
            await engine.dispose()

    asyncio.run(scenario())
