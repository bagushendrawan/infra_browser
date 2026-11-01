import httpx
import pytest

from src.browser.dependencies import get_service
from src.main import app


class FakeService:
    async def create(self):
        return {
            "tab_id": "12345678-1234-4234-8234-123456789abc",
            "url": "about:blank",
            "title": "",
        }

    async def screenshot(self, tab_id, **kwargs):
        return b"\x89PNG\r\n\x1a\n"


@pytest.fixture
async def client():
    app.dependency_overrides[get_service] = lambda: FakeService()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def test_create(client):
    response = await client.post("/v1/browser/tabs")
    assert response.status_code == 201
    assert response.json()["url"] == "about:blank"


async def test_validation(client):
    response = await client.post(
        "/v1/browser/tabs/invalid/navigate", json={"url": "file:///etc/passwd"}
    )
    assert response.status_code == 422


async def test_screenshot(client):
    response = await client.post(
        "/v1/browser/tabs/12345678-1234-4234-8234-123456789abc/screenshot", json={}
    )
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "status,code",
    [
        (404, "tab_not_found"),
        (409, "tab_limit"),
        (422, "invalid_selector"),
        (502, "browser_failure"),
        (503, "browser_unavailable"),
        (504, "operation_timeout"),
    ],
)
async def test_domain_errors(client, status, code):
    from src.browser.exceptions import BrowserError

    class FailedService:
        async def create(self):
            raise BrowserError(status, code, "Expected failure")

    app.dependency_overrides[get_service] = lambda: FailedService()
    response = await client.post("/v1/browser/tabs")
    assert response.status_code == status
    assert response.json() == {"detail": "Expected failure", "code": code}


async def test_health(client):
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 503


@pytest.mark.parametrize(
    "payload", [{}, {"url": "ftp://example.com"}, {"url": "javascript:alert(1)"}]
)
async def test_invalid_navigation(client, payload):
    response = await client.post(
        "/v1/browser/tabs/12345678-1234-4234-8234-123456789abc/navigate", json=payload
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"


async def test_actions_forward_payloads(client):
    calls = []
    tab = await FakeService().create()

    class Actions:
        async def list_tabs(self):
            return [tab]

        async def navigate(self, key, **kwargs):
            calls.append(("navigate", key, kwargs))
            return {**tab, "navigation_status": 200}

        async def click(self, key, **kwargs):
            calls.append(("click", key, kwargs))
            return tab

        async def type(self, key, **kwargs):
            calls.append(("type", key, kwargs))
            return tab

        async def clear(self, key):
            calls.append(("clear", key, {}))
            return tab

        async def delete(self, key):
            calls.append(("delete", key, {}))

    app.dependency_overrides[get_service] = lambda: Actions()
    base = "/v1/browser/tabs"
    key = tab["tab_id"]
    assert (await client.get(base)).json() == [tab]
    payloads = {
        "navigate": {"url": "https://example.com/", "wait_for_selector": "h1"},
        "click": {"selector": "button", "wait_for_selector": "#done"},
        "type": {"selector": "input", "text": "hello", "append": True},
    }
    for action, payload in payloads.items():
        response = await client.post(f"{base}/{key}/{action}", json=payload)
        assert response.status_code == 200
        actual = calls[-1][2]
        if action == "navigate":
            actual["url"] = str(actual["url"])
        assert calls[-1] == (action, key, payload)
    assert (await client.post(f"{base}/{key}/clear")).json() == tab
    assert (await client.delete(f"{base}/{key}")).status_code == 204
    assert calls[-2:] == [("clear", key, {}), ("delete", key, {})]
