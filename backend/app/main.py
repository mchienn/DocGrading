from fastapi import FastAPI

from app.api.routers.assignments import router as assignments_router
from app.api.routers.auth import router as auth_router
from app.api.routers.courses import router as courses_router
from app.api.routers.rubrics import router as rubrics_router
from app.api.routers.submissions import router as submissions_router
from app.api.routers.system import router as system_router


def create_app() -> FastAPI:
    application = FastAPI(
        title="DocGrading API",
        version="0.1.0",
        openapi_url="/api/v1/openapi.json",
    )
    application.include_router(system_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(courses_router, prefix="/api/v1")
    application.include_router(assignments_router, prefix="/api/v1")
    application.include_router(rubrics_router, prefix="/api/v1")
    application.include_router(submissions_router, prefix="/api/v1")
    return application


app = create_app()
