from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
from httpx2 import AsyncClient, Limits, Response
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.config import get_settings
from app.db.session import _session_factory
from app.models.course import Membership
from app.models.enums import MembershipRole, MembershipStatus, UserRole, UserStatus
from app.models.identity import User
from app.services.auth import auth_cookie_names, hash_password

PASSWORD = "T022-Development-Only-Password!"


@dataclass
class Sample:
    durations: list[float] = field(default_factory=list)
    errors: int = 0


class Recorder:
    def __init__(self) -> None:
        self.samples: dict[str, Sample] = {}

    def add(self, name: str, duration: float, *, error: bool = False) -> None:
        sample = self.samples.setdefault(name, Sample())
        sample.durations.append(duration)
        sample.errors += int(error)

    def report(self, elapsed: float) -> dict[str, dict[str, float | int]]:
        report: dict[str, dict[str, float | int]] = {}
        for name, sample in sorted(self.samples.items()):
            ordered = sorted(sample.durations)
            report[name] = {
                "requests": len(ordered),
                "errors": sample.errors,
                "p50_ms": _percentile(ordered, 0.50) * 1000,
                "p95_ms": _percentile(ordered, 0.95) * 1000,
                "throughput_rps": len(ordered) / elapsed,
            }
        return report


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    return values[max(0, math.ceil(percentile * len(values)) - 1)]


def _text_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _storage_url(presigned_url: str, storage_base_url: str | None) -> str:
    if storage_base_url is None:
        return presigned_url
    source = urlsplit(presigned_url)
    target = urlsplit(storage_base_url)
    return urlunsplit((target.scheme, target.netloc, source.path, source.query, ""))


async def _request(
    client: AsyncClient,
    method: str,
    path: str,
    expected: int,
    *,
    recorder: Recorder | None = None,
    metric: str | None = None,
    **kwargs: object,
) -> Response:
    started = time.perf_counter()
    try:
        response = await client.request(method, path, **kwargs)
    except Exception:
        if recorder is not None and metric is not None:
            recorder.add(metric, time.perf_counter() - started, error=True)
        raise
    if recorder is not None and metric is not None:
        recorder.add(
            metric,
            time.perf_counter() - started,
            error=response.status_code != expected,
        )
    if response.status_code != expected:
        raise RuntimeError(
            f"{method} {path}: expected {expected}, got {response.status_code}: "
            f"{response.text[:500]}"
        )
    return response


async def _login(client: AsyncClient, email: str) -> None:
    await _request(
        client,
        "POST",
        "/api/v1/auth/login",
        200,
        json={"email": email, "password": PASSWORD},
    )
    _, csrf_cookie = auth_cookie_names(False)
    client.headers["X-CSRF-Token"] = client.cookies[csrf_cookie]


async def _seed_users(run_id: str, users: int) -> tuple[str, str, list[str]]:
    teacher_email = f"t022-teacher-{run_id}@example.test"
    admin_email = f"t022-admin-{run_id}@example.test"
    student_emails = [
        f"t022-student-{index}-{run_id}@example.test" for index in range(users)
    ]
    password_hash = await asyncio.to_thread(hash_password, PASSWORD)
    async with _session_factory()() as database:
        database.add_all(
            [
                User(
                    id=uuid.uuid4(),
                    email=teacher_email,
                    display_name="T-022 Teacher",
                    password_hash=password_hash,
                    roles=[UserRole.TEACHER],
                    status=UserStatus.ACTIVE,
                    revision=1,
                ),
                User(
                    id=uuid.uuid4(),
                    email=admin_email,
                    display_name="T-022 Admin",
                    password_hash=password_hash,
                    roles=[UserRole.ADMIN],
                    status=UserStatus.ACTIVE,
                    revision=1,
                ),
                *[
                    User(
                        id=uuid.uuid4(),
                        email=email,
                        display_name=f"T-022 Student {index}",
                        password_hash=password_hash,
                        roles=[UserRole.STUDENT],
                        status=UserStatus.ACTIVE,
                        revision=1,
                    )
                    for index, email in enumerate(student_emails)
                ],
            ]
        )
        await database.commit()
    return teacher_email, admin_email, student_emails


async def _student_ids(emails: list[str]) -> dict[str, uuid.UUID]:
    async with _session_factory()() as database:
        rows = (
            await database.execute(
                sa.select(User.email, User.id).where(User.email.in_(emails))
            )
        ).all()
    return dict(rows)


