"""The whole app, fed real recordings from data.rtt.io (Hobbyist token, detailed mode, Reading, 2026-11-07 15:26)."""

import html
import json
import re

import pytest
from fastapi.testclient import TestClient

from realliferail.domain.engine import State, build
from realliferail.domain.models import Kind
from realliferail.domain.parse import parse_board, parse_service
from realliferail.services.app import Realliferail
from realliferail.sources.transport import Response
from realliferail.web.app import create_app
from tests.conftest import FIXTURES, Clock, at

REAL = FIXTURES / "rtt"
BOARD = REAL / "real_location_RDG_20261107-1526.json"
SERVICES = {p.name.split("_")[2]: p for p in REAL.glob("real_service_*_20261107-1526.json")}
NOW = at(15, 26, 5)

INFO = {"api_version": "2026-07-25", "credentials": {"entitlements": ["allowAllocationsPassenger", "allowDetailed"]}}


class Replay:
    def __init__(self):
        self.calls = []

    def get(self, path, params, token):
        self.calls.append((path, params))
        if path == "/api/info":
            return Response(200, {}, INFO)
        if path == "/gb-nr/location":
            return Response(200, {}, json.loads(BOARD.read_text()))
        if path == "/gb-nr/service":
            ident = params["uniqueIdentity"].split(":")[0]
            if ident in SERVICES:
                return Response(200, {}, json.loads(SERVICES[ident].read_text()))
            return Response(404, {}, None)
        return Response(404, {}, None)


pytestmark = pytest.mark.skipif(not BOARD.exists(), reason="no real recordings")


@pytest.fixture
def web():
    clock = Clock(NOW)
    return TestClient(create_app(Realliferail(transport=Replay(), token="t", clock=clock, demo=False)))


def text(r):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", r.text)).split())


def test_real_board_parses_with_detail():
    b = parse_board(json.loads(BOARD.read_text()), fallback_name="", time_from=NOW, time_to=NOW)
    assert len(b.rows) == 57
    assert sum(1 for r in b.rows if not r.for_passengers) == 2
    assert any(r.is_bus for r in b.rows)
    assert all(r.headcode for r in b.rows)  # detailed mode gives headcodes
    assert {"Arterio", "Voyager"} <= {r.branding for r in b.rows}


def test_real_services_have_quarter_minute_actuals_and_passes():
    for path in SERVICES.values():
        s = parse_service(json.loads(path.read_text()))
        passes = [p for p in s.points if p.kind is Kind.PASS]
        assert len(passes) >= 15
        seconds = {t.actual.second for p in s.points for t in (p.arrival, p.departure, p.passing) if t.actual}
        assert seconds <= {0, 15, 30, 45} and seconds - {0}
        assert s.headcode and s.units and s.leading_class
        tl = build(s, NOW)
        assert tl.position.state in (State.RUNNING, State.AT_STATION)


def test_board_hides_empty_stock_unless_asked(web):
    r = web.get("/board", params={"station": "RDG"})
    t = text(r)
    assert "Bristol East Depot" not in t and "Reading Traincare Depot" not in t
    assert "hidden: show all" in t
    everything = web.get("/board", params={"station": "RDG", "all": 1})
    assert "Bristol East Depot" in text(everything) and "Not in service" in text(everything)


def test_departures_leave_out_set_down_only_calls(web):
    r = web.get("/board", params={"station": "RDG"})
    # 1V51 terminates at Reading (set down only), so it isn't a departure
    assert "1V51" not in text(r)
    arr = web.get("/board", params={"station": "RDG", "mode": "arr"})
    assert "1V51" in text(arr)


def test_bus_rows_are_labelled(web):
    assert "Bus · Great Western Railway" in text(web.get("/board", params={"station": "RDG"}))


def test_real_train_page(web):
    r = web.get("/train/C42388:2026-11-07?at=RDG")
    assert r.status_code == 200
    t = text(r)
    assert "1D27" in t or "1V51" in t
    assert re.search(r"\d\d:\d\d[¼½¾]", t), "quarter-minute actuals should show as fractions"
    assert r.text.count("route__pt is-pass") >= 15
