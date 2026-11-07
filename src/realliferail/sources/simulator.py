"""A pretend data.rtt.io for demo mode and tests.

Answers the same paths with the same JSON shapes as the real API, including the quirks seen in a real response
(docs/rtt-api.md "Observed quirks"): naive local times, namespaced query long codes, no shortCodes on origin and
destination, `platform.forecast`, no headcode on board rows, and passes whose displayAs is "PASS" or null.

Routes are real lines with real station names and plausible working-timetable section times. They are not a copy of
any real timetable. Trains move in real time: a point is reported once the train's true time there has passed, with
actuals rounded down to the minute like real reports. Each train gets a delay profile from a hash of its identity:
on time, late and recovering, late and getting later, held at a signal in one section, or cancelled.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .transport import Response

LONDON = ZoneInfo("Europe/London")


@dataclass(frozen=True)
class Loc:
    name: str
    crs: str | None  # None for a timing point that isn't a station
    tiploc: str
    run: float  # booked minutes from the previous location, for a stopping train
    allowance: int = 0  # seconds of performance allowance in the section *after* this location


# GWR main line, Paddington to Oxford
GW = [
    Loc("London Paddington", "PAD", "PADTON", 0),
    Loc("Royal Oak", None, "ROYAOJN", 1.5),
    Loc("Westbourne Park", None, "WBRNPKS", 0.5),
    Loc("Ladbroke Grove", None, "LADBRKG", 1),
    Loc("Old Oak Common East Jn", None, "OLDOXRS", 1),
    Loc("Acton Main Line", "AML", "ACTONML", 1.5),
    Loc("Ealing Broadway", "EAL", "EALINGB", 1.5),
    Loc("West Ealing", "WEA", "WEALING", 1),
    Loc("Hanwell", "HAN", "HANWELL", 1),
    Loc("Southall", "STL", "STHALL", 2, allowance=60),
    Loc("Hayes & Harlington", "HAY", "HAYESAH", 2),
    Loc("Airport Junction", None, "AIRPJN", 1),
    Loc("West Drayton", "WDT", "WDRYTON", 1.5),
    Loc("Iver", "IVR", "IVER", 1.5),
    Loc("Langley", "LNY", "LANGLEY", 1.5),
    Loc("Slough", "SLO", "SLOUGH", 2, allowance=60),
    Loc("Burnham", "BNM", "BNHAM", 2),
    Loc("Taplow", "TAP", "TAPLOW", 1.5),
    Loc("Maidenhead", "MAI", "MDNHEAD", 1.5),
    Loc("Ruscombe", None, "RUSCOMB", 3),
    Loc("Twyford", "TWY", "TWYFORD", 1.5, allowance=120),
    Loc("Reading East Main", None, "RDNGEMJ", 3.5),
    Loc("Reading", "RDG", "RDNGSTN", 1.5),
    Loc("Reading West Jn", None, "RDNGWJN", 1),
    Loc("Tilehurst", "TLH", "TILHRST", 2),
    Loc("Pangbourne", "PAN", "PANGBRN", 3),
    Loc("Goring & Streatley", "GOR", "GORASTR", 3),
    Loc("Cholsey", "CHO", "CHOLSEY", 3),
    Loc("Didcot East Jn", None, "DIDCTEJ", 3.5),
    Loc("Didcot Parkway", "DID", "DIDCOTP", 1, allowance=60),
    Loc("Didcot North Jn", None, "DIDCTNJ", 1.5),
    Loc("Appleford", "APF", "APLFORD", 2.5),
    Loc("Culham", "CUM", "CULHAM", 2),
    Loc("Radley", "RAD", "RADLEY", 2),
    Loc("Kennington Jn", None, "KNNGTNJ", 3),
    Loc("Oxford", "OXF", "OXFD", 3),
]

# South Western main line, Waterloo to Woking
SW = [
    Loc("London Waterloo", "WAT", "WATRLMN", 0),
    Loc("Vauxhall", "VXH", "VAUXHLM", 2),
    Loc("Queenstown Road (Battersea)", "QRB", "QTRDBAT", 2),
    Loc("Clapham Junction", "CLJ", "CLPHMJM", 2, allowance=60),
    Loc("Earlsfield", "EAD", "EARLFLD", 2),
    Loc("Wimbledon", "WIM", "WDON", 3),
    Loc("Raynes Park", "RAY", "RAYNSPK", 2),
    Loc("New Malden", "NEM", "NEWMLDN", 2),
    Loc("Berrylands", "BRS", "BRLANDS", 2),
    Loc("Surbiton", "SUR", "SURBITN", 2, allowance=60),
    Loc("Hampton Court Jn", None, "HMPTNJ", 1.5),
    Loc("Esher", "ESH", "ESHER", 1.5),
    Loc("Hersham", "HER", "HERSHAM", 2),
    Loc("Walton-on-Thames", "WAL", "WALTON", 2),
    Loc("Weybridge", "WYB", "WEYBDGE", 3),
    Loc("Byfleet & New Haw", "BFN", "BYFLETT", 2),
    Loc("West Byfleet", "WBY", "WBYFLET", 2),
    Loc("Woking Junction", None, "WOKINGJ", 2.5),
    Loc("Woking", "WOK", "WOKING", 0.5),
]


@dataclass(frozen=True)
class Pattern:
    route: str
    op_code: str
    op_name: str
    prefix: str  # identity letter
    headcode: str  # e.g. "1P" or "2R"
    stops: frozenset[str] | None  # tiplocs it calls at; None means every station
    speed: float  # share of the stopping train's section time when not stopping either side
    minutes: tuple[int, ...]  # minutes past each hour it leaves its origin
    first_hour: int = 6
    last_hour: int = 23
    vehicles: int = 8
    end: str | None = None  # tiploc where it terminates early (None means the end of the route)


PATTERNS = [
    Pattern(
        "GW",
        "GW",
        "Great Western Railway",
        "C",
        "1P",
        frozenset({"PADTON", "SLOUGH", "RDNGSTN", "DIDCOTP", "OXFD"}),
        0.72,
        (0, 30),
        vehicles=9,
    ),
    Pattern("GW", "XR", "Elizabeth Line", "C", "9R", None, 1.0, (12, 42), vehicles=9, end="RDNGSTN"),
    Pattern(
        "GW",
        "GW",
        "Great Western Railway",
        "C",
        "2N",
        frozenset(
            {"RDNGSTN", "TILHRST", "PANGBRN", "GORASTR", "CHOLSEY", "DIDCOTP", "APLFORD", "CULHAM", "RADLEY", "OXFD"}
        ),
        1.0,
        (21,),
        vehicles=4,
    ),
    Pattern(
        "SW",
        "SW",
        "South Western Railway",
        "W",
        "1D",
        frozenset({"WATRLMN", "CLPHMJM", "SURBITN", "WOKING"}),
        0.75,
        (5, 35),
        vehicles=10,
    ),
    Pattern("SW", "SW", "South Western Railway", "W", "2K", None, 1.0, (20, 50), vehicles=8),
]
ROUTES = {"GW": GW, "SW": SW}


def _h(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


@dataclass
class SimPoint:
    loc: Loc
    calls: bool
    arr: datetime | None  # working timetable
    dep: datetime | None
    pas: datetime | None
    true_arr: datetime | None = None
    true_dep: datetime | None = None
    true_pas: datetime | None = None
    platform: str | None = None
    cancelled: bool = False
    allow_after: int = 0  # seconds of allowance in the section after this point, in this train's direction


@dataclass
class SimService:
    identity: str
    headcode: str
    run_date: date
    pattern: Pattern
    points: list[SimPoint]
    profile: str
    cancelled: bool = False

    @property
    def origin(self) -> SimPoint:
        return self.points[0]

    @property
    def destination(self) -> SimPoint:
        return self.points[-1]


def _half(minutes: float) -> timedelta:
    return timedelta(seconds=round(minutes * 2) * 30)


def build_service(pattern: Pattern, start: datetime, reverse: bool, run_date: date, n: int) -> SimService:
    locs = list(ROUTES[pattern.route])
    if pattern.end:
        cut = next(i for i, loc in enumerate(locs) if loc.tiploc == pattern.end)
        locs = locs[: cut + 1]
    # pattern stops may start mid-route (e.g. Reading to Oxford stopper)
    stops = pattern.stops
    if stops is not None:
        idx = [i for i, loc in enumerate(locs) if loc.tiploc in stops]
        locs = locs[idx[0] : idx[-1] + 1]
    runs = [loc.run for loc in locs]
    allows = [loc.allowance for loc in locs]
    if reverse:
        # section times belong between neighbours, so shift them when the list flips
        locs = locs[::-1]
        runs = [0, *runs[::-1][:-1]]
        allows = [*allows[::-1][1:], 0]
    pts: list[SimPoint] = []
    t = start
    for i, loc in enumerate(locs):
        calls = loc.crs is not None and (stops is None or loc.tiploc in stops)
        if i > 0:
            prev_calls = pts[-1].calls
            share = 1.0 if (calls or prev_calls) else pattern.speed
            t += _half(runs[i] * share + allows[i - 1] / 60)
        if i == 0:
            pts.append(SimPoint(loc, True, None, t, None))
        elif i == len(locs) - 1:
            pts.append(SimPoint(loc, True, t, None, None))
        elif calls:
            dwell = timedelta(minutes=1) if loc.crs in {"RDG", "CLJ", "SUR", "DID", "SLO"} else timedelta(seconds=30)
            pts.append(SimPoint(loc, True, t, t + dwell, None))
            t += dwell
        else:
            pts.append(SimPoint(loc, False, None, None, t))
    ident = f"{pattern.prefix}{_h(pattern.headcode, start.isoformat(), reverse) % 90000 + 10000:05d}"
    letter = pattern.headcode[1]
    hc = (
        f"{pattern.headcode[0]}{letter}{n % 100:02d}"
        if not reverse
        else f"{pattern.headcode[0]}{chr(ord(letter) + 1)}{n % 100:02d}"
    )
    for i, p in enumerate(pts):
        p.allow_after = allows[i] if i < len(pts) - 1 else 0
        if p.calls:
            p.platform = (
                str(1 + (_h(ident, i) % 4) + (0 if not reverse else 4))
                if p.loc.crs not in {"WOK", "OXF"}
                else str(1 + (_h(ident, i) % 2) + (2 if reverse else 0))
            )
    svc = SimService(ident, hc, run_date, pattern, pts, profile="")
    _apply_profile(svc)
    return svc


def _apply_profile(s: SimService) -> None:
    r = _h("profile", s.identity, s.run_date) % 100
    if r < 52:
        profile = "on-time"
    elif r < 74:
        profile = "late-recovering"
    elif r < 86:
        profile = "late-growing"
    elif r < 95:
        profile = "held"
    elif r < 98:
        profile = "cancelled"
    else:
        profile = "part-cancelled"
    s.profile = profile
    start_delay = 0.0
    if profile == "late-recovering":
        start_delay = 3 + _h("d", s.identity) % 7
    elif profile == "late-growing":
        start_delay = 1 + _h("d", s.identity) % 3
    held_at = 2 + _h("held", s.identity) % max(len(s.points) - 3, 1)
    held_for = 3 + _h("hf", s.identity) % 6
    delay = start_delay * 60.0
    jitter_seed = _h("j", s.identity)
    for i, p in enumerate(s.points):
        noise = ((jitter_seed >> (i % 40)) & 3) * 10 - 15  # -15..+15 s
        if profile == "late-growing" and i > 0:
            delay += 25 + (jitter_seed >> (i % 30) & 1) * 30
        if profile == "held" and i == held_at:
            delay += held_for * 60
        d = timedelta(seconds=max(delay + noise, -50))
        if p.calls:
            if p.arr:
                p.true_arr = p.arr + d
            if p.dep:
                # never leave early; a late train uses spare dwell to recover a little
                p.true_dep = (
                    max(p.dep, (p.true_arr or p.dep) + timedelta(seconds=25)) if p.arr else p.dep + max(d, timedelta(0))
                )
                delay = (p.true_dep - p.dep).total_seconds()
        else:
            p.true_pas = p.pas + d
        if profile == "late-recovering" and i > 0:
            delay = max(delay - s.points[i - 1].allow_after * 0.8 - 15, 0)
    if profile == "cancelled":
        s.cancelled = True
        for p in s.points:
            p.cancelled = True
    elif profile == "part-cancelled":
        cut = len(s.points) * 2 // 3
        for p in s.points[cut:]:
            p.cancelled = True


class Timetable:
    """All simulated services for a day. Built lazily and kept, so identities stay stable."""

    def __init__(self):
        self._days: dict[date, list[SimService]] = {}

    def day(self, d: date) -> list[SimService]:
        if d not in self._days:
            out = []
            for pi, pat in enumerate(PATTERNS):
                n = pi * 20
                for hour in range(pat.first_hour, pat.last_hour + 1):
                    for minute in pat.minutes:
                        n += 1
                        start = datetime.combine(d, time(hour, minute), tzinfo=LONDON)
                        for reverse in (False, True):
                            out.append(
                                build_service(
                                    pat, start + (timedelta(minutes=7) if reverse else timedelta()), reverse, d, n
                                )
                            )
            self._days[d] = out
        return self._days[d]

    def find(self, identity: str, d: date) -> SimService | None:
        return next((s for s in self.day(d) if s.identity == identity), None)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(LONDON).replace(tzinfo=None).isoformat(timespec="seconds") if dt else None


def _floor_min(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


REPORT_LAG = timedelta(seconds=30)


def _event(
    planned: datetime | None,
    true: datetime | None,
    now: datetime,
    advertised: bool,
    delay_now: float,
    cancelled: bool,
    is_dep: bool,
) -> dict | None:
    if planned is None:
        return None
    ev: dict[str, Any] = {"scheduleInternal": _iso(planned)}
    if advertised:
        ev["scheduleAdvertised"] = _iso(_floor_min(planned))
    if cancelled:
        ev["isCancelled"] = True
        return ev
    if true is not None and now >= true + REPORT_LAG:
        act = _floor_min(true + timedelta(seconds=30))  # reports are to the nearest minute
        ev["realtimeActual"] = _iso(act)
        ev["realtimeInternalLateness"] = round((act - planned).total_seconds() / 60)
        if advertised:
            ev["realtimeAdvertisedLateness"] = round((act - _floor_min(planned)).total_seconds() / 60)
    elif advertised:
        # RTT-style forecast at calls: current delay carried forward, never leaving early
        f = planned + timedelta(seconds=max(delay_now, 0 if is_dep else -60))
        ev["realtimeForecast"] = _iso(_floor_min(f))
    ev["isCancelled"] = False
    return ev


class SimTransport:
    """Implements Transport. `clock` gives the simulated now."""

    def __init__(
        self, clock=lambda: datetime.now(UTC), timetable: Timetable | None = None, stations=None, limit_hour: int = 100
    ):
        self.clock = clock
        self.tt = timetable or Timetable()
        self.stations = stations  # optional StationIndex, for names of stations the routes don't cover
        self.requests: list[tuple[str, dict]] = []
        self.limit_hour = limit_hour

    def _headers(self) -> dict[str, str]:
        used = len(self.requests)
        return {
            "x-ratelimit-limit-minute": "10",
            "x-ratelimit-remaining-minute": str(max(10 - used % 10, 0)),
            "x-ratelimit-limit-hour": str(self.limit_hour),
            "x-ratelimit-remaining-hour": str(max(self.limit_hour - used, 0)),
            "x-ratelimit-limit-day": "1000",
            "x-ratelimit-remaining-day": str(max(1000 - used, 0)),
        }

    def get(self, path: str, params: dict[str, str], token: str | None) -> Response:
        self.requests.append((path, dict(params)))
        h = self._headers()
        if path == "/api/info":
            return Response(
                200,
                h,
                {
                    "api_version": "2026-07-25",
                    "credentials": {
                        "entitlements": [],
                        "historyRestriction": True,
                        "historyRestrictToDays": 14,
                        "namespaceRestriction": True,
                        "namespacesAvailable": ["gb-nr"],
                    },
                },
            )
        if path == "/gb-nr/location":
            return self._location(params, h)
        if path == "/gb-nr/service":
            return self._service(params, h)
        return Response(404, h, {"error": "Not found"})

    # ---- helpers ----
    def _now(self) -> datetime:
        return self.clock().astimezone(LONDON)

    def _delay_before(self, s: SimService, idx: int, now: datetime) -> float:
        """Delay (s) at the last reported point before idx, as RTT would see it."""
        delay = 0.0
        for p in s.points[:idx]:
            for planned, true in ((p.dep, p.true_dep), (p.pas, p.true_pas), (p.arr, p.true_arr)):
                if planned and true and now >= true + REPORT_LAG:
                    delay = (true - planned).total_seconds()
                    break
        return delay

    def _status(self, s: SimService, i: int, now: datetime) -> str | None:
        p = s.points[i]
        if s.cancelled or p.cancelled or not p.calls:
            return None
        if p.true_arr and p.true_arr <= now and (p.true_dep is None or now < p.true_dep):
            return "AT_PLATFORM" if (p.true_dep is None or now < p.true_dep - timedelta(seconds=30)) else "DEPART_READY"
        if p.true_arr and p.true_arr - timedelta(minutes=2) <= now < p.true_arr:
            return "APPROACHING"
        if p.true_dep and p.true_dep <= now < p.true_dep + timedelta(seconds=40):
            return "DEPARTING"
        return None

    def _temporal(self, s: SimService, i: int, now: datetime) -> dict:
        p = s.points[i]
        cancelled = s.cancelled or p.cancelled
        delay = self._delay_before(s, i + 1, now)
        t: dict[str, Any] = {}
        if p.calls:
            if p.arr:
                t["arrival"] = _event(p.arr, p.true_arr, now, True, delay, cancelled, False)
            if p.dep:
                t["departure"] = _event(p.dep, p.true_dep, now, True, delay, cancelled, True)
            t["scheduledCallType"] = "ADVERTISED_OPEN"
            t["realtimeCallType"] = None if cancelled else "ADVERTISED_OPEN"
            t["displayAs"] = "CANCELLED" if cancelled else "CALL"
        else:
            t["pass"] = _event(p.pas, p.true_pas, now, False, delay, cancelled, False)
            t["scheduledCallType"] = None
            t["realtimeCallType"] = None
            # both forms seen: "PASS", and null meaning a pass
            t["displayAs"] = "CANCELLED" if cancelled else ("PASS" if _h(p.loc.tiploc) % 2 else None)
        status = self._status(s, i, now)
        if status:
            t["status"] = status
        t["isInterpolated"] = False
        return t

    def _meta(self, s: SimService, i: int, now: datetime, detailed_alloc: bool) -> dict:
        p = s.points[i]
        m: dict[str, Any] = {}
        if p.platform:
            near = p.true_arr or p.true_dep
            if near and now >= near - timedelta(minutes=10):
                m["platform"] = {"planned": p.platform, "actual": p.platform}
            else:
                m["platform"] = {"planned": p.platform, "forecast": p.platform}
        m["numberOfVehicles"] = s.pattern.vehicles
        m["allocationIndex"] = 0
        if detailed_alloc:
            m["allowances"] = {"engineering": None, "pathing": None, "performance": p.allow_after or None}
        return m

    def _schedule_meta(self, s: SimService, board: bool) -> dict:
        m = {
            "uniqueIdentity": f"gb-nr:{s.identity}:{s.run_date.isoformat()}",
            "namespace": "gb-nr",
            "identity": s.identity,
            "departureDate": s.run_date.isoformat(),
            "operator": {"code": s.pattern.op_code, "name": s.pattern.op_name},
            "modeType": "TRAIN",
            "inPassengerService": True,
        }
        if not board:
            m["trainReportingIdentity"] = s.headcode  # absent on real free board rows
        return m

    @staticmethod
    def _pair(p: SimPoint, departing: bool) -> dict:
        t = p.dep if departing else p.arr
        return {
            "location": {"description": p.loc.name, "longCodes": [p.loc.tiploc]},
            "temporalData": {"scheduleInternal": _iso(t), "scheduleAdvertised": _iso(_floor_min(t)) if t else None},
        }

    def _resolve(self, code: str) -> tuple[str, str | None, str | None]:
        code = code.upper()
        for route in ROUTES.values():
            for loc in route:
                if code in (loc.crs, loc.tiploc):
                    return loc.name, loc.crs, loc.tiploc
        if self.stations is not None:
            st = self.stations.by_crs(code)
            if st:
                return st.name, st.crs, None
        return code, code if len(code) == 3 else None, None

    def _location(self, params: dict[str, str], h: dict[str, str]) -> Response:
        code = params.get("code", "")
        if not code:
            return Response(400, h, {"error": "code is required"})
        name, crs, tiploc = self._resolve(code)
        now = self._now()
        tf_raw = params.get("timeFrom")
        tf = datetime.fromisoformat(tf_raw) if tf_raw else now
        tf = tf.replace(tzinfo=LONDON) if tf.tzinfo is None else tf.astimezone(LONDON)
        window = int(params.get("timeWindow", "60"))
        tt = tf + timedelta(minutes=window)
        filter_to = params.get("filterTo", "").upper() or None
        rows = []
        for d in {tf.date() - timedelta(days=1), tf.date(), tt.date()}:
            for s in self.tt.day(d):
                for i, p in enumerate(s.points):
                    if (
                        not p.calls
                        or (crs and p.loc.crs != crs and p.loc.tiploc != tiploc)
                        or (not crs and p.loc.tiploc != tiploc)
                    ):
                        continue
                    when = p.dep or p.arr
                    if not (tf <= when < tt):
                        continue
                    if filter_to and not any(
                        q.calls and filter_to in (q.loc.crs, q.loc.tiploc) for q in s.points[i + 1 :]
                    ):
                        continue
                    rows.append((when, s, i))
        rows.sort(key=lambda r: r[0])
        query = {
            "location": {
                "namespace": "gb-nr",
                "description": name,
                "shortCodes": [crs] if crs else [],
                "longCodes": [f"gb-nr:{tiploc}"] if tiploc else [],
            },
            "timeFrom": tf.isoformat(timespec="seconds"),
            "timeTo": tt.isoformat(timespec="seconds"),
            "detailed": False,
        }
        if not rows:
            return Response(204, h, None)
        services = []
        for _, s, i in rows:
            services.append(
                {
                    "temporalData": self._temporal(s, i, now),
                    "locationMetadata": self._meta(s, i, now, False),
                    "scheduleMetadata": self._schedule_meta(s, board=True),
                    "origin": [self._pair(s.origin, True)],
                    "destination": [self._pair(s.destination, False)],
                }
            )
        return Response(
            200,
            h,
            {"systemStatus": {"realtimeNetworkRail": "OK", "rttCore": "OK"}, "query": query, "services": services},
        )

    def _service(self, params: dict[str, str], h: dict[str, str]) -> Response:
        uid = params.get("uniqueIdentity", "")
        parts = uid.split(":")
        if len(parts) < 2:
            return Response(400, h, {"error": "uniqueIdentity must be identity:date"})
        identity, d = parts[-2], parts[-1]
        try:
            day = date.fromisoformat(d)
        except ValueError:
            return Response(400, h, {"error": "bad date"})
        s = self.tt.find(identity, day)
        if s is None:
            return Response(404, h, None)
        now = self._now()
        locs = []
        for i, p in enumerate(s.points):
            locs.append(
                {
                    "temporalData": self._temporal(s, i, now),
                    "locationMetadata": self._meta(s, i, now, True),
                    "location": {
                        "namespace": "gb-nr",
                        "description": p.loc.name,
                        "shortCodes": [p.loc.crs] if p.loc.crs else [],
                        "longCodes": [p.loc.tiploc],
                    },
                }
            )
        reasons = []
        if (
            s.profile in ("late-recovering", "late-growing", "held")
            and self._delay_before(s, len(s.points), now) >= 180
        ):
            reasons = [
                {
                    "type": "DELAY",
                    "code": "XA",
                    "system": "TRUST",
                    "shortText": "a signalling problem" if s.profile == "held" else "a late-running train ahead",
                    "longText": None,
                }
            ]
        if s.cancelled:
            reasons = [
                {
                    "type": "CANCEL",
                    "code": "M8",
                    "system": "TRUST",
                    "shortText": "a fault on this train",
                    "longText": None,
                }
            ]
        body = {
            "systemStatus": {"realtimeNetworkRail": "OK", "rttCore": "OK"},
            "query": {"uniqueIdentity": f"gb-nr:{s.identity}:{s.run_date.isoformat()}"},
            "service": {
                "scheduleMetadata": self._schedule_meta(s, board=False),
                "locations": locs,
                "allocationData": [{"allocationIndex": 0, "passengerVehicles": s.pattern.vehicles}],
                "origin": [self._pair(s.origin, True)],
                "destination": [self._pair(s.destination, False)],
                "reasons": reasons,
            },
        }
        return Response(200, h, body)
