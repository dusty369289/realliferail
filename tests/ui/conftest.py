"""A real server in a thread, running the simulator at a fixed moment, and a browser whose clock agrees with it."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from realliferail.services.app import Realliferail
from realliferail.sources.simulator import SimTransport
from realliferail.web.app import create_app
from tests.conftest import Clock, at

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / ".ui-report"
MOMENT = at(14, 20)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def sim_clock():
    return Clock(MOMENT)


@pytest.fixture(scope="session")
def core(sim_clock):
    return Realliferail(transport=SimTransport(clock=sim_clock), clock=sim_clock, demo=True)


@pytest.fixture(scope="session")
def server(core):
    port = _free_port()
    config = uvicorn.Config(create_app(core), host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


VIEWPORTS = {
    "phone-360": {"viewport": {"width": 360, "height": 780}, "is_mobile": True, "has_touch": True},
    "phone-412": {"viewport": {"width": 412, "height": 915}, "is_mobile": True, "has_touch": True},
    "desktop": {"viewport": {"width": 1280, "height": 900}},
}


@pytest.fixture(autouse=True)
def fresh_allowance(core):
    """Every UI test happens in the same frozen simulated minute, so each starts with a full allowance.

    Without this the server's real 10-a-minute limit runs out a few tests in, as it should.
    """
    from realliferail.sources.budget import Budget

    core.budget.__init__(clock=core.budget._clock)
    core.client.budget = core.budget
    core.client._t._times.clear()
    assert isinstance(core.budget, Budget)


@pytest.fixture
def moment(core, sim_clock):
    """Move the simulated world (server and browser) to another time for one test."""

    def move(t):
        sim_clock.t = t
        core.client._cache.clear()  # answers fetched "later" would otherwise look fresh forever

    yield move
    move(MOMENT)


@pytest.fixture
def make_page(browser, sim_clock):
    """A page whose clock starts at the simulated now."""
    made = []

    def make(viewport="phone-412", scheme="dark"):
        ctx = browser.new_context(color_scheme=scheme, device_scale_factor=1, **VIEWPORTS[viewport])
        page = ctx.new_page()
        page.clock.install(time=sim_clock().timestamp())  # then runs on in real time; run_for() jumps ahead
        page.problems = []
        failed_docs = set()

        def on_response(r):
            if r.request.resource_type == "document" and r.status >= 400:
                failed_docs.add(r.url)  # pages that answer 4xx on purpose (bad input, unknown train)

        def on_console(m):
            if m.type != "error":
                return
            if "Failed to load resource" in m.text and m.location.get("url") in failed_docs:
                return
            page.problems.append(f"console {m.type}: {m.text} ({m.location.get('url')})")

        page.on("response", on_response)
        page.on("console", on_console)
        page.on("pageerror", lambda e: page.problems.append(f"page error: {e}"))
        made.append(ctx)
        return page

    yield make
    for ctx in made:
        ctx.close()


def pytest_sessionfinish(session, exitstatus):
    shots = sorted(REPORT.glob("*.png")) if REPORT.exists() else []
    if not shots:
        return
    cards = "\n".join(
        f'<figure><a href="{p.name}"><img src="{p.name}" loading="lazy"></a><figcaption>{p.stem}</figcaption></figure>'
        for p in shots
    )
    (REPORT / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>UI report</title>"
        "<style>body{font:14px system-ui;background:#222;color:#eee;margin:16px}"
        "main{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}"
        "img{width:100%;border:1px solid #444}figure{margin:0}</style>"
        f"<h1>UI report</h1><p>{len(shots)} screenshots, simulated trains at {MOMENT:%Y-%m-%d %H:%M}.</p>"
        f"<main>{cards}</main>"
    )
