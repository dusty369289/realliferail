"""Command line: run the server, check the token, look at boards and trains, record real responses."""

from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path

import typer

from ..domain.engine import build
from ..domain.models import Kind
from ..domain.parse import parse_service
from ..services.app import LONDON, Realliferail, RttError, from_environment
from ..web.app import hm

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Real Life Rail: live GB train tracker.")


def _core(demo: bool) -> Realliferail:
    core = from_environment(demo=True if demo else None)
    if core.demo and not demo:
        typer.secho("No RTT_TOKEN found, so using simulated trains (demo mode).", fg="yellow", err=True)
    return core


def _lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; this just picks the outward interface
            return s.getsockname()[0]
    except OSError:
        return None


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Address to listen on."),
    port: int = typer.Option(8765, help="Port."),
    lan: bool = typer.Option(
        False, "--lan", help="Listen on every interface so a phone on the same network can open it."
    ),
    demo: bool = typer.Option(False, "--demo", help="Use simulated trains even if a token is set."),
    hosted: bool = typer.Option(
        False,
        "--hosted",
        help="For a public server: each visitor brings their own key, kept encrypted in their browser. "
        "Needs REALLIFERAIL_SECRET (64 hex characters). The server stores no key.",
    ),
    insecure_cookies: bool = typer.Option(
        False, "--insecure-cookies", help="Hosted mode over plain http, for local testing only."
    ),
):
    """Start the web app."""
    import os

    import uvicorn

    from ..services.hosted import Hosted, load_secret
    from ..web.app import create_app

    if hosted:
        try:
            secret = load_secret(os.environ.get("REALLIFERAIL_SECRET"))
        except ValueError as e:
            typer.secho(str(e), fg="red", err=True)
            raise typer.Exit(2) from e
        web = create_app(hosted=Hosted(secret), secure_cookies=not insecure_cookies)
        typer.echo("Hosted mode: visitors bring their own keys. No key is stored here.")
    else:
        web = create_app(_core(demo))
    if lan:
        host = "0.0.0.0"
    typer.echo(f"Real Life Rail on http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}")
    if host == "0.0.0.0":
        ip = _lan_ip()
        if ip:
            typer.echo(f"On your phone (same Wi-Fi): http://{ip}:{port}")
    # uvicorn exits rather than raising when the port is taken, so check first and say it in a sentence
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
    except OSError as e:
        typer.secho(f"Couldn't listen on {host}:{port}: {e.strerror or e}. Try another --port.", fg="red", err=True)
        raise typer.Exit(1) from e
    # behind a reverse proxy (Caddy) in hosted mode; uvicorn's own access log stays off, the proxy logs
    uvicorn.run(
        web,
        host=host,
        port=port,
        log_level="warning",
        proxy_headers=hosted,
        forwarded_allow_ips="*" if hosted else None,
    )


@app.command()
def token():
    """Check the RTT token: what it's allowed and how much allowance is left. Costs one or two calls."""
    core = from_environment()
    if core.demo:
        typer.secho("No token. Put RTT_TOKEN=... in .env (get one at https://api-portal.rtt.io).", fg="red", err=True)
        raise typer.Exit(2)
    try:
        info = core.client.check_token()
    except RttError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from e
    st = core.budget.state()
    typer.echo(f"Token works ({info.kind} token), API version {info.api_version or 'unknown'}.")
    typer.echo(f"Detailed mode: {'on' if info.detailed else 'off'}")
    typer.echo(f"Entitlements: {', '.join(info.entitlements) or 'none (free plan)'}")
    if info.history_days:
        typer.echo(f"History: last {info.history_days} days")
    typer.echo("Left: " + ", ".join(f"{d} {st.remaining[d]}/{st.limits[d]}" for d in ("minute", "hour", "day")))


