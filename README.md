# Browser API

Start from this directory with `uv run python main.py` (localhost:9104).
See [shared setup and API smoke tests](../README.md).

Standalone Python 3.12 FastAPI service using async Playwright and headless Chromium.
Each managed tab owns a separate nonpersistent browser context. Cookies and storage
are isolated. Run one Uvicorn worker: state and capacity are local to the process.
Use a trusted private network; this service has no authentication and can access
any HTTP/HTTPS destination reachable by its host.

```sh
uv sync
uv run playwright install --with-deps chromium
cp .env.example .env
uv run --no-sync uvicorn src.main:app --host 127.0.0.1 --port 9104 --workers 1
```

Browser installation may need administrator access for host libraries. Chromium
must match the locked Playwright version. Startup fails if it cannot launch.
`/health/live` reports process liveness; `/health/ready` returns 503 if Chromium
is disconnected. Restart the service to recover; all tab IDs disappear on restart.
Docs are at `/docs` in `ENVIRONMENT=local` or `staging` only.

Settings load from this directory's `.env`, overridden by process environment:

| Setting | Default |
| --- | --- |
| `BROWSER_MAX_TABS` | 5 |
| `BROWSER_TIMEOUT_SECONDS` | 30 |
| `BROWSER_VIEWPORT_WIDTH` | 1280 |
| `BROWSER_VIEWPORT_HEIGHT` | 720 |

Run these commands from the service directory. Create a tab and copy its UUID into
`TAB_ID`:

```sh
curl -X POST http://127.0.0.1:9104/v1/browser/tabs
TAB_ID=replace-with-returned-uuid
curl http://127.0.0.1:9104/v1/browser/tabs
curl -X POST "http://127.0.0.1:9104/v1/browser/tabs/$TAB_ID/navigate" \
  -H 'Content-Type: application/json' -d '{"url":"https://example.com","wait_for_selector":"h1"}'
curl -X POST "http://127.0.0.1:9104/v1/browser/tabs/$TAB_ID/click" \
  -H 'Content-Type: application/json' -d '{"selector":"a"}'
# On a page with an input, replace its text (append=true sends character events):
curl -X POST "http://127.0.0.1:9104/v1/browser/tabs/$TAB_ID/type" \
  -H 'Content-Type: application/json' -d '{"selector":"input","text":"hello","append":false}'
curl -X POST "http://127.0.0.1:9104/v1/browser/tabs/$TAB_ID/screenshot" \
  -H 'Content-Type: application/json' -d '{"full_page":false,"wait_for_selector":"body"}' -o screenshot.png
curl -X POST "http://127.0.0.1:9104/v1/browser/tabs/$TAB_ID/clear"
curl -X DELETE "http://127.0.0.1:9104/v1/browser/tabs/$TAB_ID"
```

Create returns 201. Other JSON actions return `tab_id`, `url`, `title`; navigation
also returns `navigation_status` (upstream HTTP errors remain valid page results).
List returns an array. Delete returns 204. Screenshot returns PNG bytes, without
server-side saved files. Clearing replaces the context, removes session state,
and preserves the tab ID. Failed resets remove the tab and free its slot.

Selectors use Playwright locator syntax. Click/type require one unique target.
Navigate and click optionally accept `wait_for_selector` for resulting content.
Screenshots wait for document load, visible content, fonts, visible images, and
two animation frames, and disable animations during capture. For apps that load
content asynchronously, supply a selector identifying finished content; generic
checks cannot know when every app has finished. Blank pages time out. Full-page
capture does not scroll to trigger every lazy-loaded resource.

Operations on a tab serialize, including clear/close; separate tabs can progress
concurrently. The deadline includes lock acquisition. Capacity includes creations
in progress. Unsolicited popups are closed. Downloads and persistent profiles are
not supported. No automatic action retries: a timeout may have partially changed
the page, so inspect state before retrying a click or typing.

Errors contain `detail` and `code`: 422 invalid input/ambiguous or invalid selector,
404 unknown tab, 409 capacity reached, 502 browser/navigation failure, 503 browser
unavailable, 504 operation/readiness timeout.

```sh
uv run --no-sync pytest -q -m 'not browser'
uv run --no-sync pytest -q -m browser
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
```

Real-browser tests require Chromium and use a local HTTP fixture without external
websites. They cover actions, delayed rendering, session isolation, reset/close,
capacity races, serialization, cancellation, and browser disconnection.

Validation: run the checks above and the shared HTTP smoke suite on the deployment host.

## Original resources

- [Playwright for Python](https://github.com/microsoft/playwright-python) — upstream browser automation library.
- [Playwright Python documentation](https://playwright.dev/python/) — installation, browser management, and API documentation.
