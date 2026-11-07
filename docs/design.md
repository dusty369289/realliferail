# Design notes

## 2026-11-07: "Platform" (replaces the first look)

The owner said the first look (uppYT's Lights down) was boxy, looked AI-made, and was too like their other apps. They
asked for guidance from human-made apps. The new look comes from British railway heritage and transit apps people
actually use, not from app-template chrome.

References, and what each gave:
- **British Rail Corporate Identity Manual (1965, Design Research Unit)** and Kinneir and Calvert's Rail Alphabet
  ([Fonts In Use](https://fontsinuse.com/uses/62451/british-rail-identity-and-signs-1965-1990s),
  [Ministry of Type](https://ministryoftype.co.uk/words/british_rail_identity),
  [transitmap.net](https://transitmap.net/br-manual)). One clear signage sans throughout, navy and white sign plates,
  and a strict, plain hierarchy. Rail Alphabet itself is licensed, so **Barlow** (OFL, drawn from highway and rail
  signage) stands in, with its semi-condensed cut for station names so long names fit.
- **Network Rail Wayfinding Design Manual (2022)**: platform numbers on solid plates, which became the board's platform plates.
  An *expected* platform is an outlined plate, and a confirmed one is solid.
- **Beck-style line diagrams** (carriage-wall line maps): a thick line with ringed stops. Passed track is in ink, track
  still to come is pale. Passing points are short ticks off the side.
- **The yellow warning panel on British train fronts**: the train marker is that panel, with a windscreen and a dark edge. It's
  the most recognisable "it's a train" shape there is, and it means the accent colour has a reason to be there.
- **Transit app / MTA app case studies**
  ([Pratt IxD critique](https://ixd.prattsi.org/2026/02/design-critique-transit/),
  [MTA concept](https://www.adamfishercox.com/portfolio/mta-app)): one giant number you can read while walking
  ("9 min until it leaves Reading"), zero taps to what matters, later departures one glance away.
- **GOV.UK Design System**: the yellow focus ring with a dark outline (human, accessible, not a glow). Buttons name their action.
- **Printed timetables**: warm paper (`#f3efe6`) and navy ink instead of neutral grey. Night mode is deep navy, not black.

Rules that came with it:
- No cards or boxes around content. Hierarchy comes from type size and weight, with hairlines between list rows only.
- No glow, no gradients, no pills. Small square-cornered plates are the one "chip" shape, and only where real signage uses
  them (platform, Board / Alight).
- Inputs are underlined fields, like a form on paper, not boxed widgets.
- Our own estimates are whole minutes and italic. Only RTT's own times get quarter-minute fractions.
- Contrast is still enforced by `tests/test_design.py`. Yellow on paper is only about 1.4:1, so the panel always carries its dark edge,
  and the test checks the edge.

## From memory, not re-read
- **Every Layout:** stack and cluster primitives in `composition/layout.css`.
- **CUBE CSS:** composition, utility, block, exception, in cascade layers.
- **Practical Typography:** tabular figures for every time.
- **WCAG 2.2:** 4.5:1 text contrast (tested), visible focus, 44 px targets (tested).
