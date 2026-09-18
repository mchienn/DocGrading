from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import uuid
from collections import Counter
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.config import Config
from httpx2 import ASGITransport, AsyncClient, Response
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.routers import operations as operations_router
from app.api.routers import submissions as submissions_router
from app.core.config import get_settings
from app.db import session as db_session
from app.main import create_app
from app.models.analysis import DocumentIR
from app.models.course import Membership
from app.models.enums import (
    MembershipRole,
    MembershipStatus,
    UserRole,
    UserStatus,
)
from app.models.identity import User
from app.models.review import EvidenceAnchor, Finding
from app.services import submission as submission_service
from app.services.auth import auth_cookie_names, hash_password
from app.services.storage import ObjectHead, StorageObjectChanged, StorageObjectNotFound
from tests.test_t010_document_ir_parser import _make_text_pdf

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database E2E tests require RUN_DATABASE_TESTS=1",
)

PASSWORD = "T021-Strong-Password!"


class MemoryStorage:
    """Object-storage boundary; application modules and PostgreSQL remain real."""

    expiry_seconds = 300

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.sealed_keys: dict[str, str] = {}
        self.fail_reads: set[str] = set()
        self.block_key: str | None = None
        self.read_started = threading.Event()
        self.read_release = threading.Event()

    def create_presigned_post(self, key: str, _max_size: int) -> dict[str, Any]:
        return {
            "url": "https://storage.test/upload",
            "fields": {"key": key, "Content-Type": "application/pdf"},
        }

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def head(self, key: str) -> ObjectHead:
        try:
            data = self.objects[key]
        except KeyError as exc:
            raise StorageObjectNotFound from exc
        return ObjectHead(
            content_type="application/pdf",
            content_length=len(data),
            etag=hashlib.sha256(data).hexdigest(),
        )

    def seal_upload(
        self,
        source_key: str,
        destination_key: str,
        expected_etag: str,
    ) -> ObjectHead:
        source = self.head(source_key)
        if source.etag != expected_etag:
            raise StorageObjectChanged
        self.objects[destination_key] = self.objects[source_key]
        self.sealed_keys[source_key] = destination_key
        return self.head(destination_key)

    def get_bounded(self, key: str, max_size: int) -> bytes:
        if key == self.block_key:
            self.read_started.set()
            if not self.read_release.wait(10):
                raise TimeoutError("T-021 worker gate timed out")
        if key in self.fail_reads:
            raise RuntimeError("simulated object-storage failure")
        try:
            return self.objects[key][: max_size + 1]
        except KeyError as exc:
            raise StorageObjectNotFound from exc

    def block_once(self, key: str) -> None:
        self.block_key = key
        self.read_started.clear()
        self.read_release.clear()

    def unblock(self) -> None:
        self.read_release.set()
        self.block_key = None


def _alembic_config() -> Config:
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    return config


async def _create_database(admin_url: URL, name: str) -> None:
    engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def _drop_database(admin_url: URL, name: str) -> None:
    engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(
                sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            )
    finally:
        await engine.dispose()


def _clear_database_caches() -> None:
    get_settings.cache_clear()
    db_session._session_factory.cache_clear()
    db_session._engine.cache_clear()


async def _expect(
    client: AsyncClient,
    step: str,
    method: str,
    path: str,
    status: int,
    **kwargs: Any,
) -> Response:
    response = await client.request(method, path, **kwargs)
    assert (
        response.status_code == status
    ), f"{step}: expected {status}, got {response.status_code}: {response.text}"
    return response


async def _login(
    client: AsyncClient,
    *,
    email: str,
    expected_role: UserRole,
    step: str,
) -> str:
    response = await _expect(
        client,
        step,
        "POST",
        "/api/v1/auth/login",
        200,
        json={"email": email, "password": PASSWORD},
    )
    payload = response.json()
    assert set(payload) == {"id", "email", "display_name", "roles", "status"}, step
    assert expected_role.value in payload["roles"], step
    session_cookie, csrf_cookie = auth_cookie_names(
        get_settings().session_cookie_secure
    )
    session_id = client.cookies.get(session_cookie)
    csrf_token = client.cookies.get(csrf_cookie)
    assert session_id, f"{step}: session cookie missing"
    assert csrf_token, f"{step}: CSRF cookie missing"
    client.headers["X-CSRF-Token"] = csrf_token
    return session_id


