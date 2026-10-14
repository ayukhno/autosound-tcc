# PLAN W-10 · v1.1.4 — real use and earlier waves' leftovers

The milestone `W-10 · v1.1.4` (#10): 25 issues, all `ok` (the Arbiter, 2026-10-14). The map by group and the
ranking: `docs/W-10-POOL-RANKED.md`. State: `docs/TODO.md` F-102.

**The arm: no engine** (`hub/bin/role tcc --no-SP`, hub H-022). The method is `hub:seam` «Без двигуна»: the
session builds or briefs an Agent; the seats from «Process weight»; `Engine: none` in the PR body. One branch,
`wave-10`, in the main tree; one PR; the full suite runs once, on the PR's CI.

## Order (the Arbiter's «го», 2026-10-14)

| step | group | issues | note |
|---|---|---|---|
| 0 | the Arbiter's retest on the VM, v1.1.3 | #184, #192, #183, #165 | what no longer reproduces is closed |
| 1 | Release tooling | #201, #202 | cheap; makes the release itself cheaper |
| 1‖ | a study, beside everything | #181 | a document, no code |
| 2 | Install and update | #194, #195 | #195 may need a skill ticket for the method's half |
| 3 | AI picks + what step 0 leaves | #196, #182, #165; #184, #192, #183 | |
| 4 | Rounds and the bank | #197, #198, #199, #200 | the skill's halves of #198/#199 ticketed first; #200 waits for the skill's W-10 tag |
| 5 | Window polish, Leftovers | #203, #166, #167, #204, #180; #205–#209 | the Haiku trial |

Code implementers run **one at a time** in the tree (no parallel edits, no tests over a changing file); the study
runs beside them.

## Weight and models (`hub:seam`, with the Arbiter's word of 2026-10-14 on Haiku)

| task | implementer | task review | group |
|---|---|---|---|
| `Risk: high` — #184, #194, #195, #197–#201 | opus · high, test first | opus · high → one fix round → re-review of the fix | silent-failure + test seats (opus · high) → one fix round |
| ordinary — #165, #180, #182, #183, #192, #196, #202, #204–#206, #208, #209 | opus · medium | none | the same two seats |
| mechanical — #166, #167, #203, #207 | **haiku · high** (#166, #203) / **haiku · xhigh** (#167, #207) — a trial | none | the same two seats; their findings on these four counted apart |
| the study #181 | opus · high | — | — |
| the wave | — | — | one final branch review on **Fable** (the wave holds `Risk: high` code) |

**The Haiku trial** (the Arbiter, 2026-10-14: «для механічних задач спробувати Хайку 5.5 … high чи extra high —
треба зрозуміти можливість нової моделі»). It replaces TCC's Sonnet trial for this wave. History: on 2026-10-13
Haiku 5.5 did not make a small mod edit (it stopped at a hub guard and left a plan with an error) — effort unknown
then. Measure per task: done or not, defects the Opus seats find, rework rounds, time; high against xhigh. The
result goes to the ledger below and one line to the hub's H-019.

## The implementer's brief (every spawn)

- Tree `~/dev/autosound/tcc`, branch `wave-10`. Read the issue (`gh issue view N -R ayukhno/autosound-tcc`) — it is
  the brief — and `CLAUDE.md`.
- A red test first for a defect; then the fix; then green.
- **Tests: only the changed files' tests** (`uv run python -m pytest tests/<file> -q`, at most `-n 4`; plain `uv run pytest` fails to spawn on this Mac). No `make check`, no
  whole suite: it runs on the PR's CI, and a local one loads the Mac beside the VM. `uvx ruff@0.12.0 check` on the
  changed files.
- Commit only your own files, by path (never `git add -A` / `commit -a`); the subject in English,
  `<group>: <what> (#N)`, with the session's attribution lines. No push.
- Report: what changed, the commits, the tests run and their result, anything left or doubtful.

## Ledger

| issue | state | implementer | commits | review | note |
|---|---|---|---|---|---|
| #201 | built — task review running | opus · high | 0a01d66, 5e24c74 | opus · high | ship skips the local suite on `ci-green` ok; `make ship VERSION= AT=` dry check; CHANGELOG v1.1.3 corrected; fallback cannot run today (the hub fails ci-green and windows-ran on unreadable CI) |
| #202 | building | opus · medium | | — (ordinary) | |
| #181 | done — the study, `docs/STUDY-W-10-codex-primary.md` | opus · high | (this commit) | — | feasible, L (2–4 days); next: a ≤1-day spike on six points; five questions for the Arbiter (§5) |
