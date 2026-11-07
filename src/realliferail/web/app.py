"""FastAPI app. Holds no business logic: it calls `services.app.Realliferail` and renders templates."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..domain.engine import Shown, State, stop_summary
from ..domain.models import Kind, TimeSource
from ..services.app import Realliferail, RttError

HERE = Path(__file__).parent
LONDON = ZoneInfo("Europe/London")
VERSION = "1"


def hm(dt: datetime | None, half: bool = False) -> str:
    if dt is None:
        return ""
    dt = dt.astimezone(LONDON)
    s = dt.strftime("%H:%M")
    if half and dt.second >= 30:
        s += "½"
    return s


def ago(seconds: float) -> str:
    s = int(max(seconds, 0))
    if s < 60:
        return f"{s} s ago"
    if s < 3600:
        return f"{s // 60} min ago"
    return f"{s // 3600} h ago"


def delay_class(shown: Shown | None) -> str:
    if shown is None or shown.delay_min is None:
        return ""
    if shown.delay_min >= 5:
        return "is-very-late"
    if shown.delay_min >= 2:
        return "is-late"
    if shown.delay_min <= -1:
        return "is-early"
    return "is-ontime"


def create_app(core: Realliferail) -> FastAPI:
    app = FastAPI(title="Real Life Rail", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.core = core
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    env = templates.env
    env.filters["hm"] = hm
    env.filters["hmh"] = lambda dt: hm(dt, half=True)
    env.globals.update(Kind=Kind, TimeSource=TimeSource, State=State, delay_class=delay_class, ago=ago, VERSION=VERSION)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def page(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
        ctx.update(demo=core.demo, budget=core.budget.state(), now=core.now())
        return templates.TemplateResponse(request, name, ctx, status_code=status)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
            "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        return resp

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return page(request, "home.html")

    @app.get("/board", response_class=HTMLResponse)
    def board(
        request: Request,
        station: str = "",
        time: str = "",
        day: str = "",
        to: str = "",
        mode: str = "dep",
        window: int = 60,
    ):
        if not station.strip():
            return RedirectResponse("/", status_code=303)
        mode = "arr" if mode == "arr" else "dep"
        error = None
        when = None
        try:
            when = _when(core, time, day)
        except ValueError:
            error = "That time isn't valid. Use 24-hour time like 17:45."
        result = None
        if error is None:
            try:
                result = core.board(station, when, window, to or None, mode)
            except RttError as e:
                error = str(e)
        base = {"station": station, "to": to, "mode": mode, "window": window}
        nav = {}
        if result:
            t0 = result.board.time_from
            for label, delta in (("earlier", -window), ("later", window)):
                t = t0 + timedelta(minutes=delta)
                nav[label] = "/board?" + urlencode({**base, "time": t.strftime("%H:%M"), "day": t.date().isoformat()})
            other = "arr" if mode == "dep" else "dep"
            nav["switch"] = "/board?" + urlencode({**base, "mode": other, "time": time, "day": day})
        live = not time  # "now" boards refresh themselves
        return page(
            request,
            "board.html",
            status=200 if result else 400,
            result=result,
            error=error,
            q=base | {"time": time, "day": day},
            nav=nav,
            live=live,
        )

    @app.get("/train/{uid}", response_class=HTMLResponse)
    def train(request: Request, uid: str, at: str = "", to: str = ""):
        try:
            res = core.service(uid)
        except RttError as e:
            return page(request, "error.html", status=404, error=str(e))
        return page(
            request,
            "train.html",
            res=res,
            tl=res.timeline,
            at=at.upper(),
            to=to.upper(),
            uid=uid,
            stop=stop_summary(res.timeline, at),
            off=stop_summary(res.timeline, to, boarding=False),
        )

    @app.get("/train/{uid}/live", response_class=HTMLResponse)
    def train_live(request: Request, uid: str, at: str = "", to: str = ""):
        try:
            res = core.service(uid, background=True)
        except RttError as e:
            return HTMLResponse(f'<p class="problem" data-error>{_esc(str(e))}</p>', status_code=503)
        return page(
            request,
            "_route.html",
            res=res,
            tl=res.timeline,
            at=at.upper(),
            to=to.upper(),
            uid=uid,
            stop=stop_summary(res.timeline, at),
            off=stop_summary(res.timeline, to, boarding=False),
        )

    @app.get("/api/stations")
    def stations(q: str = Query("", max_length=60)):
        return JSONResponse([{"name": s.name, "crs": s.crs} for s in core.search_stations(q)])

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request):
        info = core.token_info()
        return page(request, "about.html", info=info, token_error=core.token_error)

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(HERE / "static" / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js")
    def sw():
        # served from the root so its scope covers the whole app
        return FileResponse(
            HERE / "static" / "js" / "sw.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    @app.get("/offline", response_class=HTMLResponse)
    def offline(request: Request):
        return page(request, "offline.html")

    @app.get("/healthz")
    def healthz():
        return Response("ok", media_type="text/plain")

    return app


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _when(core: Realliferail, time: str, day: str) -> datetime | None:
    time, day = time.strip(), day.strip()
    if not time and not day:
        return None
    now = core.now()
    d = datetime.fromisoformat(day).date() if day else now.date()
    if time:
        hh, _, mm = time.replace(".", ":").partition(":")
        t = datetime(d.year, d.month, d.day, int(hh), int(mm or 0), tzinfo=LONDON)
        if not day and t < now - timedelta(hours=6):
            t += timedelta(days=1)  # "00:30" typed at 23:50 means tonight, not last night
    else:
        t = datetime(d.year, d.month, d.day, now.hour, now.minute, tzinfo=LONDON)
    return t
