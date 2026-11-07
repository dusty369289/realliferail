"""Our simulator and fixtures must match RTT's published OpenAPI schema, so demo mode can't drift from the real thing.

One adjustment to the spec, because it contradicts itself: enums on nullable fields gain null (the field
descriptions say null is allowed). Formats are not checked, so `trainReportingIdentity`'s stray `format: date` (its
example is "1L40") does no harm.
"""

import copy
from functools import cache
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from realliferail.sources.simulator import SimTransport
from tests.conftest import FIXTURES, Clock, at, fixture_json

SPEC = Path(__file__).resolve().parents[1] / "docs" / "rtt-openapi.yml"


def _fix(node):
    if isinstance(node, dict):
        one = node.get("oneOf")
        if (
            "enum" in node
            and isinstance(one, list)
            and any(o.get("type") == "null" for o in one if isinstance(o, dict))
        ):
            node["enum"] = [*node["enum"], None]
        for v in node.values():
            _fix(v)
    elif isinstance(node, list):
        for v in node:
            _fix(v)


@cache
def validator(path: str) -> Draft202012Validator:
    spec = yaml.safe_load(SPEC.read_text())
    spec = copy.deepcopy(spec)
    _fix(spec)
    resource = Resource(contents=spec, specification=DRAFT202012)
    registry = Registry().with_resource("spec", resource)
    pointer = "/paths/" + path.replace("/", "~1") + "/get/responses/200/content/application~1json/schema"
    return Draft202012Validator({"$ref": "spec#" + pointer}, registry=registry)


def errors(path: str, body) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator(path).iter_errors(body)]


@pytest.mark.parametrize("hour", [6, 9, 14, 17, 22])
def test_simulated_boards_match_the_spec(hour):
    clock = Clock(at(hour, 10))
    sim = SimTransport(clock=clock)
    for code in ("RDG", "PAD", "WAT", "CLJ", "OXF"):
        r = sim.get("/gb-nr/location", {"code": code, "timeFrom": f"2026-11-07T{hour:02d}:00:00"}, None)
        if r.status == 204:
            continue
        assert r.status == 200
        assert errors("/gb-nr/location", r.body) == []


def test_simulated_services_match_the_spec():
    clock = Clock(at(14, 10))
    sim = SimTransport(clock=clock)
    services = sim.tt.day(clock().date())
    for s in services[::7]:
        r = sim.get("/gb-nr/service", {"uniqueIdentity": f"{s.identity}:{s.run_date.isoformat()}"}, None)
        assert r.status == 200
        assert errors("/gb-nr/service", r.body) == [], s.identity


def test_fixtures_match_the_spec():
    assert errors("/gb-nr/location", fixture_json("spec_location_reading.json")) == []
    assert errors("/gb-nr/service", fixture_json("spec_service_reading_paddington.json")) == []


@pytest.mark.parametrize("p", sorted((FIXTURES / "rtt").glob("real_*.json")), ids=lambda p: p.name)
def test_real_recordings_match_the_spec(p):  # pragma: no cover - runs once recordings exist
    import json

    body = json.loads(p.read_text())
    path = "/gb-nr/service" if "service" in body else "/gb-nr/location"
    # a real answer that breaks the spec is worth knowing about, not hiding: the message names the field
    assert errors(path, body) == []


def test_the_validator_really_rejects_wrong_shapes():
    body = fixture_json("spec_service_reading_paddington.json")
    body["service"]["locations"][0]["temporalData"]["displayAs"] = "TELEPORTED"
    body["service"]["locations"][1]["temporalData"]["pass"]["realtimeNoReport"] = "yes"
    found = errors("/gb-nr/service", body)
    assert len(found) == 2, found
