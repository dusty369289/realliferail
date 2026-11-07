"""Turn RTT next-generation JSON into domain models.

Tolerant by design: every field may be missing. See docs/rtt-api.md for the quirks handled here. Naive times are UK
local time (observed), so they're given the Europe/London zone. Times with an offset keep it, converted to London.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .models import (
    Allowances,
    Board,
    BoardRow,
    Display,
    Endpoint,
    Kind,
    Point,
    Reason,
    Service,
    SystemStatus,
    Times,
)

LONDON = ZoneInfo("Europe/London")
ADVERTISED = {"ADVERTISED_OPEN", "ADVERTISED_SET_DOWN", "ADVERTISED_PICK_UP"}


def parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LONDON)
    return dt.astimezone(LONDON)


def _times(raw: Any) -> Times:
    if not isinstance(raw, dict):
        return Times()
    return Times(
        advertised=parse_time(raw.get("scheduleAdvertised")),
        internal=parse_time(raw.get("scheduleInternal")),
        forecast=parse_time(raw.get("realtimeForecast")),
        estimate=parse_time(raw.get("realtimeEstimate")),
        actual=parse_time(raw.get("realtimeActual")),
        no_report=bool(raw.get("realtimeNoReport")),
        cancelled=bool(raw.get("isCancelled")),
    )


def _strip_ns(code: str) -> str:
    return code.split(":", 1)[1] if ":" in code else code


def _first(codes: Any) -> str | None:
    if isinstance(codes, list) and codes and isinstance(codes[0], str):
        return _strip_ns(codes[0])
    return None


def _display(raw: Any) -> Display:
    try:
        return Display(raw) if raw else Display.PASS
    except ValueError:
        return Display.CALL


def _platform(meta: dict) -> tuple[str | None, bool, bool]:
    p = meta.get("platform")
    if not isinstance(p, dict):
        return None, False, False
    planned, forecast, actual = p.get("planned"), p.get("forecast"), p.get("actual")
    shown = actual or forecast or planned
    changed = bool(planned and shown and str(shown) != str(planned))
    return (str(shown) if shown is not None else None), bool(actual), changed


def _reasons(raw: Any) -> tuple[Reason, ...]:
    if not isinstance(raw, list):
        return ()
    out = []
    for r in raw:
        if isinstance(r, dict):
            text = r.get("longText") or r.get("shortText")
            if text:
                out.append(Reason(kind=str(r.get("type") or "DELAY"), text=str(text)))
    return tuple(out)


def _endpoints(raw: Any) -> tuple[Endpoint, ...]:
    if not isinstance(raw, list):
        return ()
    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        loc = e.get("location") or {}
        t = e.get("temporalData") or {}
        out.append(
            Endpoint(
                name=str(loc.get("description") or "Unknown"),
                tiploc=_first(loc.get("longCodes")),
                time=parse_time(t.get("scheduleAdvertised")) or parse_time(t.get("scheduleInternal")),
            )
        )
    return tuple(out)


def _status(raw: Any) -> SystemStatus:
    if not isinstance(raw, dict):
        return SystemStatus()
    return SystemStatus(network_rail=str(raw.get("realtimeNetworkRail") or "OK"), core=str(raw.get("rttCore") or "OK"))


def _unique(meta: dict) -> tuple[str, str, date]:
    identity = str(meta.get("identity") or "")
    run = meta.get("departureDate")
    uid = meta.get("uniqueIdentity")
    if not (identity and run) and isinstance(uid, str):
        parts = uid.split(":")
        if len(parts) >= 3:
            identity, run = identity or parts[-2], run or parts[-1]
    run_date = date.fromisoformat(run) if run else date.today()
    return f"{identity}:{run_date.isoformat()}", identity, run_date


def _pa(meta: dict, key: str) -> str | None:
    v = meta.get(key)
    if isinstance(v, dict):
        return v.get("actual") or v.get("forecast") or v.get("planned")
    return None


def parse_point(raw: dict) -> Point:
    t = raw.get("temporalData") or {}
    meta = raw.get("locationMetadata") or {}
    loc = raw.get("location") or {}
    display = _display(t.get("displayAs"))
    arrival, departure, passing = _times(t.get("arrival")), _times(t.get("departure")), _times(t.get("pass"))
    call_type = t.get("realtimeCallType") or t.get("scheduledCallType")
    is_pass = display is Display.PASS or (arrival.is_empty and departure.is_empty and not passing.is_empty)
    if display in (Display.CANCELLED, Display.DIVERTED) and not passing.is_empty and arrival.is_empty:
        is_pass = True
    platform, confirmed, changed = _platform(meta)
    allow = meta.get("allowances") if isinstance(meta.get("allowances"), dict) else {}

    return Point(
        name=str(loc.get("description") or "Unknown"),
        crs=_first(loc.get("shortCodes")),
        tiploc=_first(loc.get("longCodes")),
        kind=Kind.PASS if is_pass else Kind.CALL,
        display=display,
        arrival=arrival,
        departure=departure,
        passing=passing,
        platform=platform,
        platform_confirmed=confirmed,
        platform_changed=changed,
        status=t.get("status"),
        public=(call_type in ADVERTISED) if call_type else (not is_pass),
        request_stop=bool(meta.get("isRequestStop")),
        interpolated=bool(t.get("isInterpolated")),
        allowances=Allowances(
            engineering=int(allow.get("engineering") or 0),
            pathing=int(allow.get("pathing") or 0),
            performance=int(allow.get("performance") or 0),
        ),
        line=_pa(meta, "line"),
        path=_pa(meta, "path"),
    )


def parse_service(body: dict) -> Service:
    s = body.get("service") or {}
    meta = s.get("scheduleMetadata") or {}
    uid, identity, run_date = _unique(meta)
    points = tuple(parse_point(p) for p in (s.get("locations") or []) if isinstance(p, dict))
    vehicles = None
    units: list[str] = []
    leading = None
    alloc = s.get("allocationData")
    if isinstance(alloc, list) and alloc and isinstance(alloc[0], dict):
        vehicles = alloc[0].get("passengerVehicles")
        leading = alloc[0].get("leadingClass")
        for item in alloc[0].get("allocationItems") or []:
            if isinstance(item, dict) and item.get("identity") and not item.get("identitySuppressed"):
                units.append(str(item["identity"]))
    if vehicles is None:
        for p in s.get("locations") or []:
            n = (p.get("locationMetadata") or {}).get("numberOfVehicles") if isinstance(p, dict) else None
            if n:
                vehicles = n
                break
    origins = _endpoints(s.get("origin"))
    destinations = _endpoints(s.get("destination"))
    if not origins and points:
        origins = (Endpoint(points[0].name, points[0].tiploc, points[0].departure.booked),)
    if not destinations and points:
        destinations = (Endpoint(points[-1].name, points[-1].tiploc, points[-1].arrival.booked),)
    op = meta.get("operator") or {}
    return Service(
        unique_id=uid,
        identity=identity,
        run_date=run_date,
        headcode=meta.get("trainReportingIdentity"),
        operator_code=str(op.get("code") or ""),
        operator_name=str(op.get("name") or op.get("code") or "Unknown operator"),
        mode=str(meta.get("modeType") or "TRAIN"),
        passenger=meta.get("inPassengerService") is not False,
        origins=origins,
        destinations=destinations,
        points=points,
        reasons=_reasons(s.get("reasons")),
        vehicles=int(vehicles) if vehicles else None,
        units=tuple(units),
        leading_class=str(leading) if leading else None,
        branding=next(
            (
                lm.get("stockBranding")
                for p in s.get("locations") or []
                if isinstance(p, dict)
                for lm in [p.get("locationMetadata") or {}]
                if lm.get("stockBranding")
            ),
            None,
        ),
        stp=meta.get("stpIndicator"),
    )


def parse_board(body: dict | None, *, fallback_name: str, time_from: datetime, time_to: datetime) -> Board:
    """`body` is None for a 204 (no services)."""
    body = body or {}
    q = body.get("query") or {}
    loc = q.get("location") or {}
    rows = []
    for raw in body.get("services") or []:
        if not isinstance(raw, dict):
            continue
        t = raw.get("temporalData") or {}
        meta = raw.get("scheduleMetadata") or {}
        lm = raw.get("locationMetadata") or {}
        uid, identity, run_date = _unique(meta)
        platform, confirmed, changed = _platform(lm)
        op = meta.get("operator") or {}
        origins = _endpoints(raw.get("origin"))
        dests = _endpoints(raw.get("destination"))
        rows.append(
            BoardRow(
                unique_id=uid,
                identity=identity,
                run_date=run_date,
                headcode=meta.get("trainReportingIdentity"),
                operator_code=str(op.get("code") or ""),
                operator_name=str(op.get("name") or op.get("code") or ""),
                mode=str(meta.get("modeType") or "TRAIN"),
                origin=" & ".join(o.name for o in origins) or "Unknown",
                destination=" & ".join(d.name for d in dests) or "Unknown",
                arrival=_times(t.get("arrival")),
                departure=_times(t.get("departure")),
                platform=platform,
                platform_confirmed=confirmed,
                platform_changed=changed,
                display=_display(t.get("displayAs")) if t.get("displayAs") else Display.CALL,
                status=t.get("status"),
                vehicles=lm.get("numberOfVehicles"),
                passenger=meta.get("inPassengerService") is not False,
                call_type=t.get("realtimeCallType") or t.get("scheduledCallType"),
                branding=lm.get("stockBranding"),
                line=_pa(lm, "line"),
                stp=meta.get("stpIndicator"),
                reasons=_reasons(raw.get("reasons")),
            )
        )
    return Board(
        station_name=str(loc.get("description") or fallback_name),
        station_crs=_first(loc.get("shortCodes")),
        time_from=parse_time(q.get("timeFrom")) or time_from,
        time_to=parse_time(q.get("timeTo")) or time_to,
        rows=tuple(rows),
        status=_status(body.get("systemStatus")),
    )
