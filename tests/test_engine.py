from dataclasses import replace
from datetime import timedelta

from realliferail.domain.engine import State, build, stop_summary
from realliferail.domain.models import Kind, Times, TimeSource
from realliferail.domain.parse import parse_service
from tests.conftest import at, fixture_json


def svc():
    return parse_service(fixture_json("spec_service_reading_paddington.json"))


def test_running_between_reports():
    tl = build(svc(), at(10, 5))
    p = tl.position
    assert p.state is State.RUNNING
    assert (p.from_index, p.to_index) == (1, 2)  # passed Reading East Main, heading for Twyford
    assert 0 < p.fraction <= 0.95
    assert "Reading East Main" in p.headline and "Twyford" in p.headline
    assert p.delay_min == 2  # 10:04 against 10:01:30 working time: 2.5 min, whole minutes toward zero


def test_marker_holds_short_of_an_unreported_point():
    tl = build(svc(), at(10, 7))
    assert tl.position.fraction == 0.95


def test_overdue_says_so_plainly():
    tl = build(svc(), at(10, 20))
    assert tl.position.state is State.OVERDUE
    assert "No report at Twyford" in tl.position.headline


def test_our_estimate_fills_passes_and_uses_allowances():
    tl = build(svc(), at(10, 5))
    twy = tl.points[2]
    assert twy.passing.source is TimeSource.OUR_ESTIMATE
    # passed Reading East Main 10:04 (booked 10:01:30). The section is booked at 210 s with 30 s of pathing allowance,
    # and a late train wins back 75% of that: 10:04 + 187.5 s
    assert abs((twy.passing.time - at(10, 7, 7)).total_seconds()) <= 0.5


def test_rtt_forecast_wins_and_estimates_carry_on_from_it():
    tl = build(svc(), at(10, 5))
    mai = tl.points[3]
    assert mai.arrival.source is TimeSource.FORECAST and mai.arrival.time == at(10, 11)
    assert mai.departure.source is TimeSource.FORECAST and mai.departure.time == at(10, 12)
    southall = tl.points[5]
    assert southall.passing.source is TimeSource.OUR_ESTIMATE
    # carries on from RTT's 10:12 departure, not from our own earlier guess
    assert southall.passing.time >= at(10, 30)


def test_never_earlier_than_the_working_timetable():
    s = svc()
    # make the train very early at Reading East Main
    pts = list(s.points)
    pts[1] = replace(pts[1], passing=replace(pts[1].passing, actual=at(9, 50)))
    tl = build(replace(s, points=tuple(pts)), at(9, 51))
    for v in tl.points[2:]:
        for shown, ev in ((v.passing, v.point.passing), (v.arrival, v.point.arrival)):
            if shown and shown.source is TimeSource.OUR_ESTIMATE:
                assert shown.time >= ev.planned


def test_never_leaves_a_public_stop_early():
    s = svc()
    pts = list(s.points)
    # strip RTT's forecasts at Maidenhead so ours is used
    m = pts[3]
    pts[3] = replace(m, arrival=replace(m.arrival, forecast=None), departure=replace(m.departure, forecast=None))
    pts[1] = replace(pts[1], passing=replace(pts[1].passing, actual=at(9, 58)))
    tl = build(replace(s, points=tuple(pts)), at(9, 59))
    assert tl.points[3].departure.time >= at(10, 10)


def test_not_started():
    s = svc()
    pts = list(s.points)
    pts[0] = replace(pts[0], departure=replace(pts[0].departure, actual=None))
    pts[1] = replace(pts[1], passing=replace(pts[1].passing, actual=None))
    tl = build(replace(s, points=tuple(pts)), at(9, 50))
    assert tl.position.state is State.NOT_STARTED
    assert "10:00" in tl.position.headline
    late = build(replace(s, points=tuple(pts)), at(10, 3))
    assert late.position.state is State.AT_ORIGIN


def test_at_station_while_dwelling():
    s = svc()
    pts = list(s.points)
    pts[2] = replace(pts[2], passing=replace(pts[2].passing, actual=at(10, 7)))
    pts[3] = replace(pts[3], arrival=replace(pts[3].arrival, actual=at(10, 11)))
    tl = build(replace(s, points=tuple(pts)), at(10, 11, 30))
    assert tl.position.state is State.AT_STATION
    assert tl.position.from_index == 3
    assert "At Maidenhead" in tl.position.headline


def test_arrived():
    s = svc()
    pts = [
        replace(p, passing=replace(p.passing, actual=p.passing.planned))
        if p.kind is Kind.PASS
        else replace(
            p,
            arrival=replace(p.arrival, actual=p.arrival.planned),
            departure=replace(p.departure, actual=p.departure.planned),
        )
        for p in s.points
    ]
    tl = build(replace(s, points=tuple(pts)), at(11, 0))
    assert tl.position.state is State.ARRIVED
    assert "London Paddington" in tl.position.headline


def test_cancelled_points_are_skipped_for_position():
    s = svc()
    pts = list(s.points)
    for i in (2, 3):
        p = pts[i]
        pts[i] = replace(
            p,
            passing=replace(p.passing, actual=at(10, 7)),
            arrival=replace(p.arrival, actual=at(10, 11)),
            departure=replace(p.departure, actual=at(10, 13)),
        )
    tl = build(replace(s, points=tuple(pts)), at(10, 14))
    assert tl.position.from_index == 3
    assert tl.position.to_index == 5  # Slough (4) is cancelled


def test_whole_train_cancelled():
    s = svc()
    from realliferail.domain.models import Display

    pts = tuple(replace(p, display=Display.CANCELLED) for p in s.points)
    tl = build(replace(s, points=pts), at(10, 0))
    assert tl.position.state is State.CANCELLED


def test_empty_service():
    tl = build(replace(svc(), points=()), at(10, 0))
    assert tl.position.state is State.NO_DATA


def test_stop_summary():
    tl = build(svc(), at(10, 5))
    mai = stop_summary(tl, "MAI")
    assert mai.status == "ahead" and mai.minutes == 7 and mai.platform == "5" and mai.calls_between == 0
    assert stop_summary(tl, "RDG").status == "gone"
    assert stop_summary(tl, "SLO").status == "cancelled"
    pad = stop_summary(tl, "pad", boarding=False)
    assert pad.status == "ahead" and pad.calls_between == 1  # Maidenhead; Slough is cancelled
    assert stop_summary(tl, "TWY") is None  # passes aren't stops
    assert stop_summary(tl, "") is None


def test_lateness_rounds_toward_zero():
    s = svc()
    pts = list(s.points)
    pts[1] = replace(pts[1], passing=Times(internal=at(10, 1, 30), actual=at(10, 1)))
    tl = build(replace(s, points=tuple(pts)), at(10, 2))
    assert tl.points[1].passing.delay_min == 0
    assert tl.position.delay_min == 0
    assert "on time" in tl.position.headline


def test_moving_forward_in_time_never_moves_backwards():
    s = svc()
    fractions = [build(s, at(10, 4) + timedelta(seconds=15 * k)).position.fraction for k in range(20)]
    assert fractions == sorted(fractions)
