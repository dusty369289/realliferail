"""Everything the interfaces call. Wires config, client, stations and clock together."""

from __future__ import annotations

import json
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
from ..sources.rtt import AuthError, BusyError, Fetched, RttClient, RttError, TokenInfo
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
    hidden: int = 0  # empty stock and staff-only calls left out
    show_all: bool = False


@dataclass(frozen=True, slots=True)
class ServiceResult:
    timeline: Timeline
    fetched: Fetched
    refresh_after: float  # seconds the page should wait before asking again


def default_home() -> Path:
    """Where settings and the cached access token live. Outside the project, so they're never committed."""
    return Path(os.environ.get("REALLIFERAIL_HOME") or Path.home() / ".config" / "realliferail")


@dataclass(frozen=True, slots=True)
class Tier:
    """What this token can do, worked out from its entitlements and the limits RTT reports."""

    name: str  # Demo, Free, Hobbyist, Team or above
    detailed: bool
    allocations: bool
    per_minute: int
    per_hour: int

    @property
    def precision(self) -> str:
        return "to the quarter minute" if self.detailed else "to the minute"


TIERS = [
    # name, what it adds, cost. Shown on the settings page. The app decides from entitlements, not from this table.
    ("Free", "Live times to the minute, boards and trains, 10 calls a minute and 100 an hour.", "£0"),
    (
        "Hobbyist",
        "Detailed mode: reports to the quarter minute, headcodes, running lines, unit numbers and class, empty stock.",
        "£4 a month",
    ),
    ("Team", "As Hobbyist, with 40 calls a minute and 1200 an hour, so trains update more often.", "£29 a month"),
]


class Realliferail:
    def __init__(
        self,
        token: str | None = None,
        transport: Transport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        stations: StationIndex | None = None,
        demo: bool | None = None,
        home: Path | None = None,
    ):
        self.clock = clock
        self.stations = stations or StationIndex.bundled()
        self.home = home
        self.demo = (token is None and transport is None) if demo is None else demo
        self._sim = SimTransport(clock=clock, stations=self.stations)
        self._real = transport if (transport is not None and not isinstance(transport, SimTransport)) else None
        if transport is None:
            transport = self._sim if self.demo else self._real_transport()
        self.budget = Budget(clock=clock)
        state = home / "access.json" if home else None
        self.client = RttClient(
            transport, token if not self.demo else "demo", self.budget, clock=clock, state_file=state
        )
        self.token_error: str | None = None

    def _real_transport(self) -> Transport:
        if self._real is None:
            self._real = HttpTransport()
        return self._real

    # ---- settings ----
    def tier(self) -> Tier:
        lim = self.budget.limits
        if self.demo:
            return Tier("Demo", False, False, lim["minute"], lim["hour"])
        info = self.token_info()
        ents = set(info.entitlements) if info else set()
        detailed = "allowDetailed" in ents
        allocations = bool(ents & {"allowAllocations", "allowAllocationsPassenger"})
        if ents & {"allowFullAllocationListing", "allowFullAllocationListingPassenger"} or lim["hour"] > 100:
            name = "Team or above"
        elif detailed:
            name = "Hobbyist"
        else:
            name = "Free"
        return Tier(name, detailed, allocations, lim["minute"], lim["hour"])

    def set_token(self, token: str) -> TokenInfo:
        """Check a new token with RTT (1 to 3 calls), and only then use it and save it."""
        token = token.strip().strip('"').strip("'")
        if token.startswith("RTT_TOKEN="):
            token = token.split("=", 1)[1]
        if len(token) < 20 or any(c.isspace() for c in token):
            raise AuthError("That doesn't look like a Realtime Trains token. Copy it again from api-portal.rtt.io.")
        probe = RttClient(self._real_transport(), token, self.budget, clock=self.clock)
        info = probe.check_token()
        self.client._t = self._real_transport()
        self.client.set_token(token)
        self.client.info = info
        self.client._access, self.client._access_until = probe._access, probe._access_until
        self.client._save_state()
        self.demo = False
        self.token_error = None
        self._save_settings({"rtt_token": token})
        return info

    def remove_token(self) -> None:
        self.client._t = self._sim
        self.client.set_token("demo")
        self.demo = True
        self.token_error = None
        self._save_settings({"rtt_token": None})

    def _save_settings(self, changes: dict) -> None:
        if not self.home:
            return
        path = self.home / "settings.json"
        data = load_settings(self.home)
        data.update(changes)
        data = {k: v for k, v in data.items() if v is not None}
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.chmod(0o600)
        tmp.replace(path)

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
        show_all: bool = False,
        force: bool = False,
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
        f = self.client.location(code, when, window, to_st.crs if to_st else None, force=force)
        b = parse_board(
            f.body, fallback_name=st.name if st else code, time_from=when, time_to=when + timedelta(minutes=window)
        )
        if mode == "arr":
            rows = [r for r in b.rows if not r.arrival.is_empty and r.call_type != "ADVERTISED_PICK_UP"]
        else:
            rows = [r for r in b.rows if not r.departure.is_empty and r.call_type != "ADVERTISED_SET_DOWN"]
        hidden = 0
        if not show_all:
            before = len(rows)
            rows = [r for r in rows if r.for_passengers]
            hidden = before - len(rows)
        return BoardResult(
            board=b, rows=tuple(rows), station=st, fetched=f, mode=mode, to=to_st, hidden=hidden, show_all=show_all
        )

    def service(self, unique_id: str, background: bool = False, force: bool = False) -> ServiceResult:
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
        f = self.client.service(f"{ident}:{day}", interactive=not background or force, ttl=ttl, force=force)
        if not f.body:
            raise RttError("Realtime Trains has no details for that train.")
        svc = parse_service(f.body)
        tl = build(svc, self.now())
        return ServiceResult(
            timeline=tl, fetched=f, refresh_after=max(15.0, min(self.budget.refresh_interval(), 120.0))
        )


def load_settings(home: Path) -> dict:
    try:
        d = json.loads((home / "settings.json").read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except OSError, ValueError:
        return {}


def from_environment(demo: bool | None = None, home: Path | None = None) -> Realliferail:
    """Token from the settings page first, then RTT_TOKEN in the environment or a .env file."""
    home = home or default_home()
    if demo is None:
        demo = os.environ.get("REALLIFERAIL_DEMO", "").lower() in ("1", "true", "yes")
    token = None if demo else (load_settings(home).get("rtt_token") or find_token())
    return Realliferail(token=token, demo=demo or token is None, home=home)


__all__ = [
    "TIERS",
    "AuthError",
    "BoardResult",
    "BusyError",
    "Realliferail",
    "RttError",
    "ServiceResult",
    "Tier",
    "from_environment",
]
