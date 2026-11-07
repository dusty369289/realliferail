# Design notes

Look taken from uppYT's **Lights down** theme (`uppYT/src/uppyt/web/static/css/themes/lights-down.css`), so the owner's
projects feel like one family.

## From memory, not re-read
- **Every Layout:** stack, cluster and sidebar primitives in `composition/layout.css`.
- **CUBE CSS:** composition, utility, block, exception, in cascade layers.
- **Refactoring UI:** de-emphasise labels, not emphasise values. Fixed spacing and type scales.
- **Practical Typography:** tabular figures for every time, so columns line up.
- **GOV.UK Design System:** buttons name their action. Say what's wrong instead of disabling.
- **WCAG 2.2:** 4.5:1 text contrast (tested), visible focus, keyboard works for everything.
- **Station departure boards and RTT's own pages:** the booked-then-actual column pair, platform in its own column,
  passes in smaller grey text. Familiar to anyone who uses RTT.

## Service view
A vertical line down the left. Calls are filled squares (not circles, for the near-square look). Passes are short ticks.
The train is a blue bar on the line, placed between the last and next points by the engine, with "Passed X 14:52 ·
next Y est 14:58" pinned at the top. Points already reported fade to muted. Your boarding station stays bold.