@app.command()
def board(
    station: str = typer.Argument(..., help="Station name or CRS code."),
    time: str = typer.Option("", help="HH:MM, default now."),
    to: str = typer.Option("", help="Only trains calling here later."),
    arrivals: bool = typer.Option(False, "--arrivals", help="Arrivals instead of departures."),
    demo: bool = typer.Option(False, "--demo"),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Show a departure (or arrival) board."""
    core = _core(demo)
    when = None
    if time:
        hh, _, mm = time.partition(":")
        n = core.now()
        when = n.replace(hour=int(hh), minute=int(mm or 0), second=0, microsecond=0)
    try:
        res = core.board(station, when, 60, to or None, "arr" if arrivals else "dep")
    except RttError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from e
    rows = []
    for r in res.rows:
        t = r.arrival if arrivals else r.departure
        live = t.actual or t.forecast or t.estimate
        rows.append(
            {
                "id": r.unique_id,
                "booked": hm(t.booked),
                "live": hm(live),
                "actual": bool(t.actual),
                "place": r.origin if arrivals else r.destination,
                "platform": r.platform,
                "operator": r.operator_name,
                "cancelled": r.cancelled,
            }
        )
    if as_json:
        typer.echo(json.dumps({"station": res.board.station_name, "rows": rows}, indent=1))
        return
    typer.echo(
        f"{res.board.station_name}: {'arrivals' if arrivals else 'departures'} "
        f"{hm(res.board.time_from)} to {hm(res.board.time_to)}"
    )
    for r in rows:
        live = "Cancelled" if r["cancelled"] else (r["live"] if r["live"] and r["live"] != r["booked"] else "On time")
        typer.echo(f"  {r['booked']}  {live:9}  {r['place'][:32]:32}  {r['platform'] or '':>3}  {r['id']}")


@app.command()
def train(
    unique_id: str = typer.Argument(..., help="Identity:date, e.g. C05986:2026-09-06 (shown by `board`)."),
    passes: bool = typer.Option(True, "--passes/--no-passes", help="Show timing points it runs through."),
    demo: bool = typer.Option(False, "--demo"),
):
    """Show one train's run and where it is now."""
    core = _core(demo)
    try:
        res = core.service(unique_id)
    except RttError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from e
    tl = res.timeline
    s = tl.service
    typer.echo(f"{s.operator_name} {s.headcode or ''}  {s.origin_name} to {s.destination_name}".strip())
    typer.echo(tl.position.headline)
    for v in tl.points:
        p = v.point
        if p.kind is Kind.PASS and not passes:
            continue
        shown = v.passing or v.departure or v.arrival
        if shown is None:
            continue
        mark = ">" if tl.position.from_index == v.index else " "
        src = {"actual": "", "forecast": "exp", "est": "est"}.get(str(shown.source), "")
        name = p.name if p.kind is Kind.CALL else f"  ({p.name})"
        live = "" if str(shown.source) == "booked" else f"{hm(shown.time)} {src}".strip()
        typer.echo(f"{mark} {name[:34]:34} {hm(shown.booked, half=p.kind is Kind.PASS):6} {live}")


@app.command()
def record(
    station: str = typer.Argument("RDG", help="Station to record a board from."),
    services: int = typer.Option(2, help="How many of its trains to record too."),
    out: Path = typer.Option(Path("tests/fixtures/rtt"), help="Folder to write into."),
):
    """Save real RTT responses as test fixtures. Costs 1 + SERVICES calls (plus 1-2 to check the token)."""
    core = from_environment()
    if core.demo:
        typer.secho("Recording needs a real token (RTT_TOKEN).", fg="red", err=True)
        raise typer.Exit(2)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(LONDON).strftime("%Y%m%d-%H%M")
    core.client.check_token()
    f = core.client.location(station, core.now(), 60)
    path = out / f"real_location_{station.upper()}_{stamp}.json"
    path.write_text(json.dumps(f.body, indent=1) + "\n", "utf-8")
    typer.echo(f"wrote {path}")
    for raw in ((f.body or {}).get("services") or [])[:services]:
        meta = raw.get("scheduleMetadata") or {}
        uid = f"{meta.get('identity')}:{meta.get('departureDate')}"
        sf = core.client.service(uid)
        p = out / f"real_service_{meta.get('identity')}_{stamp}.json"
        p.write_text(json.dumps(sf.body, indent=1) + "\n", "utf-8")
        svc = parse_service(sf.body)
        tl = build(svc, core.now())
        n_pass = sum(1 for pt in svc.points if pt.kind is Kind.PASS)
        typer.echo(f"wrote {p} ({len(svc.points)} points, {n_pass} passes): {tl.position.headline}")
    st = core.budget.state()
    typer.echo(f"Allowance left this hour: {st.remaining['hour']}")


if __name__ == "__main__":
    app()
