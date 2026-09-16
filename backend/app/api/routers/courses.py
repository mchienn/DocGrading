"""Course CRUD endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_active_owned_course,
    get_owned_course,
    require_roles,
)
from app.api.schemas_course import (
    CourseCreate,
    CourseInviteResponse,
    CourseJoinCodeCreateRequest,
    CourseJoinCodeResponse,
    CourseJoinCodeUpdateRequest,
    CourseJoinRequest,
    CourseJoinResponse,
    CourseMemberAddRequest,
    CourseMemberAddResponse,
    CourseMemberListResponse,
    CourseMemberRemoveRequest,
    CourseMemberResponse,
    CourseResponse,
    CourseUpdate,
)
from app.db.session import get_db_session
from app.models.course import Course, Membership
from app.models.enums import MembershipAddOutcome, MembershipStatus, UserRole
from app.models.identity import User
from app.services import course as course_svc
from app.services import course_join as join_svc


def _member_response(membership: Membership, user: User) -> CourseMemberResponse:
    return CourseMemberResponse(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=membership.status,
        joined_at=membership.joined_at,
        joined_via=membership.joined_via,
    )


join_router = APIRouter(prefix="/course-joins", tags=["courses"])
router = APIRouter(prefix="/courses", tags=["courses"])


@router.get(
    "/{course_id}/members",
    response_model=CourseMemberListResponse,
)
async def list_course_members(
    course: Course = Depends(get_owned_course),
    member_status: MembershipStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> CourseMemberListResponse:
    rows, total = await course_svc.list_members(
        db,
        course_id=course.id,
        member_status=member_status,
        page=page,
        page_size=page_size,
    )
    return CourseMemberListResponse(
        items=[_member_response(membership, user) for membership, user in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/{course_id}/members",
    response_model=CourseMemberAddResponse,
    status_code=201,
)
async def add_course_member(
    body: CourseMemberAddRequest,
    course: Course = Depends(get_active_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseMemberAddResponse:
    outcome, membership, invite = await course_svc.add_member(
        db,
        course_id=course.id,
        email=body.email,
        actor_user_id=user.id,
        reason=body.reason,
    )
    await db.commit()
    if outcome == MembershipAddOutcome.INVITED:
        assert invite is not None
        return CourseMemberAddResponse(
            outcome=outcome,
            invite=CourseInviteResponse(
                id=invite.id,
                course_id=invite.course_id,
                email=invite.email,
                status="PENDING",
                created_at=invite.created_at,
            ),
        )
    assert membership is not None
    member_user = await db.get(User, membership.user_id)
    assert member_user is not None
    return CourseMemberAddResponse(
        outcome=outcome,
        member=_member_response(membership, member_user),
    )


@router.delete("/{course_id}/members/{user_id}", status_code=204)
async def remove_course_member(
    user_id: uuid.UUID,
    body: CourseMemberRemoveRequest | None = None,
    course: Course = Depends(get_active_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await course_svc.remove_member(
        db,
        course_id=course.id,
        user_id=user_id,
        actor_user_id=user.id,
        reason=body.reason if body is not None else None,
    )
    await db.commit()


@router.post("", response_model=CourseResponse, status_code=201)
async def create_course(
    body: CourseCreate,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseResponse:
    """Create a new course (Teacher/Admin only)."""
    course = await course_svc.create_course(
        db,
        code=body.code,
        name=body.name,
        term=body.term,
        owner_teacher_id=user.id,
    )
    await db.commit()
    return CourseResponse.model_validate(course)


@router.get("", response_model=list[CourseResponse])
async def list_courses(
    user: User = Depends(
        require_roles(UserRole.ADMIN, UserRole.TEACHER, UserRole.STUDENT)
    ),
    db: AsyncSession = Depends(get_db_session),
) -> list[CourseResponse]:
    """List courses visible to the current role scope."""
    if UserRole.ADMIN in user.roles:
        courses = await course_svc.list_courses(db)
    elif UserRole.TEACHER in user.roles:
        courses = await course_svc.list_courses(db, owner_teacher_id=user.id)
    else:
        courses = await course_svc.list_courses(db, member_user_id=user.id)
    return [CourseResponse.model_validate(course) for course in courses]


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course: Course = Depends(get_owned_course),
) -> CourseResponse:
    """Get a single course (owner or Admin)."""
    return CourseResponse.model_validate(course)


@router.put("/{course_id}", response_model=CourseResponse)
async def update_course(
    body: CourseUpdate,
    course: Course = Depends(get_active_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseResponse:
    """Update a course (owner or Admin)."""
    course = await course_svc.update_course(
        db,
        course,
        actor_user_id=user.id,
        name=body.name,
        term=body.term,
    )
    await db.commit()
    return CourseResponse.model_validate(course)


@router.delete("/{course_id}", status_code=204)
async def delete_course(
    course: Course = Depends(get_active_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a course (owner or Admin)."""
    await course_svc.delete_course(db, course, actor_user_id=user.id)
    await db.commit()


