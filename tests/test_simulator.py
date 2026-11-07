from collections import Counter
from datetime import timedelta

from realliferail.domain.engine import State, build
from realliferail.domain.models import Kind
from realliferail.domain.parse import parse_board, parse_service
from realliferail.sources.simulator import SimTransport, Timetable
from tests.conftest import Clock, at


def test_timetable_is_stable_and_has_every_delay_profile():
    a, b = Timetable().day(at(0, 0).date()), Timetable().day(at(0, 0).date())
    assert [s.identity for s in a] == [s.identity for s in b]
    assert len({s.identity for s in a}) == len(a)  # identities are unique
    profiles = Counter(s.profile for s in a)
    assert set(profiles) == {"on-time", "late-recovering", "late-growing", "held", "cancelled", "part-cancelled"}
    assert profiles["on-time"] > len(a) / 3


def test_reports_appear_as_time_passes():
    clock = Clock(at(14, 0))
    sim = SimTransport(clock=clock)
    s = next(x for x in sim.tt.day(clock().date()) if x.profile == "on-time" and x.origin.dep >= at(14, 5))
    uid = {"uniqueIdentity": f"{s.identity}:{s.run_date.isoformat()}"}
    reported = []
    while clock() < s.destination.arr + timedelta(minutes=5):
        svc = parse_service(sim.get("/gb-nr/service", uid, None).body)
        reported.append(sum(1 for p in svc.points if (p.passing.actual or p.departure.actual or p.arrival.actual)))
        clock.advance(minutes=5)
    assert reported == sorted(reported)
    assert reported[0] == 0 and reported[-1] == len(s.points)


def test_actuals_are_whole_minutes_and_working_times_half_minutes():
    clock = Clock(at(16, 0))
    sim = SimTransport(clock=clock)
    seconds_actual, seconds_wtt = set(), set()
    for s in sim.tt.day(clock().date())[:40]:
        svc = parse_service(sim.get("/gb-nr/service", {"uniqueIdentity": f"{s.identity}:{s.run_date}"}, None).body)
        for p in svc.points:
            for t in (p.arrival, p.departure, p.passing):
                if t.actual:
                    seconds_actual.add(t.actual.second)
                if t.internal:
                    seconds_wtt.add(t.internal.second)
    assert seconds_actual == {0}
    assert seconds_wtt == {0, 30}


def test_held_train_shows_overdue_in_the_engine():
    clock = Clock(at(12, 0))
    sim = SimTransport(clock=clock)
    s = next(x for x in sim.tt.day(clock().date()) if x.profile == "held" and x.origin.dep >= at(12, 0))
    uid = {"uniqueIdentity": f"{s.identity}:{s.run_date}"}
    states = set()
    while clock() < s.destination.arr + timedelta(minutes=20):
        svc = parse_service(sim.get("/gb-nr/service", uid, None).body)
        states.add(build(svc, clock()).position.state)
        clock.advance(seconds=30)
    assert State.OVERDUE in states and State.ARRIVED in states and State.RUNNING in states


def test_board_filters_and_204():
    clock = Clock(at(14, 0))
    sim = SimTransport(clock=clock)
    r = sim.get("/gb-nr/location", {"code": "RDG", "timeFrom": "2026-11-07T14:00:00", "filterTo": "OXF"}, None)
    b = parse_board(r.body, fallback_name="", time_from=clock(), time_to=clock())
    assert b.rows and all(row.destination == "Oxford" for row in b.rows)
    r = sim.get("/gb-nr/location", {"code": "EDB", "timeFrom": "2026-11-07T14:00:00"}, None)
    assert r.status == 204 and r.body is None
    assert sim.get("/gb-nr/location", {}, None).status == 400


def test_passes_include_both_display_forms():
    clock = Clock(at(14, 0))
    sim = SimTransport(clock=clock)
    s = sim.tt.day(clock().date())[0]
    body = sim.get("/gb-nr/service", {"uniqueIdentity": f"{s.identity}:{s.run_date}"}, None).body
    forms = {loc["temporalData"]["displayAs"] for loc in body["service"]["locations"] if "pass" in loc["temporalData"]}
    assert forms == {"PASS", None}
    svc = parse_service(body)
    assert any(p.kind is Kind.PASS for p in svc.points)


def test_reverse_direction_allowances_follow_the_train():
    tt = Timetable()
    day = tt.day(at(0, 0).date())
    up = next(s for s in day if s.pattern.headcode == "2K" and s.origin.loc.crs == "WAT")
    down = next(s for s in day if s.pattern.headcode == "2K" and s.origin.loc.crs == "WOK")
    # Surbiton carries the allowance towards Woking; going the other way, it's applied after Hampton Court Jn
    assert next(p for p in up.points if p.loc.crs == "SUR").allow_after == 60
    assert next(p for p in down.points if p.loc.tiploc == "HMPTNJ").allow_after == 60
    total_up = (up.destination.arr - up.origin.dep).total_seconds()
    total_down = (down.destination.arr - down.origin.dep).total_seconds()
    assert total_up == total_down
