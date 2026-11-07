# Build plan

Written 2026-11-07 at the start, while the owner was away. The owner said to build it all without asking, spend nothing,
and use uppYT as the reference for look, testing and working rules.

## Goal
A phone-first train app that beats the usual ones in one way: it uses RTT's timing-point data to show **where the train
is between stations**, with every junction and through station it passes, and their times.

## What the research changed
- The API most guides describe is dead. The new one needs a token from `api-portal.rtt.io`, which only the owner can get.
  So the app is built against a **simulator** that follows the spec and a real recorded response, runs in demo mode with
  no token, and switches to live data when `RTT_TOKEN` is set.
- **There are no signals in the API.** The closest it gets is timing points. The UI says "timing points", not signals.
  Signal-level tracking would need Network Rail's TD feed, which is noted as a later stage.
- At 100 calls an hour, polling has to be budgeted, cached and shared.

## Stages
1. **Docs:** brief, API reference, decisions, design notes.
2. **Core:** frozen models, parser (tolerant of missing fields, naive times as Europe/London), transport, token handling
   (access or refresh), budget and cache, offline station list with search.
3. **Simulator:** a pretend RTT producing boards and services for real station names. Trains move in real time with
   delays, passes, cancellations and early running, so the live view can be exercised with no token. Also the test double.
4. **Engine:** live position along the timeline, overdue detection, recovery-aware estimates where RTT has no forecast.
5. **Web/PWA:** search with autocomplete, board, service view with live marker, manifest and service worker, system-status
   and demo banners, budget readout.
6. **CLI:** `serve`, `board`, `service`, `token` (check entitlements and limits), `record` (save real responses as
   fixtures, stripping nothing secret because the token is never in a body).
7. **Tests:** domain, parser against the real capture's quirks, budget, engine, web routes, simulator, plus a playwright
   screenshot matrix at phone and desktop widths with a contact sheet I read after each visual change.
8. **Iterate:** run the real app in a browser, look at the screenshots, fix what's wrong, repeat.
9. **Docs for the owner:** README with token steps, how to run it on the PC, and how to open it on the Android phone.

## Later, not now
- Network Rail TD feed for signal-by-signal positions (needs an NR open data account plus berth maps).
- A geographic map. Station coordinates are bundled, but timing points have none.
- Backtesting our estimate against RTT's forecast. `record` collects the data for it once a token exists.
