import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import uuid4

from playwright.async_api import BrowserContext, Error, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout

from src.browser.config import BrowserSettings
from src.browser.exceptions import BrowserError


@dataclass
class Tab:
    context: BrowserContext
    page: Page
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BrowserService:
    def __init__(self, settings: BrowserSettings):
        self.settings = settings
        self.tabs: dict[str, Tab] = {}
        self.capacity_lock = asyncio.Lock()
        self.playwright = None
        self.browser = None

    @property
    def ready(self):
        return bool(self.browser and self.browser.is_connected())

    async def start(self):
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
        except BaseException:
            await self.close()
            raise

    async def close(self):
        try:
            if self.browser:
                await self.browser.close()
        finally:
            self.tabs.clear()
            try:
                if self.playwright:
                    await self.playwright.stop()
            finally:
                self.browser = None
                self.playwright = None

    @asynccontextmanager
    async def deadline(self):
        if not self.ready:
            raise BrowserError(503, "browser_unavailable", "Browser unavailable")
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                yield
        except (TimeoutError, PlaywrightTimeout) as exc:
            raise BrowserError(504, "operation_timeout", "Operation timed out") from exc
        except Error as exc:
            message = str(exc)
            if (
                "strict mode violation" in message
                or "selector" in message
                and "parsing" in message
            ):
                raise BrowserError(
                    422, "invalid_selector", "Selector must identify one valid target"
                ) from exc
            raise BrowserError(
                502, "browser_failure", "Browser operation failed"
            ) from exc

    async def new_tab(self):
        context = await self.browser.new_context(
            viewport={
                "width": self.settings.viewport_width,
                "height": self.settings.viewport_height,
            },
            accept_downloads=False,
        )
        try:
            context.set_default_timeout(self.settings.timeout_seconds * 1000)
            page = await context.new_page()

            async def close_popup(popup):
                try:
                    await popup.close()
                except Error:
                    pass  # The context or popup may already have been closed.

            context.on("page", close_popup)
            return Tab(context, page)
        except BaseException:
            await context.close()
            raise

    @staticmethod
    async def describe(tab_id, tab):
        return {"tab_id": tab_id, "url": tab.page.url, "title": await tab.page.title()}

    async def create(self):
        async with self.deadline(), self.capacity_lock:
            if len(self.tabs) >= self.settings.max_tabs:
                raise BrowserError(409, "tab_limit", "Maximum active tabs reached")
            tab = await self.new_tab()
            tab_id = str(uuid4())
            try:
                result = await self.describe(tab_id, tab)
            except BaseException:
                await tab.context.close()
                raise
            self.tabs[tab_id] = tab
            return result

    @asynccontextmanager
    async def locked_tab(self, tab_id):
        async with self.deadline():
            tab = self.tabs.get(tab_id)
            if tab is None:
                raise BrowserError(404, "tab_not_found", "Unknown tab")
            async with tab.lock:
                if self.tabs.get(tab_id) is not tab:
                    raise BrowserError(404, "tab_not_found", "Unknown tab")
                yield tab

    async def list_tabs(self):
        async with self.deadline():
            return await self._list_tabs()

    async def _list_tabs(self):
        result = []
        for tab_id in list(self.tabs):
            try:
                async with self.locked_tab(tab_id) as tab:
                    result.append(await self.describe(tab_id, tab))
            except BrowserError as exc:
                if exc.status != 404:
                    raise
        return result

    @staticmethod
    async def wait_ready(page, selector):
        if selector:
            await page.locator(selector).wait_for(state="visible")

    async def navigate(self, tab_id, url, wait_for_selector=None):
        async with self.locked_tab(tab_id) as tab:
            response = await tab.page.goto(str(url), wait_until="load")
            await self.wait_ready(tab.page, wait_for_selector)
            return {
                **await self.describe(tab_id, tab),
                "navigation_status": response.status if response else None,
            }

    async def click(self, tab_id, selector, wait_for_selector=None):
        async with self.locked_tab(tab_id) as tab:
            await tab.page.locator(selector).click()
            await self.wait_ready(tab.page, wait_for_selector)
            return await self.describe(tab_id, tab)

    async def type(self, tab_id, selector, text, append=False):
        async with self.locked_tab(tab_id) as tab:
            locator = tab.page.locator(selector)
            if append:
                await locator.press_sequentially(text)
            else:
                await locator.fill(text)
            return await self.describe(tab_id, tab)

    async def screenshot(self, tab_id, wait_for_selector=None, full_page=False):
        async with self.locked_tab(tab_id) as tab:
            page = tab.page
            await page.wait_for_load_state("load")
            await self.wait_ready(page, wait_for_selector)
            await page.wait_for_function("""() => {
                const body = document.body;
                return body && [body, ...body.querySelectorAll('*')].some(el => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility === 'visible'
                        && s.display !== 'none' && Number(s.opacity) > 0
                        && el.checkVisibility({checkOpacity:true, checkVisibilityCSS:true})
                        && ([...el.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim())
                            || ['IMG','SVG','CANVAS','INPUT','VIDEO'].includes(el.tagName));
                });
            }""")
            await page.evaluate("""async () => {
                await document.fonts.ready;
                await Promise.all([...document.images].filter(img => {
                    const r = img.getBoundingClientRect();
                    return r.width && r.height && r.bottom > 0 && r.top < innerHeight;
                }).map(img => img.complete ? Promise.resolve() : new Promise(resolve => {
                    img.addEventListener('load', resolve, {once:true});
                    img.addEventListener('error', resolve, {once:true});
                })));
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            }""")
            return await page.screenshot(
                type="png", full_page=full_page, animations="disabled"
            )

    async def clear(self, tab_id):
        async with self.locked_tab(tab_id) as tab:
            replacement = None
            try:
                await tab.context.close()
                replacement = await self.new_tab()
                result = await self.describe(tab_id, replacement)
            except BaseException:
                self.tabs.pop(tab_id, None)
                if replacement:
                    await replacement.context.close()
                raise
            # Keep the existing lock so requests already waiting remain serialized.
            tab.context, tab.page = replacement.context, replacement.page
            return result

    async def delete(self, tab_id):
        async with self.locked_tab(tab_id) as tab:
            await tab.context.close()
            self.tabs.pop(tab_id, None)
