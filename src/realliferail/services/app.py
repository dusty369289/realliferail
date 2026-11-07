"""Everything the interfaces call. Wires config, client, stations and clock together."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..domain.engine import Timeline, build
from ..domain.models import Board, BoardRow
from ..domain.parse import parse_board, parse_service
from ..sources.budget import Budget
from ..sources.rtt import AuthError, Fetched, RttClient, RttError, TokenInfo
from ..sources.simulator import SimTransport
from ..sources.stations import Station, StationIndex
from ..sources.transport import HttpTransport, Transport

LONDON = ZoneInfo("Europe/London")


def load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = path.read_text("utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def find_token(env: dict[str, str] | None = None, files: list[Path] | None = None) -> str | None:
    env = os.environ if env is None else env
    if env.get("RTT_TOKEN"):
        return env["RTT_TOKEN"].strip()
    for f in files if files is not None else default_env_files():
        tok = load_env_file(f).get("RTT_TOKEN")
        if tok:
            return tok
    return None


def default_env_files() -> list[Path]:
    here = Path.cwd() / ".env"
    project = Path(__file__).resolve().parents[3] / ".env"
    user = Path.home() / ".config" / "realliferail" / ".env"
    seen, out = set(), []
    for p in (here, project, user):
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


@dataclass(frozen=True, slots=True)
class BoardResult:
    board: Board
    rows: tuple[BoardRow, ...]  # filtered to the mode
    station: Station | None
    fetched: Fetched
    mode: str  # dep or arr
    to: Station | None


@dataclass(frozen=True, slots=True)
class ServiceResult:
    timeline: Timeline
    fetched: Fetched
    refresh_after: float  # seconds the page should wait before asking again


class Realliferail:
    def __init__(
        self,
        token: str | None = None,
        transport: Transport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        stations: StationIndex | None = None,
        demo: bool | None = None,
    ):
        self.clock = clock
        self.stations = stations or StationIndex.bundled()
        self.demo = (token is None and transport is None) if demo is None else demo
        if transport is None:
            transport = SimTransport(clock=clock, stations=self.stations) if self.demo else HttpTransport()
        self.budget = Budget(clock=clock)
        self.client = RttClient(transport, token if not self.demo else "demo", self.budget, clock=clock)
        self.token_error: str | None = None

    def now(self) -> datetime:
        return self.clock().astimezone(LONDON)

    def token_info(self) -> TokenInfo | None:
        if self.demo:
            return None
        if self.client.info is None and self.token_error is None:
            try:
                self.client.check_token()
            except RttError as e:
                self.token_error = str(e)
        return self.client.info

    # ---- operations ----
    def search_stations(self, q: str, limit: int = 8) -> list[Station]:
        return self.stations.search(q, limit)

    def board(
        self,
        station: str,
        when: datetime | None = None,
        window: int = 60,
        to: str | None = None,
        mode: str = "dep",
    ) -> BoardResult:
        st = self.stations.resolve(station)
        code = st.crs if st else station.strip().upper()
        if not code:
            raise RttError("Type a station name or code.")
        to_st = self.stations.resolve(to) if to else None
        if to and not to_st:
            raise RttError(f"Couldn't find a station called “{to}”.")
        if not 1 <= window <= 240:
            raise RttError("The time window must be between 1 and 240 minutes.")
        self.token_info()
        when = (when or self.now()).astimezone(LONDON)
        f = self.client.location(code, when, window, to_st.crs if to_st else None)
        b = parse_board(
            f.body, fallback_name=st.name if st else code, time_from=when, time_to=when + timedelta(minutes=window)
        )
        if mode == "arr":
            rows = tuple(r for r in b.rows if not r.arrival.is_empty)
        else:
            rows = tuple(r for r in b.rows if not r.departure.is_empty)
        return BoardResult(board=b, rows=rows, station=st, fetched=f, mode=mode, to=to_st)

    def service(self, unique_id: str, background: bool = False) -> ServiceResult:
        uid = unique_id.strip()
        if ":" not in uid:
            raise RttError("That isn't a train identity (it should look like C05986:2026-09-06).")
        ident, _, day = uid.rpartition(":")
        try:
            date.fromisoformat(day)
        except ValueError as e:
            raise RttError("That train's date isn't valid.") from e
        self.token_info()
        ttl = self.budget.refresh_interval() if background else None
        f = self.client.service(f"{ident}:{day}", interactive=not background, ttl=ttl)
        if not f.body:
            raise RttError("Realtime Trains has no details for that train.")
        svc = parse_service(f.body)
        tl = build(svc, self.now())
        return ServiceResult(
            timeline=tl, fetched=f, refresh_after=max(15.0, min(self.budget.refresh_interval(), 120.0))
        )


def from_environment(demo: bool | None = None) -> Realliferail:
    if demo is None:
        demo = os.environ.get("REALLIFERAIL_DEMO", "").lower() in ("1", "true", "yes")
    token = None if demo else find_token()
    return Realliferail(token=token, demo=demo or token is None)


__all__ = ["AuthError", "BoardResult", "Realliferail", "RttError", "ServiceResult", "from_environment"]
