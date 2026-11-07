"""One allowance for every real RTT call. Obeys RTT's headers, and is careful before it has seen any.

The free tier allows 10 a minute, 100 an hour and 1000 a day (docs/rtt-api.md). We keep our own sliding count of calls
too, because a header only tells us what was left at the last answer. Interactive requests (a board someone just asked
for) can use the reserve. Background refreshes (a service page re-polling) can't, so a person searching never finds
the allowance gone.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

DIMENSIONS = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}
FREE_LIMITS = {"minute": 10, "hour": 100, "day": 1000, "week": 7000}


@dataclass(frozen=True, slots=True)
class BudgetState:
    limits: dict[str, int]
    remaining: dict[str, int]
    blocked_until: datetime | None
    calls_made: int


class Budget:
    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC), reserve: int = 10):
        self._clock = clock
        self._lock = threading.Lock()
        self._calls: deque[datetime] = deque()
        self.limits = dict(FREE_LIMITS)
        self._header_remaining: dict[str, tuple[int, datetime]] = {}
        self.blocked_until: datetime | None = None
        self.reserve = reserve
        self.total = 0

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=DIMENSIONS["week"])
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()

    def _used(self, now: datetime, seconds: int) -> int:
        cutoff = now - timedelta(seconds=seconds)
        return sum(1 for t in self._calls if t >= cutoff)

    def remaining(self, dim: str, now: datetime | None = None) -> int:
        now = now or self._clock()
        ours = self.limits[dim] - self._used(now, DIMENSIONS[dim])
        h = self._header_remaining.get(dim)
        if h is not None:
            value, seen = h
            since = sum(1 for t in self._calls if t > seen)
            # a header is only trusted within its own window
            if now - seen < timedelta(seconds=DIMENSIONS[dim]):
                ours = min(ours, value - since)
        return max(ours, 0)

    def can_spend(self, interactive: bool) -> bool:
        with self._lock:
            now = self._clock()
            if self.blocked_until and now < self.blocked_until:
                return False
            if self.remaining("minute", now) < 1:
                return False
            hour, day = self.remaining("hour", now), self.remaining("day", now)
            need = 1 if interactive else 1 + self.reserve
            return hour >= need and day >= need and self.remaining("week", now) >= 1

    def spend(self) -> None:
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._calls.append(now)
            self.total += 1

    def observe(self, status: int, headers: dict[str, str]) -> None:
        with self._lock:
            now = self._clock()
            for dim in DIMENSIONS:
                cap = dim.capitalize()
                lim = headers.get(f"x-ratelimit-limit-{dim}") or headers.get(f"x-ratelimit-limit-{cap}".lower())
                rem = headers.get(f"x-ratelimit-remaining-{dim}")
                if lim and lim.isdigit():
                    self.limits[dim] = int(lim)
                if rem and rem.lstrip("-").isdigit():
                    self._header_remaining[dim] = (int(rem), now)
            if status == 429:
                ra = headers.get("retry-after", "60")
                secs = int(ra) if ra.isdigit() else 60
                self.blocked_until = now + timedelta(seconds=max(secs, 1))

    def refresh_interval(self, floor: float = 30.0) -> float:
        """Seconds between background re-fetches of one service, so the hour isn't used up early."""
        now = self._clock()
        left = self.remaining("hour", now) - self.reserve
        if left <= 0:
            return 600.0
        # assume one followed train; spread what's left of the hour across the next hour
        return max(floor, 3600.0 / left)

    def state(self) -> BudgetState:
        now = self._clock()
        return BudgetState(
            limits=dict(self.limits),
            remaining={d: self.remaining(d, now) for d in DIMENSIONS},
            blocked_until=self.blocked_until if self.blocked_until and self.blocked_until > now else None,
            calls_made=self.total,
        )
