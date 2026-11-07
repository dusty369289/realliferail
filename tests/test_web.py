import html
import re

import pytest
from fastapi.testclient import TestClient

from realliferail.services.app import Realliferail
from realliferail.sources.simulator import SimTransport
from realliferail.web.app import create_app
from tests.conftest import at

SECRET = "SECRET-TOKEN-must-never-show"


@pytest.fixture
def core(clock):
    c = Realliferail(transport=SimTransport(clock=clock), token=SECRET, clock=clock, demo=False)
    return c


@pytest.fixture
def web(core):
    return TestClient(create_app(core))


def text(r) -> str:
    """What a reader sees: entities decoded, runs of whitespace as one space."""
    return " ".join(html.unescape(r.text).split())


def first_train(web, station="RDG"):
    r = web.get("/board", params={"station": station})
    m = re.search(r'href="(/train/[^"]+)"', r.text)
    return m.group(1).replace("&amp;", "&")


def test_home(web):
    r = web.get("/")
    assert r.status_code == 200
    assert "Where are you catching a train?" in text(r)
    assert 'name="station"' in r.text


def test_security_headers(web):
    h = web.get("/").headers
    assert "default-src 'self'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"


def test_board_now(web):
    r = web.get("/board", params={"station": "Reading"})
    assert r.status_code == 200
    assert "<h1>Reading</h1>" in r.text
    assert "Departures, 14:20 to 15:20" in text(r)
    assert r.text.count('class="trains__row') >= 4
    assert "data-live-board" in r.text  # a "now" board refreshes itself


def test_board_at_time_and_calling_at(web):
    r = web.get("/board", params={"station": "RDG", "time": "17:00", "to": "Oxford"})
    assert r.status_code == 200
    assert "calling at Oxford" in text(r)
    assert "London Paddington</span>" not in r.text
    assert "data-live-board" not in r.text


def test_board_arrivals_include_terminating_trains(web):
    r = web.get("/board", params={"station": "RDG", "mode": "arr"})
    assert "Arrivals" in r.text
    assert "Abbey Wood" not in r.text  # sim has no Abbey Wood, but Elizabeth line trains from Paddington terminate
    assert "London Paddington</span>" in r.text


def test_board_bad_input_is_a_sentence(web):
    r = web.get("/board", params={"station": "RDG", "time": "25:99"})
    assert r.status_code == 400 and "isn't valid" in text(r)
    r = web.get("/board", params={"station": "RDG", "to": "zzzqqqx"})
    assert r.status_code == 400 and "Couldn't find a station" in text(r)
    assert web.get("/board", params={"station": ""}, follow_redirects=False).status_code == 303


def test_board_after_midnight_means_tonight(web, clock):
    clock.t = at(23, 50)
    r = web.get("/board", params={"station": "RDG", "time": "00:30"})
    assert "on Sun 8 Nov" in text(r)


def test_board_no_trains(web):
    r = web.get("/board", params={"station": "Edinburgh"})
    assert r.status_code == 200
    assert "No departures in this hour" in text(r)


def test_train_page(web):
    href = first_train(web)
    r = web.get(href)
    assert r.status_code == 200
    assert 'class="route"' in r.text
    assert "data-train-marker" in r.text
    assert 'class="route__pt is-call' in r.text and " is-at" in r.text
    assert 'class="live__stop"' in r.text


def test_train_live_fragment(web):
    href = first_train(web)
    uid = href.split("?")[0]
    r = web.get(uid + "/live?at=RDG")
    assert r.status_code == 200
    assert r.text.lstrip().startswith('<section class="live"')
    assert "<html" not in r.text


def test_unknown_train(web):
    assert web.get("/train/Z99999:2026-11-07").status_code == 404
    assert "isn't a train" in text(web.get("/train/nonsense"))
    assert web.get("/train/Z9:2026-99-99").status_code == 404


def test_station_api(web):
    r = web.get("/api/stations", params={"q": "padd"})
    assert r.json()[0] == {"name": "London Paddington", "crs": "PAD"}
    assert web.get("/api/stations", params={"q": "x" * 61}).status_code == 422


def test_pwa_files(web):
    m = web.get("/manifest.webmanifest")
    assert m.headers["content-type"].startswith("application/manifest+json")
    assert m.json()["display"] == "standalone"
    for icon in m.json()["icons"]:
        assert web.get(icon["src"]).status_code == 200
    sw = web.get("/sw.js")
    assert sw.headers["content-type"].startswith("text/javascript")
    for asset in re.findall(r'"(/static/[^"]+)"', sw.text):
        assert web.get(asset).status_code == 200, asset
    assert web.get("/offline").status_code == 200


def test_about_shows_token_state_not_token(web):
    r = web.get("/about")
    assert "Working (access token)" in text(r)
    assert "of 100 left" in text(r)


def test_token_never_reaches_the_browser(web):
    href = first_train(web)
    pages = ["/", "/about", "/board?station=RDG", href, href.split("?")[0] + "/live", "/api/stations?q=rea"]
    for p in pages:
        r = web.get(p)
        assert SECRET not in r.text, p
        assert SECRET not in str(r.headers), p


def test_demo_banner_only_in_demo(clock):
    demo = TestClient(create_app(Realliferail(clock=clock)))
    assert "Demo data." in demo.get("/").text
    assert "Demo mode" in demo.get("/about").text


def test_board_is_cached_for_a_minute(web, core, clock):
    web.get("/board", params={"station": "RDG"})
    n = core.budget.total
    web.get("/board", params={"station": "RDG"})
    assert core.budget.total == n
    clock.advance(seconds=61)
    web.get("/board", params={"station": "RDG"})
    assert core.budget.total == n + 1


def test_live_polling_slows_when_allowance_is_low(web, core):
    href = first_train(web)
    sim = core.client._t
    sim.limit_hour = len(sim.requests) + 21  # all made "now", so its next answer says 20 are left this hour
    r = web.get(href.split("?")[0] + "/live")
    assert 'data-refresh="120"' in r.text


def test_allowance_low_banner(web, core):
    core.budget.observe(200, {"x-ratelimit-remaining-hour": "8"})
    assert "Only 8 Realtime Trains calls left this hour" in text(web.get("/"))


def test_untrusted_text_is_escaped(clock):
    class Evil(SimTransport):
        def get(self, path, params, token):
            r = super().get(path, params, token)
            if path == "/gb-nr/location" and r.body:
                r.body["services"][0]["destination"][0]["location"]["description"] = "<script>alert(1)</script>"
            return r

    c = Realliferail(transport=Evil(clock=clock), token="t", clock=clock, demo=False)
    r = TestClient(create_app(c)).get("/board", params={"station": "RDG"})
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_out_of_allowance_is_busy_not_missing(web, core):
    href = first_train(web)
    core.budget.observe(429, {"retry-after": "60"})
    core.client._cache.clear()
    r = web.get(href)
    assert r.status_code == 503
    assert "Realtime Trains is busy" in text(r)
    assert 'http-equiv="refresh"' in r.text
    b = web.get("/board", params={"station": "WAT"})
    assert b.status_code == 503 and "tries again by itself" in text(b)
