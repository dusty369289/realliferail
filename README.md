# Real Life Rail

Where your train really is, between stations.

Type a station and a time, pick a train, and see its whole run. That includes every stop **and every timing point it
passes through** (junctions and the stations it runs past), with the booked, reported and expected time at each one. A
yellow train-front panel shows where the train is *now*. Between reports it moves along the line at the booked speed for that section,
and it holds short of the next point until that point is reported. A train held at a signal therefore shows as held, not
as if it had arrived.

It's built on the [Realtime Trains](https://www.realtimetrains.co.uk/) API. RTT records every timing point, not only
stations, so the train's position can be shown more precisely than in apps that only know about stations.

- Runs on a server (Docker) or your own computer. Your phone opens it in Chrome and installs it as an app.
- Works without a token in **demo mode**, with simulated trains on two real routes.
- Free-tier friendly: calls are cached, shared and paced to fit 100 an hour.

## Quick start

```sh
cd ~/Projects/realliferail
uv sync
uv run realliferail serve            # http://127.0.0.1:8765, demo mode until you add a token
```

### Add your Realtime Trains token

1. Sign in at <https://api-portal.rtt.io> (the API portal, not the RTT+ subscriptions page) and request a token. The
   free plan works. The Hobbyist plan (£4 a month) adds detailed mode, which the app uses automatically when your token
   allows it.
2. Put it in `.env` in this folder (it's gitignored):
   ```
   RTT_TOKEN=paste-your-token-here
   ```
   Either an access token or a refresh token works. The app works out which.
3. Check it: `uv run realliferail token`. This costs 1 or 2 calls and shows entitlements and what's left this hour.
4. Restart `serve`. The "Demo data" banner goes away.

In single-user mode the key stays on the server and never reaches the browser. In hosted mode it reaches the browser only
as an encrypted cookie that page scripts can't read. Tests check both.

## Two ways to run it

**Hosted (a server, for your phone and friends).** Everyone brings their own Realtime Trains key. It's pasted once
in Settings, checked with RTT, then kept **in that browser only**, encrypted (AES-256-GCM, server secret), in an
HttpOnly cookie that page scripts can't read. The server stores no key and no data. It decrypts the cookie for each request and keeps
that person's short-life access token and allowance in memory. With no key you get demo trains, so a public server
can't spend anyone's allowance. RTT's terms are kept: no key is ever built into an app, and each person uses their own.

```sh
docker build -t realliferail .
docker run -d -p 8080:8080 --read-only --tmpfs /tmp --user 65534:65534 --cap-drop ALL \
  -e REALLIFERAIL_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" realliferail
```
Put HTTPS in front (Caddy, for example). Keep `REALLIFERAIL_SECRET` the same across restarts, because changing it signs
everyone out. They just paste their key again. The live copy is at **https://rail.3net.dev**.

**Single user (your own computer).** `uv run realliferail serve` keeps one key on the server
(`~/.config/realliferail/settings.json`, or `RTT_TOKEN` in `.env`) and shares it between all your devices.

### On your Android phone

Open **https://rail.3net.dev** in Chrome, tap ⋮ and choose **Install app**. Then:
1. **Settings**: paste your key from api-portal.rtt.io (once per device).
2. Search your commute with "Calling at", then **Save this journey**. From then on it's one tap, and **Return** gives the way
   home.
3. Tap your train. The big number counts down to your departure, and the yellow panel shows the train on the line, junction by
   junction. If you leave and come back, it catches up at once. The home screen offers "Carry on tracking".

## How often it updates, and what refresh costs

Realtime Trains allows 10 calls a minute and 100 an hour on Free and Hobbyist. The server keeps every answer and shares it
between all your devices and tabs:
- A train page asks again every 40 s or so (`3600 / (calls left this hour - 10)`, never under 30 s), slows down when
  the hour runs low, and stops while the app is in the background. It catches up as soon as you come back.
- **Refresh** gets a new answer only if the current one is over 15 s old. Pressing it again and again costs nothing. It
  says "Already up to date (8 s old)".
- Boards are kept for a minute. The last 10 calls of each hour are kept for searches, never spent on background updates.
- If the allowance does run out, pages show the last answer marked as stale, or a "busy" page that retries by itself.
  They never show "not found".

## Plans

**Settings** in the app takes the key. It's checked with RTT before it's kept, and never shown again in full. It
shows which plan it is, and the app adapts:

| | Free | Hobbyist (£4/month) | Team and up |
|---|---|---|---|
| Live times | to the minute | **to the quarter minute** (berth steps) | same |
| Passing points and the train between stations | yes | yes, more precise | same |
| Headcodes, unit numbers and class, branding | | yes | yes |
| Empty stock and staff-only moves (off by default) | | yes | yes |
| Update interval | about 40 s | about 40 s | faster, from the bigger allowance |

## Reading the train page

| You see | It means |
|---|---|
| **14:41** in bold | Reported by RTT: to the minute on Free, to the quarter minute (14:41¼) with detailed mode. |
| 14:41 | RTT's forecast. |
| *14:41* <sup>est</sup> in grey italic | Our estimate, where RTT gives none. It carries the delay forward, lets a late train win back booked recovery time, and never leaves a stop early. |
| small grey rows | Timing points it passes without stopping. Their booked times are working-timetable times, which can be on the half minute (½). |
| yellow panel | Where we think the train is now (it's the front of a train). |
| +3 / −1 | Minutes late / early. |

The panel at the top says what's happening in a sentence, such as *"Passed Twyford 14:52 (2 min late). Next: Reading,
expected about 14:58"* and *"It leaves Reading at 14:58, in 6 min, platform 4"*. If a train goes quiet longer than
expected, it says so instead of guessing.

**What it can't show:** signals. RTT's API only gives timing points, not signals or track sections (`docs/rtt-api.md`
explains why). Signal-level tracking would need Network Rail's own train describer feed, a possible later stage.

## Command line

```sh
uv run realliferail board RDG                 # departures now  (--arrivals, --to PAD, --time 17:30, --json)
uv run realliferail train C12345:2026-11-07   # one train's run and where it is (--no-passes)
uv run realliferail token                     # check the token and the allowance
uv run realliferail record RDG --services 2   # save real answers as test fixtures (costs 3 calls + token check)
uv run realliferail serve --lan --demo        # simulated trains even with a token set
```

## Development

```sh
uv run pytest                 # everything except browser and live tests, no network
uv run pytest -m ui           # browser matrix (phone and desktop, dark and light), then open .ui-report/index.html
uv run pytest -m live -n 0    # real RTT calls (needs a token, about 4 calls)
uv run ruff check . && uv run ruff format .
```

`CLAUDE.md` is the standing brief, `docs/decisions.md` records why things are the way they are, and `docs/rtt-api.md`
is the API reference with what was observed.

## Credits

- Train data: [Realtime Trains](https://www.realtimetrains.co.uk/). Not affiliated. API spec in `docs/rtt-openapi.yml` (MIT).
- Station list: [uk-railway-stations](https://github.com/davwheat/uk-railway-stations) by David Wheatley, from
  [Trainline EU](https://github.com/trainline-eu/stations), ODbL.
- Typeface: Barlow and Barlow Semi Condensed by Jeremy Tribby, SIL Open Font License.
