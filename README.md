# Real Life Rail

Where your train really is, between stations.

Type a station and a time, pick a train, and see its whole run. That includes every stop **and every timing point it
passes through** (junctions and the stations it runs past), with the booked, reported and expected time at each one. A
blue bar shows where the train is *now*. Between reports it moves along the line at the booked speed for that section,
and it holds short of the next point until that point is reported. A train held at a signal therefore shows as held, not
as if it had arrived.

It's built on the [Realtime Trains](https://www.realtimetrains.co.uk/) API. RTT records every timing point, not only
stations, so the train's position can be shown more precisely than in apps that only know about stations.

- Runs on your PC. Your phone opens it in Chrome and can install it to the home screen.
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

The token stays on the server. RTT's terms forbid putting it in an app, and it never reaches the browser (a test
checks this).

## On your Android phone

1. On the PC: `uv run realliferail serve --lan`. It prints an address like `http://192.168.0.186:8765`.
2. Fedora's firewall blocks that port by default. Open it once:
   ```sh
   sudo firewall-cmd --permanent --add-port=8765/tcp && sudo firewall-cmd --reload
   ```
3. On the phone (same Wi-Fi), open that address in Chrome. Then tap ⋮ and choose **Add to Home screen**.

Over plain `http://` on a local address, Chrome adds a shortcut rather than a full app, because installing needs
HTTPS. The pages work the same either way. For the full app (its own window, icon and offline page), either:
- use [Tailscale](https://tailscale.com/) and run `tailscale serve 8765`, which gives an `https://…ts.net` address that
  also works away from home, **or**
- in Chrome on the phone, open `chrome://flags`, enable *Insecure origins treated as secure*, and add
  `http://192.168.0.186:8765`.

To keep it running all the time, there's a systemd user service in `scripts/realliferail.service`. Its header comments
give the commands.

## Reading the train page

| You see | It means |
|---|---|
| **14:41** in bold | Reported by RTT. Reports are to the minute. |
| 14:41 | RTT's forecast. |
| 14:41 <sup>est</sup> in grey | Our estimate, where RTT gives none. It carries the delay forward, lets a late train win back booked recovery time, and never leaves a stop early. |
| small grey rows | Timing points it passes without stopping. Their booked times are working-timetable times, which can be on the half minute (½). |
| blue bar | Where we think the train is now. |
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
- Typeface: IBM Plex Sans, SIL Open Font License.
