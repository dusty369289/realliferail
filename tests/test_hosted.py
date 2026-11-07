"""Hosted mode: each browser brings its own key, sealed in an HttpOnly cookie. The server keeps no key."""

import base64

import pytest
from fastapi.testclient import TestClient

from realliferail.services.hosted import COOKIE, Hosted, KeyBox, load_secret
from realliferail.web.app import create_app
from tests.test_settings import GOOD, FakeRtt, text

SECRET = bytes(range(32))
FORM = {"content-type": "application/x-www-form-urlencoded"}


@pytest.fixture
def hosted(clock):
    return Hosted(SECRET, clock=clock, transport=FakeRtt())


@pytest.fixture
def web(hosted):
    # TestClient talks plain http, so the Secure flag would stop the cookie coming back
    return TestClient(create_app(hosted=hosted, secure_cookies=False))


def save_key(web, token=GOOD):
    return web.post("/settings/token", content=f"token={token}", headers=FORM, follow_redirects=False)


# ---- the box ----
def test_seal_and_open():
    box = KeyBox(SECRET)
    sealed = box.seal(GOOD)
    assert GOOD not in sealed and box.open(sealed) == GOOD
    assert box.seal(GOOD) != sealed  # a fresh nonce every time


@pytest.mark.parametrize("bad", [None, "", "x", "!!!", "A" * 5000, base64.urlsafe_b64encode(bytes(range(40))).decode()])
def test_garbage_opens_to_nothing(bad):
    assert KeyBox(SECRET).open(bad) is None


def test_tampered_or_foreign_cookie_opens_to_nothing():
    sealed = KeyBox(SECRET).seal(GOOD)
    flipped = sealed[:-2] + ("A" if sealed[-2] != "A" else "B") + sealed[-1]
    assert KeyBox(SECRET).open(flipped) is None
    assert KeyBox(bytes(32)).open(sealed) is None  # another server's secret


def test_secret_must_be_strong():
    assert load_secret(SECRET.hex()) == SECRET
    assert load_secret(base64.urlsafe_b64encode(SECRET).decode()) == SECRET
    for bad in (None, "", "abc", "00" * 16, "zz" * 32):
        with pytest.raises(ValueError):
            load_secret(bad)


# ---- the web app ----
def test_no_key_is_demo(web):
    assert "Demo data." in web.get("/").text
    assert "in this browser only" in text(web.get("/settings"))


def test_saving_a_key_sets_a_sealed_httponly_cookie(clock, hosted):
    web = TestClient(create_app(hosted=hosted, secure_cookies=True), base_url="https://testserver")
    r = save_key(web)
    assert r.status_code == 303
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and GOOD not in cookie
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age="):
        assert flag.lower() in cookie.lower(), flag


def test_key_works_from_the_cookie(web, hosted, tmp_path):
    save_key(web)
    s = web.get("/settings")
    assert "Hobbyist" in text(s) and "…bcdef" in text(s) and "Demo data." not in s.text
    assert GOOD not in s.text
    assert web.get("/train/X1:2026-11-07").status_code == 200
    assert hosted.active == 1


def test_server_writes_nothing_to_disk(web, tmp_path, monkeypatch):
    home = tmp_path / "home"  # REALLIFERAIL_HOME, set by conftest
    save_key(web)
    web.get("/train/X1:2026-11-07")
    assert not home.exists() or not any(home.iterdir())


def test_other_browsers_stay_on_demo(web, hosted):
    save_key(web)
    stranger = TestClient(create_app(hosted=hosted, secure_cookies=False))
    assert "Demo data." in stranger.get("/").text


def test_each_key_has_its_own_allowance(clock):
    fake = FakeRtt()
    h = Hosted(SECRET, clock=clock, transport=fake)
    a = h.for_key(GOOD)
    b = h.for_key("another-good-looking-token-1234567890")
    assert a is not b and a.budget is not b.budget and a.client is not b.client
    assert h.for_key(GOOD) is a


