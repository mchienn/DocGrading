from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.schemas_operations import (
    AdminAnalysisJobDetailResponse,
    AdminAnalysisJobListResponse,
    AdminAuditEventListResponse,
    AdminDashboardResponse,
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdateRequest,
)
from app.db.session import get_db_session
from app.models.enums import AnalysisJobStatus, UserRole, UserStatus
from app.models.identity import User
from app.services import analysis_job as job_svc
from app.services import operations as operations_svc
from app.services.analysis_dispatch import dispatch_analysis_job_now

router = APIRouter(tags=["operations"])
metrics_router = APIRouter(tags=["operations"])
admin_user = require_roles(UserRole.ADMIN)


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    role: UserRole | None = Query(default=None),
    user_status: UserStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, min_length=1, max_length=320),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    _admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> AdminUserListResponse:
    return await operations_svc.list_users(
        db,
        role=role,
        user_status=user_status,
        search=search,
        page=page,
        page_size=page_size,
    )


class _CreateUserRoute(APIRoute):
    def get_route_handler(self):  # noqa: ANN202
        handler = super().get_route_handler()

        async def safe_handler(request):  # noqa: ANN001, ANN202
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # FastAPI validation inputs may contain the plaintext password.
                raise HTTPException(
                    status_code=422,
                    detail=[
                        {key: error[key] for key in ("loc", "msg", "type")}
                        for error in exc.errors()
                    ],
                ) from None

        return safe_handler


async def create_user(
    body: AdminUserCreateRequest,
    admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> AdminUserResponse:
    try:
        response = await operations_svc.create_user(
            db, body=body, actor_user_id=admin.id
        )
        await db.commit()
        return response
    except IntegrityError as exc:
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(
            status_code=409, detail="Email is already registered"
        ) from None


router.add_api_route(
    "/users",
    create_user,
    methods=["POST"],
    status_code=201,
    response_model=AdminUserResponse,
    route_class_override=_CreateUserRoute,
)


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: uuid.UUID,
    _admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> AdminUserResponse:
    return await operations_svc.get_user(db, user_id)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: AdminUserUpdateRequest,
    admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> AdminUserResponse:
    try:
        response = await operations_svc.update_user(
            db,
            user_id=user_id,
            body=body,
            actor_user_id=admin.id,
        )
        await db.commit()
        return response
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="User roles conflict with existing Course or membership data",
        ) from exc


@router.get("/operations/analysis-jobs", response_model=AdminAnalysisJobListResponse)
async def list_analysis_jobs(
    job_status: AnalysisJobStatus | None = Query(default=None, alias="status"),
    course_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    _admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> AdminAnalysisJobListResponse:
    return await operations_svc.list_analysis_jobs(
        db,
        job_status=job_status,
        course_id=course_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/operations/analysis-jobs/{job_id}",
    response_model=AdminAnalysisJobDetailResponse,
)
async def get_analysis_job(
    job_id: uuid.UUID,
    _admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> AdminAnalysisJobDetailResponse:
    return await operations_svc.get_analysis_job(db, job_id)


@router.post(
    "/operations/analysis-jobs/{job_id}/retry",
    response_model=AdminAnalysisJobDetailResponse,
)
async def retry_analysis_job(
    job_id: uuid.UUID,
    admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> AdminAnalysisJobDetailResponse:
    job = await job_svc.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    job = await job_svc.retry_job(db, job, admin)
    response = await operations_svc.get_analysis_job(db, job.id)
    await db.commit()
    await dispatch_analysis_job_now(job.id)
    return response


@router.get("/operations/audit-events", response_model=AdminAuditEventListResponse)
async def list_audit_events(
    actor_user_id: uuid.UUID | None = Query(default=None),
    resource_type: str | None = Query(default=None, min_length=1, max_length=128),
    from_time: datetime | None = Query(default=None),
    to_time: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    _admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> AdminAuditEventListResponse:
    return await operations_svc.list_audit_events(
        db,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        from_time=from_time,
        to_time=to_time,
        page=page,
        page_size=page_size,
    )


@router.get("/operations/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(
    _admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> AdminDashboardResponse:
    return await operations_svc.get_dashboard(db)


@metrics_router.get("/metrics", response_class=PlainTextResponse)
async def get_metrics(
    _admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlainTextResponse:
    return PlainTextResponse(
        await operations_svc.get_metrics(db),
        media_type="text/plain; version=0.0.4",
    )
