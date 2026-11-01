import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.browser.config import BrowserSettings
from src.browser.exceptions import BrowserError
from src.browser.router import router
from src.browser.service import BrowserService


@asynccontextmanager
async def lifespan(app):
    service = BrowserService(BrowserSettings())
    await service.start()
    app.state.browser = service
    try:
        yield
    finally:
        await service.close()


app = FastAPI(
    title="Browser API",
    lifespan=lifespan,
    openapi_url="/openapi.json"
    if os.getenv("ENVIRONMENT", "local") in {"local", "staging"}
    else None,
)
app.include_router(router)


@app.exception_handler(BrowserError)
async def browser_error(request: Request, exc: BrowserError):
    return JSONResponse(
        {"detail": exc.detail, "code": exc.code}, status_code=exc.status
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        {"detail": "Invalid request fields", "code": "invalid_input"}, status_code=422
    )


@app.get("/health/live", summary="Process liveness")
async def live():
    return {"status": "ok"}


@app.get("/health/ready", summary="Browser readiness")
async def ready(request: Request):
    service = getattr(request.app.state, "browser", None)
    ready = bool(service and service.ready)
    return JSONResponse({"ready": ready}, status_code=200 if ready else 503)
