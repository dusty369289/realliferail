"""FastAPI app. Holds no business logic: it calls `services.app.Realliferail` and renders templates."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..domain.engine import Shown, State, stop_summary
from ..domain.models import Kind, TimeSource
from ..services.app import TIERS, BusyError, Realliferail, RttError
from ..services.hosted import COOKIE, MAX_AGE, Hosted

HERE = Path(__file__).parent
LONDON = ZoneInfo("Europe/London")
VERSION = "1"


FRACTIONS = {15: "¼", 30: "½", 45: "¾"}


def hm(dt: datetime | None, half: bool = False) -> str:
    """14:31, or with `half`, 14:31½ / 14:31¼: the working timetable has half minutes, detailed actuals quarters."""
    if dt is None:
        return ""
    dt = dt.astimezone(LONDON)
    s = dt.strftime("%H:%M")
    if half and dt.second:
        s += FRACTIONS.get(round(dt.second / 15) * 15, "")
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


def private_client(host: str | None) -> bool:
    """Single-user mode: the server's key can only be changed from this machine or the home network."""
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def create_app(
    core: Realliferail | None = None,
    settings_allowed=private_client,
    hosted: Hosted | None = None,
    secure_cookies: bool = True,
) -> FastAPI:
    """Single-user (`core`: one key, kept on the server) or hosted (`hosted`: each browser brings its own key)."""
    if (core is None) == (hosted is None):
        raise ValueError("give exactly one of core or hosted")
    app = FastAPI(title="Real Life Rail", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    env = templates.env
    env.filters["hm"] = hm
    env.filters["hmh"] = lambda dt: hm(dt, half=True)
    env.globals.update(Kind=Kind, TimeSource=TimeSource, State=State, delay_class=delay_class, ago=ago, VERSION=VERSION)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def cur(request: Request) -> Realliferail:
        """This visitor's client: from their cookie when hosted, else the one server-wide client."""
        c = getattr(request.state, "core", None)
        if c is None:
            c = hosted.for_cookie(request.cookies.get(COOKIE)) if hosted else core
            request.state.core = c
        return c

    def page(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
        c = cur(request)
        ctx.update(demo=c.demo, budget=c.budget.state(), now=c.now(), hosted=hosted is not None)
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
        all: int = 0,
        refresh: int = 0,
    ):
        core = cur(request)
        if not station.strip():
            return RedirectResponse("/", status_code=303)
        if max(len(station), len(to), len(time), len(day)) > 80:
            return HTMLResponse("That search is too long.", status_code=400)
        mode = "arr" if mode == "arr" else "dep"
        error = None
        when = None
        try:
            when = _when(core, time, day)
        except ValueError:
            error = "That time isn't valid. Use 24-hour time like 17:45."
        result = None
        busy = False
        if error is None:
            try:
                result = core.board(station, when, window, to or None, mode, show_all=bool(all), force=bool(refresh))
            except BusyError as e:
                error, busy = str(e), True
            except RttError as e:
                error = str(e)
        base = {"station": station, "to": to, "mode": mode, "window": window}
        if all:
            base["all"] = 1
        nav = {}
        if result:
            t0 = result.board.time_from
            for label, delta in (("earlier", -window), ("later", window)):
                t = t0 + timedelta(minutes=delta)
                nav[label] = "/board?" + urlencode({**base, "time": t.strftime("%H:%M"), "day": t.date().isoformat()})
            other = "arr" if mode == "dep" else "dep"
            nav["switch"] = "/board?" + urlencode({**base, "mode": other, "time": time, "day": day})
            nav["refresh"] = "/board?" + urlencode({**base, "time": time, "day": day, "refresh": 1})
            flip = {k: v for k, v in base.items() if k != "all"} | ({} if all else {"all": 1})
            nav["all"] = "/board?" + urlencode({**flip, "time": time, "day": day})
        live = not time  # "now" boards refresh themselves
        return page(
            request,
            "board.html",
            status=200 if result else (503 if busy else 400),
            result=result,
            error=error,
            busy=busy,
            q=base | {"time": time, "day": day},
            nav=nav,
            live=live,
        )

    @app.get("/train/{uid}", response_class=HTMLResponse)
    def train(request: Request, uid: str, at: str = "", to: str = ""):
        core = cur(request)
        try:
            res = core.service(uid)
        except BusyError as e:
            return page(request, "error.html", status=503, error=str(e), busy=True)
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
    def train_live(request: Request, uid: str, at: str = "", to: str = "", force: int = 0):
        core = cur(request)
        try:
            res = core.service(uid, background=not force, force=bool(force))
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

    index = hosted.stations if hosted else core.stations

    @app.get("/api/stations")
    def stations(q: str = Query("", max_length=60)):
        return JSONResponse([{"name": s.name, "crs": s.crs} for s in index.search(q)])

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request):
        core = cur(request)
        info = core.token_info()
        return page(request, "about.html", info=info, token_error=core.token_error)

    def settings_page(request: Request, status: int = 200, **ctx) -> HTMLResponse:
        core = cur(request)
        return page(
            request,
            "settings.html",
            status=status,
            tier=core.tier(),
            tiers=TIERS,
            info=None if core.demo else core.token_info(),
            hint=None if core.demo else core.client.token_hint,
            token_error=core.token_error,
            can_edit=hosted is not None or settings_allowed(request.client.host if request.client else None),
            **ctx,
        )

    def guard(request: Request) -> HTMLResponse | None:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return HTMLResponse("Refused: that request came from another site.", status_code=403)
        if hosted is None and not settings_allowed(request.client.host if request.client else None):
            return settings_page(request, status=403, error="Settings can only be changed from your own network.")
        return None

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request, saved: int = 0, removed: int = 0):
        msg = "Token saved and working." if saved else ("Token removed. Showing demo data." if removed else None)
        return settings_page(request, message=msg)

    @app.post("/settings/token", response_class=HTMLResponse)
    async def settings_token(request: Request):
        if (refused := guard(request)) is not None:
            return refused
        body = await request.body()
        if len(body) > 8192:
            return settings_page(request, status=413, error="That's far too long to be a key.")
        form = parse_qs(body.decode("utf-8", "replace"))
        token = (form.get("token") or [""])[0]
        try:
            if hosted:
                token, _ = hosted.check(token, request.client.host if request.client else "?")
            else:
                cur(request).set_token(token)
        except BusyError as e:
            return settings_page(request, status=429, error=str(e))
        except RttError as e:
            return settings_page(request, status=400, error=str(e))
        resp = RedirectResponse("/settings?saved=1", status_code=303)
        if hosted:
            resp.set_cookie(
                COOKIE,
                hosted.box.seal(token),
                max_age=MAX_AGE,
                httponly=True,
                secure=secure_cookies,
                samesite="lax",
                path="/",
            )
        return resp

    @app.post("/settings/token/remove", response_class=HTMLResponse)
    async def settings_remove(request: Request):
        if (refused := guard(request)) is not None:
            return refused
        resp = RedirectResponse("/settings?removed=1", status_code=303)
        if hosted:
            resp.delete_cookie(COOKIE, path="/", secure=secure_cookies, httponly=True, samesite="lax")
        else:
            cur(request).remove_token()
        return resp

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
