from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, require_roles
from app.api.schemas_llm import (
    LLMCatalogTestResponse,
    LLMProviderListResponse,
    LLMProviderResponse,
    LLMProviderUpdateRequest,
    LLMRouteActivationRequest,
    LLMRouteResponse,
    LLMRouteUpdateRequest,
)
from app.models import LLMProviderConfig
from app.models.enums import LLMProvider, UserRole
from app.models.identity import User
from app.services import llm_providers

_admin = require_roles(UserRole.ADMIN)


class _SafeValidationRoute(APIRoute):
    def get_route_handler(self):  # noqa: ANN202
        handler = super().get_route_handler()

        async def safe_handler(request: Request):  # noqa: ANN202
            try:
                return await handler(request)
            except RequestValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=[
                        {key: item[key] for key in ("loc", "msg", "type")}
                        for item in exc.errors()
                    ],
                ) from None

        return safe_handler


router = APIRouter(
    prefix="/operations/llm",
    tags=["llm-operations"],
    dependencies=[Depends(_admin)],
    route_class=_SafeValidationRoute,
)


def _revision(if_match: str | None) -> int:
    if (
        if_match is None
        or not if_match.startswith('"rev-')
        or not if_match.endswith('"')
    ):
        raise HTTPException(status_code=428, detail="If-Match is required")
    try:
        value = int(if_match[5:-1])
    except ValueError as exc:
        raise HTTPException(status_code=428, detail="If-Match is required") from exc
    if value < 1:
        raise HTTPException(status_code=428, detail="If-Match is required")
    return value


@router.get("/providers", response_model=LLMProviderListResponse)
async def list_providers(
    db: AsyncSession = Depends(get_db_session),
) -> LLMProviderListResponse:
    return LLMProviderListResponse(items=await llm_providers.list_providers(db))


async def _provider(db: AsyncSession, provider: LLMProvider) -> LLMProviderConfig:
    row = await db.scalar(
        sa.select(LLMProviderConfig).where(LLMProviderConfig.provider == provider)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    return row


@router.put("/providers/{provider}", response_model=LLMProviderResponse)
async def update_provider(
    provider: LLMProvider,
    body: LLMProviderUpdateRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db_session),
) -> LLMProviderResponse:
    row = await _provider(db, provider)
    result = await llm_providers.update_provider(
        db,
        row=row,
        body=body,
        expected_revision=_revision(if_match),
        actor_user_id=admin.id,
    )
    await db.commit()
    return result


@router.delete("/providers/{provider}/credential", response_model=LLMProviderResponse)
async def remove_credential(
    provider: LLMProvider,
    if_match: str | None = Header(default=None, alias="If-Match"),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db_session),
) -> LLMProviderResponse:
    row = await _provider(db, provider)
    result = await llm_providers.delete_credential(
        db, row=row, expected_revision=_revision(if_match), actor_user_id=admin.id
    )
    await db.commit()
    return result


@router.post("/providers/{provider}/test", response_model=LLMCatalogTestResponse)
async def test_provider(
    provider: LLMProvider,
    if_match: str | None = Header(default=None, alias="If-Match"),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db_session),
) -> LLMCatalogTestResponse:
    row = await _provider(db, provider)
    result = await llm_providers.test_catalog(
        db, row=row, expected_revision=_revision(if_match), actor_user_id=admin.id
    )
    await db.commit()
    return result


@router.get("/routes/CITATION_SEMANTIC", response_model=LLMRouteResponse)
async def get_semantic_route(
    db: AsyncSession = Depends(get_db_session),
) -> LLMRouteResponse:
    return await llm_providers.get_route(db)


@router.put("/routes/CITATION_SEMANTIC", response_model=LLMRouteResponse)
async def update_semantic_route(
    body: LLMRouteUpdateRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db_session),
) -> LLMRouteResponse:
    result = await llm_providers.save_route(
        db, body=body, expected_revision=_revision(if_match), actor_user_id=admin.id
    )
    await db.commit()
    return result


@router.post("/routes/CITATION_SEMANTIC/activate", response_model=LLMRouteResponse)
async def activate_semantic_route(
    body: LLMRouteActivationRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db_session),
) -> LLMRouteResponse:
    result = await llm_providers.set_route_active(
        db,
        expected_revision=_revision(if_match),
        actor_user_id=admin.id,
        activate=True,
        request=body,
    )
    await db.commit()
    return result


@router.post("/routes/CITATION_SEMANTIC/deactivate", response_model=LLMRouteResponse)
async def deactivate_semantic_route(
    if_match: str | None = Header(default=None, alias="If-Match"),
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db_session),
) -> LLMRouteResponse:
    result = await llm_providers.set_route_active(
        db,
        expected_revision=_revision(if_match),
        actor_user_id=admin.id,
        activate=False,
    )
    await db.commit()
    return result
