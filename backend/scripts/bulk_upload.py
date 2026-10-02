"""Bulk-upload a folder of student PDF reports for local testing.

Mỗi file PDF được nộp bởi một tài khoản sinh viên riêng (vì mỗi sinh viên chỉ có
1 submission / assignment), vào assignment SRS của khóa CS101.

Yêu cầu: đã chạy `scripts.seed_users` và `scripts.seed_sample_data`, và
api + worker + storage đang chạy.

    uv run python -m scripts.bulk_upload                       # ../test_submissions
    uv run python -m scripts.bulk_upload D:/reports --recursive
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import unicodedata
import uuid
from pathlib import Path

import httpx2 as httpx
import sqlalchemy as sa

from app.db.session import _session_factory
from app.models.enums import UserRole, UserStatus
from app.models.identity import User
from app.services.auth import hash_password
from app.services.storage import S3Storage, StorageObjectNotFound
from scripts.seed_sample_data import BASE_URL, _csrf, _storage_url

STUDENT_PASSWORD = "Password123!"
TEACHER_EMAIL = "teacher@docgrading.com"
COURSE_CODE = "CS101"
CONCURRENCY = 2


# LMS exports are named "<student>_<id>_<id>_<title>.pdf" ("..._LATE_<id>_...").
_LMS_NAME_RE = re.compile(r"^(?P<name>[^_]+)_(?:LATE_)?\d+_\d+_")


def repair_mojibake(text: str) -> str:
    """Undo UTF-8 names that a zip tool decoded as CP437 ("co╠éng" -> "công")."""
    try:
        repaired = text.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return unicodedata.normalize("NFC", text)
    return unicodedata.normalize("NFC", repaired)


def student_name_from_filename(stem: str) -> str:
    """Readable student name for a PDF: the LMS name part, or the whole stem."""
    fixed = repair_mojibake(stem)
    match = _LMS_NAME_RE.match(fixed)
    return (match.group("name") if match else fixed).strip()[:120] or fixed[:120]


def _student_email(pdf_sha256: str) -> str:
    # Gắn email với nội dung file để chạy lại không tạo trùng sinh viên.
    return f"bulk.{pdf_sha256[:10]}@docgrading.com"


async def _ensure_students(files: list[tuple[Path, bytes, str]]) -> None:
    pwd_hash = await asyncio.to_thread(hash_password, STUDENT_PASSWORD)
    session_factory = _session_factory()
    async with session_factory() as session:
        for path, _, sha in files:
            email = _student_email(sha)
            name = student_name_from_filename(path.stem)
            stmt = sa.select(User).where(sa.func.lower(User.email) == email)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                # Re-running also fixes names created by older versions.
                existing.display_name = name
                continue
            session.add(
                User(
                    id=uuid.uuid4(),
                    email=email,
                    display_name=name,
                    password_hash=pwd_hash,
                    roles=[UserRole.STUDENT],
                    status=UserStatus.ACTIVE,
                    revision=1,
                )
            )
        await session.commit()


async def _prepare_assignment(emails: list[str]) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{BASE_URL}/auth/login",
            json={"email": TEACHER_EMAIL, "password": STUDENT_PASSWORD},
        )
        assert resp.status_code == 200, f"Teacher login failed: {resp.text}"
        courses = (await client.get(f"{BASE_URL}/courses")).json()
        course = next((c for c in courses if c["code"] == COURSE_CODE), None)
        assert course, f"{COURSE_CODE} not found — run scripts.seed_sample_data first"
        assignments = (
            await client.get(f"{BASE_URL}/courses/{course['id']}/assignments")
        ).json()
        assignment = next(
            (a for a in assignments if "SRS" in a["title"] and a["status"] == "OPEN"),
            None,
        )
        assert assignment, "Open SRS assignment not found — run seed_sample_data first"
        for email in emails:
            # 409 nếu đã là thành viên — bỏ qua.
            await client.post(
                f"{BASE_URL}/courses/{course['id']}/members",
                headers=_csrf(client),
                json={"email": email},
            )
        return assignment["id"]


def _idempotency_key(path: Path, pdf_sha256: str) -> str:
    # Key phụ thuộc cả tên file: cùng nội dung nhưng khác tên (vd. NFC/NFD)
    # sẽ không bị 409 mà được API nhận diện là bản trùng.
    name_hash = hashlib.sha256(path.name.encode()).hexdigest()
    return f"bulk-{pdf_sha256[:24]}-{name_hash[:12]}"


def _restore_if_missing(object_key: str, pdf_bytes: bytes) -> bool:
    storage = S3Storage()
    try:
        storage.head(object_key)
        return False
    except StorageObjectNotFound:
        pass
    storage._internal.put_object(
        Bucket=storage.bucket,
        Key=object_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )
    return True


async def _upload_one(
    assignment_id: str,
    path: Path,
    pdf_bytes: bytes,
    sha: str,
    jobs_to_retry: list[str],
) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{BASE_URL}/auth/login",
            json={"email": _student_email(sha), "password": STUDENT_PASSWORD},
        )
        if resp.status_code != 200:
            return f"LOGIN FAILED {resp.status_code}"
        presign_resp = await client.post(
            f"{BASE_URL}/assignments/{assignment_id}/uploads/presign",
            headers=_csrf(client, {"Idempotency-Key": _idempotency_key(path, sha)}),
            json={
                "filename": path.name,
                "content_type": "application/pdf",
                "size_bytes": len(pdf_bytes),
                "sha256": sha,
            },
        )
        if presign_resp.status_code != 201:
            return f"PRESIGN FAILED {presign_resp.status_code}: {presign_resp.text}"
        presign = presign_resp.json()
        if presign["upload_url"] is None:
            # LocalStack mất object khi Docker sập -> ghi lại file nếu thiếu.
            restored = await asyncio.to_thread(
                _restore_if_missing, presign["object_key"], pdf_bytes
            )
            if presign["status"] == "ERROR" and presign["analysis_job_id"]:
                jobs_to_retry.append(presign["analysis_job_id"])
                return "ERROR before -> restored file, will retry"
            suffix = ", restored missing file" if restored else ""
            return f"already uploaded ({presign['status']}{suffix})"

        upload_resp = await client.post(
            _storage_url(presign["upload_url"]),
            data=presign["fields"],
            files={"file": (path.name, pdf_bytes, "application/pdf")},
        )
        if upload_resp.status_code != 204:
            return f"STORAGE FAILED {upload_resp.status_code}"

        comp_resp = await client.post(
            f"{BASE_URL}/document-versions/{presign['document_version_id']}/complete",
            headers=_csrf(client),
        )
        if comp_resp.status_code != 202:
            return f"COMPLETE FAILED {comp_resp.status_code}: {comp_resp.text}"
        return f"queued (job {comp_resp.json()['analysis_job_id']})"


async def _retry_jobs(job_ids: list[str]) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(
            f"{BASE_URL}/auth/login",
            json={"email": TEACHER_EMAIL, "password": STUDENT_PASSWORD},
        )
        for job_id in job_ids:
            resp = await client.post(
                f"{BASE_URL}/analysis-jobs/{job_id}/retry", headers=_csrf(client)
            )
            print(f"retry job {job_id}: {resp.status_code}")


async def main(folder: Path, recursive: bool) -> None:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    paths = sorted(folder.glob(pattern))
    if not paths:
        print(f"Không có file PDF nào trong {folder}")
        return
    files = []
    seen: dict[str, Path] = {}
    for path in paths:
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen:
            # Cùng nội dung -> cùng sinh viên + idempotency key, API sẽ trả 409.
            print(f"- {path.name}: bỏ qua, trùng nội dung với {seen[sha].name}")
            continue
        seen[sha] = path
        files.append((path, data, sha))
    print(f"Tìm thấy {len(files)} PDF (không trùng) trong {folder}")

    await _ensure_students(files)
    emails = [_student_email(sha) for _, _, sha in files]
    assignment_id = await _prepare_assignment(emails)

    semaphore = asyncio.Semaphore(CONCURRENCY)
    jobs_to_retry: list[str] = []

    async def run(path: Path, data: bytes, sha: str) -> None:
        async with semaphore:
            try:
                outcome = await _upload_one(
                    assignment_id, path, data, sha, jobs_to_retry
                )
            except httpx.HTTPError as exc:
                outcome = f"ERROR {type(exc).__name__}: {exc}"
        print(f"- {path.name}: {outcome}")

    await asyncio.gather(*(run(*item) for item in files))
    if jobs_to_retry:
        await _retry_jobs(jobs_to_retry)
    print("Xong. Theo dõi tiến độ xử lý: docker compose logs -f worker")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "folder",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "test_submissions",
    )
    parser.add_argument("--recursive", action="store_true", help="Quét cả thư mục con")
    args = parser.parse_args()
    asyncio.run(main(args.folder, args.recursive))
