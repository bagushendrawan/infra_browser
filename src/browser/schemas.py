from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class TabResponse(BaseModel):
    tab_id: UUID
    url: str
    title: str


class NavigationResponse(TabResponse):
    navigation_status: int | None


class ReadyRequest(BaseModel):
    wait_for_selector: str | None = Field(default=None, min_length=1)


class NavigateRequest(ReadyRequest):
    url: HttpUrl


class ClickRequest(ReadyRequest):
    selector: str = Field(min_length=1)


class TypeRequest(BaseModel):
    selector: str = Field(min_length=1)
    text: str
    append: bool = False


class ScreenshotRequest(ReadyRequest):
    full_page: bool = False


class ErrorResponse(BaseModel):
    detail: str
    code: str
