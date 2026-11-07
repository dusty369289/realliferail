# Decisions

Newest last. Add to this whenever a choice is made, with the reason.

## 2026-11-07: planning, owner away

- **Next-generation API only (`data.rtt.io`).** The old API answers 418 and is shut.
- **Free tier, no spending.** The owner said don't spend. Detailed mode (£4 a month) stays off. The app asks for
  `detailed=false` and copes with whatever fields come back.
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
- **Work happens in place on a branch.** The folder wasn't a git repo, so worktree isolation was impossible. The repo
  starts with the plan on `main`, and the build goes on `first-build` for the owner to fast-forward.
