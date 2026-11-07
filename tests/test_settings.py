"""Settings page, tiers, the access-token cache, and refresh that's safe to press repeatedly."""

import html
import json
import re

import pytest
from fastapi.testclient import TestClient

from realliferail.services.app import Realliferail, from_environment
from realliferail.sources.budget import Budget
from realliferail.sources.rtt import RttClient
from realliferail.sources.transport import Response
from realliferail.web.app import create_app, private_client

GOOD = "good-refresh-token-0123456789abcdef"


class FakeRtt:
    """Refresh-token flow like the real one: /api/info refuses the refresh token, the access token works."""

    def __init__(self, entitlements=("allowAllocationsPassenger", "allowDetailed"), hour="100"):
        self.ents = list(entitlements)
        self.calls = []
        self.hour = hour

    def get(self, path, params, token):
        self.calls.append(path)
        h = {"x-ratelimit-limit-minute": "10", "x-ratelimit-limit-hour": self.hour}
        if path == "/api/get_access_token":
            if token == GOOD:
                return Response(200, h, {"token": "short-access", "validUntil": "2026-11-07T18:00:00Z"})
            return Response(401, h, {"error": "no"})
        if path == "/api/info":
            if token == "short-access":
                return Response(200, h, {"api_version": "2026-07-25", "credentials": {"entitlements": self.ents}})
            return Response(401, h, {"error": "no"})
        if path == "/gb-nr/service":
            return Response(
                200, h, {"service": {"scheduleMetadata": {"identity": "X1", "departureDate": "2026-11-07"}}}
            )
        return Response(404, h, None)


def text(r):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", r.text)).split())


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def app_for(core, allowed=True):
    return TestClient(create_app(core, settings_allowed=lambda host: allowed))


def test_demo_settings_invites_a_key(clock, home):
    web = app_for(Realliferail(clock=clock, home=home))
    t = text(web.get("/settings"))
    assert "simulated" in t and "Check and save key" in t
    assert "Hobbyist" in t and "£4 a month" in t


def test_saving_a_key_checks_it_first(clock, home):
    fake = FakeRtt()
    core = Realliferail(clock=clock, home=home, transport=fake, demo=True)
    web = app_for(core)
    bad = web.post(
        "/settings/token",
        content="token=not-a-real-token-at-all-zzzz",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert bad.status_code == 400 and "refused the token" in text(bad)
    assert not (home / "settings.json").exists()
    ok = web.post(
        "/settings/token",
        content=f"token={GOOD}",
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=True,
    )
    assert "Token saved and working" in text(ok)
    assert "Hobbyist" in text(ok) and "quarter minute" in text(ok)
    assert GOOD not in ok.text  # never shown back
    assert "…bcdef" in text(ok)
    saved = json.loads((home / "settings.json").read_text())
    assert saved["rtt_token"] == GOOD
    assert oct((home / "settings.json").stat().st_mode)[-3:] == "600"
    assert not core.demo and "Demo data." not in ok.text


def test_free_tier_is_named_and_not_detailed(clock, home):
    fake = FakeRtt(entitlements=())
    core = Realliferail(clock=clock, home=home, transport=fake, demo=True)
    core.set_token(GOOD)
    tier = core.tier()
    assert tier.name == "Free" and not tier.detailed and tier.precision == "to the minute"


def test_bigger_allowance_reads_as_team(clock, home):
    core = Realliferail(clock=clock, home=home, transport=FakeRtt(hour="1200"), demo=True)
    core.set_token(GOOD)
    assert core.tier().name == "Team or above"


def test_remove_key_goes_back_to_demo(clock, home):
    core = Realliferail(clock=clock, home=home, transport=FakeRtt(), demo=True)
    core.set_token(GOOD)
    web = app_for(core)
    r = web.post("/settings/token/remove", follow_redirects=True)
    assert "Token removed" in text(r) and core.demo
    assert "rtt_token" not in json.loads((home / "settings.json").read_text())


def test_settings_writes_refused_from_outside(clock, home):
    core = Realliferail(clock=clock, home=home, transport=FakeRtt(), demo=True)
    web = app_for(core, allowed=False)
    r = web.post(
        "/settings/token", content=f"token={GOOD}", headers={"content-type": "application/x-www-form-urlencoded"}
    )
    assert r.status_code == 403 and core.demo
    assert "Check and save key" not in web.get("/settings").text


def test_cross_site_posts_refused(clock, home):
    core = Realliferail(clock=clock, home=home, transport=FakeRtt(), demo=True)
    r = app_for(core).post("/settings/token/remove", headers={"origin": "https://evil.example"})
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("host", "ok"),
    [
        ("127.0.0.1", True),
        ("192.168.0.20", True),
        ("10.1.2.3", True),
        ("100.101.102.103", False),
        ("::1", True),
        ("8.8.8.8", False),
        ("81.2.69.160", False),
        ("testclient", False),
        (None, False),
    ],
)
def test_private_client(host, ok):
    assert private_client(host) is ok


def test_settings_token_survives_restart_without_spending_calls(clock, home):
    fake = FakeRtt()
    core = Realliferail(clock=clock, home=home, transport=fake, demo=True)
    core.set_token(GOOD)
    before = len(fake.calls)
    again = Realliferail(token=GOOD, clock=clock, home=home, transport=fake, demo=False)
    again.service("X1:2026-11-07")
    # the cached access token and entitlements were reused: one call for the train, nothing to re-authenticate
    assert fake.calls[before:] == ["/gb-nr/service"]
    assert again.tier().name == "Hobbyist"


def test_cached_access_token_ignored_for_a_different_key(clock, home):
    fake = FakeRtt()
    Realliferail(clock=clock, home=home, transport=fake, demo=True).set_token(GOOD)
    c = RttClient(
        fake, "another-token-entirely-0000000000", Budget(clock=clock), clock=clock, state_file=home / "access.json"
    )
    assert c.info is None


def test_from_environment_prefers_settings(home, monkeypatch):
    home.mkdir(parents=True)
    (home / "settings.json").write_text(json.dumps({"rtt_token": "from-settings-xxxxxxxxxxxxxxxx"}))
    monkeypatch.setenv("RTT_TOKEN", "from-env-yyyyyyyyyyyyyyyyyyyyyy")
    core = from_environment(home=home)
    assert core.client._token == "from-settings-xxxxxxxxxxxxxxxx"


def test_pressing_refresh_repeatedly_costs_one_call(clock, home):
    fake = FakeRtt()
    core = Realliferail(clock=clock, home=home, transport=fake, demo=True)
    core.set_token(GOOD)
    core.service("X1:2026-11-07")
    n = fake.calls.count("/gb-nr/service")
    for _ in range(20):
        core.service("X1:2026-11-07", force=True)  # someone hammering the button
    assert fake.calls.count("/gb-nr/service") == n
    clock.advance(seconds=16)
    core.service("X1:2026-11-07", force=True)
    core.service("X1:2026-11-07", force=True)
    assert fake.calls.count("/gb-nr/service") == n + 1


def test_refresh_never_exceeds_the_minute_limit(clock, home):
    fake = FakeRtt()
    core = Realliferail(clock=clock, home=home, transport=fake, demo=True)
    core.set_token(GOOD)
    made = 0
    for i in range(30):  # 30 different trains in one minute
        try:
            core.service(f"X{i}:2026-11-07", force=True)
            made += 1
        except Exception:
            pass
    calls_this_minute = len(fake.calls)
    assert calls_this_minute <= 10
    assert made < 30
