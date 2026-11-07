"""Browser matrix: every page at phone and desktop widths in both schemes, plus the main flows.

Run with `uv run pytest -m ui`, then look at `.ui-report/index.html`. Checks here catch breakage. Only looking at the
contact sheet tells you whether it looks right.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from realliferail.domain.engine import State, build
from realliferail.domain.parse import parse_service
from realliferail.sources.simulator import SimTransport
from tests.ui.conftest import MOMENT, REPORT, VIEWPORTS

pytestmark = [pytest.mark.ui, pytest.mark.timeout(60)]


def find_train(core, state: State, at_station: str | None = None) -> tuple[str, datetime]:
    """A simulated train in the wanted state, and the first moment from MOMENT (2-minute steps) it's in that state."""
    sim = SimTransport(timetable=core.client._t.tt)  # its own, so looking doesn't use the server's allowance
    saved = sim.clock
    try:
        for step in range(0, 180, 2):
            t = MOMENT + timedelta(minutes=step)
            sim.clock = lambda t=t: t
            for s in sim.tt.day(MOMENT.date()):
                if at_station and not any(p.loc.crs == at_station and p.calls for p in s.points):
                    continue
                if not (s.origin.dep - timedelta(minutes=30) <= t <= s.destination.arr + timedelta(minutes=30)):
                    continue
                body = sim.get("/gb-nr/service", {"uniqueIdentity": f"{s.identity}:{s.run_date}"}, None).body
                tl = build(parse_service(body), t)
                if tl.position.state is not state:
                    continue
                pos = tl.position
                if state is State.RUNNING and not (
                    pos.fraction < 0.5 and (pos.expected - pos.since).total_seconds() >= 90
                ):
                    continue  # want one clearly mid-section, so movement shows
                if at_station and state is State.RUNNING:
                    idx = next(i for i, p in enumerate(s.points) if p.loc.crs == at_station)
                    if tl.position.to_index is None or tl.position.to_index > idx:
                        continue  # want one still coming towards the station
                q = f"?at={at_station}" if at_station else ""
                return f"/train/{s.identity}:{s.run_date}{q}", t
    finally:
        sim.clock = saved
    raise LookupError(state)


def shoot(page, name: str, full: bool = False):
    REPORT.mkdir(exist_ok=True)
    page.wait_for_timeout(150)
    page.screenshot(path=str(REPORT / f"{name}.png"), full_page=full)


def common_checks(page):
    assert page.problems == [], page.problems
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"page scrolls sideways by {overflow}px"


def small_targets(page) -> list[str]:
    return page.evaluate(
        """() => [...document.querySelectorAll('button, input, select, .trains__link, .topbar__nav a, .board__nav a')]
          .filter(e => e.offsetParent !== null)
          .map(e => (e.type === 'checkbox' || e.type === 'radio') && e.closest('label') ? e.closest('label') : e)
          .filter(e => { const r = e.getBoundingClientRect(); return r.height < 43.5; })
          .map(e => (e.id || e.className || e.tagName) + ' ' + Math.round(e.getBoundingClientRect().height))"""
    )


PAGES = {
    "home": lambda core: "/",
    "board": lambda core: "/board?station=RDG",
    "board-arrivals": lambda core: "/board?station=CLJ&mode=arr&time=17:30",
    "board-empty": lambda core: "/board?station=EDB",
    "board-error": lambda core: "/board?station=RDG&time=99:99",
    "train-running": lambda core: find_train(core, State.RUNNING, "RDG"),
    "train-at-station": lambda core: find_train(core, State.AT_STATION),
    "train-overdue": lambda core: find_train(core, State.OVERDUE),
    "train-not-started": lambda core: find_train(core, State.NOT_STARTED, "RDG"),
    "train-arrived": lambda core: find_train(core, State.ARRIVED),
    "about": lambda core: "/about",
    "settings": lambda core: "/settings",
    "missing-train": lambda core: "/train/Z1:2026-11-07",
}


@pytest.mark.parametrize("scheme", ["dark", "light"])
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("name", list(PAGES))
def test_page_matrix(server, core, make_page, moment, name, viewport, scheme):
    target = PAGES[name](core)
    if isinstance(target, tuple):
        target, t = target
        moment(t)
    page = make_page(viewport, scheme)
    page.goto(server + target)
    page.wait_for_load_state("networkidle")
    common_checks(page)
    if viewport.startswith("phone"):
        assert small_targets(page) == []
    if name.startswith("train-") and name != "train-cancelled":
        marker = page.locator("[data-train-marker]")
        assert marker.is_visible(), "the train marker should be on the line"
    shoot(page, f"{name}--{viewport}--{scheme}", full=name.startswith("board") or name == "about")