async def _seed_users(ids: dict[str, uuid.UUID], emails: dict[str, str]) -> None:
    password_hash = hash_password(PASSWORD)
    async with db_session._session_factory()() as database:
        database.add_all(
            [
                User(
                    id=ids["teacher"],
                    email=emails["teacher"],
                    display_name="T-021 Teacher",
                    password_hash=password_hash,
                    roles=[UserRole.TEACHER],
                    status=UserStatus.ACTIVE,
                    revision=1,
                ),
                User(
                    id=ids["student_a"],
                    email=emails["student_a"],
                    display_name="T-021 Student A",
                    password_hash=password_hash,
                    roles=[UserRole.STUDENT],
                    status=UserStatus.ACTIVE,
                    revision=1,
                ),
                User(
                    id=ids["student_b"],
                    email=emails["student_b"],
                    display_name="T-021 Student B",
                    password_hash=password_hash,
                    roles=[UserRole.STUDENT],
                    status=UserStatus.ACTIVE,
                    revision=1,
                ),
                User(
                    id=ids["admin"],
                    email=emails["admin"],
                    display_name="T-021 Admin",
                    password_hash=password_hash,
                    roles=[UserRole.ADMIN],
                    status=UserStatus.ACTIVE,
                    revision=1,
                ),
            ]
        )
        await database.commit()


async def _add_memberships(course_id: uuid.UUID, ids: dict[str, uuid.UUID]) -> None:
    async with db_session._session_factory()() as database:
        database.add_all(
            [
                Membership(
                    id=uuid.uuid4(),
                    course_id=course_id,
                    user_id=ids[name],
                    role=MembershipRole.STUDENT,
                    status=MembershipStatus.ACTIVE,
                )
                for name in ("student_a", "student_b")
            ]
        )
        await database.commit()


async def _upload(
    client: AsyncClient,
    storage: MemoryStorage,
    *,
    assignment_id: uuid.UUID,
    data: bytes,
    label: str,
) -> dict[str, Any]:
    sha256 = hashlib.sha256(data).hexdigest()
    presign = await _expect(
        client,
        f"{label} presign",
        "POST",
        f"/api/v1/assignments/{assignment_id}/uploads/presign",
        201,
        headers={"Idempotency-Key": f"{label}-presign"},
        json={
            "filename": f"{label}.pdf",
            "content_type": "application/pdf",
            "size_bytes": len(data),
            "sha256": sha256,
        },
    )
    payload = presign.json()
    assert payload["status"] == "UPLOADING", label
    assert payload["expires_in"] == 300, label
    assert payload["reused"] is False, label
    storage.put(payload["object_key"], data)

    completed = await _expect(
        client,
        f"{label} complete",
        "POST",
        f"/api/v1/document-versions/{payload['document_version_id']}/complete",
        202,
    )
    completion = completed.json()
    assert completion["submission_id"] == payload["submission_id"], label
    assert completion["document_version_id"] == payload["document_version_id"], label
    assert completion["status"] == "QUEUED", label
    sealed_key = storage.sealed_keys[payload["object_key"]]
    assert sealed_key != payload["object_key"], label
    return {**payload, **completion, "object_key": sealed_key}


