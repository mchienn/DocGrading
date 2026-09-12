import asyncio
import contextlib
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.routers.assignments import router as assignments_router
from app.api.routers.auth import router as auth_router
from app.api.routers.courses import router as courses_router
from app.api.routers.notifications import router as notifications_router
from app.api.routers.rubrics import router as rubrics_router
from app.api.routers.submissions import router as submissions_router
from app.api.routers.system import router as system_router
from app.core.config import get_settings
from app.services.analysis_dispatch import (
    run_analysis_dispatch_poller,
    wait_for_analysis_dispatch_publications,
)
from app.services.auth import auth_cookie_names, csrf_token_for_session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_settings()
    dispatch_poller = asyncio.create_task(run_analysis_dispatch_poller())
    try:
        yield
    finally:
        dispatch_poller.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await dispatch_poller
        await wait_for_analysis_dispatch_publications()


def create_app() -> FastAPI:
    application = FastAPI(
        title="DocGrading API",
        version="0.1.0",
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def require_csrf_token(request: Request, call_next):  # noqa: ANN001, ANN202
        unsafe = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if unsafe and request.url.path != "/api/v1/auth/login":
            session_cookie_name, csrf_cookie_name = auth_cookie_names(
                get_settings().session_cookie_secure
            )
            cookie_token = request.cookies.get(csrf_cookie_name)
            header_token = request.headers.get("X-CSRF-Token")
            try:
                expected_token = csrf_token_for_session(
                    uuid.UUID(request.cookies.get(session_cookie_name, ""))
                )
            except ValueError:
                expected_token = None
            if (
                not cookie_token
                or not header_token
                or not expected_token
                or not secrets.compare_digest(cookie_token, expected_token)
                or not secrets.compare_digest(header_token, expected_token)
            ):
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "CSRF validation failed"},
                )
        return await call_next(request)

    application.include_router(system_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(courses_router, prefix="/api/v1")
    application.include_router(assignments_router, prefix="/api/v1")
    application.include_router(rubrics_router, prefix="/api/v1")
    application.include_router(notifications_router, prefix="/api/v1")
    application.include_router(submissions_router, prefix="/api/v1")
    return application


app = create_app()
