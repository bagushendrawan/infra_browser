from fastapi import Request

from src.browser.exceptions import BrowserError
from src.browser.service import BrowserService


async def get_service(request: Request) -> BrowserService:
    service = getattr(request.app.state, "browser", None)
    if service is None:
        raise BrowserError(503, "browser_unavailable", "Browser unavailable")
    return service
