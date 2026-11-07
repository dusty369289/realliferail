"""Where the train is, and when it'll reach each point. Pure functions of (service, now).

Display time for each event, in order of trust: RTT actual > RTT forecast > RTT's no-report estimate > ours > booked.

Our estimate carries the latest known delay forward along the working timetable. A late train can win back the booked
allowances in each section, and dwell time beyond `min_dwell`, but never runs ahead of the working timetable and never
leaves a public stop before its booked time. `recovery_share` says how much of an allowance a late train really gets
back. It's a guess until backtested (docs/plan.md, "Later").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .models import Kind, Point, Service, Times, TimeSource


@dataclass(frozen=True, slots=True)
class EngineConfig:
    recovery_share: float = 0.75
    min_dwell: timedelta = timedelta(seconds=30)
    hold_fraction: float = 0.95  # never place the train past this share of an unreported section
    overdue_after: timedelta = timedelta(minutes=2)


class State(StrEnum):
    NOT_STARTED = "not-started"
    AT_ORIGIN = "at-origin"
    AT_STATION = "at-station"
    RUNNING = "running"
    OVERDUE = "overdue"
    ARRIVED = "arrived"
    CANCELLED = "cancelled"
    NO_DATA = "no-data"


@dataclass(frozen=True, slots=True)
class Shown:
    time: datetime | None
    source: TimeSource
    booked: datetime | None
    delay_min: int | None  # against the booked time shown, whole minutes, + is late

    @property
    def changed(self) -> bool:
        return (
            self.time is not None and self.booked is not None and abs((self.time - self.booked).total_seconds()) >= 60
        )


@dataclass(frozen=True, slots=True)
class PointView:
    index: int
    point: Point
    arrival: Shown | None
    departure: Shown | None
    passing: Shown | None
    reported: bool  # the train has been reported at or beyond here
    ours_arrival: datetime | None  # our own estimates, also shown where RTT forecast differs
    ours_departure: datetime | None


@dataclass(frozen=True, slots=True)
class Position:
    state: State
    from_index: int | None  # last point reported
    to_index: int | None  # next point
    since: datetime | None  # when it left/passed from_index
    expected: datetime | None  # when we expect it at to_index
    fraction: float  # 0..1 through the section at `now`
    delay_min: int | None  # current lateness against the working timetable
    headline: str


@dataclass(frozen=True, slots=True)
class Timeline:
    service: Service
    points: tuple[PointView, ...]
    position: Position
    now: datetime


def _round_min(seconds: float) -> int:
    # Railway convention: lateness is whole minutes, rounded toward zero for small early/late noise
    return int(seconds // 60) if seconds >= 0 else -int((-seconds) // 60)


def _shown(t: Times, ours: datetime | None) -> Shown | None:
    if t.is_empty and ours is None:
        return None
    booked = t.booked
    if t.actual:
        time, src = t.actual, TimeSource.ACTUAL
    elif t.forecast:
        time, src = t.forecast, TimeSource.FORECAST
    elif t.estimate:
        time, src = t.estimate, TimeSource.RTT_ESTIMATE
    elif ours:
        time, src = ours, TimeSource.OUR_ESTIMATE
    else:
        time, src = booked, TimeSource.BOOKED
    delay = _round_min((time - booked).total_seconds()) if (time and booked) else None
    return Shown(time=time, source=src, booked=booked, delay_min=delay)


def _actual_of(p: Point) -> tuple[datetime | None, Times | None]:
    """The latest actual at this point and which event it belongs to."""
    for t in (p.departure, p.passing, p.arrival) if p.kind is Kind.CALL else (p.passing,):
        if t.actual:
            return t.actual, t
    return None, None


def build(service: Service, now: datetime, cfg: EngineConfig | None = None) -> Timeline:
    cfg = cfg or EngineConfig()
    pts = service.points
    usable = [i for i, p in enumerate(pts) if not p.cancelled]

    last = None  # index of the last point with any actual
    for i in usable:
        if _actual_of(pts[i])[0] is not None:
            last = i

    # --- our estimates, propagated forward from the last report (or from the start if none) ---
    ours_arr: dict[int, datetime] = {}
    ours_dep: dict[int, datetime] = {}
    cursor: datetime | None = None  # time the train leaves the previous usable point
    prev: int | None = None
    start = usable.index(last) if last is not None else 0
    for k in range(start, len(usable)):
        i = usable[k]
        p = pts[i]
        if k == start:
            if last is None:
                # Not yet reported: it leaves on time, or now if already overdue to start
                first = p.last_event.planned
                cursor = max(first, now) if first else None
            else:
                act, ev = _actual_of(p)
                if p.kind is Kind.CALL and ev is p.arrival and not p.departure.is_empty:
                    # arrived, not yet departed: departs after a minimum dwell, not before booked
                    dep = max(act + cfg.min_dwell, p.departure.planned or act)
                    dep = max(dep, now) if not p.departure.actual else dep
                    ours_dep[i] = dep
                    cursor = dep
                else:
                    cursor = act
            prev = i
            continue
        if cursor is None or prev is None:
            break
        a_prev = pts[prev].last_event.planned
        a_here = p.first_event.planned
        if a_prev is None or a_here is None:
            prev = i
            continue
        booked_run = (a_here - a_prev).total_seconds()
        slack = pts[prev].allowances.total * cfg.recovery_share
        min_run = max(booked_run - slack, booked_run * 0.5, 0)
        arr = max(cursor + timedelta(seconds=min_run), a_here)
        ours_arr[i] = arr
        # RTT knows more than we do, so where it has forecast a point, carry on from its time instead of ours
        first = p.first_event
        anchor = first.forecast or first.estimate
        base = anchor or arr
        if p.kind is Kind.PASS:
            cursor = base
        else:
            dep_planned = p.departure.planned
            if dep_planned is not None:
                dwell = min(cfg.min_dwell, max(dep_planned - (p.arrival.planned or dep_planned), timedelta(0)))
                dep = max(base + dwell, dep_planned)
                ours_dep[i] = dep
                cursor = p.departure.forecast or p.departure.estimate or dep
            else:
                cursor = base
        prev = i

    views = []
    for i, p in enumerate(pts):
        reported = last is not None and i <= last
        if p.kind is Kind.PASS:
            views.append(
                PointView(i, p, None, None, _shown(p.passing, ours_arr.get(i)), reported, ours_arr.get(i), None)
            )
        else:
            views.append(
                PointView(
                    i,
                    p,
                    _shown(p.arrival, ours_arr.get(i)) if not p.arrival.is_empty else None,
                    _shown(p.departure, ours_dep.get(i)) if not p.departure.is_empty else None,
                    None,
                    reported,
                    ours_arr.get(i),
                    ours_dep.get(i),
                )
            )

    position = _position(service, tuple(views), usable, last, now, cfg)
    return Timeline(service=service, points=tuple(views), position=position, now=now)


def _expected_at(v: PointView) -> datetime | None:
    s = v.passing if v.point.kind is Kind.PASS else v.arrival or v.departure
    return s.time if s else None


def _name(p: Point) -> str:
    return p.name


def _late_text(d: int | None) -> str:
    if d is None:
        return ""
    if d == 0:
        return "on time"
    return f"{d} min late" if d > 0 else f"{-d} min early"


def _position(
    service: Service,
    views: tuple[PointView, ...],
    usable: list[int],
    last: int | None,
    now: datetime,
    cfg: EngineConfig,
) -> Position:
    pts = service.points
    if not pts:
        return Position(State.NO_DATA, None, None, None, None, 0.0, None, "No route data for this train.")
    if not usable:
        return Position(State.CANCELLED, None, None, None, None, 0.0, None, "This train is cancelled.")

    if last is None:
        first = usable[0]
        p = pts[first]
        dep = p.departure.planned or p.last_event.planned
        if dep and now < dep:
            return Position(
                State.NOT_STARTED,
                None,
                first,
                None,
                dep,
                0.0,
                None,
                f"Not started yet. Due to leave {p.name} at {dep:%H:%M}.",
            )
        return Position(
            State.AT_ORIGIN,
            first,
            usable[1] if len(usable) > 1 else None,
            None,
            None,
            0.0,
            None,
            f"No reports yet. It was due to leave {p.name} at {dep:%H:%M}." if dep else "No reports yet.",
        )

    lp = pts[last]
    act, ev = _actual_of(lp)
    planned = ev.planned if ev else None
    delay = _round_min((act - planned).total_seconds()) if (act and planned) else None
    late = _late_text(delay)

    nxt_k = usable.index(last) + 1
    if nxt_k >= len(usable):
        return Position(State.ARRIVED, last, None, act, None, 1.0, delay, f"Arrived at {lp.name} {act:%H:%M}, {late}.")
    nxt = usable[nxt_k]

    if lp.kind is Kind.CALL and ev is lp.arrival and not lp.departure.is_empty:
        due = views[last].departure.time if views[last].departure else None
        tail = f", due to leave {due:%H:%M}" if due else ""
        return Position(
            State.AT_STATION,
            last,
            nxt,
            act,
            _expected_at(views[nxt]),
            0.0,
            delay,
            f"At {lp.name} since {act:%H:%M}{tail} ({late}).",
        )

    expected = _expected_at(views[nxt]) or views[nxt].ours_arrival
    np_ = pts[nxt]
    if expected is None or expected <= act:
        frac = cfg.hold_fraction
    else:
        frac = min(max((now - act) / (expected - act), 0.0), cfg.hold_fraction)
    verb = "Passed" if lp.kind is Kind.PASS else "Left"
    if expected is not None and now > expected + cfg.overdue_after:
        over = _round_min((now - expected).total_seconds())
        return Position(
            State.OVERDUE,
            last,
            nxt,
            act,
            expected,
            cfg.hold_fraction,
            delay,
            f"{verb} {lp.name} {act:%H:%M}. No report at {np_.name} yet, {over} min after expected. "
            "It may be held at a signal, or the report is late.",
        )
    exp_txt = f", expected about {expected:%H:%M}" if expected else ""
    return Position(
        State.RUNNING,
        last,
        nxt,
        act,
        expected,
        frac,
        delay,
        f"{verb} {lp.name} {act:%H:%M} ({late}). Next: {np_.name}{exp_txt}.",
    )


@dataclass(frozen=True, slots=True)
class StopSummary:
    name: str
    index: int
    shown: Shown | None
    platform: str | None
    platform_confirmed: bool
    status: str  # ahead, here, gone, cancelled
    minutes: int | None  # from now until the train is due there (ahead only)
    calls_between: int  # stops between the train and this one


def stop_summary(tl: Timeline, code: str, boarding: bool = True) -> StopSummary | None:
    """How things stand at one station on this train: where you get on (or off)."""
    code = code.strip().upper()
    if not code:
        return None
    idx = next(
        (v.index for v in tl.points if v.point.kind is Kind.CALL and code in (v.point.crs, v.point.tiploc)), None
    )
    if idx is None:
        return None
    v = tl.points[idx]
    p = v.point
    shown = (v.departure or v.arrival) if boarding else (v.arrival or v.departure)
    pos = tl.position
    if p.cancelled:
        status = "cancelled"
    elif pos.state is State.AT_STATION and pos.from_index == idx:
        status = "here"
    elif v.reported:
        status = "gone"
    else:
        status = "ahead"
    minutes = None
    between = 0
    if status == "ahead":
        if shown and shown.time:
            minutes = max(int((shown.time - tl.now).total_seconds() // 60), 0)
        start = pos.from_index if pos.from_index is not None else -1
        between = sum(1 for w in tl.points[start + 1 : idx] if w.point.kind is Kind.CALL and not w.point.cancelled)
    return StopSummary(p.name, idx, shown, p.platform, p.platform_confirmed, status, minutes, between)
