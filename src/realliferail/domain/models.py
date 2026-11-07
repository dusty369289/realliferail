"""Frozen models for what the app shows. Built by `domain.parse` from RTT JSON. No I/O here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class Kind(StrEnum):
    CALL = "call"  # stops here (any call type, including origin and destination)
    PASS = "pass"  # timing point the train runs through


class Display(StrEnum):
    CALL = "CALL"
    PASS = "PASS"
    CANCELLED = "CANCELLED"
    DIVERTED = "DIVERTED"
    STARTS = "STARTS"
    TERMINATES = "TERMINATES"


class TimeSource(StrEnum):
    ACTUAL = "actual"  # reported by RTT
    FORECAST = "forecast"  # RTT's forecast
    RTT_ESTIMATE = "rtt-estimate"  # RTT's own estimate for a point with no report
    OUR_ESTIMATE = "est"  # ours (domain.engine)
    BOOKED = "booked"  # nothing better than the timetable


@dataclass(frozen=True, slots=True)
class Times:
    """One event (arrival, departure or pass) at a point."""

    advertised: datetime | None = None  # public timetable (GBTT)
    internal: datetime | None = None  # working timetable (WTT), may have half minutes
    forecast: datetime | None = None
    estimate: datetime | None = None  # RTT's no-report estimate
    actual: datetime | None = None
    no_report: bool = False
    cancelled: bool = False

    @property
    def booked(self) -> datetime | None:
        """The time to show as booked: public if there is one, else working."""
        return self.advertised or self.internal

    @property
    def planned(self) -> datetime | None:
        """The time to plan with: the working timetable is finer, so prefer it."""
        return self.internal or self.advertised

    @property
    def is_empty(self) -> bool:
        return self.advertised is None and self.internal is None and self.actual is None and self.forecast is None


@dataclass(frozen=True, slots=True)
class Allowances:
    engineering: int = 0  # seconds
    pathing: int = 0
    performance: int = 0

    @property
    def total(self) -> int:
        return self.engineering + self.pathing + self.performance


@dataclass(frozen=True, slots=True)
class Reason:
    kind: str  # DELAY or CANCEL
    text: str


@dataclass(frozen=True, slots=True)
class Point:
    """One location on a service's run."""

    name: str
    crs: str | None
    tiploc: str | None
    kind: Kind
    display: Display
    arrival: Times = field(default_factory=Times)
    departure: Times = field(default_factory=Times)
    passing: Times = field(default_factory=Times)
    platform: str | None = None
    platform_confirmed: bool = False
    platform_changed: bool = False
    status: str | None = None  # APPROACHING, AT_PLATFORM, ...
    public: bool = True  # an advertised call
    request_stop: bool = False
    interpolated: bool = False
    allowances: Allowances = field(default_factory=Allowances)
    line: str | None = None
    path: str | None = None

    @property
    def cancelled(self) -> bool:
        return self.display in (Display.CANCELLED, Display.DIVERTED)

    @property
    def first_event(self) -> Times:
        if self.kind is Kind.PASS:
            return self.passing
        return self.arrival if not self.arrival.is_empty else self.departure

    @property
    def last_event(self) -> Times:
        if self.kind is Kind.PASS:
            return self.passing
        return self.departure if not self.departure.is_empty else self.arrival


@dataclass(frozen=True, slots=True)
class Endpoint:
    name: str
    tiploc: str | None
    time: datetime | None


@dataclass(frozen=True, slots=True)
class Service:
    unique_id: str  # "C05986:2026-09-06" (namespace dropped)
    identity: str
    run_date: date
    headcode: str | None
    operator_code: str
    operator_name: str
    mode: str
    passenger: bool
    origins: tuple[Endpoint, ...]
    destinations: tuple[Endpoint, ...]
    points: tuple[Point, ...]
    reasons: tuple[Reason, ...] = ()
    vehicles: int | None = None
    units: tuple[str, ...] = ()
    leading_class: str | None = None
    branding: str | None = None
    stp: str | None = None

    @property
    def origin_name(self) -> str:
        return " & ".join(o.name for o in self.origins) or "Unknown"

    @property
    def destination_name(self) -> str:
        return " & ".join(d.name for d in self.destinations) or "Unknown"


@dataclass(frozen=True, slots=True)
class BoardRow:
    """One service as seen from the board's station."""

    unique_id: str
    identity: str
    run_date: date
    headcode: str | None
    operator_code: str
    operator_name: str
    mode: str
    origin: str
    destination: str
    arrival: Times
    departure: Times
    platform: str | None
    platform_confirmed: bool
    platform_changed: bool
    display: Display
    status: str | None
    vehicles: int | None
    passenger: bool = True
    call_type: str | None = None  # ADVERTISED_OPEN / _PICK_UP / _SET_DOWN / OPERATIONAL_ONLY
    branding: str | None = None  # e.g. "Arterio", "Voyager"
    line: str | None = None  # running line here, e.g. "UML"
    stp: str | None = None  # WTT, VAR, STP (detailed mode)
    reasons: tuple[Reason, ...] = ()

    @property
    def cancelled(self) -> bool:
        return self.display in (Display.CANCELLED, Display.DIVERTED) or (
            self.departure.cancelled if not self.departure.is_empty else self.arrival.cancelled
        )

    @property
    def for_passengers(self) -> bool:
        """Something a passenger can board or leave here: not empty stock, not a staff-only stop."""
        return self.passenger and self.call_type != "OPERATIONAL_ONLY"

    @property
    def is_bus(self) -> bool:
        return "BUS" in self.mode

    @property
    def terminates_here(self) -> bool:
        return self.departure.is_empty and not self.arrival.is_empty

    @property
    def starts_here(self) -> bool:
        return self.arrival.is_empty and not self.departure.is_empty


@dataclass(frozen=True, slots=True)
class SystemStatus:
    network_rail: str = "OK"
    core: str = "OK"

    @property
    def ok(self) -> bool:
        return self.network_rail == "OK" and self.core == "OK"

    @property
    def message(self) -> str | None:
        if self.core == "SCHEDULE_ONLY" or self.network_rail == "REALTIME_DATA_NONE":
            return "Realtime Trains has no live data right now, so times are the timetable only."
        if not self.ok:
            return "Realtime Trains says live data is limited right now. Some times may be missing or late."
        return None


@dataclass(frozen=True, slots=True)
class Board:
    station_name: str
    station_crs: str | None
    time_from: datetime
    time_to: datetime
    rows: tuple[BoardRow, ...]
    status: SystemStatus = field(default_factory=SystemStatus)
