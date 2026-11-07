# Decisions

Newest last. Add to this whenever a choice is made, with the reason.

## 2026-11-07: planning, owner away

- **Next-generation API only (`data.rtt.io`).** The old API answers 418 and is shut.
- **Free tier works. Detailed mode is used when it's allowed.** The owner first said not to spend, then asked about the paid
  plan mid-build. So the app asks for `detailed=true` only when `/api/info` lists `allowDetailed`, and copes with
  whatever fields come back either way.
- **Server plus PWA, not a native Android app.** RTT forbids tokens in distributed apps, so a server is needed anyway.
  A PWA installs on Android from Chrome, and the same pages work on a desktop. No Android SDK, no store.
- **Same stack as uppYT** (FastAPI, Jinja, plain CSS, Typer, uv, pytest + playwright), so the owner's habits and harness
  carry over. Plain JS for the live view, because the marker moves every second and htmx swaps would be wasteful.
- **No TUI.** uppYT's every-feature-in-three-surfaces rule doesn't carry over. A train tracker is a phone thing. The CLI
  covers scripting and checking the token.
- **Demo mode with a simulator** when there's no token, clearly bannered. It lets the owner see the app working
  immediately, and it's the test double. Chosen over shipping a blank app that can't show anything until a token exists.
- **Fixtures:** the uppYT rule is "recordings only". With no token, real service responses can't be recorded yet. One real
  board response captured by another open project shows the true shape. Its quirks are reproduced in our own fixtures,
  named `spec_*.json`. The file itself has no licence, so it isn't copied. `realliferail record` replaces them once a
  token exists.
- **Offline station list:** davwheat/uk-railway-stations (ODbL, from Trainline EU) for name, CRS and lat/lon, bundled
  unchanged with attribution. It costs no API calls on every keystroke. RTT accepts CRS codes directly.
- **Signals aren't claimed.** The API has timing points only. The UI says "passes" and "timing points".
- **Our estimate only fills gaps.** RTT's forecast wins where it exists, since it uses more data than we have. Ours is
  used for points RTT hasn't forecast, and for the live position, and it's labelled.
- **Colour means something.** Lights down stays greyscale. Amber for late, red for cancelled or problems, and one blue accent
  for the live train marker. Same as uppYT's "colour only comes from content", with the content here being status.
- **Work happens on a branch in a worktree.** The repo starts with the plan on `main`. The build is on
  `worktree-first-build` (in `.claude/worktrees/first-build`), for the owner to fast-forward `main` to.

## 2026-11-07: building

- **Estimate tuning is a guess, said so.** A late train wins back 75% of the booked allowance in each section, and a
  minimum dwell is 30 s. No real data could be used to tune this. `record` collects what a backtest would need.
- **Lateness is whole minutes, rounded toward zero**, as on the railway. 2.5 min late shows as 2.
- **The marker never passes an unreported point.** It holds at 95% of the section. Once the section has taken 2 min longer
  than expected, the page says "No report at X yet". That covers a train held at a signal, or a late report, and we
  can't tell which. That's said plainly rather than guessed.
- **Out of allowance is "busy", not "missing".** UI tests showed that once the budget ran out, a train page said
  "Couldn't show that train" with a 404. Now it's a 503 that names the reason and retries every 30 s. Cached answers are
  served, marked stale, whenever there are any.
- **The simulator's rate-limit headers slide** like the real ones. They first counted every request since start, so a
  demo server would have locked itself out after 100 calls.
- **Big stations win short prefixes in search.** "padd" gave Paddock Wood before Paddington. A hand-picked list of
  termini and big interchanges gets a boost. There's no usage data in the bundled list to do better.
- **Layout changes jump, progress animates.** Every refresh made the travelled line regrow from the top (seen on the
  contact sheet). Only the train's own movement animates now.
- **With passing points hidden, the marker runs between the visible stops by time.** Hidden rows have no height, so
  placing it between two hidden passes put it in the wrong spot.
- **Phone targets are 44 px**, enforced by the browser matrix. The nav links were 37 px.
- **The service worker caches only the app shell, never train data.** A stale time shown as current would be worse than
  the offline page.
- **Each UI test gets a fresh allowance.** All of them run in one frozen simulated minute, so the real 10-a-minute
  limit would correctly trip a few tests in. Resetting it per test is a test fixture, not a looser limit.
