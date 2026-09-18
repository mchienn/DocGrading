"""Seed real data: 3 courses + 1 teacher account"""
import asyncio
import uuid
from app.db.session import _session_factory
from app.models.identity import User
from app.models.enums import UserRole, UserStatus, MembershipRole, MembershipStatus
from app.models.course import Course, Membership
from app.services.auth import hash_password


async def seed():
    password_hash = await asyncio.to_thread(hash_password, "Teacher@2026")

    # Teacher user
    teacher_id = uuid.uuid4()
    teacher = User(
        id=teacher_id,
        email="teacher@docgrading.edu.vn",
        display_name="Giảng viên",
        password_hash=password_hash,
        roles=[UserRole.TEACHER],
        status=UserStatus.ACTIVE,
        revision=1,
    )

    # 3 Courses
    courses = [
        Course(
            id=uuid.uuid4(),
            code="INT2208-01",
            name="Công nghệ phần mềm",
            term="Kỳ 2 - 2024",
            owner_teacher_id=teacher_id,
            revision=1,
        ),
        Course(
            id=uuid.uuid4(),
            code="CS4899",
            name="Khóa luận tốt nghiệp",
            term="Academic year 2024",
            owner_teacher_id=teacher_id,
            revision=1,
        ),
        Course(
            id=uuid.uuid4(),
            code="INT3501",
            name="Thực tập doanh nghiệp",
            term="Summer 2024",
            owner_teacher_id=teacher_id,
            revision=1,
        ),
    ]

    # Teacher memberships in all courses
    memberships = [
        Membership(
            id=uuid.uuid4(),
            course_id=course.id,
            user_id=teacher_id,
            role=MembershipRole.TEACHER,
            status=MembershipStatus.ACTIVE,
        )
        for course in courses
    ]

    async with _session_factory()() as db:
        db.add(teacher)
        db.add_all(courses)
        db.add_all(memberships)
        await db.commit()

    print("✅ Seeded real data:")
    print(f"   Teacher: teacher@docgrading.edu.vn")
    print(f"   Password: Teacher@2026")
    print(f"   Courses:")
    for course in courses:
        print(f"     - {course.code}: {course.name}")


if __name__ == "__main__":
    asyncio.run(seed())
