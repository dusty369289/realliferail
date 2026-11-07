"""Offline station search, from the bundled list in `data/stations.json` (see data/README.md). No API calls."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources


@dataclass(frozen=True, slots=True)
class Station:
    name: str
    crs: str
    lat: float | None
    lon: float | None


# Big stations people are most likely to mean when a short prefix fits several ("padd" is Paddington before
# Paddock Wood). Hand-picked: London termini and the busiest interchanges outside London.
MAJOR = frozenset(
    [
        "PAD",
        "EUS",
        "KGX",
        "STP",
        "LST",
        "LBG",
        "WAT",
        "VIC",
        "CHX",
        "CST",
        "FST",
        "MYB",
        "MOG",
        "BFR",
        "CLJ",
        "SRA",
        "ZFD",
        "TCR",
        "LIV",
        "BHM",
        "BHI",
        "MAN",
        "MCV",
        "LDS",
        "LIV",
        "LPY",
        "GLC",
        "GLQ",
        "EDB",
        "HYM",
        "NCL",
        "YRK",
        "SHF",
        "NOT",
        "DBY",
        "LEI",
        "BRI",
        "BPW",
        "CDF",
        "RDG",
        "OXF",
        "CBG",
        "MKC",
        "PBO",
        "DON",
        "WKF",
        "HUD",
        "PRE",
        "CRE",
        "STP",
        "GTW",
        "SOU",
        "BMH",
        "EXD",
        "PLY",
        "SWI",
        "BTN",
        "ABD",
        "INV",
        "PER",
        "STG",
        "DEE",
        "COV",
        "WVH",
        "NWP",
    ]
)


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ").replace("st.", "st ").replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class StationIndex:
    def __init__(self, stations: list[Station]):
        self.stations = stations
        self._by_crs = {s.crs: s for s in stations}
        self._norm = [(_norm(s.name), s) for s in stations]

    @classmethod
    def bundled(cls) -> StationIndex:
        return _bundled()

    def by_crs(self, code: str) -> Station | None:
        return self._by_crs.get(code.strip().upper())

    def search(self, query: str, limit: int = 8) -> list[Station]:
        q = _norm(query)
        if not q:
            return []
        scored: list[tuple[float, str, Station]] = []
        exact = self.by_crs(query) if len(query.strip()) == 3 else None
        for name, st in self._norm:
            if st is exact:
                continue
            words = name.split()
            if name == q:
                score = 1
            elif name.startswith(q):
                score = 2
            elif any(w.startswith(q) for w in words):
                score = 3
            elif all(any(w.startswith(part) for w in words) for part in q.split()):
                score = 4
            elif q in name:
                score = 5
            else:
                continue
            if st.crs in MAJOR and score > 1:
                score -= 1.5
            scored.append((score, name, st))
        scored.sort(key=lambda t: (t[0], len(t[1]), t[1]))
        out = [exact] if exact else []
        return out + [s for _, _, s in scored][: limit - len(out)]

    def resolve(self, text: str) -> Station | None:
        """Best guess for what someone typed: a CRS, an exact name, or the top search hit."""
        text = text.strip()
        if not text:
            return None
        m = re.search(r"\(([A-Za-z]{3})\)\s*$", text)
        if m and self.by_crs(m.group(1)):
            return self.by_crs(m.group(1))
        if len(text) == 3 and self.by_crs(text):
            return self.by_crs(text)
        hits = self.search(text, 1)
        return hits[0] if hits else None


@cache
def _bundled() -> StationIndex:
    raw = json.loads(resources.files("realliferail.data").joinpath("stations.json").read_text("utf-8"))
    out = []
    for r in raw:
        crs = (r.get("crsCode") or "").strip().upper()
        name = (r.get("stationName") or "").strip()
        if len(crs) == 3 and name:
            out.append(Station(name=name, crs=crs, lat=r.get("lat"), lon=r.get("long")))
    return StationIndex(out)
