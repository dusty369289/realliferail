# Real Life Rail

A live train tracker for Great Britain that runs on your phone. Type a station and a time, pick a train, and watch it
move along its route. It shows every call **and every timing point it passes** (junctions, through stations), with
booked, actual and estimated times. Between reports it places the train on the line rather than freezing at the last
station. Data comes from the Realtime Trains (RTT) next-generation API at `data.rtt.io`.

FastAPI, Jinja, plain JS, httpx, Pydantic, Typer, uv, Python 3.14. Plain CUBE CSS, no build step. Installable as a PWA
on Android. The server holds the RTT token. The phone only ever talks to our server.

**This file is the standing brief. Keep it current.** Whenever a choice is made, add it to `docs/decisions.md` with the
date and the reason, and change this file if a rule changes. Check `docs/decisions.md` before re-opening a question.
`docs/rtt-api.md` is the API reference with what was actually observed. `docs/design.md` holds UI references.
`docs/plan.md` is the build plan.

## Rules
- **Commits:** small, logical, short messages, explicit paths (never `git add -A`). **Never** an AI co-author trailer or
  a "Generated with" line. All work is attributed to the owner.
- **Publishing:** GitHub (`dusty369289`) only, and only when the owner asks.
- **The token never leaves the server.** RTT's terms: no token in a distributed app, or it gets revoked. It lives in
  `.env` (gitignored) or the environment. Never logged, never sent to the browser, never in fixtures or screenshots.
- **The RTT allowance is tiny and shared.** The free tier allows 10 a minute, 100 an hour and 1000 a day. Tests never call RTT. Local
  dev without a token runs the simulator. Every real call goes through one budget (`sources/budget.py`) that obeys
  `X-RateLimit-Remaining-*` and `Retry-After`. Polling slows down to fit the budget rather than run out.
- **Be plain about limits.** Say when data is simulated, stale, estimated by us, or missing. Never pass our estimate off
  as RTT's forecast. RTT has no signal or berth data. Don't claim signals.

## Never cut these corners
The same as uppYT, because the owner asked for them to hold on every project.
- **Look before approving.** Inspect first, and approve in a later step. Never send an inspection and the action that
  depends on it together.
- **Keep failing output.** Write a run to a file before reading its tail, and read the real error. Failures are kept in
  `.test-review/failures.log`.
- **Flaky means investigate.** Never re-run until green and move on.
- **Explain warnings, don't clear them.** If a limit is really wrong, say why in `docs/decisions.md`.
- **If one slips anyway, say so** in the report, plainly, and repair what can be repaired.

## Architecture
```
src/realliferail/
  domain/    frozen models (Service, Point, Times), parsing RTT JSON, live position + estimate engine. No I/O
  sources/   transport (the only HTTP code), RTT client, token handling, budget + cache, simulator, station list
  services/  behaviour the interfaces call: board, service, stations
  web/       FastAPI app, templates, static (CSS, JS, PWA manifest, service worker)
  cli/       Typer: serve, board, service, token, record
```
Dependencies point inward only: interfaces -> services -> sources -> domain. Clock and transport are injected.
No HTTP outside `sources/transport.py`. No raw colours outside `web/static/css/themes/`.

## Product rules
- **Board:** departures (or arrivals) at a station from a chosen time, default now, 60-minute window, optional
  "calling at" filter. Cached for 60 s per query.
- **Service view:** every location RTT returns, including passes. Calls are full rows, passes are small rows.
  Times: booked (public time, or working time for passes), then actual if reported, else RTT's forecast, else our
  estimate, each marked as such.
- **Live position:** the last reported point and the next point give a section. Progress through it uses elapsed time
  against the working timetable's section time. It never passes an unreported point (holds at 95%), and says "overdue"
  once the section has taken longer than booked plus 2 minutes.
- **Our estimate** carries the current delay forward. A late train can win back booked allowances (performance,
  engineering, pathing) and extra dwell time, but never leaves an advertised stop before its public time. Our estimate is used only
  where RTT gives no forecast, and it's labelled "est".
- **Polling:** the page moves the marker every second, and asks our server again when the last answer says to
  (`data-refresh`). That's every 15 to 120 s: `3600 / (hour left - 10)`, with a floor of 30 s, from `Budget.refresh_interval`. The server
  re-fetches a train at most that often. Background refreshes never touch the last 10 calls of the hour, which are kept
  for people searching.
- **Your stop:** boards link to `/train/<id>?at=<CRS>&to=<CRS>`. The top panel then says when the train leaves your stop,
  how many minutes and stops away it is, and the platform.

## UI
- **Lights down**, taken from uppYT: black, white and grey, dark first, IBM Plex Sans with tabular figures. Colour is only
  used to mean something. Amber for late, red for cancelled, and one accent for the live train.
- No pills, no glow, near-square corners, ordinary controls. The owner rejected a stereotypical AI look.
- CUBE layers: `tokens, base, composition, block, utility, exception`. Themes are token-only files.
- Phone first (412 px wide). Big touch targets. Works one-handed.

## Tests
- `uv run pytest` runs everything except browser and live tests. `uv run pytest -m ui` runs the phone and desktop
  screenshot matrix, then read `.ui-report/index.html`. `uv run pytest -m live -n 0` makes real RTT calls (costs allowance, needs a token).
- Tests never touch the network. Fixtures are **recordings** where we have them (`tests/fixtures/rtt/`). Spec-derived
  fixtures are named `spec_*.json` and say so, until a real recording replaces them.
- 10 s hard timeout per test. Run output: `pytest ... > file 2>&1`, then read the file.
- After changing how a page looks, read the contact sheet. Before each commit: the full suite once.

## Things that have caught us out
- `api.rtt.io` (the old API) is gone. It answers 418 "no longer available". Only `data.rtt.io` works.
- Real times come **without a UTC offset** (`2026-09-06T14:51:00`) and are UK local time, while `query.timeFrom` has
  one. Parse naive times as Europe/London.
- `query.location.longCodes` come prefixed (`gb-nr:PADTON`), while origin/destination long codes don't. Origin and
  destination locations may have no `shortCodes`.
- `platform.forecast` is populated in practice, though the spec says "not currently used".
- **The spec contradicts itself on nullable enums** (`oneOf: [string, null]` with an enum that leaves out null).
  `tests/test_schema.py` adds null to those enums. Don't "fix" real data to match the spec.
- **UI tests share one frozen simulated minute**, so the real 10-a-minute budget trips a few tests in. The
  `fresh_allowance` fixture resets it per test. A budget error in the app shows as a 503 "busy" page, never as "missing".
- **A paused browser clock freezes debounces too.** Use `page.clock.install(time=...)` and `run_for()`, not `pause_at`.
- **Jinja escapes apostrophes** (`isn&#39;t`). Web tests compare `text(r)`, which unescapes and collapses whitespace.
- **The worktree guard rejects some compound shell commands.** Use the Edit tool, or split commands up.
