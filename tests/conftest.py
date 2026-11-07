from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from realliferail.services.app import Realliferail
from realliferail.sources.simulator import SimTransport

pytest_plugins = ["tests.harness.review"]

LONDON = ZoneInfo("Europe/London")
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    """Tests never touch the network, and never see a real token. Live tests (-m live) are the one exception."""
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.delenv("RTT_TOKEN", raising=False)
    monkeypatch.delenv("REALLIFERAIL_DEMO", raising=False)
    monkeypatch.setattr("realliferail.services.app.default_env_files", lambda: [])

    def refuse(*a, **k):
        raise AssertionError("a test tried to use the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)


def fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / "rtt" / name).read_text("utf-8"))


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw):
        from datetime import timedelta

        self.t = self.t + timedelta(**kw)


def at(h: int, m: int, s: int = 0, day: tuple[int, int, int] = (2026, 11, 7)) -> datetime:
    return datetime(*day, h, m, s, tzinfo=LONDON)


@pytest.fixture
def clock() -> Clock:
    return Clock(at(14, 20))


@pytest.fixture
def demo(clock) -> Realliferail:
    return Realliferail(transport=SimTransport(clock=clock), token="test-token", clock=clock, demo=False)
