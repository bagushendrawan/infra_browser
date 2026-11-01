import asyncio

import pytest

from src.browser.config import BrowserSettings
from src.browser.exceptions import BrowserError
from src.browser.service import BrowserService

pytestmark = pytest.mark.browser

HTML = b"""<html><head><title>Fixture</title></head><body>
<input id="input"><button onclick="document.title='clicked'">Click</button>
<script>setTimeout(()=>{let p=document.createElement('p');p.id='ready';p.textContent='Rendered';document.body.append(p)},150)</script>
</body></html>"""


@pytest.fixture
async def site():
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
            + str(len(HTML)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + HTML
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    async with server:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"


@pytest.fixture
async def service():
    service = BrowserService(BrowserSettings(max_tabs=2, timeout_seconds=3))
    await service.start()
    yield service
    await service.close()
    assert not service.ready
    assert not service.tabs


async def test_browser_flow(service, site):
    tab = await service.create()
    key = tab["tab_id"]
    assert (await service.navigate(key, site))["navigation_status"] == 200
    await service.type(key, "#input", "hello")
    await service.type(key, "#input", "!", append=True)
    assert await service.tabs[key].page.locator("#input").input_value() == "hello!"
    assert (await service.click(key, "button"))["title"] == "clicked"
    image = await service.screenshot(key, wait_for_selector="#ready")
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert await service.tabs[key].page.locator("#ready").is_visible()
    await service.tabs[key].page.evaluate("localStorage.setItem('secret','yes')")
    await service.tabs[key].context.add_cookies(
        [{"name": "secret", "value": "yes", "url": site}]
    )
    second = (await service.create())["tab_id"]
    await service.navigate(second, site)
    assert (
        await service.tabs[second].page.evaluate("localStorage.getItem('secret')")
        is None
    )
    assert not await service.tabs[second].context.cookies()
    cleared = await service.clear(key)
    assert cleared["tab_id"] == key and cleared["url"] == "about:blank"
    await service.navigate(key, site)
    assert (
        await service.tabs[key].page.evaluate("localStorage.getItem('secret')") is None
    )
    assert not await service.tabs[key].context.cookies()
    assert len(await service.list_tabs()) == 2
    await service.delete(second)
    await service.create()


async def test_capacity_and_errors(service, site):
    results = await asyncio.gather(
        *(service.create() for _ in range(5)), return_exceptions=True
    )
    assert sum(isinstance(r, dict) for r in results) == 2
    assert all(r.status == 409 for r in results if isinstance(r, BrowserError))
    key = next(iter(service.tabs))
    await service.navigate(key, site)
    with pytest.raises(BrowserError) as error:
        await service.click(key, "input,button")
    assert error.value.status == 422
    service.settings.timeout_seconds = 0.1
    with pytest.raises(BrowserError) as error:
        await service.screenshot(key, wait_for_selector="#missing")
    assert error.value.status == 504
    await service.delete(key)
    with pytest.raises(BrowserError) as error:
        await service.clear(key)
    assert error.value.status == 404


async def test_serialization_and_cancellation(service):
    key = (await service.create())["tab_id"]
    second = (await service.create())["tab_id"]
    async with service.tabs[key].lock:
        pending = asyncio.create_task(service.clear(key))
        await asyncio.sleep(0)
        assert not pending.done()
        await service.clear(second)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    await service.clear(key)
    assert len(service.tabs) == 2
    await service.browser.close()
    with pytest.raises(BrowserError) as error:
        await service.create()
    assert error.value.status == 503


async def test_blank_screenshot_and_failed_navigation(service):
    key = (await service.create())["tab_id"]
    service.settings.timeout_seconds = 0.15
    with pytest.raises(BrowserError) as error:
        await service.screenshot(key)
    assert error.value.status == 504
    # A bound-but-not-listening socket provides a deterministic refused port.
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        with pytest.raises(BrowserError) as error:
            await service.navigate(key, f"http://127.0.0.1:{sock.getsockname()[1]}")
    assert error.value.status == 502


async def test_popup_is_closed(service, site):
    key = (await service.create())["tab_id"]
    await service.navigate(key, site)
    context = service.tabs[key].context
    async with context.expect_page() as popup_info:
        await service.tabs[key].page.evaluate("window.open('about:blank')")
    popup = await popup_info.value
    if not popup.is_closed():
        await popup.wait_for_event("close", timeout=3000)
    assert len(context.pages) == 1