async def _process_and_track(
    client: AsyncClient,
    storage: MemoryStorage,
    upload: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    from app.workers import tasks as worker_tasks

    job_id = upload["analysis_job_id"]
    queued = await _expect(
        client,
        f"{label} poll QUEUED",
        "GET",
        f"/api/v1/analysis-jobs/{job_id}",
        200,
    )
    assert queued.json()["status"] == "QUEUED", label

    storage.block_once(upload["object_key"])
    worker = asyncio.create_task(worker_tasks._run_analysis_job(job_id))
    started = await asyncio.to_thread(storage.read_started.wait, 10)
    assert started, f"{label}: worker never reached object read"
    running = await _expect(
        client,
        f"{label} poll RUNNING",
        "GET",
        f"/api/v1/analysis-jobs/{job_id}",
        200,
    )
    assert running.json()["status"] == "RUNNING", label
    storage.unblock()
    assert await asyncio.wait_for(worker, 60) == job_id, label

    done = await _expect(
        client,
        f"{label} poll DONE",
        "GET",
        f"/api/v1/analysis-jobs/{job_id}",
        200,
    )
    payload = done.json()
    assert payload["status"] == "DONE", label
    assert payload["attempt_count"] == 1, label

    async with db_session._session_factory()() as database:
        document_ir = await database.scalar(
            sa.select(DocumentIR).where(
                DocumentIR.document_version_id
                == uuid.UUID(upload["document_version_id"])
            )
        )
        assert document_ir is not None, f"{label}: Document IR missing"
        assert (
            document_ir.content["source"]["sha256"]
            == hashlib.sha256(storage.objects[upload["object_key"]]).hexdigest()
        ), label
        assert document_ir.content["paragraphs"], f"{label}: Document IR has no text"
        return document_ir.content


async def _add_finding(
    upload: dict[str, Any],
    *,
    criterion_version_id: uuid.UUID,
    score: int,
    label: str,
) -> uuid.UUID:
    finding_id = uuid.uuid4()
    async with db_session._session_factory()() as database:
        document_ir = await database.scalar(
            sa.select(DocumentIR).where(
                DocumentIR.document_version_id
                == uuid.UUID(upload["document_version_id"])
            )
        )
        assert document_ir is not None, f"{label}: Document IR missing before finding"
        paragraph = document_ir.content["paragraphs"][0]
        database.add(
            Finding(
                id=finding_id,
                analysis_job_id=uuid.UUID(upload["analysis_job_id"]),
                criterion_version_id=criterion_version_id,
                severity="MAJOR",
                description=f"{label} finding",
                suggestion=f"{label} suggestion",
                proposed_score=score,
            )
        )
        await database.flush()
        database.add(
            EvidenceAnchor(
                id=uuid.uuid4(),
                finding_id=finding_id,
                document_ir_id=document_ir.id,
                element_id=paragraph["id"],
                page_number=paragraph["page_number"],
            )
        )
        await database.commit()
    return finding_id


async def _review_and_publish(
    teacher: AsyncClient,
    *,
    course_id: uuid.UUID,
    upload: dict[str, Any],
    finding_id: uuid.UUID,
    comment: str,
    final_score: int | None,
    label: str,
) -> dict[str, Any]:
    submission_id = upload["submission_id"]
    document_version_id = upload["document_version_id"]
    queue = await _expect(
        teacher,
        f"{label} teacher queue",
        "GET",
        f"/api/v1/courses/{course_id}/submission-queue?status=UNREVIEWED",
        200,
    )
    assert any(
        item["submission_id"] == submission_id
        and item["document_version_id"] == document_version_id
        for item in queue.json()["items"]
    ), label

    evidence = await _expect(
        teacher,
        f"{label} evidence",
        "GET",
        f"/api/v1/submissions/{submission_id}/evidence",
        200,
    )
    evidence_payload = evidence.json()
    assert evidence_payload["document_version_id"] == document_version_id, label
    assert evidence_payload["findings"][0]["id"] == str(finding_id), label
    assert set(evidence_payload["findings"][0]["evidence"][0]) == {
        "document_ir_id",
        "element_id",
        "page_number",
        "bbox",
    }, label

    lock = await _expect(
        teacher,
        f"{label} review lock",
        "POST",
        f"/api/v1/submissions/{submission_id}/review-lock",
        200,
    )
    assert lock.json()["acquired"] is True, label

    current = await _expect(
        teacher,
        f"{label} load draft",
        "GET",
        f"/api/v1/submissions/{submission_id}/review-draft",
        200,
    )
    decision: dict[str, Any] = {"finding_id": str(finding_id), "decision": "ACCEPT"}
    if final_score is not None:
        decision = {
            "finding_id": str(finding_id),
            "decision": "EDIT",
            "final_score": final_score,
            "reason": f"{label} score correction",
        }
    saved = await _expect(
        teacher,
        f"{label} autosave",
        "PUT",
        f"/api/v1/submissions/{submission_id}/review-draft",
        200,
        json={
            "document_version_id": document_version_id,
            "revision": current.json()["revision"],
            "comment": comment,
            "decisions": [decision],
        },
    )
    assert saved.json()["comment"] == comment, label
    assert saved.json()["decisions"][0]["finding_id"] == str(finding_id), label

    approved = await _expect(
        teacher,
        f"{label} approve",
        "POST",
        f"/api/v1/document-versions/{document_version_id}/approve",
        200,
        headers={"Idempotency-Key": f"{label}-approve"},
    )
    assert approved.json()["status"] == "APPROVED", label

    published = await _expect(
        teacher,
        f"{label} publish",
        "POST",
        f"/api/v1/document-versions/{document_version_id}/publish",
        200,
        headers={"Idempotency-Key": f"{label}-publish"},
        json={"reason": f"{label} ready for student"},
    )
    payload = published.json()
    assert payload["document_version_id"] == document_version_id, label
    assert payload["comment"] == comment, label

    await _expect(
        teacher,
        f"{label} release lock",
        "DELETE",
        f"/api/v1/submissions/{submission_id}/review-lock",
        204,
    )
    return payload


def _assert_audit_sequence(
    events: list[dict[str, Any]],
    resource_type: str,
    resource_id: str,
    expected_actions: list[str],
) -> None:
    matching = list(
        reversed(
            [
                event
                for event in events
                if event["resource_type"] == resource_type
                and event["resource_id"] == resource_id
            ]
        )
    )
    assert [event["action"] for event in matching] == expected_actions
    timestamps = [datetime.fromisoformat(event["occurred_at"]) for event in matching]
    assert timestamps == sorted(timestamps)


async def _e2e_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import tasks as worker_tasks

    run_id = uuid.uuid4().hex
    ids = {
        name: uuid.uuid4() for name in ("teacher", "student_a", "student_b", "admin")
    }
    emails = {name: f"t021-{name}-{run_id}@test.local" for name in ids}
    audit_started_at = datetime.now(UTC)
    await _seed_users(ids, emails)

    storage = MemoryStorage()

    async def accepted_dispatch(_job_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(submission_service, "S3Storage", lambda: storage)
    monkeypatch.setattr(worker_tasks, "S3Storage", lambda: storage)
    monkeypatch.setattr(
        submissions_router, "dispatch_analysis_job_now", accepted_dispatch
    )
    monkeypatch.setattr(
        operations_router, "dispatch_analysis_job_now", accepted_dispatch
    )

    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncExitStack() as stack:
        teacher = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://testserver")
        )
        student_a = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://testserver")
        )
        student_b = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://testserver")
        )
        admin = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://testserver")
        )

        teacher_session_id = await _login(
            teacher,
            email=emails["teacher"],
            expected_role=UserRole.TEACHER,
            step="1 teacher login",
        )
        course = (
            await _expect(
                teacher,
                "1 create Course",
                "POST",
                "/api/v1/courses",
                201,
                json={
                    "code": f"T021-{run_id[:12]}",
                    "name": "T-021 Critical Flow",
                    "term": "2026A",
                },
            )
        ).json()
        course_id = uuid.UUID(course["id"])
        assert course["status"] == "ACTIVE", "1 create Course"
        await _add_memberships(course_id, ids)

        rubric = (
            await _expect(
                teacher,
                "1 create RubricVersion draft",
                "POST",
                "/api/v1/rubrics",
                201,
                json={"name": "T-021 Rubric", "calculation_method": "WEIGHTED_SUM"},
            )
        ).json()
        rubric_id = uuid.UUID(rubric["id"])
        assert rubric["status"] == "DRAFT", "1 create RubricVersion draft"

        assignment = (
            await _expect(
                teacher,
                "1 create Assignment",
                "POST",
                f"/api/v1/courses/{course_id}/assignments",
                201,
                json={
                    "rubric_version_id": str(rubric_id),
                    "title": "T-021 Assignment",
                    "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                    "max_submissions": 3,
                },
            )
        ).json()
        assignment_id = uuid.UUID(assignment["id"])
        assert assignment["status"] == "DRAFT", "1 create Assignment"

        criterion = (
            await _expect(
                teacher,
                "1 add criterion",
                "POST",
                f"/api/v1/rubrics/{rubric_id}/criteria",
                201,
                json={
                    "code": "C1",
                    "title": "Required section",
                    "description": "Required section exists",
                    "weight": 100,
                    "position": 1,
                    "evaluation_method": "AI",
                },
            )
        ).json()
        criterion_version_id = uuid.UUID(criterion["id"])
        criterion_id = uuid.UUID(criterion["criterion_id"])

        published_rubric = await _expect(
            teacher,
            "1 publish RubricVersion",
            "POST",
            f"/api/v1/rubrics/{rubric_id}/publish",
            200,
        )
        assert published_rubric.json()["status"] == "PUBLISHED", "1 publish rubric"
        opened_assignment = await _expect(
            teacher,
            "1 publish Assignment",
            "POST",
            f"/api/v1/courses/{course_id}/assignments/{assignment_id}/publish",
            200,
        )
        assert opened_assignment.json()["status"] == "OPEN", "1 publish Assignment"
        empty_queue = await _expect(
            teacher,
            "1 empty submission queue",
            "GET",
            f"/api/v1/courses/{course_id}/submission-queue",
            200,
        )
        assert empty_queue.json() == {
            "items": [],
            "page": 1,
            "page_size": 50,
            "total": 0,
        }, "1 empty submission queue"

        student_a_session_id = await _login(
            student_a,
            email=emails["student_a"],
            expected_role=UserRole.STUDENT,
            step="2 Student A login",
        )
        student_b_session_id = await _login(
            student_b,
            email=emails["student_b"],
            expected_role=UserRole.STUDENT,
            step="2 Student B login",
        )
        visible_assignment = await _expect(
            student_a,
            "2 Student views Assignment",
            "GET",
            f"/api/v1/courses/{course_id}/assignments/{assignment_id}",
            200,
        )
        assert visible_assignment.json()["status"] == "OPEN", "2 view Assignment"

        first_pdf = _make_text_pdf("Required section evidence version one.")
        first = await _upload(
            student_a,
            storage,
            assignment_id=assignment_id,
            data=first_pdf,
            label="2 first version",
        )
        first_ir = await _process_and_track(
            student_a, storage, first, label="2 first version"
        )
        assert first_ir["pages"][0]["number"] == 1, "2 Document IR persisted"

        await _expect(
            student_b,
            "security Student B cannot see Student A Submission",
            "GET",
            f"/api/v1/submissions/{first['submission_id']}/versions",
            404,
        )
        first_finding = await _add_finding(
            first,
            criterion_version_id=criterion_version_id,
            score=80,
            label="3 first review",
        )
        await _expect(
            student_b,
            "security Student B cannot open Student A evidence",
            "GET",
            f"/api/v1/submissions/{first['submission_id']}/evidence",
            403,
        )
        first_result = await _review_and_publish(
            teacher,
            course_id=course_id,
            upload=first,
            finding_id=first_finding,
            comment="Version one feedback",
            final_score=None,
            label="3 first review",
        )

        result = await _expect(
            student_a,
            "4 Student views published result",
            "GET",
            f"/api/v1/submissions/{first['submission_id']}/published-result",
            200,
        )
        result_payload = result.json()
        assert result_payload == first_result, "4 published result snapshot mismatch"
        assert result_payload["findings"][0]["score"] == "80.00", "4 result score"
        await _expect(
            student_b,
            "security Student B cannot see Student A published result",
            "GET",
            f"/api/v1/submissions/{first['submission_id']}/published-result",
            404,
        )

        review_request = (
            await _expect(
                student_a,
                "4 create criterion review request",
                "POST",
                f"/api/v1/published-results/{first_result['published_result_id']}"
                "/review-requests",
                201,
                json={
                    "submission_id": first["submission_id"],
                    "criterion_id": str(criterion_id),
                    "reason": "Please explain criterion C1",
                },
            )
        ).json()
        review_request_id = review_request["id"]
        assert review_request["status"] == "OPEN", "4 review request status"

        teacher_notifications = await _expect(
            teacher,
            "5 Teacher receives review notification",
            "GET",
            "/api/v1/notifications?unread=true",
            200,
        )
        assert any(
            item["type"] == "REVIEW_REQUEST_CREATED"
            and item["payload"] == {"review_request_id": review_request_id}
            for item in teacher_notifications.json()["items"]
        ), "5 Teacher review notification missing"
        listed_requests = await _expect(
            teacher,
            "5 Teacher lists review requests",
            "GET",
            f"/api/v1/courses/{course_id}/review-requests?status=OPEN",
            200,
        )
        assert [item["id"] for item in listed_requests.json()["items"]] == [
            review_request_id
        ], "5 Teacher review queue"
        resolved = await _expect(
            teacher,
            "5 Teacher resolves review request",
            "PATCH",
            f"/api/v1/review-requests/{review_request_id}",
            200,
            json={"status": "RESOLVED", "response": "Criterion C1 reviewed"},
        )
        assert resolved.json()["status"] == "RESOLVED", "5 resolve status"

        student_notifications = await _expect(
            student_a,
            "5 Student receives resolution notification",
            "GET",
            "/api/v1/notifications?unread=true&page_size=100",
            200,
        )
        notification_types = {
            item["type"] for item in student_notifications.json()["items"]
        }
        assert {
            "RESULT_PUBLISHED",
            "REVIEW_REQUEST_RESOLVED",
        } <= notification_types, "5 Student notifications missing"
        assert any(
            item["type"] == "REVIEW_REQUEST_RESOLVED"
            and item["payload"] == {"review_request_id": review_request_id}
            for item in student_notifications.json()["items"]
        ), "5 resolution notification payload"
        rejected_request = (
            await _expect(
                student_a,
                "5 create review request for rejection",
                "POST",
                f"/api/v1/published-results/{first_result['published_result_id']}"
                "/review-requests",
                201,
                json={
                    "submission_id": first["submission_id"],
                    "criterion_id": str(criterion_id),
                    "reason": "Please reconsider criterion C1",
                },
            )
        ).json()
        rejected_request_id = rejected_request["id"]
        rejected = await _expect(
            teacher,
            "5 Teacher rejects review request",
            "PATCH",
            f"/api/v1/review-requests/{rejected_request_id}",
            200,
            json={"status": "REJECTED", "response": "Published score stands"},
        )
        assert rejected.json()["status"] == "REJECTED", "5 reject status"
        rejected_notifications = await _expect(
            student_a,
            "5 Student receives rejection notification",
            "GET",
            "/api/v1/notifications?unread=true&page_size=100",
            200,
        )
        assert any(
            item["type"] == "REVIEW_REQUEST_REJECTED"
            and item["payload"] == {"review_request_id": rejected_request_id}
            for item in rejected_notifications.json()["items"]
        ), "5 rejection notification payload"

        second_pdf = _make_text_pdf("Required section improved in version two.")
        second = await _upload(
            student_a,
            storage,
            assignment_id=assignment_id,
            data=second_pdf,
            label="6 second version",
        )
        assert second["submission_id"] == first["submission_id"], "6 same Submission"
        assert (
            second["document_version_id"] != first["document_version_id"]
        ), "6 new DocumentVersion"
        await _process_and_track(student_a, storage, second, label="6 second version")
        second_finding = await _add_finding(
            second,
            criterion_version_id=criterion_version_id,
            score=85,
            label="6 second review",
        )
        second_result = await _review_and_publish(
            teacher,
            course_id=course_id,
            upload=second,
            finding_id=second_finding,
            comment="Version two feedback",
            final_score=90,
            label="6 second review",
        )

        versions = await _expect(
            student_a,
            "6 list two versions",
            "GET",
            f"/api/v1/submissions/{first['submission_id']}/versions",
            200,
        )
        version_payload = versions.json()
        assert version_payload["total"] == 2, "6 version count"
        assert [item["version_number"] for item in version_payload["items"]] == [
            1,
            2,
        ], "6 version order"
        comparison = await _expect(
            student_a,
            "6 compare two versions",
            "GET",
            f"/api/v1/submissions/{first['submission_id']}/versions/compare",
            200,
            params={
                "left_version_id": first["document_version_id"],
                "right_version_id": second["document_version_id"],
            },
        )
        compared = comparison.json()
        assert compared["left"]["comment"] == "Version one feedback", "6 left comment"
        assert compared["right"]["comment"] == "Version two feedback", "6 right comment"
        assert compared["left"]["findings"][0]["score"] == "80.00", "6 left score"
        assert compared["right"]["findings"][0]["score"] == "90.00", "6 right score"
        assert second_result["version_number"] == 1, "6 result version"

        error_pdf = _make_text_pdf("Valid third PDF with simulated storage failure.")
        error_upload = await _upload(
            student_a,
            storage,
            assignment_id=assignment_id,
            data=error_pdf,
            label="7 error job",
        )
        storage.fail_reads.add(error_upload["object_key"])
        assert await worker_tasks._run_analysis_job(
            error_upload["analysis_job_id"]
        ) == (error_upload["analysis_job_id"]), "7 simulated failed worker"
        error_job = await _expect(
            student_a,
            "7 Student sees ERROR job",
            "GET",
            f"/api/v1/analysis-jobs/{error_upload['analysis_job_id']}",
            200,
        )
        assert error_job.json()["status"] == "ERROR", "7 failed job status"
        assert (
            error_job.json()["error_code"] == "PDF_STORAGE_ERROR"
        ), "7 failed job code"

        admin_session_id = await _login(
            admin,
            email=emails["admin"],
            expected_role=UserRole.ADMIN,
            step="7 Admin login",
        )
        users = await _expect(
            admin,
            "7 Admin lists users",
            "GET",
            "/api/v1/users?page_size=100",
            200,
        )
        assert users.json()["total"] == 4, "7 Admin user total"
        assert all(
            "password_hash" not in item for item in users.json()["items"]
        ), "7 Admin user privacy"
        jobs = await _expect(
            admin,
            "7 Admin lists all jobs",
            "GET",
            "/api/v1/operations/analysis-jobs?page_size=100",
            200,
        )
        assert jobs.json()["total"] == 3, "7 Admin job total"
        assert {item["id"] for item in jobs.json()["items"]} == {
            first["analysis_job_id"],
            second["analysis_job_id"],
            error_upload["analysis_job_id"],
        }, "7 Admin job scope"
        detail = await _expect(
            admin,
            "7 Admin views failed job",
            "GET",
            f"/api/v1/operations/analysis-jobs/{error_upload['analysis_job_id']}",
            200,
        )
        assert detail.json()["status"] == "ERROR", "7 Admin failed job detail"
        await _expect(
            admin,
            "7 missing job contract",
            "GET",
            f"/api/v1/operations/analysis-jobs/{uuid.uuid4()}",
            404,
        )
        dashboard = await _expect(
            admin,
            "7 Admin dashboard",
            "GET",
            "/api/v1/operations/dashboard",
            200,
        )
        assert dashboard.json()["jobs_by_status"] == {
            "QUEUED": 0,
            "RUNNING": 0,
            "DONE": 2,
            "ERROR": 1,
        }, "7 Admin dashboard job counts"
        assert (
            dashboard.json()["open_review_requests"] == 0
        ), "7 Admin dashboard reviews"

        retried = await _expect(
            admin,
            "7 Admin retries failed job",
            "POST",
            f"/api/v1/operations/analysis-jobs/{error_upload['analysis_job_id']}/retry",
            200,
        )
        assert retried.json()["id"] == error_upload["analysis_job_id"], "7 same job row"
        assert retried.json()["status"] == "QUEUED", "7 retried status"
        assert retried.json()["attempt_count"] == 1, "7 retry preserves attempt count"

        audit = await _expect(
            admin,
            "integrity Admin reads audit trail",
            "GET",
            "/api/v1/operations/audit-events?page_size=100",
            200,
        )
        events = audit.json()["items"]
        audit_finished_at = datetime.now(UTC)
        assert audit.json()["total"] == len(events), "integrity audit pagination"
        event_times = [datetime.fromisoformat(event["occurred_at"]) for event in events]
        assert all(
            audit_started_at <= occurred_at <= audit_finished_at
            for occurred_at in event_times
        ), "integrity audit timing"

        expected_events = Counter(
            [
                ("Session", teacher_session_id, "LOGIN"),
                ("Course", str(course_id), "CREATE"),
                ("RubricVersion", str(rubric_id), "CREATE"),
                ("Assignment", str(assignment_id), "CREATE"),
                ("CriterionVersion", criterion["id"], "CREATE"),
                ("RubricVersion", str(rubric_id), "PUBLISH"),
                ("Assignment", str(assignment_id), "PUBLISH"),
                ("Session", student_a_session_id, "LOGIN"),
                ("Session", student_b_session_id, "LOGIN"),
                ("AnalysisJob", first["analysis_job_id"], "QUEUED"),
                ("AnalysisJob", first["analysis_job_id"], "RUNNING"),
                ("DocumentVersion", first["document_version_id"], "PROCESSING"),
                ("AnalysisJob", first["analysis_job_id"], "DONE"),
                (
                    "DocumentVersion",
                    first["document_version_id"],
                    "AWAITING_REVIEW",
                ),
                ("DocumentVersion", first["document_version_id"], "APPROVE"),
                ("DocumentVersion", first["document_version_id"], "PUBLISH"),
                ("ReviewRequest", review_request_id, "OPEN"),
                ("ReviewRequest", review_request_id, "RESOLVE"),
                ("ReviewRequest", rejected_request_id, "OPEN"),
                ("ReviewRequest", rejected_request_id, "REJECT"),
                ("AnalysisJob", second["analysis_job_id"], "QUEUED"),
                ("AnalysisJob", second["analysis_job_id"], "RUNNING"),
                ("DocumentVersion", second["document_version_id"], "PROCESSING"),
                ("AnalysisJob", second["analysis_job_id"], "DONE"),
                (
                    "DocumentVersion",
                    second["document_version_id"],
                    "AWAITING_REVIEW",
                ),
                ("Finding", str(second_finding), "FINDING_OVERRIDE"),
                ("DocumentVersion", second["document_version_id"], "APPROVE"),
                ("DocumentVersion", second["document_version_id"], "PUBLISH"),
                ("AnalysisJob", error_upload["analysis_job_id"], "QUEUED"),
                ("AnalysisJob", error_upload["analysis_job_id"], "RUNNING"),
                (
                    "DocumentVersion",
                    error_upload["document_version_id"],
                    "PROCESSING",
                ),
                ("AnalysisJob", error_upload["analysis_job_id"], "ERROR"),
                ("Session", admin_session_id, "LOGIN"),
                ("AnalysisJob", error_upload["analysis_job_id"], "QUEUED"),
            ]
        )
        actual_events = Counter(
            (
                event["resource_type"],
                event["resource_id"],
                event["action"],
            )
            for event in events
        )
        assert actual_events == expected_events, "integrity complete audit event set"

        _assert_audit_sequence(events, "Course", str(course_id), ["CREATE"])
        _assert_audit_sequence(
            events, "RubricVersion", str(rubric_id), ["CREATE", "PUBLISH"]
        )
        _assert_audit_sequence(events, "CriterionVersion", criterion["id"], ["CREATE"])
        _assert_audit_sequence(
            events, "Assignment", str(assignment_id), ["CREATE", "PUBLISH"]
        )
        _assert_audit_sequence(
            events,
            "AnalysisJob",
            first["analysis_job_id"],
            ["QUEUED", "RUNNING", "DONE"],
        )
        _assert_audit_sequence(
            events,
            "DocumentVersion",
            first["document_version_id"],
            ["PROCESSING", "AWAITING_REVIEW", "APPROVE", "PUBLISH"],
        )
        _assert_audit_sequence(
            events,
            "ReviewRequest",
            review_request_id,
            ["OPEN", "RESOLVE"],
        )
        _assert_audit_sequence(
            events,
            "ReviewRequest",
            rejected_request_id,
            ["OPEN", "REJECT"],
        )
        _assert_audit_sequence(
            events,
            "AnalysisJob",
            second["analysis_job_id"],
            ["QUEUED", "RUNNING", "DONE"],
        )
        _assert_audit_sequence(
            events,
            "DocumentVersion",
            second["document_version_id"],
            ["PROCESSING", "AWAITING_REVIEW", "APPROVE", "PUBLISH"],
        )
        _assert_audit_sequence(
            events, "Finding", str(second_finding), ["FINDING_OVERRIDE"]
        )
        _assert_audit_sequence(
            events,
            "AnalysisJob",
            error_upload["analysis_job_id"],
            ["QUEUED", "RUNNING", "ERROR", "QUEUED"],
        )


async def _run_e2e(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        await _e2e_scenario(monkeypatch)
    finally:
        if db_session._engine.cache_info().currsize:
            await db_session._engine().dispose()


def test_t021_critical_flows_end_to_end_on_isolated_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    admin_url = make_url(base_settings.database_url).set(database="postgres")
    database_name = f"t021_{uuid.uuid4().hex}"
    asyncio.run(_create_database(admin_url, database_name))
    try:
        monkeypatch.setenv("POSTGRES_DB", database_name)
        _clear_database_caches()
        command.upgrade(_alembic_config(), "head")
        asyncio.run(_run_e2e(monkeypatch))
    finally:
        _clear_database_caches()
        asyncio.run(_drop_database(admin_url, database_name))
