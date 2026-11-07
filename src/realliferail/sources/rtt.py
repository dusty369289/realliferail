"""RTT client: token handling, caching and the budget, over a Transport (real or simulated)."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .budget import Budget
from .transport import Response, Transport, TransportError


class RttError(Exception):
    """Something to tell the user, in a sentence."""


class AuthError(RttError):
    pass


class BusyError(RttError):
    """Not the user's fault and not permanent: out of allowance, asked to wait, or RTT unreachable. Try again soon."""


@dataclass(frozen=True, slots=True)
class Fetched:
    body: Any  # None for "no services" (204)
    fetched_at: datetime
    stale: bool = False  # served from cache because we couldn't (or shouldn't) refetch
    note: str | None = None  # why it's stale


@dataclass
class TokenInfo:
    entitlements: list[str] = field(default_factory=list)
    api_version: str | None = None
    history_days: int | None = None
    kind: str = "unknown"  # access or refresh

    @property
    def detailed(self) -> bool:
        return "allowDetailed" in self.entitlements


class RttClient:
    def __init__(
        self,
        transport: Transport,
        token: str | None,
        budget: Budget,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        board_ttl: float = 60.0,
        service_ttl: float = 30.0,
        state_file: Path | None = None,
        min_refresh_age: float = 15.0,
        max_cached: int = 500,
    ):
        self._t = transport
        self._token = token
        self._access: str | None = None
        self._access_until: datetime | None = None
        self.budget = budget
        self._clock = clock
        self.board_ttl = board_ttl
        self.service_ttl = service_ttl
        self._cache: dict[tuple, Fetched] = {}
        self._lock = threading.Lock()
        self._key_locks: dict[tuple, threading.Lock] = {}
        self.info: TokenInfo | None = None
        self.state_file = state_file
        self.min_refresh_age = min_refresh_age  # a forced refresh never refetches anything younger than this
        self.max_cached = max_cached  # answers kept; the oldest go first
        self._load_state()

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    @property
    def token_hint(self) -> str | None:
        """The last 5 characters, so a person can tell which token is in use without it being shown."""
        return f"…{self._token[-5:]}" if self._token and len(self._token) > 12 else None

    def set_token(self, token: str | None) -> None:
        with self._lock:
            self._token = token
            self._access = None
            self._access_until = None
            self.info = None
            self._cache.clear()
        self._save_state()

    # ---- the short-life access token survives restarts, so each start doesn't cost 3 calls ----
    def _fingerprint(self) -> str | None:
        return hashlib.sha256(self._token.encode()).hexdigest()[:16] if self._token else None

    def _load_state(self) -> None:
        if not self.state_file or not self._token:
            return
        try:
            d = json.loads(self.state_file.read_text())
        except OSError, ValueError:
            return
        if d.get("for") != self._fingerprint():
            return
        until = _parse_dt(d.get("until"))
        if d.get("kind") == "refresh" and (until is None or until <= self._clock()):
            return
        self.info = TokenInfo(
            entitlements=list(d.get("entitlements") or []),
            api_version=d.get("api_version"),
            history_days=d.get("history_days"),
            kind=d.get("kind", "unknown"),
        )
        if self.info.kind == "refresh":
            self._access, self._access_until = d.get("access"), until

    def _save_state(self) -> None:
        if not self.state_file:
            return
        if not self._token or self.info is None:
            self.state_file.unlink(missing_ok=True)
            return
        d = {
            "for": self._fingerprint(),
            "kind": self.info.kind,
            "entitlements": self.info.entitlements,
            "api_version": self.info.api_version,
            "history_days": self.info.history_days,
        }
        if self.info.kind == "refresh" and self._access:
            d["access"] = self._access
            d["until"] = self._access_until.isoformat() if self._access_until else None
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        tmp.chmod(0o600)
        tmp.replace(self.state_file)

    # ---- token ----
    def _raw(self, path: str, params: dict[str, str], token: str | None) -> Response:
        self.budget.spend()
        try:
            r = self._t.get(path, params, token)
        except TransportError as e:
            raise BusyError(f"Couldn't reach Realtime Trains ({e}).") from e
        self.budget.observe(r.status, r.headers)
        return r

    def _bearer(self) -> str:
        if not self._token:
            raise AuthError("No Realtime Trains token is set.")
        now = self._clock()
        if self._access and (self._access_until is None or now < self._access_until):
            return self._access
        if self.info is None or self.info.kind == "unknown":
            self.check_token()
        if self.info and self.info.kind == "access":
            self._access, self._access_until = self._token, None
            return self._token
        r = self._raw("/api/get_access_token", {}, self._token)
        if r.status != 200 or not isinstance(r.body, dict) or not r.body.get("token"):
            raise AuthError("Realtime Trains didn't accept the token. Check it in api-portal.rtt.io.")
        self._access = r.body["token"]
        self._access_until = _until(r.body.get("validUntil"), now)
        self._save_state()
        return self._access

    def check_token(self) -> TokenInfo:
        """Try the token as an access token, then as a refresh token. Costs one or two calls."""
        if not self._token:
            raise AuthError("No Realtime Trains token is set.")
        r = self._raw("/api/info", {}, self._token)
        if r.status == 200 and isinstance(r.body, dict):
            self.info = _info(r.body, "access")
            self._save_state()
            return self.info
        r2 = self._raw("/api/get_access_token", {}, self._token)
        if r2.status == 200 and isinstance(r2.body, dict) and r2.body.get("token"):
            self._access = r2.body["token"]
            self._access_until = _until(r2.body.get("validUntil"), self._clock())
            r3 = self._raw("/api/info", {}, self._access)
            self.info = _info(r3.body if isinstance(r3.body, dict) else {}, "refresh")
            if not self.info.entitlements:
                self.info.entitlements = list(r2.body.get("entitlements") or [])
            self._save_state()
            return self.info
        raise AuthError(f"Realtime Trains refused the token (HTTP {r.status}). Check it in api-portal.rtt.io.")

    # ---- data ----
    def _get(
        self, key: tuple, path: str, params: dict[str, str], ttl: float, interactive: bool, force: bool = False
    ) -> Fetched:
        with self._lock:
            lock = self._key_locks.setdefault(key, threading.Lock())
        with lock:  # two phones asking for the same train cost one call
            now = self._clock()
            cached = self._cache.get(key)
            age = (now - cached.fetched_at).total_seconds() if cached else None
            if cached and force and age < self.min_refresh_age:
                # pressing refresh again and again costs nothing: it's already this fresh
                return cached
            if cached and not force and age < ttl:
                return cached
            if not self.budget.can_spend(interactive):
                if cached:
                    return Fetched(cached.body, cached.fetched_at, stale=True, note="Saving the hourly allowance")
                st = self.budget.state()
                if st.blocked_until:
                    raise BusyError(f"Realtime Trains asked us to wait until {st.blocked_until:%H:%M:%S}.")
                raise BusyError("The Realtime Trains allowance is used up for now. Try again in a few minutes.")
            try:
                r = self._raw(path, params, self._bearer())
            except RttError:
                if cached:
                    return Fetched(cached.body, cached.fetched_at, stale=True, note="Realtime Trains didn't answer")
                raise
            if r.status == 401:
                self._access = None
                if self.info and self.info.kind != "refresh":
                    self.info = None
                raise AuthError("Realtime Trains refused the token. It may have expired or been revoked.")
            if r.status == 429:
                if cached:
                    return Fetched(
                        cached.body, cached.fetched_at, stale=True, note="Realtime Trains asked us to slow down"
                    )
                raise BusyError("Realtime Trains asked us to slow down. Try again shortly.")
            if r.status == 204:
                f = Fetched(None, now)
            elif r.status == 200:
                f = Fetched(r.body, now)
            elif r.status == 404:
                raise RttError("Realtime Trains doesn't know that train.")
            elif r.status == 400:
                msg = r.body.get("error") if isinstance(r.body, dict) else None
                raise RttError(f"Realtime Trains couldn't answer that: {msg or 'bad request'}.")
            else:
                if cached:
                    return Fetched(cached.body, cached.fetched_at, stale=True, note=f"Realtime Trains error {r.status}")
                raise BusyError(f"Realtime Trains had a problem (HTTP {r.status}).")
            self._cache[key] = f
            if len(self._cache) > self.max_cached:
                drop = len(self._cache) - self.max_cached + max(self.max_cached // 5, 1)
                oldest = sorted(self._cache.items(), key=lambda kv: kv[1].fetched_at)[:drop]
                for k, _ in oldest:
                    self._cache.pop(k, None)
                with self._lock:  # and the per-answer locks, or they'd pile up for every board ever asked for
                    for k in [k for k, lk in self._key_locks.items() if k not in self._cache and not lk.locked()]:
                        del self._key_locks[k]
            return f

    def location(
        self, code: str, time_from: datetime, window_min: int = 60, filter_to: str | None = None, force: bool = False
    ) -> Fetched:
        params = {
            "code": code.upper(),
            "timeFrom": time_from.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeWindow": str(window_min),
        }
        if filter_to:
            params["filterTo"] = filter_to.upper()
        if self.info and self.info.detailed:
            params["detailed"] = "true"
        # round the key to the minute so "now" from several phones shares one answer
        key = ("loc", params["code"], time_from.strftime("%Y-%m-%dT%H:%M"), window_min, params.get("filterTo"))
        return self._get(key, "/gb-nr/location", params, self.board_ttl, interactive=True, force=force)

    def service(
        self, unique_id: str, interactive: bool = True, ttl: float | None = None, force: bool = False
    ) -> Fetched:
        params = {"uniqueIdentity": unique_id}
        if self.info and self.info.detailed:
            params["detailed"] = "true"
        ttl = self.service_ttl if ttl is None else ttl
        return self._get(("svc", unique_id), "/gb-nr/service", params, ttl, interactive=interactive, force=force)


def _info(body: dict, kind: str) -> TokenInfo:
    cred = body.get("credentials") or {}
    return TokenInfo(
        entitlements=list(cred.get("entitlements") or []),
        api_version=body.get("api_version"),
        history_days=cred.get("historyRestrictToDays") if cred.get("historyRestriction") else None,
        kind=kind,
    )


def _parse_dt(v) -> datetime | None:
    try:
        return datetime.fromisoformat(v)
    except TypeError, ValueError:
        return None


def _until(valid_until, now: datetime) -> datetime:
    """When to stop using a short-life access token: a minute before it expires, or in 10 minutes if we can't tell."""
    try:
        return datetime.fromisoformat(valid_until.replace("Z", "+00:00")) - timedelta(seconds=60)
    except AttributeError, ValueError:
        return now + timedelta(minutes=10)