@router.post("/{course_id}/archive", response_model=CourseResponse)
async def archive_course(
    course: Course = Depends(get_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseResponse:
    """Archive an ACTIVE course (owner or Admin)."""
    course = await course_svc.archive_course(db, course, actor_user_id=user.id)
    await db.commit()
    return CourseResponse.model_validate(course)


def _join_code_response(row) -> CourseJoinCodeResponse:  # noqa: ANN001
    return CourseJoinCodeResponse(
        id=row.id,
        course_id=row.course_id,
        code=row.code,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        status=join_svc._state(row),
        join_url=join_svc.join_url(row.code),
        qr_url=join_svc.qr_url(row.course_id),
    )


@router.post(
    "/{course_id}/join-code",
    response_model=CourseJoinCodeResponse,
    status_code=201,
)
async def create_course_join_code(
    body: CourseJoinCodeCreateRequest,
    course: Course = Depends(get_active_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseJoinCodeResponse:
    row = await join_svc.create_join_code(
        db, course_id=course.id, expires_at=body.expires_at, actor_user_id=user.id
    )
    await db.commit()
    return _join_code_response(row)


@router.get(
    "/{course_id}/join-code",
    response_model=CourseJoinCodeResponse,
)
async def get_course_join_code(
    course: Course = Depends(get_owned_course),
    db: AsyncSession = Depends(get_db_session),
) -> CourseJoinCodeResponse:
    row = await join_svc.get_join_code(db, course_id=course.id)
    return _join_code_response(row)


@router.put(
    "/{course_id}/join-code",
    response_model=CourseJoinCodeResponse,
)
async def update_course_join_code(
    body: CourseJoinCodeUpdateRequest,
    course: Course = Depends(get_active_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseJoinCodeResponse:
    row = await join_svc.update_join_code(
        db, course_id=course.id, expires_at=body.expires_at, actor_user_id=user.id
    )
    await db.commit()
    return _join_code_response(row)


@router.delete(
    "/{course_id}/join-code",
    response_model=CourseJoinCodeResponse,
)
async def revoke_course_join_code(
    course: Course = Depends(get_active_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseJoinCodeResponse:
    row = await join_svc.revoke_join_code(
        db, course_id=course.id, actor_user_id=user.id
    )
    await db.commit()
    return _join_code_response(row)


@router.post(
    "/{course_id}/join-code/regenerate",
    response_model=CourseJoinCodeResponse,
)
async def regenerate_course_join_code(
    body: CourseJoinCodeCreateRequest,
    course: Course = Depends(get_active_owned_course),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseJoinCodeResponse:
    row = await join_svc.regenerate_join_code(
        db, course_id=course.id, expires_at=body.expires_at, actor_user_id=user.id
    )
    await db.commit()
    return _join_code_response(row)


@router.get(
    "/{course_id}/join-code/qr",
    response_class=Response,
)
async def get_course_join_code_qr(
    course: Course = Depends(get_owned_course),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    row = await join_svc.get_join_code(db, course_id=course.id)
    return Response(join_svc.render_qr_svg(row.code), media_type="image/svg+xml")


@join_router.post("", response_model=CourseJoinResponse)
async def join_course_by_code(
    body: CourseJoinRequest,
    request: Request,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db_session),
) -> CourseJoinResponse:
    outcome, membership, course = await join_svc.join_course(
        db, code=body.code, user=user, request=request
    )
    await db.commit()
    return CourseJoinResponse(
        outcome=outcome,
        membership_id=membership.id,
        course_code=course.code,
        course_name=course.name,
    )
