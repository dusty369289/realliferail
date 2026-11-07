"""The only HTTP code. Talks to data.rtt.io and nothing else."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

BASE = "https://data.rtt.io"
ALLOWED_HOSTS = {"data.rtt.io"}
API_VERSION = "2026-07-25"  # newest version in the changelog, pinned so shapes don't shift under us


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names
    body: Any = None  # parsed JSON, or None (e.g. 204)


class Transport(Protocol):
    def get(self, path: str, params: dict[str, str], token: str | None) -> Response: ...


class TransportError(Exception):
    """Network failure: no answer at all."""


class HttpTransport:
    def __init__(self, base: str = BASE, timeout: float = 10.0):
        host = urlsplit(base).hostname or ""
        if host.lower() not in ALLOWED_HOSTS:
            raise ValueError(f"Refusing to talk to {host}: only {', '.join(sorted(ALLOWED_HOSTS))} is allowed.")
        self._client = httpx.Client(
            base_url=base,
            timeout=timeout,
            headers={"Version": API_VERSION, "User-Agent": "realliferail/0.1 (personal use)"},
            follow_redirects=False,
        )

    def get(self, path: str, params: dict[str, str], token: str | None) -> Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            r = self._client.get(path, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise TransportError(type(e).__name__) from e
        body = None
        if r.content:
            try:
                body = r.json()
            except ValueError:
                body = {"error": r.text[:300]}
        return Response(status=r.status_code, headers={k.lower(): v for k, v in r.headers.items()}, body=body)

    def close(self) -> None:
        self._client.close()