async def _setup_course(
    teacher: AsyncClient,
    run_id: str,
    student_emails: list[str],
) -> tuple[str, str]:
    course = (
        await _request(
            teacher,
            "POST",
            "/api/v1/courses",
            201,
            json={
                "code": f"T022-{run_id}",
                "name": "T-022 Load Smoke",
                "term": "2026A",
            },
        )
    ).json()
    course_id = course["id"]
    ids = await _student_ids(student_emails)
    async with _session_factory()() as database:
        database.add_all(
            [
                Membership(
                    id=uuid.uuid4(),
                    course_id=uuid.UUID(course_id),
                    user_id=ids[email],
                    role=MembershipRole.STUDENT,
                    status=MembershipStatus.ACTIVE,
                )
                for email in student_emails
            ]
        )
        await database.commit()

    rubric = (
        await _request(
            teacher,
            "POST",
            "/api/v1/rubrics",
            201,
            json={"name": "T-022 Load Rubric", "calculation_method": "WEIGHTED_SUM"},
        )
    ).json()
    rubric_id = rubric["id"]
    await _request(
        teacher,
        "POST",
        f"/api/v1/rubrics/{rubric_id}/criteria",
        201,
        json={
            "code": "BASELINE",
            "title": "Baseline",
            "description": "T-022 load-only criterion",
            "weight": 100,
            "position": 1,
            "evaluation_method": "AI",
        },
    )
    await _request(teacher, "POST", f"/api/v1/rubrics/{rubric_id}/publish", 200)
    assignment = (
        await _request(
            teacher,
            "POST",
            f"/api/v1/courses/{course_id}/assignments",
            201,
            json={
                "rubric_version_id": rubric_id,
                "title": "T-022 Load Assignment",
                "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "max_submissions": 5,
            },
        )
    ).json()
    assignment_id = assignment["id"]
    await _request(
        teacher,
        "POST",
        f"/api/v1/courses/{course_id}/assignments/{assignment_id}/publish",
        200,
    )
    return course_id, assignment_id


async def _upload_and_wait(
    student: AsyncClient,
    *,
    assignment_id: str,
    storage_base_url: str | None,
    run_id: str,
    student_index: int,
    round_index: int,
    recorder: Recorder,
) -> dict[str, str]:
    label = f"{run_id}-{student_index}-{round_index}"
    pdf = _text_pdf(f"T022 load smoke {label}")
    digest = hashlib.sha256(pdf).hexdigest()
    presign = (
        await _request(
            student,
            "POST",
            f"/api/v1/assignments/{assignment_id}/uploads/presign",
            201,
            recorder=recorder,
            metric="upload_presign",
            headers={"Idempotency-Key": f"t022-presign-{label}"},
            json={
                "filename": f"{label}.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(pdf),
                "sha256": digest,
            },
        )
    ).json()
    await _request(
        student,
        "POST",
        _storage_url(presign["upload_url"], storage_base_url),
        204,
        recorder=recorder,
        metric="object_upload",
        data=presign["fields"],
        files={"file": (f"{label}.pdf", pdf, "application/pdf")},
    )
    completion = (
        await _request(
            student,
            "POST",
            f"/api/v1/document-versions/{presign['document_version_id']}/complete",
            202,
            recorder=recorder,
            metric="upload_complete",
        )
    ).json()

    claim_recorded = False
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        job = (
            await _request(
                student,
                "GET",
                f"/api/v1/analysis-jobs/{completion['analysis_job_id']}",
                200,
            )
        ).json()
        if job["status"] != "QUEUED" and not claim_recorded:
            if job["started_at"] is None:
                raise RuntimeError("claimed analysis job has no started_at")
            queued_at = datetime.fromisoformat(job["queued_at"])
            started_at = datetime.fromisoformat(job["started_at"])
            recorder.add("job_claim", (started_at - queued_at).total_seconds())
            claim_recorded = True
        if job["status"] == "DONE":
            return {
                "submission_id": completion["submission_id"],
                "document_version_id": completion["document_version_id"],
            }
        if job["status"] == "ERROR":
            job_id = completion["analysis_job_id"]
            raise RuntimeError(f"analysis job {job_id} failed: {job['error_code']}")
        await asyncio.sleep(0.05)
    raise TimeoutError(f"analysis job {completion['analysis_job_id']} did not finish")


async def _prepare_and_publish(
    teacher: AsyncClient,
    item: dict[str, str],
    *,
    run_id: str,
    student_index: int,
    round_index: int,
    recorder: Recorder,
) -> None:
    submission_id = item["submission_id"]
    version_id = item["document_version_id"]
    await _request(
        teacher,
        "POST",
        f"/api/v1/submissions/{submission_id}/review-lock",
        200,
    )
    draft = (
        await _request(
            teacher,
            "GET",
            f"/api/v1/submissions/{submission_id}/review-draft",
            200,
        )
    ).json()
    await _request(
        teacher,
        "PUT",
        f"/api/v1/submissions/{submission_id}/review-draft",
        200,
        json={
            "document_version_id": version_id,
            "revision": draft["revision"],
            "comment": "T-022 load smoke",
            "decisions": [],
        },
    )
    key = f"{run_id}-{student_index}-{round_index}"
    await _request(
        teacher,
        "POST",
        f"/api/v1/document-versions/{version_id}/approve",
        200,
        headers={"Idempotency-Key": f"t022-approve-{key}"},
    )
    await _request(
        teacher,
        "POST",
        f"/api/v1/document-versions/{version_id}/publish",
        200,
        recorder=recorder,
        metric="publish",
        headers={"Idempotency-Key": f"t022-publish-{key}"},
        json={"reason": "T-022 load smoke publication"},
    )
    await _request(
        teacher,
        "DELETE",
        f"/api/v1/submissions/{submission_id}/review-lock",
        204,
    )


