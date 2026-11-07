"""Hosted mode: every visitor brings their own Realtime Trains key, and the server keeps none.

The key lives in the visitor's browser as an HttpOnly cookie, encrypted (AES-256-GCM) with a server secret. Page
scripts can't read it, and a copied cookie is useless without the secret. On each request the server decrypts it, and
uses a per-key client held only in memory: that key's short-life access token, its own allowance and its own answers.
Nothing is written to disk. Restarting the server only costs each person one token exchange. Visitors with no key get
the simulator.

Rotating the secret (REALLIFERAIL_SECRET) logs everyone out, and they paste their key again.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..sources.budget import Budget
from ..sources.rtt import AuthError, BusyError, TokenInfo
from ..sources.stations import StationIndex
from ..sources.transport import HttpTransport, Transport
from .app import Realliferail, clean_token

COOKIE = "rlr_key"
AAD = b"realliferail key v1"
MAX_AGE = 400 * 24 * 3600  # the longest browsers keep a cookie


def load_secret(raw: str | None) -> bytes:
    """REALLIFERAIL_SECRET: 32 random bytes as 64 hex characters or base64. Refuse anything weaker."""
    if not raw:
        raise ValueError(
            "REALLIFERAIL_SECRET is not set. Make one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    raw = raw.strip()
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except ValueError as e:
            raise ValueError("REALLIFERAIL_SECRET must be hex or base64.") from e
    if len(key) != 32:
        raise ValueError("REALLIFERAIL_SECRET must be exactly 32 bytes (64 hex characters).")
    return key


class KeyBox:
    """Seals a token into an opaque cookie value and opens it again. Tampered or foreign values open to None."""

    def __init__(self, secret: bytes):
        self._aes = AESGCM(secret)

    def seal(self, token: str) -> str:
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, token.encode(), AAD)
        return base64.urlsafe_b64encode(nonce + ct).decode().rstrip("=")

    def open(self, blob: str | None) -> str | None:
        if not blob or len(blob) > 4096:
            return None
        try:
            raw = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))
            if len(raw) < 12 + 16:
                return None
            return self._aes.decrypt(raw[:12], raw[12:], AAD).decode()
        except InvalidTag, ValueError, UnicodeDecodeError:
            return None


class Hosted:
    def __init__(
        self,
        secret: bytes,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        transport: Transport | None = None,
        stations: StationIndex | None = None,
        max_keys: int = 200,
        idle_seconds: float = 12 * 3600,
        monotonic: Callable[[], float] = time.monotonic,
        cached_per_key: int = 30,
        checks_per_ip: int = 5,
        checks_total: int = 30,
        check_window: float = 600.0,
    ):
        self.box = KeyBox(secret)
        self.clock = clock
        self.stations = stations or StationIndex.bundled()
        self._transport = transport
        # the demo is the simulator: free to run, so no allowance that one busy visitor could use up for everyone
        self.demo = Realliferail(clock=clock, stations=self.stations, demo=True, budget=Budget.unlimited(clock))
        self._cores: OrderedDict[str, tuple[Realliferail, float]] = OrderedDict()
        self._lock = threading.Lock()
        self.max_keys = max_keys
        self.idle_seconds = idle_seconds
        self._mono = monotonic
        # Memory bound: max_keys x cached_per_key answers (a busy board is about 90 kB) stays well under 512 MB.
        self.cached_per_key = cached_per_key
        # Checking a key calls RTT from this server. Throttled, so nobody can make it hammer RTT with junk keys
        # (RTT might then rate-limit the server's IP for everyone).
        self.checks_per_ip = checks_per_ip
        self.checks_total = checks_total
        self.check_window = check_window
        self._checks: list[tuple[float, str]] = []

    def _real(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport()
        return self._transport

    @staticmethod
    def _id(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def for_key(self, token: str | None) -> Realliferail:
        """The visitor's own client, from their decrypted key. Kept in memory, dropped when idle."""
        if not token:
            return self.demo
        kid = self._id(token)
        now = self._mono()
        with self._lock:
            for k in [k for k, (_, seen) in self._cores.items() if now - seen > self.idle_seconds]:
                del self._cores[k]
            if kid in self._cores:
                core = self._cores[kid][0]
                self._cores.move_to_end(kid)
            else:
                core = Realliferail(
                    token=token,
                    transport=self._real(),
                    clock=self.clock,
                    stations=self.stations,
                    demo=False,
                    max_cached=self.cached_per_key,
                )
                while len(self._cores) >= self.max_keys:
                    self._cores.popitem(last=False)
            self._cores[kid] = (core, now)
            return core

    def for_cookie(self, blob: str | None) -> Realliferail:
        return self.for_key(self.box.open(blob))

    def allow_check(self, ip: str) -> bool:
        """Room for one more key check from this address (and overall) in the current window?"""
        now = self._mono()
        with self._lock:
            self._checks = [(t, a) for t, a in self._checks if now - t < self.check_window]
            mine = sum(1 for _, a in self._checks if a == ip)
            if mine >= self.checks_per_ip or len(self._checks) >= self.checks_total:
                return False
            self._checks.append((now, ip))
            return True

    def check(self, token: str, ip: str = "?") -> tuple[str, TokenInfo]:
        """Ask RTT whether a key works (1 to 3 calls). Returns the cleaned key and what it's allowed."""
        token = clean_token(token)  # junk is refused here, before any call and without using up a check
        if not self.allow_check(ip):
            raise BusyError("Too many key checks just now. Wait a few minutes and try again.")
        core = self.for_key(token)
        try:
            info = core.client.check_token()
        except AuthError:
            with self._lock:
                self._cores.pop(self._id(token), None)
            raise
        return token, info

    @property
    def active(self) -> int:
        return len(self._cores)
