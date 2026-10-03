# Plan · W-7 · v1.1.1 — the patch after v1.1.0

Written 2026-10-03, on the Arbiter's word after v1.1.0 («Скіл вже випускає 3.1.1 - то і ми можемо зібрати доробки»,
«Дай попередження - беремо», «Та і 146 теж»). Four issues on `W-7 · v1.1.1` (#7), all `ok`: #145–#148. Pool F-093.

## Global Constraints

As PLAN-W-6's: branch `wave-7` in the main tree, one committer at a time, targeted tests at most `-n 4`, a test fails
first, text in tests through `theme.drawn_width` (the Windows CI runner has no fonts), strings uk/en by the builder and
pl/de through the Advisor, English commits naming the issue; no key on argv or in a log; no live REW, GitHub or `gh`.

## Tasks

1. **#145** every drop-down box reads in the dark theme (finding 143). One app-wide combo-box rule, both themes. *~1 h*
2. **#146** a TCC candidate's row names the candidate's version (finding 150). *~30 min*
3. **#147** a hand tick on a red row warns and moves the row to «Take it as it is» (finding 149). *~30 min*
4. **#148** the capture check reads a sweep over its own range, and a title of the wrong kind is said (finding 146). *~1 h*

## Order and cost

1 → 4 by one builder, then one review (Opus), the Advisor, the Arbiter's VM look, a PR with CI, a candidate
`beta-v1.1.1-rc1` by the `tcc` role, `v1.1.1` by the `release` role (or by `tcc` — a patch; the preflight says). About
3 hours of build and review.