async def _queue_load(
    teacher: AsyncClient,
    course_id: str,
    deadline: float,
    think_time: float,
    recorder: Recorder,
) -> None:
    while time.monotonic() < deadline:
        response = await _request(
            teacher,
            "GET",
            f"/api/v1/courses/{course_id}/submission-queue?page_size=100",
            200,
            recorder=recorder,
            metric="submission_queue_list",
        )
        if set(response.json()) != {"items", "page", "page_size", "total"}:
            raise RuntimeError("submission queue response shape changed")
        await asyncio.sleep(think_time)


def _print_report(report: dict[str, object]) -> None:
    print(
        "| Operation | Requests | Errors | p50 (ms) | p95 (ms) | Throughput "
        "(requests/s) |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    for name, raw in metrics.items():
        assert isinstance(raw, dict)
        print(
            f"| {name} | {raw['requests']} | {raw['errors']} | "
            f"{raw['p50_ms']:.6f} | {raw['p95_ms']:.6f} | "
            f"{raw['throughput_rps']:.6f} |"
        )


async def run(args: argparse.Namespace) -> dict[str, object]:
    if args.users < 1 or args.users > 50:
        raise ValueError("--users must be between 1 and 50")
    if args.duration <= 0 or args.think_time < 0:
        raise ValueError("--duration must be positive and --think-time non-negative")
    if get_settings().app_env != "development":
        raise RuntimeError("load smoke is restricted to APP_ENV=development")

    run_id = uuid.uuid4().hex[:12]
    recorder = Recorder()
    teacher_email, admin_email, student_emails = await _seed_users(run_id, args.users)
    limits = Limits(max_connections=max(20, args.users * 4))
    clients = [
        AsyncClient(base_url=args.base_url, timeout=30, limits=limits)
        for _ in range(args.users + 2)
    ]
    teacher, admin, *students = clients
    try:
        await _login(teacher, teacher_email)
        await _login(admin, admin_email)
        await asyncio.gather(
            *[
                _login(student, email)
                for student, email in zip(students, student_emails, strict=True)
            ]
        )
        course_id, assignment_id = await _setup_course(teacher, run_id, student_emails)

        started_at = datetime.now(UTC)
        started = time.monotonic()
        deadline = started + args.duration
        queue_tasks = [
            asyncio.create_task(
                _queue_load(
                    teacher,
                    course_id,
                    deadline,
                    args.think_time,
                    recorder,
                )
            )
            for _ in range(args.users)
        ]
        rounds = 0
        try:
            while rounds < 5 and time.monotonic() < deadline:
                uploads = await asyncio.gather(
                    *[
                        _upload_and_wait(
                            student,
                            assignment_id=assignment_id,
                            storage_base_url=args.storage_base_url,
                            run_id=run_id,
                            student_index=index,
                            round_index=rounds,
                            recorder=recorder,
                        )
                        for index, student in enumerate(students)
                    ]
                )
                await asyncio.gather(
                    *[
                        _prepare_and_publish(
                            teacher,
                            item,
                            run_id=run_id,
                            student_index=index,
                            round_index=rounds,
                            recorder=recorder,
                        )
                        for index, item in enumerate(uploads)
                    ]
                )
                rounds += 1
            await asyncio.gather(*queue_tasks)
        finally:
            for task in queue_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*queue_tasks, return_exceptions=True)
        elapsed = time.monotonic() - started

        metrics_response = await _request(admin, "GET", "/metrics", 200)
        metrics_text = metrics_response.text
        required_metrics = {
            "docgrading_analysis_jobs",
            "docgrading_analysis_queue_depth",
            "docgrading_analysis_job_age_seconds_avg",
        }
        if not all(name in metrics_text for name in required_metrics):
            raise RuntimeError("/metrics is missing required Prometheus metrics")

        return {
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "config": {
                "users": args.users,
                "requested_duration_seconds": args.duration,
                "think_time_seconds": args.think_time,
                "max_upload_rounds_per_user": 5,
            },
            "actual_duration_seconds": elapsed,
            "rounds_completed": rounds,
            "metrics": recorder.report(elapsed),
        }
    finally:
        await asyncio.gather(*[client.aclose() for client in clients])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T-022 real-stack load smoke")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--storage-base-url")
    parser.add_argument("--users", type=int, default=8)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--think-time", type=float, default=0.05)
    parser.add_argument(
        "--output", type=Path, default=Path("../artifacts/t022-load.json")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _print_report(report)
    print(f"Results: {args.output}")


if __name__ == "__main__":
    main()
