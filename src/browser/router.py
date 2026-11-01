from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from src.browser.dependencies import get_service
from src.browser.schemas import (
    ClickRequest,
    ErrorResponse,
    NavigateRequest,
    NavigationResponse,
    ScreenshotRequest,
    TabResponse,
    TypeRequest,
)
from src.browser.service import BrowserService

router = APIRouter(
    prefix="/v1/browser",
    tags=["browser"],
    responses={
        code: {"model": ErrorResponse, "description": description}
        for code, description in {
            404: "Unknown tab",
            409: "Tab capacity reached",
            422: "Invalid input or selector",
            502: "Browser operation failed",
            503: "Browser unavailable",
            504: "Operation timed out",
        }.items()
    },
)
Service = Annotated[BrowserService, Depends(get_service)]


@router.post(
    "/tabs",
    response_model=TabResponse,
    status_code=201,
    summary="Create an isolated tab",
)
async def create(service: Service):
    return await service.create()


@router.get("/tabs", response_model=list[TabResponse], summary="List active tabs")
async def list_tabs(service: Service):
    return await service.list_tabs()


@router.post(
    "/tabs/{tab_id}/navigate",
    response_model=NavigationResponse,
    summary="Navigate a tab",
)
async def navigate(tab_id: UUID, payload: NavigateRequest, service: Service):
    return await service.navigate(str(tab_id), **payload.model_dump())


@router.post(
    "/tabs/{tab_id}/click", response_model=TabResponse, summary="Click a unique target"
)
async def click(tab_id: UUID, payload: ClickRequest, service: Service):
    return await service.click(str(tab_id), **payload.model_dump())


@router.post(
    "/tabs/{tab_id}/type",
    response_model=TabResponse,
    summary="Replace or append input text",
)
async def type_text(tab_id: UUID, payload: TypeRequest, service: Service):
    return await service.type(str(tab_id), **payload.model_dump())


@router.post(
    "/tabs/{tab_id}/screenshot",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "PNG screenshot"}},
    summary="Capture a rendered page",
)
async def screenshot(tab_id: UUID, payload: ScreenshotRequest, service: Service):
    return Response(
        await service.screenshot(str(tab_id), **payload.model_dump()),
        media_type="image/png",
    )


@router.post(
    "/tabs/{tab_id}/clear",
    response_model=TabResponse,
    summary="Reset the isolated session",
)
async def clear(tab_id: UUID, service: Service):
    return await service.clear(str(tab_id))


@router.delete(
    "/tabs/{tab_id}", status_code=204, summary="Close a tab and release capacity"
)
async def delete(tab_id: UUID, service: Service):
    await service.delete(str(tab_id))
    return Response(status_code=204)