def open_train(server, core, make_page, moment, state=State.RUNNING, station="RDG"):
    path, t = find_train(core, state, station)
    moment(t)
    page = make_page()
    page.goto(server + path)
    return page


def test_marker_sits_between_its_two_points(server, core, make_page, moment):
    page = open_train(server, core, make_page, moment)
    page.wait_for_timeout(300)
    live = page.locator(".live")
    a, b = int(live.get_attribute("data-from")), int(live.get_attribute("data-to"))
    rows = page.locator(".route__pt")
    ya = rows.nth(a).bounding_box()
    yb = rows.nth(b).bounding_box()
    m = page.locator("[data-train-marker]").bounding_box()
    centre = m["y"] + m["height"] / 2
    assert ya["y"] + ya["height"] / 2 - 1 <= centre <= yb["y"] + yb["height"] / 2 + 1


def test_marker_moves_with_the_clock(server, core, make_page, moment):
    page = open_train(server, core, make_page, moment)
    page.wait_for_timeout(1000)  # the marker eases into place over 0.9 s
    y1 = page.locator("[data-train-marker]").bounding_box()["y"]
    page.clock.run_for(20_000)
    page.wait_for_timeout(1000)
    y2 = page.locator("[data-train-marker]").bounding_box()["y"]
    assert y2 > y1


def test_search_flow_by_keyboard(server, make_page):
    page = make_page()
    page.goto(server + "/")
    page.fill("#station", "readin")
    page.wait_for_selector("#station-list li")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert page.input_value("#station") == "Reading (RDG)"
    page.keyboard.press("Enter")  # submits
    page.wait_for_selector(".trains")
    assert page.locator("h1").inner_text() == "Reading"
    page.locator(".trains__link").first.click()
    page.wait_for_selector(".route")
    assert page.locator(".is-at").count() == 1
    common_checks(page)


def test_recent_stations_remembered(server, make_page):
    page = make_page()
    page.goto(server + "/board?station=WAT")
    page.wait_for_function("localStorage.getItem('rlr.recent') !== null")
    page.goto(server + "/")
    recent = page.locator("[data-recent]")
    assert recent.is_visible()
    assert "London Waterloo" in recent.inner_text()


def test_passing_points_toggle(server, core, make_page, moment):
    page = open_train(server, core, make_page, moment)
    passes = page.locator(".route__pt.is-pass")
    assert passes.first.is_visible()
    page.uncheck("[data-toggle-passes]")
    assert not passes.first.is_visible()
    assert page.locator("[data-train-marker]").is_visible()
    shoot(page, "train-running-no-passes--phone-412--dark")
    page.reload()
    assert not page.is_checked("[data-toggle-passes]")  # remembered


def test_live_region_refreshes_without_reloading(server, core, make_page, moment):
    page = open_train(server, core, make_page, moment)
    page.evaluate("window.__marker = 1")
    with page.expect_response(lambda r: "/live" in r.url, timeout=5_000):
        page.clock.run_for(130_000)
    page.wait_for_timeout(200)
    assert page.evaluate("window.__marker") == 1  # same document
    assert page.locator(".route").count() == 1
    common_checks(page)


def test_service_worker_registers(server, make_page):
    page = make_page()
    page.goto(server + "/")
    # 127.0.0.1 is a secure context, so the worker registers there (on a LAN address over http it can't)
    assert page.evaluate("navigator.serviceWorker.ready.then(r => !!r.active)")


def test_save_a_journey_and_use_it_both_ways(server, make_page):
    page = make_page()
    page.goto(server + "/board?station=RDG&to=PAD")
    page.click("[data-save-journey]")
    assert "home screen" in page.inner_text("[data-save-note]")
    page.goto(server + "/")
    go = page.locator(".journeys__go").first
    assert go.inner_text() == "Reading → London Paddington"
    shoot(page, "home-with-journeys--phone-412--dark")
    page.locator(".journeys__back").first.click()
    page.wait_for_selector(".board")
    assert page.locator("h1").inner_text() == "London Paddington"
    assert "calling at Reading" in page.inner_text(".board__sub")
    common_checks(page)


def test_carry_on_tracking_card(server, core, make_page, moment):
    page = open_train(server, core, make_page, moment)
    title = page.get_attribute("[data-train]", "data-title")
    page.goto(server + "/")
    card = page.locator("[data-tracking]")
    assert card.is_visible() and title in card.inner_text()
    card.locator("a").click()
    page.wait_for_selector(".route")
    common_checks(page)


def test_refresh_button_does_not_refetch_fresh_data(server, core, make_page, moment):
    page = open_train(server, core, make_page, moment)
    hits = []
    page.on("request", lambda r: hits.append(r.url) if "/live" in r.url else None)
    for _ in range(5):
        page.click("[data-refresh-now]")
    assert "Already up to date" in page.inner_text("[data-refresh-note]")
    assert hits == []
