"""Seed sample data for DocGrading local testing."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit

import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

BASE_URL = "http://localhost:8000/api/v1"
STORAGE_URL = "http://localhost:9000"


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
    content.set_data(
        f"BT /F1 14 Tf 72 720 Td (DocGrading Sample Document) Tj ET\n"
        f"BT /F1 11 Tf 72 680 Td ({text}) Tj ET\n"
        f"BT /F1 10 Tf 72 650 Td (Section 1: Introduction and System Overview) Tj ET\n"
        f"BT /F1 10 Tf 72 620 Td (Section 2: Functional and Non-Functional Requirements) Tj ET\n"
        f"BT /F1 10 Tf 72 590 Td (Section 3: Use Case Models and Verification) Tj ET".encode("ascii")
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _storage_url(presigned_url: str) -> str:
    source = urlsplit(presigned_url)
    target = urlsplit(STORAGE_URL)
    return urlunsplit((target.scheme, target.netloc, source.path, source.query, ""))


def _csrf(client: httpx.AsyncClient, extra: dict | None = None) -> dict[str, str]:
    headers: dict[str, str] = dict(extra or {})
    token = client.cookies.get("csrf_token")
    if token:
        headers["X-CSRF-Token"] = token
    return headers


async def main() -> None:
    now = datetime.now(UTC)
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Teacher Login
        print("Logging in Teacher...")
        resp = await client.post(f"{BASE_URL}/auth/login", json={"email": "teacher@docgrading.com", "password": "Password123!"})
        assert resp.status_code == 200, f"Teacher login failed: {resp.text}"
        print("Teacher logged in.")

        # 2. Courses
        courses = (await client.get(f"{BASE_URL}/courses")).json()
        cs101 = next((c for c in courses if c["code"] == "CS101"), None)
        if not cs101:
            print("Creating course CS101...")
            resp = await client.post(f"{BASE_URL}/courses", headers=_csrf(client), json={
                "code": "CS101",
                "name": "Nhập môn Công nghệ Phần mềm",
                "term": "2026-SPRING",
            })
            assert resp.status_code == 201, f"Failed creating CS101: {resp.text}"
            cs101 = resp.json()
        print(f"CS101 ID: {cs101['id']}")

        cs202 = next((c for c in courses if c["code"] == "CS202"), None)
        if not cs202:
            print("Creating course CS202...")
            resp = await client.post(f"{BASE_URL}/courses", headers=_csrf(client), json={
                "code": "CS202",
                "name": "Kiến trúc và Thiết kế Phần mềm",
                "term": "2026-FALL",
            })
            assert resp.status_code == 201, f"Failed creating CS202: {resp.text}"
            cs202 = resp.json()
        print(f"CS202 ID: {cs202['id']}")

        # 3. Add Student to CS101
        print("Enrolling student into CS101...")
        add_resp = await client.post(
            f"{BASE_URL}/courses/{cs101['id']}/members",
            headers=_csrf(client),
            json={"email": "student@docgrading.com"},
        )
        print(f"Student enrollment status: {add_resp.status_code}")

        # 4. Create Join Code for CS202
        join_code_resp = await client.get(f"{BASE_URL}/courses/{cs202['id']}/join-code")
        if join_code_resp.status_code == 404:
            print("Generating join code for CS202...")
            resp = await client.post(
                f"{BASE_URL}/courses/{cs202['id']}/join-code",
                headers=_csrf(client),
                json={"expires_at": (now + timedelta(days=30)).isoformat()}
            )
            assert resp.status_code == 201, f"Failed creating join code: {resp.text}"
            join_code_data = resp.json()
        else:
            join_code_data = join_code_resp.json()
        print(f"CS202 Join Code: {join_code_data['code']}")

        # 5. Rubric
        rubrics = (await client.get(f"{BASE_URL}/rubrics")).json()
        rubric = next((r for r in rubrics if r["name"] == "Bảng tiêu chí chấm SRS IEEE 830"), None)
        if not rubric:
            print("Creating Rubric...")
            resp = await client.post(f"{BASE_URL}/rubrics", headers=_csrf(client), json={
                "name": "Bảng tiêu chí chấm SRS IEEE 830",
                "calculation_method": "WEIGHTED_SUM",
                "description": "Tiêu chí đánh giá tài liệu Đặc tả Yêu cầu phần mềm",
            })
            assert resp.status_code == 201, f"Failed creating rubric: {resp.text}"
            rubric = resp.json()
            rubric_id = rubric["id"]

            await client.post(f"{BASE_URL}/rubrics/{rubric_id}/criteria", headers=_csrf(client), json={
                "code": "SRS-01",
                "title": "Cấu trúc & Định dạng IEEE 830",
                "description": "Báo cáo có đủ 3 phần chính, phân cấp rõ ràng",
                "weight": 30,
                "position": 1,
                "evaluation_method": "AI",
            })
            await client.post(f"{BASE_URL}/rubrics/{rubric_id}/criteria", headers=_csrf(client), json={
                "code": "SRS-02",
                "title": "Yêu cầu Chức năng & Phi chức năng",
                "description": "Yêu cầu đo lường được, không mơ hồ, có mã định danh",
                "weight": 40,
                "position": 2,
                "evaluation_method": "AI",
            })
            await client.post(f"{BASE_URL}/rubrics/{rubric_id}/criteria", headers=_csrf(client), json={
                "code": "SRS-03",
                "title": "Đặc tả Use Case & Kịch bản",
                "description": "Luồng chính, luồng phụ, ngoại lệ và tiền điều kiện đầy đủ",
                "weight": 30,
                "position": 3,
                "evaluation_method": "AI",
            })
            pub_resp = await client.post(f"{BASE_URL}/rubrics/{rubric_id}/publish", headers=_csrf(client))
            assert pub_resp.status_code == 200, f"Failed publishing rubric: {pub_resp.text}"
            rubric = (await client.get(f"{BASE_URL}/rubrics/{rubric_id}")).json()
        print(f"Rubric ID: {rubric['id']} (Status: {rubric['status']})")

        # 6. Assignments in CS101
        existing_assignments = (await client.get(f"{BASE_URL}/courses/{cs101['id']}/assignments")).json()
        as1 = next((a for a in existing_assignments if "SRS" in a["title"]), None)
        if not as1:
            print("Creating Assignment 1 (OPEN)...")
            resp = await client.post(f"{BASE_URL}/courses/{cs101['id']}/assignments", headers=_csrf(client), json={
                "rubric_version_id": rubric["id"],
                "title": "Bài tập lớn: Báo cáo SRS Hoàn chỉnh",
                "description": "Nộp file PDF báo cáo đặc tả yêu cầu IEEE 830.",
                "due_at": (now + timedelta(days=7)).isoformat(),
                "max_submissions": 5,
            })
            assert resp.status_code == 201, f"Failed creating Assignment 1: {resp.text}"
            as1 = resp.json()
            pub_as1 = await client.post(f"{BASE_URL}/courses/{cs101['id']}/assignments/{as1['id']}/publish", headers=_csrf(client))
            assert pub_as1.status_code == 200, f"Failed publishing Assignment 1: {pub_as1.text}"
            as1 = (await client.get(f"{BASE_URL}/courses/{cs101['id']}/assignments/{as1['id']}")).json()
        print(f"Assignment 1 ID: {as1['id']} (Status: {as1['status']})")

        as2 = next((a for a in existing_assignments if "Kiến trúc" in a["title"]), None)
        if not as2:
            print("Creating Assignment 2 (DRAFT)...")
            resp = await client.post(f"{BASE_URL}/courses/{cs101['id']}/assignments", headers=_csrf(client), json={
                "rubric_version_id": rubric["id"],
                "title": "Bài tập 2: Thiết kế Kiến trúc Hệ thống",
                "description": "Đang chuẩn bị đề bài.",
                "due_at": (now + timedelta(days=14)).isoformat(),
                "max_submissions": 3,
            })
            assert resp.status_code == 201, f"Failed creating Assignment 2: {resp.text}"
            as2 = resp.json()
        print(f"Assignment 2 ID: {as2['id']} (Status: {as2['status']})")

        as3 = next((a for a in existing_assignments if "Khởi động" in a["title"]), None)
        if not as3:
            print("Creating Assignment 3 (CLOSED)...")
            resp = await client.post(f"{BASE_URL}/courses/{cs101['id']}/assignments", headers=_csrf(client), json={
                "rubric_version_id": rubric["id"],
                "title": "Bài tập Khởi động Tuần 1",
                "description": "Khảo sát đề tài và lập nhóm.",
                "due_at": (now - timedelta(days=1)).isoformat(),
                "max_submissions": 3,
            })
            assert resp.status_code == 201, f"Failed creating Assignment 3: {resp.text}"
            as3 = resp.json()
            await client.post(f"{BASE_URL}/courses/{cs101['id']}/assignments/{as3['id']}/publish", headers=_csrf(client))
            await client.post(f"{BASE_URL}/courses/{cs101['id']}/assignments/{as3['id']}/close", headers=_csrf(client))
            as3 = (await client.get(f"{BASE_URL}/courses/{cs101['id']}/assignments/{as3['id']}")).json()
        print(f"Assignment 3 ID: {as3['id']} (Status: {as3['status']})")

        # 7. Student Submits PDF to Assignment 1
        print("Logging in Student...")
        await client.post(f"{BASE_URL}/auth/logout", headers=_csrf(client))
        resp = await client.post(f"{BASE_URL}/auth/login", json={"email": "student@docgrading.com", "password": "Password123!"})
        assert resp.status_code == 200, f"Student login failed: {resp.text}"
        print("Student logged in.")

        pdf_bytes = _text_pdf("Sample Student SRS Submission with Full Requirements Specification")
        pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        filename = "SRS_Report_Group01.pdf"
        presign_key = f"presign-{int(datetime.now(UTC).timestamp())}"
        presign_resp = await client.post(
            f"{BASE_URL}/assignments/{as1['id']}/uploads/presign",
            headers=_csrf(client, {"Idempotency-Key": presign_key}),
            json={
                "filename": filename,
                "content_type": "application/pdf",
                "size_bytes": len(pdf_bytes),
                "sha256": pdf_sha256,
            },
        )
        assert presign_resp.status_code == 201, f"Presign failed: {presign_resp.text}"
        presign = presign_resp.json()

        print("Uploading PDF to storage...")
        upload_url = _storage_url(presign["upload_url"])
        upload_resp = await client.post(
            upload_url,
            data=presign["fields"],
            files={"file": (filename, pdf_bytes, "application/pdf")},
        )
        assert upload_resp.status_code == 204, f"Storage upload failed: {upload_resp.status_code}"

        print("Marking upload complete...")
        comp_resp = await client.post(
            f"{BASE_URL}/document-versions/{presign['document_version_id']}/complete",
            headers=_csrf(client),
        )
        assert comp_resp.status_code == 202, f"Complete upload failed: {comp_resp.text}"
        completion = comp_resp.json()
        job_id = completion["analysis_job_id"]
        submission_id = completion["submission_id"]
        doc_version_id = completion["document_version_id"]
        print(f"Submission ID: {submission_id}, Analysis Job ID: {job_id}")

        print("Waiting for Analysis Job to complete...")
        for _ in range(60):
            job = (await client.get(f"{BASE_URL}/analysis-jobs/{job_id}")).json()
            if job["status"] == "DONE":
                print("Analysis Job finished: DONE!")
                break
            elif job["status"] == "ERROR":
                print(f"Analysis Job failed: {job.get('error_code')}")
                break
            await asyncio.sleep(0.5)

        # 8. Teacher Reviews & Publishes Result
        print("Logging in Teacher for review...")
        await client.post(f"{BASE_URL}/auth/logout", headers=_csrf(client))
        await client.post(f"{BASE_URL}/auth/login", json={"email": "teacher@docgrading.com", "password": "Password123!"})

        print("Locking submission for review...")
        lock_resp = await client.post(f"{BASE_URL}/submissions/{submission_id}/review-lock", headers=_csrf(client))
        assert lock_resp.status_code == 200, f"Review lock failed: {lock_resp.text}"

        draft = (await client.get(f"{BASE_URL}/submissions/{submission_id}/review-draft")).json()
        print("Submitting review draft...")
        draft_resp = await client.put(
            f"{BASE_URL}/submissions/{submission_id}/review-draft",
            headers=_csrf(client),
            json={
                "document_version_id": doc_version_id,
                "revision": draft["revision"],
                "comment": "Báo cáo trình bày rõ ràng, đáp ứng tốt cấu trúc IEEE 830.",
                "decisions": [],
            },
        )
        assert draft_resp.status_code == 200, f"Review draft save failed: {draft_resp.text}"

        print("Approving and publishing result...")
        approve_key = f"approve-{doc_version_id}"
        publish_key = f"publish-{doc_version_id}"
        app_resp = await client.post(
            f"{BASE_URL}/document-versions/{doc_version_id}/approve",
            headers=_csrf(client, {"Idempotency-Key": approve_key}),
        )
        assert app_resp.status_code == 200, f"Approve failed: {app_resp.text}"

        pub_resp = await client.post(
            f"{BASE_URL}/document-versions/{doc_version_id}/publish",
            headers=_csrf(client, {"Idempotency-Key": publish_key}),
            json={"reason": "Giảng viên đã đánh giá và chốt điểm đợt 1."},
        )
        assert pub_resp.status_code == 200, f"Publish failed: {pub_resp.text}"

        await client.delete(f"{BASE_URL}/submissions/{submission_id}/review-lock", headers=_csrf(client))
        print("Published successfully!")

        print("\n==========================================")
        print("SAMPLE DATA SEED COMPLETE!")
        print("==========================================")


if __name__ == "__main__":
    asyncio.run(main())
