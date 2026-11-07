from datetime import datetime, timedelta
from pathlib import Path

import pytest

from realliferail.domain.models import Display, Kind
from realliferail.domain.parse import LONDON, parse_board, parse_service, parse_time
from tests.conftest import FIXTURES, at, fixture_json


def test_naive_times_are_london_local():
    t = parse_time("2026-07-06T15:02:00")
    assert t.tzinfo is not None
    assert t.utcoffset() == timedelta(hours=1)  # BST in July
    assert parse_time("2026-11-07T15:02:00").utcoffset() == timedelta(0)  # GMT in November


def test_offset_times_are_converted_to_london():
    assert parse_time("2026-07-06T14:02:00Z") == datetime(2026, 7, 6, 15, 2, tzinfo=LONDON)
    assert parse_time("2026-07-06T15:02:00+01:00").hour == 15


@pytest.mark.parametrize("bad", [None, "", "not a time", 12, {}])
def test_bad_times_are_none(bad):
    assert parse_time(bad) is None


def test_board_quirks():
    when = at(15, 0, day=(2026, 7, 6))
    b = parse_board(fixture_json("spec_location_reading.json"), fallback_name="X", time_from=when, time_to=when)
    assert b.station_name == "Reading"
    assert b.station_crs == "RDG"
    assert b.time_from.hour == 15
    assert not b.status.ok and "limited" in b.status.message
    first, terminating, cancelled, bus = b.rows
    assert first.unique_id == "C11111:2026-07-06"
    assert first.headcode is None  # real board rows have none
    assert first.origin == "London Paddington" and first.destination == "Plymouth"
    assert first.platform == "9" and first.platform_confirmed and not first.platform_changed
    assert first.status == "AT_PLATFORM"
    assert first.arrival.actual == at(15, 3, day=(2026, 7, 6))
    assert terminating.terminates_here and terminating.platform == "14" and not terminating.platform_confirmed
    assert cancelled.cancelled
    assert cancelled.reasons[0].text == "A fault on this train."
    assert bus.mode == "REPLACEMENT_BUS" and bus.starts_here


def test_no_services_204_gives_an_empty_board():
    when = at(15, 0)
    b = parse_board(None, fallback_name="Reading", time_from=when, time_to=when + timedelta(hours=1))
    assert b.rows == () and b.station_name == "Reading" and b.status.ok


def test_service_points():
    s = parse_service(fixture_json("spec_service_reading_paddington.json"))
    assert s.unique_id == "C12345:2026-11-07"
    assert s.headcode == "1A23"
    assert [p.kind for p in s.points] == [Kind.CALL, Kind.PASS, Kind.PASS, Kind.CALL, Kind.CALL, Kind.PASS, Kind.CALL]
    east = s.points[1]
    assert east.display is Display.PASS  # displayAs null means a pass
    assert east.passing.internal.second == 30
    assert east.passing.actual == at(10, 4)
    assert east.allowances.pathing == 30
    mai = s.points[3]
    assert mai.arrival.advertised == at(10, 9) and mai.arrival.internal == at(10, 8, 30)
    assert mai.platform == "5" and mai.platform_changed
    assert s.points[4].cancelled
    assert s.points[2].allowances.total == 120
    assert s.vehicles == 5 and s.leading_class == "387"
    assert s.units == ("387131",)  # suppressed identities stay hidden
    assert s.reasons[0].text == "A late-running train ahead"
    assert s.origin_name == "Reading" and s.destination_name == "London Paddington"


def test_service_with_nothing_but_identity_still_parses():
    s = parse_service({"service": {"scheduleMetadata": {"uniqueIdentity": "gb-nr:X1:2026-01-02"}}})
    assert s.unique_id == "X1:2026-01-02" and s.points == () and s.operator_name == "Unknown operator"


def test_missing_everything_does_not_crash():
    parse_service({})
    parse_board({"services": [{}, None, 3]}, fallback_name="X", time_from=at(1, 0), time_to=at(2, 0))


REAL = sorted((FIXTURES / "rtt").glob("real_*.json"))


@pytest.mark.parametrize("path", REAL, ids=lambda p: Path(p).name)
def test_every_real_recording_parses(path):  # pragma: no cover - runs once recordings exist
    import json

    body = json.loads(path.read_text())
    if "service" in body:
        s = parse_service(body)
        assert s.points
    else:
        parse_board(body, fallback_name="?", time_from=at(0, 0), time_to=at(1, 0))
