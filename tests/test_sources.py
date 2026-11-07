import threading

import pytest

from realliferail.sources.budget import Budget
from realliferail.sources.rtt import AuthError, RttClient, RttError
from realliferail.sources.stations import StationIndex
from realliferail.sources.transport import HttpTransport, Response
from tests.conftest import at


class Fake:
    """Scripted transport. `answers` maps path to a list of Responses (last one repeats)."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def get(self, path, params, token):
        self.calls.append((path, dict(params), token))
        q = self.answers[path]
        return q.pop(0) if len(q) > 1 else q[0]


INFO = Response(200, {}, {"api_version": "2026-07-25", "credentials": {"entitlements": []}})


def client(clock, answers, token="tok", **kw):
    return RttClient(Fake(answers), token, Budget(clock=clock), clock=clock, **kw)


# ---- budget ----
def test_budget_starts_at_free_limits_and_counts(clock):
    b = Budget(clock=clock)
    for _ in range(10):
        assert b.can_spend(True)
        b.spend()
    assert not b.can_spend(True)  # 10 a minute
    clock.advance(seconds=61)
    assert b.can_spend(True)


def test_budget_trusts_headers(clock):
    b = Budget(clock=clock)
    b.observe(200, {"x-ratelimit-limit-hour": "100", "x-ratelimit-remaining-hour": "10"})
    assert b.remaining("hour") == 10
    assert b.can_spend(True)
    assert not b.can_spend(False)  # background refreshes keep a reserve of 10 for people searching
    b.observe(200, {"x-ratelimit-remaining-hour": "0"})
    assert not b.can_spend(True)


def test_budget_429_blocks_until_retry_after(clock):
    b = Budget(clock=clock)
    b.observe(429, {"retry-after": "30"})
    assert not b.can_spend(True)
    clock.advance(seconds=31)
    assert b.can_spend(True)


def test_refresh_interval_slows_when_the_hour_runs_low(clock):
    b = Budget(clock=clock)
    assert b.refresh_interval() == 40.0  # 3600 / (100 - 10)
    b.observe(200, {"x-ratelimit-remaining-hour": "20"})
    assert b.refresh_interval() == 360.0
    b.observe(200, {"x-ratelimit-remaining-hour": "5"})
    assert b.refresh_interval() == 600.0


# ---- client ----
def test_access_token_used_directly(clock):
    c = client(clock, {"/api/info": [INFO], "/gb-nr/service": [Response(200, {}, {"service": {}})]})
    c.service("X:2026-11-07")
    paths = [p for p, _, _ in c._t.calls]
    assert paths == ["/api/info", "/gb-nr/service"]
    assert c.info.kind == "access"


def test_refresh_token_exchanged(clock):
    answers = {
        "/api/info": [Response(401, {}, {"error": "bad"}), INFO],
        "/api/get_access_token": [Response(200, {}, {"token": "short", "validUntil": "2026-11-07T15:00:00Z"})],
        "/gb-nr/service": [Response(200, {}, {"service": {}})],
    }
    c = client(clock, answers, token="long")
    c.service("X:2026-11-07")
    assert c.info.kind == "refresh"
    assert c._t.calls[-1][2] == "short"


def test_bad_token_says_so(clock):
    c = client(clock, {"/api/info": [Response(401, {}, {})], "/api/get_access_token": [Response(401, {}, {})]})
    with pytest.raises(AuthError, match="api-portal"):
        c.service("X:2026-11-07")


def test_cache_shares_answers(clock):
    c = client(clock, {"/api/info": [INFO], "/gb-nr/service": [Response(200, {}, {"service": {}})]})
    a = c.service("X:2026-11-07")
    b = c.service("X:2026-11-07")
    assert a is b
    clock.advance(seconds=31)
    c.service("X:2026-11-07")
    assert sum(1 for p, _, _ in c._t.calls if p == "/gb-nr/service") == 2


def test_concurrent_requests_for_one_train_cost_one_call(clock):
    c = client(clock, {"/api/info": [INFO], "/gb-nr/service": [Response(200, {}, {"service": {}})]})
    c.check_token()
    threads = [threading.Thread(target=c.service, args=("X:2026-11-07",)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for p, _, _ in c._t.calls if p == "/gb-nr/service") == 1


def test_stale_answer_when_allowance_is_out(clock):
    c = client(clock, {"/api/info": [INFO], "/gb-nr/service": [Response(200, {}, {"service": {}})]})
    first = c.service("X:2026-11-07")
    c.budget.observe(200, {"x-ratelimit-remaining-hour": "0"})
    clock.advance(seconds=60)
    again = c.service("X:2026-11-07")
    assert again.stale and again.body is first.body and "allowance" in again.note


def test_no_cache_and_no_allowance_is_a_sentence(clock):
    c = client(clock, {"/api/info": [INFO]})
    c.check_token()
    c.budget.observe(200, {"x-ratelimit-remaining-hour": "0"})
    with pytest.raises(RttError, match="allowance"):
        c.service("X:2026-11-07")


def test_429_and_5xx_fall_back_to_cache(clock):
    c = client(
        clock,
        {
            "/api/info": [INFO],
            "/gb-nr/service": [
                Response(200, {}, {"service": {}}),
                Response(429, {"retry-after": "5"}, None),
                Response(503, {}, None),
            ],
        },
    )
    c.service("X:2026-11-07")
    clock.advance(seconds=31)
    assert c.service("X:2026-11-07").stale
    clock.advance(seconds=31)
    assert c.service("X:2026-11-07").stale


def test_204_is_no_services(clock):
    c = client(clock, {"/api/info": [INFO], "/gb-nr/location": [Response(204, {}, None)]})
    f = c.location("RDG", at(14, 0))
    assert f.body is None and not f.stale


def test_location_params(clock):
    c = client(clock, {"/api/info": [INFO], "/gb-nr/location": [Response(204, {}, None)]})
    c.location("rdg", at(14, 0), 90, "pad")
    _, params, _ = c._t.calls[-1]
    assert params == {"code": "RDG", "timeFrom": "2026-11-07T14:00:00", "timeWindow": "90", "filterTo": "PAD"}


def test_detailed_asked_for_only_when_allowed(clock):
    info = Response(200, {}, {"credentials": {"entitlements": ["allowDetailed"]}})
    c = client(clock, {"/api/info": [info], "/gb-nr/service": [Response(200, {}, {"service": {}})]})
    c.check_token()
    c.service("X:2026-11-07")
    assert c._t.calls[-1][1]["detailed"] == "true"


def test_404_and_400_are_sentences(clock):
    c = client(
        clock,
        {
            "/api/info": [INFO],
            "/gb-nr/service": [Response(404, {}, None)],
            "/gb-nr/location": [Response(400, {}, {"error": "history restricted"})],
        },
    )
    with pytest.raises(RttError, match="doesn't know"):
        c.service("X:2026-11-07")
    with pytest.raises(RttError, match="history restricted"):
        c.location("RDG", at(14, 0))


def test_transport_only_talks_to_rtt():
    with pytest.raises(ValueError, match=r"only data\.rtt\.io"):
        HttpTransport("https://example.com")


# ---- stations ----
def test_station_search():
    idx = StationIndex.bundled()
    assert len(idx.stations) > 2500
    assert idx.search("rdg")[0].name == "Reading"
    assert idx.search("Reading")[0].crs == "RDG"
    assert idx.search("kings cross")[0].crs == "KGX"
    assert idx.search("clap jun")[0].crs == "CLJ"
    assert idx.search("") == []
    assert idx.resolve("Reading (RDG)").crs == "RDG"
    assert idx.resolve("paddington").crs == "PAD"
    assert idx.resolve("zzzzqqq") is None