def test_bad_key_sets_no_cookie(web):
    r = save_key(web, "not-a-real-token-at-all-zzzz")
    assert r.status_code == 400 and "refused the token" in text(r)
    assert "set-cookie" not in r.headers


def test_forget_deletes_the_cookie(web):
    save_key(web)
    r = web.post("/settings/token/remove", follow_redirects=False)
    assert r.status_code == 303 and "max-age=0" in r.headers["set-cookie"].lower()
    web.cookies.clear()
    assert "Demo data." in web.get("/").text


def test_tampered_cookie_is_demo(web):
    web.cookies.set(COOKIE, "tampered-value-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    assert "Demo data." in web.get("/").text


def test_anyone_can_set_their_own_key_but_not_cross_site(web):
    # hosted settings aren't limited to private addresses: each browser only changes its own cookie
    assert save_key(web).status_code == 303
    r = web.post("/settings/token/remove", headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_oversized_post_refused(web):
    r = web.post("/settings/token", content="token=" + "a" * 9000, headers=FORM)
    assert r.status_code == 413


def test_idle_keys_are_dropped(clock):
    t = [0.0]
    h = Hosted(SECRET, clock=clock, transport=FakeRtt(), idle_seconds=60, monotonic=lambda: t[0])
    first = h.for_key(GOOD)
    t[0] = 61
    h.for_key("another-good-looking-token-1234567890")
    assert h.active == 1
    assert h.for_key(GOOD) is not first


def test_key_count_is_capped(clock):
    h = Hosted(SECRET, clock=clock, transport=FakeRtt(), max_keys=3)
    for i in range(10):
        h.for_key(f"token-number-{i:02d}-padding-padding")
    assert h.active == 3


def test_create_app_needs_exactly_one_mode(hosted):
    with pytest.raises(ValueError):
        create_app()


# ---- public-server protections ----
def test_demo_never_runs_out(clock):
    h = Hosted(SECRET, clock=clock, transport=FakeRtt())
    web = TestClient(create_app(hosted=h, secure_cookies=False))
    for i in range(40):  # far past 10 a minute, all in the same minute
        r = web.get("/board", params={"station": "RDG", "time": f"{6 + i % 12:02d}:{i:02d}"})
        assert r.status_code == 200, (i, r.status_code)


def test_key_checks_are_throttled_per_address(clock):
    fake = FakeRtt()
    h = Hosted(SECRET, clock=clock, transport=fake, checks_per_ip=3)
    web = TestClient(create_app(hosted=h, secure_cookies=False))
    for _ in range(3):
        assert save_key(web, "plausible-but-wrong-token-000000").status_code == 400
    calls = len(fake.calls)
    r = save_key(web, "plausible-but-wrong-token-000000")
    assert r.status_code == 429 and "Too many key checks" in text(r)
    assert len(fake.calls) == calls  # refused without calling RTT
    assert save_key(web, "short").status_code == 400  # junk is refused before the throttle, costs nothing


def test_key_checks_have_a_global_cap(clock):
    h = Hosted(SECRET, clock=clock, transport=FakeRtt(), checks_per_ip=100, checks_total=4)
    for i in range(4):
        assert h.allow_check(f"10.0.0.{i}")
    assert not h.allow_check("10.0.0.99")


def test_each_key_keeps_a_bounded_cache(clock):
    h = Hosted(SECRET, clock=clock, transport=FakeRtt(), cached_per_key=5)
    core = h.for_key(GOOD)
    for i in range(40):
        core.client.service(f"X{i}:2026-11-07")
        clock.advance(seconds=15)  # stay inside 10 a minute, counting the 3-call token exchange at the start
    assert len(core.client._cache) <= 5
    assert len(core.client._key_locks) <= 6


def test_simulator_forgets_old_requests(clock):
    from realliferail.sources.simulator import SimTransport

    sim = SimTransport(clock=clock)
    for _ in range(1500):
        sim.get("/api/info", {}, None)
    assert len(sim.requests) == 1000


def test_overlong_search_refused(web):
    assert web.get("/board", params={"station": "x" * 200}).status_code == 400
